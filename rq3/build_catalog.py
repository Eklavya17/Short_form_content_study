"""Build data/rq3_catalog.json from the annotated catalog CSV.

Usage:
    python -m rq3.build_catalog [--csv utils/data_with_cloudflare.csv]

Sources for each hosted clip (rows with a Cloudflare URL):
    id, title, url, topic, structure   CSV columns
    stage times                        Annotation, e.g. "HOOK (0:00-0:04)"
    loop times                         individually timed LOOP spans in the
                                       Annotation, else the Pause Times column
                                       (Query Ranges drops each clip's last loop)
    duration, faststart                the MP4 header on R2 (rq3.media)
    hand-marked times                  data/rq3_manual_fixes.json, applied last

Clips with missing or doubtful times are still written, with the reasons in
their `review` field, and listed at the end of the run.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from rq3.catalog import CATALOG_PATH, Clip, Loop, Stage, StageLabel, Structure, write_catalog
from rq3.media import MediaInfo, probe_mp4

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "utils" / "data_with_cloudflare.csv"
FIXES_PATH = ROOT / "data" / "rq3_manual_fixes.json"

# Tolerances for flagging doubtful annotations, in seconds.
MAX_STAGE_GAP_S = 2.0
MAX_STAGE_OVERLAP_S = 1.0
MAX_LOOP_GAP_S = 1.0
MAX_END_OVERRUN_S = 1.0

# "HOOK (0:00-0:04)", "PAYOFF [primary] (0:54-1:00)", "SETUP (0:04-0:09: ..." (no ")").
# A label must be followed directly by its times, so "PAYOFF [micro]. LOOP 2 (...)"
# does not borrow LOOP 2's times.
STAGE_PATTERN = re.compile(
    r"\b(HOOK|SETUP|DEVELOPMENT|BUILDUP|PAYOFF)\s*(?:\[(\w+)\])?\s*"
    r"\(\s*(\d+:\d+)\s*[-–]\s*(\d+:\d+|end)",
    re.IGNORECASE,
)

# "Loop 1 (0:06-0:11)", "LOOP 2 (0:05–0:10)", "Loop 4 (0:22 - End)", the typo
# "Loop 1 (0:04:0:10)", and blocks such as "LOOPS 4–n (0:24–0:48)".
LOOP_PATTERN = re.compile(
    r"\bLOOPS?\s*(\d+|n)?(\s*[-–]\s*(?:\d+|n))?\s*"
    r"\(\s*(\d+:\d+)\s*[-–:]\s*(\d+:\d+|end)",
    re.IGNORECASE,
)

Probe = Callable[[str], MediaInfo]


# --- Parsing ------------------------------------------------------------------


def parse_timestamp(text: str) -> float | None:
    """Seconds for "1:05" or "0:015"; None for "End"."""
    if text.strip().lower() == "end":
        return None
    minutes, seconds = text.split(":")
    return int(minutes) * 60 + int(seconds)


def parse_stages(annotation: str, duration_s: float) -> tuple[Stage, ...]:
    """Codebook stage spans from an annotation. Micro-payoffs are skipped (they are
    loop ends), and back-to-back spans with the same label are merged."""
    stages: list[Stage] = []
    for label, tag, start, end in STAGE_PATTERN.findall(annotation):
        if label.upper() == "PAYOFF" and tag.lower() == "micro":
            continue
        end_s = parse_timestamp(end)
        stage = Stage(
            StageLabel(label.lower()),
            float(parse_timestamp(start)),
            float(duration_s if end_s is None else end_s),
        )
        if stages and stages[-1].label is stage.label:
            stage = Stage(stage.label, stages[-1].start_s, stage.end_s)
            stages.pop()
        stages.append(stage)
    return tuple(sorted(stages, key=lambda s: s.start_s))


def parse_loop_spans(text: str, duration_s: float) -> list[tuple[float, float, bool]]:
    """(start, end, is_block) for every loop span in free text, in time order.

    A block ("LOOPS 4-n (0:24-0:48)") covers several loops whose individual
    times are unknown.
    """
    spans = []
    for _first, range_part, start, end in LOOP_PATTERN.findall(text):
        end_s = parse_timestamp(end)
        spans.append(
            (
                float(parse_timestamp(start)),
                float(duration_s if end_s is None else end_s),
                bool(range_part),
            )
        )
    return sorted(spans)


def choose_loops(annotation: str, pause_times: str, duration_s: float) -> tuple[tuple[Loop, ...], bool]:
    """Loops numbered in time order, and whether any of them is a block.

    Individually timed LOOP spans in the annotation are preferred: Pause Times
    sometimes disagrees with them (e.g. the bento clip). Otherwise Pause Times is
    used, not Query Ranges, which drops each clip's final loop that runs to End.
    """
    spans = parse_loop_spans(annotation, duration_s)
    if not any(not is_block for *_, is_block in spans):
        spans = parse_loop_spans(pause_times, duration_s)
    loops = tuple(Loop(i, start, end) for i, (start, end, _) in enumerate(spans, start=1))
    return loops, any(is_block for *_, is_block in spans)


def latest_time_mentioned(*texts: str) -> float:
    """The largest m:ss time in the texts; the duration fallback if the MP4 can't be read."""
    times = [parse_timestamp(t) for text in texts for t in re.findall(r"\d+:\d+", text)]
    return float(max((t for t in times if t is not None), default=0))


