import base64
import json

from shared.attachments import human_size, validate_attachment_content


def _content(filename="note.txt", mime_type="text/plain", data=b"hello") -> str:
    return json.dumps({
        "filename": filename,
        "mime_type": mime_type,
        "size_bytes": len(data),
        "data_b64": base64.b64encode(data).decode("ascii"),
    })


def test_validate_file_attachment_accepts_valid_payload():
    ok, error = validate_attachment_content(_content(), "file")
    assert ok
    assert error is None


def test_validate_image_attachment_requires_image_mime():
    ok, error = validate_attachment_content(_content(mime_type="text/plain"), "image")
    assert not ok
    assert "Image message" in error


def test_validate_rejects_path_like_filename():
    ok, error = validate_attachment_content(_content(filename="../secret.txt"), "file")
    assert not ok
    assert "filename" in error


def test_validate_rejects_size_mismatch():
    payload = json.loads(_content())
    payload["size_bytes"] = 99
    ok, error = validate_attachment_content(json.dumps(payload), "file")
    assert not ok
    assert "size" in error.lower()


def test_human_size_formats_kilobytes():
    assert human_size(2048) == "2.0 KB"
