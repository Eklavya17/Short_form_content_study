"""Local demo of the RQ3 feeds, with a debug panel. For testing only, not the study.

Run:
    python -m rq3.demo            then open http://127.0.0.1:5001
    python -m rq3.demo --host 0.0.0.0 --port 8000   (e.g. on a course VM)

It runs the real engine (rq3.feeds, rq3.scoring) on the real catalog. Each browser
gets its own in-memory session: no database, nothing is saved when it stops.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from random import Random
from typing import Any

from flask import Flask, Response, jsonify, redirect, render_template, request, session

from rq3.catalog import Clip, load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.feeds import (
    Decision,
    DecisionKind,
    Feed,
    FeedState,
    PoolExhaustedError,
    choose_next,
    cooldown_candidates,
    first_video,
    new_state,
    restore_state,
    topic_odds,
)
from rq3.scoring import (
    Outcome,
    average_watch,
    judge_swipe,
    watch_fraction,
)

ROOT = Path(__file__).resolve().parent.parent
CONFIG = DEFAULT_CONFIG
CLIPS = load_catalog()
TOPICS = sorted({clip.topic for clip in CLIPS})
TIMELINE_STEP_S = 0.25

app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
app.config["SECRET_KEY"] = os.environ.get("RQ3_DEMO_SECRET", secrets.token_hex(16))


@dataclass
class DemoSession:
    rng: Random = field(default_factory=lambda: Random(secrets.randbits(64)))
    state: FeedState | None = None
    seen: set[str] = field(default_factory=set)  # carried across blocks until Reset
    ratings: dict[str, int] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)


SESSIONS: dict[str, DemoSession] = {}


def current_session() -> DemoSession:
    if "demo_id" not in session:
        session["demo_id"] = secrets.token_urlsafe(12)
    return SESSIONS.setdefault(session["demo_id"], DemoSession())


# --- What the page needs about a clip ---------------------------------------------------


def rule_timeline(clip: Clip) -> list[dict[str, Any]]:
    """The scoring rule a swipe would match at each moment, merged into segments, so the
    page can show "if you swipe now" without duplicating the rules in JavaScript."""
    segments: list[dict[str, Any]] = []
    t = 0.0
    while t < clip.duration_s:
        verdict = judge_swipe(clip, t, False, CONFIG)
        key = (verdict.rule.value, verdict.g, verdict.loop_index)
        if segments and (segments[-1]["rule"], segments[-1]["g"], segments[-1]["loop"]) == key:
            segments[-1]["end_s"] = round(t + TIMELINE_STEP_S, 2)
        else:
            segments.append(
                {
                    "rule": verdict.rule.value,
                    "g": verdict.g,
                    "loop": verdict.loop_index,
                    "start_s": t,
                    "end_s": round(t + TIMELINE_STEP_S, 2),
                }
            )
        t = round(t + TIMELINE_STEP_S, 2)
    return segments


def clip_payload(clip: Clip) -> dict[str, Any]:
    return {
        "id": clip.id,
        "title": clip.title,
        "url": clip.url,
        "topic": clip.topic,
        "structure": clip.structure.name.lower(),
        "duration_s": clip.duration_s,
        "stages": [{"label": s.label.value, "start_s": s.start_s, "end_s": s.end_s} for s in clip.stages],
        "loops": [{"index": lp.index, "start_s": lp.start_s, "end_s": lp.end_s} for lp in clip.loops],
        "review": list(clip.review),
        "rule_timeline": rule_timeline(clip),
    }


# --- Explaining a decision ------------------------------------------------------------------


def explain_decision(state: FeedState, decision: Decision, left_topic: str | None, p_before: float | None) -> dict[str, Any]:
    """Everything the panel shows about why this video was picked."""
    at_decision = restore_state(decision.state_snapshot, CLIPS, CONFIG)
    explanation: dict[str, Any] = {
        "feed": state.feed.value,
        "kind": decision.kind.value,
        "topic": decision.topic,
        "run_position": decision.run_position,
        "forced_reason": decision.forced_reason,
        "p_before": p_before,
        "p_used": decision.stay_probability,
        "p_now": state.stay_probability,
        "draw": decision.draw,
        "unseen_in_topic": sum(1 for c in CLIPS if c.topic == decision.topic and c.id not in state.seen),
    }
    if state.feed is Feed.A:
        explanation["cooldowns"] = at_decision.cooldowns
        explanation["candidates"] = cooldown_candidates(at_decision)
    elif decision.kind is not DecisionKind.STAY:
        explanation["topic_odds"] = topic_odds(at_decision, exclude=left_topic)
    return explanation


def block_summary(history: list[dict[str, Any]]) -> dict[str, Any]:
    runs, run = [], 0
    for row in history:
        if row["kind"] == DecisionKind.STAY.value:
            run += 1
        else:
            if run:
                runs.append(run)
            run = 1
    if run:
        runs.append(run)
    return {
        "videos": len(history),
        "average_run": round(sum(runs) / len(runs), 2) if runs else 0,
        "runs_three_plus": sum(r >= 3 for r in runs),
        "forced_switches": sum(row["kind"] == DecisionKind.FORCED_SWITCH.value for row in history),
    }


def response_for(demo: DemoSession, decision: Decision, explanation: dict, scored: dict | None):
    state = demo.state
    demo.history.append(
        {
            "clip_id": decision.clip_id,
            "topic": decision.topic,
            "kind": decision.kind.value,
            "run_position": decision.run_position,
            "p_used": decision.stay_probability,
            "draw": decision.draw,
            "scored_previous": scored,
            "decision": explanation,
        }
    )
    return jsonify(
        {
            "clip": clip_payload(state.clips[decision.clip_id]),
            "decision": explanation,
            "scored": scored,
            "topic_scores": state.topic_scores,
            "history": demo.history,
            "summary": block_summary(demo.history),
            "seen_total": len(state.seen),
            "pool_size": len(CLIPS),
        }
    )


# --- Routes -------------------------------------------------------------------------------


@app.get("/")
def demo_page():
    # On Windows, "localhost" tries IPv6 first and adds ~0.3 s to every request,
    # because the server listens on IPv4 only. Send the browser to 127.0.0.1.
    if request.host.split(":")[0] == "localhost":
        return redirect(request.url.replace("://localhost", "://127.0.0.1", 1))
    return render_template("rq3/demo.html", topics=TOPICS, config=CONFIG)


@app.post("/api/start")
def start_block():
    demo = current_session()
    data = request.get_json(force=True)
    feed = Feed(data["feed"])
    demo.ratings = {t: int(data.get("ratings", {}).get(t, 3)) for t in TOPICS}
    if demo.state is not None:
        demo.seen = demo.state.seen
    demo.state = new_state(feed, CLIPS, demo.ratings, CONFIG, seen=demo.seen)
    demo.history = []
    p_before = demo.state.stay_probability
    try:
        decision = first_video(demo.state, demo.rng)
    except PoolExhaustedError:
        return jsonify({"error": "Every clip has been shown. Press Reset to start over."}), 409
    return response_for(demo, decision, explain_decision(demo.state, decision, None, p_before), None)


@app.post("/api/swipe")
def swipe():
    demo = current_session()
    state = demo.state
    if state is None or state.current_clip_id is None:
        return jsonify({"error": "Start a block first."}), 400
    data = request.get_json(force=True)
    clip = state.clips[state.current_clip_id]
    outcome = Outcome(
        clip_id=clip.id,
        watched_s=max(float(data["watched_s"]), 0.0),
        swipe_s=min(max(float(data["swipe_s"]), 0.0), clip.duration_s),
        reached_end=bool(data["reached_end"]),
        liked=bool(data["liked"]),
    )
    verdict = judge_swipe(clip, outcome.swipe_s, outcome.reached_end, CONFIG)
    scored = {
        "clip_title": clip.title,
        "swipe_s": round(outcome.swipe_s, 2),
        "duration_s": clip.duration_s,
        "watched_s": round(outcome.watched_s, 2),
        "rule": verdict.rule.value,
        "g": verdict.g,
        "loop": verdict.loop_index,
        "loops_total": len(clip.loops),
        "w": round(watch_fraction(outcome.watched_s, clip.duration_s), 3),
        "w_bar": round(average_watch(state.watch_history, CONFIG), 3),
        "warmup": len(state.watch_history) < CONFIG.warmup_videos,
        "liked": outcome.liked,
        "reached_end": outcome.reached_end,
    }
    p_before = state.stay_probability
    try:
        decision = choose_next(state, outcome, demo.rng)
    except PoolExhaustedError:
        return jsonify({"error": "Every clip has been shown. Press Reset to start over.", "scored": scored}), 409
    scored["e"] = round(decision.previous_engagement, 3)
    explanation = explain_decision(state, decision, clip.topic, p_before)
    return response_for(demo, decision, explanation, scored)


@app.post("/api/reset")
def reset():
    session_id = session.get("demo_id")
    SESSIONS.pop(session_id, None)
    return jsonify({"ok": True, "pool_size": len(CLIPS)})


@app.get("/api/export")
def export_block():
    demo = current_session()
    payload = {"feed": demo.state.feed.value if demo.state else None, "ratings": demo.ratings, "history": demo.history}
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=rq3_demo_block.json"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the RQ3 feed demo with its debug panel.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5001)))
    args = parser.parse_args()
    print(f"RQ3 demo: http://{args.host}:{args.port}  ({len(CLIPS)} clips, {len(TOPICS)} topics)")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
