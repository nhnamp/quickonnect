"""Client-side whiteboard connection engine.

Handles formatting and sending drawing events and export requests over TCP.
"""

import logging
from shared.constants import PacketType

logger = logging.getLogger(__name__)


class WhiteboardEngine:
    """Client-side coordinator for the collaborative whiteboard network layer.

    Generates unique client-side event IDs to match incoming acknowledgments,
    and formats drawing and export packets.
    """

    def __init__(self, connection_manager, username: str) -> None:
        self._conn = connection_manager
        self._username = username
        self._local_counter = 0

    def generate_event_id(self) -> str:
        """Generate a unique client-side ID for matching DRAW_ACKs."""
        self._local_counter += 1
        return f"{self._username}-{self._local_counter}"

    def send_draw_event(self, room_code: str, event_type: str, payload: dict) -> str:
        """Construct and send a DRAW_EVENT packet to the server.

        Returns the generated client_event_id.
        """
        client_event_id = self.generate_event_id()
        try:
            self._conn.send(
                PacketType.DRAW_EVENT,
                {
                    "room_code": room_code,
                    "event_type": event_type,
                    "payload": payload,
                    "client_event_id": client_event_id,
                },
            )
        except Exception:
            logger.exception("Failed to send DRAW_EVENT to server")
        return client_event_id

    def send_export_request(self, room_code: str) -> None:
        """Send an EXPORT_REQUEST packet to the server."""
        try:
            self._conn.send(
                PacketType.EXPORT_REQUEST,
                {
                    "room_code": room_code,
                },
            )
        except Exception:
            logger.exception("Failed to send EXPORT_REQUEST to server")
