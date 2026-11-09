"""Participant preview routes, backed by the database."""

import json

import pytest

from rq3.demo import app

URL = "http://127.0.0.1:5001"


@pytest.fixture
def client(database_url, db):
    app.config.update(TESTING=True, RQ3_DATABASE_URL=database_url)
    with app.test_client() as test_client:
        yield test_client


def post(client, path, body=None):
    return client.post(f"/participant/api/{path}", json=body or {}, base_url=URL)


def begin(client, participant_id="P1", videos_per_part=3):
    response = post(client, "begin", {"participant_id": participant_id, "videos_per_part": videos_per_part})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def watch_part(client):
    status = post(client, "next-part").get_json()
    shown = []
    while status["stage"] == "watching":
        clip = status["clip"]
        shown.append(clip["id"])
        status = post(client, "swipe", {"clip_id": clip["id"], "watched_s": 5, "swipe_s": 5, "reached_end": False, "liked": False}).get_json()
    return shown, status


def test_page_loads(client):
    page = client.get("/participant", base_url=URL).data
    assert b"Participant ID" in page and b"Food and drink" in page


def test_full_run_through_the_routes(client):
    assert begin(client)["stage"] == "ready"
    shown = []
    for _ in range(3):
        ids, status = watch_part(client)
        shown += ids
    assert status["stage"] == "done" and len(set(shown)) == 9


def test_page_never_sees_topic_or_engine_details(client):
    begin(client)
    clip = post(client, "next-part").get_json()["clip"]
    assert set(clip) == {"id", "title", "url", "duration_s"}


def test_status_survives_a_new_browser_session_with_the_same_id(client):
    begin(client, "P7")
    first = post(client, "next-part").get_json()["clip"]["id"]
    post(client, "new")
    assert client.get("/participant/api/status", base_url=URL).get_json()["stage"] == "welcome"
    assert begin(client, "P7")["clip"]["id"] == first


def test_export_downloads_the_participant(client):
    begin(client, videos_per_part=2)
    watch_part(client)
    export = json.loads(client.get("/participant/api/export", base_url=URL).data)
    assert export["participant_id"] == "P1" and len(export["parts"][0]["videos"]) == 2


def test_errors_come_back_as_messages(client):
    response = post(client, "begin", {"participant_id": "  "})
    assert response.status_code == 400 and "Participant ID" in response.get_json()["error"]


def test_participant_link_resumes_a_known_participant(client):
    begin(client, "P5")
    playing = post(client, "next-part").get_json()["clip"]["id"]
    post(client, "new")
    arrived = post(client, "arrive", {"participant_id": "P5"}).get_json()
    assert arrived["stage"] == "watching" and arrived["clip"]["id"] == playing


def test_participant_link_for_a_new_id_starts_at_welcome(client):
    assert post(client, "arrive", {"participant_id": "NEW1"}).get_json()["stage"] == "welcome"


def test_event_batches_are_stored(client):
    begin(client)
    clip = post(client, "next-part").get_json()["clip"]
    events = [{"event_type": "first_frame", "clip_id": clip["id"], "details": {"load_ms": 300}}]
    assert post(client, "events", {"events": events}).get_json()["kept"] == 1


def test_events_without_a_participant_are_ignored(client):
    post(client, "new")
    assert post(client, "events", {"events": [{"event_type": "pause", "clip_id": "x"}]}).get_json()["kept"] == 0
