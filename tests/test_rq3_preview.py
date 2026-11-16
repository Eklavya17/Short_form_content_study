"""Participant preview routes, backed by the database."""

import json

import pytest

from rq3.demo import app

URL = "http://127.0.0.1:5001"


@pytest.fixture
def client(database_url, db):
    app.config.update(TESTING=True, RQ3_DATABASE_URL=database_url, RQ3_TESTING_TOOLS="1")
    with app.test_client() as test_client:
        yield test_client


def post(client, path, body=None):
    return client.post(f"/participant/api/{path}", json=body or {}, base_url=URL)


def begin(client, participant_id="P1", videos_per_part=3):
    response = post(client, "begin", {"participant_id": participant_id, "videos_per_part": videos_per_part, "consented": True})
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
    for part in range(1, 4):
        ids, status = watch_part(client)
        shown += ids
        assert status["stage"] == "survey" and status["survey_part"] == part
        answers = {"enjoyment": 4, "repetition": 2, "continuation": 5}
        status = post(client, "survey", {"part": part, "answers": answers}).get_json()
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


def test_participants_never_see_the_testing_tools(client):
    app.config["RQ3_TESTING_TOOLS"] = ""
    page = client.get("/participant", base_url=URL).data
    assert b"Testing" not in page and b"videos-per-part" not in page and b"new-button" not in page
    status = begin(client, "P8", videos_per_part=1)  # a tampered request is ignored
    assert status["videos_per_part"] != 1
    assert client.get("/participant/api/export", base_url=URL).status_code == 404


def joined_pid(client):
    response = client.get("/participant/join", base_url=URL)
    assert response.status_code == 302
    return response.location.split("pid=")[1]


def test_group_link_gives_each_browser_its_own_id(client):
    first = joined_pid(client)
    assert first == joined_pid(client)  # reopening in the same browser keeps the ID
    with app.test_client() as other_browser:
        assert joined_pid(other_browser) != first
    assert post(client, "arrive", {"participant_id": first}).get_json()["stage"] == "welcome"


def test_group_link_resumes_someone_who_started(client):
    begin(client, "P7")
    assert joined_pid(client) == "P7"


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


# --- The external (Qualtrics) questionnaire -----------------------------------------------

SURVEY = "https://example.qualtrics.com/jfe/form/SV_test"


def finish_all_parts(client):
    begin(client, videos_per_part=1)
    for part in range(1, 4):
        watch_part(client)
        status = post(client, "survey", {"part": part, "answers": {"enjoyment": 3, "repetition": 3, "continuation": 3}}).get_json()
    return status


@pytest.fixture
def survey_on():
    app.config["RQ3_SURVEY_URL"] = SURVEY
    yield
    app.config.pop("RQ3_SURVEY_URL")


def test_page_turns_the_questionnaire_on_only_when_configured(client, survey_on):
    assert b'data-questionnaire="on"' in client.get("/participant", base_url=URL).data
    app.config["RQ3_SURVEY_URL"] = ""
    assert b'data-questionnaire="off"' in client.get("/participant", base_url=URL).data


def test_round_trip_through_the_questionnaire(client, survey_on):
    done = finish_all_parts(client)
    assert done["stage"] == "done" and done["questionnaire_done"] is False

    out = client.get("/participant/questionnaire", base_url=URL)
    assert out.status_code == 302 and out.location == f"{SURVEY}?pid=P1&study=rq3"

    post(client, "new")  # coming back works even in a fresh browser session
    back = client.get("/participant/finished?pid=P1&rid=R_abc", base_url=URL)
    assert back.status_code == 302 and back.location.endswith("/participant?pid=P1")
    assert client.get("/participant/api/status", base_url=URL).get_json()["questionnaire_done"] is True


def test_questionnaire_before_finishing_goes_back_to_the_study(client, survey_on):
    begin(client)
    out = client.get("/participant/questionnaire", base_url=URL)
    assert out.status_code == 302 and out.location.endswith("/participant")


def test_unknown_return_shows_a_message(client):
    response = client.get("/participant/finished?pid=NOBODY", base_url=URL)
    assert response.status_code == 400 and b"contact the study team" in response.data