def video_id(youtube_url: str) -> str:
    return youtube_url.rstrip("/").split("/")[-1]


# --- Checks -------------------------------------------------------------------


def review_reasons(clip: Clip, loop_block: bool = False) -> list[str]:
    """Everything about a clip's times that a person should check."""
    reasons: list[str] = []
    needs_payoff = clip.structure in (Structure.STORY, Structure.HYBRID)
    needs_loops = clip.structure in (Structure.LOOPS, Structure.HYBRID)

    if clip.hook_end_s is None:
        reasons.append("no hook time")
    if needs_payoff and clip.primary_payoff is None:
        reasons.append("no primary payoff time")
    if needs_loops and not clip.loops:
        reasons.append("no loop times")
    if loop_block:
        reasons.append("a loop block has no individual loop times")

    for before, after in zip(clip.stages, clip.stages[1:]):
        overlap = before.end_s - after.start_s
        if overlap > MAX_STAGE_OVERLAP_S:
            reasons.append(f"{overlap:g} s overlap of {before.label.value} and {after.label.value}")

    uncovered = uncovered_spans(clip)
    for start_s, end_s in uncovered:
        reasons.append(f"{start_s:g}-{end_s:g} s is in no stage or loop")

    for before, after in zip(clip.loops, clip.loops[1:]):
        gap = after.start_s - before.end_s
        already_reported = any(start <= before.end_s < end for start, end in uncovered)
        if gap > MAX_LOOP_GAP_S and not already_reported:
            reasons.append(f"{gap:g} s gap after loop {before.index} (loops may be missing)")

    latest_end = max([s.end_s for s in clip.stages] + [lp.end_s for lp in clip.loops], default=0)
    if latest_end > clip.duration_s + MAX_END_OVERRUN_S:
        reasons.append(f"times run to {latest_end:g} s, past the {clip.duration_s:g} s video")
    return reasons


def uncovered_spans(clip: Clip) -> list[tuple[float, float]]:
    """Stretches longer than MAX_STAGE_GAP_S, between the first annotated time and
    the last, that no stage or loop covers."""
    spans = sorted([(s.start_s, s.end_s) for s in clip.stages] + [(lp.start_s, lp.end_s) for lp in clip.loops])
    gaps = []
    covered_to = spans[0][1] if spans else 0.0
    for start_s, end_s in spans[1:]:
        if start_s - covered_to > MAX_STAGE_GAP_S:
            gaps.append((covered_to, start_s))
        covered_to = max(covered_to, end_s)
    return gaps


# --- Hand fixes ---------------------------------------------------------------


