"""The RQ3 feed engine: picks each next video for feeds A, B and C.

Usage, the same in the simulator and the server:

    state = new_state(Feed.B, clips, interest_ratings, config)
    decision = first_video(state, rng)
    ...viewer watches decision.clip_id...
    decision = choose_next(state, outcome, rng)

The three feeds share everything except two rules:

    feed  stay on the topic?        p after each video                 topic on a switch
    A     never                     (no p)                             random, cooldown 0
    B     random draw against p     p + step * e + like_step * like    by topic score
    C     random draw against p     p - step * |e| - like_step * like  by topic score

e is the engagement score from rq3.scoring. In B and C, p is clipped to
[min, max] and reset after every switch. A switch is forced when a run reaches
max_run_length or the topic has no unseen clips left. Topic scores start from
the interest survey and move with engagement and likes in every feed; only B
and C use them. Every Decision records p, the random draw and a state snapshot,
so the analysis can weight stay/switch comparisons by the chance actually used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from random import Random
from typing import Any

from rq3.catalog import Clip
from rq3.config import FeedConfig
from rq3.scoring import Outcome, score_outcome, watch_fraction


class Feed(str, Enum):
    A = "A"  # random, cooldown only
    B = "B"  # more of the same
    C = "C"  # move on


class DecisionKind(str, Enum):
    FIRST = "first"
    STAY = "stay"
    SWITCH = "switch"
    FORCED_SWITCH = "forced_switch"


class PoolExhaustedError(RuntimeError):
    """Every clip has been shown; the block is longer than the pool allows."""


@dataclass(frozen=True)
class Decision:
    """One choice of next video, with everything the analysis needs."""

    clip_id: str
    topic: str
    kind: DecisionKind
    run_position: int  # 1 for the first video of a same-topic run
    stay_probability: float | None  # p used for the draw; None for feed A and first videos
    draw: float | None  # the random number compared with p
    forced_reason: str | None  # "run_cap" or "topic_exhausted" on a forced switch
    previous_engagement: float | None  # e of the video that just ended
    state_snapshot: dict[str, Any]  # engine state when the choice was made


@dataclass
class FeedState:
    """Everything the engine remembers within one block. Saved between requests."""

    feed: Feed
    config: FeedConfig
    clips: dict[str, Clip]  # the whole pool, by id
    topic_scores: dict[str, float]
    cooldowns: dict[str, int]
    stay_probability: float
    current_clip_id: str | None = None
    run_length: int = 0
    seen: set[str] = field(default_factory=set)  # includes clips from earlier blocks
    watch_history: list[float] = field(default_factory=list)  # this block only

    @property
    def topics(self) -> list[str]:
        return sorted(self.topic_scores)

    @property
    def current_topic(self) -> str | None:
        return self.clips[self.current_clip_id].topic if self.current_clip_id else None

    def snapshot(self) -> dict[str, Any]:
        """JSON-safe copy of the state (config and clips are code and data, not state)."""
        return {
            "feed": self.feed.value,
            "topic_scores": dict(self.topic_scores),
            "cooldowns": dict(self.cooldowns),
            "stay_probability": self.stay_probability,
            "current_clip_id": self.current_clip_id,
            "run_length": self.run_length,
            "seen": sorted(self.seen),
            "watch_history": list(self.watch_history),
        }


def restore_state(snapshot: dict[str, Any], clips: list[Clip], config: FeedConfig) -> FeedState:
    """Rebuild a FeedState saved with FeedState.snapshot()."""
    return FeedState(
        feed=Feed(snapshot["feed"]),
        config=config,
        clips={clip.id: clip for clip in clips},
        topic_scores=dict(snapshot["topic_scores"]),
        cooldowns=dict(snapshot["cooldowns"]),
        stay_probability=snapshot["stay_probability"],
        current_clip_id=snapshot["current_clip_id"],
        run_length=snapshot["run_length"],
        seen=set(snapshot["seen"]),
        watch_history=list(snapshot["watch_history"]),
    )


def interest_to_score(rating: int) -> float:
    """Map a 1-5 interest rating onto the -1..1 topic-score scale (3 -> 0)."""
    if not 1 <= rating <= 5:
        raise ValueError(f"interest rating must be 1-5, got {rating}")
    return (rating - 3) / 2


# --- Public API -----------------------------------------------------------------


def new_state(
    feed: Feed,
    clips: list[Clip],
    interest_ratings: dict[str, int],
    config: FeedConfig,
    seen: set[str] | None = None,
) -> FeedState:
    """Start a block. `seen` carries clips shown in earlier blocks, so none repeat.
    Topics without a rating start neutral (as if rated 3)."""
    topics = sorted({clip.topic for clip in clips})
    return FeedState(
        feed=feed,
        config=config,
        clips={clip.id: clip for clip in clips},
        topic_scores={t: interest_to_score(interest_ratings.get(t, 3)) for t in topics},
        cooldowns={t: 0 for t in topics},
        stay_probability=config.initial_stay_probability,
        seen=set(seen or ()),
    )


def first_video(state: FeedState, rng: Random) -> Decision:
    """Pick the block's opening video. A picks any topic; B and C favour high scores."""
    snapshot = state.snapshot()
    if state.feed is Feed.A:
        topic = _pick_topic_by_cooldown(state, rng)
    else:
        topic = _pick_topic_by_score(state, rng, exclude=None)
    return _play(state, topic, DecisionKind.FIRST, rng, snapshot=snapshot)


