#!/usr/bin/env python3
"""Protocol-level E2E smoke test against a running local demo stack."""

from __future__ import annotations

import base64
import json
import os
import queue
import random
import string
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.network.connection import ConnectionManager
from client.network.lb_client import request_server
from shared.attachments import validate_attachment_content
from shared.constants import PacketType


def main() -> int:
    lb_host = os.environ.get("LB_HOST", "127.0.0.1")
    lb_port = int(os.environ.get("LB_PORT", "9000"))
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    room_code = f"TST-{suffix[:4].upper()}"

    host, port = request_server(lb_host, lb_port, room_code)
    alice = SmokeClient("alice_" + suffix, "password123", host, port)
    bob = SmokeClient("bob_" + suffix, "password123", host, port)

    try:
        alice.connect_and_register()
        bob.connect_and_register()
        alice.join_room(room_code)
        bob.join_room(room_code)

        alice.send_chat(room_code, "hello from alice")
        bob.expect_chat(room_code, "hello from alice", timeout=5)

        attachment_content = make_attachment()
        alice.send_message(room_code, attachment_content, "file")
        bob.expect_message_type(room_code, "file", timeout=5)

        alice.send_draw(room_code)
        bob.expect_packet(PacketType.DRAW_BROADCAST, lambda p: p.get("room_code") == room_code, timeout=5)

        alice.send_audio(room_code)
        bob.expect_packet(PacketType.MIXED_AUDIO, lambda p: p.get("room_code") == room_code, timeout=5)

        print("Protocol E2E smoke test passed.")
        return 0
    finally:
        alice.close()
        bob.close()


class SmokeClient:
    def __init__(self, username: str, password: str, host: str, port: int):
        self.username = username
        self.password = password
        self.host = host
        self.port = port
        self.conn = ConnectionManager()
        self.user_id = 0

    def connect_and_register(self) -> None:
        self.conn.connect(self.host, self.port)
        self.conn.send(PacketType.REGISTER_REQUEST, {
            "username": self.username,
            "password": self.password,
        })
        packet = self.expect_packet(PacketType.REGISTER_RESPONSE, timeout=10)
        if not packet.get("success"):
            raise RuntimeError(f"Register failed for {self.username}: {packet}")
        self.user_id = int(packet["user_id"])

    def join_room(self, room_code: str) -> None:
        self.conn.send(PacketType.JOIN_ROOM, {"room_code": room_code})
        self.expect_packet(PacketType.ROOM_STATE, lambda p: p.get("room_code") == room_code, timeout=10)
        self.expect_packet(PacketType.MESSAGE_HISTORY, lambda p: p.get("room_code") == room_code, timeout=10)
        self.expect_packet(PacketType.WHITEBOARD_SYNC, lambda p: p.get("room_code") == room_code, timeout=10)

    def send_chat(self, room_code: str, text: str) -> None:
        self.send_message(room_code, text, "text")

    def send_message(self, room_code: str, content: str, msg_type: str) -> None:
        self.conn.send(PacketType.CHAT_MESSAGE, {
            "room_code": room_code,
            "content": content,
            "msg_type": msg_type,
        })

    def send_draw(self, room_code: str) -> None:
        self.conn.send(PacketType.DRAW_EVENT, {
            "room_code": room_code,
            "client_seq_num": 1,
            "event_type": "STROKE",
            "payload": {
                "points": [{"x": 5, "y": 5}, {"x": 30, "y": 35}],
                "color": "#112233",
                "width": 4,
            },
        })

    def send_audio(self, room_code: str) -> None:
        pcm = b"\x00\x10" * 320
        self.conn.send(PacketType.AUDIO_CHUNK, {
            "room_code": room_code,
            "seq": 1,
            "timestamp_ms": int(time.time() * 1000),
            "sample_rate": 16000,
            "channels": 1,
            "sample_width": 2,
            "pcm_b64": base64.b64encode(pcm).decode("ascii"),
        })

    def expect_chat(self, room_code: str, content: str, timeout: float) -> dict:
        return self.expect_packet(
            PacketType.CHAT_MESSAGE,
            lambda p: p.get("room_code") == room_code and p.get("content") == content,
            timeout=timeout,
        )

    def expect_message_type(self, room_code: str, msg_type: str, timeout: float) -> dict:
        return self.expect_packet(
            PacketType.CHAT_MESSAGE,
            lambda p: p.get("room_code") == room_code and p.get("msg_type") == msg_type,
            timeout=timeout,
        )

    def expect_packet(self, packet_type: PacketType, predicate=None, timeout: float = 5) -> dict:
        deadline = time.monotonic() + timeout
        skipped = []
        while time.monotonic() < deadline:
            try:
                packet = self.conn.packet_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if packet.packet_type == PacketType.ERROR:
                raise RuntimeError(f"Server returned error to {self.username}: {packet.payload}")
            if packet.packet_type == packet_type and (predicate is None or predicate(packet.payload)):
                return packet.payload
            skipped.append((packet.packet_type, packet.payload))
        raise TimeoutError(f"{self.username} timed out waiting for {packet_type}; skipped={skipped[-5:]}")

    def close(self) -> None:
        self.conn.disconnect()


def make_attachment() -> str:
    data = b"quickonnect smoke attachment"
    payload = {
        "filename": "smoke.txt",
        "mime_type": "text/plain",
        "size_bytes": len(data),
        "data_b64": base64.b64encode(data).decode("ascii"),
    }
    content = json.dumps(payload, separators=(",", ":"))
    valid, error = validate_attachment_content(content, "file")
    if not valid:
        raise RuntimeError(error or "invalid attachment")
    return content


if __name__ == "__main__":
    raise SystemExit(main())
