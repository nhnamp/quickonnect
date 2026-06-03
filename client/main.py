import sys
import logging
import argparse
import os

from PyQt6.QtWidgets import QApplication

from client.config import ClientConfig
from client.network.connection import ConnectionManager
import client.network.lb_client as lb_client
from client.storage.local_store import LocalStore
from client.ui.login_window import LoginWindow
from client.ui.main_window import MainWindow


logger = logging.getLogger(__name__)


class App:
    def __init__(self):
        self._config = ClientConfig()
        if self._config.direct_server:
            self._enable_direct_server_mode()
        self._conn = ConnectionManager()
        self._store = LocalStore(self._config.data_dir)
        self._login_window: LoginWindow | None = None
        self._main_window: MainWindow | None = None

    @staticmethod
    def _enable_direct_server_mode() -> None:
        """Treat the configured LB host/port as the actual chat server.

        This is useful for Ngrok TCP demos, where a single public tunnel
        points directly at one local chat server port.
        """
        def direct_server(host: str, port: int, room_code: str | None = None) -> tuple[str, int]:
            return host, port

        lb_client.request_server = direct_server
        try:
            import client.ui.login_window as login_window
            login_window.request_server = direct_server
        except ImportError:
            pass
        try:
            import client.ui.main_window as main_window
            main_window.request_server = direct_server
        except ImportError:
            pass

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


def _apply_cli_args() -> None:
    parser = argparse.ArgumentParser(description="Start the QuicKonNect desktop client")
    parser.add_argument("--host", help="Load balancer host, or direct server host with --direct-server")
    parser.add_argument("--port", type=int, help="Load balancer port, or direct server port with --direct-server")
    parser.add_argument(
        "--direct-server",
        action="store_true",
        help="Bypass the load balancer and connect directly to the host/port",
    )
    parser.add_argument("--data-dir", help="Override the local client data directory")
    args, remaining = parser.parse_known_args()
    sys.argv = [sys.argv[0], *remaining]

    if args.host:
        os.environ["LB_HOST"] = args.host
    if args.port is not None:
        os.environ["LB_PORT"] = str(args.port)
    if args.direct_server:
        os.environ["QUICKONNECT_DIRECT_SERVER"] = "1"
    if args.data_dir:
        os.environ["QUICKONNECT_DATA"] = args.data_dir


def run_client():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    _apply_cli_args()
    app = App()
    app.run()


if __name__ == "__main__":
    run_client()
