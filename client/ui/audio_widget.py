"""Audio call controls and subtitle display."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QListWidget, QListWidgetItem, QMessageBox,
)

from shared.constants import PacketType
from client.features.audio_engine import AudioEngine


class AudioWidget(QWidget):
    send_packet = pyqtSignal(int, dict)

    def __init__(self, connection_manager, user_id: int, username: str, parent=None) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._user_id = user_id
        self._username = username
        self._room_code: str | None = None
        self._engine = AudioEngine(connection_manager, self)
        self._engine.level_changed.connect(self._on_level_changed)
        self._engine.playback_queue_changed.connect(self._on_queue_changed)
        self._engine.stopped.connect(self._on_engine_stopped)
        self._build_ui()
        self._refresh_controls()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._status_label = QLabel("Select a room before joining audio.")
        self._status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._status_label)

        controls = QHBoxLayout()
        self._join_btn = QPushButton("Join Audio")
        self._join_btn.clicked.connect(self._on_join_clicked)
        self._leave_btn = QPushButton("Leave Audio")
        self._leave_btn.clicked.connect(self._on_leave_clicked)
        self._mute_btn = QPushButton("Mute")
        self._mute_btn.clicked.connect(self._on_mute_clicked)
        controls.addWidget(self._join_btn)
        controls.addWidget(self._leave_btn)
        controls.addWidget(self._mute_btn)
        controls.addStretch()
        layout.addLayout(controls)

        meter_row = QHBoxLayout()
        meter_row.addWidget(QLabel("Mic level"))
        self._level = QProgressBar()
        self._level.setRange(0, 100)
        self._level.setTextVisible(False)
        meter_row.addWidget(self._level)
        meter_row.addWidget(QLabel("Playback buffer"))
        self._queue_label = QLabel("0")
        self._queue_label.setFixedWidth(24)
        meter_row.addWidget(self._queue_label)
        layout.addLayout(meter_row)

        layout.addWidget(QLabel("Subtitles"))
        self._subtitle_list = QListWidget()
        self._subtitle_list.setAlternatingRowColors(True)
        layout.addWidget(self._subtitle_list, stretch=1)

        self._hint_label = QLabel(
            "Subtitles appear when the server is started with QUICKONNECT_STT_ENABLED=1."
        )
        self._hint_label.setStyleSheet("color: #777;")
        self._hint_label.setWordWrap(True)
        layout.addWidget(self._hint_label)

    def set_current_room(self, room_code: str | None) -> None:
        if room_code == self._room_code:
            return
        if self._engine.is_running():
            self._engine.stop("Switched room")
        self._room_code = room_code
        self._engine.set_room(room_code)
        self._subtitle_list.clear()
        self._refresh_controls()

    def on_mixed_audio(self, payload: dict) -> None:
        self._engine.handle_mixed_audio(payload)

    def on_subtitle(self, payload: dict) -> None:
        room_code = str(payload.get("room_code", "")).strip()
        speaker = payload.get("speaker_username", "speaker")
        text = payload.get("text", "").strip()
        lines = payload.get("lines", [])
        room_suffix = f" ({room_code})" if room_code and room_code != self._room_code else ""
        if isinstance(lines, list) and lines:
            rendered_lines = []
            for line in lines:
                if not isinstance(line, dict):
                    continue
                lang = str(line.get("lang", "")).strip() or "?"
                value = str(line.get("text", "")).strip()
                if value:
                    rendered_lines.append(f"{lang}: {value}")
            if rendered_lines:
                item = QListWidgetItem(f"{speaker}{room_suffix}\n" + "\n".join(rendered_lines))
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
                item.setSizeHint(QSize(0, 22 * (len(rendered_lines) + 1)))
                self._subtitle_list.addItem(item)
                self._subtitle_list.scrollToBottom()
                while self._subtitle_list.count() > 50:
                    self._subtitle_list.takeItem(0)
                return

        if not text:
            return
        task = payload.get("task", "transcribe")
        suffix = " → EN" if task == "translate" else ""
        item = QListWidgetItem(f"{speaker}{room_suffix}{suffix}: {text}")
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
        self._subtitle_list.addItem(item)
        self._subtitle_list.scrollToBottom()
        while self._subtitle_list.count() > 50:
            self._subtitle_list.takeItem(0)

    def shutdown(self) -> None:
        if self._engine.is_running():
            self._engine.stop("Shutdown")

    def _on_join_clicked(self) -> None:
        if not self._room_code:
            QMessageBox.information(self, "Audio", "Pick a room in the Chat tab first.")
            return
        ok, error = self._engine.start(self._room_code)
        if not ok:
            QMessageBox.warning(self, "Audio", error or "Could not start audio.")
            return
        self._refresh_controls()

    def _on_leave_clicked(self) -> None:
        self._engine.stop("User left audio")
        self._refresh_controls()

    def _on_mute_clicked(self) -> None:
        self._engine.set_muted(not self._engine.is_muted())
        self._refresh_controls()

    def _on_level_changed(self, value: int) -> None:
        self._level.setValue(value)

    def _on_queue_changed(self, value: int) -> None:
        self._queue_label.setText(str(value))

    def _on_engine_stopped(self, reason: str) -> None:
        if reason and reason not in ("User left audio", "Shutdown", "Switched room"):
            self._status_label.setText(reason)
        self._level.setValue(0)
        self._queue_label.setText("0")
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        in_room = self._room_code is not None
        running = self._engine.is_running()
        muted = self._engine.is_muted()

        self._join_btn.setEnabled(in_room and not running)
        self._leave_btn.setEnabled(running)
        self._mute_btn.setEnabled(running)
        self._mute_btn.setText("Unmute" if muted else "Mute")

        if not in_room:
            self._status_label.setText("Select a room in the Chat tab before joining audio.")
        elif running:
            state = "muted" if muted else "live"
            self._status_label.setText(f"Room {self._room_code}: audio {state}.")
        else:
            self._status_label.setText(f"Room {self._room_code}: audio not joined.")
