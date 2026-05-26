import logging
import socket
import threading
import time

from shared.constants import PacketType, HEALTH_CHECK_INTERVAL
from shared.protocol import send_packet, read_packet

logger = logging.getLogger(__name__)


class ServerInfo:
    def __init__(self, server_id: str, host: str, port: int):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.connection_count = 0
        self.cpu_load = 0
        self.is_up = False
        self.last_check = 0.0


class HealthChecker(threading.Thread):
    """Periodically queries all chat servers for their health status."""

    def __init__(self, servers: list[dict]):
        super().__init__(daemon=True)
        self._lock = threading.Lock()
        self._servers: dict[str, ServerInfo] = {}
        self._running = False

        for s in servers:
            info = ServerInfo(s["server_id"], s["host"], s["port"])
            self._servers[s["server_id"]] = info

    def run(self):
        self._running = True
        logger.info("Health checker started for %d servers", len(self._servers))
        while self._running:
            self._check_all()
            time.sleep(HEALTH_CHECK_INTERVAL)

    def stop(self):
        self._running = False

    def get_least_loaded(self) -> ServerInfo | None:
        """Return the UP server with the fewest connections. Tiebreak by cpu_load."""
        with self._lock:
            up_servers = [s for s in self._servers.values() if s.is_up]
            if not up_servers:
                return None
            up_servers.sort(key=lambda s: (s.connection_count, s.cpu_load))
            return up_servers[0]

    def get_server_info(self, server_id: str) -> ServerInfo | None:
        with self._lock:
            return self._servers.get(server_id)

    def _check_all(self):
        for info in list(self._servers.values()):
            self._check_one(info)

    def _check_one(self, info: ServerInfo):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((info.host, info.port))
            send_packet(sock, PacketType.HEALTH_QUERY, {}, aes_key=None)
            response = read_packet(sock, aes_key=None)
            sock.close()

            with self._lock:
                info.connection_count = response.payload.get("connection_count", 0)
                info.cpu_load = response.payload.get("cpu_load", 0)
                info.is_up = True
                info.last_check = time.time()

        except Exception:
            with self._lock:
                info.is_up = False
                info.last_check = time.time()
            logger.debug("Server %s (%s:%d) is DOWN", info.server_id, info.host, info.port)
