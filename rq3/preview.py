"""Participant preview: the RQ3 study as a participant sees it, minus consent and
surveys (those live in Qualtrics). Served by rq3.demo at /participant.

Flow: enter an ID and rate each topic, then three parts (one per feed) in an order
chosen for you, with a break screen after each part where the Qualtrics survey
will go. No debug information is shown, and the page never receives a clip's
topic. All logic is in rq3.study; everything is stored in Postgres, so re-entering
the same ID, refreshing, or restarting the server resumes where the participant
left off. Clips never repeat for a participant.
"""

from __future__ import annotations

import json

from flask import Blueprint, Response, current_app, g, jsonify, render_template, request, session

from rq3 import storage
from rq3.catalog import load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.study import Study, StudyError

STUDY = Study(load_catalog(), DEFAULT_CONFIG)
TOPIC_NAMES = {
    "animals_nature": "Animals and nature",
    "diy_projects": "DIY and crafts",
    "entertainment": "Comedy and entertainment",
    "food_drink": "Food and drink",
    "gaming": "Gaming",
    "knowledge_tests": "Facts, quizzes and experiments",
    "sports_fitness": "Sports and fitness",
    "transformations_mechanisms": "Satisfying transformations and how things work",
}

preview = Blueprint("preview", __name__, url_prefix="/participant")


def db() -> storage.Connection:
    """One database connection per request, closed when the request ends."""
    if "rq3_db" not in g:
        g.rq3_db = storage.connect(current_app.config["RQ3_DATABASE_URL"])
    return g.rq3_db


@preview.teardown_app_request
def close_db(_error: BaseException | None) -> None:
    connection = g.pop("rq3_db", None)
    if connection is not None:
        connection.close()


@preview.errorhandler(StudyError)
def study_error(error: StudyError):
    return jsonify({"error": str(error)}), 400


def participant_id() -> str:
    return session.get("participant_id", "")


# --- Routes --------------------------------------------------------------------------


@preview.get("")
def participant_page():
    return render_template(
        "rq3/participant.html",
        topics=STUDY.topics,
        topic_names=TOPIC_NAMES,
        videos_per_part=STUDY.config.videos_per_block,
        max_videos_per_part=STUDY.max_videos_per_part,
    )


@preview.get("/api/status")
def status():
    return jsonify(STUDY.status(db(), participant_id() or None).to_json())


@preview.post("/api/arrive")
def arrive():
    """Opened from a participant link (?pid=...): resume them if they exist."""
    pid = str(request.get_json(force=True).get("participant_id", "")).strip()
    STUDY.check_participant_id(pid)
    result = STUDY.status(db(), pid)
    if result.stage == "welcome":
        session.pop("participant_id", None)
    else:
        session["participant_id"] = pid
    return jsonify(result.to_json())


@preview.post("/api/begin")
def begin():
    data = request.get_json(force=True)
    result = STUDY.begin(
        db(),
        str(data.get("participant_id", "")),
        data.get("ratings") or {},
        int(data.get("videos_per_part") or 0) or None,
        device=request.headers.get("User-Agent"),
    )
    session["participant_id"] = result.participant_id
    return jsonify(result.to_json())


@preview.post("/api/next-part")
def next_part():
    return jsonify(STUDY.next_part(db(), participant_id()).to_json())


@preview.post("/api/swipe")
def swipe():
    return jsonify(STUDY.swipe(db(), participant_id(), request.get_json(force=True)).to_json())


@preview.post("/api/events")
def events():
    """A batch of player events (also sent by the browser as the page closes)."""
    if not participant_id():
        return jsonify({"kept": 0})
    data = request.get_json(force=True, silent=True) or {}
    return jsonify({"kept": STUDY.record_events(db(), participant_id(), data.get("events") or [])})


@preview.post("/api/new")
def new_participant():
    session.pop("participant_id", None)
    return jsonify({"stage": "welcome"})


@preview.get("/api/export")
def export():
    payload = STUDY.export(db(), participant_id())
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=rq3_participant_{payload['participant_id']}.json"},
    )
