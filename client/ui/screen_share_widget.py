"""Dedicated screen-sharing tab.

Layout (top-to-bottom):
  - Status bar — which room, who is sharing, who has remote control.
  - Frame view — a QLabel that holds the most recent decoded frame, scaled
    to fit while preserving aspect ratio. Receives input events when the
    local user has been granted remote control.
  - Controls — Share / Stop / Request Control / Revoke buttons.

The widget is purely a view: all network traffic happens through the
ConnectionManager passed in at construction. All packet receipt is
pushed in from main_window via the on_packet() entry points.
"""

import logging

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage, QPainter, QColor
import base64
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QMessageBox, QStackedWidget, QFileDialog,
)

from shared.constants import PacketType
from client.features.screen_engine import ScreenCaptureEngine, decode_jpeg
from client.features.remote_control import RemoteControlSender, RemoteControlExecutor
from client.features.audio_engine import AudioEngine
from client.features.whiteboard_engine import WhiteboardEngine
from client.ui.subtitle_widget import SubtitleWidget
from client.ui.whiteboard_widget import WhiteboardWidget

logger = logging.getLogger(__name__)


class FrameLabel(QLabel):
    """QLabel that holds the latest frame and reports its drawn geometry."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(320, 180))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #111; color: #888;")
        self.setText("No active screen share")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._source: QImage | None = None
        self._draw_geom: tuple[int, int, int, int] | None = None  # ox,oy,w,h

    def set_frame(self, image: QImage) -> None:
        self._source = image
        self._refresh_pixmap()

    def clear_frame(self) -> None:
        self._source = None
        self._draw_geom = None
        self.setPixmap(QPixmap())
        self.setText("No active screen share")

    def displayed_geometry(self) -> tuple[int, int, int, int] | None:
        return self._draw_geom

    def resizeEvent(self, event):  # noqa: N802
        self._refresh_pixmap()
        # Reposition subtitle overlay (if present as child widget)
        for child in self.children():
            if hasattr(child, 'show_subtitle'):  # duck-type check for SubtitleWidget
                cw = child.width()
                ch = child.sizeHint().height()
                x = (self.width() - cw) // 2
                y = self.height() - ch - 12
                child.move(max(0, x), max(0, y))
        super().resizeEvent(event)

    def _refresh_pixmap(self) -> None:
        if self._source is None or self._source.isNull():
            return
        avail = self.size()
        scaled = self._source.scaled(
            avail, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pix = QPixmap.fromImage(scaled)
        self.setPixmap(pix)
        # Compute letterbox offsets so RemoteControlSender can map mouse coords.
        ox = (avail.width() - scaled.width()) // 2
        oy = (avail.height() - scaled.height()) // 2
        self._draw_geom = (ox, oy, scaled.width(), scaled.height())


class ScreenShareWidget(QWidget):
    """The Screen tab. One instance per main window."""

    send_packet = pyqtSignal(int, dict)

    def __init__(self, connection_manager, user_id: int, username: str, parent=None) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._user_id = user_id
        self._username = username
        self._room_code: str | None = None

        # Share state for the currently-active share (any participant).
        self._sharer_user_id: int | None = None
        self._sharer_username: str = ""
        self._controller_user_id: int | None = None
        self._controller_username: str = ""

        self._engine = ScreenCaptureEngine(connection_manager, self)
        self._engine.stopped.connect(self._on_engine_stopped)
        self._engine.frame_captured.connect(self._on_local_frame_captured)

        self._executor = RemoteControlExecutor()
        self._remote_sender = RemoteControlSender(
            connection_manager,
            self._current_room,
            lambda: self._frame_label.displayed_geometry() if self._frame_label else None,
            self,
        )

        self._audio_engine = AudioEngine(connection_manager)
        self._whiteboard_engine = WhiteboardEngine(connection_manager, username)

        self._build_ui()
        self._refresh_controls()

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._status_label = QLabel("Select a room to share or view a screen.")
        self._status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._status_label)

        # Stacked view containing Screen Frame and Whiteboard
        self._stacked_view = QStackedWidget(self)
        self._frame_label = FrameLabel(self)
        self._whiteboard_widget = WhiteboardWidget(self)
        self._whiteboard_widget.draw_created.connect(self._on_local_draw)
        self._whiteboard_widget.export_requested.connect(self._on_local_export)

        self._stacked_view.addWidget(self._frame_label)
        self._stacked_view.addWidget(self._whiteboard_widget)
        layout.addWidget(self._stacked_view, stretch=1)

        # Controls row 1: share / stop / request control / revoke + audio mute
        btn_row = QHBoxLayout()
        self._share_btn = QPushButton("Share Screen")
        self._share_btn.clicked.connect(self._on_share_clicked)
        self._stop_btn = QPushButton("Stop Sharing")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        
        self._whiteboard_btn = QPushButton("🎨 Whiteboard")
        self._whiteboard_btn.setCheckable(True)
        self._whiteboard_btn.clicked.connect(self._on_whiteboard_toggled)

        self._request_btn = QPushButton("Request Control")
        self._request_btn.clicked.connect(self._on_request_clicked)
        self._revoke_btn = QPushButton("Revoke Control")
        self._revoke_btn.clicked.connect(self._on_revoke_clicked)

        self._mute_btn = QPushButton("\U0001F3A4 Mute")
        self._mute_btn.setCheckable(True)
        self._mute_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; }"
            "QPushButton:checked { background-color: #c0392b; color: white; }"
        )
        self._mute_btn.clicked.connect(self._on_mute_toggled)

        btn_row.addWidget(self._share_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addWidget(self._whiteboard_btn)
        btn_row.addWidget(self._mute_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._request_btn)
        btn_row.addWidget(self._revoke_btn)
        layout.addLayout(btn_row)

        # Controls row 2: quality + FPS sliders
        tune_row = QHBoxLayout()
        tune_row.addWidget(QLabel("FPS"))
        self._fps_slider = QSlider(Qt.Orientation.Horizontal)
        self._fps_slider.setRange(5, 30)
        self._fps_slider.setValue(30)
        self._fps_slider.setFixedWidth(120)
        self._fps_slider.valueChanged.connect(self._on_fps_changed)
        tune_row.addWidget(self._fps_slider)
        self._fps_value = QLabel("30")
        tune_row.addWidget(self._fps_value)

        tune_row.addSpacing(24)
        tune_row.addWidget(QLabel("JPEG quality"))
        self._quality_slider = QSlider(Qt.Orientation.Horizontal)
        self._quality_slider.setRange(30, 95)
        self._quality_slider.setValue(70)
        self._quality_slider.setFixedWidth(120)
        self._quality_slider.valueChanged.connect(self._on_quality_changed)
        tune_row.addWidget(self._quality_slider)
        self._quality_value = QLabel("70")
        tune_row.addWidget(self._quality_value)

        tune_row.addSpacing(24)
        tune_row.addWidget(QLabel("Scale"))
        self._scale_slider = QSlider(Qt.Orientation.Horizontal)
        self._scale_slider.setRange(25, 100)  # percent
        self._scale_slider.setValue(100)
        self._scale_slider.setFixedWidth(120)
        self._scale_slider.valueChanged.connect(self._on_scale_changed)
        tune_row.addWidget(self._scale_slider)
        self._scale_value = QLabel("100%")
        tune_row.addWidget(self._scale_value)
        tune_row.addStretch()
        layout.addLayout(tune_row)

        self._diag_label = QLabel("")
        self._diag_label.setStyleSheet("color: #888;")
        layout.addWidget(self._diag_label)

        # Subtitle overlay (positioned manually on top of the stacked view)
        self._subtitle_widget = SubtitleWidget(self._stacked_view)
        self._subtitle_widget.setFixedWidth(600)
        self._subtitle_widget.hide()

    # ------------------------------------------------------------------
    # External entry points (called by main_window)
    # ------------------------------------------------------------------

    def set_current_room(self, room_code: str | None) -> None:
        if room_code == self._room_code:
            return
        # Switching rooms drops any local-side state we know about; the
        # server will tell us the new room's share state via the ROOM_STATE
        # packet that follows the JOIN_ROOM the chat widget just sent.
        if self._engine.is_running():
            self._engine.stop("Switched room")
            self._send_screen_stop(self._room_code)
        # Stop audio in the old room
        self._audio_engine.stop()
        self._whiteboard_widget.clear_all()
        self._whiteboard_btn.setChecked(False)
        self._stacked_view.setCurrentIndex(0)
        self._room_code = room_code
        self._clear_share_state()
        self._refresh_controls()
        # Start audio in the new room (if we have one)
        if room_code:
            ok, error = self._audio_engine.start(room_code)
            if not ok:
                logger.warning("Audio engine failed to start: %s", error)

    def handle_room_state_screen(self, screen_info: dict | None) -> None:
        """Apply any active share carried by a ROOM_STATE payload."""
        if not screen_info:
            self._clear_share_state()
            self._refresh_controls()
            return
        self._sharer_user_id = screen_info.get("sharer_user_id")
        self._sharer_username = screen_info.get("sharer_username", "")
        self._controller_user_id = screen_info.get("controller_user_id")
        self._controller_username = screen_info.get("controller_username", "") or ""
        self._refresh_controls()

    def on_screen_start(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        self._sharer_user_id = payload.get("sharer_user_id")
        self._sharer_username = payload.get("sharer_username", "")
        self._controller_user_id = None
        self._controller_username = ""
        self._refresh_controls()
        # The sharer's own engine was already started by _on_share_clicked
        # before SCREEN_START was sent. Nothing extra to do for them here.

    def on_screen_stop(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        # If WE were the sharer (e.g. cleanup-triggered stop) bring the
        # capture engine down.
        if self._engine.is_running() and self._sharer_user_id == self._user_id:
            self._engine.stop("Stop received from server")
        self._executor.stop()
        self._clear_share_state()
        self._frame_label.clear_frame()
        self._refresh_controls()

    def on_screen_relay(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        jpeg_b64 = payload.get("jpeg_b64", "")
        if not jpeg_b64:
            return
        image = decode_jpeg(jpeg_b64)
        if image is None or image.isNull():
            return
        self._frame_label.set_frame(image)

    def on_remote_request(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        requester_username = payload.get("requester_username", "someone")
        requester_user_id = payload.get("requester_user_id")
        if requester_user_id is None:
            return
        # Only fire the dialog if WE are the sharer.
        if self._sharer_user_id != self._user_id:
            return
        if not self._executor.is_running():
            QMessageBox.warning(
                self,
                "Remote Control",
                "Remote control is not available on this machine.",
            )
            self.send_packet.emit(int(PacketType.REMOTE_GRANT), {
                "room_code": self._room_code,
                "granted": False,
                "target_user_id": requester_user_id,
            })
            return
        reply = QMessageBox.question(
            self,
            "Remote Control Request",
            f"{requester_username} is asking for remote control of your screen.\n"
            f"Allow them to control your mouse and keyboard?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        granted = (reply == QMessageBox.StandardButton.Yes)
        self.send_packet.emit(int(PacketType.REMOTE_GRANT), {
            "room_code": self._room_code,
            "granted": granted,
            "target_user_id": requester_user_id,
        })

    def on_remote_grant(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        granted = bool(payload.get("granted", False))
        target_user_id = payload.get("target_user_id")
        target_username = payload.get("target_username", "") or ""

        # Local effect on the controller side:
        if granted and target_user_id == self._user_id:
            self._controller_user_id = self._user_id
            self._controller_username = self._username
            self._enable_remote_input()
        elif not granted and self._controller_user_id == self._user_id:
            # We had control and just got revoked/denied.
            self._disable_remote_input()
            self._controller_user_id = None
            self._controller_username = ""
        else:
            self._controller_user_id = target_user_id if granted else None
            self._controller_username = target_username if granted else ""

        if self._sharer_user_id == self._user_id and granted and not self._executor.is_running():
            self.send_packet.emit(int(PacketType.REMOTE_GRANT), {
                "room_code": self._room_code,
                "granted": False,
                "target_user_id": None,
            })
            QMessageBox.warning(
                self, "Remote control",
                "Remote control is not running on this machine.",
            )
            return
        self._refresh_controls()

    def on_remote_event(self, payload: dict) -> None:
        # Only the sharer ever receives REMOTE_EVENT from the server.
        if self._sharer_user_id != self._user_id:
            return
        if payload.get("room_code") != self._room_code:
            return
        self._executor.submit(payload)

    def on_mixed_audio(self, payload: dict) -> None:
        """Handle incoming MIXED_AUDIO packet — feed to playback."""
        if payload.get("room_code") != self._room_code:
            return
        pcm_b64 = payload.get("pcm_b64", "")
        if pcm_b64:
            self._audio_engine.feed_playback(pcm_b64)

    def on_subtitle(self, payload: dict) -> None:
        """Handle incoming SUBTITLE packet — show subtitle overlay."""
        if payload.get("room_code") != self._room_code:
            return
        speaker = payload.get("speaker_username", "")
        text = payload.get("text", "")
        translated = payload.get("translated_text", "")
        if text:
            self._subtitle_widget.show_subtitle(speaker, text, translated)
            self._position_subtitle()

    def shutdown(self) -> None:
        """Called on logout / disconnect — stop any local threads."""
        if self._engine.is_running():
            self._engine.stop("Shutdown")
        self._audio_engine.stop()
        self._executor.stop()
        self._remote_sender.detach()
        self._subtitle_widget.clear()
        self._whiteboard_widget.clear_all()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_share_clicked(self) -> None:
        try:
            self._start_screen_share()
        except BaseException as exc:
            logger.exception("Unexpected error while starting screen share")
            self._engine.stop(f"Screen share startup failed: {exc}")
            self._executor.stop()
            self._clear_share_state()
            self._frame_label.clear_frame()
            self._refresh_controls()
            QMessageBox.critical(
                self,
                "Screen Share",
                f"Could not start screen sharing:\n{exc}",
            )

    def _start_screen_share(self) -> None:
        if not self._room_code:
            QMessageBox.information(self, "Screen Share",
                                    "Pick a room in the Chat tab first.")
            return
        if self._sharer_user_id is not None:
            QMessageBox.information(self, "Screen Share",
                                    f"{self._sharer_username} is already sharing.")
            return
        ok, error = self._engine.start(self._room_code)
        if not ok:
            logger.error("Screen share startup failed: %s", error or "Could not start capture.")
            QMessageBox.warning(self, "Screen Share", error or "Could not start capture.")
            return
        executor_ok, executor_error = self._executor.start()
        if not executor_ok:
            logger.warning("Remote control executor unavailable: %s", executor_error)
            QMessageBox.warning(
                self, "Remote Control",
                executor_error or "Remote control is not available on this machine.",
            )
        # Optimistically mark ourselves as the sharer; SCREEN_START broadcast
        # will confirm. If the server rejects (race against another sharer)
        # an ERROR comes back and main_window surfaces it.
        self._sharer_user_id = self._user_id
        self._sharer_username = self._username
        self.send_packet.emit(int(PacketType.SCREEN_START), {"room_code": self._room_code})
        self._refresh_controls()

    def _on_stop_clicked(self) -> None:
        if not self._room_code:
            return
        if self._sharer_user_id != self._user_id:
            return
        self._engine.stop("User stopped")
        self._executor.stop()
        self._send_screen_stop(self._room_code)
        self._clear_share_state()
        self._frame_label.clear_frame()
        self._refresh_controls()

    def _on_request_clicked(self) -> None:
        if not self._room_code or self._sharer_user_id is None:
            return
        if self._sharer_user_id == self._user_id:
            return
        if self._controller_user_id is not None:
            QMessageBox.information(self, "Remote Control",
                                    "Someone already has control of this share.")
            return
        self.send_packet.emit(int(PacketType.REMOTE_REQUEST), {"room_code": self._room_code})

    def _on_revoke_clicked(self) -> None:
        if not self._room_code:
            return
        # The sharer revokes for a guest controller. The controller revokes
        # for themselves (the server only honors revoke from the sharer,
        # but we also let the controller signal a self-revoke by sending the
        # same packet — the server handler treats granted=False as revoke).
        if self._sharer_user_id == self._user_id:
            self.send_packet.emit(int(PacketType.REMOTE_GRANT), {
                "room_code": self._room_code,
                "granted": False,
                "target_user_id": None,
            })
        elif self._controller_user_id == self._user_id:
            # Controller-initiated revoke: tell the sharer via a request
            # for control with the sentinel "release" — simplest reuse of
            # the existing surface is to just disable local input and let
            # the sharer be the source of truth via their revoke button.
            # We toggle our local sender off; the server-side state will
            # be cleared next time the sharer revokes or share ends.
            self._disable_remote_input()
            self._controller_user_id = None
            self._controller_username = ""
            self._refresh_controls()

    def _on_mute_toggled(self) -> None:
        muted = self._mute_btn.isChecked()
        self._audio_engine.set_muted(muted)
        self._mute_btn.setText("\U0001F507 Unmute" if muted else "\U0001F3A4 Mute")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _current_room(self) -> str | None:
        return self._room_code

    def _send_screen_stop(self, room_code: str | None) -> None:
        if not room_code:
            return
        self.send_packet.emit(int(PacketType.SCREEN_STOP), {"room_code": room_code})

    def _clear_share_state(self) -> None:
        self._sharer_user_id = None
        self._sharer_username = ""
        self._controller_user_id = None
        self._controller_username = ""
        self._disable_remote_input()

    def _refresh_controls(self) -> None:
        in_room = self._room_code is not None
        someone_sharing = self._sharer_user_id is not None
        we_share = self._sharer_user_id == self._user_id
        we_control = self._controller_user_id == self._user_id

        self._share_btn.setEnabled(in_room and not someone_sharing)
        self._stop_btn.setEnabled(we_share)
        self._mute_btn.setEnabled(in_room)
        self._request_btn.setEnabled(
            in_room and someone_sharing and not we_share and self._controller_user_id is None,
        )
        self._revoke_btn.setEnabled(
            (we_share and self._controller_user_id is not None) or we_control,
        )

        if not in_room:
            self._status_label.setText("Select a room in the Chat tab to share or view its screen.")
        elif not someone_sharing:
            self._status_label.setText(f"Room {self._room_code}: no active screen share.")
        else:
            who = "You" if we_share else (self._sharer_username or "?")
            ctrl = ""
            if self._controller_user_id is not None:
                ctrl_who = "you" if we_control else (self._controller_username or "?")
                ctrl = f"  ·  remote control: {ctrl_who}"
            self._status_label.setText(f"Room {self._room_code}: {who} is sharing{ctrl}")

    def _on_engine_stopped(self, reason: str) -> None:
        normal_reasons = {
            "User stopped",
            "Stop received from server",
            "Switched room",
            "Shutdown",
        }
        if not reason or reason in normal_reasons:
            return

    def _on_frame_dropped(self, total: int) -> None:
        self._diag_label.setText(f"Dropped frames (queue full): {total}")

    # ------------------------------------------------------------------
    # Whiteboard handlers
    # ------------------------------------------------------------------

    def _on_whiteboard_toggled(self) -> None:
        show_wb = self._whiteboard_btn.isChecked()
        self._stacked_view.setCurrentIndex(1 if show_wb else 0)
        self._refresh_controls()
        if show_wb:
            # Force graphics view fit-in-view update
            self._whiteboard_widget.view.fitInView(
                self._whiteboard_widget.scene.sceneRect(),
                Qt.AspectRatioMode.KeepAspectRatio
            )

    def _on_local_draw(self, event_type: str, payload: dict) -> None:
        """Called when a local shape is completed on the whiteboard widget."""
        if not self._room_code:
            return
        self._whiteboard_engine.send_draw_event(self._room_code, event_type, payload)

    def _on_local_export(self) -> None:
        """Export the whiteboard canvas as PNG client-side (local rendering)."""
        scene = self._whiteboard_widget.scene
        # Create image container with canvas dimensions
        image = QImage(
            int(scene.width()),
            int(scene.height()),
            QImage.Format.Format_ARGB32_Premultiplied
        )
        image.fill(QColor("#1e1e1e"))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scene.render(painter)
        painter.end()

        # Prompt user to choose save path
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Whiteboard PNG Export",
            f"whiteboard_{self._room_code}.png",
            "PNG Images (*.png);;All Files (*)",
        )
        if path:
            try:
                if image.save(path, "PNG"):
                    QMessageBox.information(
                        self,
                        "Whiteboard Saved",
                        f"Whiteboard PNG successfully saved (client-side export) to:\n{path}"
                    )
                else:
                    raise Exception("QImage.save returned False")
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Error Saving File",
                    f"Failed to save exported whiteboard:\n{exc}"
                )

    def on_draw_broadcast(self, payload: dict) -> None:
        """Handle incoming DRAW_BROADCAST — apply to canvas."""
        if payload.get("room_code") != self._room_code:
            return
        seq_num = payload.get("seq_num")
        user_id = payload.get("user_id")
        username = payload.get("username", "")
        event_type = payload.get("event_type", "")
        data = payload.get("payload", {})
        client_event_id = payload.get("client_event_id")

        if seq_num is None:
            return

        self._whiteboard_widget.apply_event(seq_num, user_id, username, event_type, data)

        # If we drew this shape and received confirmed broadcast, push to undo/redo history
        if user_id == self._user_id:
            if event_type == "undo":
                target = data.get("target_seq")
                if target is not None:
                    self._whiteboard_widget.record_own_undo(target, seq_num)
            else:
                self._whiteboard_widget.record_own_draw(seq_num)

    def on_draw_ack(self, payload: dict) -> None:
        """Handle incoming DRAW_ACK — confirmation from server."""
        # Simple confirmation. The actual drawing is applied on DRAW_BROADCAST
        # to ensure correct state sync among all clients, including sender.
        pass

    def on_whiteboard_sync(self, payload: dict) -> None:
        """Handle incoming WHITEBOARD_SYNC — batch load active events."""
        if payload.get("room_code") != self._room_code:
            return
        snapshot_b64 = payload.get("snapshot")
        events = payload.get("events", [])
        self._whiteboard_widget.clear_all()
        if snapshot_b64:
            self._whiteboard_widget.apply_snapshot(snapshot_b64)
        for e in events:
            seq_num = e.get("seq_num")
            user_id = e.get("user_id")
            username = e.get("username", "")
            event_type = e.get("event_type", "")
            data = e.get("payload", {})
            if seq_num is not None:
                self._whiteboard_widget.apply_event(seq_num, user_id, username, event_type, data)

    def on_file_transfer(self, payload: dict) -> None:
        """Handle incoming FILE_TRANSFER — save exported PNG to local disk."""
        if payload.get("room_code") != self._room_code:
            return
        file_type = payload.get("file_type")
        if file_type != "whiteboard_export":
            return
        file_data_b64 = payload.get("file_data", "")
        file_name = payload.get("file_name", "whiteboard_export.png")

        if not file_data_b64:
            return

        try:
            file_data = base64.b64decode(file_data_b64)
        except Exception:
            logger.error("Failed to decode export file data")
            return

        # Prompt user to choose save path
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Whiteboard PNG Export",
            file_name,
            "PNG Images (*.png);;All Files (*)",
        )
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(file_data)
                QMessageBox.information(
                    self,
                    "Whiteboard Saved",
                    f"Whiteboard PNG successfully saved to:\n{path}"
                )
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Error Saving File",
                    f"Failed to save exported whiteboard:\n{exc}"
                )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Position subtitle overlay at the bottom-center of stacked view
        if hasattr(self, "_subtitle_widget") and self._subtitle_widget.isVisible():
            self._position_subtitle()

    def _position_subtitle(self) -> None:
        sw = self._subtitle_widget.width()
        sh = self._subtitle_widget.sizeHint().height()
        # center horizontally relative to stacked view, place near bottom
        geom = self._stacked_view.geometry()
        x = geom.x() + (geom.width() - sw) // 2
        y = geom.y() + geom.height() - sh - 16
        self._subtitle_widget.move(max(0, x), max(0, y))
        logger.error("Screen sharing stopped unexpectedly: %s", reason)
        if self._sharer_user_id == self._user_id:
            self._send_screen_stop(self._room_code)
        self._executor.stop()
        self._clear_share_state()
        self._frame_label.clear_frame()
        self._refresh_controls()
        QMessageBox.warning(self, "Screen Share", reason)

    def _on_local_frame_captured(self, image: QImage) -> None:
        if self._engine.is_running():
            self._frame_label.set_frame(image)

    def _enable_remote_input(self) -> None:
        self._remote_sender.attach(self._frame_label)
        self._remote_sender.set_enabled(True)
        self._frame_label.setFocus(Qt.FocusReason.OtherFocusReason)

    def _disable_remote_input(self) -> None:
        self._remote_sender.detach()
