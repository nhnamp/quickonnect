"""Client-side camera capture engine.

The camera feature uses QtMultimedia so it works inside the existing PyQt
event loop without an extra OpenCV dependency. Frames are downscaled, JPEG
encoded, and sent through the existing ConnectionManager.
"""

import base64
import logging
import time

from PyQt6.QtCore import QObject, QBuffer, QByteArray, QIODevice, pyqtSignal
from PyQt6.QtGui import QImage

from shared.constants import PacketType

logger = logging.getLogger(__name__)


CAMERA_FPS = 12
CAMERA_JPEG_QUALITY = 55
CAMERA_MAX_WIDTH = 360
CAMERA_MAX_HEIGHT = 270


class CameraEngine(QObject):
    """Owns local camera capture and frame sending for one room."""

    frame_captured = pyqtSignal(QImage)
    stopped = pyqtSignal(str)

    def __init__(self, connection_manager, parent=None) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._room_code: str | None = None
        self._running = False
        self._camera = None
        self._capture_session = None
        self._video_sink = None
        self._last_sent = 0.0
        self._seq = 0

    def is_running(self) -> bool:
        return self._running

    def start(self, room_code: str) -> tuple[bool, str | None]:
        if self._running:
            return False, "Camera is already on"

        try:
            from PyQt6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
        except Exception as exc:
            logger.error("Qt camera support unavailable: %s", exc)
            return False, f"Camera support unavailable: {exc}"

        devices = QMediaDevices.videoInputs()
        if not devices:
            return False, "No camera device was found"

        device = devices[0]
        self._video_sink = QVideoSink(self)
        self._video_sink.videoFrameChanged.connect(self._on_video_frame)

        self._camera = QCamera(device, self)
        self._camera.errorOccurred.connect(self._on_camera_error)
        self._capture_session = QMediaCaptureSession(self)
        self._capture_session.setCamera(self._camera)
        self._capture_session.setVideoSink(self._video_sink)

        self._room_code = room_code
        self._running = True
        self._last_sent = 0.0
        self._seq = 0

        logger.info("Starting camera device: %s", device.description())
        self._camera.start()
        return True, None

    def stop(self, reason: str = "") -> None:
        if not self._running and self._camera is None:
            return
        self._running = False

        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                logger.debug("Camera stop error (ignored)")

        if self._video_sink is not None:
            try:
                self._video_sink.videoFrameChanged.disconnect(self._on_video_frame)
            except Exception:
                pass

        self._capture_session = None
        self._video_sink = None
        self._camera = None
        self._room_code = None
        self.stopped.emit(reason)
        logger.info("Camera stopped")

    def _on_video_frame(self, frame) -> None:
        if not self._running or not self._room_code:
            return

        now = time.monotonic()
        min_interval = 1.0 / max(1, CAMERA_FPS)
        if now - self._last_sent < min_interval:
            return

        try:
            image = frame.toImage()
        except Exception as exc:
            logger.warning("Camera frame conversion failed: %s", exc)
            return
        if image.isNull():
            return

        image = image.convertToFormat(QImage.Format.Format_RGB888)
        image = _scale_camera_image(image)
        jpeg_bytes = _encode_jpeg(image, CAMERA_JPEG_QUALITY)
        if not jpeg_bytes:
            logger.warning("Camera JPEG encoding failed")
            return

        self._last_sent = now
        self._seq += 1
        self.frame_captured.emit(image)
        try:
            self._conn.send(PacketType.CAMERA_FRAME, {
                "room_code": self._room_code,
                "seq": self._seq,
                "width": image.width(),
                "height": image.height(),
                "jpeg_b64": base64.b64encode(jpeg_bytes).decode("ascii"),
            })
        except Exception as exc:
            logger.exception("Failed to send camera frame")
            self.stop(f"Failed to send camera frame: {exc}")

    def _on_camera_error(self, error, error_string: str) -> None:
        if not self._running:
            return
        message = error_string or str(error) or "Camera error"
        logger.error("Camera error: %s", message)
        self.stop(message)


def _scale_camera_image(image: QImage) -> QImage:
    """Return an image that fits the camera transport bounds."""
    if image.width() <= CAMERA_MAX_WIDTH and image.height() <= CAMERA_MAX_HEIGHT:
        return image
    from PyQt6.QtCore import Qt
    return image.scaled(
        CAMERA_MAX_WIDTH,
        CAMERA_MAX_HEIGHT,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _encode_jpeg(image: QImage, quality: int) -> bytes | None:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        ok = image.save(buf, "JPG", quality)
        if not ok:
            return None
        return bytes(buf.data())
    finally:
        buf.close()


def decode_camera_jpeg(jpeg_b64: str) -> QImage | None:
    try:
        raw = base64.b64decode(jpeg_b64)
    except Exception:
        return None
    image = QImage()
    if not image.loadFromData(QByteArray(raw), "JPG"):
        return None
    return image
