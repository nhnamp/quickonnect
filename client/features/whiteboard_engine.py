"""Client-side whiteboard event helpers."""

from __future__ import annotations


def make_draw_packet(room_code: str, event_type: str, payload: dict, client_seq_num: int) -> dict:
    return {
        "room_code": room_code,
        "client_seq_num": client_seq_num,
        "event_type": event_type,
        "payload": payload,
    }


def normalize_rect(x1: float, y1: float, x2: float, y2: float) -> dict:
    x = min(x1, x2)
    y = min(y1, y2)
    return {
        "x": x,
        "y": y,
        "w": abs(x2 - x1),
        "h": abs(y2 - y1),
    }


def last_undoable_seq(events: list[dict], own_user_id: int) -> int | None:
    undone = {
        event.get("payload", {}).get("target_seq_num")
        for event in events
        if event.get("event_type") == "UNDO"
    }
    for event in reversed(events):
        seq = event.get("seq_num")
        if (
            event.get("user_id") == own_user_id
            and event.get("event_type") not in {"UNDO", "CLEAR"}
            and seq not in undone
        ):
            return seq
    return None
