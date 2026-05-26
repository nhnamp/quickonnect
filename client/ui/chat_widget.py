import logging
from datetime import datetime
from html import escape

import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem,
    QSplitter, QInputDialog, QFileDialog, QMessageBox,
)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QImage, QTextDocument

from shared.constants import PacketType
from shared.attachments import (
    build_attachment_content,
    decode_attachment_data,
    human_size,
    parse_attachment_content,
)

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
        self._file_btn = QPushButton("File")
        self._file_btn.clicked.connect(self._on_send_file)
        self._file_btn.setEnabled(False)
        self._image_btn = QPushButton("Image")
        self._image_btn.clicked.connect(self._on_send_image)
        self._image_btn.setEnabled(False)
        self._save_btn = QPushButton("Save Attachment")
        self._save_btn.clicked.connect(self._on_save_attachment)
        self._save_btn.setEnabled(False)
        input_row.addWidget(self._msg_input)
        input_row.addWidget(self._send_btn)
        input_row.addWidget(self._file_btn)
        input_row.addWidget(self._image_btn)
        input_row.addWidget(self._save_btn)
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
        self._file_btn.setEnabled(True)
        self._image_btn.setEnabled(True)
        self._refresh_attachment_button()
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
        self._file_btn.setEnabled(True)
        self._image_btn.setEnabled(True)
        self._refresh_attachment_button()
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

    def _on_send_file(self):
        self._send_attachment(force_image=False)

    def _on_send_image(self):
        self._send_attachment(force_image=True)

    def _send_attachment(self, force_image: bool):
        if not self._current_room:
            return
        if force_image:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Send Image",
                "",
                "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp);;All Files (*)",
            )
        else:
            path, _ = QFileDialog.getOpenFileName(self, "Send File")
        if not path:
            return
        content, error = build_attachment_content(path, force_image=force_image)
        if error or content is None:
            QMessageBox.warning(self, "Attachment", error or "Could not prepare attachment.")
            return
        self.send_packet.emit(PacketType.CHAT_MESSAGE, {
            "room_code": self._current_room,
            "content": content,
            "msg_type": "image" if force_image else "file",
        })

    def _on_save_attachment(self):
        attachments = self._current_attachments()
        if not attachments:
            return
        labels = [
            f"{idx + 1}. {payload['filename']} ({human_size(payload['size_bytes'])})"
            for idx, payload in enumerate(attachments)
        ]
        selected, ok = QInputDialog.getItem(
            self,
            "Save Attachment",
            "Choose attachment:",
            labels,
            len(labels) - 1,
            False,
        )
        if not ok or not selected:
            return
        selected_index = labels.index(selected)
        payload = attachments[selected_index]
        suggested = os.path.basename(payload["filename"])
        path, _ = QFileDialog.getSaveFileName(self, "Save Attachment", suggested)
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(decode_attachment_data(payload))
        except OSError as exc:
            QMessageBox.warning(self, "Save Attachment", f"Could not save file: {exc}")

    def add_message(self, msg: dict):
        """Called when a CHAT_MESSAGE arrives from the server."""
        room_code = msg.get("room_code", "")
        if room_code and room_code not in self._room_messages:
            self.add_room(room_code)

        if room_code:
            self._room_messages.setdefault(room_code, []).append(msg)

        if room_code == self._current_room:
            self._update_message_view()
            self._refresh_attachment_button()

    def load_history(self, room_id: int, messages: list[dict], room_code: str = ""):
        """Called when MESSAGE_HISTORY arrives."""
        target_room = room_code if room_code in self._room_messages else None
        if target_room is None and self._current_room and self._current_room in self._room_messages:
            target_room = self._current_room
        if target_room is None:
            target_room = None
            for code, msgs in self._room_messages.items():
                if any(m.get("room_id") == room_id for m in msgs):
                    target_room = code
                    break

        if target_room is None:
            return

        self._room_messages[target_room] = messages + self._room_messages.get(target_room, [])
        if target_room == self._current_room:
            self._update_message_view()
            self._refresh_attachment_button()

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

        html_parts = []
        document = self._message_view.document()
        for idx, m in enumerate(messages):
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
            line = f"[{escape(str(ts))}] {escape(str(sender))}: "
            if msg_type in {"image", "file"}:
                attachment = parse_attachment_content(str(content))
                if attachment:
                    if str(attachment.get("mime_type", "")).startswith("image/"):
                        rendered = self._render_image_attachment(document, idx, attachment)
                        if rendered:
                            html_parts.append(line + rendered)
                            continue
                    kind = "image" if msg_type == "image" else "file"
                    content = (
                        f"[{kind}: {attachment['filename']} "
                        f"({human_size(attachment['size_bytes'])})]"
                    )
            html_parts.append(line + escape(str(content)))

        self._message_view.setHtml("<br>".join(html_parts))
        sb = self._message_view.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._refresh_attachment_button()

    def _render_image_attachment(self, document: QTextDocument, index: int, payload: dict) -> str:
        try:
            image = QImage.fromData(decode_attachment_data(payload))
        except Exception:
            return ""
        if image.isNull():
            return ""

        max_width = 360
        max_height = 240
        shown = image.scaled(
            max_width,
            max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        resource_url = QUrl(f"quickonnect-image://{self._current_room}/{index}")
        document.addResource(QTextDocument.ResourceType.ImageResource, resource_url, shown)

        filename = escape(str(payload["filename"]))
        size = escape(human_size(payload["size_bytes"]))
        width = shown.width()
        height = shown.height()
        return (
            f"<span style='color:#d6d6d6'>[image: {filename} ({size})]</span>"
            f"<br><img src='{resource_url.toString()}' width='{width}' height='{height}'>"
        )

    def _current_attachments(self) -> list[dict]:
        if not self._current_room:
            return []
        attachments = []
        for msg in self._room_messages.get(self._current_room, []):
            if msg.get("msg_type") not in {"image", "file"}:
                continue
            payload = parse_attachment_content(str(msg.get("content", "")))
            if payload:
                attachments.append(payload)
        return attachments

    def _refresh_attachment_button(self) -> None:
        self._save_btn.setEnabled(bool(self._current_attachments()))
