"""Simulated viewers, used to tune FeedConfig before any participant.

Usage:
    python -m rq3.simulation                      # defaults from rq3.config
    python -m rq3.simulation --step 0.45 --videos-per-block 10 --pool-copies 2

Each simulated participant rates every topic, then scrolls three blocks (A, B and
C in a random order) drawn from one shared pool, so no clip repeats, exactly as
in the study. Viewers have a programmed reaction to same-topic runs:

    indifferent  run position does not change how much they watch
    tiring       each extra same-topic video is watched `run_effect` less
    momentum     each extra same-topic video is watched `run_effect` more

Checks from the RQ3 Build Plan, Step 2:
    1. B's average same-topic run is at least one video longer than C's.
    2. The run-position analysis recovers the effect we programmed in.
    3. Fewer than 1 in 20 switches are forced by a topic running out.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field, replace
from enum import Enum
from random import Random
from statistics import mean

from rq3.catalog import Clip, load_catalog
from rq3.config import DEFAULT_CONFIG, FeedConfig
from rq3.feeds import Decision, DecisionKind, Feed, PoolExhaustedError, choose_next, first_video, new_state
from rq3.scoring import Outcome


class ViewerType(str, Enum):
    INDIFFERENT = "indifferent"
    TIRING = "tiring"
    MOMENTUM = "momentum"


@dataclass(frozen=True)
class SimulatedViewer:
    kind: ViewerType
    base_watch: float = 0.55  # typical fraction watched
    noise: float = 0.3  # spread of the fraction watched from video to video
    run_effect: float = 0.1  # change in fraction watched per extra same-topic video
    interest_effect: float = 0.05  # change per interest point above or below 3
    like_rate: float = 0.3  # chance of liking a video they watched to the end

    def watch(self, clip: Clip, run_position: int, interest: int, rng: Random) -> Outcome:
        """How much of `clip` this viewer watches, where they swipe, and whether they like it.

        A fraction above 1 means they watched to the end and swiped during the replay.
        """
        direction = {ViewerType.INDIFFERENT: 0, ViewerType.TIRING: -1, ViewerType.MOMENTUM: 1}[self.kind]
        fraction = (
            self.base_watch
            + direction * self.run_effect * (run_position - 1)
            + self.interest_effect * (interest - 3)
            + rng.gauss(0, self.noise)
        )
        fraction = min(max(fraction, 0.02), 1.5)
        reached_end = fraction >= 1
        swipe_s = clip.duration_s * (fraction - 1 if reached_end else fraction)
        liked = reached_end and rng.random() < self.like_rate
        return Outcome(clip.id, clip.duration_s * fraction, swipe_s, reached_end, liked)


@dataclass
class FeedStats:
    """Totals for one feed and one viewer type, across simulated participants."""

    runs: list[int] = field(default_factory=list)
    switches: int = 0
    forced_by_topic: int = 0
    forced_by_cap: int = 0
    exhausted_blocks: int = 0
    watch_by_run_position: dict[int, list[float]] = field(default_factory=lambda: defaultdict(list))

    @property
    def mean_run(self) -> float:
        return mean(self.runs) if self.runs else 0.0

    @property
    def share_runs_three_plus(self) -> float:
        return sum(r >= 3 for r in self.runs) / len(self.runs) if self.runs else 0.0

    @property
    def topic_forced_rate(self) -> float:
        return self.forced_by_topic / self.switches if self.switches else 0.0

    def mean_watch(self, position: int) -> float | None:
        """Mean fraction watched (capped at 1) at a run position; 3 means 3 and later."""
        values = [
            w for pos, ws in self.watch_by_run_position.items() if min(pos, 3) == position for w in ws
        ]
        return mean(values) if values else None

    @property
    def recovered_effect(self) -> float | None:
        """Estimated change in watch per extra same-topic video (position 2 minus 1)."""
        first, second = self.mean_watch(1), self.mean_watch(2)
        return None if first is None or second is None else second - first


def simulate_participant(
    viewer: SimulatedViewer,
    clips: list[Clip],
    config: FeedConfig,
    rng: Random,
    stats: dict[Feed, FeedStats],
) -> None:
    """One participant: random interest ratings, then blocks A, B, C in a random order."""
    topics = sorted({clip.topic for clip in clips})
    ratings = {topic: rng.randint(1, 5) for topic in topics}
    order = list(Feed)
    rng.shuffle(order)
    seen: set[str] = set()
    for feed in order:
        state = new_state(feed, clips, ratings, config, seen=seen)
        try:
            _simulate_block(state, viewer, ratings, config.videos_per_block, rng, stats[feed])
        except PoolExhaustedError:
            stats[feed].exhausted_blocks += 1
        seen = state.seen


def _simulate_block(state, viewer, ratings, length, rng, stats: FeedStats) -> None:
    decision: Decision = first_video(state, rng)
    run = 1
    for position in range(length):
        clip = state.clips[decision.clip_id]
        outcome = viewer.watch(clip, decision.run_position, ratings[clip.topic], rng)
        stats.watch_by_run_position[decision.run_position].append(min(outcome.watched_s / clip.duration_s, 1.0))
        if position == length - 1:
            break
        decision = choose_next(state, outcome, rng)
        if decision.kind is DecisionKind.STAY:
            run += 1
            continue
        stats.runs.append(run)
        run = 1
        stats.switches += 1
        if decision.forced_reason == "topic_exhausted":
            stats.forced_by_topic += 1
        elif decision.forced_reason == "run_cap":
            stats.forced_by_cap += 1
    stats.runs.append(run)


def simulate(
    viewer: SimulatedViewer,
    clips: list[Clip],
    config: FeedConfig = DEFAULT_CONFIG,
    participants: int = 1000,
    seed: int = 1,
) -> dict[Feed, FeedStats]:
    rng = Random(seed)
    stats = {feed: FeedStats() for feed in Feed}
    for _ in range(participants):
        simulate_participant(viewer, clips, config, rng, stats)
    return stats


def enlarge_pool(clips: list[Clip], copies: int) -> list[Clip]:
    """Pretend each clip exists `copies` times, to see how a bigger pool behaves."""
    return [replace(clip, id=f"{clip.id}~{k}") for clip in clips for k in range(copies)]


# --- Command line -------------------------------------------------------------------


def _fmt(value: float | None, pattern: str = "{:+.2f}") -> str:
    return "  n/a" if value is None else pattern.format(value)


def print_report(results: dict[ViewerType, dict[Feed, FeedStats]], viewer_effect: float) -> None:
    header = f"{'viewer':<12}{'feed':<5}{'avg run':>8}{'runs 3+':>9}{'forced':>8}{'watch@1':>9}{'@2':>7}{'@3+':>7}{'found':>8}"
    print(header)
    print("-" * len(header))
    for kind, by_feed in results.items():
        for feed, s in by_feed.items():
            print(
                f"{kind.value:<12}{feed.value:<5}{s.mean_run:>8.2f}{s.share_runs_three_plus:>9.0%}"
                f"{s.topic_forced_rate:>8.1%}{_fmt(s.mean_watch(1), '{:.2f}'):>9}"
                f"{_fmt(s.mean_watch(2), '{:.2f}'):>7}{_fmt(s.mean_watch(3), '{:.2f}'):>7}"
                f"{_fmt(s.recovered_effect):>8}"
                + (f"  ({s.exhausted_blocks} blocks ran out of clips)" if s.exhausted_blocks else "")
            )
        print()

    indifferent = results[ViewerType.INDIFFERENT]
    gap = indifferent[Feed.B].mean_run - indifferent[Feed.C].mean_run
    worst_forced = max(s.topic_forced_rate for by_feed in results.values() for s in by_feed.values())
    tiring = results[ViewerType.TIRING][Feed.B].recovered_effect
    print("Checks")
    print(f"  1. B's runs longer than C's by >= 1 video:   {gap:+.2f}  {'PASS' if gap >= 1 else 'FAIL'}")
    found = tiring is not None and abs(tiring + viewer_effect) <= viewer_effect / 2
    print(f"  2. Recovers programmed tiring of {-viewer_effect:+.2f}:     {_fmt(tiring)}  {'PASS' if found else 'FAIL'}")
    print(f"  3. Topic-exhausted switches under 5%:        {worst_forced:.1%}  {'PASS' if worst_forced < 0.05 else 'FAIL'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate viewers through feeds A, B and C.")
    parser.add_argument("--participants", type=int, default=1000)
    parser.add_argument("--videos-per-block", type=int, default=DEFAULT_CONFIG.videos_per_block)
    parser.add_argument("--step", type=float, default=DEFAULT_CONFIG.engagement_step, help="B/C engagement step")
    parser.add_argument("--like-step", type=float, default=DEFAULT_CONFIG.like_step)
    parser.add_argument("--reset", type=float, default=DEFAULT_CONFIG.initial_stay_probability, help="p after a switch")
    parser.add_argument("--pool-copies", type=int, default=1, help="pretend each clip exists N times")
    parser.add_argument("--run-effect", type=float, default=0.1, help="programmed tiring/momentum per video")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    config = replace(
        DEFAULT_CONFIG,
        videos_per_block=args.videos_per_block,
        engagement_step=args.step,
        like_step=args.like_step,
        initial_stay_probability=args.reset,
    )
    clips = enlarge_pool(load_catalog(), args.pool_copies)
    print(
        f"{args.participants} participants x 3 blocks of {config.videos_per_block}, "
        f"{len(clips)} clips, step {config.engagement_step}, like step {config.like_step}, "
        f"reset p {config.initial_stay_probability}\n"
    )
    results = {
        kind: simulate(SimulatedViewer(kind, run_effect=args.run_effect), clips, config, args.participants, args.seed)
        for kind in ViewerType
    }
    print_report(results, args.run_effect)


if __name__ == "__main__":
    main()
