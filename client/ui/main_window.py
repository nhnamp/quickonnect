import logging

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

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    logout_requested = pyqtSignal()

    def __init__(self, conn_mgr: ConnectionManager, local_store: LocalStore, user_info: dict):
        super().__init__()
        self._conn = conn_mgr
        self._store = local_store
        self._user_id = user_info.get("user_id", 0)
        self._username = user_info.get("username", "")

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
        for btn in [self._chat_btn, self._friends_btn, self._screen_btn]:
            btn.setStyleSheet(
                "QPushButton { color: white; background: #2c3e50; padding: 8px; border: none; }"
                "QPushButton:hover { background: #1abc9c; }"
            )

        self._chat_btn.clicked.connect(lambda: self._stack.setCurrentIndex(0))
        self._friends_btn.clicked.connect(lambda: self._stack.setCurrentIndex(1))
        self._screen_btn.clicked.connect(lambda: self._stack.setCurrentIndex(2))

        sidebar_layout.addWidget(self._chat_btn)
        sidebar_layout.addWidget(self._friends_btn)
        sidebar_layout.addWidget(self._screen_btn)
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

        self._stack.addWidget(self._chat_widget)
        self._stack.addWidget(self._friend_widget)
        self._stack.addWidget(self._screen_widget)

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

        elif ptype == PacketType.MESSAGE_HISTORY:
            room_id = data.get("room_id", 0)
            messages = data.get("messages", [])
            room_code = data.get("room_code", "")
            if room_code:
                self._chat_widget.add_room(room_code, room_id)
            self._chat_widget.load_history(room_id, messages)

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

        elif ptype == PacketType.ERROR:
            code = data.get("code", 0)
            msg = data.get("message", "Unknown error")
            if code == 307:
                QMessageBox.information(self, "Redirect",
                    f"Room is on another server. Please rejoin with the room code.")
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

    def _on_logout(self):
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        self._store.clear_session()
        self._conn.disconnect()
        self.logout_requested.emit()
        self.close()

    def _on_disconnected(self, reason: str):
        QTimer.singleShot(0, lambda: self._show_disconnect(reason))

    def _show_disconnect(self, reason: str):
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        QMessageBox.warning(self, "Disconnected", f"Lost connection: {reason}")
        self.logout_requested.emit()
        self.close()

    def closeEvent(self, event):
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        if self._conn.connected:
            self._conn.disconnect()
        event.accept()
