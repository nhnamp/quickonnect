"""Client-side TCP connection manager with auto-reconnect.

Manages the encrypted TCP connection to the chat server, running a
receiver thread and a heartbeat thread in the background. Incoming
packets are placed in a queue for the UI to consume via QTimer polling.

When ``enable_reconnect()`` is called, a disconnection triggers an
automatic reconnection loop with exponential backoff.  On success the
connection re-authenticates and rejoins any rooms the client was in.
"""

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

_MAX_RECONNECT_ATTEMPTS = 10
_INITIAL_BACKOFF = 1.0
_MAX_BACKOFF = 30.0


class ConnectionManager:
    """Manages the encrypted TCP connection to the chat server.

    Runs a receiver thread and a heartbeat thread in the background.
    Incoming packets are placed in a queue for the UI to consume.
    Supports automatic reconnection with exponential backoff.
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
        self.on_reconnecting: callable = None   # (attempt, max_attempts)
        self.on_reconnected: callable = None

        # Reconnection state
        self._reconnect_enabled = False
        self._reconnect_host: str | None = None
        self._reconnect_port: int | None = None
        self._reconnect_auth_payload: dict | None = None
        self._reconnect_auth_type: str | None = None
        self._reconnect_room_codes: list[str] = []
        self._reconnecting = False

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
        """Intentional disconnect — disables auto-reconnect."""
        self._reconnect_enabled = False
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

    # ------------------------------------------------------------------
    # Reconnection
    # ------------------------------------------------------------------

    def enable_reconnect(self, host: str, port: int,
                         auth_payload: dict, auth_type: str,
                         room_codes: list[str] | None = None) -> None:
        """Enable auto-reconnect on disconnect.

        Parameters
        ----------
        host, port : server address to reconnect to.
        auth_payload : dict with ``token`` (JWT) or ``username``/``password``.
        auth_type : one of 'jwt', 'login', or 'register'.
        room_codes : rooms to rejoin after re-auth.
        """
        self._reconnect_enabled = True
        self._reconnect_host = host
        self._reconnect_port = port
        self._reconnect_auth_payload = auth_payload
        self._reconnect_auth_type = auth_type
        self._reconnect_room_codes = list(room_codes or [])

    def disable_reconnect(self) -> None:
        """Disable auto-reconnect (e.g. during intentional logout)."""
        self._reconnect_enabled = False

    def update_room_codes(self, room_codes: list[str]) -> None:
        """Update the list of rooms to rejoin on reconnect."""
        self._reconnect_room_codes = list(room_codes)

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Background loops
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Disconnect handling
    # ------------------------------------------------------------------

    def _handle_disconnect(self, reason: str) -> None:
        if not self._running:
            return
        self._running = False

        # Close the socket so any blocking recv unblocks
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        self._aes_key = None

        if self._reconnect_enabled and not self._reconnecting:
            # Attempt auto-reconnect in a separate thread
            self._reconnecting = True
            thread = threading.Thread(target=self._reconnect_loop, args=(reason,), daemon=True)
            thread.start()
        else:
            logger.info("Disconnected: %s", reason)
            if self.on_disconnected:
                self.on_disconnected(reason)

    def _reconnect_loop(self, original_reason: str) -> None:
        """Attempt reconnection with exponential backoff."""
        backoff = _INITIAL_BACKOFF
        for attempt in range(1, _MAX_RECONNECT_ATTEMPTS + 1):
            if not self._reconnect_enabled:
                break

            logger.info("Reconnect attempt %d/%d (backoff %.1fs)",
                        attempt, _MAX_RECONNECT_ATTEMPTS, backoff)
            if self.on_reconnecting:
                try:
                    self.on_reconnecting(attempt, _MAX_RECONNECT_ATTEMPTS)
                except Exception:
                    pass

            time.sleep(backoff)

            try:
                # Create new socket and connect
                self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._sock.settimeout(10)
                self._sock.connect((self._reconnect_host, self._reconnect_port))
                self._sock.settimeout(None)

                # Re-handshake
                self._do_handshake()
                self._running = True

                # Re-authenticate
                if not self._do_reconnect_auth():
                    raise ConnectionError("Re-authentication failed")

                # Restart background threads
                self._receiver_thread = threading.Thread(
                    target=self._receiver_loop, daemon=True)
                self._receiver_thread.start()

                self._heartbeat_thread = threading.Thread(
                    target=self._heartbeat_loop, daemon=True)
                self._heartbeat_thread.start()

                # Rejoin rooms
                self._do_rejoin_rooms()

                logger.info("Reconnected successfully on attempt %d", attempt)
                self._reconnecting = False
                if self.on_reconnected:
                    try:
                        self.on_reconnected()
                    except Exception:
                        pass
                return

            except Exception as e:
                logger.warning("Reconnect attempt %d failed: %s", attempt, e)
                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                    self._sock = None
                self._aes_key = None
                self._running = False

                # Exponential backoff
                backoff = min(backoff * 2, _MAX_BACKOFF)

        # All attempts exhausted
        self._reconnecting = False
        self._reconnect_enabled = False
        logger.info("Reconnection failed after %d attempts", _MAX_RECONNECT_ATTEMPTS)
        if self.on_disconnected:
            self.on_disconnected(
                f"Reconnection failed after {_MAX_RECONNECT_ATTEMPTS} attempts "
                f"(original: {original_reason})"
            )

    def _do_reconnect_auth(self) -> bool:
        """Re-authenticate after reconnecting. Returns True on success."""
        auth_type = self._reconnect_auth_type
        payload = self._reconnect_auth_payload
        if not payload:
            return False

        try:
            if auth_type == "jwt":
                send_packet(self._sock, PacketType.AUTH_REQUEST,
                            {"token": payload.get("token", "")}, self._aes_key)
                resp = read_packet(self._sock, self._aes_key)
                return resp.payload.get("success", False)
            elif auth_type == "login":
                send_packet(self._sock, PacketType.LOGIN_REQUEST, {
                    "username": payload.get("username", ""),
                    "password": payload.get("password", ""),
                }, self._aes_key)
                resp = read_packet(self._sock, self._aes_key)
                if resp.payload.get("success"):
                    # Update stored token for future reconnects
                    new_token = resp.payload.get("token")
                    if new_token:
                        self._reconnect_auth_payload = {"token": new_token}
                        self._reconnect_auth_type = "jwt"
                    return True
                return False
            else:
                return False
        except Exception:
            logger.debug("Reconnect auth failed")
            return False

    def _do_rejoin_rooms(self) -> None:
        """Rejoin all rooms after reconnection."""
        for room_code in self._reconnect_room_codes:
            try:
                self.send(PacketType.JOIN_ROOM, {"room_code": room_code})
            except Exception:
                logger.debug("Failed to rejoin room %s", room_code)
