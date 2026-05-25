import logging
from queue import Empty

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from shared.constants import PacketType
from shared.protocol import Packet
from client.network.connection import ConnectionManager
from client.storage.local_store import LocalStore
from client.ui.chat_widget import ChatWidget
from client.ui.friend_list_widget import FriendListWidget
from client.ui.screen_share_widget import ScreenShareWidget
from client.ui.audio_widget import AudioWidget
from client.ui.whiteboard_widget import WhiteboardWidget

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    logout_requested = pyqtSignal()

    def __init__(self, conn_mgr: ConnectionManager, local_store: LocalStore, user_info: dict):
        super().__init__()
        self._conn = conn_mgr
        self._store = local_store
        self._user_id = user_info.get("user_id", 0)
        self._username = user_info.get("username", "")
        self._redirecting = False

        self.setWindowTitle(f"QuicKonNect - {self._username}")
        self.setMinimumSize(800, 600)

        self._build_ui()
        self._start_packet_polling()

        self._conn.on_disconnected = self._on_disconnected

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Top bar
        top_bar = QWidget()
        top_bar.setStyleSheet("background-color: #2c3e50; color: white; padding: 4px;")
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(8, 4, 8, 4)

        app_label = QLabel("QuicKonNect")
        app_label.setStyleSheet("font-weight: bold; font-size: 16px;")
        top_layout.addWidget(app_label)
        top_layout.addStretch()

        user_label = QLabel(f"Logged in as: {self._username}")
        top_layout.addWidget(user_label)

        logout_btn = QPushButton("Logout")
        logout_btn.setStyleSheet("background-color: #c0392b; color: white; padding: 4px 12px;")
        logout_btn.clicked.connect(self._on_logout)
        top_layout.addWidget(logout_btn)

        main_layout.addWidget(top_bar)

        # Body: sidebar + content
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setFixedWidth(100)
        sidebar.setStyleSheet("background-color: #34495e;")
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(4, 8, 4, 8)

        self._chat_btn = QPushButton("Chat")
        self._friends_btn = QPushButton("Friends")
        self._screen_btn = QPushButton("Screen")
        self._audio_btn = QPushButton("Audio")
        self._whiteboard_btn = QPushButton("Whiteboard")
        for btn in [self._chat_btn, self._friends_btn, self._screen_btn, self._audio_btn, self._whiteboard_btn]:
            btn.setStyleSheet(
                "QPushButton { color: white; background: #2c3e50; padding: 8px; border: none; }"
                "QPushButton:hover { background: #1abc9c; }"
            )

        self._chat_btn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._friends_btn.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        self._screen_btn.clicked.connect(lambda: self._stack.setCurrentIndex(2))
        self._audio_btn.clicked.connect(lambda: self._stack.setCurrentIndex(3))
        self._whiteboard_btn.clicked.connect(lambda: self._stack.setCurrentIndex(4))

        sidebar_layout.addWidget(self._chat_btn)
        sidebar_layout.addWidget(self._friends_btn)
        sidebar_layout.addWidget(self._screen_btn)
        sidebar_layout.addWidget(self._audio_btn)
        sidebar_layout.addWidget(self._whiteboard_btn)
        sidebar_layout.addStretch()

        body_layout.addWidget(sidebar)

        # Content stack
        self._stack = QStackedWidget()

        self._chat_widget = ChatWidget()
        self._chat_widget.send_packet.connect(self._send_packet)

        self._friend_widget = FriendListWidget()
        self._friend_widget.send_packet.connect(self._send_packet)
        self._friend_widget.start_dm.connect(self._on_start_dm)

        self._screen_widget = ScreenShareWidget(self._conn, self._user_id, self._username)
        self._screen_widget.send_packet.connect(self._send_packet)
        self._chat_widget.room_changed.connect(self._screen_widget.set_current_room)

        self._audio_widget = AudioWidget(self._conn, self._user_id, self._username)
        self._audio_widget.send_packet.connect(self._send_packet)
        self._chat_widget.room_changed.connect(self._audio_widget.set_current_room)

        self._whiteboard_widget = WhiteboardWidget(self._user_id)
        self._whiteboard_widget.send_packet.connect(self._send_packet)
        self._chat_widget.room_changed.connect(self._whiteboard_widget.set_current_room)

        self._stack.addWidget(self._chat_widget)
        self._stack.addWidget(self._friend_widget)
        self._stack.addWidget(self._screen_widget)
        self._stack.addWidget(self._audio_widget)
        self._stack.addWidget(self._whiteboard_widget)

        body_layout.addWidget(self._stack)
        main_layout.addWidget(body)

    # ------------------------------------------------------------------
    # Packet polling
    # ------------------------------------------------------------------

    def _start_packet_polling(self):
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_packets)
        self._poll_timer.start(16)  # ~60 Hz

    def _poll_packets(self):
        while not self._conn.packet_queue.empty():
            try:
                packet = self._conn.packet_queue.get_nowait()
                self._handle_packet(packet)
            except Exception:
                break

    def _handle_packet(self, packet: Packet):
        ptype = packet.packet_type
        data = packet.payload

        if ptype == PacketType.ROOM_STATE:
            room_code = data.get("room_code", "")
            room_id = data.get("room_id", 0)
            self._chat_widget.add_room(room_code, room_id)
            self._stack.setCurrentIndex(0)
            # Phase 2: surface any active share that already exists in the room.
            self._screen_widget.set_current_room(room_code)
            self._screen_widget.handle_room_state_screen(data.get("screen"))
            self._audio_widget.set_current_room(room_code)
            self._whiteboard_widget.set_current_room(room_code)

        elif ptype == PacketType.MESSAGE_HISTORY:
            room_id = data.get("room_id", 0)
            messages = data.get("messages", [])
            room_code = data.get("room_code", "")
            if room_code:
                self._chat_widget.add_room(room_code, room_id)
            self._chat_widget.load_history(room_id, messages, room_code)

        elif ptype == PacketType.CHAT_MESSAGE:
            self._chat_widget.add_message(data)

        elif ptype == PacketType.ROOM_UPDATE:
            self._chat_widget.handle_room_update(data)

        elif ptype == PacketType.FRIEND_LIST:
            friends = data.get("friends", [])
            self._friend_widget.update_friends(friends)

        elif ptype == PacketType.FRIEND_UPDATE:
            self._friend_widget.handle_friend_update(data)

        elif ptype == PacketType.SCREEN_START:
            self._screen_widget.on_screen_start(data)

        elif ptype == PacketType.SCREEN_STOP:
            self._screen_widget.on_screen_stop(data)

        elif ptype == PacketType.SCREEN_RELAY:
            self._screen_widget.on_screen_relay(data)

        elif ptype == PacketType.REMOTE_REQUEST:
            self._screen_widget.on_remote_request(data)

        elif ptype == PacketType.REMOTE_GRANT:
            self._screen_widget.on_remote_grant(data)

        elif ptype == PacketType.REMOTE_EVENT:
            self._screen_widget.on_remote_event(data)

        elif ptype == PacketType.MIXED_AUDIO:
            self._audio_widget.on_mixed_audio(data)

        elif ptype == PacketType.SUBTITLE:
            self._audio_widget.on_subtitle(data)

        elif ptype == PacketType.WHITEBOARD_SYNC:
            self._whiteboard_widget.on_sync(data)

        elif ptype == PacketType.DRAW_BROADCAST:
            self._whiteboard_widget.on_draw_broadcast(data)

        elif ptype == PacketType.FILE_TRANSFER:
            self._whiteboard_widget.on_file_transfer(data)

        elif ptype == PacketType.ERROR:
            code = data.get("code", 0)
            msg = data.get("message", "Unknown error")
            if code == 307:
                self._handle_room_redirect(data)
            else:
                self.statusBar().showMessage(f"Error: {msg}", 5000)

        elif ptype == PacketType.HEARTBEAT:
            pass

        else:
            logger.debug("Unhandled packet in UI: %s", ptype)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _send_packet(self, packet_type: int, payload: dict):
        self._conn.send(PacketType(packet_type), payload)

    def _on_start_dm(self, friend_username: str):
        # Deterministic room code for DMs
        names = sorted([self._username, friend_username])
        room_code = f"DM-{names[0]}-{names[1]}"
        self._conn.send(PacketType.JOIN_ROOM, {"room_code": room_code})
        self._stack.setCurrentIndex(0)

    def _handle_room_redirect(self, data: dict):
        host = data.get("redirect_host", "")
        port = int(data.get("redirect_port", 0))
        room_code = data.get("room_code", "")
        if not host or not port or not room_code:
            QMessageBox.information(self, "Redirect", "Room is on another server. Please rejoin.")
            return

        session = self._store.load_session() or {}
        token = session.get("token", "")
        if not token:
            QMessageBox.warning(self, "Redirect", "Please log in again before joining this room.")
            return

        self.statusBar().showMessage(f"Reconnecting to room server for {room_code}...", 5000)
        self._redirecting = True
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        self._audio_widget.shutdown()
        self._conn.disconnect()

        while not self._conn.packet_queue.empty():
            try:
                self._conn.packet_queue.get_nowait()
            except Empty:
                break

        try:
            self._conn.connect(host, port)
            self._conn.send(PacketType.AUTH_REQUEST, {"token": token})
            packet = self._conn.packet_queue.get(timeout=15)
            if packet.packet_type != PacketType.AUTH_RESPONSE or not packet.payload.get("success"):
                raise ConnectionError(packet.payload.get("error", "Authentication failed after redirect"))
            self._conn.send(PacketType.JOIN_ROOM, {"room_code": room_code})
            self._conn.on_disconnected = self._on_disconnected
        except Exception as exc:
            self._conn.disconnect()
            QMessageBox.warning(self, "Redirect failed", str(exc))
        finally:
            self._redirecting = False
            self._poll_timer.start(16)

    def _on_logout(self):
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        self._audio_widget.shutdown()
        self._store.clear_session()
        self._conn.disconnect()
        self.logout_requested.emit()
        self.close()

    def _on_disconnected(self, reason: str):
        if self._redirecting:
            return
        QTimer.singleShot(0, lambda: self._show_disconnect(reason))

    def _show_disconnect(self, reason: str):
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        self._audio_widget.shutdown()
        QMessageBox.warning(self, "Disconnected", f"Lost connection: {reason}")
        self.logout_requested.emit()
        self.close()

    def closeEvent(self, event):
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        self._audio_widget.shutdown()
        if self._conn.connected:
            self._conn.disconnect()
        event.accept()
