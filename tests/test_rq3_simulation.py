"""Simulator: viewers behave as programmed, and the summary measures what it claims."""

from random import Random
from statistics import mean

import pytest

from rq3.catalog import load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.feeds import Feed
from rq3.simulation import SimulatedViewer, ViewerType, enlarge_pool, simulate

CATALOG = load_catalog()
CLIP = CATALOG[0]


def average_fraction(viewer: SimulatedViewer, run_position: int, draws: int = 4000) -> float:
    rng = Random(0)
    return mean(
        min(viewer.watch(CLIP, run_position, 3, rng).watched_s / CLIP.duration_s, 1.0) for _ in range(draws)
    )


def test_tiring_viewer_watches_less_later_in_a_run():
    viewer = SimulatedViewer(ViewerType.TIRING)
    assert average_fraction(viewer, 3) < average_fraction(viewer, 1) - 0.1


def test_momentum_viewer_watches_more_later_in_a_run():
    viewer = SimulatedViewer(ViewerType.MOMENTUM)
    assert average_fraction(viewer, 3) > average_fraction(viewer, 1) + 0.1


def test_watching_past_the_end_swipes_during_the_replay():
    viewer = SimulatedViewer(ViewerType.INDIFFERENT, base_watch=1.2, noise=0.0)
    outcome = viewer.watch(CLIP, 1, 3, Random(0))
    assert outcome.reached_end
    assert outcome.swipe_s == pytest.approx(CLIP.duration_s * 0.2)


def test_only_videos_watched_to_the_end_get_liked():
    viewer = SimulatedViewer(ViewerType.INDIFFERENT, base_watch=0.3, noise=0.0, like_rate=1.0)
    assert not viewer.watch(CLIP, 1, 3, Random(0)).liked


def test_simulation_recovers_programmed_tiring_and_keeps_a_without_runs():
    stats = simulate(SimulatedViewer(ViewerType.TIRING), CATALOG, DEFAULT_CONFIG, participants=300, seed=4)
    assert stats[Feed.A].mean_run == 1.0
    assert -0.15 < stats[Feed.B].recovered_effect < -0.05
    assert stats[Feed.B].mean_run > stats[Feed.C].mean_run


def test_enlarged_pool_has_unique_ids_and_same_topics():
    bigger = enlarge_pool(CATALOG, 2)
    assert len(bigger) == 2 * len(CATALOG)
    assert len({clip.id for clip in bigger}) == len(bigger)
    assert {clip.topic for clip in bigger} == {clip.topic for clip in CATALOG}


def test_bigger_pool_cuts_forced_switches():
    viewer = SimulatedViewer(ViewerType.INDIFFERENT)
    small = simulate(viewer, CATALOG, DEFAULT_CONFIG, participants=200, seed=1)[Feed.B]
    large = simulate(viewer, enlarge_pool(CATALOG, 2), DEFAULT_CONFIG, participants=200, seed=1)[Feed.B]
    assert large.topic_forced_rate < small.topic_forced_rate / 3
