import json
import logging
import signal
import threading

import redis

from server.config import ServerConfig
from server.acceptor import Acceptor
from server.room_manager import RoomManager
from server.services.db import init_pool, close_pool
from server.services.auth_service import AuthService
from server.services.message_service import MessageService
from server.services.friend_service import FriendService

logger = logging.getLogger(__name__)


class ChatServer:
    def __init__(self, config: ServerConfig):
        self.config = config
        self._redis = redis.Redis(
            host=config.redis_host, port=config.redis_port, decode_responses=True,
        )
        self._pubsub = self._redis.pubsub()

        self.auth_service = AuthService(config.jwt_secret)
        self.message_service = MessageService()
        self.friend_service = FriendService()
        self.room_manager = RoomManager(config.server_id, self._redis)

        self._clients_lock = threading.Lock()
        self._clients: dict[int, object] = {}  # user_id -> ClientHandler

        self._acceptor: Acceptor | None = None
        self._running = False
        self._pubsub_thread: threading.Thread | None = None

    def start(self):
        logger.info("Starting chat server %s on %s:%d", self.config.server_id, self.config.host, self.config.port)

        init_pool(self.config.dsn)

        self._register_server()
        self._start_pubsub_listener()

        self._acceptor = Acceptor(self.config.host, self.config.port, self)
        self._running = True
        self._acceptor.start()

        logger.info("Chat server %s is ready", self.config.server_id)

    def stop(self):
        logger.info("Stopping chat server %s", self.config.server_id)
        self._running = False

        # Phase 5: notify all clients of impending shutdown
        from shared.constants import PacketType as PT
        with self._clients_lock:
            for handler in list(self._clients.values()):
                try:
                    handler.send(PT.SERVER_SHUTDOWN, {
                        "message": "Server is shutting down",
                        "reconnect_delay": 5,
                    })
                except Exception:
                    pass

        # Give clients a moment to process the shutdown notification
        import time
        time.sleep(1)

        if self._acceptor:
            self._acceptor.stop()

        with self._clients_lock:
            for handler in list(self._clients.values()):
                handler.disconnect()
            self._clients.clear()

        self._unregister_server()
        try:
            self._pubsub.unsubscribe()
            self._pubsub.close()
        except Exception:
            pass

        close_pool()
        logger.info("Chat server %s stopped", self.config.server_id)

    def register_client(self, handler) -> None:
        with self._clients_lock:
            old_handler = self._clients.get(handler.user_id)
            if old_handler and old_handler is not handler:
                logger.info("Disconnecting old session for user %s", handler.username)
                old_handler.disconnect()
            self._clients[handler.user_id] = handler

        self._redis.sadd("online_users", str(handler.user_id))
        self._redis.publish("user_status", json.dumps({
            "user_id": handler.user_id,
            "username": handler.username,
            "online": True,
            "server_id": self.config.server_id,
        }))

    def unregister_client(self, handler) -> None:
        with self._clients_lock:
            self._clients.pop(handler.user_id, None)

        self._redis.srem("online_users", str(handler.user_id))
        self._redis.publish("user_status", json.dumps({
            "user_id": handler.user_id,
            "username": handler.username,
            "online": False,
            "server_id": self.config.server_id,
        }))

    def get_online_users(self) -> set[int]:
        try:
            members = self._redis.smembers("online_users")
            return {int(m) for m in members}
        except Exception:
            return set()

    def get_connection_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    def get_client(self, user_id: int):
        with self._clients_lock:
            return self._clients.get(user_id)

    def get_client_by_username(self, username: str):
        with self._clients_lock:
            for handler in self._clients.values():
                if handler.username == username:
                    return handler
        return None

    def get_server_address(self, server_id: str) -> tuple[str, int] | None:
        try:
            data = self._redis.hget("servers", server_id)
            if data:
                info = json.loads(data)
                return info["host"], info["port"]
        except Exception:
            pass
        return None

    def publish_friend_event(self, event: dict) -> None:
        try:
            self._redis.publish("friend_events", json.dumps(event))
        except Exception:
            logger.warning("Failed to publish friend event")

    def publish_dm_message(self, recipient_username: str, msg_data: dict) -> None:
        """Publish a DM message so the recipient's server can deliver it."""
        try:
            self._redis.publish("dm_messages", json.dumps({
                "recipient_username": recipient_username,
                "message": msg_data,
                "originating_server_id": self.config.server_id,
            }))
        except Exception:
            logger.warning("Failed to publish DM message")

    # ------------------------------------------------------------------
    # Redis pub/sub
    # ------------------------------------------------------------------

    def _start_pubsub_listener(self):
        self._pubsub.subscribe("user_status", "friend_events", "dm_messages", "room_invites")
        self._pubsub_thread = threading.Thread(target=self._pubsub_loop, daemon=True)
        self._pubsub_thread.start()

    def _pubsub_loop(self):
        for message in self._pubsub.listen():
            if not self._running:
                break
            if message["type"] != "message":
                continue
            try:
                data = json.loads(message["data"])
                channel = message["channel"]
                if isinstance(channel, bytes):
                    channel = channel.decode()

                if channel == "user_status":
                    self._handle_user_status(data)
                elif channel == "friend_events":
                    self._handle_friend_event(data)
                elif channel == "dm_messages":
                    self._handle_dm_message(data)
                elif channel == "room_invites":
                    self._handle_room_invite_pubsub(data)
            except Exception:
                logger.debug("Failed to process pub/sub message")

    def _handle_user_status(self, data: dict):
        from shared.constants import PacketType

        user_id = data.get("user_id")
        online = data.get("online", False)
        username = data.get("username", "")

        with self._clients_lock:
            for uid, handler in self._clients.items():
                if uid != user_id:
                    handler.send(PacketType.FRIEND_UPDATE, {
                        "event": "status",
                        "user_id": user_id,
                        "username": username,
                        "online": online,
                    })

    def _handle_friend_event(self, data: dict):
        from shared.constants import PacketType

        event_type = data.get("type")

        if event_type == "friend_request":
            to_username = data.get("to_username")
            with self._clients_lock:
                for uid, handler in self._clients.items():
                    if handler.username == to_username:
                        handler.send(PacketType.FRIEND_UPDATE, {
                            "event": "incoming_request",
                            "from_user_id": data["from_user_id"],
                            "from_username": data["from_username"],
                        })
                        handler._send_friend_list()
                        break

        elif event_type == "friend_accepted":
            to_user_id = data.get("to_user_id")
            handler = self.get_client(to_user_id)
            if handler:
                handler._send_friend_list()

    def _handle_dm_message(self, data: dict):
        """Deliver a DM message published by another server.

        Skip messages this server originated — the local delivery path already
        handled them, and Redis pub/sub echoes back to the publisher.
        """
        from shared.constants import PacketType

        if data.get("originating_server_id") == self.config.server_id:
            return

        recipient_username = data.get("recipient_username", "")
        msg_data = data.get("message", {})
        if not recipient_username or not msg_data:
            return

        handler = self.get_client_by_username(recipient_username)
        if handler is not None:
            handler.send(PacketType.CHAT_MESSAGE, msg_data)

    # ------------------------------------------------------------------
    # Server registry in Redis
    # ------------------------------------------------------------------

    def _register_server(self):
        info = json.dumps({
            "host": self.config.host if self.config.host != "0.0.0.0" else "127.0.0.1",
            "port": self.config.port,
        })
        self._redis.hset("servers", self.config.server_id, info)

    def _unregister_server(self):
        try:
            self._redis.hdel("servers", self.config.server_id)
        except Exception:
            pass

    def _handle_room_invite_pubsub(self, data: dict):
        """Deliver a room invite published by another server."""
        from shared.constants import PacketType

        if data.get("originating_server_id") == self.config.server_id:
            return

        target_username = data.get("target_username", "")
        if not target_username:
            return

        handler = self.get_client_by_username(target_username)
        if handler is not None:
            handler.send(PacketType.ROOM_INVITE_NOTIFY, {
                "room_code": data.get("room_code", ""),
                "from_user_id": data.get("from_user_id"),
                "from_username": data.get("from_username", ""),
            })


def run_server(config: ServerConfig | None = None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if config is None:
        config = ServerConfig()

    server = ChatServer(config)

    shutdown_event = threading.Event()

    def handle_signal(signum, frame):
        logger.info("Received signal %d, shutting down...", signum)
        server.stop()
        shutdown_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    server.start()
    shutdown_event.wait()


if __name__ == "__main__":
    run_server()
