"""Participant links (?pid=), the hand-off to the Qualtrics questionnaire, and the
/finished return page. Runs against a throwaway local Postgres:

    pip install pytest pixeltable-pgserver
    pytest -q
"""

import json
import os
import tempfile

import pytest

pgserver = pytest.importorskip("pixeltable_pgserver")

_DATA_DIR = tempfile.mkdtemp(prefix="rq12-test-db-")
_SERVER = pgserver.get_server(_DATA_DIR, cleanup_mode="stop")
os.environ["DATABASE_URL"] = _SERVER.get_uri()

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

import app as study_app  # noqa: E402
from db import SCHEMA_STATEMENTS  # noqa: E402

SURVEY = "https://example.qualtrics.com/jfe/form/SV_test"


def raw_db():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, autocommit=True)


@pytest.fixture(autouse=True)
def clean_db():
    with raw_db() as db:
        for statement in SCHEMA_STATEMENTS:
            db.execute(statement)
        db.execute("TRUNCATE TABLE events, responses, trials, sessions RESTART IDENTITY CASCADE")
    yield


@pytest.fixture
def client():
    study_app.app.config.update(TESTING=True, STUDY_SURVEY_URL=SURVEY)
    with study_app.app.test_client() as test_client:
        yield test_client
    study_app.app.config.pop("STUDY_SURVEY_URL", None)


def session_row(pid):
    with raw_db() as db:
        return db.execute("SELECT * FROM sessions WHERE id = %s", (pid,)).fetchone()


def finish_all_videos(pid):
    with raw_db() as db:
        row = db.execute("SELECT trial_order_json FROM sessions WHERE id = %s", (pid,)).fetchone()
        db.execute(
            "UPDATE sessions SET current_position = %s WHERE id = %s",
            (len(json.loads(row["trial_order_json"])), pid),
        )


def test_participant_link_names_the_session(client):
    assert client.get("/?pid=P001").status_code == 200
    assert session_row("P001") is not None
    assert client.get("/api/trial/current").get_json()["complete"] is False


def test_the_same_link_resumes_on_another_browser(client):
    client.get("/?pid=P001")
    order = session_row("P001")["trial_order_json"]
    with study_app.app.test_client() as other_browser:
        other_browser.get("/?pid=P001")
    assert session_row("P001")["trial_order_json"] == order
    with raw_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 1


def test_a_bad_pid_falls_back_to_a_random_session(client):
    client.get("/?pid=has space")
    with raw_db() as db:
        rows = db.execute("SELECT id FROM sessions").fetchall()
    assert len(rows) == 1 and rows[0]["id"] != "has space"


def test_no_link_still_gets_a_random_session(client):
    client.get("/")
    with raw_db() as db:
        assert db.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()["n"] == 1


def test_questionnaire_waits_until_every_video_is_watched(client):
    client.get("/?pid=P001")
    response = client.get("/questionnaire")
    assert response.status_code == 302 and response.location.endswith("/")


def test_round_trip_through_the_questionnaire(client):
    client.get("/?pid=P001")
    finish_all_videos("P001")

    status = client.get("/api/trial/current").get_json()
    assert status == {"complete": True, "questionnaire": True, "questionnaire_done": False}
    assert session_row("P001")["completed_at"] is not None

    out = client.get("/questionnaire")
    assert out.status_code == 302 and out.location == f"{SURVEY}?pid=P001&study=rq1-rq2"
    assert session_row("P001")["questionnaire_sent_at"] is not None

    with study_app.app.test_client() as returning_browser:  # the link works in any browser
        back = returning_browser.get("/finished?pid=P001&rid=R_first")
        assert back.status_code == 302 and back.location.endswith("/")
        assert returning_browser.get("/api/trial/current").get_json()["questionnaire_done"] is True

    client.get("/finished?pid=P001&rid=R_second")  # a second click changes nothing
    row = session_row("P001")
    assert row["questionnaire_done_at"] is not None and row["questionnaire_response_id"] == "R_first"


def test_finished_for_an_unknown_or_unfinished_participant_is_refused(client):
    client.get("/?pid=P001")
    for pid in ("P001", "NOBODY", ""):
        response = client.get(f"/finished?pid={pid}&rid=R_x")
        assert response.status_code == 400 and b"contact the study team" in response.data


def test_without_a_survey_link_the_study_ends_as_before(client):
    study_app.app.config["STUDY_SURVEY_URL"] = ""
    client.get("/?pid=P001")
    finish_all_videos("P001")
    assert client.get("/api/trial/current").get_json()["questionnaire"] is False
    assert client.get("/questionnaire").location.endswith("/")
