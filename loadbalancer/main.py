import logging
import signal
import socket
import threading

import redis

from loadbalancer.config import LBConfig
from loadbalancer.health_checker import HealthChecker
from loadbalancer.router import Router

logger = logging.getLogger(__name__)


class LoadBalancer:
    def __init__(self, config: LBConfig):
        self.config = config
        self._redis = redis.Redis(
            host=config.redis_host, port=config.redis_port, decode_responses=True,
        )
        self._health_checker = HealthChecker(config.chat_servers)
        self._router = Router(self._health_checker, self._redis)
        self._server_sock: socket.socket | None = None
        self._running = False

    def start(self):
        logger.info("Starting load balancer on %s:%d", self.config.host, self.config.port)
        self._health_checker.start()

        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.config.host, self.config.port))
        self._server_sock.listen(64)
        self._server_sock.settimeout(1.0)
        self._running = True

        logger.info("Load balancer is ready")

        while self._running:
            try:
                client_sock, addr = self._server_sock.accept()
                t = threading.Thread(
                    target=self._router.handle_client,
                    args=(client_sock, addr),
                    daemon=True,
                )
                t.start()
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    logger.exception("Accept error in LB")
                break

    def stop(self):
        logger.info("Stopping load balancer")
        self._running = False
        self._health_checker.stop()
        if self._server_sock:
            try:
                self._server_sock.close()
            except Exception:
                pass


def run_lb(config: LBConfig | None = None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if config is None:
        config = LBConfig()

    lb = LoadBalancer(config)

    def handle_signal(signum, frame):
        logger.info("Received signal %d, shutting down LB...", signum)
        lb.stop()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    lb.start()


if __name__ == "__main__":
    run_lb()
