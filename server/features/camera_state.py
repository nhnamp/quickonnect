"""Per-room camera state.

The server does not decode camera JPEG frames. It only tracks which room
members have enabled their camera so stale frames from inactive users can be
dropped and joining clients can learn who is already broadcasting.
"""

import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraUser:
    user_id: int
    username: str

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
        }


class CameraState:
    """Thread-safe active-camera registry for one room."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[int, str] = {}

    def start_camera(self, user_id: int, username: str) -> bool:
        """Mark a user's camera active. Returns True if this changed state."""
        with self._lock:
            already_active = user_id in self._active
            self._active[user_id] = username
            return not already_active

    def stop_camera(self, user_id: int) -> bool:
        """Mark a user's camera inactive. Returns True if it was active."""
        with self._lock:
            return self._active.pop(user_id, None) is not None

    def is_active(self, user_id: int) -> bool:
        with self._lock:
            return user_id in self._active

    def get_active(self) -> list[CameraUser]:
        with self._lock:
            return [
                CameraUser(user_id=user_id, username=username)
                for user_id, username in sorted(self._active.items())
            ]
