import logging
import socket

from shared.constants import PacketType
from shared.protocol import send_packet, read_packet

logger = logging.getLogger(__name__)


def request_server(lb_host: str, lb_port: int, room_code: str | None = None) -> tuple[str, int]:
    """
    Connect to the load balancer and request a chat server assignment.
    Returns (server_host, server_port).
    Raises ConnectionError on failure.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    try:
        sock.connect((lb_host, lb_port))

        payload = {}
        if room_code:
            payload["room_code"] = room_code

        send_packet(sock, PacketType.CONNECT_REQUEST, payload, aes_key=None)
        response = read_packet(sock, aes_key=None)

        if response.packet_type == PacketType.ERROR:
            raise ConnectionError(response.payload.get("message", "Load balancer error"))

        if response.packet_type != PacketType.CONNECT_RESPONSE:
            raise ConnectionError(f"Unexpected response: {response.packet_type}")

        host = response.payload["server_ip"]
        port = response.payload["server_port"]
        
        # If the server is bound to all interfaces or localhost, 
        # replace it with the LB's host so remote clients know where to connect.
        if host in ("0.0.0.0", "127.0.0.1", "localhost", "::", ""):
            host = lb_host

        logger.info("LB assigned server %s:%d (room=%s)", host, port, room_code or "none")
        return host, port

    finally:
        try:
            sock.close()
        except Exception:
            pass
