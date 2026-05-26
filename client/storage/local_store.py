import json
import os
import logging

logger = logging.getLogger(__name__)


class LocalStore:
    """Persists JWT token and client settings to disk."""

    def __init__(self, data_dir: str):
        self._data_dir = data_dir
        self._store_path = os.path.join(data_dir, "session.json")
        os.makedirs(data_dir, exist_ok=True)

    def save_session(self, token: str, user_id: int, username: str) -> None:
        data = {"token": token, "user_id": user_id, "username": username}
        try:
            with open(self._store_path, "w") as f:
                json.dump(data, f)
        except Exception:
            logger.warning("Failed to save session")

    def load_session(self) -> dict | None:
        """Returns {"token": str, "user_id": int, "username": str} or None."""
        if not os.path.exists(self._store_path):
            return None
        try:
            with open(self._store_path, "r") as f:
                data = json.load(f)
            if "token" in data:
                return data
        except Exception:
            logger.debug("Failed to load session")
        return None

    def clear_session(self) -> None:
        try:
            if os.path.exists(self._store_path):
                os.remove(self._store_path)
        except Exception:
            logger.debug("Failed to clear session")
