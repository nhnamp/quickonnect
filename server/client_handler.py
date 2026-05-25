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
        self._e2e_public_key: str = ""  # Base64-encoded E2E public key

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
            PacketType.SCREEN_START: self._handle_screen_start,
            PacketType.SCREEN_STOP: self._handle_screen_stop,
            PacketType.SCREEN_FRAME: self._handle_screen_frame,
            PacketType.REMOTE_REQUEST: self._handle_remote_request,
            PacketType.REMOTE_GRANT: self._handle_remote_grant,
            PacketType.REMOTE_EVENT: self._handle_remote_event,
            PacketType.AUDIO_CHUNK: self._handle_audio_chunk,
            PacketType.DRAW_EVENT: self._handle_draw_event,
            PacketType.EXPORT_REQUEST: self._handle_export_request,
            PacketType.ROOM_INVITE: self._handle_room_invite,
            PacketType.PUBLIC_KEY_ANNOUNCE: self._handle_public_key_announce,
            PacketType.PUBLIC_KEY_REQUEST: self._handle_public_key_request,
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
        state_payload = state.to_dict()
        # If a screen share is already in progress in this room, tell the
        # joining client right away so its UI can show the active share
        # without waiting for the next frame.
        screen = room_manager.get_screen_state(room_code)
        if screen is not None and screen.is_sharing():
            info = screen.get_state()
            state_payload["screen"] = {
                "sharer_user_id": info.sharer_user_id,
                "sharer_username": info.sharer_username,
                "controller_user_id": info.controller_user_id,
                "controller_username": info.controller_username,
            }
        self.send(PacketType.ROOM_STATE, state_payload)

        history = self._server.message_service.get_history(state.room_id)
        self.send(PacketType.MESSAGE_HISTORY, {
            "room_id": state.room_id,
            "messages": [m.to_dict() for m in history],
        })

        wb = room_manager.get_whiteboard_state(room_code)
        if wb is not None:
            self.send(PacketType.WHITEBOARD_SYNC, {
                "room_code": room_code,
                "snapshot": wb.get_snapshot_b64(),
                "events": wb.get_active_events(),
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

        # Phase 2: surrender any share / control grant this user owned in
        # this room before we drop them from the participant list, so the
        # remaining members get the SCREEN_STOP / REMOTE_GRANT notification.
        screen = self._server.room_manager.get_screen_state(room_code)
        screen_stopped = False
        controller_cleared_info = None
        if screen is not None:
            if screen.stop_if_sharer(self.user_id):
                screen_stopped = True
            elif screen.clear_controller_if(self.user_id):
                controller_cleared_info = screen.get_state()

        if screen_stopped:
            clients = self._server.room_manager.get_room_clients(room_code)
            for uid, handler in clients.items():
                if uid != self.user_id:
                    handler.send(PacketType.SCREEN_STOP, {
                        "room_code": room_code,
                        "sharer_user_id": self.user_id,
                    })
        elif controller_cleared_info is not None:
            clients = self._server.room_manager.get_room_clients(room_code)
            for uid, handler in clients.items():
                if uid != self.user_id:
                    handler.send(PacketType.REMOTE_GRANT, {
                        "room_code": room_code,
                        "granted": False,
                        "target_user_id": None,
                        "target_username": None,
                        "sharer_user_id": controller_cleared_info.sharer_user_id,
                    })

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

        # Validate msg_type
        if msg_type not in ("text", "image", "file"):
            self.send(PacketType.ERROR, {"code": 400, "message": "Invalid message type"})
            return

        # File/image size validation (base64 content ~= 4/3 * raw size)
        _MAX_CONTENT_LEN = 14 * 1024 * 1024  # ~10 MB after base64 decoding
        if msg_type in ("image", "file") and len(content) > _MAX_CONTENT_LEN:
            self.send(PacketType.ERROR, {"code": 413, "message": "File too large (max 10 MB)"})
            return

        is_dm = room_code.startswith("DM-")

        if is_dm:
            # DM rooms are server-agnostic. The sender may not be in this
            # server's _rooms[room_code]["clients"] for either of two
            # reasons:
            #   (a) the room does not exist on this server at all — the
            #       sender only received earlier DMs via the Redis push
            #       fallback (cross-server case);
            #   (b) the room DOES exist locally because the OTHER
            #       participant joined here first, but the sender
            #       themselves was delivered earlier DMs via the same-
            #       server local push path in _handle_chat_message and was
            #       never added to clients.
            # In both cases, the broadcast loop below would skip the
            # sender — the sender would never see their own message echoed
            # back even though the recipient receives it normally. The
            # trigger we need is "sender not in local clients", not "room
            # not found". join_room is idempotent on the (room, clients)
            # map; we only invoke it when the sender is genuinely absent
            # so we don't accumulate redundant room_participants rows.
            clients_now = self._server.room_manager.get_room_clients(room_code)
            if self.user_id not in clients_now:
                state, lazy_error = self._server.room_manager.join_room(
                    room_code, self.user_id, self.username, self,
                )
                if lazy_error or state is None:
                    self.send(PacketType.ERROR, {
                        "code": 500,
                        "message": lazy_error or "Failed to open DM room",
                    })
                    return
                self._current_rooms.add(room_code)

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
        # Pass through file metadata
        if msg_type in ("image", "file"):
            msg_data["filename"] = packet.payload.get("filename", "")
            msg_data["filesize"] = packet.payload.get("filesize", 0)

        clients = self._server.room_manager.get_room_clients(room_code)
        for uid, handler in clients.items():
            handler.send(PacketType.CHAT_MESSAGE, msg_data)

        # DM push: if this is a DM room, also push to the recipient even if they
        # have not joined the room locally. DM rooms are server-agnostic, so a
        # recipient connected to a different chat server is reached via Redis
        # pub/sub.
        if is_dm:
            recipient_username = self._extract_dm_recipient(room_code)
            if recipient_username:
                already_delivered = any(
                    h.username == recipient_username for h in clients.values()
                )
                if not already_delivered:
                    local = self._server.get_client_by_username(recipient_username)
                    if local is not None:
                        local.send(PacketType.CHAT_MESSAGE, msg_data)
                    else:
                        self._server.publish_dm_message(recipient_username, msg_data)

    def _extract_dm_recipient(self, room_code: str) -> str | None:
        """Given a DM room code, return the other participant's username.

        The room code format is 'DM-{sorted_name_1}-{sorted_name_2}'. We
        anchor on this user's known username so usernames containing a hyphen
        still parse correctly.
        """
        inner = room_code[3:]
        prefix = self.username + "-"
        suffix = "-" + self.username
        if inner.startswith(prefix):
            return inner[len(prefix):]
        if inner.endswith(suffix):
            return inner[:-len(suffix)]
        return None

    # ------------------------------------------------------------------
    # Screen sharing & remote control
    # ------------------------------------------------------------------

    def _resolve_screen_room(self, packet: Packet) -> tuple[str | None, object | None]:
        """Look up the screen-relay state for the room named in the packet.

        Returns (room_code, screen_state) or (None, None) after sending an
        ERROR packet back to the client. The caller may bail out on (None, _).
        """
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code:
            self.send(PacketType.ERROR, {"code": 400, "message": "Room code required"})
            return None, None
        if room_code not in self._current_rooms:
            self.send(PacketType.ERROR, {"code": 403, "message": "Not in this room"})
            return None, None
        screen = self._server.room_manager.get_screen_state(room_code)
        if screen is None:
            self.send(PacketType.ERROR, {"code": 404, "message": "Room not found"})
            return None, None
        return room_code, screen

    def _broadcast_to_room(self, room_code: str, packet_type: PacketType, payload: dict,
                          include_self: bool = True) -> None:
        clients = self._server.room_manager.get_room_clients(room_code)
        for uid, handler in clients.items():
            if not include_self and uid == self.user_id:
                continue
            handler.send(packet_type, payload)

    def _handle_screen_start(self, packet: Packet):
        room_code, screen = self._resolve_screen_room(packet)
        if room_code is None:
            return
        ok, error = screen.start_share(self.user_id, self.username)
        if not ok:
            self.send(PacketType.ERROR, {"code": 409, "message": error or "Cannot start share"})
            return
        self._broadcast_to_room(room_code, PacketType.SCREEN_START, {
            "room_code": room_code,
            "sharer_user_id": self.user_id,
            "sharer_username": self.username,
        })

    def _handle_screen_stop(self, packet: Packet):
        room_code, screen = self._resolve_screen_room(packet)
        if room_code is None:
            return
        if not screen.stop_share(self.user_id):
            # Not the sharer or no active share: silently ignore — the client
            # is already in the right state from its own UI's perspective.
            return
        self._broadcast_to_room(room_code, PacketType.SCREEN_STOP, {
            "room_code": room_code,
            "sharer_user_id": self.user_id,
        })

    def _handle_screen_frame(self, packet: Packet):
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code or room_code not in self._current_rooms:
            return
        screen = self._server.room_manager.get_screen_state(room_code)
        if screen is None or screen.sharer_user_id() != self.user_id:
            # Frames from a non-sharer are dropped without an error: a stale
            # frame in flight after a stop is not a protocol violation.
            return
        relay_payload = {
            "room_code": room_code,
            "sharer_user_id": self.user_id,
            "jpeg_b64": packet.payload.get("jpeg_b64", ""),
            "width": packet.payload.get("width", 0),
            "height": packet.payload.get("height", 0),
            "seq": packet.payload.get("seq", 0),
        }
        self._broadcast_to_room(room_code, PacketType.SCREEN_RELAY, relay_payload,
                                include_self=False)

    def _handle_remote_request(self, packet: Packet):
        room_code, screen = self._resolve_screen_room(packet)
        if room_code is None:
            return
        info = screen.get_state()
        if info is None:
            self.send(PacketType.ERROR, {"code": 409, "message": "No active screen share"})
            return
        if info.sharer_user_id == self.user_id:
            self.send(PacketType.ERROR, {"code": 400, "message": "You are the sharer"})
            return
        sharer = self._server.room_manager.get_room_clients(room_code).get(info.sharer_user_id)
        if sharer is None:
            self.send(PacketType.ERROR, {"code": 410, "message": "Sharer is no longer connected"})
            return
        sharer.send(PacketType.REMOTE_REQUEST, {
            "room_code": room_code,
            "requester_user_id": self.user_id,
            "requester_username": self.username,
        })

    def _handle_remote_grant(self, packet: Packet):
        room_code, screen = self._resolve_screen_room(packet)
        if room_code is None:
            return
        target_user_id = packet.payload.get("target_user_id")
        granted = bool(packet.payload.get("granted", False))

        info = screen.get_state()
        if info is None or info.sharer_user_id != self.user_id:
            self.send(PacketType.ERROR, {
                "code": 403, "message": "Only the active sharer can grant remote control",
            })
            return

        if granted:
            target_handler = self._server.room_manager.get_room_clients(room_code).get(target_user_id)
            if target_handler is None:
                self.send(PacketType.ERROR, {
                    "code": 410, "message": "Target user is no longer in this room",
                })
                return
            ok, error = screen.set_controller(self.user_id, target_user_id, target_handler.username)
            if not ok:
                self.send(PacketType.ERROR, {"code": 500, "message": error or "Failed to grant"})
                return
        else:
            # Either denying a request or revoking a previously granted controller.
            # set_controller(None) handles both — it clears the slot.
            ok, error = screen.set_controller(self.user_id, None, None)
            if not ok:
                self.send(PacketType.ERROR, {"code": 500, "message": error or "Failed to update"})
                return

        # Tell every room participant about the new control state, so viewers
        # can update their UI (the controller sees their granted indicator;
        # others see "X has remote control" or that the slot is free).
        self._broadcast_to_room(room_code, PacketType.REMOTE_GRANT, {
            "room_code": room_code,
            "granted": granted,
            "target_user_id": target_user_id if granted else None,
            "target_username": (
                self._server.room_manager.get_room_clients(room_code)
                .get(target_user_id).username if granted and target_user_id is not None
                and self._server.room_manager.get_room_clients(room_code).get(target_user_id)
                else None
            ),
            "sharer_user_id": self.user_id,
        })

    def _handle_remote_event(self, packet: Packet):
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code or room_code not in self._current_rooms:
            return
        screen = self._server.room_manager.get_screen_state(room_code)
        if screen is None:
            return
        info = screen.get_state()
        if info is None:
            return
        if info.controller_user_id != self.user_id:
            # Silently drop — a stale event after a revoke is not an error.
            return
        sharer = self._server.room_manager.get_room_clients(room_code).get(info.sharer_user_id)
        if sharer is None:
            return
        # Forward verbatim — the host's executor reads what it needs.
        forward = dict(packet.payload)
        forward["controller_user_id"] = self.user_id
        sharer.send(PacketType.REMOTE_EVENT, forward)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _handle_audio_chunk(self, packet: Packet):
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code or room_code not in self._current_rooms:
            return
        mixer = self._server.room_manager.get_audio_mixer(room_code)
        if mixer is None:
            return
        # Lazily register this user as an audio participant
        mixer.add_participant(self.user_id, self.username)
        pcm_b64 = packet.payload.get("pcm_b64", "")
        seq = packet.payload.get("seq", 0)
        if pcm_b64:
            mixer.feed_audio(self.user_id, pcm_b64, seq)

    # ------------------------------------------------------------------
    # Whiteboard
    # ------------------------------------------------------------------

    def _handle_draw_event(self, packet: Packet):
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code or room_code not in self._current_rooms:
            return
        wb = self._server.room_manager.get_whiteboard_state(room_code)
        if wb is None:
            return
        
        event_type = packet.payload.get("event_type")
        payload = packet.payload.get("payload")
        client_event_id = packet.payload.get("client_event_id")

        if not event_type or not isinstance(payload, dict):
            return

        seq = wb.add_event(self.user_id, event_type, payload, client_event_id)

        # Send ACK to the sender
        self.send(PacketType.DRAW_ACK, {
            "room_code": room_code,
            "client_event_id": client_event_id,
            "seq_num": seq,
        })

        # Broadcast to all clients in the room
        self._broadcast_to_room(room_code, PacketType.DRAW_BROADCAST, {
            "room_code": room_code,
            "seq_num": seq,
            "user_id": self.user_id,
            "username": self.username,
            "event_type": event_type,
            "payload": payload,
            "client_event_id": client_event_id,
        })

    def _handle_export_request(self, packet: Packet):
        room_code = packet.payload.get("room_code", "").strip()
        if not room_code or room_code not in self._current_rooms:
            return
        wb = self._server.room_manager.get_whiteboard_state(room_code)
        if wb is None:
            return

        try:
            png_bytes = wb.render_png()
            png_b64 = base64.b64encode(png_bytes).decode("ascii")
            self.send(PacketType.FILE_TRANSFER, {
                "room_code": room_code,
                "file_type": "whiteboard_export",
                "file_data": png_b64,
                "file_name": f"whiteboard_{room_code}.png",
            })
        except Exception:
            logger.exception("Failed to render and export whiteboard to PNG")
            self.send(PacketType.ERROR, {"code": 500, "message": "Failed to render whiteboard"})

    # ------------------------------------------------------------------
    # Room invites
    # ------------------------------------------------------------------

    def _handle_room_invite(self, packet: Packet):
        """Forward a room invite to the target user."""
        target_username = packet.payload.get("target_username", "").strip()
        room_code = packet.payload.get("room_code", "").strip()
        if not target_username or not room_code:
            self.send(PacketType.ERROR, {"code": 400, "message": "Invalid invite"})
            return

        # Look up locally first
        target = self._server.get_client_by_username(target_username)
        if target is not None:
            target.send(PacketType.ROOM_INVITE_NOTIFY, {
                "room_code": room_code,
                "from_user_id": self.user_id,
                "from_username": self.username,
            })
        else:
            # Try cross-server via Redis
            try:
                import json
                self._server._redis.publish("room_invites", json.dumps({
                    "target_username": target_username,
                    "room_code": room_code,
                    "from_user_id": self.user_id,
                    "from_username": self.username,
                    "originating_server_id": self._server.config.server_id,
                }))
            except Exception:
                logger.debug("Failed to publish room invite")

        self.send(PacketType.ROOM_UPDATE, {
            "room_code": room_code,
            "event": "invite_sent",
            "username": target_username,
        })

    # ------------------------------------------------------------------
    # E2E Public Key Exchange
    # ------------------------------------------------------------------

    def _handle_public_key_announce(self, packet: Packet):
        """Store the client's E2E public key for key exchange."""
        self._e2e_public_key = packet.payload.get("public_key", "")
        logger.debug("Stored E2E public key for user %s", self.username)

    def _handle_public_key_request(self, packet: Packet):
        """Look up a user's E2E public key and respond."""
        target_username = packet.payload.get("target_username", "").strip()
        if not target_username:
            self.send(PacketType.ERROR, {"code": 400, "message": "Username required"})
            return

        target = self._server.get_client_by_username(target_username)
        if target is None or not target._e2e_public_key:
            self.send(PacketType.PUBLIC_KEY_RESPONSE, {
                "username": target_username,
                "public_key": "",
                "found": False,
            })
            return

        self.send(PacketType.PUBLIC_KEY_RESPONSE, {
            "username": target_username,
            "public_key": target._e2e_public_key,
            "found": True,
        })

    # ------------------------------------------------------------------
    # Friends
    # ------------------------------------------------------------------

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
            # Phase 2: if this user owned a screen share or held the remote
            # control grant in any of their rooms, stop/revoke and notify the
            # remaining members. Done BEFORE remove_client_from_all_rooms so
            # the recipient list is still intact.
            for room_code in list(self._current_rooms):
                screen = self._server.room_manager.get_screen_state(room_code)
                if screen is None:
                    continue
                if screen.stop_if_sharer(self.user_id):
                    clients = self._server.room_manager.get_room_clients(room_code)
                    for uid, handler in clients.items():
                        if uid != self.user_id:
                            handler.send(PacketType.SCREEN_STOP, {
                                "room_code": room_code,
                                "sharer_user_id": self.user_id,
                            })
                elif screen.clear_controller_if(self.user_id):
                    info = screen.get_state()
                    clients = self._server.room_manager.get_room_clients(room_code)
                    for uid, handler in clients.items():
                        if uid != self.user_id:
                            handler.send(PacketType.REMOTE_GRANT, {
                                "room_code": room_code,
                                "granted": False,
                                "target_user_id": None,
                                "target_username": None,
                                "sharer_user_id": info.sharer_user_id if info else None,
                            })

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
