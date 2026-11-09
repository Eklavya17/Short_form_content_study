"""The RQ3 feed engine: picks each next video for feeds A, B and C.

Usage, the same in the simulator and the server:

    state = new_state(feed, clips, interest_ratings, config)
    decision = first_video(state, rng)
    ...viewer watches decision.clip_id...
    decision = choose_next(state, outcome, rng)

Rules (RQ3 Build Plan, Step 2):
    A  random topic whose cooldown counter is 0; likes and watch time are ignored.
    B  p <- p + step * e + like_step * like
    C  p <- p - step * |e| - like_step * like
    B and C draw stay/switch with probability p, clipped to [min, max]; p resets on
    a switch. A switch is forced when the run hits max_run_length or the topic has
    no unseen clips left. On a switch, B and C pick a topic by softmax over topic
    scores, excluding the current topic.

Every Decision records p, the random draw and a state snapshot, so the analysis
can weight stay/switch comparisons by the probability actually used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from random import Random

from rq3.catalog import Clip
from rq3.config import FeedConfig


class Feed(str, Enum):
    A = "A"  # random, cooldown only
    B = "B"  # more of the same
    C = "C"  # move on


class DecisionKind(str, Enum):
    FIRST = "first"
    STAY = "stay"
    SWITCH = "switch"
    FORCED_SWITCH = "forced_switch"


@dataclass(frozen=True)
class Outcome:
    """How the viewer left the video that just played."""

    clip_id: str
    watched_s: float  # total seconds watched, loops included, pauses excluded
    swipe_s: float  # video time when they swiped
    reached_end: bool  # watched to the end at least once
    liked: bool


@dataclass(frozen=True)
class Decision:
    """One choice of next video, with everything the analysis needs."""

    clip_id: str
    topic: str
    kind: DecisionKind
    stay_probability: float | None  # None for feed A and for the first video
    draw: float | None  # the random number compared with stay_probability
    forced_reason: str | None  # "run_cap" or "topic_exhausted" on a forced switch
    run_position: int  # 1 for the first video of a same-topic run
    state_snapshot: dict


@dataclass
class FeedState:
    """Everything the engine remembers within one block. Saved between requests."""

    feed: Feed
    config: FeedConfig
    clips_by_topic: dict[str, list[Clip]]
    topic_scores: dict[str, float]  # starts from the interest survey
    cooldowns: dict[str, int]  # feed A only
    stay_probability: float
    current_topic: str | None = None
    run_length: int = 0
    seen: set[str] = field(default_factory=set)
    watch_history: list[float] = field(default_factory=list)

    def snapshot(self) -> dict:
        """JSON-safe copy of the parts the analysis needs."""
        raise NotImplementedError("Part 1, step 8: decision record")


def interest_to_score(rating: int) -> float:
    """Map a 1-5 interest rating onto the -1..1 topic-score scale (3 -> 0)."""
    if not 1 <= rating <= 5:
        raise ValueError(f"interest rating must be 1-5, got {rating}")
    return (rating - 3) / 2


def new_state(
    feed: Feed,
    clips: list[Clip],
    interest_ratings: dict[str, int],
    config: FeedConfig,
    seen: set[str] | None = None,
) -> FeedState:
    """Start a block. `seen` carries clips shown in earlier blocks (no repeats)."""
    raise NotImplementedError("Part 1, steps 4-6: feeds")


def first_video(state: FeedState, rng: Random) -> Decision:
    """Pick the block's opening video."""
    raise NotImplementedError("Part 1, steps 4-6: feeds")


def choose_next(state: FeedState, outcome: Outcome, rng: Random) -> Decision:
    """Score the video that just ended, update the state and pick the next video."""
    raise NotImplementedError("Part 1, steps 4-8: feeds")


# --- Internal steps, one per rule ----------------------------------------------


def _update_topic_score(state: FeedState, topic: str, score: float, liked: bool) -> None:
    """Move a topic's score toward this video's engagement (all feeds)."""
    raise NotImplementedError("Part 1, step 6: topic choice")


def _update_stay_probability(state: FeedState, score: float, liked: bool) -> None:
    """Apply the B or C update to p and clip it to the configured bounds."""
    raise NotImplementedError("Part 1, step 5: feeds B and C")


def _pick_topic_by_cooldown(state: FeedState, rng: Random) -> str:
    """Feed A: a random topic whose counter is 0, else the lowest counter."""
    raise NotImplementedError("Part 1, step 4: feed A")


def _pick_topic_by_score(state: FeedState, rng: Random) -> str:
    """Feeds B and C: softmax over topic scores, excluding the current topic."""
    raise NotImplementedError("Part 1, step 6: topic choice")


def _pick_clip(state: FeedState, topic: str, rng: Random) -> Clip | None:
    """An unseen clip from `topic`, most similar to the last one; None if exhausted."""
    raise NotImplementedError("Part 1, steps 2 and 7")
