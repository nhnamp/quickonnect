import os
import time
import hmac
import json
import hashlib
import base64
import logging

import bcrypt
from cryptography.hazmat.primitives.asymmetric import rsa, padding as asym_padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from shared.constants import BCRYPT_COST, JWT_EXPIRY_HOURS

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RSA Key Exchange
# ---------------------------------------------------------------------------

def generate_rsa_keypair() -> tuple:
    """Generate an ephemeral RSA-2048 key pair. Returns (private_key, public_key)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


def serialize_public_key(public_key) -> bytes:
    """Serialize RSA public key to PEM bytes."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def deserialize_public_key(pem_bytes: bytes):
    """Deserialize RSA public key from PEM bytes."""
    return serialization.load_pem_public_key(pem_bytes)


def rsa_encrypt(public_key, plaintext: bytes) -> bytes:
    """Encrypt data with RSA-OAEP-SHA256. Max plaintext size ~190 bytes for 2048-bit key."""
    return public_key.encrypt(
        plaintext,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def rsa_decrypt(private_key, ciphertext: bytes) -> bytes:
    """Decrypt data with RSA-OAEP-SHA256."""
    return private_key.decrypt(
        ciphertext,
        asym_padding.OAEP(
            mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


# ---------------------------------------------------------------------------
# AES-256-GCM
# ---------------------------------------------------------------------------

def generate_aes_key() -> bytes:
    """Generate a random 256-bit AES key."""
    return AESGCM.generate_key(bit_length=256)


def aes_encrypt(key: bytes, plaintext: bytes, aad: bytes | None = None) -> tuple[bytes, bytes, bytes]:
    """
    Encrypt with AES-256-GCM.
    Returns (nonce, ciphertext, auth_tag). Nonce is 12 bytes, tag is 16 bytes.
    """
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_and_tag = aesgcm.encrypt(nonce, plaintext, aad)
    ciphertext = ct_and_tag[:-16]
    tag = ct_and_tag[-16:]
    return nonce, ciphertext, tag


def aes_decrypt(key: bytes, nonce: bytes, ciphertext: bytes, tag: bytes, aad: bytes | None = None) -> bytes:
    """Decrypt with AES-256-GCM. Raises InvalidTag on tampered data."""
    aesgcm = AESGCM(key)
    ct_and_tag = ciphertext + tag
    return aesgcm.decrypt(nonce, ct_and_tag, aad)


# ---------------------------------------------------------------------------
# BCrypt Password Hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    """Hash a password with BCrypt. Returns the hash as a string."""
    salt = bcrypt.gensalt(rounds=BCRYPT_COST)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a BCrypt hash."""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT (HMAC-SHA256, self-implemented — no external JWT library needed)
# ---------------------------------------------------------------------------

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_jwt(user_id: int, username: str, secret: str) -> str:
    """Create a JWT token signed with HMAC-SHA256."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "username": username,
        "iat": now,
        "exp": now + JWT_EXPIRY_HOURS * 3600,
    }

    header_b64 = _b64url_encode(json.dumps(header).encode())
    payload_b64 = _b64url_encode(json.dumps(payload).encode())
    message = f"{header_b64}.{payload_b64}"

    signature = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    return f"{message}.{sig_b64}"


def decode_jwt(token: str, secret: str) -> dict | None:
    """
    Decode and verify a JWT token. Returns the payload dict on success, None on failure
    (invalid signature, expired, or malformed).
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts
    message = f"{header_b64}.{payload_b64}"

    expected_sig = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    actual_sig = _b64url_decode(sig_b64)

    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64))
    except (json.JSONDecodeError, Exception):
        return None

    if payload.get("exp", 0) < int(time.time()):
        return None

    return payload


# ---------------------------------------------------------------------------
# E2E Message Encryption (for DM text messages)
# ---------------------------------------------------------------------------

def e2e_encrypt_message(plaintext: str, recipient_pub_key) -> dict:
    """Encrypt a message for E2E delivery.

    Generates a random AES-256 key, encrypts the message with AES-GCM,
    then wraps the AES key with the recipient's RSA public key.
    Returns a dict with encrypted_content, encrypted_key, nonce, and tag
    (all base64-encoded).
    """
    aes_key = generate_aes_key()
    plaintext_bytes = plaintext.encode("utf-8")
    nonce, ciphertext, tag = aes_encrypt(aes_key, plaintext_bytes)
    encrypted_key = rsa_encrypt(recipient_pub_key, aes_key)
    return {
        "encrypted_content": base64.b64encode(ciphertext).decode("ascii"),
        "encrypted_key": base64.b64encode(encrypted_key).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }


def e2e_decrypt_message(encrypted_data: dict, private_key) -> str:
    """Decrypt an E2E encrypted message.

    Unwraps the AES key with the recipient's RSA private key,
    then decrypts the message content with AES-GCM.
    Returns the plaintext string. Raises ValueError on failure.
    """
    try:
        encrypted_key = base64.b64decode(encrypted_data["encrypted_key"])
        aes_key = rsa_decrypt(private_key, encrypted_key)
        ciphertext = base64.b64decode(encrypted_data["encrypted_content"])
        nonce = base64.b64decode(encrypted_data["nonce"])
        tag = base64.b64decode(encrypted_data["tag"])
        plaintext_bytes = aes_decrypt(aes_key, nonce, ciphertext, tag)
        return plaintext_bytes.decode("utf-8")
    except Exception as e:
        raise ValueError(f"Failed to decrypt E2E message: {e}") from e


def serialize_private_key(private_key) -> bytes:
    """Serialize RSA private key to PEM bytes (no password protection)."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def deserialize_private_key(pem_bytes: bytes):
    """Deserialize RSA private key from PEM bytes."""
    return serialization.load_pem_private_key(pem_bytes, password=None)

