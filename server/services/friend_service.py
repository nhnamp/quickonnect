import logging

from shared.models import Friend
from server.services.db import get_connection

logger = logging.getLogger(__name__)


class FriendService:
    def send_request(self, from_user_id: int, target_username: str) -> tuple[bool, str]:
        """Send a friend request. Returns (success, error_message)."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM users WHERE username = %s", (target_username,))
                    row = cur.fetchone()
                    if row is None:
                        return False, "User not found"

                    target_id = row[0]
                    if target_id == from_user_id:
                        return False, "Cannot add yourself"

                    cur.execute(
                        "SELECT status FROM friendships WHERE user_id = %s AND friend_id = %s",
                        (from_user_id, target_id),
                    )
                    existing = cur.fetchone()
                    if existing is not None:
                        return False, f"Friend request already exists (status: {existing[0]})"

                    cur.execute(
                        "INSERT INTO friendships (user_id, friend_id, status) VALUES (%s, %s, 'pending')",
                        (from_user_id, target_id),
                    )
                    conn.commit()
        except Exception:
            logger.exception("Failed to send friend request")
            return False, "Failed to send request"

        return True, ""

    def respond_to_request(self, user_id: int, from_user_id: int, accept: bool) -> tuple[bool, str]:
        """Accept or reject a friend request. Returns (success, error_message)."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT status FROM friendships WHERE user_id = %s AND friend_id = %s",
                        (from_user_id, user_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        return False, "No pending request from this user"
                    if row[0] != "pending":
                        return False, "Request already processed"

                    if accept:
                        cur.execute(
                            "UPDATE friendships SET status = 'accepted' "
                            "WHERE user_id = %s AND friend_id = %s",
                            (from_user_id, user_id),
                        )
                        cur.execute(
                            "INSERT INTO friendships (user_id, friend_id, status) "
                            "VALUES (%s, %s, 'accepted') "
                            "ON CONFLICT (user_id, friend_id) DO UPDATE SET status = 'accepted'",
                            (user_id, from_user_id),
                        )
                    else:
                        cur.execute(
                            "DELETE FROM friendships WHERE user_id = %s AND friend_id = %s",
                            (from_user_id, user_id),
                        )
                    conn.commit()
        except Exception:
            logger.exception("Failed to respond to friend request")
            return False, "Failed to process response"

        return True, ""

    def get_friends(self, user_id: int) -> list[Friend]:
        """Get all friends and pending requests for a user."""
        friends: list[Friend] = []
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    # Accepted friends (both directions)
                    cur.execute(
                        "SELECT u.id, u.username, f.status FROM friendships f "
                        "JOIN users u ON u.id = f.friend_id "
                        "WHERE f.user_id = %s AND f.status = 'accepted'",
                        (user_id,),
                    )
                    for row in cur.fetchall():
                        friends.append(Friend(user_id=row[0], username=row[1], status=row[2]))

                    # Incoming pending requests
                    cur.execute(
                        "SELECT u.id, u.username FROM friendships f "
                        "JOIN users u ON u.id = f.user_id "
                        "WHERE f.friend_id = %s AND f.status = 'pending'",
                        (user_id,),
                    )
                    for row in cur.fetchall():
                        friends.append(Friend(user_id=row[0], username=row[1], status="incoming"))
        except Exception:
            logger.exception("Failed to get friends list")

        return friends

    def get_target_user_id(self, target_username: str) -> int | None:
        """Look up a user id by username."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT id FROM users WHERE username = %s", (target_username,))
                    row = cur.fetchone()
                    return row[0] if row else None
        except Exception:
            logger.exception("Failed to look up user")
            return None
