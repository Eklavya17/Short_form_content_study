"""Score how well one video went: e = (w - w_bar) + g.

    w      fraction of the video watched, capped at 1 (replays are tracked separately)
    w_bar  this viewer's average watch fraction so far in the block
    g      a bonus or penalty for where in the video they swiped

g comes from the first rule that matches, checked in this order:

    1. played to the end at least once              +0.2
    2. during the hook                              -0.4
    3. after the primary payoff started             +0.2
    4. within 1 s after a loop's micro-payoff       +0.1
    5. inside an annotated buildup / setup / development span
                                                    -0.1 / -0.3 / -0.2
    6. in the middle of a loop                      -0.2
    7. in a gap of at most 2 s after a stage: as that stage
    8. nothing annotated at that time               -0.2

Annotated stages (5) are checked before loops (6) because Pause Times often
starts loop 1 at 0:00, over the hook and setup. Story clips never match 4 or 6
(no loops); loop-only clips never match 3 (no primary payoff). Values live in
rq3.config. The like is not part of e: the feed engine applies it separately, so
B and C can treat it in opposite directions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from rq3.catalog import Clip, StageLabel
from rq3.config import FeedConfig


@dataclass(frozen=True)
class Outcome:
    """How the viewer left the video that just played, as the player reports it."""

    clip_id: str
    watched_s: float  # total seconds watched, replays included, pauses excluded
    swipe_s: float  # video time when they swiped
    reached_end: bool  # the video played to its end at least once
    liked: bool


class SwipeRule(str, Enum):
    """Which scoring rule a swipe matched. Also the swipe stage used in analysis."""

    REACHED_END = "reached_end"
    HOOK = "hook"
    AFTER_PAYOFF = "after_payoff"
    AFTER_MICRO_PAYOFF = "after_micro_payoff"
    BUILDUP = "buildup"
    MID_LOOP = "mid_loop"
    SETUP = "setup"
    DEVELOPMENT = "development"
    UNANNOTATED = "unannotated"


# --- The rules, in the order they are checked ---------------------------------------


def classify_swipe(clip: Clip, swipe_s: float, reached_end: bool, config: FeedConfig) -> SwipeRule:
    """The first rule (see module docstring) that matches a swipe at `swipe_s`."""
    if reached_end:
        return SwipeRule.REACHED_END
    if _in_hook(clip, swipe_s):
        return SwipeRule.HOOK
    if _after_primary_payoff(clip, swipe_s, config):
        return SwipeRule.AFTER_PAYOFF
    if _just_after_micro_payoff(clip, swipe_s, config):
        return SwipeRule.AFTER_MICRO_PAYOFF

    rule = _rule_for_stage(_stage_containing(clip, swipe_s))
    if rule is not None:
        return rule
    if _in_loop(clip, swipe_s):
        return SwipeRule.MID_LOOP
    return _rule_for_stage(_stage_before_short_gap(clip, swipe_s, config)) or SwipeRule.UNANNOTATED


_STAGE_RULES = {
    StageLabel.BUILDUP: SwipeRule.BUILDUP,
    # Inside the payoff's grace period the answer is not yet taken in: still buildup.
    StageLabel.PAYOFF: SwipeRule.BUILDUP,
    StageLabel.SETUP: SwipeRule.SETUP,
    StageLabel.DEVELOPMENT: SwipeRule.DEVELOPMENT,
}


def _rule_for_stage(stage: StageLabel | None) -> SwipeRule | None:
    return _STAGE_RULES.get(stage) if stage is not None else None


def _stage_containing(clip: Clip, t: float) -> StageLabel | None:
    """The stage whose annotated span includes `t` (no gap filling)."""
    return next((s.label for s in clip.stages if s.start_s <= t < s.end_s), None)


def _stage_before_short_gap(clip: Clip, t: float, config: FeedConfig) -> StageLabel | None:
    """The stage that ended at most `max_filled_gap_s` before `t`, if any."""
    ended = [s for s in clip.stages if s.end_s <= t]
    if ended and t - ended[-1].end_s <= config.max_filled_gap_s:
        return ended[-1].label
    return None


def _in_hook(clip: Clip, t: float) -> bool:
    return clip.hook_end_s is not None and t < clip.hook_end_s


def _after_primary_payoff(clip: Clip, t: float, config: FeedConfig) -> bool:
    return clip.payoff_s is not None and t >= clip.payoff_s + config.payoff_grace_s


def _just_after_micro_payoff(clip: Clip, t: float, config: FeedConfig) -> bool:
    window = config.micro_payoff_window_s
    return any(loop.end_s <= t <= loop.end_s + window for loop in clip.loops)


def _in_loop(clip: Clip, t: float) -> bool:
    return any(loop.start_s <= t < loop.end_s for loop in clip.loops)


def adjustment_for(rule: SwipeRule, config: FeedConfig) -> float:
    """g for a matched rule."""
    stage = config.stage_adjustment
    return {
        SwipeRule.REACHED_END: stage["after_payoff"],
        SwipeRule.HOOK: stage["hook"],
        SwipeRule.AFTER_PAYOFF: stage["after_payoff"],
        SwipeRule.AFTER_MICRO_PAYOFF: config.after_micro_payoff_adjustment,
        SwipeRule.BUILDUP: stage["buildup"],
        SwipeRule.MID_LOOP: config.mid_loop_adjustment,
        SwipeRule.SETUP: stage["setup"],
        SwipeRule.DEVELOPMENT: stage["development"],
        SwipeRule.UNANNOTATED: config.unannotated_adjustment,
    }[rule]


def swipe_adjustment(clip: Clip, swipe_s: float, reached_end: bool, config: FeedConfig) -> float:
    """g: the bonus or penalty for where in `clip` the viewer swiped."""
    return adjustment_for(classify_swipe(clip, swipe_s, reached_end, config), config)


# --- Putting it together --------------------------------------------------------------


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


def engagement_score(watched: float, average: float, adjustment: float) -> float:
    """e = (w - w_bar) + g. Positive means the video went better than usual."""
    return (watched - average) + adjustment


def score_outcome(clip: Clip, outcome: Outcome, history: list[float], config: FeedConfig) -> float:
    """e for one video. `history` holds the watch fractions of the earlier videos
    in this block, not including this one."""
    if outcome.clip_id != clip.id:
        raise ValueError(f"Outcome is for clip {outcome.clip_id}, not {clip.id}")
    watched = watch_fraction(outcome.watched_s, clip.duration_s)
    adjustment = swipe_adjustment(clip, outcome.swipe_s, outcome.reached_end, config)
    return engagement_score(watched, average_watch(history, config), adjustment)
