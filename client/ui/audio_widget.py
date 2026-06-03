"""Audio call controls and live subtitle list."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QProgressBar,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
)

from client.features.audio_engine import AudioEngine


class AudioWidget(QWidget):
    """Small UI surface for room audio and translated subtitles."""

    send_packet = pyqtSignal(int, dict)

    def __init__(self, connection_manager, user_id: int, username: str, parent=None) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._user_id = user_id
        self._username = username
        self._room_code: str | None = None
        self._last_error = ""
        self._engine = AudioEngine(connection_manager)
        self._build_ui()
        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._refresh_diagnostics)
        self._diag_timer.start(250)
        self._refresh_controls()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)

        self._status_label = QLabel("Select a room in Chat to start audio.")
        self._status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._status_label)

        controls = QHBoxLayout()
        self._join_btn = QPushButton("Join Audio")
        self._join_btn.clicked.connect(lambda: self._start_audio(show_dialog=True))
        self._leave_btn = QPushButton("Leave Audio")
        self._leave_btn.clicked.connect(self._leave_audio)
        self._mute_btn = QPushButton("Mute")
        self._mute_btn.clicked.connect(self._toggle_mute)
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
        meter_row.addWidget(self._level, stretch=1)
        self._queue_label = QLabel("Buffer: 0")
        meter_row.addWidget(self._queue_label)
        layout.addLayout(meter_row)

        layout.addWidget(QLabel("Subtitles"))
        self._subtitle_list = QListWidget()
        self._subtitle_list.setAlternatingRowColors(True)
        layout.addWidget(self._subtitle_list, stretch=1)

    def set_current_room(self, room_code: str | None) -> None:
        room_code = str(room_code).strip() if room_code else None
        if room_code == self._room_code:
            return
        if self._engine.is_running():
            self._engine.stop()
        self._room_code = room_code
        self._last_error = ""
        self._subtitle_list.clear()
        if self._room_code:
            self._start_audio(show_dialog=False)
        self._refresh_controls()

    def on_mixed_audio(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        pcm_b64 = payload.get("pcm_b64", "")
        if pcm_b64:
            self._engine.feed_playback(pcm_b64)

    def on_subtitle(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        speaker = str(payload.get("speaker_username", "") or "speaker")
        rendered_lines = self._render_subtitle_lines(payload)
        if not rendered_lines:
            return

        item = QListWidgetItem(f"{speaker}\n" + "\n".join(rendered_lines))
        item.setTextAlignment(Qt.AlignmentFlag.AlignLeft)
        item.setSizeHint(QSize(0, 22 * (len(rendered_lines) + 1)))
        self._subtitle_list.addItem(item)
        self._subtitle_list.scrollToBottom()
        while self._subtitle_list.count() > 50:
            self._subtitle_list.takeItem(0)

    def shutdown(self) -> None:
        if self._engine.is_running():
            self._engine.stop()
        self._diag_timer.stop()

    def _start_audio(self, *, show_dialog: bool) -> None:
        if not self._room_code:
            if show_dialog:
                QMessageBox.information(self, "Audio", "Select a room in Chat first.")
            return
        if self._engine.is_running():
            self._refresh_controls()
            return

        ok, error = self._engine.start(self._room_code)
        if not ok:
            self._last_error = error or "Audio unavailable."
            self._status_label.setText(self._last_error)
            if show_dialog:
                QMessageBox.warning(self, "Audio", self._last_error)
            self._refresh_controls()
            return
        self._last_error = ""
        if error:
            self._status_label.setText(error)
        self._refresh_controls()

    def _leave_audio(self) -> None:
        self._engine.stop()
        self._refresh_controls()

    def _toggle_mute(self) -> None:
        self._engine.set_muted(not self._engine.is_muted())
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
            self._status_label.setText("Select a room in Chat to start audio.")
        elif running:
            state = "muted" if muted else "live"
            self._status_label.setText(f"Room {self._room_code}: audio {state}.")
        elif self._last_error:
            self._status_label.setText(self._last_error)
        else:
            self._status_label.setText(f"Room {self._room_code}: audio stopped.")

    def _refresh_diagnostics(self) -> None:
        diag = self._engine.diagnostics()
        rms = int(diag.get("last_rms", 0))
        level = max(0, min(100, int((rms / 32768.0) * 200)))
        self._level.setValue(level if diag.get("running") else 0)
        self._queue_label.setText(f"Buffer: {diag.get('playback_queue', 0)}")

    @staticmethod
    def _render_subtitle_lines(payload: dict) -> list[str]:
        lines = payload.get("lines")
        rendered: list[str] = []
        if isinstance(lines, list):
            for line in lines:
                if not isinstance(line, dict):
                    continue
                lang = str(line.get("lang", "")).strip() or "?"
                text = str(line.get("text", "")).strip()
                if text:
                    rendered.append(f"{lang}: {text}")
            if rendered:
                return rendered

        text = str(payload.get("text", "")).strip()
        translated = str(payload.get("translated_text", "")).strip()
        source_lang = str(payload.get("source_lang", "")).strip() or "auto"
        target_lang = str(payload.get("target_lang", "")).strip()

        if text:
            rendered.append(f"{source_lang}: {text}")
        if translated:
            rendered.append(f"{target_lang or 'translated'}: {translated}")
        return rendered
