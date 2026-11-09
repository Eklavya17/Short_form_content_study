"""Checks that hold for the scaffold: modules import, settled decisions are encoded,
and the small helpers that are already implemented behave correctly.

Replace these with per-rule tests as each Part 1 step is built.
"""

import importlib
from pathlib import Path

import pytest

from rq3.catalog import Structure
from rq3.config import DEFAULT_CONFIG
from rq3.feeds import interest_to_score
from rq3.scoring import average_watch, engagement_score, watch_fraction
from rq3.storage import EVENT_TYPES

PLAYER_JS = Path(__file__).resolve().parent.parent / "static" / "rq3" / "player.js"

MODULES = [
    "rq3.config",
    "rq3.catalog",
    "rq3.build_catalog",
    "rq3.scoring",
    "rq3.feeds",
    "rq3.simulation",
    "rq3.storage",
    "rq3.web",
    "rq3.analysis",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_settled_decisions():
    config = DEFAULT_CONFIG
    assert config.engagement_step == 0.3
    assert config.cooldown == 3
    assert config.micro_payoff_window_s == 1.0
    assert list(config.story_adjustment) == [
        "hook",
        "setup",
        "development",
        "buildup",
        "after_payoff",
    ]
    assert config.loop_adjustment["after_micro_payoff"] == 0.1


def test_structure_values_match_catalog_labels():
    assert {s.value for s in Structure} == {
        "terminal_primary",
        "loops_only",
        "hybrid_loops_to_terminal",
    }


def test_watch_fraction_caps_loops_at_one():
    assert watch_fraction(90, 30) == 1.0
    assert watch_fraction(15, 30) == 0.5


def test_average_watch_uses_default_during_warmup():
    assert average_watch([0.9, 0.9], DEFAULT_CONFIG) == 0.5
    assert average_watch([0.2, 0.4, 0.6], DEFAULT_CONFIG) == pytest.approx(0.4)


def test_engagement_score_example_from_plan():
    # Watched all of a story clip with the default average: (1.0 - 0.5) + 0.2
    assert engagement_score(1.0, 0.5, 0.2) == pytest.approx(0.7)


def test_interest_ratings_map_to_minus_one_to_one():
    assert [interest_to_score(r) for r in range(1, 6)] == [-1.0, -0.5, 0.0, 0.5, 1.0]


def test_player_and_server_agree_on_events():
    source = PLAYER_JS.read_text(encoding="utf-8")
    for event in EVENT_TYPES:
        assert f'"{event}"' in source
