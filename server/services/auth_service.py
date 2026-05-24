import logging

from shared.crypto import hash_password, verify_password, create_jwt, decode_jwt
from shared.models import User
from server.services.db import get_connection

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, jwt_secret: str):
        self._jwt_secret = jwt_secret

    def register(self, username: str, password: str) -> tuple[User | None, str | None, str | None]:
        """
        Register a new user. Returns (user, jwt_token, error_message).
        On failure, user and token are None and error_message is set.
        """
        if not username or len(username) < 3 or len(username) > 50:
            return None, None, "Username must be 3-50 characters"
        if not password or len(password) < 6:
            return None, None, "Password must be at least 6 characters"

        pw_hash = hash_password(password)

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id, created_at",
                        (username, pw_hash),
                    )
                    row = cur.fetchone()
                    conn.commit()
        except Exception as e:
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                return None, None, "Username already taken"
            logger.exception("Registration failed")
            return None, None, "Registration failed"

        user = User(id=row[0], username=username, created_at=row[1])
        token = create_jwt(user.id, user.username, self._jwt_secret)

        self._store_session(user.id, token)
        logger.info("User registered: %s (id=%d)", username, user.id)
        return user, token, None

    def login(self, username: str, password: str) -> tuple[User | None, str | None, str | None]:
        """
        Authenticate with username and password.
        Returns (user, jwt_token, error_message).
        """
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, username, password_hash, created_at FROM users WHERE username = %s",
                        (username,),
                    )
                    row = cur.fetchone()
        except Exception:
            logger.exception("Login query failed")
            return None, None, "Login failed"

        if row is None:
            return None, None, "Invalid username or password"

        user_id, uname, pw_hash, created_at = row
        if not verify_password(password, pw_hash):
            return None, None, "Invalid username or password"

        user = User(id=user_id, username=uname, created_at=created_at)
        token = create_jwt(user.id, user.username, self._jwt_secret)

        self._store_session(user.id, token)
        logger.info("User logged in: %s (id=%d)", username, user.id)
        return user, token, None

    def validate_token(self, token: str) -> User | None:
        """Validate a JWT token and return the User if valid."""
        payload = decode_jwt(token, self._jwt_secret)
        if payload is None:
            return None

        user_id = payload.get("user_id")
        username = payload.get("username")
        if user_id is None or username is None:
            return None

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, username FROM users WHERE id = %s", (user_id,))
                    row = cur.fetchone()
        except Exception:
            logger.exception("Token validation query failed")
            return None

        if row is None:
            return None

        return User(id=row[0], username=row[1])

    def _store_session(self, user_id: int, token: str) -> None:
        """Store a session token in the database for tracking."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sessions (user_id, token, expires_at) "
                        "VALUES (%s, %s, NOW() + INTERVAL '24 hours')",
                        (user_id, token),
                    )
                    conn.commit()
        except Exception:
            logger.exception("Failed to store session")
