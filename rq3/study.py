"""The RQ3 participant flow, stored in Postgres. No Flask code: the web routes and
the tests call the same functions.

A participant has a fixed feed order (balanced across participants) and goes
through three parts, one feed each. Every request runs in one transaction that
first locks the participant's row, so a double click or two open tabs cannot
interleave. After each decision the feed's engine state is saved, so a refresh or
a server restart continues exactly where the participant was.

Clips are never split into parts in advance: each part's feed picks from the
whole pool minus every clip that participant has already seen.

Only raw facts are stored. Scores (swipe rule, g, e) are recomputed from them in
`export`, so the scoring formula can change after data collection.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from random import Random
from typing import Any

from rq3 import storage
from rq3.catalog import Clip
from rq3.config import FeedConfig
from rq3.feeds import Decision, Feed, PoolExhaustedError, choose_next, first_video, new_state, restore_state
from rq3.scoring import Outcome, judge_swipe, score_outcome, watch_fraction

PARTS = 3
PARTICIPANT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_EVENTS_PER_REQUEST = 200


class StudyError(ValueError):
    """A request the participant's state does not allow; the message is shown to them."""


@dataclass(frozen=True)
class Status:
    """Where a participant is, which is all the page needs to render."""

    stage: str  # welcome, ready, watching, break or done
    participant_id: str | None = None
    parts_done: int = 0
    videos_per_part: int = 0
    clip: Clip | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "stage": self.stage,
            "participant_id": self.participant_id,
            "parts_total": PARTS,
            "parts_done": self.parts_done,
            "videos_per_part": self.videos_per_part,
        }
        if self.clip is not None:
            # Only what playback needs: never the topic or any engine detail.
            payload["clip"] = {
                "id": self.clip.id,
                "title": self.clip.title,
                "url": self.clip.url,
                "duration_s": self.clip.duration_s,
            }
        return payload


class Study:
    def __init__(self, clips: list[Clip], config: FeedConfig):
        self.clips = clips
        self.clips_by_id = {clip.id: clip for clip in clips}
        self.topics = sorted({clip.topic for clip in clips})
        self.config = config

    @property
    def max_videos_per_part(self) -> int:
        return len(self.clips) // PARTS

    # --- Requests --------------------------------------------------------------------

    def begin(
        self,
        db: storage.Connection,
        participant_id: str,
        interest: dict[str, Any],
        videos_per_part: int | None = None,
        device: str | None = None,
    ) -> Status:
        """Register a participant, or return where an existing one is."""
        participant_id = participant_id.strip()
        self.check_participant_id(participant_id)
        videos_per_part = videos_per_part or self.config.videos_per_block
        if not 1 <= videos_per_part <= self.max_videos_per_part:
            raise StudyError(f"Videos per part must be 1-{self.max_videos_per_part} with {len(self.clips)} clips.")

        with db.transaction():
            participant = storage.get_participant(db, participant_id, lock=True)
            if participant is None:
                order = storage.assign_feed_order(db)  # takes the sign-up lock
                participant = storage.get_participant(db, participant_id)  # created while we waited?
            if participant is None:
                ratings = {t: _clamp_rating(interest.get(t, 3)) for t in self.topics}
                storage.create_participant(db, participant_id, order, ratings, videos_per_part, device)
                participant = storage.get_participant(db, participant_id)
            return self._status(db, participant)

    @staticmethod
    def check_participant_id(participant_id: str) -> None:
        if not PARTICIPANT_ID_PATTERN.match(participant_id):
            raise StudyError("Participant ID must be 1-64 letters, digits, - or _.")

    def status(self, db: storage.Connection, participant_id: str | None) -> Status:
        participant = storage.get_participant(db, participant_id) if participant_id else None
        return self._status(db, participant) if participant else Status("welcome")

    def next_part(self, db: storage.Connection, participant_id: str) -> Status:
        """Start the participant's next part with its first video."""
        with db.transaction():
            participant = self._locked_participant(db, participant_id)
            blocks = storage.blocks_for(db, participant_id)
            if any(block["ended_at"] is None for block in blocks):
                return self._status(db, participant)
            if len(blocks) >= PARTS:
                raise StudyError("All parts are finished.")

            feed = Feed(participant["feed_order"][len(blocks)])
            seen = set(blocks[-1]["feed_state"]["seen"]) if blocks else set()
            state = new_state(feed, self.clips, participant["interest"], self.config, seen=seen)
            decision = first_video(state, _rng())
            block_id = storage.start_block(db, participant_id, len(blocks) + 1, feed.value, state.snapshot())
            storage.record_impression(db, block_id, 1, _decision_row(decision))
            return self._status(db, participant)

    def swipe(self, db: storage.Connection, participant_id: str, report: dict[str, Any]) -> Status:
        """Record how the viewer left the current video and pick the next one.

        `report` is what the player sends: clip_id, watched_s, swipe_s, reached_end,
        liked, and any player events not yet sent. A report for any clip other than
        the one playing (a double click, an old tab) only has its events recorded.
        """
        with db.transaction():
            participant = self._locked_participant(db, participant_id)
            self._record_events(db, participant_id, report.get("events") or [])
            block = _open_block(storage.blocks_for(db, participant_id))
            if block is None:
                raise StudyError("No part is playing.")
            state = restore_state(block["feed_state"], self.clips, self.config)
            if report.get("clip_id") != state.current_clip_id:
                return self._status(db, participant)

            impressions = storage.impressions_for(db, block["id"])
            clip = self.clips_by_id[state.current_clip_id]
            outcome = _outcome_from(report, clip)
            storage.record_outcome(db, impressions[-1]["id"], _outcome_row(outcome))

            if len(impressions) >= participant["videos_per_part"]:
                self._end_part(db, participant, block)
                return self._status(db, participant)
            try:
                decision = choose_next(state, outcome, _rng())
            except PoolExhaustedError:
                self._end_part(db, participant, block)
                return self._status(db, participant)
            storage.record_impression(db, block["id"], len(impressions) + 1, _decision_row(decision))
            storage.save_feed_state(db, block["id"], state.snapshot())
            return self._status(db, participant)

    def record_events(self, db: storage.Connection, participant_id: str, events: list[dict[str, Any]]) -> int:
        """Store a batch of player events; returns how many were kept."""
        with db.transaction():
            self._locked_participant(db, participant_id)
            return self._record_events(db, participant_id, events)

    def export(self, db: storage.Connection, participant_id: str) -> dict[str, Any]:
        """Everything stored for one participant, with scores recomputed from raw facts."""
        participant = storage.get_participant(db, participant_id)
        if participant is None:
            raise StudyError("No such participant.")
        parts = []
        for block in storage.blocks_for(db, participant_id):
            history: list[float] = []
            videos = []
            for row in storage.impressions_for(db, block["id"]):
                clip = self.clips_by_id[row["clip_id"]]
                video = {
                    "position": row["position"],
                    "clip_id": row["clip_id"],
                    "title": clip.title,
                    "topic": row["topic"],
                    "decision": row["decision"],
                    "run_position": row["run_position"],
                    "stay_probability": row["stay_probability"],
                    "draw": row["draw"],
                    "forced_reason": row["forced_reason"],
                    "shown_at": row["shown_at"],
                    "outcome": row["outcome"],
                    "scored": None,
                    "events": storage.events_for(db, row["id"]),
                }
                if row["outcome"] is not None:
                    outcome = Outcome(clip.id, **row["outcome"])
                    verdict = judge_swipe(clip, outcome.swipe_s, outcome.reached_end, self.config)
                    fraction = watch_fraction(outcome.watched_s, clip.duration_s)
                    video["scored"] = {
                        "swipe_rule": verdict.rule.value,
                        "g": verdict.g,
                        "fraction_watched": round(fraction, 3),
                        "e": round(score_outcome(clip, outcome, history, self.config), 3),
                    }
                    history.append(fraction)
                videos.append(video)
            parts.append(
                {
                    "part": block["block_number"],
                    "feed": block["feed"],
                    "started_at": block["started_at"],
                    "ended_at": block["ended_at"],
                    "videos": videos,
                }
            )
        return {
            "participant_id": participant["id"],
            "created_at": participant["created_at"],
            "completed_at": participant["completed_at"],
            "feed_order": participant["feed_order"],
            "interest": participant["interest"],
            "videos_per_part": participant["videos_per_part"],
            "device": participant["device"],
            "parts": parts,
        }

    # --- Helpers -------------------------------------------------------------------

    def _record_events(self, db: storage.Connection, participant_id: str, events: list[dict[str, Any]]) -> int:
        """Attach each event to the impression of the clip it is about. Events with an
        unknown type or clip are dropped rather than failing the whole batch."""
        kept = 0
        impression_ids: dict[str, int | None] = {}
        for event in events[:MAX_EVENTS_PER_REQUEST]:
            clip_id = str(event.get("clip_id", ""))
            if event.get("event_type") not in storage.EVENT_TYPES:
                continue
            if clip_id not in impression_ids:
                impression_ids[clip_id] = storage.impression_for_clip(db, participant_id, clip_id)
            if impression_ids[clip_id] is None:
                continue
            storage.record_event(db, impression_ids[clip_id], {
                "event_type": event["event_type"],
                "video_time": _number_or_none(event.get("video_time")),
                "client_wall_time": str(event.get("client_wall_time", ""))[:40] or None,
                "details": event.get("details") if isinstance(event.get("details"), dict) else {},
            })
            kept += 1
        return kept

    def _locked_participant(self, db: storage.Connection, participant_id: str) -> dict[str, Any]:
        participant = storage.get_participant(db, participant_id, lock=True)
        if participant is None:
            raise StudyError("Enter a participant ID first.")
        return participant

    def _end_part(self, db: storage.Connection, participant: dict[str, Any], block: dict[str, Any]) -> None:
        storage.end_block(db, block["id"])
        if block["block_number"] >= PARTS:
            storage.mark_completed(db, participant["id"])

    def _status(self, db: storage.Connection, participant: dict[str, Any]) -> Status:
        blocks = storage.blocks_for(db, participant["id"])
        open_block = _open_block(blocks)
        ended = sum(1 for block in blocks if block["ended_at"] is not None)
        common = {
            "participant_id": participant["id"],
            "parts_done": ended,
            "videos_per_part": participant["videos_per_part"],
        }
        if open_block is not None:
            clip = self.clips_by_id[open_block["feed_state"]["current_clip_id"]]
            return Status("watching", clip=clip, **common)
        if ended >= PARTS:
            return Status("done", **common)
        return Status("break" if ended else "ready", **common)


