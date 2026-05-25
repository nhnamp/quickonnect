import logging
import ipaddress
import socket
import threading

import redis

from shared.constants import PacketType
from shared.protocol import read_packet, send_packet
from loadbalancer.health_checker import HealthChecker

logger = logging.getLogger(__name__)


class Router:
    """
    Room-aware load balancer router.
    - If a room code is provided and already mapped to a server: route there.
    - Otherwise: pick the least-loaded UP server.
    """

    def __init__(self, health_checker: HealthChecker, redis_client: redis.Redis):
        self._hc = health_checker
        self._redis = redis_client

    def handle_client(self, client_sock: socket.socket, addr: tuple):
        """Handle one LB client connection (short-lived)."""
        try:
            client_sock.settimeout(10)
            packet = read_packet(client_sock, aes_key=None)

            if packet.packet_type != PacketType.CONNECT_REQUEST:
                logger.warning("Expected CONNECT_REQUEST from %s, got %s", addr, packet.packet_type)
                send_packet(client_sock, PacketType.ERROR, {
                    "code": 400, "message": "Expected CONNECT_REQUEST",
                }, aes_key=None)
                client_sock.close()
                return

            room_code = packet.payload.get("room_code")
            target = self._resolve(room_code)

            if target is None:
                send_packet(client_sock, PacketType.ERROR, {
                    "code": 503, "message": "No available servers",
                }, aes_key=None)
            else:
                host = self._advertised_host(target.host, client_sock)
                send_packet(client_sock, PacketType.CONNECT_RESPONSE, {
                    "server_ip": host,
                    "server_port": target.port,
                }, aes_key=None)
                logger.info(
                    "Routed client %s to %s:%d (room=%s)",
                    addr, host, target.port, room_code or "none",
                )

        except Exception:
            logger.debug("Error handling LB client %s", addr)
        finally:
            try:
                client_sock.close()
            except Exception:
                pass

    def _resolve(self, room_code: str | None):
        """Resolve which server to route to.

        DM rooms (codes prefixed with 'DM-') are server-agnostic: the LB does
        not look up or write a room->server pin for them. The two participants
        may end up on different chat servers; cross-server delivery happens
        via Redis pub/sub on the 'dm_messages' channel.
        """
        is_dm = bool(room_code) and room_code.startswith("DM-")

        if room_code and not is_dm:
            server_id = self._get_room_server(room_code)
            if server_id:
                info = self._hc.get_server_info(server_id)
                if info and info.is_up:
                    return info
                logger.warning("Room %s mapped to server %s which is DOWN", room_code, server_id)

        target = self._hc.get_least_loaded()
        if target and room_code and not is_dm:
            self._set_room_server(room_code, target.server_id)

        return target

    def _advertised_host(self, configured_host: str, client_sock: socket.socket) -> str:
        """Return an address the requesting client can use to reach the chat server.

        The load balancer may health-check local chat servers through 127.0.0.1,
        but a second laptop cannot use that address because it points back to
        itself. When a server host is loopback or wildcard, advertise the local
        interface address that the client used to reach this LB connection.
        """
        if not self._is_local_only_host(configured_host):
            return configured_host

        try:
            local_host = client_sock.getsockname()[0]
        except OSError:
            local_host = ""

        if local_host and not self._is_unspecified_host(local_host):
            return local_host
        return "127.0.0.1"

    @staticmethod
    def _is_local_only_host(host: str) -> bool:
        normalized = host.strip().lower()
        if normalized == "localhost":
            return True
        try:
            addr = ipaddress.ip_address(normalized)
        except ValueError:
            return False
        return addr.is_loopback or addr.is_unspecified

    @staticmethod
    def _is_unspecified_host(host: str) -> bool:
        try:
            return ipaddress.ip_address(host.strip()).is_unspecified
        except ValueError:
            return False

    def _get_room_server(self, room_code: str) -> str | None:
        try:
            val = self._redis.get(f"room:{room_code}")
            if val is None:
                return None
            return val if isinstance(val, str) else val.decode("utf-8")
        except Exception:
            return None

    def _set_room_server(self, room_code: str, server_id: str):
        try:
            self._redis.set(f"room:{room_code}", server_id)
        except Exception:
            logger.warning("Failed to set room->server mapping in Redis")
