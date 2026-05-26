import json
import struct
import socket
import logging
from dataclasses import dataclass

from shared.constants import (
    MAGIC,
    PROTOCOL_VERSION,
    HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    PacketType,
    PLAINTEXT_PACKET_TYPES,
)
from shared.crypto import aes_encrypt, aes_decrypt

logger = logging.getLogger(__name__)

HEADER_FORMAT = "!4sHHI12s16s"


@dataclass
class Packet:
    packet_type: PacketType
    payload: dict


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from socket. Raises ConnectionError on failure."""
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed while reading")
        data.extend(chunk)
    return bytes(data)


def encode_packet(
    packet_type: PacketType,
    payload: dict,
    aes_key: bytes | None = None,
) -> bytes:
    """Encode a packet into bytes ready to send over TCP."""
    payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    if aes_key is not None and packet_type not in PLAINTEXT_PACKET_TYPES:
        aad = struct.pack("!4sHHI", MAGIC, PROTOCOL_VERSION, packet_type, len(payload_bytes))
        nonce, ciphertext, tag = aes_encrypt(aes_key, payload_bytes, aad)
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC,
            PROTOCOL_VERSION,
            packet_type,
            len(ciphertext),
            nonce,
            tag,
        )
        return header + ciphertext
    else:
        nonce = b"\x00" * 12
        tag = b"\x00" * 16
        header = struct.pack(
            HEADER_FORMAT,
            MAGIC,
            PROTOCOL_VERSION,
            packet_type,
            len(payload_bytes),
            nonce,
            tag,
        )
        return header + payload_bytes


def decode_header(header_bytes: bytes) -> tuple[PacketType, int, bytes, bytes]:
    """Decode a 40-byte header. Returns (packet_type, payload_len, nonce, auth_tag)."""
    magic, version, ptype, payload_len, nonce, tag = struct.unpack(HEADER_FORMAT, header_bytes)

    if magic != MAGIC:
        raise ValueError(f"Invalid magic: {magic!r}")
    if version != PROTOCOL_VERSION:
        raise ValueError(f"Unsupported protocol version: {version}")
    if payload_len > MAX_PAYLOAD_SIZE:
        raise ValueError(f"Payload too large: {payload_len}")

    return PacketType(ptype), payload_len, nonce, tag


def read_packet(sock: socket.socket, aes_key: bytes | None = None) -> Packet:
    """Read one complete packet from socket."""
    header_bytes = _recv_exact(sock, HEADER_SIZE)
    packet_type, payload_len, nonce, tag = decode_header(header_bytes)

    raw_payload = _recv_exact(sock, payload_len) if payload_len > 0 else b""

    is_encrypted = nonce != b"\x00" * 12
    if is_encrypted:
        if aes_key is None:
            raise ValueError("Received encrypted packet but no AES key available")
        aad = struct.pack("!4sHHI", MAGIC, PROTOCOL_VERSION, packet_type, payload_len)
        raw_payload = aes_decrypt(aes_key, nonce, raw_payload, tag, aad)

    payload = json.loads(raw_payload.decode("utf-8")) if raw_payload else {}
    return Packet(packet_type=packet_type, payload=payload)


def send_packet(
    sock: socket.socket,
    packet_type: PacketType,
    payload: dict,
    aes_key: bytes | None = None,
) -> None:
    """Encode and send a packet over TCP."""
    data = encode_packet(packet_type, payload, aes_key)
    sock.sendall(data)
