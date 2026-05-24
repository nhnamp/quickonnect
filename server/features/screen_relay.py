"""Per-room screen share + remote control state.

The server does not decode JPEG frames; it only relays them. This module owns
the small bit of state needed to enforce the "one sharer per room" and "one
controller per share" rules and to validate that an incoming SCREEN_FRAME
came from the current sharer and an incoming REMOTE_EVENT came from the
current controller.

All public methods are safe to call from multiple ClientHandler threads.
"""

import threading
from dataclasses import dataclass


@dataclass
class ShareInfo:
    sharer_user_id: int
    sharer_username: str
    controller_user_id: int | None = None
    controller_username: str | None = None


class ScreenRelayState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._share: ShareInfo | None = None

    def get_state(self) -> ShareInfo | None:
        with self._lock:
            return ShareInfo(
                sharer_user_id=self._share.sharer_user_id,
                sharer_username=self._share.sharer_username,
                controller_user_id=self._share.controller_user_id,
                controller_username=self._share.controller_username,
            ) if self._share else None

    def is_sharing(self) -> bool:
        with self._lock:
            return self._share is not None

    def sharer_user_id(self) -> int | None:
        with self._lock:
            return self._share.sharer_user_id if self._share else None

    def controller_user_id(self) -> int | None:
        with self._lock:
            return self._share.controller_user_id if self._share else None

    def start_share(self, user_id: int, username: str) -> tuple[bool, str | None]:
        """Try to start a share. Returns (ok, error_message)."""
        with self._lock:
            if self._share is not None:
                if self._share.sharer_user_id == user_id:
                    return True, None
                return False, "Another participant is already sharing"
            self._share = ShareInfo(sharer_user_id=user_id, sharer_username=username)
            return True, None

    def stop_share(self, user_id: int) -> bool:
        """Stop the share if the user is the current sharer. Returns True if cleared."""
        with self._lock:
            if self._share is None:
                return False
            if self._share.sharer_user_id != user_id:
                return False
            self._share = None
            return True

    def stop_if_sharer(self, user_id: int) -> bool:
        """Used by disconnect cleanup. Returns True if the share was cleared."""
        return self.stop_share(user_id)

    def set_controller(
        self, sharer_user_id: int, controller_user_id: int | None, controller_username: str | None,
    ) -> tuple[bool, str | None]:
        """Grant or revoke remote control. Only the current sharer may change it.

        Pass controller_user_id=None to clear (revoke).
        """
        with self._lock:
            if self._share is None:
                return False, "No active screen share"
            if self._share.sharer_user_id != sharer_user_id:
                return False, "Only the sharer can change remote control"
            self._share.controller_user_id = controller_user_id
            self._share.controller_username = controller_username
            return True, None

    def clear_controller_if(self, user_id: int) -> bool:
        """Clear the controller if the given user is currently the controller.

        Used by disconnect cleanup so a controller who drops off does not keep
        an orphaned grant. Returns True if a controller was cleared.
        """
        with self._lock:
            if self._share is None:
                return False
            if self._share.controller_user_id != user_id:
                return False
            self._share.controller_user_id = None
            self._share.controller_username = None
            return True