def choose_next(state: FeedState, outcome: Outcome, rng: Random) -> Decision:
    """Score the video that just ended, update the state and pick the next video."""
    if state.current_clip_id is None:
        raise ValueError("choose_next called before first_video")
    clip = state.clips[state.current_clip_id]
    engagement = score_outcome(clip, outcome, state.watch_history, state.config)
    state.watch_history.append(watch_fraction(outcome.watched_s, clip.duration_s))
    _update_topic_score(state, clip.topic, engagement, outcome.liked)

    if state.feed is Feed.A:
        snapshot = state.snapshot()
        topic = _pick_topic_by_cooldown(state, rng)
        return _play(state, topic, DecisionKind.SWITCH, rng, snapshot=snapshot, engagement=engagement)

    _update_stay_probability(state, engagement, outcome.liked)
    snapshot = state.snapshot()
    p = state.stay_probability
    draw = rng.random()  # always drawn, so every decision has a logged draw
    forced_reason = _forced_switch_reason(state)

    if forced_reason is None and draw < p:
        kind, topic = DecisionKind.STAY, clip.topic
    else:
        kind = DecisionKind.FORCED_SWITCH if forced_reason else DecisionKind.SWITCH
        topic = _pick_topic_by_score(state, rng, exclude=clip.topic)
        state.stay_probability = state.config.initial_stay_probability
    return _play(
        state, topic, kind, rng,
        snapshot=snapshot, engagement=engagement, p=p, draw=draw, forced_reason=forced_reason,
    )


# --- The rules -------------------------------------------------------------------


def _update_stay_probability(state: FeedState, engagement: float, liked: bool) -> None:
    """The one place B and C differ: a like or a good watch raises p in B, lowers it in C."""
    config = state.config
    like = 1.0 if liked else 0.0
    if state.feed is Feed.B:
        p = state.stay_probability + config.engagement_step * engagement + config.like_step * like
    else:
        p = state.stay_probability - config.engagement_step * abs(engagement) - config.like_step * like
    state.stay_probability = min(max(p, config.min_stay_probability), config.max_stay_probability)


def _update_topic_score(state: FeedState, topic: str, engagement: float, liked: bool) -> None:
    """Move the topic's score toward this video's engagement, plus a bonus for a like."""
    config = state.config
    target = engagement + (config.like_affinity_bonus if liked else 0.0)
    rate = config.affinity_update_rate
    state.topic_scores[topic] = (1 - rate) * state.topic_scores[topic] + rate * target


def _forced_switch_reason(state: FeedState) -> str | None:
    if state.run_length >= state.config.max_run_length:
        return "run_cap"
    if not _unseen_clips(state, state.current_topic):
        return "topic_exhausted"
    return None


def _pick_topic_by_cooldown(state: FeedState, rng: Random) -> str:
    """Feed A: a random topic whose counter is 0, else one with the lowest counter."""
    available = _topics_with_unseen(state)
    lowest = min(state.cooldowns[t] for t in available)
    return rng.choice([t for t in available if state.cooldowns[t] == lowest])


def _pick_topic_by_score(state: FeedState, rng: Random, exclude: str | None) -> str:
    """Feeds B and C: softmax over topic scores, never the topic being left."""
    available = [t for t in _topics_with_unseen(state) if t != exclude] or _topics_with_unseen(state)
    temperature = state.config.topic_temperature
    weights = [math.exp(state.topic_scores[t] / temperature) for t in available]
    return rng.choices(available, weights=weights)[0]


def _topics_with_unseen(state: FeedState) -> list[str]:
    topics = [t for t in state.topics if _unseen_clips(state, t)]
    if not topics:
        raise PoolExhaustedError(f"All {len(state.clips)} clips have been shown")
    return topics


def _unseen_clips(state: FeedState, topic: str | None) -> list[Clip]:
    """Unseen clips in `topic`, in a stable order so a seeded rng is reproducible."""
    return sorted(
        (c for c in state.clips.values() if c.topic == topic and c.id not in state.seen),
        key=lambda c: c.id,
    )


def _pick_clip(state: FeedState, topic: str, rng: Random) -> Clip:
    """A random unseen clip from `topic`. Becomes "most similar to the last clip"
    once VCA similarity exists; until then every clip in a topic counts as similar."""
    return rng.choice(_unseen_clips(state, topic))


def _play(
    state: FeedState,
    topic: str,
    kind: DecisionKind,
    rng: Random,
    *,
    snapshot: dict[str, Any],
    engagement: float | None = None,
    p: float | None = None,
    draw: float | None = None,
    forced_reason: str | None = None,
) -> Decision:
    """Pick a clip from `topic`, record it as playing, and describe the decision."""
    clip = _pick_clip(state, topic, rng)
    state.run_length = state.run_length + 1 if kind is DecisionKind.STAY else 1
    state.current_clip_id = clip.id
    state.seen.add(clip.id)
    for t in state.cooldowns:
        state.cooldowns[t] = max(0, state.cooldowns[t] - 1)
    state.cooldowns[topic] = state.config.cooldown
    return Decision(
        clip_id=clip.id,
        topic=topic,
        kind=kind,
        run_position=state.run_length,
        stay_probability=p,
        draw=draw,
        forced_reason=forced_reason,
        previous_engagement=engagement,
        state_snapshot=snapshot,
    )
