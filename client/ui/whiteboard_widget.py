"""Collaborative whiteboard tab."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPointF, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PyQt6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
    QVBoxLayout,
)

from shared.constants import PacketType
from client.features.whiteboard_engine import make_draw_packet, normalize_rect, last_undoable_seq


class WhiteboardCanvas(QWidget):
    event_ready = pyqtSignal(str, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 420)
        self.setMouseTracking(True)
        self.setStyleSheet("background-color: white;")
        self._tool = "pen"
        self._color = QColor("#111111")
        self._width = 3
        self._events: list[dict] = []
        self._drawing = False
        self._start: QPointF | None = None
        self._points: list[dict] = []
        self._preview: QPointF | None = None

    def set_tool(self, tool: str) -> None:
        self._tool = tool

    def set_color(self, color: QColor) -> None:
        if color.isValid():
            self._color = color

    def set_width(self, width: int) -> None:
        self._width = max(1, min(40, int(width)))

    def events(self) -> list[dict]:
        return list(self._events)

    def replace_events(self, events: list[dict]) -> None:
        self._events = sorted(events, key=lambda event: event.get("seq_num", 0))
        self.update()

    def add_event(self, event: dict) -> None:
        seq = event.get("seq_num")
        if seq is not None and any(existing.get("seq_num") == seq for existing in self._events):
            return
        self._events.append(event)
        self._events.sort(key=lambda item: item.get("seq_num", 0))
        self.update()

    def clear_local(self) -> None:
        self._events = []
        self.update()

    def export_png(self, path: str) -> bool:
        image = QImage(self.size(), QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        self._paint_events(painter)
        painter.end()
        return image.save(path, "PNG")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if self._tool == "text":
            text, ok = QInputDialog.getText(self, "Text", "Enter text:")
            if ok and text.strip():
                self.event_ready.emit("TEXT", {
                    "x": pos.x(),
                    "y": pos.y(),
                    "text": text.strip(),
                    "color": self._color.name(),
                    "font_size": max(12, self._width * 6),
                })
            return
        if self._tool == "eraser":
            self.event_ready.emit("ERASE", {
                "x": pos.x(),
                "y": pos.y(),
                "radius": max(4, self._width * 3),
            })
            return
        self._drawing = True
        self._start = pos
        self._preview = pos
        self._points = [{"x": pos.x(), "y": pos.y()}]

    def mouseMoveEvent(self, event):  # noqa: N802
        if not self._drawing:
            return
        pos = event.position()
        self._preview = pos
        if self._tool == "pen":
            self._points.append({"x": pos.x(), "y": pos.y()})
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._drawing:
            return
        pos = event.position()
        self._drawing = False
        if self._tool == "pen":
            if len(self._points) > 1:
                self.event_ready.emit("STROKE", {
                    "points": self._points,
                    "color": self._color.name(),
                    "width": self._width,
                })
        elif self._tool in {"rect", "oval"} and self._start is not None:
            rect = normalize_rect(self._start.x(), self._start.y(), pos.x(), pos.y())
            if rect["w"] >= 2 and rect["h"] >= 2:
                rect.update({"color": self._color.name(), "width": self._width})
                self.event_ready.emit("RECT" if self._tool == "rect" else "OVAL", rect)
        self._start = None
        self._preview = None
        self._points = []
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("white"))
        self._paint_events(painter)
        self._paint_preview(painter)
        painter.end()

    def _paint_events(self, painter: QPainter) -> None:
        undone = {
            event.get("payload", {}).get("target_seq_num")
            for event in self._events
            if event.get("event_type") == "UNDO"
        }
        for event in self._events:
            event_type = event.get("event_type")
            if event.get("seq_num") in undone:
                continue
            if event_type == "UNDO":
                continue
            if event_type == "CLEAR":
                painter.fillRect(self.rect(), QColor("white"))
                continue
            self._paint_one(painter, event_type, event.get("payload", {}))

    def _paint_one(self, painter: QPainter, event_type: str, payload: dict) -> None:
        if event_type == "STROKE":
            points = payload.get("points", [])
            if len(points) < 2:
                return
            pen = QPen(QColor(payload.get("color", "#111111")), int(payload.get("width", 3)))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            for a, b in zip(points, points[1:]):
                painter.drawLine(QPointF(a["x"], a["y"]), QPointF(b["x"], b["y"]))
        elif event_type in {"RECT", "OVAL"}:
            painter.setPen(QPen(QColor(payload.get("color", "#111111")), int(payload.get("width", 3))))
            x, y, w, h = payload.get("x", 0), payload.get("y", 0), payload.get("w", 0), payload.get("h", 0)
            if event_type == "RECT":
                painter.drawRect(int(x), int(y), int(w), int(h))
            else:
                painter.drawEllipse(int(x), int(y), int(w), int(h))
        elif event_type == "TEXT":
            painter.setPen(QPen(QColor(payload.get("color", "#111111"))))
            painter.setFont(QFont("Arial", int(payload.get("font_size", 18))))
            painter.drawText(QPointF(payload.get("x", 0), payload.get("y", 0)), payload.get("text", ""))
        elif event_type == "ERASE":
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("white"))
            r = float(payload.get("radius", 16))
            x = float(payload.get("x", 0))
            y = float(payload.get("y", 0))
            painter.drawEllipse(QPointF(x, y), r, r)

    def _paint_preview(self, painter: QPainter) -> None:
        if not self._drawing or self._start is None or self._preview is None:
            return
        painter.setPen(QPen(self._color, self._width, Qt.PenStyle.DashLine))
        if self._tool == "pen" and len(self._points) > 1:
            for a, b in zip(self._points, self._points[1:]):
                painter.drawLine(QPointF(a["x"], a["y"]), QPointF(b["x"], b["y"]))
        elif self._tool in {"rect", "oval"}:
            rect = normalize_rect(self._start.x(), self._start.y(), self._preview.x(), self._preview.y())
            if self._tool == "rect":
                painter.drawRect(int(rect["x"]), int(rect["y"]), int(rect["w"]), int(rect["h"]))
            else:
                painter.drawEllipse(int(rect["x"]), int(rect["y"]), int(rect["w"]), int(rect["h"]))


class WhiteboardWidget(QWidget):
    send_packet = pyqtSignal(int, dict)

    def __init__(self, user_id: int, parent=None) -> None:
        super().__init__(parent)
        self._user_id = user_id
        self._room_code: str | None = None
        self._client_seq = 0
        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._status = QLabel("")
        self._status.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._status)

        toolbar = QHBoxLayout()
        self._buttons: dict[str, QPushButton] = {}
        for label, tool in [("Pen", "pen"), ("Rect", "rect"), ("Oval", "oval"), ("Text", "text"), ("Eraser", "eraser")]:
            btn = QPushButton(label)
            btn.clicked.connect(lambda _checked=False, t=tool: self._set_tool(t))
            self._buttons[tool] = btn
            toolbar.addWidget(btn)

        color_btn = QPushButton("Color")
        color_btn.clicked.connect(self._pick_color)
        toolbar.addWidget(color_btn)

        toolbar.addWidget(QLabel("Width"))
        self._width = QSpinBox()
        self._width.setRange(1, 40)
        self._width.setValue(3)
        self._width.valueChanged.connect(self._set_width)
        toolbar.addWidget(self._width)

        undo_btn = QPushButton("Undo")
        undo_btn.clicked.connect(self._undo)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self._clear)
        export_btn = QPushButton("Export PNG")
        export_btn.clicked.connect(self._export)
        toolbar.addStretch()
        toolbar.addWidget(undo_btn)
        toolbar.addWidget(clear_btn)
        toolbar.addWidget(export_btn)
        layout.addLayout(toolbar)

        self._canvas = WhiteboardCanvas(self)
        self._canvas.event_ready.connect(self._send_event)
        layout.addWidget(self._canvas, stretch=1)
        self._set_tool("pen")

    def set_current_room(self, room_code: str | None) -> None:
        if room_code == self._room_code:
            return
        self._room_code = room_code
        self._canvas.clear_local()
        self._refresh_status()

    def on_sync(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        self._canvas.replace_events(payload.get("events", []))
        self._refresh_status()

    def on_draw_broadcast(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        self._canvas.add_event(payload)
        self._refresh_status()

    def on_file_transfer(self, payload: dict) -> None:
        # Server-side export currently returns the event log. The primary PNG
        # export is local because the client has the rendered canvas.
        if payload.get("room_code") == self._room_code:
            self._refresh_status()

    def _set_tool(self, tool: str) -> None:
        self._canvas.set_tool(tool)
        for key, btn in self._buttons.items():
            btn.setEnabled(key != tool)

    def _pick_color(self) -> None:
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self._canvas.set_color(color)

    def _set_width(self, value: int) -> None:
        self._canvas.set_width(value)

    def _send_event(self, event_type: str, payload: dict) -> None:
        if not self._room_code:
            QMessageBox.information(self, "Whiteboard", "Pick a room in the Chat tab first.")
            return
        self._client_seq += 1
        self.send_packet.emit(
            int(PacketType.DRAW_EVENT),
            make_draw_packet(self._room_code, event_type, payload, self._client_seq),
        )

    def _undo(self) -> None:
        target = last_undoable_seq(self._canvas.events(), self._user_id)
        if target is None:
            return
        self._send_event("UNDO", {"target_seq_num": target})

    def _clear(self) -> None:
        if QMessageBox.question(self, "Clear whiteboard", "Clear the whiteboard for everyone?") == QMessageBox.StandardButton.Yes:
            self._send_event("CLEAR", {})

    def _export(self) -> None:
        if not self._room_code:
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Whiteboard",
            f"whiteboard-{self._room_code}.png",
            "PNG Images (*.png)",
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if not self._canvas.export_png(path):
            QMessageBox.warning(self, "Export Whiteboard", "Could not export the PNG file.")

    def _refresh_status(self) -> None:
        if not self._room_code:
            self._status.setText("Select a room in the Chat tab to use the whiteboard.")
        else:
            self._status.setText(f"Room {self._room_code}: {len(self._canvas.events())} whiteboard events.")
