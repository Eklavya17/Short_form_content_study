"""Every tunable number for the RQ3 feeds.

Values are the starting points recorded in the RQ3 Build Plan. They are tuned in
the simulator (rq3.simulation), so other modules must read them from a
FeedConfig instead of hard-coding them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


def _frozen(values: dict[str, float]) -> Mapping[str, float]:
    return MappingProxyType(values)


@dataclass(frozen=True)
class FeedConfig:
    # --- Engagement score: e = (w - w_bar) + g --------------------------------
    # w_bar (the viewer's average watch fraction) is undefined at first, so this
    # default is used until the viewer has finished `warmup_videos` videos.
    default_average_watch: float = 0.5
    warmup_videos: int = 3

    # g by the codebook stage the viewer swiped in. Used for every structure:
    # loop clips have hooks, setups and (hybrids) buildups and payoffs too.
    stage_adjustment: Mapping[str, float] = field(
        default_factory=lambda: _frozen(
            {
                "hook": -0.4,
                "setup": -0.3,
                "development": -0.2,
                "buildup": -0.1,
                "after_payoff": 0.2,  # also used when the video was watched to the end
            }
        )
    )

    # g inside the loops of loop and hybrid clips.
    mid_loop_adjustment: float = -0.2
    after_micro_payoff_adjustment: float = 0.1
    # A swipe this soon after a loop's micro-payoff counts as "left satisfied".
    micro_payoff_window_s: float = 1.0

    # The primary payoff counts as seen this long after it starts (0 = at its start).
    payoff_grace_s: float = 0.0
    # A swipe in a gap this short between annotated stages counts as the stage
    # before it; in a longer gap, or where nothing is annotated, it is unannotated.
    max_filled_gap_s: float = 2.0
    unannotated_adjustment: float = -0.2

    # --- Stay probability p (feeds B and C) ------------------------------------
    # p at the start of every same-topic run (the value it resets to on a switch).
    # B leans toward staying and C toward switching; with a shared 0.6 the
    # simulator found B's runs only ~0.4 videos longer than C's, with these ~1.
    b_initial_stay_probability: float = 0.75
    c_initial_stay_probability: float = 0.45
    min_stay_probability: float = 0.15
    max_stay_probability: float = 0.9
    engagement_step: float = 0.3  # how far one video's score moves p
    like_step: float = 0.25  # how far a like moves p (up in B, down in C)
    max_run_length: int = 5  # same-topic videos in a row before a forced switch

    # --- Topic choice when B or C switches --------------------------------------
    affinity_update_rate: float = 0.3  # weight of the newest video in a topic's score
    like_affinity_bonus: float = 0.3  # a like raises the topic's score in every feed
    topic_temperature: float = 0.5  # lower = favourite topics chosen more often

    # --- Feed A -----------------------------------------------------------------
    cooldown: int = 3  # videos before a played topic can return

    # --- Session ----------------------------------------------------------------
    videos_per_block: int = 12  # at most 14 while the pool is 44 clips


DEFAULT_CONFIG = FeedConfig()
