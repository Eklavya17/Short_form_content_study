"""Feed engine: feed A's cooldown, the B/C stay-probability equations, forced
switches, no repeats, and saving state between requests."""

import json
from collections import Counter
from random import Random

import pytest

from rq3.catalog import Clip, Stage, StageLabel, Structure, load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.feeds import (
    DecisionKind,
    Feed,
    PoolExhaustedError,
    choose_next,
    first_video,
    new_state,
    restore_state,
)
from rq3.scoring import Outcome

CATALOG = load_catalog()


class FixedDraw(Random):
    """An rng whose random() always returns `value`, so stay/switch draws are known."""

    def __init__(self, value: float, seed: int = 0):
        super().__init__(seed)
        self.value = value

    def random(self) -> float:
        return self.value


def make_pool(topics=("food", "games", "sport"), per_topic=10, duration_s=30.0) -> list[Clip]:
    stages = (
        Stage(StageLabel.HOOK, 0, 3),
        Stage(StageLabel.DEVELOPMENT, 3, 24),
        Stage(StageLabel.PAYOFF, 24, duration_s),
    )
    return [
        Clip(f"{topic}-{i}", f"{topic} {i}", "https://example.com", topic, duration_s, Structure.STORY, stages, ())
        for topic in topics
        for i in range(per_topic)
    ]


def watched_all(clip: Clip, liked: bool = False) -> Outcome:
    return Outcome(clip.id, watched_s=clip.duration_s, swipe_s=1.0, reached_end=True, liked=liked)


def liked_it(clip: Clip) -> Outcome:
    return watched_all(clip, liked=True)


def swiped_in_hook(clip: Clip) -> Outcome:
    return Outcome(clip.id, watched_s=1.0, swipe_s=1.0, reached_end=False, liked=False)


def run_block(feed: Feed, n: int, rng: Random, outcome=watched_all, clips=CATALOG, ratings=None):
    state = new_state(feed, clips, ratings or {}, DEFAULT_CONFIG)
    decisions = [first_video(state, rng)]
    for _ in range(n - 1):
        clip = state.clips[decisions[-1].clip_id]
        decisions.append(choose_next(state, outcome(clip), rng))
    return state, decisions


# --- Feed A --------------------------------------------------------------------------


def test_feed_a_never_repeats_a_topic_within_the_cooldown():
    for seed in range(50):
        _, decisions = run_block(Feed.A, 14, Random(seed))
        topics = [d.topic for d in decisions]
        for i, topic in enumerate(topics):
            assert topic not in topics[max(0, i - DEFAULT_CONFIG.cooldown) : i], (seed, topics)


def test_feed_a_ignores_likes_and_watch_time():
    _, loved = run_block(Feed.A, 12, Random(7), outcome=liked_it)
    _, skipped = run_block(Feed.A, 12, Random(7), outcome=swiped_in_hook)
    assert [d.clip_id for d in loved] == [d.clip_id for d in skipped]


def test_feed_a_always_switches_and_logs_no_p():
    _, decisions = run_block(Feed.A, 10, Random(1))
    assert {d.kind for d in decisions[1:]} == {DecisionKind.SWITCH}
    assert all(d.stay_probability is None and d.draw is None for d in decisions)


# --- Feeds B and C: the two equations -------------------------------------------------


def p_after_first_video(feed: Feed, outcome_for) -> float:
    clips = make_pool()
    state = new_state(feed, clips, {}, DEFAULT_CONFIG)
    rng = FixedDraw(0.99)
    first = first_video(state, rng)
    return choose_next(state, outcome_for(state.clips[first.clip_id]), rng).stay_probability


def test_full_watch_raises_p_in_b_and_lowers_it_in_c():
    # e = (1.0 - 0.5) + 0.2 = 0.7; step 0.3 moves p by 0.21 from B's 0.75 and C's 0.45.
    assert p_after_first_video(Feed.B, watched_all) == pytest.approx(0.9)  # 0.96, capped
    assert p_after_first_video(Feed.C, watched_all) == pytest.approx(0.24)


def test_a_like_pushes_p_to_the_bounds():
    assert p_after_first_video(Feed.B, liked_it) == pytest.approx(0.9)  # 0.75 + 0.21 + 0.25, capped
    assert p_after_first_video(Feed.C, liked_it) == pytest.approx(0.15)  # 0.45 - 0.21 - 0.25, floored


def test_b_and_c_start_runs_from_their_own_p():
    assert new_state(Feed.A, make_pool(), {}, DEFAULT_CONFIG).stay_probability is None
    assert new_state(Feed.B, make_pool(), {}, DEFAULT_CONFIG).stay_probability == 0.75
    assert new_state(Feed.C, make_pool(), {}, DEFAULT_CONFIG).stay_probability == 0.45


