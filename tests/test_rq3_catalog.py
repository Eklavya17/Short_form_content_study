"""Catalog builder: parsing the annotation formats found in the CSV, checks,
hand fixes, and the committed catalog file."""

import csv
import struct
from collections import Counter

import pytest

from rq3.build_catalog import (
    apply_fix,
    choose_loops,
    parse_stages,
    parse_timestamp,
    read_clips,
    review_reasons,
)
from rq3.catalog import Clip, Loop, Stage, StageLabel, Structure, clip_from_dict, clip_to_dict, load_catalog
from rq3.media import MediaInfo, parse_mvhd

PYTHON_CATCH = (
    "HOOK (0:00–0:04): dangerous snake-capture situation. DEVELOPMENT (0:04–0:43): catcher "
    "approaches. BUILDUP (0:43–0:54): secure grip becomes imminent. PAYOFF [primary] (0:54–1:00): "
    "python is fully controlled."
)


def make_clip(structure=Structure.STORY, stages=(), loops=(), duration_s=30.0) -> Clip:
    return Clip(
        id="x",
        title="Test clip",
        url="https://example.com/x.mp4",
        topic="food_drink",
        duration_s=duration_s,
        structure=structure,
        stages=tuple(stages),
        loops=tuple(loops),
    )


# --- Timestamps and stages -------------------------------------------------------


@pytest.mark.parametrize("text, seconds", [("0:07", 7), ("1:05", 65), ("0:015", 15), ("End", None)])
def test_parse_timestamp(text, seconds):
    assert parse_timestamp(text) == seconds


def test_parse_stages_reads_a_story_annotation():
    stages = parse_stages(PYTHON_CATCH, duration_s=60.2)
    assert [(s.label.value, s.start_s, s.end_s) for s in stages] == [
        ("hook", 0, 4),
        ("development", 4, 43),
        ("buildup", 43, 54),
        ("payoff", 54, 60),
    ]


def test_micro_payoff_does_not_borrow_the_next_loops_times():
    annotation = (
        "HOOK (0:00–0:02): premise. LOOP 1 (0:02–0:05): first exchange, ending in a comic "
        "PAYOFF [micro]. LOOP 2 (0:05–0:10): second exchange."
    )
    assert [s.label for s in parse_stages(annotation, 15)] == [StageLabel.HOOK]


def test_back_to_back_spans_with_the_same_label_merge():
    annotation = "DEVELOPMENT (0:08–0:23): stones placed. DEVELOPMENT (0:23–0:25): path arranged."
    assert parse_stages(annotation, 29) == (Stage(StageLabel.DEVELOPMENT, 8, 25),)


def test_missing_closing_parenthesis_still_parses():
    annotation = "SETUP (0:04–0:09: intro to hot ice DEVELOPMENT (0:09–0:20): poured."
    assert [s.label for s in parse_stages(annotation, 33)] == [StageLabel.SETUP, StageLabel.DEVELOPMENT]


# --- Loops -----------------------------------------------------------------------


def test_pause_times_keep_the_final_loop_that_runs_to_end():
    loops, block = choose_loops("HOOK: no times.", "Loop 1 (0:02-0:09); Loop 2 (0:09-0:12); Loop 3 (0:12-End)", 28.0)
    assert loops[-1] == Loop(3, 12, 28.0)
    assert not block


def test_colon_typo_between_loop_times_parses():
    loops, _ = choose_loops("", "Loop 1 (0:04:0:10); Loop 2 (0:10-0:18)", 31.0)
    assert loops[0] == Loop(1, 4, 10)


def test_individually_timed_annotation_loops_win_over_pause_times():
    annotation = "LOOP 1 (0:01–0:14): sandwich. LOOP 2 (0:14–0:28): main. LOOP 3 (0:28–0:36): sides."
    pause_times = "Loop 1 (0:00-0:14); Loop 2 (0:14-0:27); Loop 3 (0:27-0:39); Loop 4 (0:39-End)"
    loops, _ = choose_loops(annotation, pause_times, 47.0)
    assert [(lp.start_s, lp.end_s) for lp in loops] == [(1, 14), (14, 28), (28, 36)]


def test_annotation_loop_block_falls_back_to_pause_times():
    annotation = "LOOPS 1–n (0:06–0:29): each yawn is a micro-payoff."
    loops, block = choose_loops(annotation, "Loop 1 (0:06-0:11); Loop 2 (0:11-End)", 29.0)
    assert len(loops) == 2 and not block


def test_a_loop_block_is_flagged():
    _, block = choose_loops("", "LOOPS 1–n (0:07–1:00): each count is tested", 68.0)
    assert block


# --- Checks and fixes --------------------------------------------------------------


def test_story_clip_without_payoff_is_flagged():
    clip = make_clip(stages=[Stage(StageLabel.HOOK, 0, 3), Stage(StageLabel.DEVELOPMENT, 3, 30)])
    assert "no primary payoff time" in review_reasons(clip)


