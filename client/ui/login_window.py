import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QMessageBox, QGroupBox, QFormLayout,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from shared.constants import PacketType
from shared.protocol import Packet
from client.network.lb_client import request_server
from client.network.connection import ConnectionManager
from client.storage.local_store import LocalStore

logger = logging.getLogger(__name__)


class _AuthWorker(QThread):
    """Background thread for LB connection + server connection + auth."""
    finished = pyqtSignal(bool, str, dict)  # success, error, user_info

    def __init__(self, lb_host, lb_port, conn_mgr, action, username, password, token):
        super().__init__()
        self._lb_host = lb_host
        self._lb_port = lb_port
        self._conn = conn_mgr
        self._action = action  # "login", "register", or "token"
        self._username = username
        self._password = password
        self._token = token

    def run(self):
        try:
            host, port = request_server(self._lb_host, self._lb_port)
            self._conn.connect(host, port)

            if self._action == "register":
                self._conn.send(PacketType.REGISTER_REQUEST, {
                    "username": self._username, "password": self._password,
                })
            elif self._action == "login":
                self._conn.send(PacketType.LOGIN_REQUEST, {
                    "username": self._username, "password": self._password,
                })
            elif self._action == "token":
                self._conn.send(PacketType.AUTH_REQUEST, {"token": self._token})

            packet = self._conn.packet_queue.get(timeout=15)
            expected_types = {
                "register": PacketType.REGISTER_RESPONSE,
                "login": PacketType.LOGIN_RESPONSE,
                "token": PacketType.AUTH_RESPONSE,
            }
            expected = expected_types[self._action]

            if packet.packet_type == expected:
                if packet.payload.get("success"):
                    self.finished.emit(True, "", packet.payload)
                else:
                    self._conn.disconnect()
                    self.finished.emit(False, packet.payload.get("error", "Auth failed"), {})
            elif packet.packet_type == PacketType.ERROR:
                self._conn.disconnect()
                self.finished.emit(False, packet.payload.get("message", "Server error"), {})
            else:
                self._conn.disconnect()
                self.finished.emit(False, f"Unexpected response: {packet.packet_type}", {})

        except Exception as e:
            self._conn.disconnect()
            self.finished.emit(False, str(e), {})


class LoginWindow(QWidget):
    login_success = pyqtSignal(dict)  # user_info with token

    def __init__(self, conn_mgr: ConnectionManager, local_store: LocalStore, lb_host: str, lb_port: int):
        super().__init__()
        self._conn = conn_mgr
        self._store = local_store
        self._lb_host = lb_host
        self._lb_port = lb_port
        self._worker: _AuthWorker | None = None

        self.setWindowTitle("QuicKonNect - Login")
        self.setFixedSize(400, 350)
        self._build_ui()
        self._try_saved_session()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("QuicKonNect")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; margin: 10px;")
        layout.addWidget(title)

        server_group = QGroupBox("Server")
        server_form = QFormLayout()
        self._host_input = QLineEdit(self._lb_host)
        self._port_input = QLineEdit(str(self._lb_port))
        server_form.addRow("LB Host:", self._host_input)
        server_form.addRow("LB Port:", self._port_input)
        server_group.setLayout(server_form)
        layout.addWidget(server_group)

        auth_group = QGroupBox("Account")
        auth_form = QFormLayout()
        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("Username (3-50 chars)")
        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._password_input.setPlaceholderText("Password (6+ chars)")
        auth_form.addRow("Username:", self._username_input)
        auth_form.addRow("Password:", self._password_input)
        auth_group.setLayout(auth_form)
        layout.addWidget(auth_group)

        btn_layout = QHBoxLayout()
        self._login_btn = QPushButton("Login")
        self._register_btn = QPushButton("Register")
        self._login_btn.clicked.connect(self._on_login)
        self._register_btn.clicked.connect(self._on_register)
        btn_layout.addWidget(self._login_btn)
        btn_layout.addWidget(self._register_btn)
        layout.addLayout(btn_layout)

        self._status_label = QLabel("")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.setStyleSheet("color: gray;")
        layout.addWidget(self._status_label)

        self._password_input.returnPressed.connect(self._on_login)

    def _try_saved_session(self):
        session = self._store.load_session()
        if session and session.get("token"):
            self._status_label.setText("Resuming session...")
            self._set_busy(True)
            self._start_auth("token", "", "", session["token"])

    def _on_login(self):
        username = self._username_input.text().strip()
        password = self._password_input.text()
        if not username or not password:
            self._status_label.setText("Enter username and password")
            self._status_label.setStyleSheet("color: red;")
            return
        self._set_busy(True)
        self._status_label.setText("Connecting...")
        self._status_label.setStyleSheet("color: gray;")
        self._start_auth("login", username, password, "")

    def _on_register(self):
        username = self._username_input.text().strip()
        password = self._password_input.text()
        if not username or not password:
            self._status_label.setText("Enter username and password")
            self._status_label.setStyleSheet("color: red;")
            return
        self._set_busy(True)
        self._status_label.setText("Registering...")
        self._status_label.setStyleSheet("color: gray;")
        self._start_auth("register", username, password, "")

    def _start_auth(self, action, username, password, token):
        lb_host = self._host_input.text().strip() or self._lb_host
        lb_port = int(self._port_input.text().strip() or self._lb_port)

        self._worker = _AuthWorker(lb_host, lb_port, self._conn, action, username, password, token)
        self._worker.finished.connect(self._on_auth_result)
        self._worker.start()

    def _on_auth_result(self, success: bool, error: str, user_info: dict):
        self._set_busy(False)
        if success:
            token = user_info.get("token", "")
            user_id = user_info.get("user_id", 0)
            username = user_info.get("username", "")
            if token:
                self._store.save_session(token, user_id, username)
            self.login_success.emit(user_info)
        else:
            self._status_label.setText(error)
            self._status_label.setStyleSheet("color: red;")
            self._store.clear_session()

    def _set_busy(self, busy: bool):
        self._login_btn.setEnabled(not busy)
        self._register_btn.setEnabled(not busy)
        self._username_input.setEnabled(not busy)
        self._password_input.setEnabled(not busy)
