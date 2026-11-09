"""Measures and comparisons for the RQ3 report (Part 2).

Inputs are the exported CSVs (participants, blocks, impressions, events) plus the
catalog. Structure (story, loops, hybrid) is a covariate everywhere because it is
uneven across topics.
"""

from __future__ import annotations

from typing import Any

from rq3.catalog import Clip


def impression_measures(events: list[dict[str, Any]], clip: Clip) -> dict[str, Any]:
    """Watch time (minus paused, stalled and hidden time), fraction watched,
    replays, swipe stage, whether the payoff was reached, time after it."""
    raise NotImplementedError("Part 2, step 10: analysis")


def attention_by_run_position(impressions: list[dict[str, Any]]) -> dict[str, Any]:
    """Momentum or tiring: fraction watched at run positions 1, 2, 3+, within B and within C."""
    raise NotImplementedError("Part 2, step 10: analysis")


def stay_versus_switch(impressions: list[dict[str, Any]]) -> dict[str, Any]:
    """Next-video attention after stay vs switch draws, weighted by the logged p."""
    raise NotImplementedError("Part 2, step 10: analysis")


def after_like(impressions: list[dict[str, Any]]) -> dict[str, Any]:
    """Next-video attention after a like, feed B vs feed C."""
    raise NotImplementedError("Part 2, step 10: analysis")


def feed_totals(blocks: list[dict[str, Any]], impressions: list[dict[str, Any]]) -> dict[str, Any]:
    """Total watch time, swipes per minute and survey ratings for A, B and C."""
    raise NotImplementedError("Part 2, step 10: analysis")


def manipulation_check(impressions: list[dict[str, Any]]) -> dict[str, Any]:
    """Did the feeds differ as designed? Run lengths and similarity to the previous video."""
    raise NotImplementedError("Part 2, step 10: analysis")