def test_complete_story_clip_has_nothing_to_review():
    clip = make_clip(duration_s=60.2, stages=parse_stages(PYTHON_CATCH, 60.2))
    assert review_reasons(clip) == []


def test_uncovered_stretch_is_flagged():
    clip = make_clip(stages=[Stage(StageLabel.HOOK, 0, 4), Stage(StageLabel.PAYOFF, 12, 30)])
    assert "4-12 s is in no stage or loop" in review_reasons(clip)


def test_fix_replaces_stages_and_is_flagged_until_confirmed():
    clip = make_clip(structure=Structure.LOOPS, loops=[Loop(1, 0, 30)])
    fix = {"confirmed": False, "stages": [{"label": "hook", "start_s": 0, "end_s": 3}]}
    fixed, notes = apply_fix(clip, fix)
    assert fixed.hook_end_s == 3
    assert notes == ["hand-marked times not yet confirmed"]
    assert apply_fix(clip, {**fix, "confirmed": True})[1] == []


def test_read_clips_end_to_end(tmp_path):
    csv_path = tmp_path / "catalog.csv"
    fields = [
        "URL", "Title", "Annotation", "Pause Times", "Payoff Label",
        "Standardized Topic Category", "Cloudflare URL",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "URL": "https://www.youtube.com/shorts/hdjuzIYqTr0", "Title": "INSANE PYTHON CATCH",
            "Annotation": PYTHON_CATCH, "Pause Times": "", "Payoff Label": "terminal_primary",
            "Standardized Topic Category": "animals_nature", "Cloudflare URL": "https://r2/python.mp4",
        })
        writer.writerow({
            "URL": "https://www.youtube.com/shorts/unhosted", "Title": "Not hosted",
            "Annotation": "", "Pause Times": "", "Payoff Label": "loops_only",
            "Standardized Topic Category": "gaming", "Cloudflare URL": "",
        })

    clips = read_clips(csv_path, probe=lambda url: MediaInfo(60.2, True), fixes={})
    assert len(clips) == 1
    clip = clips[0]
    assert (clip.id, clip.topic, clip.duration_s, clip.faststart) == ("hdjuzIYqTr0", "animals_nature", 60.2, True)
    assert clip.payoff_s == 54
    assert clip.review == ()


def test_unreadable_mp4_falls_back_to_annotated_duration(tmp_path):
    csv_path = tmp_path / "catalog.csv"
    csv_path.write_text(
        "URL,Title,Annotation,Pause Times,Payoff Label,Standardized Topic Category,Cloudflare URL\n"
        f'https://y/shorts/a,A,"{PYTHON_CATCH}",,terminal_primary,gaming,https://r2/a.mp4\n',
        encoding="utf-8",
    )

    def failing_probe(url):
        raise OSError("timed out")

    clip = read_clips(csv_path, probe=failing_probe, fixes={})[0]
    assert clip.duration_s == 60
    assert any("could not read MP4 header" in reason for reason in clip.review)


# --- Clip model ----------------------------------------------------------------


def test_stage_at_assigns_short_gaps_to_the_stage_before():
    clip = make_clip(stages=[Stage(StageLabel.BUILDUP, 20, 28), Stage(StageLabel.PAYOFF, 29, 31)], duration_s=31)
    assert clip.stage_at(28.5) is StageLabel.BUILDUP
    assert clip.stage_at(29) is StageLabel.PAYOFF
    assert clip.stage_at(10) is None  # before the first annotated stage
    assert clip.stage_at(40) is None  # after the clip


def test_clip_round_trips_through_json_form():
    clip = make_clip(structure=Structure.HYBRID, stages=[Stage(StageLabel.HOOK, 0, 2)], loops=[Loop(1, 2, 9)])
    assert clip_from_dict(clip_to_dict(clip)) == clip


def test_bad_catalog_entry_names_the_clip():
    with pytest.raises(ValueError, match="clip abc"):
        clip_from_dict({"id": "abc", "structure": "not_a_structure"})


# --- MP4 header ------------------------------------------------------------------


def test_parse_mvhd_version_0():
    body = bytes([0, 0, 0, 0]) + struct.pack(">IIII", 0, 0, 1000, 31_500)
    data = struct.pack(">I4s", 8 + len(body), b"mvhd") + body
    assert parse_mvhd(data) == 31.5


def test_parse_mvhd_version_1():
    body = bytes([1, 0, 0, 0]) + struct.pack(">QQIQ", 0, 0, 600, 27_000)
    data = struct.pack(">I4s", 8 + len(body), b"mvhd") + body
    assert parse_mvhd(data) == 45.0


# --- The committed catalog ---------------------------------------------------------


def test_committed_catalog_has_all_44_hosted_clips():
    clips = load_catalog()
    assert len(clips) == 44
    assert len({clip.topic for clip in clips}) == 8
    assert Counter(clip.structure for clip in clips) == {
        Structure.STORY: 17,
        Structure.LOOPS: 14,
        Structure.HYBRID: 13,
    }
    assert all(clip.duration_s > 0 for clip in clips)
