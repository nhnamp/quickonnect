import sys
import logging

from PyQt6.QtWidgets import QApplication

from client.config import ClientConfig
from client.network.connection import ConnectionManager
from client.storage.local_store import LocalStore
from client.ui.login_window import LoginWindow
from client.ui.main_window import MainWindow


logger = logging.getLogger(__name__)


class App:
    def __init__(self):
        self._config = ClientConfig()
        self._conn = ConnectionManager()
        self._store = LocalStore(self._config.data_dir)
        self._login_window: LoginWindow | None = None
        self._main_window: MainWindow | None = None

    def run(self):
        app = QApplication(sys.argv)
        app.setApplicationName("QuicKonNect")

        self._show_login()
        sys.exit(app.exec())

    def _show_login(self):
        self._conn = ConnectionManager()
        self._login_window = LoginWindow(
            self._conn, self._store, self._config.lb_host, self._config.lb_port,
        )
        self._login_window.login_success.connect(self._on_login_success)
        self._login_window.show()

    def _on_login_success(self, user_info: dict):
        if self._login_window:
            self._login_window.close()
            self._login_window = None

        self._main_window = MainWindow(self._conn, self._store, user_info)
        self._main_window.logout_requested.connect(self._on_logout)
        self._main_window.show()

    def _on_logout(self):
        if self._main_window:
            self._main_window = None
        self._show_login()


def run_client():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    app = App()
    app.run()


if __name__ == "__main__":
    run_client()
