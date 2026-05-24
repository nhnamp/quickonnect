"""Dedicated screen-sharing tab.

Layout (top-to-bottom):
  - Status bar — which room, who is sharing, who has remote control.
  - Frame view — a QLabel that holds the most recent decoded frame, scaled
    to fit while preserving aspect ratio. Receives input events when the
    local user has been granted remote control.
  - Controls — Share / Stop / Request Control / Revoke buttons plus
    runtime sliders for FPS and JPEG quality.

The widget is purely a view: all network traffic happens through the
ConnectionManager passed in at construction. All packet receipt is
pushed in from main_window via the on_packet() entry points.
"""

import logging

from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtGui import QPixmap, QImage
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QMessageBox,
)

from shared.constants import PacketType
from client.features.screen_engine import ScreenCaptureEngine, decode_jpeg
from client.features.remote_control import RemoteControlSender, RemoteControlExecutor

logger = logging.getLogger(__name__)


class FrameLabel(QLabel):
    """QLabel that holds the latest frame and reports its drawn geometry."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(QSize(320, 180))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #111; color: #888;")
        self.setText("No active screen share")
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
        self._engine.frame_dropped.connect(self._on_frame_dropped)

        self._executor = RemoteControlExecutor()
        self._remote_sender = RemoteControlSender(
            connection_manager,
            self._current_room,
            lambda: self._frame_label.displayed_geometry() if self._frame_label else None,
            self,
        )

        self._build_ui()
        self._remote_sender.attach(self._frame_label)
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

        self._frame_label = FrameLabel(self)
        layout.addWidget(self._frame_label, stretch=1)

        # Controls row 1: share / stop / request control / revoke
        btn_row = QHBoxLayout()
        self._share_btn = QPushButton("Share Screen")
        self._share_btn.clicked.connect(self._on_share_clicked)
        self._stop_btn = QPushButton("Stop Sharing")
        self._stop_btn.clicked.connect(self._on_stop_clicked)
        self._request_btn = QPushButton("Request Control")
        self._request_btn.clicked.connect(self._on_request_clicked)
        self._revoke_btn = QPushButton("Revoke Control")
        self._revoke_btn.clicked.connect(self._on_revoke_clicked)
        btn_row.addWidget(self._share_btn)
        btn_row.addWidget(self._stop_btn)
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
        self._room_code = room_code
        self._clear_share_state()
        self._refresh_controls()

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
            self._remote_sender.set_enabled(True)
        elif not granted and self._controller_user_id == self._user_id:
            # We had control and just got revoked/denied.
            self._remote_sender.set_enabled(False)
            self._controller_user_id = None
            self._controller_username = ""
        else:
            self._controller_user_id = target_user_id if granted else None
            self._controller_username = target_username if granted else ""

        # Local effect on the sharer (host) side: start/stop the executor.
        if self._sharer_user_id == self._user_id:
            if granted and target_user_id is not None:
                ok, error = self._executor.start()
                if not ok:
                    QMessageBox.warning(
                        self, "Remote control",
                        error or "Could not start remote control on this machine.",
                    )
                    # Roll back the grant: tell the server we're not really
                    # able to be controlled.
                    self.send_packet.emit(int(PacketType.REMOTE_GRANT), {
                        "room_code": self._room_code,
                        "granted": False,
                        "target_user_id": None,
                    })
                    return
            else:
                self._executor.stop()
        self._refresh_controls()

    def on_remote_event(self, payload: dict) -> None:
        # Only the sharer ever receives REMOTE_EVENT from the server.
        if self._sharer_user_id != self._user_id:
            return
        if payload.get("room_code") != self._room_code:
            return
        self._executor.submit(payload)

    def shutdown(self) -> None:
        """Called on logout / disconnect — stop any local threads."""
        if self._engine.is_running():
            self._engine.stop("Shutdown")
        self._executor.stop()
        self._remote_sender.detach()

    # ------------------------------------------------------------------
    # Button handlers
    # ------------------------------------------------------------------

    def _on_share_clicked(self) -> None:
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
            QMessageBox.warning(self, "Screen Share", error or "Could not start capture.")
            return
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
            self._remote_sender.set_enabled(False)
            self._controller_user_id = None
            self._controller_username = ""
            self._refresh_controls()

    # ------------------------------------------------------------------
    # Slider handlers
    # ------------------------------------------------------------------

    def _on_fps_changed(self, value: int) -> None:
        self._fps_value.setText(str(value))
        self._engine.set_fps(value)

    def _on_quality_changed(self, value: int) -> None:
        self._quality_value.setText(str(value))
        self._engine.set_quality(value)

    def _on_scale_changed(self, value: int) -> None:
        self._scale_value.setText(f"{value}%")
        self._engine.set_scale(value / 100.0)

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
        self._remote_sender.set_enabled(False)

    def _refresh_controls(self) -> None:
        in_room = self._room_code is not None
        someone_sharing = self._sharer_user_id is not None
        we_share = self._sharer_user_id == self._user_id
        we_control = self._controller_user_id == self._user_id

        self._share_btn.setEnabled(in_room and not someone_sharing)
        self._stop_btn.setEnabled(we_share)
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
        if reason and reason not in ("User stopped", "Stop received from server"):
            self._diag_label.setText(f"Capture stopped: {reason}")
        else:
            self._diag_label.setText("")

    def _on_frame_dropped(self, total: int) -> None:
        self._diag_label.setText(f"Dropped frames (queue full): {total}")
