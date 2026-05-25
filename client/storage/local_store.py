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

    # ------------------------------------------------------------------
    # E2E Encryption Key Storage
    # ------------------------------------------------------------------

    def save_user_keypair(self, username: str, private_pem: bytes, public_pem: bytes) -> None:
        """Save the user's long-term RSA keypair for E2E encryption."""
        keys_dir = os.path.join(self._data_dir, "keys")
        os.makedirs(keys_dir, exist_ok=True)
        try:
            with open(os.path.join(keys_dir, f"{username}_private.pem"), "wb") as f:
                f.write(private_pem)
            with open(os.path.join(keys_dir, f"{username}_public.pem"), "wb") as f:
                f.write(public_pem)
        except Exception:
            logger.warning("Failed to save user keypair")

    def load_user_keypair(self, username: str) -> tuple[bytes, bytes] | None:
        """Load the user's long-term RSA keypair. Returns (private_pem, public_pem) or None."""
        keys_dir = os.path.join(self._data_dir, "keys")
        priv_path = os.path.join(keys_dir, f"{username}_private.pem")
        pub_path = os.path.join(keys_dir, f"{username}_public.pem")
        if not os.path.exists(priv_path) or not os.path.exists(pub_path):
            return None
        try:
            with open(priv_path, "rb") as f:
                private_pem = f.read()
            with open(pub_path, "rb") as f:
                public_pem = f.read()
            return private_pem, public_pem
        except Exception:
            logger.debug("Failed to load user keypair")
            return None

    def save_peer_public_key(self, username: str, public_pem: bytes) -> None:
        """Cache a peer's public key for E2E encryption."""
        peers_dir = os.path.join(self._data_dir, "keys", "peers")
        os.makedirs(peers_dir, exist_ok=True)
        try:
            with open(os.path.join(peers_dir, f"{username}.pem"), "wb") as f:
                f.write(public_pem)
        except Exception:
            logger.warning("Failed to save peer public key")

    def load_peer_public_key(self, username: str) -> bytes | None:
        """Load a cached peer's public key. Returns PEM bytes or None."""
        path = os.path.join(self._data_dir, "keys", "peers", f"{username}.pem")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except Exception:
            logger.debug("Failed to load peer public key")
            return None

