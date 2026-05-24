import logging
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QInputDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal

from shared.constants import PacketType

logger = logging.getLogger(__name__)


class ChatWidget(QWidget):
    """Chat panel: room list on the left, message view on the right."""
    send_packet = pyqtSignal(int, dict)  # packet_type, payload
    room_changed = pyqtSignal(str)       # emitted when _current_room changes (Phase 2 hookup)

    def __init__(self):
        super().__init__()
        self._current_room: str | None = None
        # room_code -> list of message dicts
        self._room_messages: dict[str, list[dict]] = {}
        self._room_names: dict[str, str] = {}  # room_code -> display name
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        lbl = QLabel("Rooms")
        lbl.setStyleSheet("font-weight: bold;")
        left_layout.addWidget(lbl)

        self._room_list = QListWidget()
        self._room_list.currentItemChanged.connect(self._on_room_selected)
        left_layout.addWidget(self._room_list)

        btn_row = QHBoxLayout()
        create_btn = QPushButton("Create")
        join_btn = QPushButton("Join")
        create_btn.clicked.connect(self._on_create_room)
        join_btn.clicked.connect(self._on_join_room)
        btn_row.addWidget(create_btn)
        btn_row.addWidget(join_btn)
        left_layout.addLayout(btn_row)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        self._room_header = QLabel("Select a room")
        self._room_header.setStyleSheet("font-weight: bold; font-size: 14px;")
        right_layout.addWidget(self._room_header)

        self._message_view = QTextEdit()
        self._message_view.setReadOnly(True)
        right_layout.addWidget(self._message_view)

        input_row = QHBoxLayout()
        self._msg_input = QLineEdit()
        self._msg_input.setPlaceholderText("Type a message...")
        self._msg_input.returnPressed.connect(self._on_send)
        self._msg_input.setEnabled(False)
        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._on_send)
        self._send_btn.setEnabled(False)
        input_row.addWidget(self._msg_input)
        input_row.addWidget(self._send_btn)
        right_layout.addLayout(input_row)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)

    # ------------------------------------------------------------------
    # Room management
    # ------------------------------------------------------------------

    def _on_create_room(self):
        import string, random
        chars = string.ascii_uppercase + string.digits
        code = "".join(random.choices(chars, k=3)) + "-" + "".join(random.choices(chars, k=4))
        self.send_packet.emit(PacketType.JOIN_ROOM, {"room_code": code})

    def _on_join_room(self):
        code, ok = QInputDialog.getText(self, "Join Room", "Enter room code:")
        if ok and code.strip():
            self.send_packet.emit(PacketType.JOIN_ROOM, {"room_code": code.strip().upper()})

    def add_room(self, room_code: str, room_id: int = 0):
        """Called when the server confirms room join."""
        if room_code not in self._room_messages:
            self._room_messages[room_code] = []
            item = QListWidgetItem(room_code)
            item.setData(Qt.ItemDataRole.UserRole, room_code)
            self._room_list.addItem(item)

        self._current_room = room_code
        self._select_room_in_list(room_code)
        self._update_message_view()
        self._msg_input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self.room_changed.emit(room_code)

    def _select_room_in_list(self, room_code: str):
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == room_code:
                self._room_list.setCurrentItem(item)
                break

    def _on_room_selected(self, current: QListWidgetItem, previous: QListWidgetItem):
        if current is None:
            return
        room_code = current.data(Qt.ItemDataRole.UserRole)
        if room_code == self._current_room:
            return
        self._current_room = room_code
        self._update_message_view()
        self._msg_input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self.room_changed.emit(room_code)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def _on_send(self):
        if not self._current_room:
            return
        text = self._msg_input.text().strip()
        if not text:
            return

        self.send_packet.emit(PacketType.CHAT_MESSAGE, {
            "room_code": self._current_room,
            "content": text,
            "msg_type": "text",
        })
        self._msg_input.clear()

    def add_message(self, msg: dict):
        """Called when a CHAT_MESSAGE arrives from the server."""
        room_code = msg.get("room_code", "")
        if room_code and room_code not in self._room_messages:
            self.add_room(room_code)

        if room_code:
            self._room_messages.setdefault(room_code, []).append(msg)

        if room_code == self._current_room:
            self._update_message_view()

    def load_history(self, room_id: int, messages: list[dict]):
        """Called when MESSAGE_HISTORY arrives."""
        room_code = None
        for code, msgs in self._room_messages.items():
            if any(m.get("room_id") == room_id for m in msgs):
                room_code = code
                break

        if room_code is None:
            for code in self._room_messages:
                room_code = code
                break

        if room_code is None:
            return

        self._room_messages[room_code] = messages + self._room_messages.get(room_code, [])
        if room_code == self._current_room:
            self._update_message_view()

    def handle_room_update(self, data: dict):
        """Handle participant join/leave notifications."""
        room_code = data.get("room_code", "")
        event = data.get("event", "")
        username = data.get("username", "")

        if room_code in self._room_messages:
            system_msg = {
                "sender_name": "System",
                "content": f"{username} {event} the room",
                "sent_at": datetime.now().isoformat(),
            }
            self._room_messages[room_code].append(system_msg)
            if room_code == self._current_room:
                self._update_message_view()

    def _update_message_view(self):
        if not self._current_room:
            self._room_header.setText("Select a room")
            self._message_view.clear()
            return

        self._room_header.setText(f"Room: {self._current_room}")
        messages = self._room_messages.get(self._current_room, [])

        lines = []
        for m in messages:
            sender = m.get("sender_name", "Unknown")
            content = m.get("content", "")
            ts = m.get("sent_at", "")
            if ts and "T" in str(ts):
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    ts = dt.strftime("%H:%M:%S")
                except Exception:
                    pass
            lines.append(f"[{ts}] {sender}: {content}")

        self._message_view.setPlainText("\n".join(lines))
        sb = self._message_view.verticalScrollBar()
        sb.setValue(sb.maximum())