def load_fixes(path: Path = FIXES_PATH) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["clips"]


def apply_fix(clip: Clip, fix: dict[str, Any]) -> tuple[Clip, list[str]]:
    """Replace a clip's stages and/or loops with hand-marked ones."""
    stages = clip.stages
    loops = clip.loops
    if "stages" in fix:
        stages = tuple(
            sorted(
                (Stage(StageLabel(s["label"]), float(s["start_s"]), float(s["end_s"])) for s in fix["stages"]),
                key=lambda s: s.start_s,
            )
        )
    if "loops" in fix:
        loops = tuple(
            Loop(i, float(lp["start_s"]), float(lp["end_s"]))
            for i, lp in enumerate(sorted(fix["loops"], key=lambda lp: lp["start_s"]), start=1)
        )
    notes = [] if fix.get("confirmed") else ["hand-marked times not yet confirmed"]
    return replace(clip, stages=stages, loops=loops), notes


# --- Building -----------------------------------------------------------------


def build_clip(row: dict[str, str], probe: Probe) -> tuple[Clip, bool, list[str]]:
    """One clip from a CSV row, plus its loop-block flag and probe problems."""
    problems: list[str] = []
    try:
        media = probe(row["Cloudflare URL"])
    except (OSError, ValueError) as error:
        media = None
        problems.append(f"could not read MP4 header ({error})")

    annotation = row["Annotation"]
    pause_times = row["Pause Times"]
    if media is not None:
        duration_s = media.duration_s
    else:
        duration_s = latest_time_mentioned(annotation, pause_times)
        problems.append("duration taken from the latest annotated time")
    loops, loop_block = choose_loops(annotation, pause_times, duration_s)

    clip = Clip(
        id=video_id(row["URL"]),
        title=row["Title"].strip(),
        url=row["Cloudflare URL"].strip(),
        topic=row["Standardized Topic Category"].strip(),
        duration_s=duration_s,
        structure=Structure(row["Payoff Label"].strip()),
        stages=parse_stages(annotation, duration_s),
        loops=loops,
        faststart=media.faststart if media else None,
    )
    return clip, loop_block, problems


def read_clips(
    csv_path: Path = DEFAULT_CSV,
    probe: Probe = probe_mp4,
    fixes: dict[str, dict[str, Any]] | None = None,
) -> list[Clip]:
    """Every hosted clip in the CSV, with hand fixes applied and review reasons set."""
    fixes = load_fixes() if fixes is None else fixes
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = [row for row in csv.DictReader(stream) if row["Cloudflare URL"].strip()]

    clips = []
    for row in rows:
        clip, loop_block, notes = build_clip(row, probe)
        if clip.id in fixes:
            clip, fix_notes = apply_fix(clip, fixes[clip.id])
            notes += fix_notes
            loop_block = loop_block and "loops" not in fixes[clip.id]
        clips.append(replace(clip, review=tuple(review_reasons(clip, loop_block) + notes)))
    return clips


def print_summary(clips: list[Clip]) -> None:
    topics = Counter(clip.topic for clip in clips)
    structures = Counter(clip.structure.name.lower() for clip in clips)
    print(f"{len(clips)} clips")
    print("  by topic:     " + ", ".join(f"{t} {n}" for t, n in sorted(topics.items())))
    print("  by structure: " + ", ".join(f"{s} {n}" for s, n in sorted(structures.items())))
    slow_start = [clip for clip in clips if clip.faststart is False]
    print(f"  not faststart: {len(slow_start)} (MP4 index at the end; slower first frame)")

    flagged = [clip for clip in clips if clip.review]
    print(f"\n{len(flagged)} clips to review:")
    for clip in flagged:
        print(f"  {clip.id}  {clip.title[:45]}")
        for reason in clip.review:
            print(f"      - {reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the RQ3 clip catalog.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()

    clips = read_clips(args.csv)
    write_catalog(clips, args.out)
    print(f"Wrote {args.out}\n")
    print_summary(clips)


if __name__ == "__main__":
    main()