def test_an_early_swipe_lowers_b_and_c_by_the_same_amount():
    drop_b = DEFAULT_CONFIG.b_initial_stay_probability - p_after_first_video(Feed.B, swiped_in_hook)
    drop_c = DEFAULT_CONFIG.c_initial_stay_probability - p_after_first_video(Feed.C, swiped_in_hook)
    assert drop_b == pytest.approx(drop_c)
    assert drop_b > 0


def test_draw_below_p_stays_and_above_p_switches_and_resets():
    for draw, expected in [(0.1, DecisionKind.STAY), (0.95, DecisionKind.SWITCH)]:
        state = new_state(Feed.B, make_pool(), {}, DEFAULT_CONFIG)
        rng = FixedDraw(draw)
        first = first_video(state, rng)
        decision = choose_next(state, watched_all(state.clips[first.clip_id]), rng)
        assert decision.kind is expected
        assert (decision.topic == first.topic) == (expected is DecisionKind.STAY)
        if expected is DecisionKind.SWITCH:
            assert state.stay_probability == DEFAULT_CONFIG.b_initial_stay_probability


# --- Forced switches and the pool ------------------------------------------------------


def test_run_cap_forces_a_switch():
    _, decisions = run_block(Feed.B, 8, FixedDraw(0.0), clips=make_pool())
    assert [d.run_position for d in decisions[:6]] == [1, 2, 3, 4, 5, 1]
    assert decisions[5].kind is DecisionKind.FORCED_SWITCH
    assert decisions[5].forced_reason == "run_cap"


def test_exhausted_topic_forces_a_switch():
    _, decisions = run_block(Feed.B, 4, FixedDraw(0.0), clips=make_pool(per_topic=2))
    assert decisions[2].forced_reason == "topic_exhausted"
    assert decisions[2].topic != decisions[1].topic


def test_no_clip_repeats_within_or_across_blocks():
    shown = set()
    for feed in (Feed.A, Feed.B, Feed.C):
        state = new_state(feed, CATALOG, {}, DEFAULT_CONFIG, seen=shown)
        rng = Random(3)
        decisions = [first_video(state, rng)]
        for _ in range(13):
            decisions.append(choose_next(state, watched_all(state.clips[decisions[-1].clip_id]), rng))
        ids = [d.clip_id for d in decisions]
        assert len(set(ids)) == len(ids)
        assert not shown & set(ids)
        shown |= set(ids)
    assert len(shown) == 42


def test_running_out_of_clips_raises():
    with pytest.raises(PoolExhaustedError):
        run_block(Feed.A, 7, Random(0), clips=make_pool(per_topic=2))


# --- Topic choice ---------------------------------------------------------------------


def test_b_and_c_open_on_favourite_topics_more_often():
    ratings = {"food": 5, "games": 1, "sport": 3}
    firsts = Counter(
        first_video(new_state(Feed.B, make_pool(), ratings, DEFAULT_CONFIG), Random(seed)).topic
        for seed in range(400)
    )
    assert firsts["food"] > firsts["sport"] > firsts["games"]


def test_a_like_raises_the_topic_score_in_every_feed():
    for feed in Feed:
        state = new_state(feed, make_pool(), {}, DEFAULT_CONFIG)
        rng = Random(0)
        first = first_video(state, rng)
        choose_next(state, liked_it(state.clips[first.clip_id]), rng)
        assert state.topic_scores[first.topic] > 0


# --- Decisions and saved state ----------------------------------------------------------


def test_decision_snapshot_is_json_and_state_survives_a_round_trip():
    state, decisions = run_block(Feed.C, 5, Random(11))
    json.dumps([d.state_snapshot for d in decisions])  # storable as-is
    restored = restore_state(json.loads(json.dumps(state.snapshot())), CATALOG, DEFAULT_CONFIG)
    assert restored.snapshot() == state.snapshot()

    outcome = watched_all(state.clips[state.current_clip_id])
    assert choose_next(state, outcome, Random(5)) == choose_next(restored, outcome, Random(5))


def test_outcome_must_be_for_the_clip_that_was_playing():
    state = new_state(Feed.B, make_pool(), {}, DEFAULT_CONFIG)
    first_video(state, Random(0))
    elsewhere = Outcome("not-playing", watched_s=5, swipe_s=5, reached_end=False, liked=False)
    with pytest.raises(ValueError):
        choose_next(state, elsewhere, Random(0))