def _open_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((block for block in blocks if block["ended_at"] is None), None)


def _rng() -> Random:
    return Random(secrets.randbits(64))


def _number_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_rating(value: Any) -> int:
    try:
        return min(max(int(value), 1), 5)
    except (TypeError, ValueError):
        return 3


def _outcome_from(report: dict[str, Any], clip: Clip) -> Outcome:
    return Outcome(
        clip_id=clip.id,
        watched_s=max(float(report.get("watched_s", 0)), 0.0),
        swipe_s=min(max(float(report.get("swipe_s", 0)), 0.0), clip.duration_s),
        reached_end=bool(report.get("reached_end")),
        liked=bool(report.get("liked")),
    )


def _outcome_row(outcome: Outcome) -> dict[str, Any]:
    return {
        "watched_s": round(outcome.watched_s, 3),
        "swipe_s": round(outcome.swipe_s, 3),
        "reached_end": outcome.reached_end,
        "liked": outcome.liked,
    }


def _decision_row(decision: Decision) -> dict[str, Any]:
    return {
        "clip_id": decision.clip_id,
        "topic": decision.topic,
        "kind": decision.kind.value,
        "run_position": decision.run_position,
        "forced_reason": decision.forced_reason,
        "stay_probability": decision.stay_probability,
        "draw": decision.draw,
        "previous_engagement": decision.previous_engagement,
        "state_snapshot": decision.state_snapshot,
    }
