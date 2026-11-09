"""Participant preview: three parts in a balanced order, no repeats, resume by ID."""

import json

import pytest

import rq3.preview as preview
from rq3.demo import app

URL = "http://127.0.0.1:5001"


@pytest.fixture
def client():
    preview.RUNS.clear()
    preview.ORDER_COUNTS.clear()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def post(client, path, body=None):
    return client.post(f"/participant/api/{path}", json=body or {}, base_url=URL)


def begin(client, participant_id="P1", videos_per_part=3, ratings=None):
    response = post(client, "begin", {"participant_id": participant_id, "videos_per_part": videos_per_part, "ratings": ratings or {}})
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def watch_part(client):
    status = post(client, "next-part").get_json()
    assert status["stage"] == "watching"
    shown = []
    while status["stage"] == "watching":
        clip = status["clip"]
        shown.append(clip["id"])
        status = post(client, "swipe", {"watched_s": 5, "swipe_s": 5, "reached_end": False, "liked": False}).get_json()
    return shown, status


def test_page_loads(client):
    page = client.get("/participant", base_url=URL).data
    assert b"Participant ID" in page and b"Food and drink" in page


def test_three_parts_without_repeats(client):
    assert begin(client)["stage"] == "ready"
    shown = []
    for part in range(1, 4):
        ids, status = watch_part(client)
        assert len(ids) == 3
        shown += ids
        assert status["parts_done"] == part
        assert status["stage"] == ("done" if part == 3 else "break")
    assert len(set(shown)) == 9


def test_page_never_sees_topic_or_engine_details(client):
    begin(client)
    clip = post(client, "next-part").get_json()["clip"]
    assert set(clip) == {"id", "title", "url", "duration_s"}


def test_feed_orders_are_balanced_across_participants(client):
    orders = []
    for i in range(12):
        client.post("/participant/api/new", base_url=URL)
        begin(client, participant_id=f"P{i}")
        orders.append(preview.RUNS[f"P{i}"].feed_order)
    assert sorted(set(orders)) == sorted(preview.FEED_ORDERS)
    assert all(orders.count(order) == 2 for order in preview.FEED_ORDERS)


def test_same_id_resumes_instead_of_restarting(client):
    begin(client, "P7")
    first = post(client, "next-part").get_json()["clip"]["id"]
    client.post("/participant/api/new", base_url=URL)
    resumed = begin(client, "P7")
    assert resumed["stage"] == "watching" and resumed["clip"]["id"] == first


def test_export_has_order_feeds_and_outcomes(client):
    begin(client, videos_per_part=2)
    for _ in range(3):
        watch_part(client)
    export = json.loads(client.get("/participant/api/export", base_url=URL).data)
    assert "".join(part["feed"] for part in export["parts"]) == export["feed_order"]
    rows = [video for part in export["parts"] for video in part["videos"]]
    assert len(rows) == 6 and all(row["outcome"]["swipe_rule"] for row in rows)


@pytest.mark.parametrize("body, message", [
    ({"participant_id": "  "}, "participant ID"),
    ({"participant_id": "P1", "videos_per_part": 15}, "Videos per part"),
])
def test_bad_input_is_refused(client, body, message):
    response = post(client, "begin", body)
    assert response.status_code == 400 and message in response.get_json()["error"]
