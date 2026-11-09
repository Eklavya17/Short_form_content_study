"""Clip metadata the feed engine and the scorer need.

The catalog JSON is produced by rq3.build_catalog from the annotated CSV. Stage
names follow the codebook: hook, setup, development, buildup, payoff. Loop
videos are made of repeated mini-arcs, each ending in a micro-payoff.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "rq3_catalog.json"


class Structure(str, Enum):
    """How a clip's payoffs are arranged (the catalog's payoff label)."""

    STORY = "terminal_primary"  # one arc, one primary payoff
    LOOPS = "loops_only"  # repeated micro-payoffs, no primary payoff
    HYBRID = "hybrid_loops_to_terminal"  # loops, then one primary payoff


class StageLabel(str, Enum):
    """Codebook stage labels."""

    HOOK = "hook"
    SETUP = "setup"
    DEVELOPMENT = "development"
    BUILDUP = "buildup"
    PAYOFF = "payoff"


@dataclass(frozen=True)
class Stage:
    label: StageLabel
    start_s: float
    end_s: float


@dataclass(frozen=True)
class Loop:
    """One repeated mini-arc. Its micro-payoff lands at `end_s`."""

    index: int
    start_s: float
    end_s: float


@dataclass(frozen=True)
class Clip:
    id: str
    title: str
    url: str
    topic: str
    duration_s: float
    structure: Structure
    stages: tuple[Stage, ...]
    loops: tuple[Loop, ...]
    payoff_s: float | None  # start of the primary payoff; None for loop-only clips

    def stage_at(self, video_time_s: float) -> StageLabel | None:
        """Return the stage playing at `video_time_s`, or None if unannotated there."""
        raise NotImplementedError("Part 1, step 1: catalog")


def load_catalog(path: Path = CATALOG_PATH) -> list[Clip]:
    """Read the catalog JSON written by rq3.build_catalog."""
    raise NotImplementedError("Part 1, step 1: catalog")


def clips_by_topic(clips: list[Clip]) -> dict[str, list[Clip]]:
    """Group clips by topic, keeping catalog order within each topic."""
    grouped: dict[str, list[Clip]] = defaultdict(list)
    for clip in clips:
        grouped[clip.topic].append(clip)
    return dict(grouped)


def clip_to_dict(clip: Clip) -> dict:
    """Plain-JSON form of a clip, for writing the catalog file."""
    raise NotImplementedError("Part 1, step 1: catalog")


def write_catalog(clips: list[Clip], path: Path = CATALOG_PATH) -> None:
    """Write clips as the catalog JSON (sorted by topic, then id, for stable diffs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(clips, key=lambda clip: (clip.topic, clip.id))
    payload = {"clips": [clip_to_dict(clip) for clip in ordered]}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
