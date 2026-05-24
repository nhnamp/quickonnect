import logging
import socket
import threading
import base64
import time

from shared.constants import PacketType, HEARTBEAT_TIMEOUT
from shared.protocol import read_packet, send_packet, Packet
from shared.crypto import (
    generate_rsa_keypair,
    serialize_public_key,
    deserialize_public_key,
    rsa_encrypt,
    generate_aes_key,
)

logger = logging.getLogger(__name__)


class ClientHandler(threading.Thread):
    """
    Handles a single client TCP connection in its own thread.
    Lifecycle: accept -> handshake (or health check) -> auth -> main loop -> disconnect.
    """

    def __init__(self, sock: socket.socket, addr: tuple, server):
        super().__init__(daemon=True)
        self._sock = sock
        self._addr = addr
        self._server = server
        self._aes_key: bytes | None = None
        self._send_lock = threading.Lock()
        self._running = False

        self.user_id: int | None = None
        self.username: str | None = None
        self._authenticated = False
        self._current_rooms: set[str] = set()
        self._last_heartbeat = time.time()

    def run(self):
        self._running = True
        peer = f"{self._addr[0]}:{self._addr[1]}"
        logger.info("New connection from %s", peer)
        try:
            first_packet = read_packet(self._sock, aes_key=None)

            if first_packet.packet_type == PacketType.HEALTH_QUERY:
                self._handle_health_query()
                return

            if first_packet.packet_type != PacketType.CLIENT_HELLO:
                logger.warning("Expected CLIENT_HELLO or HEALTH_QUERY, got %s from %s", first_packet.packet_type, peer)
                return

            if not self._do_handshake(first_packet):
                return

            if not self._do_auth():
                return

            self._server.register_client(self)
            self._main_loop()
        except ConnectionError:
            logger.info("Connection lost from %s", peer)
        except Exception:
            logger.exception("Error handling client %s", peer)
        finally:
            self._cleanup()

    def send(self, packet_type: PacketType, payload: dict) -> None:
        """Thread-safe packet send."""
        with self._send_lock:
            try:
                send_packet(self._sock, packet_type, payload, self._aes_key)
            except Exception:
                logger.debug("Failed to send packet to user %s", self.username)
                self._running = False

    def disconnect(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Handshake
    # ------------------------------------------------------------------

    def _do_handshake(self, hello_packet: Packet) -> bool:
        """Perform RSA key exchange. Returns True on success."""
        try:
            client_pub_pem = base64.b64decode(hello_packet.payload["public_key"])
            client_pub_key = deserialize_public_key(client_pub_pem)
        except Exception:
            logger.warning("Invalid CLIENT_HELLO from %s", self._addr)
            return False

        server_priv, server_pub = generate_rsa_keypair()
        aes_key = generate_aes_key()

        encrypted_aes = rsa_encrypt(client_pub_key, aes_key)

        response = {
            "public_key": base64.b64encode(serialize_public_key(server_pub)).decode("ascii"),
            "encrypted_session_key": base64.b64encode(encrypted_aes).decode("ascii"),
        }
        send_packet(self._sock, PacketType.SERVER_HELLO, response, aes_key=None)

        self._aes_key = aes_key
        logger.info("Handshake complete with %s", self._addr)
        return True

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _do_auth(self) -> bool:
        """Wait for an auth/register/login packet. Returns True on success."""
        self._sock.settimeout(30)
        try:
            packet = read_packet(self._sock, self._aes_key)
        except socket.timeout:
            logger.warning("Auth timeout from %s", self._addr)
            self.send(PacketType.ERROR, {"code": 408, "message": "Authentication timeout"})
            return False
        finally:
            self._sock.settimeout(None)

        auth_service = self._server.auth_service

        if packet.packet_type == PacketType.REGISTER_REQUEST:
            user, token, error = auth_service.register(
                packet.payload.get("username", ""),
                packet.payload.get("password", ""),
            )
            if error:
                self.send(PacketType.REGISTER_RESPONSE, {"success": False, "error": error})
                return False
            self.user_id = user.id
            self.username = user.username
            self._authenticated = True
            self.send(PacketType.REGISTER_RESPONSE, {
                "success": True, "token": token,
                "user_id": user.id, "username": user.username,
            })

        elif packet.packet_type == PacketType.LOGIN_REQUEST:
            user, token, error = auth_service.login(
                packet.payload.get("username", ""),
                packet.payload.get("password", ""),
            )
            if error:
                self.send(PacketType.LOGIN_RESPONSE, {"success": False, "error": error})
                return False
            self.user_id = user.id
            self.username = user.username
            self._authenticated = True
            self.send(PacketType.LOGIN_RESPONSE, {
                "success": True, "token": token,
                "user_id": user.id, "username": user.username,
            })

        elif packet.packet_type == PacketType.AUTH_REQUEST:
            token = packet.payload.get("token", "")
            user = auth_service.validate_token(token)
            if user is None:
                self.send(PacketType.AUTH_RESPONSE, {"success": False, "error": "Invalid or expired token"})
                return False
            self.user_id = user.id
            self.username = user.username
            self._authenticated = True
            self.send(PacketType.AUTH_RESPONSE, {
                "success": True, "user_id": user.id, "username": user.username,
            })

        else:
            self.send(PacketType.ERROR, {"code": 400, "message": "Expected auth packet"})
            return False

        logger.info("User authenticated: %s (id=%d)", self.username, self.user_id)

        self._send_friend_list()
        return True

    # ------------------------------------------------------------------
    # Main packet loop
    # ------------------------------------------------------------------

    def _main_loop(self):
        self._sock.settimeout(HEARTBEAT_TIMEOUT)
        while self._running:
            try:
                packet = read_packet(self._sock, self._aes_key)
            except socket.timeout:
                logger.info("Heartbeat timeout for user %s", self.username)
                break
            except ConnectionError:
                break

            self._last_heartbeat = time.time()
            self._dispatch(packet)

    def _dispatch(self, packet: Packet):
        handlers = {
            PacketType.JOIN_ROOM: self._handle_join_room,
            PacketType.LEAVE_ROOM: self._handle_leave_room,
            PacketType.CHAT_MESSAGE: self._handle_chat_message,
            PacketType.FRIEND_REQUEST: self._handle_friend_request,
            PacketType.FRIEND_RESPONSE: self._handle_friend_response,
            PacketType.HEARTBEAT: self._handle_heartbeat,
        }
        handler = handlers.get(packet.packet_type)
        if handler:
            try:
                handler(packet)
            except Exception:
                logger.exception("Error handling packet %s from %s", packet.packet_type, self.username)
        else:
            logger.debug("Unhandled packet type %s from %s", packet.packet_type, self.username)

    # ------------------------------------------------------------------
    # Packet handlers
    # ------------------------------------------------------------------

    def _handle_health_query(self):
        count = self._server.get_connection_count()
        send_packet(self._sock, PacketType.HEALTH_RESPONSE, {
            "connection_count": count,
            "cpu_load": 0,
        }, aes_key=None)
        self._sock.close()

    def _handle_heartbeat(self, packet: Packet):
        self.send(PacketType.HEARTBEAT, {"timestamp": int(time.time())})

    def _handle_join_room(self, packet: Packet):
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code:
            self.send(PacketType.ERROR, {"code": 400, "message": "Room code required"})
            return

        room_manager = self._server.room_manager
        state, error = room_manager.join_room(room_code, self.user_id, self.username, self)

        if error:
            if error.startswith("REDIRECT:"):
                target_server = error.split(":", 1)[1]
                server_info = self._server.get_server_address(target_server)
                self.send(PacketType.ERROR, {
                    "code": 307,
                    "message": f"Room is on another server",
                    "redirect_host": server_info[0] if server_info else "",
                    "redirect_port": server_info[1] if server_info else 0,
                    "room_code": room_code,
                })
            else:
                self.send(PacketType.ERROR, {"code": 500, "message": error})
            return

        self._current_rooms.add(room_code)
        self.send(PacketType.ROOM_STATE, state.to_dict())

        history = self._server.message_service.get_history(state.room_id)
        self.send(PacketType.MESSAGE_HISTORY, {
            "room_id": state.room_id,
            "messages": [m.to_dict() for m in history],
        })

        clients = room_manager.get_room_clients(room_code)
        for uid, handler in clients.items():
            if uid != self.user_id:
                handler.send(PacketType.ROOM_UPDATE, {
                    "room_code": room_code,
                    "event": "joined",
                    "user_id": self.user_id,
                    "username": self.username,
                })

    def _handle_leave_room(self, packet: Packet):
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code:
            return

        self._current_rooms.discard(room_code)
        remaining = self._server.room_manager.leave_room(room_code, self.user_id)

        for handler in remaining:
            handler.send(PacketType.ROOM_UPDATE, {
                "room_code": room_code,
                "event": "left",
                "user_id": self.user_id,
                "username": self.username,
            })

    def _handle_chat_message(self, packet: Packet):
        room_code = packet.payload.get("room_code", "")
        content = packet.payload.get("content", "")
        msg_type = packet.payload.get("msg_type", "text")

        if not room_code or not content:
            return

        room = self._server.room_manager.get_room(room_code)
        if room is None:
            self.send(PacketType.ERROR, {"code": 404, "message": "Room not found"})
            return

        msg = self._server.message_service.store_message(room.id, self.user_id, content, msg_type)
        if msg is None:
            self.send(PacketType.ERROR, {"code": 500, "message": "Failed to store message"})
            return

        msg.sender_name = self.username
        msg_data = msg.to_dict()
        msg_data["room_code"] = room_code

        clients = self._server.room_manager.get_room_clients(room_code)
        for uid, handler in clients.items():
            handler.send(PacketType.CHAT_MESSAGE, msg_data)

    def _handle_friend_request(self, packet: Packet):
        target_username = packet.payload.get("target_username", "").strip()
        if not target_username:
            return

        friend_service = self._server.friend_service
        success, error = friend_service.send_request(self.user_id, target_username)

        if not success:
            self.send(PacketType.ERROR, {"code": 400, "message": error})
            return

        self._server.publish_friend_event({
            "type": "friend_request",
            "from_user_id": self.user_id,
            "from_username": self.username,
            "to_username": target_username,
        })

        self.send(PacketType.FRIEND_UPDATE, {
            "event": "request_sent",
            "target_username": target_username,
        })

    def _handle_friend_response(self, packet: Packet):
        from_user_id = packet.payload.get("from_user_id")
        accept = packet.payload.get("accept", False)

        if from_user_id is None:
            return

        friend_service = self._server.friend_service
        success, error = friend_service.respond_to_request(self.user_id, from_user_id, accept)

        if not success:
            self.send(PacketType.ERROR, {"code": 400, "message": error})
            return

        self._send_friend_list()

        if accept:
            self._server.publish_friend_event({
                "type": "friend_accepted",
                "from_user_id": self.user_id,
                "from_username": self.username,
                "to_user_id": from_user_id,
            })

    def _send_friend_list(self):
        friends = self._server.friend_service.get_friends(self.user_id)
        online_users = self._server.get_online_users()
        for f in friends:
            f.online = f.user_id in online_users
        self.send(PacketType.FRIEND_LIST, {
            "friends": [f.to_dict() for f in friends],
        })

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self):
        self._running = False
        if self.user_id is not None:
            left_rooms = self._server.room_manager.remove_client_from_all_rooms(self.user_id)
            for room_code in left_rooms:
                clients = self._server.room_manager.get_room_clients(room_code)
                for uid, handler in clients.items():
                    handler.send(PacketType.ROOM_UPDATE, {
                        "room_code": room_code,
                        "event": "left",
                        "user_id": self.user_id,
                        "username": self.username,
                    })
            self._server.unregister_client(self)
        try:
            self._sock.close()
        except Exception:
            pass
        logger.info("Client disconnected: %s (user=%s)", self._addr, self.username)
