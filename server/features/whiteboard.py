"""Server-side whiteboard state manager.

Tracks the drawing events of a room, persists them to PostgreSQL,
and provides a headless QImage rendering method to export the canvas.
Also manages a periodic background snapshotting task.
"""

import base64
import json
import logging
import os
import threading
import time
from typing import Any

from PyQt6.QtCore import Qt, QBuffer, QIODevice
from PyQt6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QFont

from server.services.db import get_connection

logger = logging.getLogger(__name__)

# Canvas dimensions
CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
BACKGROUND_COLOR = "#1e1e1e"


class WhiteboardState:
    """Per-room collaborative whiteboard state.

    Manages sequence numbers, SQL persistence, dynamic undo/redo resolution,
    periodic snapshots, and exporting the canvas vector state to a PNG file.
    """

    def __init__(self, room_id: int, room_code: str, start_thread: bool = True) -> None:
        self._room_id = room_id
        self._room_code = room_code
        self._lock = threading.RLock()
        self._last_seq = 0
        self._last_snapshot_seq = 0
        self._snapshot_png_bytes: bytes | None = None

        # Cache of events since the last snapshot: seq_num -> event_dict
        self._events: dict[int, dict[str, Any]] = {}
        # Set of sequence numbers that have been undone
        self._undone_seqs: set[int] = set()

        # Cache of processed client_event_ids for duplicate detection
        self._processed_event_ids: set[str] = set()
        self._event_id_history: list[str] = []

        # Load initial state from database
        self.load_from_db()

        self._running = start_thread
        self._snapshot_thread = None
        if start_thread:
            self._snapshot_thread = threading.Thread(
                target=self._periodic_snapshot_loop,
                name=f"WBSnapshot-{room_code}",
                daemon=True
            )
            self._snapshot_thread.start()

    def load_from_db(self) -> None:
        """Load the latest snapshot and subsequent drawing events for this room from PostgreSQL.

        Builds the current vector shape tree and filters out undone elements.
        """
        with self._lock:
            self._events.clear()
            self._undone_seqs.clear()
            self._last_seq = 0
            self._last_snapshot_seq = 0
            self._snapshot_png_bytes = None

            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        # 1. Load latest snapshot if any
                        cur.execute(
                            "SELECT last_seq, snapshot_png FROM whiteboard_snapshots WHERE room_id = %s",
                            (self._room_id,),
                        )
                        row = cur.fetchone()
                        if row:
                            self._last_snapshot_seq = row[0]
                            self._snapshot_png_bytes = bytes(row[1])
                            self._last_seq = self._last_snapshot_seq

                        # 2. Load events after the last snapshot seq
                        cur.execute(
                            "SELECT seq_num, user_id, event_type, payload "
                            "FROM whiteboard_events "
                            "WHERE room_id = %s AND seq_num > %s "
                            "ORDER BY seq_num ASC",
                            (self._room_id, self._last_seq),
                        )
                        rows = cur.fetchall()

                        for seq_num, user_id, event_type, payload in rows:
                            if isinstance(payload, str):
                                try:
                                    payload_dict = json.loads(payload)
                                except Exception:
                                    payload_dict = {}
                            else:
                                payload_dict = payload

                            self._events[seq_num] = {
                                "seq_num": seq_num,
                                "user_id": user_id,
                                "event_type": event_type,
                                "payload": payload_dict,
                            }
                            if seq_num > self._last_seq:
                                self._last_seq = seq_num

                # Recalculate undone sequence numbers
                self._recalculate_undone_seqs()

                logger.debug(
                    "Room %s: loaded snapshot at seq %d, and %d subsequent events (%d active, last_seq=%d)",
                    self._room_code,
                    self._last_snapshot_seq,
                    len(self._events),
                    len(self.get_active_events()),
                    self._last_seq,
                )
            except Exception:
                logger.exception("Room %s: failed to load whiteboard events", self._room_code)

    def _recalculate_undone_seqs(self) -> None:
        """Dynamically compute which sequence numbers are undone by traversing in reverse order.

        Correctly resolves nested undo/redo actions.
        """
        self._undone_seqs.clear()
        for seq in sorted(self._events.keys(), reverse=True):
            event = self._events[seq]
            if event["event_type"] == "undo":
                if seq in self._undone_seqs:
                    continue
                target = event["payload"].get("target_seq")
                if isinstance(target, int):
                    self._undone_seqs.add(target)

    def add_event(self, user_id: int, event_type: str, payload: dict, client_event_id: str | None = None) -> int:
        """Add a new whiteboard event to the database and in-memory cache.

        Returns the newly assigned canonical sequence number.
        """
        with self._lock:
            # Check for duplicate client_event_id
            if client_event_id and client_event_id in self._processed_event_ids:
                logger.warning("Room %s: Duplicate client_event_id %s received, returning existing seq", self._room_code, client_event_id)
                # Search self._events for existing sequence
                for seq, ev in self._events.items():
                    if ev.get("client_event_id") == client_event_id:
                        return seq
                return self._last_seq

            self._last_seq += 1
            seq = self._last_seq

            self._events[seq] = {
                "seq_num": seq,
                "user_id": user_id,
                "event_type": event_type,
                "payload": payload,
                "client_event_id": client_event_id,
            }

            if client_event_id:
                self._processed_event_ids.add(client_event_id)
                self._event_id_history.append(client_event_id)
                if len(self._event_id_history) > 1000:
                    oldest = self._event_id_history.pop(0)
                    self._processed_event_ids.discard(oldest)

            # Re-evaluate undone sequences
            self._recalculate_undone_seqs()

            try:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "INSERT INTO whiteboard_events "
                            "(room_id, user_id, seq_num, event_type, payload) "
                            "VALUES (%s, %s, %s, %s, %s)",
                            (self._room_id, user_id, seq, event_type, json.dumps(payload)),
                        )
                        conn.commit()
            except Exception:
                logger.exception(
                    "Room %s: failed to persist whiteboard event %d",
                    self._room_code,
                    seq,
                )

            return seq

    def get_active_events(self, up_to_seq: int | None = None) -> list[dict[str, Any]]:
        """Return all drawing events since the last snapshot that have not been undone, sorted by seq_num."""
        with self._lock:
            # Re-calculate active events up to up_to_seq dynamically
            undone_seqs = set()
            events_to_process = sorted(self._events.keys())
            if up_to_seq is not None:
                events_to_process = [seq for seq in events_to_process if seq <= up_to_seq]

            for seq in reversed(events_to_process):
                event = self._events[seq]
                if event["event_type"] == "undo":
                    if seq in undone_seqs:
                        continue
                    target = event["payload"].get("target_seq")
                    if isinstance(target, int):
                        undone_seqs.add(target)

            active = []
            for seq in events_to_process:
                event = self._events[seq]
                if event["event_type"] == "undo" or seq in undone_seqs:
                    continue
                active.append(event)
            return active

    def get_snapshot_b64(self) -> str | None:
        """Get the base64-encoded representation of the latest whiteboard snapshot."""
        with self._lock:
            if self._snapshot_png_bytes:
                return base64.b64encode(self._snapshot_png_bytes).decode("ascii")
            return None

    def stop(self) -> None:
        """Gracefully stop the periodic snapshot thread."""
        self._running = False

    def _periodic_snapshot_loop(self) -> None:
        """Periodically render and save whiteboard snapshots to the database (every 60 seconds)."""
        while self._running:
            # Sleep in 1-second increments to respond to shutdown quickly
            for _ in range(60):
                if not self._running:
                    return
                time.sleep(1)

            with self._lock:
                current_last_seq = self._last_seq
                has_new_events = current_last_seq > self._last_snapshot_seq

            if has_new_events:
                try:
                    logger.debug("Room %s: taking periodic whiteboard snapshot at seq %d", self._room_code, current_last_seq)
                    png_bytes = self.render_png(up_to_seq=current_last_seq)
                    
                    with get_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                "INSERT INTO whiteboard_snapshots (room_id, last_seq, snapshot_png) "
                                "VALUES (%s, %s, %s) "
                                "ON CONFLICT (room_id) DO UPDATE "
                                "SET last_seq = EXCLUDED.last_seq, snapshot_png = EXCLUDED.snapshot_png",
                                (self._room_id, current_last_seq, png_bytes)
                            )
                            conn.commit()
                    
                    with self._lock:
                        # Prune events that are now baked into the snapshot
                        for seq in list(self._events.keys()):
                            if seq <= current_last_seq:
                                del self._events[seq]
                        
                        self._last_snapshot_seq = current_last_seq
                        self._snapshot_png_bytes = png_bytes
                        self._recalculate_undone_seqs()

                except Exception:
                    logger.exception("Room %s: failed to save periodic whiteboard snapshot", self._room_code)

    def render_png(self, up_to_seq: int | None = None) -> bytes:
        """Render all active drawing events onto a PNG canvas in headless mode.

        Returns raw PNG file bytes.
        """
        # Tell Qt we are running offscreen in case this is a headless environment
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

        from PyQt6.QtWidgets import QApplication
        if QApplication.instance() is None:
            # Keep a global reference to prevent garbage collection crashes
            global _global_app
            _global_app = QApplication([])

        active_events = self.get_active_events(up_to_seq=up_to_seq)

        # Create target image
        image = QImage(CANVAS_WIDTH, CANVAS_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied)
        
        # If we have a snapshot, initialize the image with it
        with self._lock:
            snapshot_bytes = self._snapshot_png_bytes
        
        if snapshot_bytes:
            image.loadFromData(snapshot_bytes)
        else:
            image.fill(QColor(BACKGROUND_COLOR))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        for event in active_events:
            etype = event["event_type"]
            payload = event["payload"]

            color_str = payload.get("color", "#ffffff")
            width = payload.get("width", 2)

            if etype == "eraser":
                pen_color = QColor(BACKGROUND_COLOR)
            else:
                pen_color = QColor(color_str)

            pen = QPen(
                pen_color,
                width if etype != "eraser" else width * 3,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)

            if etype in ("pen", "eraser"):
                points = payload.get("points", [])
                if len(points) >= 2:
                    path = QPainterPath()
                    path.moveTo(points[0][0], points[0][1])
                    for pt in points[1:]:
                        path.lineTo(pt[0], pt[1])
                    painter.drawPath(path)
                elif len(points) == 1:
                    # Draw single dot
                    painter.drawPoint(points[0][0], points[0][1])

            elif etype == "rect":
                rect = payload.get("rect", [0, 0, 0, 0])
                if len(rect) == 4:
                    painter.drawRect(rect[0], rect[1], rect[2], rect[3])

            elif etype == "oval":
                rect = payload.get("rect", [0, 0, 0, 0])
                if len(rect) == 4:
                    painter.drawEllipse(rect[0], rect[1], rect[2], rect[3])

            elif etype == "text":
                text = payload.get("text", "")
                pos = payload.get("text_pos", [0, 0])
                if text and len(pos) == 2:
                    # Renders text with Arial font
                    font = QFont("Arial", 16)
                    painter.setFont(font)
                    painter.drawText(pos[0], pos[1], text)

        painter.end()

        # Save QImage to buffer as PNG
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        png_bytes = buffer.data()
        buffer.close()

        return bytes(png_bytes)
