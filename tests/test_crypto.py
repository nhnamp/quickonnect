"""Tests for the cryptography module."""

import time
import unittest

from shared.crypto import (
    generate_rsa_keypair,
    serialize_public_key,
    deserialize_public_key,
    rsa_encrypt,
    rsa_decrypt,
    generate_aes_key,
    aes_encrypt,
    aes_decrypt,
    hash_password,
    verify_password,
    create_jwt,
    decode_jwt,
)


class TestRSA(unittest.TestCase):
    def test_keypair_generation(self):
        priv, pub = generate_rsa_keypair()
        self.assertIsNotNone(priv)
        self.assertIsNotNone(pub)

    def test_public_key_serialization_roundtrip(self):
        priv, pub = generate_rsa_keypair()
        pem = serialize_public_key(pub)
        pub2 = deserialize_public_key(pem)

        pem2 = serialize_public_key(pub2)
        self.assertEqual(pem, pem2)

    def test_encrypt_decrypt_roundtrip(self):
        priv, pub = generate_rsa_keypair()
        plaintext = b"This is a secret AES key placeholder."
        ciphertext = rsa_encrypt(pub, plaintext)
        decrypted = rsa_decrypt(priv, ciphertext)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_32_byte_key(self):
        priv, pub = generate_rsa_keypair()
        aes_key = generate_aes_key()
        self.assertEqual(len(aes_key), 32)

        ciphertext = rsa_encrypt(pub, aes_key)
        decrypted = rsa_decrypt(priv, ciphertext)
        self.assertEqual(decrypted, aes_key)

    def test_wrong_key_fails(self):
        priv1, pub1 = generate_rsa_keypair()
        priv2, pub2 = generate_rsa_keypair()

        ciphertext = rsa_encrypt(pub1, b"secret")
        with self.assertRaises(Exception):
            rsa_decrypt(priv2, ciphertext)

    def test_different_keypairs_produce_different_keys(self):
        priv1, pub1 = generate_rsa_keypair()
        priv2, pub2 = generate_rsa_keypair()

        pem1 = serialize_public_key(pub1)
        pem2 = serialize_public_key(pub2)
        self.assertNotEqual(pem1, pem2)


class TestAES(unittest.TestCase):
    def test_key_generation(self):
        key = generate_aes_key()
        self.assertEqual(len(key), 32)

    def test_encrypt_decrypt_roundtrip(self):
        key = generate_aes_key()
        plaintext = b"Hello, World! This is a test message."
        nonce, ct, tag = aes_encrypt(key, plaintext)

        self.assertEqual(len(nonce), 12)
        self.assertEqual(len(tag), 16)

        decrypted = aes_decrypt(key, nonce, ct, tag)
        self.assertEqual(decrypted, plaintext)

    def test_encrypt_with_aad(self):
        key = generate_aes_key()
        plaintext = b"payload data"
        aad = b"header bytes"

        nonce, ct, tag = aes_encrypt(key, plaintext, aad)
        decrypted = aes_decrypt(key, nonce, ct, tag, aad)
        self.assertEqual(decrypted, plaintext)

    def test_wrong_aad_fails(self):
        key = generate_aes_key()
        plaintext = b"payload"
        aad = b"correct_header"

        nonce, ct, tag = aes_encrypt(key, plaintext, aad)
        with self.assertRaises(Exception):
            aes_decrypt(key, nonce, ct, tag, b"wrong_header")

    def test_wrong_key_fails(self):
        key1 = generate_aes_key()
        key2 = generate_aes_key()
        plaintext = b"secret"

        nonce, ct, tag = aes_encrypt(key1, plaintext)
        with self.assertRaises(Exception):
            aes_decrypt(key2, nonce, ct, tag)

    def test_unique_nonces(self):
        key = generate_aes_key()
        nonces = set()
        for _ in range(100):
            nonce, _, _ = aes_encrypt(key, b"test")
            nonces.add(nonce)
        self.assertEqual(len(nonces), 100)

    def test_empty_plaintext(self):
        key = generate_aes_key()
        nonce, ct, tag = aes_encrypt(key, b"")
        decrypted = aes_decrypt(key, nonce, ct, tag)
        self.assertEqual(decrypted, b"")


class TestBCrypt(unittest.TestCase):
    def test_hash_and_verify(self):
        pw = "my_secure_password123"
        hashed = hash_password(pw)
        self.assertTrue(verify_password(pw, hashed))

    def test_wrong_password_fails(self):
        hashed = hash_password("correct_password")
        self.assertFalse(verify_password("wrong_password", hashed))

    def test_different_passwords_different_hashes(self):
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        self.assertNotEqual(h1, h2)

    def test_same_password_different_salts(self):
        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        self.assertNotEqual(h1, h2)  # different salts
        self.assertTrue(verify_password("same_password", h1))
        self.assertTrue(verify_password("same_password", h2))


class TestJWT(unittest.TestCase):
    def test_create_and_decode(self):
        secret = "test_secret_key"
        token = create_jwt(42, "alice", secret)
        payload = decode_jwt(token, secret)

        self.assertIsNotNone(payload)
        self.assertEqual(payload["user_id"], 42)
        self.assertEqual(payload["username"], "alice")
        self.assertIn("iat", payload)
        self.assertIn("exp", payload)

    def test_wrong_secret_fails(self):
        token = create_jwt(1, "bob", "secret1")
        result = decode_jwt(token, "secret2")
        self.assertIsNone(result)

    def test_tampered_payload_fails(self):
        token = create_jwt(1, "alice", "secret")
        parts = token.split(".")
        import base64, json
        payload_data = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
        payload_data["user_id"] = 999
        tampered = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).rstrip(b"=").decode()
        tampered_token = f"{parts[0]}.{tampered}.{parts[2]}"

        result = decode_jwt(tampered_token, "secret")
        self.assertIsNone(result)

    def test_expired_token_fails(self):
        import shared.crypto as crypto
        original_expiry = crypto.JWT_EXPIRY_HOURS

        try:
            crypto.JWT_EXPIRY_HOURS = 0
            from shared.constants import JWT_EXPIRY_HOURS
            # Create token that expires immediately
            secret = "test"
            import json, hmac, hashlib
            header = crypto._b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
            payload_dict = {"user_id": 1, "username": "x", "iat": int(time.time()) - 10, "exp": int(time.time()) - 5}
            payload_b64 = crypto._b64url_encode(json.dumps(payload_dict).encode())
            message = f"{header}.{payload_b64}"
            sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
            sig_b64 = crypto._b64url_encode(sig)
            token = f"{message}.{sig_b64}"

            result = decode_jwt(token, secret)
            self.assertIsNone(result)
        finally:
            crypto.JWT_EXPIRY_HOURS = original_expiry

    def test_malformed_token_fails(self):
        self.assertIsNone(decode_jwt("not.a.valid.token.at.all", "secret"))
        self.assertIsNone(decode_jwt("", "secret"))
        self.assertIsNone(decode_jwt("onlytwoparts.here", "secret"))


if __name__ == "__main__":
    unittest.main()
