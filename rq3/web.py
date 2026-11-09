"""Flask routes for the RQ3 study flow and the player API (Part 2).

Study flow: consent -> topic interest -> 3 practice videos -> 3 blocks, each
followed by a short survey -> end survey.

The player never decides what to show: it reports each swipe and receives the
next video (plus a likely switch candidate to preload). Register with:

    from rq3.web import rq3
    app.register_blueprint(rq3)
"""

from __future__ import annotations

from flask import Blueprint, abort

rq3 = Blueprint("rq3", __name__, url_prefix="/rq3")


def _not_built():
    abort(501, description="RQ3 route not built yet")


# --- Study pages ---------------------------------------------------------------


@rq3.get("/")
def consent_page():
    """Consent form. The participant ID comes from the study link (?pid=...)."""
    return _not_built()


@rq3.post("/consent")
def submit_consent():
    return _not_built()


@rq3.post("/interest")
def submit_interest():
    """Save 1-5 ratings for each topic; they seed the topic scores for B and C."""
    return _not_built()


@rq3.get("/feed")
def feed_page():
    """The player page for the participant's current block (or practice)."""
    return _not_built()


@rq3.post("/block-survey")
def submit_block_survey():
    """Engaging, repetitive, relevant, keep scrolling (1-7 each)."""
    return _not_built()


@rq3.post("/end-survey")
def submit_end_survey():
    """Favourite feed, and anything odd (playback problems, distractions)."""
    return _not_built()


# --- Player API ----------------------------------------------------------------


@rq3.get("/api/current")
def current_video():
    """The video to show now and a candidate to preload."""
    return _not_built()


@rq3.post("/api/swipe")
def swipe():
    """Score the video that ended, run the feed engine, save the decision, return the next video."""
    return _not_built()


@rq3.post("/api/event")
def log_event():
    """Store one player event (see storage.EVENT_TYPES)."""
    return _not_built()


# --- Admin ---------------------------------------------------------------------


@rq3.get("/admin/export/<table>.csv")
def export_table(table: str):
    """One CSV per table, behind the admin password."""
    return _not_built()
