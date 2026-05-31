"""Chat panel with room list, message view, file/image messaging, and participant list.

Phase 5 additions:
- File and image attachment (up to 10 MB, rendered inline)
- Participant list display showing who is in the current room
- Invite friend button for room invites
- Copy room code button
- E2E encryption support for DM rooms
"""

import base64
import logging
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QInputDialog, QFileDialog, QApplication,
    QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QImage, QTextCursor

from shared.constants import PacketType

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


class ChatWidget(QWidget):
    """Chat panel: room list on the left, message view + participant list on the right."""
    send_packet = pyqtSignal(int, dict)  # packet_type, payload
    join_room_requested = pyqtSignal(str)  # regular room code entered via Join button
    room_changed = pyqtSignal(str)       # emitted when _current_room changes (Phase 2 hookup)

    def __init__(self):
        super().__init__()
        self._current_room: str | None = None
        # room_code -> list of message dicts
        self._room_messages: dict[str, list[dict]] = {}
        self._room_names: dict[str, str] = {}  # room_code -> display name
        self._room_participants: dict[str, list[dict]] = {}  # room_code -> participant list
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Left panel: rooms ---
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

        # --- Right panel: messages + participants ---
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        # Room header with code + copy + invite
        header_row = QHBoxLayout()
        self._room_header = QLabel("Select a room")
        self._room_header.setStyleSheet("font-weight: bold; font-size: 14px;")
        header_row.addWidget(self._room_header)
        header_row.addStretch()

        self._copy_code_btn = QPushButton("📋 Copy Code")
        self._copy_code_btn.setFixedWidth(100)
        self._copy_code_btn.clicked.connect(self._on_copy_code)
        self._copy_code_btn.setEnabled(False)
        header_row.addWidget(self._copy_code_btn)

        self._invite_btn = QPushButton("📨 Invite")
        self._invite_btn.setFixedWidth(80)
        self._invite_btn.clicked.connect(self._on_invite_friend)
        self._invite_btn.setEnabled(False)
        header_row.addWidget(self._invite_btn)

        self._leave_btn = QPushButton("🚪 Leave")
        self._leave_btn.setFixedWidth(80)
        self._leave_btn.clicked.connect(self._on_leave_room)
        self._leave_btn.setEnabled(False)
        header_row.addWidget(self._leave_btn)

        right_layout.addLayout(header_row)

        # Message + participants split
        msg_split = QSplitter(Qt.Orientation.Horizontal)

        # Message view
        msg_panel = QWidget()
        msg_panel_layout = QVBoxLayout(msg_panel)
        msg_panel_layout.setContentsMargins(0, 0, 0, 0)

        self._message_view = QTextEdit()
        self._message_view.setReadOnly(True)
        msg_panel_layout.addWidget(self._message_view)

        # Input row: attach + text + send
        input_row = QHBoxLayout()
        self._attach_btn = QPushButton("📎")
        self._attach_btn.setFixedWidth(32)
        self._attach_btn.setToolTip("Attach file or image")
        self._attach_btn.clicked.connect(self._on_attach)
        self._attach_btn.setEnabled(False)
        input_row.addWidget(self._attach_btn)

        self._msg_input = QLineEdit()
        self._msg_input.setPlaceholderText("Type a message...")
        self._msg_input.returnPressed.connect(self._on_send)
        self._msg_input.setEnabled(False)
        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._on_send)
        self._send_btn.setEnabled(False)
        input_row.addWidget(self._msg_input)
        input_row.addWidget(self._send_btn)
        msg_panel_layout.addLayout(input_row)

        msg_split.addWidget(msg_panel)

        # Participant list
        part_panel = QWidget()
        part_layout = QVBoxLayout(part_panel)
        part_layout.setContentsMargins(0, 0, 0, 0)

        part_label = QLabel("Participants")
        part_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        part_layout.addWidget(part_label)

        self._participant_list = QListWidget()
        self._participant_list.setMaximumWidth(160)
        part_layout.addWidget(self._participant_list)

        msg_split.addWidget(part_panel)
        msg_split.setStretchFactor(0, 4)
        msg_split.setStretchFactor(1, 1)

        right_layout.addWidget(msg_split)

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
            self.join_room_requested.emit(code.strip().upper())

    def _on_copy_code(self):
        if self._current_room:
            clipboard = QApplication.clipboard()
            clipboard.setText(self._current_room)
            self._copy_code_btn.setText("✓ Copied!")
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, lambda: self._copy_code_btn.setText("📋 Copy Code"))

    def _on_invite_friend(self):
        if not self._current_room:
            return
        username, ok = QInputDialog.getText(
            self, "Invite Friend", "Enter friend's username to invite:")
        if ok and username.strip():
            self.send_packet.emit(PacketType.ROOM_INVITE, {
                "room_code": self._current_room,
                "target_username": username.strip(),
            })

    def _on_leave_room(self):
        if not self._current_room:
            return
        self.send_packet.emit(PacketType.LEAVE_ROOM, {
            "room_code": self._current_room,
        })
        # Remove from local state
        room_code = self._current_room
        self._room_messages.pop(room_code, None)
        self._room_participants.pop(room_code, None)
        # Remove from list widget
        for i in range(self._room_list.count()):
            item = self._room_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == room_code:
                self._room_list.takeItem(i)
                break
        self._current_room = None
        self._update_message_view()
        self._update_participant_list()
        self._set_input_enabled(False)

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
        self._set_input_enabled(True)
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
        self._update_participant_list()
        self._set_input_enabled(True)
        self.room_changed.emit(room_code)

    def _set_input_enabled(self, enabled: bool):
        self._msg_input.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)
        self._attach_btn.setEnabled(enabled)
        self._copy_code_btn.setEnabled(enabled)
        self._invite_btn.setEnabled(enabled)
        self._leave_btn.setEnabled(enabled)

    def get_room_codes(self) -> list[str]:
        """Return the list of room codes the user is in (for reconnection)."""
        return list(self._room_messages.keys())

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------

    def update_participants(self, room_code: str, participants: list[dict]):
        """Update the participant list for a room (from ROOM_STATE)."""
        self._room_participants[room_code] = participants
        if room_code == self._current_room:
            self._update_participant_list()

    def _update_participant_list(self):
        self._participant_list.clear()
        if not self._current_room:
            return
        participants = self._room_participants.get(self._current_room, [])
        for p in participants:
            username = p.get("username", "Unknown")
            item = QListWidgetItem(f"👤 {username}")
            self._participant_list.addItem(item)

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

    def _on_attach(self):
        """Open file picker and send as image or file message."""
        if not self._current_room:
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select file to send", "",
            "All Files (*);;Images (*.png *.jpg *.jpeg *.gif *.bmp)",
        )
        if not filepath:
            return

        filesize = os.path.getsize(filepath)
        if filesize > _MAX_FILE_SIZE:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "File Too Large",
                f"Maximum file size is 10 MB. Selected file is {filesize / 1024 / 1024:.1f} MB.",
            )
            return

        filename = os.path.basename(filepath)
        ext = os.path.splitext(filename)[1].lower()
        is_image = ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp")

        try:
            with open(filepath, "rb") as f:
                file_bytes = f.read()
        except Exception:
            logger.error("Failed to read file: %s", filepath)
            return

        content_b64 = base64.b64encode(file_bytes).decode("ascii")
        msg_type = "image" if is_image else "file"

        self.send_packet.emit(PacketType.CHAT_MESSAGE, {
            "room_code": self._current_room,
            "content": content_b64,
            "msg_type": msg_type,
            "filename": filename,
            "filesize": filesize,
        })

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
        user_id = data.get("user_id", 0)

        if room_code in self._room_messages:
            system_msg = {
                "sender_name": "System",
                "content": f"{username} {event} the room",
                "sent_at": datetime.now().isoformat(),
            }
            self._room_messages[room_code].append(system_msg)
            if room_code == self._current_room:
                self._update_message_view()

        # Update participant list
        participants = self._room_participants.get(room_code, [])
        if event == "joined":
            if not any(p.get("user_id") == user_id for p in participants):
                participants.append({"user_id": user_id, "username": username})
                self._room_participants[room_code] = participants
        elif event == "left":
            self._room_participants[room_code] = [
                p for p in participants if p.get("user_id") != user_id
            ]
        if room_code == self._current_room:
            self._update_participant_list()

    def _update_message_view(self):
        if not self._current_room:
            self._room_header.setText("Select a room")
            self._message_view.clear()
            return

        self._room_header.setText(f"Room: {self._current_room}")
        messages = self._room_messages.get(self._current_room, [])

        self._message_view.clear()
        cursor = self._message_view.textCursor()

        for m in messages:
            sender = m.get("sender_name", "Unknown")
            content = m.get("content", "")
            msg_type = m.get("msg_type", "text")
            ts = m.get("sent_at", "")
            if ts and "T" in str(ts):
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    ts = dt.strftime("%H:%M:%S")
                except Exception:
                    pass

            if msg_type == "image":
                # Render image inline
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(f"[{ts}] {sender}: ")
                filename = m.get("filename", "image")
                try:
                    img_bytes = base64.b64decode(content)
                    img = QImage()
                    img.loadFromData(img_bytes)
                    if not img.isNull():
                        # Scale to max 300px wide
                        if img.width() > 300:
                            img = img.scaledToWidth(300, Qt.TransformationMode.SmoothTransformation)
                        doc = self._message_view.document()
                        doc.addResource(
                            doc.ResourceType.ImageResource.value,
                            __import__("PyQt6.QtCore", fromlist=["QUrl"]).QUrl(filename),
                            img,
                        )
                        cursor.insertImage(filename)
                    else:
                        cursor.insertText(f"[Image: {filename}]")
                except Exception:
                    cursor.insertText(f"[Image: {filename}]")
                cursor.insertText("\n")

            elif msg_type == "file":
                filename = m.get("filename", "file")
                filesize = m.get("filesize", 0)
                size_str = f"{filesize / 1024:.1f} KB" if filesize < 1024 * 1024 else f"{filesize / 1024 / 1024:.1f} MB"
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(f"[{ts}] {sender}: 📁 {filename} ({size_str})\n")

            else:
                cursor.movePosition(QTextCursor.MoveOperation.End)
                cursor.insertText(f"[{ts}] {sender}: {content}\n")

        sb = self._message_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def save_file_from_message(self, msg: dict):
        """Save a file attachment from a message to disk."""
        content = msg.get("content", "")
        filename = msg.get("filename", "download")
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save File", filename)
        if not save_path:
            return
        try:
            file_bytes = base64.b64decode(content)
            with open(save_path, "wb") as f:
                f.write(file_bytes)
        except Exception:
            logger.error("Failed to save file: %s", save_path)
