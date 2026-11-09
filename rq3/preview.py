"""Participant preview: the RQ3 study as a participant would see it, minus consent
and surveys. Testing only; served by rq3.demo at /participant.

Flow: enter an ID and rate each topic, then three parts (one per feed) in an order
chosen for you, with a break screen after each part where the Qualtrics survey
will go. No debug information is shown. Videos never repeat for a participant:
every clip shown in an earlier part is passed to the next part's feed.

Which clips land in which part is decided at runtime by the feed engine, from the
whole unseen pool, not by splitting the pool in advance.

State lives in memory, keyed by participant ID, so re-entering the same ID (or
refreshing the page) resumes where it left off. Nothing is written to disk.
"""

from __future__ import annotations

import itertools
import json
import secrets
from collections import Counter
from dataclasses import dataclass, field
from random import Random
from typing import Any

from flask import Blueprint, Response, jsonify, render_template, request, session

from rq3.catalog import Clip, load_catalog
from rq3.config import DEFAULT_CONFIG
from rq3.feeds import Decision, Feed, FeedState, PoolExhaustedError, choose_next, first_video, new_state
from rq3.scoring import Outcome, judge_swipe, score_outcome, watch_fraction

CONFIG = DEFAULT_CONFIG
CLIPS = load_catalog()
TOPICS = sorted({clip.topic for clip in CLIPS})
FEED_ORDERS = ["".join(order) for order in itertools.permutations("ABC")]
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


@dataclass
class Part:
    feed: Feed
    state: FeedState
    videos: list[dict[str, Any]] = field(default_factory=list)  # one row per video shown


@dataclass
class ParticipantRun:
    participant_id: str
    feed_order: str
    ratings: dict[str, int]
    videos_per_part: int
    rng: Random = field(default_factory=lambda: Random(secrets.randbits(64)))
    parts: list[Part] = field(default_factory=list)
    part_open: bool = False  # True while a part is being watched

    @property
    def seen(self) -> set[str]:
        return self.parts[-1].state.seen if self.parts else set()

    @property
    def stage(self) -> str:
        if self.part_open:
            return "watching"
        if len(self.parts) == len(self.feed_order):
            return "done"
        return "break" if self.parts else "ready"


RUNS: dict[str, ParticipantRun] = {}
ORDER_COUNTS: Counter[str] = Counter()


def next_feed_order() -> str:
    """The least-used of the 6 orders of A, B and C, so orders stay balanced."""
    return min(FEED_ORDERS, key=lambda order: (ORDER_COUNTS[order], FEED_ORDERS.index(order)))


def current_run() -> ParticipantRun | None:
    return RUNS.get(session.get("participant_id", ""))


# --- What the page gets --------------------------------------------------------------


def clip_for_page(clip: Clip) -> dict[str, Any]:
    """Only what playback needs: no topic, structure or engine details."""
    return {"id": clip.id, "title": clip.title, "url": clip.url, "duration_s": clip.duration_s}


def status_payload(run: ParticipantRun) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "participant_id": run.participant_id,
        "stage": run.stage,
        "parts_total": len(run.feed_order),
        "parts_done": len(run.parts) - (1 if run.part_open else 0),
        "videos_per_part": run.videos_per_part,
    }
    if run.part_open:
        part = run.parts[-1]
        payload["clip"] = clip_for_page(part.state.clips[part.state.current_clip_id])
    return payload


def record_shown(part: Part, decision: Decision) -> None:
    part.videos.append(
        {
            "position": len(part.videos) + 1,
            "clip_id": decision.clip_id,
            "topic": decision.topic,
            "decision": decision.kind.value,
            "run_position": decision.run_position,
            "stay_probability": decision.stay_probability,
            "draw": decision.draw,
            "forced_reason": decision.forced_reason,
            "outcome": None,
        }
    )


