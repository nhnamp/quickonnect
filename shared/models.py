from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class User:
    id: int
    username: str
    created_at: datetime | None = None


@dataclass
class Room:
    id: int
    room_code: str
    created_by: int
    created_at: datetime | None = None


@dataclass
class Message:
    id: int
    room_id: int
    sender_id: int
    sender_name: str
    content: str
    msg_type: str = "text"
    sent_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "content": self.content,
            "msg_type": self.msg_type,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
        }


@dataclass
class Friend:
    user_id: int
    username: str
    status: str  # "pending" or "accepted"
    online: bool = False

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "status": self.status,
            "online": self.online,
        }


@dataclass
class Participant:
    user_id: int
    username: str

    def to_dict(self) -> dict:
        return {"user_id": self.user_id, "username": self.username}


@dataclass
class RoomState:
    room_id: int
    room_code: str
    participants: list[Participant] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "room_id": self.room_id,
            "room_code": self.room_code,
            "participants": [p.to_dict() for p in self.participants],
        }
