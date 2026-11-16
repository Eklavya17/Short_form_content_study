"""The RQ3 participant study, served by rq3.demo at /participant.

Flow: enter an ID and rate each topic, then three parts (one per feed) in an order
chosen for you, with consent at the start and a survey after each part. When
RQ3_SURVEY_URL is set (a Qualtrics survey link), the participant is then sent
there with ?pid=...&study=rq3, and the survey's end redirect brings them back to
/participant/finished?pid=...&rid=... so we know they completed it.
No debug information is shown, and the page never receives a clip's
topic. All logic is in rq3.study; everything is stored in Postgres, so re-entering
the same ID, refreshing, or restarting the server resumes where the participant
left off. Clips never repeat for a participant.
"""

from __future__ import annotations

import json
import os
import secrets

from flask import Blueprint, Response, current_app, g, jsonify, redirect, render_template, request, session, url_for

from rq3 import storage
from rq3.catalog import load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.study import SURVEY_QUESTIONS, Study, StudyError

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
    "comedy_sketches": "Comedy and sketches",
    "science_education": "Science and education",
}

SURVEY_URL_ENV = "RQ3_SURVEY_URL"
TESTING_TOOLS_ENV = "RQ3_TESTING_TOOLS"  # "1" shows the testing panels (local demo only)

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


def survey_url() -> str:
    """The external questionnaire (Qualtrics) link, or "" when there is none."""
    return (current_app.config.get(SURVEY_URL_ENV) or os.environ.get(SURVEY_URL_ENV, "")).strip()


def testing_tools() -> bool:
    """Show the testing panels (videos per part, data download, new participant)?
    Off unless RQ3_TESTING_TOOLS=1, so real participants never see them."""
    value = current_app.config.get(TESTING_TOOLS_ENV) or os.environ.get(TESTING_TOOLS_ENV, "")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


# --- Routes --------------------------------------------------------------------------


@preview.get("")
def participant_page():
    return render_template(
        "rq3/participant.html",
        topics=STUDY.topics,
        topic_names=TOPIC_NAMES,
        videos_per_part=STUDY.config.videos_per_block,
        max_videos_per_part=STUDY.max_videos_per_part,
        survey_questions=SURVEY_QUESTIONS,
        questionnaire_enabled=bool(survey_url()),
        testing_tools=testing_tools(),
    )


@preview.get("/join")
def join():
    """One link for a whole group: each browser gets its own random participant ID.

    Opening it again in the same browser goes back to the same ID (to resume, or to
    the welcome page if they had not started yet), never to a new one.
    """
    pid = participant_id() or session.get("join_id", "")
    if not pid:
        pid = f"P-{secrets.token_hex(4).upper()}"
        while storage.get_participant(db(), pid):
            pid = f"P-{secrets.token_hex(4).upper()}"
        session["join_id"] = pid
    return redirect(url_for("preview.participant_page", pid=pid))


@preview.get("/questionnaire")
def questionnaire():
    """Send a participant who finished every part to the external questionnaire."""
    url = survey_url()
    if not url or not participant_id():
        return redirect(url_for("preview.participant_page"))
    try:
        return redirect(STUDY.questionnaire_link(db(), participant_id(), url))
    except StudyError:
        return redirect(url_for("preview.participant_page"))


@preview.get("/finished")
def finished():
    """Where the questionnaire's end-of-survey redirect lands."""
    pid = request.args.get("pid", "")
    try:
        STUDY.finish_questionnaire(db(), pid, request.args.get("rid"))
    except StudyError as error:
        return render_template("rq3/message.html", message=str(error)), 400
    session["participant_id"] = pid.strip()
    return redirect(url_for("preview.participant_page", pid=pid.strip()))


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
        # only the testing panel may change it; real participants get the study default
        (int(data.get("videos_per_part") or 0) or None) if testing_tools() else None,
        device=request.headers.get("User-Agent"),
        consented=data.get("consented") is True,
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


@preview.post("/api/survey")
def survey():
    data = request.get_json(force=True)
    return jsonify(STUDY.submit_survey(db(), participant_id(), data.get("part"), data.get("answers")).to_json())


@preview.post("/api/new")
def new_participant():
    session.pop("participant_id", None)
    return jsonify({"stage": "welcome"})


@preview.get("/api/export")
def export():
    if not testing_tools():  # researchers export with `python -m rq3.admin` instead
        return jsonify({"error": "Not available."}), 404
    payload = STUDY.export(db(), participant_id())
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=rq3_participant_{payload['participant_id']}.json"},
    )
