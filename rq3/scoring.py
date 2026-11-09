"""Score how well one video went: e = (w - w_bar) + g.

    w      fraction of the video watched, capped at 1 (replays are tracked separately)
    w_bar  this viewer's average watch fraction so far in the block
    g      a bonus or penalty for where in the video they swiped

g comes from the first rule that matches, checked in this order:

    1. played to the end at least once              +0.3
    2. during the hook                              -0.3
    3. after the primary payoff started             +0.3
    4. within 1 s after a loop's micro-payoff       +0.1 after loop 1, rising to +0.3
                                                    after the last loop
    5. inside an annotated buildup / setup / development span
                                                     0.0 / -0.2 / -0.1
    6. in the middle of a loop                      -0.1 in loop 1, rising to +0.1
                                                    in the last loop
    7. in a gap of at most 2 s after a stage: as that stage
    8. nothing annotated at that time               -0.1

The values are centred so an ordinary video scores about 0. Loop rewards grow
with each loop: once a viewer has seen micro-payoffs, leaving mid-loop is less of
a rejection, and leaving right after a later payoff counts as more satisfied.
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


@dataclass(frozen=True)
class SwipeVerdict:
    """The rule a swipe matched, its g, and the loop involved (rules 4 and 6)."""

    rule: SwipeRule
    g: float
    loop_index: int | None = None


def judge_swipe(clip: Clip, swipe_s: float, reached_end: bool, config: FeedConfig) -> SwipeVerdict:
    """The first rule (see module docstring) that matches a swipe at `swipe_s`."""
    stage_g = config.stage_adjustment
    if reached_end:
        return SwipeVerdict(SwipeRule.REACHED_END, stage_g["after_payoff"])
    if _in_hook(clip, swipe_s):
        return SwipeVerdict(SwipeRule.HOOK, stage_g["hook"])
    if _after_primary_payoff(clip, swipe_s, config):
        return SwipeVerdict(SwipeRule.AFTER_PAYOFF, stage_g["after_payoff"])

    payoff_loop = _loop_just_paid_off(clip, swipe_s, config)
    if payoff_loop is not None:
        g = _along_loops(clip, payoff_loop, config.micro_payoff_adjustment_first, config.micro_payoff_adjustment_last)
        return SwipeVerdict(SwipeRule.AFTER_MICRO_PAYOFF, g, payoff_loop)

    rule = _rule_for_stage(_stage_containing(clip, swipe_s))
    if rule is not None:
        return SwipeVerdict(rule, stage_g[rule.value])

    current_loop = _loop_playing(clip, swipe_s)
    if current_loop is not None:
        g = _along_loops(clip, current_loop, config.mid_loop_adjustment_first, config.mid_loop_adjustment_last)
        return SwipeVerdict(SwipeRule.MID_LOOP, g, current_loop)

    rule = _rule_for_stage(_stage_before_short_gap(clip, swipe_s, config))
    if rule is not None:
        return SwipeVerdict(rule, stage_g[rule.value])
    return SwipeVerdict(SwipeRule.UNANNOTATED, config.unannotated_adjustment)


def classify_swipe(clip: Clip, swipe_s: float, reached_end: bool, config: FeedConfig) -> SwipeRule:
    """Which rule a swipe matched. Also the swipe stage used in analysis."""
    return judge_swipe(clip, swipe_s, reached_end, config).rule


def swipe_adjustment(clip: Clip, swipe_s: float, reached_end: bool, config: FeedConfig) -> float:
    """g: the bonus or penalty for where in `clip` the viewer swiped."""
    return judge_swipe(clip, swipe_s, reached_end, config).g


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


def _loop_just_paid_off(clip: Clip, t: float, config: FeedConfig) -> int | None:
    """Index of the latest loop whose micro-payoff landed within the window before `t`."""
    window = config.micro_payoff_window_s
    matches = [loop.index for loop in clip.loops if loop.end_s <= t <= loop.end_s + window]
    return matches[-1] if matches else None


def _loop_playing(clip: Clip, t: float) -> int | None:
    """Index of the latest-starting loop that contains `t`."""
    matches = [loop.index for loop in clip.loops if loop.start_s <= t < loop.end_s]
    return matches[-1] if matches else None


def _along_loops(clip: Clip, loop_index: int, first: float, last: float) -> float:
    """Interpolate from `first` (loop 1) to `last` (the final loop)."""
    loops = len(clip.loops)
    progress = (loop_index - 1) / (loops - 1) if loops > 1 else 0.0
    return round(first + (last - first) * progress, 4)


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
