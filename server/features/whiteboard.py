"""Server-side collaborative whiteboard state."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from server.services.db import get_connection

logger = logging.getLogger(__name__)

ALLOWED_EVENT_TYPES = {
    "STROKE",
    "RECT",
    "OVAL",
    "TEXT",
    "ERASE",
    "CLEAR",
    "UNDO",
}


@dataclass
class WhiteboardEvent:
    room_id: int
    room_code: str
    seq_num: int
    user_id: int
    username: str
    event_type: str
    payload: dict

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "room_code": self.room_code,
            "seq_num": self.seq_num,
            "user_id": self.user_id,
            "username": self.username,
            "event_type": self.event_type,
            "payload": self.payload,
        }


class WhiteboardState:
    """Per-room event log with server-assigned sequence numbers."""

    def __init__(self, room_id: int, room_code: str):
        self._room_id = room_id
        self._room_code = room_code
        self._lock = threading.Lock()
        self._events: list[WhiteboardEvent] = []
        self._next_seq = 1
        self._load_from_db()

    def sync_payload(self) -> dict:
        with self._lock:
            return {
                "room_id": self._room_id,
                "room_code": self._room_code,
                "events": [event.to_dict() for event in self._events],
            }

    def add_event(self, user_id: int, username: str, event_type: str, payload: dict) -> tuple[WhiteboardEvent | None, str | None]:
        event_type = event_type.upper().strip()
        if event_type not in ALLOWED_EVENT_TYPES:
            return None, f"Unsupported whiteboard event type: {event_type}"
        if not isinstance(payload, dict):
            return None, "Whiteboard payload must be an object"

        clean_payload = _sanitize_payload(event_type, payload)
        if clean_payload is None:
            return None, "Invalid whiteboard payload"

        with self._lock:
            seq = self._next_seq
            self._next_seq += 1
            event = WhiteboardEvent(
                room_id=self._room_id,
                room_code=self._room_code,
                seq_num=seq,
                user_id=user_id,
                username=username,
                event_type=event_type,
                payload=clean_payload,
            )
            if not self._store_event(event):
                self._next_seq -= 1
                return None, "Failed to store whiteboard event"
            self._events.append(event)
            return event, None

    def _load_from_db(self) -> None:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT e.seq_num, e.user_id, u.username, e.event_type, e.payload
                        FROM whiteboard_events e
                        JOIN users u ON u.id = e.user_id
                        WHERE e.room_id = %s
                        ORDER BY e.seq_num ASC
                        """,
                        (self._room_id,),
                    )
                    for seq_num, user_id, username, event_type, payload in cur.fetchall():
                        self._events.append(WhiteboardEvent(
                            room_id=self._room_id,
                            room_code=self._room_code,
                            seq_num=int(seq_num),
                            user_id=int(user_id),
                            username=username,
                            event_type=event_type,
                            payload=dict(payload),
                        ))
            if self._events:
                self._next_seq = max(event.seq_num for event in self._events) + 1
        except Exception:
            logger.exception("Failed to load whiteboard events for room %s", self._room_code)

    def _store_event(self, event: WhiteboardEvent) -> bool:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO whiteboard_events (room_id, user_id, seq_num, event_type, payload)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (event.room_id, event.user_id, event.seq_num, event.event_type, Jsonb(event.payload)),
                    )
                    conn.commit()
            return True
        except Exception:
            logger.exception("Failed to store whiteboard event")
            return False


def _sanitize_payload(event_type: str, payload: dict) -> dict | None:
    try:
        if event_type == "STROKE":
            points = payload.get("points", [])
            if not isinstance(points, list) or len(points) < 2:
                return None
            return {
                "points": [_point(p) for p in points[:2000]],
                "color": _color(payload.get("color", "#111111")),
                "width": _number(payload.get("width", 3), 1, 40),
            }
        if event_type in {"RECT", "OVAL"}:
            return {
                "x": _number(payload.get("x", 0), 0, 100000),
                "y": _number(payload.get("y", 0), 0, 100000),
                "w": _number(payload.get("w", 0), 1, 100000),
                "h": _number(payload.get("h", 0), 1, 100000),
                "color": _color(payload.get("color", "#111111")),
                "width": _number(payload.get("width", 3), 1, 40),
            }
        if event_type == "TEXT":
            text = str(payload.get("text", "")).strip()
            if not text:
                return None
            return {
                "x": _number(payload.get("x", 0), 0, 100000),
                "y": _number(payload.get("y", 0), 0, 100000),
                "text": text[:500],
                "color": _color(payload.get("color", "#111111")),
                "font_size": int(_number(payload.get("font_size", 18), 8, 72)),
            }
        if event_type == "ERASE":
            return {
                "x": _number(payload.get("x", 0), 0, 100000),
                "y": _number(payload.get("y", 0), 0, 100000),
                "radius": _number(payload.get("radius", 16), 2, 100),
            }
        if event_type == "UNDO":
            target = int(payload.get("target_seq_num", 0))
            return {"target_seq_num": target} if target > 0 else None
        if event_type == "CLEAR":
            return {}
    except Exception:
        return None
    return None


def _point(value) -> dict:
    if not isinstance(value, dict):
        raise ValueError("point must be object")
    return {
        "x": _number(value.get("x", 0), 0, 100000),
        "y": _number(value.get("y", 0), 0, 100000),
    }


def _number(value, low: float, high: float) -> float:
    val = float(value)
    if val < low:
        return low
    if val > high:
        return high
    return val


def _color(value) -> str:
    text = str(value)
    if len(text) == 7 and text.startswith("#"):
        int(text[1:], 16)
        return text.lower()
    return "#111111"
