"""Simulated viewers, used to tune FeedConfig before any participant.

Usage:
    python -m rq3.simulation [--blocks 2000] [--videos-per-block 12] [--seed 1]

Checks from the RQ3 Build Plan, Step 2:
    1. B's average same-topic run is at least one video longer than C's.
    2. The analysis recovers a tiring effect we program into the viewer.
    3. Fewer than 1 in 20 switches are forced by a topic running out.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from enum import Enum
from random import Random

from rq3.catalog import Clip
from rq3.config import DEFAULT_CONFIG, FeedConfig
from rq3.feeds import Decision, Feed
from rq3.scoring import Outcome


class ViewerType(str, Enum):
    INDIFFERENT = "indifferent"  # same-topic runs don't change attention
    TIRING = "tiring"  # each extra same-topic video is watched less
    MOMENTUM = "momentum"  # each extra same-topic video is watched more


@dataclass(frozen=True)
class SimulatedViewer:
    kind: ViewerType
    base_watch: float = 0.5  # typical fraction watched
    run_effect: float = 0.1  # change in watch fraction per extra same-topic video
    like_rate: float = 0.1  # chance of liking a well-watched video

    def watch(self, clip: Clip, run_position: int, rng: Random) -> Outcome:
        """Decide how long this viewer watches `clip` and whether they like it."""
        raise NotImplementedError("Part 1, step 9: simulator")


@dataclass(frozen=True)
class BlockResult:
    feed: Feed
    decisions: list[Decision]
    outcomes: list[Outcome]


@dataclass(frozen=True)
class Summary:
    mean_run_length: float
    share_runs_three_plus: float
    forced_switch_rate: float


def simulate_block(
    feed: Feed,
    viewer: SimulatedViewer,
    clips: list[Clip],
    config: FeedConfig,
    rng: Random,
) -> BlockResult:
    """Run one viewer through one block of `feed`."""
    raise NotImplementedError("Part 1, step 9: simulator")


def summarize(results: list[BlockResult]) -> Summary:
    """Run-length and forced-switch statistics across blocks."""
    raise NotImplementedError("Part 1, step 9: simulator")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate viewers through feeds A, B and C.")
    parser.add_argument("--blocks", type=int, default=2000)
    parser.add_argument("--videos-per-block", type=int, default=DEFAULT_CONFIG.videos_per_block)
    parser.add_argument("--seed", type=int, default=1)
    parser.parse_args()
    raise NotImplementedError("Part 1, step 9: simulator")


if __name__ == "__main__":
    main()
