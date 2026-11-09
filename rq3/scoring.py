"""Score how well one video went: e = (w - w_bar) + g.

    w      fraction of the video watched, capped at 1 (replays are tracked separately)
    w_bar  this viewer's average watch fraction so far in the block
    g      a bonus or penalty for where in the video they swiped

g depends on the clip's structure:
    story   by codebook stage (hook ... buildup, after payoff)
    loops   by position relative to the loops (mid-loop vs just after a micro-payoff)
    hybrid  loop rules for the loops, story rules for the final buildup and payoff
"""

from __future__ import annotations

from rq3.catalog import Clip
from rq3.config import FeedConfig


def watch_fraction(watched_s: float, duration_s: float) -> float:
    """Fraction of the clip watched, capped at 1 so loops don't inflate it."""
    if duration_s <= 0:
        raise ValueError("duration_s must be positive")
    return min(max(watched_s / duration_s, 0.0), 1.0)


def average_watch(history: list[float], config: FeedConfig) -> float:
    """w_bar: the viewer's mean watch fraction, or the default during warm-up."""
    if len(history) < config.warmup_videos:
        return config.default_average_watch
    return sum(history) / len(history)


def swipe_adjustment(clip: Clip, swipe_s: float, reached_end: bool, config: FeedConfig) -> float:
    """g: the bonus or penalty for where in `clip` the viewer swiped."""
    raise NotImplementedError("Part 1, step 3: scoring")


def engagement_score(watched: float, average: float, adjustment: float) -> float:
    """e = (w - w_bar) + g. Positive means the video went better than usual."""
    return (watched - average) + adjustment
