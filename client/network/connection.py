import base64
import logging
import socket
import threading
import time
from queue import Queue, Empty

from shared.constants import PacketType, HEARTBEAT_INTERVAL
from shared.protocol import read_packet, send_packet, Packet
from shared.crypto import (
    generate_rsa_keypair,
    serialize_public_key,
    deserialize_public_key,
    rsa_decrypt,
)

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages the encrypted TCP connection to the chat server.
    Runs a receiver thread and a heartbeat thread in the background.
    Incoming packets are placed in a queue for the UI to consume.
    """

    def __init__(self):
        self._sock: socket.socket | None = None
        self._aes_key: bytes | None = None
        self._send_lock = threading.Lock()
        self._receiver_thread: threading.Thread | None = None
        self._heartbeat_thread: threading.Thread | None = None
        self._running = False

        self.packet_queue: Queue[Packet] = Queue()
        self.on_disconnected: callable = None

    @property
    def connected(self) -> bool:
        return self._running and self._sock is not None

    def connect(self, host: str, port: int) -> None:
        """Connect to a chat server and perform the RSA handshake."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(10)
        self._sock.connect((host, port))
        self._sock.settimeout(None)

        self._do_handshake()
        self._running = True

        self._receiver_thread = threading.Thread(target=self._receiver_loop, daemon=True)
        self._receiver_thread.start()

        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

        logger.info("Connected to server %s:%d", host, port)

    def disconnect(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._aes_key = None

    def send(self, packet_type: PacketType, payload: dict) -> None:
        """Thread-safe packet send."""
        if not self._running or self._sock is None:
            return
        with self._send_lock:
            try:
                send_packet(self._sock, packet_type, payload, self._aes_key)
            except Exception:
                logger.debug("Send failed")
                self._handle_disconnect("Send failed")

    def _do_handshake(self) -> None:
        """Perform RSA key exchange with the server."""
        client_priv, client_pub = generate_rsa_keypair()
        pub_pem = serialize_public_key(client_pub)

        send_packet(self._sock, PacketType.CLIENT_HELLO, {
            "public_key": base64.b64encode(pub_pem).decode("ascii"),
        }, aes_key=None)

        response = read_packet(self._sock, aes_key=None)
        if response.packet_type != PacketType.SERVER_HELLO:
            raise ConnectionError(f"Expected SERVER_HELLO, got {response.packet_type}")

        encrypted_key = base64.b64decode(response.payload["encrypted_session_key"])
        self._aes_key = rsa_decrypt(client_priv, encrypted_key)

        logger.info("Handshake complete, AES session key established")

    def _receiver_loop(self) -> None:
        while self._running:
            try:
                packet = read_packet(self._sock, self._aes_key)
                self.packet_queue.put(packet)
            except ConnectionError:
                self._handle_disconnect("Connection lost")
                break
            except Exception:
                if self._running:
                    logger.debug("Receiver error")
                    self._handle_disconnect("Receiver error")
                break

    def _heartbeat_loop(self) -> None:
        while self._running:
            time.sleep(HEARTBEAT_INTERVAL)
            if self._running:
                self.send(PacketType.HEARTBEAT, {"timestamp": int(time.time())})

    def _handle_disconnect(self, reason: str) -> None:
        if not self._running:
            return
        self._running = False
        logger.info("Disconnected: %s", reason)
        if self.on_disconnected:
            self.on_disconnected(reason)
