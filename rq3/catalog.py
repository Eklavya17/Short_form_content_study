"""Clip metadata the feed engine and the scorer need.

The catalog JSON is produced by rq3.build_catalog from the annotated CSV. Stage
names follow the codebook: hook, setup, development, buildup, payoff. Loop
videos are made of repeated mini-arcs, each ending in a micro-payoff.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

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
    PAYOFF = "payoff"  # always the primary payoff; micro-payoffs are loop ends


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
    stages: tuple[Stage, ...]  # sorted by start time
    loops: tuple[Loop, ...]  # sorted by start time
    faststart: bool | None = None  # MP4 index at the front, so playback starts early
    review: tuple[str, ...] = ()  # problems a person should check; empty when clean

    @property
    def primary_payoff(self) -> Stage | None:
        return next((s for s in self.stages if s.label is StageLabel.PAYOFF), None)

    @property
    def payoff_s(self) -> float | None:
        """When the primary payoff starts; None for loop-only clips."""
        payoff = self.primary_payoff
        return payoff.start_s if payoff else None

    @property
    def hook_end_s(self) -> float | None:
        hook = next((s for s in self.stages if s.label is StageLabel.HOOK), None)
        return hook.end_s if hook else None

    def stage_at(self, video_time_s: float) -> StageLabel | None:
        """The stage playing at `video_time_s`.

        Annotated spans sometimes leave a second or two between stages; a time in
        such a gap belongs to the stage before it. Returns None before the first
        annotated stage or after the clip ends.
        """
        if video_time_s < 0 or video_time_s > self.duration_s:
            return None
        current = None
        for stage in self.stages:
            if stage.start_s > video_time_s:
                break
            current = stage.label
        return current


# --- Reading and writing the catalog JSON ---------------------------------------


def clip_to_dict(clip: Clip) -> dict[str, Any]:
    """Plain-JSON form of a clip, for writing the catalog file."""
    return {
        "id": clip.id,
        "title": clip.title,
        "url": clip.url,
        "topic": clip.topic,
        "duration_s": clip.duration_s,
        "structure": clip.structure.value,
        "stages": [
            {"label": s.label.value, "start_s": s.start_s, "end_s": s.end_s}
            for s in clip.stages
        ],
        "loops": [
            {"index": loop.index, "start_s": loop.start_s, "end_s": loop.end_s}
            for loop in clip.loops
        ],
        "faststart": clip.faststart,
        "review": list(clip.review),
    }


def clip_from_dict(data: dict[str, Any]) -> Clip:
    """Inverse of clip_to_dict. Raises ValueError naming the clip on bad data."""
    clip_id = data.get("id", "<missing id>")
    try:
        return Clip(
            id=data["id"],
            title=data["title"],
            url=data["url"],
            topic=data["topic"],
            duration_s=float(data["duration_s"]),
            structure=Structure(data["structure"]),
            stages=tuple(
                Stage(StageLabel(s["label"]), float(s["start_s"]), float(s["end_s"]))
                for s in data["stages"]
            ),
            loops=tuple(
                Loop(int(lp["index"]), float(lp["start_s"]), float(lp["end_s"]))
                for lp in data["loops"]
            ),
            faststart=data.get("faststart"),
            review=tuple(data.get("review", ())),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"Bad catalog entry for clip {clip_id}: {error}") from error


def load_catalog(path: Path = CATALOG_PATH) -> list[Clip]:
    """Read the catalog JSON written by rq3.build_catalog."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    clips = [clip_from_dict(entry) for entry in payload["clips"]]
    duplicate_ids = [clip_id for clip_id, n in Counter(c.id for c in clips).items() if n > 1]
    if duplicate_ids:
        raise ValueError(f"Duplicate clip ids in catalog: {sorted(duplicate_ids)}")
    return clips


def write_catalog(clips: list[Clip], path: Path = CATALOG_PATH) -> None:
    """Write clips as the catalog JSON (sorted by topic, then id, for stable diffs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(clips, key=lambda clip: (clip.topic, clip.id))
    payload = {"clips": [clip_to_dict(clip) for clip in ordered]}
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def clips_by_topic(clips: list[Clip]) -> dict[str, list[Clip]]:
    """Group clips by topic, keeping catalog order within each topic."""
    grouped: dict[str, list[Clip]] = defaultdict(list)
    for clip in clips:
        grouped[clip.topic].append(clip)
    return dict(grouped)