def record_outcome(part: Part, clip: Clip, outcome: Outcome) -> None:
    verdict = judge_swipe(clip, outcome.swipe_s, outcome.reached_end, CONFIG)
    part.videos[-1]["outcome"] = {
        "watched_s": round(outcome.watched_s, 2),
        "swipe_s": round(outcome.swipe_s, 2),
        "reached_end": outcome.reached_end,
        "liked": outcome.liked,
        "fraction_watched": round(watch_fraction(outcome.watched_s, clip.duration_s), 3),
        "swipe_rule": verdict.rule.value,
        "g": verdict.g,
        "e": round(score_outcome(clip, outcome, part.state.watch_history, CONFIG), 3),
    }


# --- Routes --------------------------------------------------------------------------


@preview.get("")
def participant_page():
    return render_template(
        "rq3/participant.html",
        topics=TOPICS,
        topic_names=TOPIC_NAMES,
        videos_per_part=CONFIG.videos_per_block,
    )


@preview.get("/api/status")
def status():
    run = current_run()
    return jsonify(status_payload(run) if run else {"stage": "welcome"})


@preview.post("/api/begin")
def begin():
    """Register a participant (or resume one with the same ID)."""
    data = request.get_json(force=True)
    participant_id = str(data.get("participant_id", "")).strip()
    if not participant_id:
        return jsonify({"error": "Enter a participant ID."}), 400
    session["participant_id"] = participant_id
    if participant_id in RUNS:
        return jsonify(status_payload(RUNS[participant_id]))

    videos_per_part = int(data.get("videos_per_part") or CONFIG.videos_per_block)
    most = len(CLIPS) // 3
    if not 1 <= videos_per_part <= most:
        return jsonify({"error": f"Videos per part must be 1-{most} with {len(CLIPS)} clips."}), 400
    order = next_feed_order()
    ORDER_COUNTS[order] += 1
    ratings = {t: min(max(int(data.get("ratings", {}).get(t, 3)), 1), 5) for t in TOPICS}
    RUNS[participant_id] = ParticipantRun(participant_id, order, ratings, videos_per_part)
    return jsonify(status_payload(RUNS[participant_id]))


@preview.post("/api/next-part")
def next_part():
    run = current_run()
    if run is None:
        return jsonify({"error": "Enter a participant ID first."}), 400
    if run.part_open:
        return jsonify(status_payload(run))
    if run.stage == "done":
        return jsonify({"error": "All parts are finished."}), 400

    feed = Feed(run.feed_order[len(run.parts)])
    state = new_state(feed, CLIPS, run.ratings, CONFIG, seen=run.seen)
    part = Part(feed, state)
    record_shown(part, first_video(state, run.rng))
    run.parts.append(part)
    run.part_open = True
    return jsonify(status_payload(run))


@preview.post("/api/swipe")
def swipe():
    run = current_run()
    if run is None or not run.part_open:
        return jsonify({"error": "No part is playing."}), 400
    part = run.parts[-1]
    clip = part.state.clips[part.state.current_clip_id]
    data = request.get_json(force=True)
    outcome = Outcome(
        clip_id=clip.id,
        watched_s=max(float(data["watched_s"]), 0.0),
        swipe_s=min(max(float(data["swipe_s"]), 0.0), clip.duration_s),
        reached_end=bool(data["reached_end"]),
        liked=bool(data["liked"]),
    )
    record_outcome(part, clip, outcome)

    if len(part.videos) >= run.videos_per_part:
        run.part_open = False  # last video of the part: nothing more to pick
        return jsonify(status_payload(run))
    try:
        record_shown(part, choose_next(part.state, outcome, run.rng))
    except PoolExhaustedError:
        run.part_open = False
    return jsonify(status_payload(run))


@preview.post("/api/new")
def new_participant():
    session.pop("participant_id", None)
    return jsonify({"stage": "welcome"})


@preview.get("/api/export")
def export():
    run = current_run()
    if run is None:
        return jsonify({"error": "No participant."}), 400
    payload = {
        "participant_id": run.participant_id,
        "feed_order": run.feed_order,
        "ratings": run.ratings,
        "videos_per_part": run.videos_per_part,
        "parts": [{"part": i + 1, "feed": p.feed.value, "videos": p.videos} for i, p in enumerate(run.parts)],
    }
    return Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=rq3_participant_{run.participant_id}.json"},
    )
