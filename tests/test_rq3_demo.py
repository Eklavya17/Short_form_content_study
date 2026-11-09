"""Demo server: a block can be started, swiped through, exported and reset."""

import json

import pytest

from rq3.demo import CLIPS, app, rule_timeline


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def start(client, feed="B", ratings=None):
    response = client.post("/api/start", json={"feed": feed, "ratings": ratings or {}})
    assert response.status_code == 200
    return response.get_json()


def swipe(client, clip, fraction=0.5, liked=False):
    response = client.post(
        "/api/swipe",
        json={
            "watched_s": clip["duration_s"] * fraction,
            "swipe_s": clip["duration_s"] * fraction,
            "reached_end": False,
            "liked": liked,
        },
    )
    return response


def test_page_loads(client):
    assert b"RQ3 feed demo" in client.get("/").data


def test_start_returns_a_clip_and_its_rule_timeline(client):
    data = start(client)
    assert data["clip"]["rule_timeline"][0]["rule"] == "hook"
    assert data["decision"]["kind"] == "first"
    assert data["decision"]["p_now"] == 0.75


def test_swipe_explains_score_and_decision(client):
    first = start(client, "C")
    data = swipe(client, first["clip"], fraction=0.5, liked=True).get_json()
    scored = data["scored"]
    assert scored["w_bar"] == 0.5 and scored["warmup"]
    assert scored["e"] == pytest.approx(scored["w"] - scored["w_bar"] + scored["g"], abs=0.002)
    assert data["decision"]["p_before"] == 0.45
    assert len(data["history"]) == 2


def test_feed_a_shows_cooldowns(client):
    first = start(client, "A")
    decision = swipe(client, first["clip"]).get_json()["decision"]
    assert decision["cooldowns"][first["clip"]["topic"]] == 3
    assert first["clip"]["topic"] not in decision["candidates"]


def test_swipe_before_start_is_refused(client):
    client.post("/api/reset")
    assert client.post("/api/swipe", json={}).status_code == 400


def test_running_out_of_clips_asks_for_reset(client):
    client.post("/api/reset")
    data = start(client, "A")
    for _ in range(len(CLIPS) - 1):
        response = swipe(client, data["clip"])
        assert response.status_code == 200
        data = response.get_json()
    response = swipe(client, data["clip"])
    assert response.status_code == 409
    assert "Reset" in response.get_json()["error"]


def test_export_downloads_the_block(client):
    first = start(client, "B")
    swipe(client, first["clip"])
    export = json.loads(client.get("/api/export").data)
    assert export["feed"] == "B" and len(export["history"]) == 2


def test_rule_timeline_covers_every_clip_end_to_end():
    for clip in CLIPS:
        segments = rule_timeline(clip)
        assert segments[0]["start_s"] == 0
        assert segments[-1]["end_s"] >= clip.duration_s - 0.25
        assert all(a["end_s"] == b["start_s"] for a, b in zip(segments, segments[1:]))
