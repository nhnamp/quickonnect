"""Helpers for file and image messages."""

from __future__ import annotations

import base64
import json
import mimetypes
import os

MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
ALLOWED_MESSAGE_TYPES = {"text", "image", "file"}


def build_attachment_content(path: str, force_image: bool = False) -> tuple[str | None, str | None]:
    """Return a JSON message content string for a local file."""
    try:
        size = os.path.getsize(path)
        if size > MAX_ATTACHMENT_BYTES:
            return None, f"File is too large. Limit is {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB."
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        return None, f"Could not read file: {exc}"

    filename = os.path.basename(path)
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if force_image and not mime_type.startswith("image/"):
        return None, "Selected file is not a recognized image."

    payload = {
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(data),
        "data_b64": base64.b64encode(data).decode("ascii"),
    }
    valid, error = validate_attachment_content(json.dumps(payload), "image" if force_image else "file")
    if not valid:
        return None, error
    return json.dumps(payload, separators=(",", ":")), None


def validate_attachment_content(content: str, msg_type: str) -> tuple[bool, str | None]:
    if msg_type not in {"image", "file"}:
        return False, "Attachment validator only accepts image/file messages"
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False, "Attachment content must be JSON"
    if not isinstance(payload, dict):
        return False, "Attachment content must be an object"

    filename = str(payload.get("filename", "")).strip()
    mime_type = str(payload.get("mime_type", "")).strip()
    data_b64 = str(payload.get("data_b64", ""))
    size_bytes = payload.get("size_bytes")

    if not filename or filename != os.path.basename(filename):
        return False, "Attachment filename is invalid"
    if len(filename) > 180:
        return False, "Attachment filename is too long"
    if not mime_type or "/" not in mime_type:
        return False, "Attachment MIME type is invalid"
    if msg_type == "image" and not mime_type.startswith("image/"):
        return False, "Image message must contain an image MIME type"
    if not isinstance(size_bytes, int) or size_bytes < 0 or size_bytes > MAX_ATTACHMENT_BYTES:
        return False, "Attachment size is invalid"

    try:
        decoded = base64.b64decode(data_b64, validate=True)
    except Exception:
        return False, "Attachment data is not valid base64"
    if len(decoded) != size_bytes:
        return False, "Attachment size does not match data"
    return True, None


def parse_attachment_content(content: str) -> dict | None:
    try:
        payload = json.loads(content)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    valid, _ = validate_attachment_content(content, "image" if str(payload.get("mime_type", "")).startswith("image/") else "file")
    return payload if valid else None


def decode_attachment_data(payload: dict) -> bytes:
    return base64.b64decode(str(payload.get("data_b64", "")), validate=True)


def human_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size_bytes} B"
