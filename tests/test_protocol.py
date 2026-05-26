"""Tests for the binary protocol encoding/decoding."""

import struct
import unittest

from shared.constants import PacketType, MAGIC, PROTOCOL_VERSION, HEADER_SIZE
from shared.protocol import encode_packet, decode_header, HEADER_FORMAT
from shared.crypto import generate_aes_key


class TestProtocolPlaintext(unittest.TestCase):
    """Test encoding/decoding without encryption."""

    def test_encode_produces_correct_header(self):
        payload = {"hello": "world"}
        data = encode_packet(PacketType.CONNECT_REQUEST, payload, aes_key=None)

        self.assertTrue(len(data) > HEADER_SIZE)
        magic, version, ptype, plen, nonce, tag = struct.unpack(HEADER_FORMAT, data[:HEADER_SIZE])
        self.assertEqual(magic, MAGIC)
        self.assertEqual(version, PROTOCOL_VERSION)
        self.assertEqual(ptype, PacketType.CONNECT_REQUEST)
        self.assertEqual(nonce, b"\x00" * 12)
        self.assertEqual(tag, b"\x00" * 16)
        self.assertEqual(len(data) - HEADER_SIZE, plen)

    def test_decode_header_validates_magic(self):
        payload = {"test": 1}
        data = encode_packet(PacketType.CONNECT_REQUEST, payload, aes_key=None)
        corrupted = b"BAAD" + data[4:]

        with self.assertRaises(ValueError) as ctx:
            decode_header(corrupted[:HEADER_SIZE])
        self.assertIn("magic", str(ctx.exception).lower())

    def test_decode_header_validates_version(self):
        payload = {"test": 1}
        data = encode_packet(PacketType.CONNECT_REQUEST, payload, aes_key=None)
        corrupted = data[:4] + struct.pack("!H", 999) + data[6:]

        with self.assertRaises(ValueError) as ctx:
            decode_header(corrupted[:HEADER_SIZE])
        self.assertIn("version", str(ctx.exception).lower())

    def test_roundtrip_plaintext(self):
        payload = {"key": "value", "number": 42, "nested": {"a": [1, 2, 3]}}
        data = encode_packet(PacketType.CONNECT_RESPONSE, payload, aes_key=None)

        ptype, plen, nonce, tag = decode_header(data[:HEADER_SIZE])
        self.assertEqual(ptype, PacketType.CONNECT_RESPONSE)

        import json
        raw = data[HEADER_SIZE:]
        decoded = json.loads(raw.decode("utf-8"))
        self.assertEqual(decoded, payload)

    def test_empty_payload(self):
        data = encode_packet(PacketType.HEALTH_QUERY, {}, aes_key=None)
        ptype, plen, nonce, tag = decode_header(data[:HEADER_SIZE])
        self.assertEqual(ptype, PacketType.HEALTH_QUERY)
        self.assertEqual(plen, 2)  # "{}" is 2 bytes

    def test_unicode_payload(self):
        payload = {"message": "Hello, the quick brown fox jumps over the lazy dog."}
        data = encode_packet(PacketType.CONNECT_REQUEST, payload, aes_key=None)
        self.assertTrue(len(data) > HEADER_SIZE)


class TestProtocolEncrypted(unittest.TestCase):
    """Test encoding/decoding with AES-256-GCM encryption."""

    def test_encrypted_packet_has_nonzero_nonce(self):
        key = generate_aes_key()
        payload = {"secret": "data"}
        data = encode_packet(PacketType.CHAT_MESSAGE, payload, aes_key=key)

        ptype, plen, nonce, tag = decode_header(data[:HEADER_SIZE])
        self.assertEqual(ptype, PacketType.CHAT_MESSAGE)
        self.assertNotEqual(nonce, b"\x00" * 12)
        self.assertNotEqual(tag, b"\x00" * 16)

    def test_encrypted_payload_differs_from_plaintext(self):
        key = generate_aes_key()
        payload = {"secret": "data"}

        encrypted = encode_packet(PacketType.CHAT_MESSAGE, payload, aes_key=key)
        plaintext = encode_packet(PacketType.CONNECT_REQUEST, payload, aes_key=None)

        enc_body = encrypted[HEADER_SIZE:]
        plain_body = plaintext[HEADER_SIZE:]
        self.assertNotEqual(enc_body, plain_body)

    def test_encrypted_roundtrip_via_socket_mock(self):
        """Simulate encode + decode through a mock socket."""
        import io
        import json
        from shared.crypto import aes_decrypt

        key = generate_aes_key()
        payload = {"user": "alice", "msg": "hello bob"}
        data = encode_packet(PacketType.CHAT_MESSAGE, payload, aes_key=key)

        ptype, plen, nonce, tag = decode_header(data[:HEADER_SIZE])
        ciphertext = data[HEADER_SIZE:]
        self.assertEqual(len(ciphertext), plen)

        aad = struct.pack("!4sHHI", MAGIC, PROTOCOL_VERSION, ptype, plen)
        decrypted = aes_decrypt(key, nonce, ciphertext, tag, aad)
        result = json.loads(decrypted.decode("utf-8"))
        self.assertEqual(result, payload)

    def test_wrong_key_fails_decryption(self):
        from shared.crypto import aes_decrypt

        key1 = generate_aes_key()
        key2 = generate_aes_key()
        payload = {"data": "sensitive"}
        data = encode_packet(PacketType.CHAT_MESSAGE, payload, aes_key=key1)

        ptype, plen, nonce, tag = decode_header(data[:HEADER_SIZE])
        ciphertext = data[HEADER_SIZE:]
        aad = struct.pack("!4sHHI", MAGIC, PROTOCOL_VERSION, ptype, plen)

        with self.assertRaises(Exception):
            aes_decrypt(key2, nonce, ciphertext, tag, aad)

    def test_tampered_ciphertext_fails(self):
        from shared.crypto import aes_decrypt

        key = generate_aes_key()
        payload = {"data": "important"}
        data = encode_packet(PacketType.CHAT_MESSAGE, payload, aes_key=key)

        ptype, plen, nonce, tag = decode_header(data[:HEADER_SIZE])
        ciphertext = bytearray(data[HEADER_SIZE:])
        if len(ciphertext) > 0:
            ciphertext[0] ^= 0xFF  # flip one byte
        aad = struct.pack("!4sHHI", MAGIC, PROTOCOL_VERSION, ptype, plen)

        with self.assertRaises(Exception):
            aes_decrypt(key, nonce, bytes(ciphertext), tag, aad)

    def test_plaintext_types_not_encrypted_even_with_key(self):
        key = generate_aes_key()
        payload = {"ip": "127.0.0.1"}
        data = encode_packet(PacketType.CONNECT_REQUEST, payload, aes_key=key)

        ptype, plen, nonce, tag = decode_header(data[:HEADER_SIZE])
        self.assertEqual(nonce, b"\x00" * 12)
        self.assertEqual(tag, b"\x00" * 16)


class TestPacketTypes(unittest.TestCase):
    def test_all_packet_types_are_unique(self):
        values = [p.value for p in PacketType]
        self.assertEqual(len(values), len(set(values)))

    def test_packet_type_ranges(self):
        for p in PacketType:
            self.assertGreaterEqual(p.value, 0)
            self.assertLessEqual(p.value, 0xFFFF)


if __name__ == "__main__":
    unittest.main()
