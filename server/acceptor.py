import logging
import socket
import threading

from server.client_handler import ClientHandler

logger = logging.getLogger(__name__)


class Acceptor(threading.Thread):
    """Listens for incoming TCP connections and spawns a ClientHandler thread for each."""

    def __init__(self, host: str, port: int, server):
        super().__init__(daemon=True)
        self._host = host
        self._port = port
        self._server = server
        self._server_sock: socket.socket | None = None
        self._running = False

    def run(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self._host, self._port))
        self._server_sock.listen(64)
        self._server_sock.settimeout(1.0)
        self._running = True

        logger.info("Acceptor listening on %s:%d", self._host, self._port)

        while self._running:
            try:
                client_sock, addr = self._server_sock.accept()
                handler = ClientHandler(client_sock, addr, self._server)
                handler.start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.exception("Accept error")
                break

    def stop(self):
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass
