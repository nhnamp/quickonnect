"""Tests for Phase 5 features: E2E encryption, reconnection, and room management."""

import base64
import os
import tempfile
import threading
import time
import unittest

from shared.crypto import (
    generate_rsa_keypair,
    serialize_public_key,
    deserialize_public_key,
    serialize_private_key,
    deserialize_private_key,
    e2e_encrypt_message,
    e2e_decrypt_message,
    generate_aes_key,
)
from shared.constants import PacketType
from client.storage.local_store import LocalStore


class TestE2EEncryption(unittest.TestCase):
    """Tests for the E2E message encryption functions."""

    def test_encrypt_decrypt_roundtrip(self):
        """A message encrypted with the recipient's public key should decrypt with their private key."""
        priv, pub = generate_rsa_keypair()
        plaintext = "Hello, this is a secret message! 🔒"
        encrypted = e2e_encrypt_message(plaintext, pub)

        self.assertIn("encrypted_content", encrypted)
        self.assertIn("encrypted_key", encrypted)
        self.assertIn("nonce", encrypted)
        self.assertIn("tag", encrypted)

        decrypted = e2e_decrypt_message(encrypted, priv)
        self.assertEqual(decrypted, plaintext)

    def test_wrong_key_fails(self):
        """Decrypting with the wrong private key should raise ValueError."""
        priv1, pub1 = generate_rsa_keypair()
        priv2, pub2 = generate_rsa_keypair()

        encrypted = e2e_encrypt_message("secret", pub1)

        with self.assertRaises(ValueError):
            e2e_decrypt_message(encrypted, priv2)

    def test_tampered_content_fails(self):
        """Tampered encrypted content should fail decryption."""
        priv, pub = generate_rsa_keypair()
        encrypted = e2e_encrypt_message("original message", pub)

        # Tamper with the encrypted content
        content_bytes = base64.b64decode(encrypted["encrypted_content"])
        tampered = bytearray(content_bytes)
        if len(tampered) > 0:
            tampered[0] ^= 0xFF
        encrypted["encrypted_content"] = base64.b64encode(bytes(tampered)).decode("ascii")

        with self.assertRaises(ValueError):
            e2e_decrypt_message(encrypted, priv)

    def test_empty_message(self):
        """Empty messages should encrypt and decrypt correctly."""
        priv, pub = generate_rsa_keypair()
        encrypted = e2e_encrypt_message("", pub)
        decrypted = e2e_decrypt_message(encrypted, priv)
        self.assertEqual(decrypted, "")

    def test_unicode_message(self):
        """Unicode messages with special characters should work."""
        priv, pub = generate_rsa_keypair()
        msg = "日本語テスト 🎌 Привет мир 🌍"
        encrypted = e2e_encrypt_message(msg, pub)
        decrypted = e2e_decrypt_message(encrypted, priv)
        self.assertEqual(decrypted, msg)

    def test_long_message(self):
        """Long messages should work (AES handles arbitrary length)."""
        priv, pub = generate_rsa_keypair()
        msg = "A" * 10000
        encrypted = e2e_encrypt_message(msg, pub)
        decrypted = e2e_decrypt_message(encrypted, priv)
        self.assertEqual(decrypted, msg)


class TestPrivateKeySerialization(unittest.TestCase):
    """Tests for RSA private key serialization added in Phase 5."""

    def test_serialize_deserialize_roundtrip(self):
        """Private key should survive serialization and deserialization."""
        priv, pub = generate_rsa_keypair()
        pem = serialize_private_key(priv)
        restored = deserialize_private_key(pem)

        # Verify by encrypting with public and decrypting with restored private
        from shared.crypto import rsa_encrypt, rsa_decrypt
        plaintext = b"test data 123"
        ct = rsa_encrypt(pub, plaintext)
        result = rsa_decrypt(restored, ct)
        self.assertEqual(result, plaintext)

    def test_pem_format(self):
        """Serialized private key should be in PEM format."""
        priv, _ = generate_rsa_keypair()
        pem = serialize_private_key(priv)
        self.assertTrue(pem.startswith(b"-----BEGIN PRIVATE KEY-----"))
        self.assertTrue(pem.strip().endswith(b"-----END PRIVATE KEY-----"))


