"""Swipe scorer: one test per rule, the rule order, and worked examples on real clips."""

from dataclasses import replace

import pytest

from rq3.catalog import Clip, Loop, Stage, StageLabel, Structure, load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.scoring import (
    Outcome,
    SwipeRule,
    classify_swipe,
    score_outcome,
    swipe_adjustment,
)

CONFIG = DEFAULT_CONFIG
CATALOG = {clip.id: clip for clip in load_catalog()}
PYTHON_CATCH = CATALOG["hdjuzIYqTr0"]  # story: hook 0-4, development 4-43, buildup 43-54, payoff 54
GUESS_THE_ANIMAL = CATALOG["rqsRdfdN4uI"]  # hybrid: hook 0-3, loops end 5/15/25/35, payoff 35
BATTLEFIELD = CATALOG["ETbLDhSx1jU"]  # hybrid: setup 3-8, loop 6 ends 47, buildup 47-50 inside loop 7


def story_clip(**changes) -> Clip:
    clip = Clip(
        id="story",
        title="Story",
        url="https://example.com/story.mp4",
        topic="food_drink",
        duration_s=30.0,
        structure=Structure.STORY,
        stages=(
            Stage(StageLabel.HOOK, 0, 3),
            Stage(StageLabel.SETUP, 3, 6),
            Stage(StageLabel.DEVELOPMENT, 6, 18),
            Stage(StageLabel.BUILDUP, 18, 24),
            Stage(StageLabel.PAYOFF, 24, 30),
        ),
        loops=(),
    )
    return replace(clip, **changes)


def loop_clip(**changes) -> Clip:
    clip = Clip(
        id="loops",
        title="Loops",
        url="https://example.com/loops.mp4",
        topic="gaming",
        duration_s=30.0,
        structure=Structure.LOOPS,
        stages=(Stage(StageLabel.HOOK, 0, 2),),
        loops=(Loop(1, 0, 10), Loop(2, 10, 20), Loop(3, 20, 30)),
    )
    return replace(clip, **changes)


def rule(clip: Clip, t: float, reached_end: bool = False, config=CONFIG) -> SwipeRule:
    return classify_swipe(clip, t, reached_end, config)


# --- One test per rule -------------------------------------------------------------


def test_rule_1_reaching_the_end_wins_even_if_they_swipe_in_the_replays_hook():
    assert rule(story_clip(), 1.0, reached_end=True) is SwipeRule.REACHED_END
    assert swipe_adjustment(story_clip(), 1.0, True, CONFIG) == 0.2


def test_rule_2_hook():
    assert rule(story_clip(), 2.9) is SwipeRule.HOOK
    assert rule(loop_clip(), 1.0) is SwipeRule.HOOK  # hook beats loop 1, which starts at 0:00


def test_rule_3_after_primary_payoff_starts():
    assert rule(story_clip(), 24.0) is SwipeRule.AFTER_PAYOFF
    assert rule(story_clip(), 23.9) is SwipeRule.BUILDUP


def test_rule_3_grace_period_keeps_the_start_of_the_payoff_as_buildup():
    graced = replace(CONFIG, payoff_grace_s=1.0)
    assert rule(story_clip(), 24.5, config=graced) is SwipeRule.BUILDUP
    assert rule(story_clip(), 25.0, config=graced) is SwipeRule.AFTER_PAYOFF


def test_rule_4_within_window_after_a_micro_payoff():
    assert rule(loop_clip(), 10.0) is SwipeRule.AFTER_MICRO_PAYOFF
    assert rule(loop_clip(), 11.0) is SwipeRule.AFTER_MICRO_PAYOFF
    assert rule(loop_clip(), 11.1) is SwipeRule.MID_LOOP


def test_rule_4_window_is_a_setting():
    wider = replace(CONFIG, micro_payoff_window_s=2.0)
    assert rule(loop_clip(), 11.5, config=wider) is SwipeRule.AFTER_MICRO_PAYOFF


def test_rule_5_story_stages():
    assert rule(story_clip(), 4.0) is SwipeRule.SETUP
    assert rule(story_clip(), 10.0) is SwipeRule.DEVELOPMENT
    assert rule(story_clip(), 20.0) is SwipeRule.BUILDUP


def test_rule_6_mid_loop():
    assert rule(loop_clip(), 5.0) is SwipeRule.MID_LOOP
    assert swipe_adjustment(loop_clip(), 5.0, False, CONFIG) == -0.2


