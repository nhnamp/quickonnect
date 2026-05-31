import logging
import threading
import string
import random

from shared.models import Room, Participant, RoomState
from server.services.db import get_connection
from server.features.screen_relay import ScreenRelayState
from server.features.audio_mixer import AudioMixerState
from server.features.stt_worker import STTManager
from server.features.subtitle import SubtitleBroadcaster
from server.features.whiteboard import WhiteboardState

logger = logging.getLogger(__name__)


def _generate_room_code() -> str:
    chars = string.ascii_uppercase + string.digits
    part1 = "".join(random.choices(chars, k=3))
    part2 = "".join(random.choices(chars, k=4))
    return f"{part1}-{part2}"


def _is_dm_room(room_code: str) -> bool:
    """DM rooms are server-agnostic and skip Redis room->server pinning."""
    return room_code.startswith("DM-")


class RoomManager:
    """
    Manages active rooms on this server. Thread-safe.
    Each room tracks its connected participants (client handlers).
    """

    def __init__(self, server_id: str, redis_client):
        self._server_id = server_id
        self._redis = redis_client
        self._lock = threading.Lock()
        # room_code -> {"room": Room, "clients": {user_id: client_handler}}
        self._rooms: dict[str, dict] = {}

    def create_room(self, user_id: int) -> Room | None:
        """Create a new room in the database and register it in Redis."""
        room_code = _generate_room_code()
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO rooms (room_code, created_by) VALUES (%s, %s) RETURNING id, created_at",
                        (room_code, user_id),
                    )
                    row = cur.fetchone()
                    conn.commit()
        except Exception:
            logger.exception("Failed to create room")
            return None

        room = Room(id=row[0], room_code=room_code, created_by=user_id, created_at=row[1])
        self._register_room_in_redis(room_code)
        return room

    def get_screen_state(self, room_code: str) -> ScreenRelayState | None:
        """Return the per-room ScreenRelayState, or None if the room is not active here."""
        with self._lock:
            room_data = self._rooms.get(room_code)
            return room_data["screen"] if room_data else None

    def get_audio_mixer(self, room_code: str) -> AudioMixerState | None:
        """Return the per-room AudioMixerState, or None if the room is not active here."""
        with self._lock:
            room_data = self._rooms.get(room_code)
            return room_data["audio"] if room_data else None

    def get_whiteboard_state(self, room_code: str) -> WhiteboardState | None:
        """Return the per-room WhiteboardState, or None if the room is not active here."""
        with self._lock:
            room_data = self._rooms.get(room_code)
            return room_data["whiteboard"] if room_data else None

    def join_room(self, room_code: str, user_id: int, username: str, client_handler) -> tuple[RoomState | None, str | None]:
        """
        Join a room. Creates it if it doesn't exist.
        Returns (room_state, error_message).
        For regular rooms, if the room is on another server the error_message
        contains redirect info. DM rooms ('DM-' prefix) are server-agnostic:
        neither the redirect check nor the Redis pin is applied to them, and
        both participants may join independently on whichever server they are
        currently connected to.
        """
        dm = _is_dm_room(room_code)

        if not dm:
            server_for_room = self._get_room_server(room_code)
            if server_for_room is not None and server_for_room != self._server_id:
                return None, f"REDIRECT:{server_for_room}"

        with self._lock:
            if room_code in self._rooms:
                room_data = self._rooms[room_code]
                room = room_data["room"]
            else:
                room = self._get_or_create_room_in_db(room_code, user_id)
                if room is None:
                    return None, "Failed to create or find room"
                self._rooms[room_code] = {
                    "room": room,
                    "clients": {},
                    "screen": ScreenRelayState(),
                    "audio": self._create_audio_state(room_code),
                    "whiteboard": WhiteboardState(room.id, room_code),
                }
                if not dm:
                    self._register_room_in_redis(room_code)
                room_data = self._rooms[room_code]

            room_data["clients"][user_id] = client_handler

        self._record_participant(room.id, user_id)

        participants = self._get_participants(room_code)
        state = RoomState(room_id=room.id, room_code=room_code, participants=participants)
        return state, None

    def leave_room(self, room_code: str, user_id: int) -> list:
        """Remove a user from a room. Returns list of remaining client handlers."""
        with self._lock:
            room_data = self._rooms.get(room_code)
            if room_data is None:
                return []

            # Remove from audio mixer
            audio: AudioMixerState | None = room_data.get("audio")
            if audio is not None:
                audio.remove_participant(user_id)

            room_data["clients"].pop(user_id, None)
            self._mark_participant_left(room_data["room"].id, user_id)

            remaining = list(room_data["clients"].values())

            if not room_data["clients"]:
                # Stop audio mixer and STT before destroying the room
                self._stop_audio_state(room_data)
                del self._rooms[room_code]
                if not _is_dm_room(room_code):
                    self._unregister_room_from_redis(room_code)

            return remaining

    def get_room_clients(self, room_code: str) -> dict[int, object]:
        """Get all connected clients in a room. Returns {user_id: client_handler}."""
        with self._lock:
            room_data = self._rooms.get(room_code)
            if room_data is None:
                return {}
            return dict(room_data["clients"])

    def get_room(self, room_code: str) -> Room | None:
        """Get the Room object for a room code."""
        with self._lock:
            room_data = self._rooms.get(room_code)
            return room_data["room"] if room_data else None

    def remove_client_from_all_rooms(self, user_id: int) -> list[str]:
        """Remove a client from all rooms. Returns list of room codes they left."""
        left_rooms = []
        with self._lock:
            for room_code in list(self._rooms.keys()):
                room_data = self._rooms[room_code]
                if user_id in room_data["clients"]:
                    # Remove from audio mixer
                    audio: AudioMixerState | None = room_data.get("audio")
                    if audio is not None:
                        audio.remove_participant(user_id)

                    room_data["clients"].pop(user_id)
                    self._mark_participant_left(room_data["room"].id, user_id)
                    left_rooms.append(room_code)
                    if not room_data["clients"]:
                        self._stop_audio_state(room_data)
                        del self._rooms[room_code]
                        if not _is_dm_room(room_code):
                            self._unregister_room_from_redis(room_code)
        return left_rooms

    def get_connection_count(self) -> int:
        """Get total number of connected clients across all rooms."""
        seen_users: set[int] = set()
        with self._lock:
            for room_data in self._rooms.values():
                seen_users.update(room_data["clients"].keys())
        return len(seen_users)

    def _get_participants(self, room_code: str) -> list[Participant]:
        with self._lock:
            room_data = self._rooms.get(room_code)
            if room_data is None:
                return []
            return [
                Participant(user_id=uid, username=handler.username)
                for uid, handler in room_data["clients"].items()
                if handler.username
            ]

    def _get_or_create_room_in_db(self, room_code: str, creator_id: int) -> Room | None:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, room_code, created_by, created_at FROM rooms WHERE room_code = %s",
                        (room_code,),
                    )
                    row = cur.fetchone()
                    if row:
                        return Room(id=row[0], room_code=row[1], created_by=row[2], created_at=row[3])

                    cur.execute(
                        "INSERT INTO rooms (room_code, created_by) VALUES (%s, %s) RETURNING id, created_at",
                        (room_code, creator_id),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    return Room(id=row[0], room_code=room_code, created_by=creator_id, created_at=row[1])
        except Exception:
            logger.exception("Failed to get or create room in DB")
            return None

    def _record_participant(self, room_id: int, user_id: int) -> None:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO room_participants (room_id, user_id) VALUES (%s, %s)",
                        (room_id, user_id),
                    )
                    conn.commit()
        except Exception:
            logger.debug("Failed to record participant (may be duplicate)")

    def _mark_participant_left(self, room_id: int, user_id: int) -> None:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE room_participants SET left_at = NOW() "
                        "WHERE room_id = %s AND user_id = %s AND left_at IS NULL",
                        (room_id, user_id),
                    )
                    conn.commit()
        except Exception:
            logger.debug("Failed to mark participant left")

    def _register_room_in_redis(self, room_code: str) -> None:
        try:
            self._redis.set(f"room:{room_code}", self._server_id)
        except Exception:
            logger.warning("Failed to register room %s in Redis", room_code)

    def _unregister_room_from_redis(self, room_code: str) -> None:
        try:
            self._redis.delete(f"room:{room_code}")
        except Exception:
            logger.warning("Failed to unregister room %s from Redis", room_code)

    def _get_room_server(self, room_code: str) -> str | None:
        try:
            val = self._redis.get(f"room:{room_code}")
            return val if val is None else val if isinstance(val, str) else val.decode("utf-8")
        except Exception:
            logger.warning("Failed to query Redis for room %s", room_code)
            return None

    def _create_audio_state(self, room_code: str) -> AudioMixerState:
        """Create the per-room audio pipeline: mixer -> STT -> subtitles."""
        get_clients = lambda: self.get_room_clients(room_code)
        subtitle = SubtitleBroadcaster(room_code, get_clients)
        stt = STTManager(room_code, subtitle.broadcast_transcript)
        mixer = AudioMixerState(
            room_code, get_clients,
            stt_feed_fn=stt.feed_audio if stt.is_enabled() else None,
        )
        # Store STT and subtitle references so we can stop them later
        mixer._stt_manager = stt
        mixer._subtitle_broadcaster = subtitle
        return mixer

    @staticmethod
    def _stop_audio_state(room_data: dict) -> None:
        """Stop all audio and whiteboard threads for a room that is being destroyed."""
        audio: AudioMixerState | None = room_data.get("audio")
        if audio is not None:
            try:
                audio.stop()
                stt = getattr(audio, "_stt_manager", None)
                if stt is not None:
                    stt.stop()
            except Exception:
                logger.exception("Error stopping audio state")

        wb = room_data.get("whiteboard")
        if wb is not None:
            try:
                wb.stop()
            except Exception:
                logger.exception("Error stopping whiteboard state")
