"""Stored participant flow: parts, no repeats, resuming, balanced orders, and the
guards against double clicks and bad input."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import pytest

from rq3 import storage
from rq3.catalog import load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.scoring import Outcome, judge_swipe, score_outcome
from rq3.study import PARTS, Study, StudyError

CLIPS = load_catalog()


@pytest.fixture
def study():
    return Study(CLIPS, DEFAULT_CONFIG)


def report(status, **changes):
    values = {"clip_id": status.clip.id, "watched_s": 5.0, "swipe_s": 5.0, "reached_end": False, "liked": False}
    return {**values, **changes}


def watch_part(study, db, pid):
    status = study.next_part(db, pid)
    shown = []
    while status.stage == "watching":
        shown.append(status.clip.id)
        status = study.swipe(db, pid, report(status))
    return shown, status


def test_three_parts_without_repeats(study, db):
    assert study.begin(db, "P1", {}, videos_per_part=4).stage == "ready"
    shown = []
    for part in range(1, PARTS + 1):
        ids, status = watch_part(study, db, "P1")
        assert len(ids) == 4
        shown += ids
        assert status.parts_done == part
        assert status.stage == ("done" if part == PARTS else "break")
    assert len(set(shown)) == 12
    assert storage.get_participant(db, "P1")["completed_at"] is not None


def test_parts_follow_the_assigned_feed_order(study, db):
    study.begin(db, "P1", {}, videos_per_part=2)
    for _ in range(PARTS):
        watch_part(study, db, "P1")
    export = study.export(db, "P1")
    assert "".join(part["feed"] for part in export["parts"]) == export["feed_order"]


def test_a_restart_resumes_the_same_video_and_feed_state(study, db):
    study.begin(db, "P1", {"food_drink": 5}, videos_per_part=6)
    status = study.next_part(db, "P1")
    status = study.swipe(db, "P1", report(status, watched_s=30, liked=True))
    restarted = Study(CLIPS, DEFAULT_CONFIG)  # as if the server had restarted
    resumed = restarted.status(db, "P1")
    assert resumed.stage == "watching" and resumed.clip.id == status.clip.id
    after = restarted.swipe(db, "P1", report(resumed))
    assert after.clip.id not in {status.clip.id}


def test_a_repeated_or_stale_swipe_is_ignored(study, db):
    study.begin(db, "P1", {}, videos_per_part=5)
    first = study.next_part(db, "P1")
    second = study.swipe(db, "P1", report(first))
    again = study.swipe(db, "P1", report(first))  # same clip reported twice
    assert again.clip.id == second.clip.id
    rows = storage.impressions_for(db, storage.blocks_for(db, "P1")[0]["id"])
    assert len(rows) == 2 and rows[0]["outcome"] is not None and rows[1]["outcome"] is None


def test_same_id_resumes_instead_of_restarting(study, db):
    study.begin(db, "P1", {}, videos_per_part=3)
    playing = study.next_part(db, "P1")
    again = study.begin(db, "P1", {"gaming": 5}, videos_per_part=9)
    assert again.stage == "watching" and again.clip.id == playing.clip.id
    assert again.videos_per_part == 3


def test_feed_orders_are_balanced_even_when_people_start_at_once(study, database_url):
    def sign_up(i):
        with storage.connect(database_url) as connection:
            study.begin(connection, f"P{i}", {})

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(sign_up, range(12)))
    with storage.connect(database_url) as connection:
        rows = connection.execute("SELECT feed_order FROM rq3_participants").fetchall()
    assert Counter(row["feed_order"] for row in rows) == {order: 2 for order in storage.FEED_ORDERS}


def test_export_recomputes_scores_from_raw_outcomes(study, db):
    study.begin(db, "P1", {}, videos_per_part=2)
    status = study.next_part(db, "P1")
    status = study.swipe(db, "P1", report(status, watched_s=1.0, swipe_s=1.0))
    video = study.export(db, "P1")["parts"][0]["videos"][0]
    assert video["outcome"] == {"watched_s": 1.0, "swipe_s": 1.0, "reached_end": False, "liked": False}
    clip = study.clips_by_id[video["clip_id"]]
    outcome = Outcome(clip.id, **video["outcome"])
    assert video["scored"]["swipe_rule"] == judge_swipe(clip, 1.0, False, DEFAULT_CONFIG).rule.value
    assert video["scored"]["e"] == pytest.approx(score_outcome(clip, outcome, [], DEFAULT_CONFIG), abs=0.001)


@pytest.mark.parametrize("pid, videos, message", [
    ("", None, "Participant ID"),
    ("has space", None, "Participant ID"),
    ("P1", 15, "Videos per part"),
])
def test_bad_input_is_refused(study, db, pid, videos, message):
    with pytest.raises(StudyError, match=message):
        study.begin(db, pid, {}, videos_per_part=videos)


def test_swipe_without_a_playing_part_is_refused(study, db):
    study.begin(db, "P1", {})
    with pytest.raises(StudyError, match="No part is playing"):
        study.swipe(db, "P1", {"clip_id": "x"})


def test_unknown_event_types_are_rejected(db):
    with pytest.raises(ValueError, match="Unknown event type"):
        storage.record_event(db, 1, {"event_type": "scrolled_sideways"})