def test_rule_7_short_gap_belongs_to_the_stage_before():
    gapped = story_clip(stages=(Stage(StageLabel.HOOK, 0, 3), Stage(StageLabel.BUILDUP, 3, 20), Stage(StageLabel.PAYOFF, 21, 30)))
    assert rule(gapped, 20.5) is SwipeRule.BUILDUP


def test_rule_7_long_gap_is_unannotated():
    gapped = story_clip(stages=(Stage(StageLabel.HOOK, 0, 3), Stage(StageLabel.SETUP, 3, 5), Stage(StageLabel.PAYOFF, 25, 30)))
    assert rule(gapped, 6.5) is SwipeRule.SETUP
    assert rule(gapped, 12.0) is SwipeRule.UNANNOTATED


def test_rule_8_nothing_annotated():
    bare = loop_clip(stages=(), loops=(Loop(1, 10, 20),))
    assert rule(bare, 5.0) is SwipeRule.UNANNOTATED
    assert swipe_adjustment(bare, 5.0, False, CONFIG) == -0.2


# --- Rule order on real clips ----------------------------------------------------------


def test_annotated_setup_beats_a_pause_times_loop_that_covers_it():
    assert BATTLEFIELD.loops[0].start_s == 0  # loop 1 covers the hook and setup
    assert rule(BATTLEFIELD, 5.0) is SwipeRule.SETUP


def test_buildup_beats_mid_loop():
    assert rule(BATTLEFIELD, 48.5) is SwipeRule.BUILDUP


def test_micro_payoff_window_beats_buildup():
    assert rule(BATTLEFIELD, 47.5) is SwipeRule.AFTER_MICRO_PAYOFF


def test_primary_payoff_beats_the_micro_payoff_that_starts_it():
    # Guess The Animal's loop 4 ends at 0:35, exactly where the final payoff starts.
    assert rule(GUESS_THE_ANIMAL, 35.5) is SwipeRule.AFTER_PAYOFF


# --- Worked examples (w_bar = 0.5) -------------------------------------------------------


def engagement(clip: Clip, swipe_s: float, reached_end: bool = False) -> float:
    watched = clip.duration_s if reached_end else swipe_s
    outcome = Outcome(clip.id, watched_s=watched, swipe_s=swipe_s, reached_end=reached_end, liked=False)
    return score_outcome(clip, outcome, history=[], config=CONFIG)


@pytest.mark.parametrize(
    "swipe_s, reached_end, expected",
    [
        (2, False, 2 / 60.024 - 0.5 - 0.4),  # hook
        (30, False, 30 / 60.024 - 0.5 - 0.2),  # development
        (50, False, 50 / 60.024 - 0.5 - 0.1),  # buildup
        (56, False, 56 / 60.024 - 0.5 + 0.2),  # after payoff
        (3, True, 1.0 - 0.5 + 0.2),  # watched to the end, swiped in the replay
    ],
)
def test_python_catch_examples(swipe_s, reached_end, expected):
    assert engagement(PYTHON_CATCH, swipe_s, reached_end) == pytest.approx(expected)


@pytest.mark.parametrize(
    "swipe_s, expected",
    [
        (2, 2 / 46.092 - 0.5 - 0.4),  # hook
        (10, 10 / 46.092 - 0.5 - 0.2),  # mid-loop
        (15.5, 15.5 / 46.092 - 0.5 + 0.1),  # just after a micro-payoff
        (40, 40 / 46.092 - 0.5 + 0.2),  # after the final payoff
    ],
)
def test_guess_the_animal_examples(swipe_s, expected):
    assert engagement(GUESS_THE_ANIMAL, swipe_s) == pytest.approx(expected)


# --- score_outcome ---------------------------------------------------------------------


def test_score_uses_the_viewers_own_average_after_warmup():
    clip = story_clip()
    outcome = Outcome(clip.id, watched_s=15, swipe_s=15, reached_end=False, liked=True)
    # w = 0.5, w_bar = 0.2 after three videos, g = development -0.2; the like is ignored.
    assert score_outcome(clip, outcome, [0.2, 0.2, 0.2], CONFIG) == pytest.approx(0.1)


def test_score_rejects_an_outcome_for_another_clip():
    outcome = Outcome("other", watched_s=5, swipe_s=5, reached_end=False, liked=False)
    with pytest.raises(ValueError, match="other"):
        score_outcome(story_clip(), outcome, [], CONFIG)


def test_every_catalog_clip_scores_at_every_second():
    for clip in CATALOG.values():
        for second in range(int(clip.duration_s) + 1):
            g = swipe_adjustment(clip, float(second), False, CONFIG)
            assert -0.4 <= g <= 0.2, (clip.id, second)