class TestLocalStoreKeypair(unittest.TestCase):
    """Tests for keypair storage in LocalStore."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.store = LocalStore(self._tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_save_and_load_keypair(self):
        """Saved keypair should be loadable."""
        priv, pub = generate_rsa_keypair()
        priv_pem = serialize_private_key(priv)
        pub_pem = serialize_public_key(pub)

        self.store.save_user_keypair("testuser", priv_pem, pub_pem)
        result = self.store.load_user_keypair("testuser")

        self.assertIsNotNone(result)
        loaded_priv, loaded_pub = result
        self.assertEqual(loaded_priv, priv_pem)
        self.assertEqual(loaded_pub, pub_pem)

    def test_load_nonexistent_keypair(self):
        """Loading a nonexistent keypair should return None."""
        self.assertIsNone(self.store.load_user_keypair("nobody"))

    def test_save_and_load_peer_key(self):
        """Peer public keys should be saveable and loadable."""
        _, pub = generate_rsa_keypair()
        pub_pem = serialize_public_key(pub)

        self.store.save_peer_public_key("alice", pub_pem)
        loaded = self.store.load_peer_public_key("alice")
        self.assertEqual(loaded, pub_pem)

    def test_load_nonexistent_peer_key(self):
        """Loading a nonexistent peer key should return None."""
        self.assertIsNone(self.store.load_peer_public_key("nobody"))


class TestPacketTypes(unittest.TestCase):
    """Verify Phase 5 packet types exist and are unique."""

    def test_new_packet_types_exist(self):
        """Phase 5 packet types should be defined."""
        self.assertEqual(PacketType.ROOM_INVITE, 0x0024)
        self.assertEqual(PacketType.ROOM_INVITE_NOTIFY, 0x0025)
        self.assertEqual(PacketType.PUBLIC_KEY_ANNOUNCE, 0x0090)
        self.assertEqual(PacketType.PUBLIC_KEY_REQUEST, 0x0091)
        self.assertEqual(PacketType.PUBLIC_KEY_RESPONSE, 0x0092)
        self.assertEqual(PacketType.SERVER_SHUTDOWN, 0x00FD)

    def test_all_packet_types_unique(self):
        """All packet type values should be unique."""
        values = [pt.value for pt in PacketType]
        self.assertEqual(len(values), len(set(values)),
                         f"Duplicate packet type values: {[v for v in values if values.count(v) > 1]}")


class TestConnectionManagerReconnect(unittest.TestCase):
    """Tests for ConnectionManager reconnection configuration."""

    def test_enable_disable_reconnect(self):
        """Reconnection should be toggleable."""
        from client.network.connection import ConnectionManager
        cm = ConnectionManager()
        self.assertFalse(cm._reconnect_enabled)

        cm.enable_reconnect("127.0.0.1", 9000,
                            {"token": "test"}, "jwt", ["ROOM-1"])
        self.assertTrue(cm._reconnect_enabled)
        self.assertEqual(cm._reconnect_host, "127.0.0.1")
        self.assertEqual(cm._reconnect_port, 9000)
        self.assertEqual(cm._reconnect_room_codes, ["ROOM-1"])

        cm.disable_reconnect()
        self.assertFalse(cm._reconnect_enabled)

    def test_update_room_codes(self):
        """Room codes should be updatable for reconnection."""
        from client.network.connection import ConnectionManager
        cm = ConnectionManager()
        cm.enable_reconnect("localhost", 9000, {"token": "t"}, "jwt", [])
        cm.update_room_codes(["ROOM-A", "ROOM-B"])
        self.assertEqual(cm._reconnect_room_codes, ["ROOM-A", "ROOM-B"])

    def test_disconnect_disables_reconnect(self):
        """Intentional disconnect should disable reconnection."""
        from client.network.connection import ConnectionManager
        cm = ConnectionManager()
        cm.enable_reconnect("localhost", 9000, {"token": "t"}, "jwt")
        cm.disconnect()
        self.assertFalse(cm._reconnect_enabled)


if __name__ == "__main__":
    unittest.main()
