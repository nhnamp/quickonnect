import logging
from datetime import datetime

from shared.models import Message
from server.services.db import get_connection

logger = logging.getLogger(__name__)

MESSAGE_HISTORY_LIMIT = 100


class MessageService:
    def store_message(self, room_id: int, sender_id: int, content: str, msg_type: str = "text") -> Message | None:
        """Store a message in the database. Returns the Message with its id and timestamp."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO messages (room_id, sender_id, content, msg_type) "
                        "VALUES (%s, %s, %s, %s) RETURNING id, sent_at",
                        (room_id, sender_id, content, msg_type),
                    )
                    row = cur.fetchone()
                    conn.commit()
        except Exception:
            logger.exception("Failed to store message")
            return None

        cur2 = None
        sender_name = ""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur2:
                    cur2.execute("SELECT username FROM users WHERE id = %s", (sender_id,))
                    name_row = cur2.fetchone()
                    sender_name = name_row[0] if name_row else ""
        except Exception:
            pass

        return Message(
            id=row[0],
            room_id=room_id,
            sender_id=sender_id,
            sender_name=sender_name,
            content=content,
            msg_type=msg_type,
            sent_at=row[1],
        )

    def get_history(self, room_id: int, limit: int = MESSAGE_HISTORY_LIMIT) -> list[Message]:
        """Retrieve the most recent messages for a room, ordered oldest first."""
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT m.id, m.room_id, m.sender_id, u.username, m.content, m.msg_type, m.sent_at "
                        "FROM messages m JOIN users u ON m.sender_id = u.id "
                        "WHERE m.room_id = %s ORDER BY m.sent_at DESC LIMIT %s",
                        (room_id, limit),
                    )
                    rows = cur.fetchall()
        except Exception:
            logger.exception("Failed to retrieve message history")
            return []

        messages = [
            Message(
                id=r[0], room_id=r[1], sender_id=r[2], sender_name=r[3],
                content=r[4], msg_type=r[5], sent_at=r[6],
            )
            for r in rows
        ]
        messages.reverse()
        return messages
