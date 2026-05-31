"""Tests for camera frame helpers."""

from PyQt6.QtGui import QImage

from client.features.camera_engine import (
    CAMERA_MAX_HEIGHT,
    CAMERA_MAX_WIDTH,
    _camera_permission_denied_message,
    _encode_jpeg,
    _scale_camera_image,
    decode_camera_jpeg,
)


def test_scale_camera_image_fits_transport_bounds() -> None:
    image = QImage(1280, 720, QImage.Format.Format_RGB888)

    scaled = _scale_camera_image(image)

    assert scaled.width() <= CAMERA_MAX_WIDTH
    assert scaled.height() <= CAMERA_MAX_HEIGHT


def test_camera_jpeg_round_trip() -> None:
    image = QImage(64, 48, QImage.Format.Format_RGB888)
    image.fill(0x336699)

    jpeg = _encode_jpeg(image, 60)
    assert jpeg

    decoded = decode_camera_jpeg(__import__("base64").b64encode(jpeg).decode("ascii"))
    assert decoded is not None
    assert not decoded.isNull()


def test_camera_permission_denied_message_mentions_macos_settings() -> None:
    message = _camera_permission_denied_message()

    assert "macOS" in message
    assert "Privacy & Security > Camera" in message
