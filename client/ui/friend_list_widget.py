import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QListWidgetItem, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from shared.constants import PacketType

logger = logging.getLogger(__name__)


class FriendListWidget(QWidget):
    """Friends panel with online status, add friend, and pending request handling."""
    send_packet = pyqtSignal(int, dict)
    start_dm = pyqtSignal(str)  # friend's username -> open DM room

    def __init__(self):
        super().__init__()
        self._friends: list[dict] = []
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        title = QLabel("Friends")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        add_row = QHBoxLayout()
        self._add_input = QLineEdit()
        self._add_input.setPlaceholderText("Username to add...")
        self._add_input.returnPressed.connect(self._on_add_friend)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._on_add_friend)
        add_row.addWidget(self._add_input)
        add_row.addWidget(add_btn)
        layout.addLayout(add_row)

        pending_label = QLabel("Pending Requests")
        pending_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(pending_label)

        self._pending_list = QListWidget()
        self._pending_list.setMaximumHeight(120)
        layout.addWidget(self._pending_list)

        friends_label = QLabel("Online / Offline")
        friends_label.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(friends_label)

        self._friend_list = QListWidget()
        self._friend_list.itemDoubleClicked.connect(self._on_friend_double_click)
        layout.addWidget(self._friend_list)

    def _on_add_friend(self):
        username = self._add_input.text().strip()
        if not username:
            return
        self.send_packet.emit(PacketType.FRIEND_REQUEST, {"target_username": username})
        self._add_input.clear()

    def _on_friend_double_click(self, item: QListWidgetItem):
        username = item.data(Qt.ItemDataRole.UserRole)
        if username:
            self.start_dm.emit(username)

    def update_friends(self, friends: list[dict]):
        """Full refresh of the friend list."""
        self._friends = friends
        self._refresh_lists()

    def handle_friend_update(self, data: dict):
        """Handle incremental friend updates."""
        event = data.get("event", "")

        if event == "status":
            user_id = data.get("user_id")
            online = data.get("online", False)
            for f in self._friends:
                if f.get("user_id") == user_id:
                    f["online"] = online
                    break
            self._refresh_lists()

        elif event == "request_sent":
            QMessageBox.information(
                self, "Friend Request",
                f"Request sent to {data.get('target_username', '')}",
            )

        elif event == "incoming_request":
            from_name = data.get("from_username", "")
            QMessageBox.information(
                self, "Friend Request",
                f"{from_name} sent you a friend request!",
            )

    def _refresh_lists(self):
        self._pending_list.clear()
        self._friend_list.clear()

        for f in self._friends:
            status = f.get("status", "")
            username = f.get("username", "")
            user_id = f.get("user_id", 0)

            if status == "incoming":
                item_widget = QWidget()
                h = QHBoxLayout(item_widget)
                h.setContentsMargins(2, 2, 2, 2)
                h.addWidget(QLabel(f"{username}"))
                accept_btn = QPushButton("Accept")
                reject_btn = QPushButton("Reject")
                accept_btn.setFixedWidth(60)
                reject_btn.setFixedWidth(60)

                def make_handler(uid, accept):
                    return lambda: self._respond(uid, accept)

                accept_btn.clicked.connect(make_handler(user_id, True))
                reject_btn.clicked.connect(make_handler(user_id, False))
                h.addWidget(accept_btn)
                h.addWidget(reject_btn)

                item = QListWidgetItem()
                item.setSizeHint(item_widget.sizeHint())
                self._pending_list.addItem(item)
                self._pending_list.setItemWidget(item, item_widget)

            elif status == "accepted":
                online = f.get("online", False)
                indicator = " [online]" if online else ""
                item = QListWidgetItem(f"{username}{indicator}")
                item.setData(Qt.ItemDataRole.UserRole, username)
                if online:
                    item.setForeground(QColor("green"))
                else:
                    item.setForeground(QColor("gray"))
                self._friend_list.addItem(item)

    def _respond(self, from_user_id: int, accept: bool):
        self.send_packet.emit(PacketType.FRIEND_RESPONSE, {
            "from_user_id": from_user_id,
            "accept": accept,
        })
