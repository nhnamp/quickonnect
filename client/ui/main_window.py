"""Main application window with sidebar navigation and packet routing.

Phase 5 additions:
- Reconnection status banner
- Room invite notification handling
- E2E public key announcement and exchange
- Server shutdown notification handling
- Participant list updates from ROOM_STATE
"""

import base64
import logging

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QMessageBox,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal

from shared.constants import PacketType
from shared.protocol import Packet
from shared.crypto import (
    generate_rsa_keypair,
    serialize_public_key,
    deserialize_public_key,
    serialize_private_key,
    deserialize_private_key,
)
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

        # E2E encryption keypair
        self._e2e_private_key = None
        self._e2e_public_key_pem: bytes | None = None

        self.setWindowTitle(f"QuicKonNect - {self._username}")
        self.setMinimumSize(800, 600)

        self._build_ui()
        self._start_packet_polling()

        self._conn.on_disconnected = self._on_disconnected
        self._conn.on_reconnecting = self._on_reconnecting
        self._conn.on_reconnected = self._on_reconnected

        # Initialize E2E keys and announce to server
        self._init_e2e_keys()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Reconnection banner (hidden by default)
        self._reconnect_banner = QLabel()
        self._reconnect_banner.setStyleSheet(
            "background-color: #e67e22; color: white; padding: 6px; font-weight: bold;"
        )
        self._reconnect_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._reconnect_banner.hide()
        main_layout.addWidget(self._reconnect_banner)

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
    # E2E Key Management
    # ------------------------------------------------------------------

    def _init_e2e_keys(self):
        """Load or generate the long-term E2E RSA keypair and announce to server."""
        keypair = self._store.load_user_keypair(self._username)
        if keypair:
            priv_pem, pub_pem = keypair
            try:
                self._e2e_private_key = deserialize_private_key(priv_pem)
                self._e2e_public_key_pem = pub_pem
            except Exception:
                logger.warning("Failed to load stored keypair, generating new one")
                keypair = None

        if not keypair:
            priv, pub = generate_rsa_keypair()
            self._e2e_private_key = priv
            self._e2e_public_key_pem = serialize_public_key(pub)
            priv_pem = serialize_private_key(priv)
            self._store.save_user_keypair(self._username, priv_pem, self._e2e_public_key_pem)

        # Announce public key to server for E2E exchanges
        self._conn.send(PacketType.PUBLIC_KEY_ANNOUNCE, {
            "public_key": base64.b64encode(self._e2e_public_key_pem).decode("ascii"),
        })

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
            # Update participant list
            participants = data.get("participants", [])
            self._chat_widget.update_participants(room_code, participants)
            self._stack.setCurrentIndex(0)
            # Phase 2: surface any active share that already exists in the room.
            self._screen_widget.set_current_room(room_code)
            self._screen_widget.handle_room_state_screen(data.get("screen"))
            # Update connection manager's room list for reconnection
            self._conn.update_room_codes(self._chat_widget.get_room_codes())

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

        elif ptype == PacketType.MIXED_AUDIO:
            self._screen_widget.on_mixed_audio(data)

        elif ptype == PacketType.SUBTITLE:
            self._screen_widget.on_subtitle(data)

        elif ptype == PacketType.DRAW_BROADCAST:
            self._screen_widget.on_draw_broadcast(data)

        elif ptype == PacketType.DRAW_ACK:
            self._screen_widget.on_draw_ack(data)

        elif ptype == PacketType.WHITEBOARD_SYNC:
            self._screen_widget.on_whiteboard_sync(data)

        elif ptype == PacketType.FILE_TRANSFER:
            self._screen_widget.on_file_transfer(data)

        elif ptype == PacketType.ROOM_INVITE_NOTIFY:
            self._handle_room_invite(data)

        elif ptype == PacketType.PUBLIC_KEY_RESPONSE:
            self._handle_public_key_response(data)

        elif ptype == PacketType.SERVER_SHUTDOWN:
            self._handle_server_shutdown(data)

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
    # Room invite handling
    # ------------------------------------------------------------------

    def _handle_room_invite(self, data: dict):
        room_code = data.get("room_code", "")
        from_username = data.get("from_username", "")
        reply = QMessageBox.question(
            self, "Room Invite",
            f"{from_username} invites you to join room {room_code}.\n\nAccept?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._conn.send(PacketType.JOIN_ROOM, {"room_code": room_code})

    # ------------------------------------------------------------------
    # E2E public key handling
    # ------------------------------------------------------------------

    def _handle_public_key_response(self, data: dict):
        username = data.get("username", "")
        public_key_b64 = data.get("public_key", "")
        if username and public_key_b64:
            pub_pem = base64.b64decode(public_key_b64)
            self._store.save_peer_public_key(username, pub_pem)

    # ------------------------------------------------------------------
    # Server shutdown handling
    # ------------------------------------------------------------------

    def _handle_server_shutdown(self, data: dict):
        msg = data.get("message", "Server is shutting down")
        self.statusBar().showMessage(f"⚠ {msg}", 10000)

    # ------------------------------------------------------------------
    # Reconnection
    # ------------------------------------------------------------------

    def _on_reconnecting(self, attempt: int, max_attempts: int):
        QTimer.singleShot(0, lambda: self._show_reconnect_banner(attempt, max_attempts))

    def _show_reconnect_banner(self, attempt: int, max_attempts: int):
        self._reconnect_banner.setText(
            f"⟳ Reconnecting... attempt {attempt}/{max_attempts}"
        )
        self._reconnect_banner.show()

    def _on_reconnected(self):
        QTimer.singleShot(0, self._hide_reconnect_banner)

    def _hide_reconnect_banner(self):
        self._reconnect_banner.hide()
        self.statusBar().showMessage("✓ Reconnected successfully", 5000)
        # Re-announce E2E public key
        if self._e2e_public_key_pem:
            self._conn.send(PacketType.PUBLIC_KEY_ANNOUNCE, {
                "public_key": base64.b64encode(self._e2e_public_key_pem).decode("ascii"),
            })

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
        self._reconnect_banner.hide()
        QMessageBox.warning(self, "Disconnected", f"Lost connection: {reason}")
        self.logout_requested.emit()
        self.close()

    def closeEvent(self, event):
        self._poll_timer.stop()
        self._screen_widget.shutdown()
        if self._conn.connected:
            self._conn.disconnect()
        event.accept()
