"""Client-side screen sharing engine.

Two background threads cooperate when the local user is sharing their screen:

  capture thread ──► bounded queue ──► send thread ──► ConnectionManager.send
       │
       └── grabs the primary monitor with mss, builds a QImage, encodes JPEG
           via QBuffer at the fixed quality, and tries to enqueue the
           frame. If the queue is full (the network can't keep up) the
           oldest queued frame is dropped first — never block the capture.

For the receiver side this module also exposes a single static helper that
decodes a JPEG byte string into a QImage. The decode is called from the
main/UI thread by the screen share widget when a SCREEN_RELAY packet
arrives — never from the network thread.

mss and pyautogui only work where there is a real display, so we import
mss lazily inside the capture thread and surface a clear error if the
host is headless.
"""

import base64
import logging
import threading
import time
import traceback
from collections import deque

from PyQt6.QtCore import QObject, QBuffer, QByteArray, QIODevice, pyqtSignal
from PyQt6.QtGui import QImage

from shared.constants import PacketType

logger = logging.getLogger(__name__)


# Bounded queue depth. With drop-oldest semantics this caps how much
# in-flight latency the network layer can introduce: at 30 FPS, 3 frames
# is ~100 ms worst case before frames start being dropped.
SEND_QUEUE_MAX = 3
SCREEN_CAPTURE_FPS = 30
SCREEN_JPEG_QUALITY = 75
SCREEN_CAPTURE_SCALE = 1.0


class ScreenCaptureEngine(QObject):
    """Drives capture + encode + send threads while the local user is sharing.

    The engine never touches Qt widgets — frame display lives in the widget.
    """

    frame_sent = pyqtSignal(int)        # seq number of the frame just sent
    frame_captured = pyqtSignal(QImage) # local preview frame for the sharer
    stopped = pyqtSignal(str)           # reason (empty string = normal stop)

    def __init__(self, connection_manager, parent=None) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._room_code: str | None = None

        self._queue: deque = deque()
        self._queue_lock = threading.Lock()
        self._queue_cond = threading.Condition(self._queue_lock)

        self._running = False
        self._capture_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._seq = 0
        self._monitor: dict | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._running

    def start(self, room_code: str) -> tuple[bool, str | None]:
        if self._running:
            return False, "Already sharing"
        ok, error = self._preflight_capture()
        if not ok:
            logger.error("Screen capture startup failed: %s", error)
            return False, error
        self._room_code = room_code
        self._running = True
        self._seq = 0
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="screen-capture", daemon=True,
        )
        self._send_thread = threading.Thread(
            target=self._send_loop, name="screen-send", daemon=True,
        )
        self._capture_thread.start()
        self._send_thread.start()
        return True, None

    def stop(self, reason: str = "") -> None:
        if not self._running:
            return
        self._running = False
        # Wake the send thread out of its condition wait so it can exit.
        with self._queue_cond:
            self._queue_cond.notify_all()
        self.stopped.emit(reason)

    def _preflight_capture(self) -> tuple[bool, str | None]:
        """Verify that screen capture can actually initialize and grab once."""
        try:
            with _open_mss() as sct:
                monitor, shot = _select_monitor(sct)
                # Validate conversion/encoding too. A successful grab that
                # cannot become a JPEG would still produce a black/no-frame UI.
                qimg = _qimage_from_mss(shot)
                if qimg.isNull():
                    return False, "Screen capture unavailable: captured image is empty"
                jpeg = _encode_jpeg(qimg, SCREEN_JPEG_QUALITY)
                if not jpeg:
                    return False, "Screen capture unavailable: could not encode captured frame"
                self._monitor = dict(monitor)
            return True, None
        except BaseException as exc:
            return False, f"Screen capture unavailable: {exc}"

    # ------------------------------------------------------------------
    # Capture / encode loop
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        try:
            with _open_mss() as sct:
                monitor = self._monitor or _select_monitor(sct)[0]
                while self._running:
                    frame_start = time.monotonic()
                    frame_interval = 1.0 / SCREEN_CAPTURE_FPS

                    try:
                        shot = sct.grab(monitor)
                    except BaseException as exc:
                        logger.exception("mss.grab failed")
                        self.stop(f"Screen capture failed: {exc}")
                        return

                    qimg = _qimage_from_mss(shot)
                    if qimg.isNull():
                        logger.error("mss produced an empty image")
                        self.stop("Screen capture failed: empty frame")
                        return

                    if SCREEN_CAPTURE_SCALE < 1.0:
                        new_w = max(2, int(shot.width * SCREEN_CAPTURE_SCALE))
                        new_h = max(2, int(shot.height * SCREEN_CAPTURE_SCALE))
                        from PyQt6.QtCore import Qt
                        qimg = qimg.scaled(
                            new_w, new_h,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )

                    jpeg_bytes = _encode_jpeg(qimg, SCREEN_JPEG_QUALITY)
                    if jpeg_bytes is None:
                        logger.error("QImage JPEG encoding failed")
                        self.stop("Screen capture failed: could not encode JPEG frame")
                        return

                    self.frame_captured.emit(qimg)
                    self._enqueue_frame(jpeg_bytes, qimg.width(), qimg.height())

                    # Pace to the configured FPS.
                    elapsed = time.monotonic() - frame_start
                    sleep_for = frame_interval - elapsed
                    if sleep_for > 0:
                        time.sleep(sleep_for)
        except BaseException as exc:
            logger.exception("Capture loop crashed")
            self.stop(f"Capture loop crashed: {exc}")

    def _enqueue_frame(self, jpeg_bytes: bytes, width: int, height: int) -> None:
        with self._queue_cond:
            while len(self._queue) >= SEND_QUEUE_MAX:
                self._queue.popleft()
            self._seq += 1
            self._queue.append((self._seq, jpeg_bytes, width, height))
            self._queue_cond.notify()

    # ------------------------------------------------------------------
    # Send loop
    # ------------------------------------------------------------------

    def _send_loop(self) -> None:
        while self._running:
            item = None
            with self._queue_cond:
                while self._running and not self._queue:
                    self._queue_cond.wait(timeout=0.5)
                if not self._running:
                    break
                if self._queue:
                    item = self._queue.popleft()
            if item is None:
                continue
            seq, jpeg_bytes, width, height = item
            try:
                self._conn.send(PacketType.SCREEN_FRAME, {
                    "room_code": self._room_code,
                    "seq": seq,
                    "width": width,
                    "height": height,
                    "jpeg_b64": base64.b64encode(jpeg_bytes).decode("ascii"),
                })
                self.frame_sent.emit(seq)
            except BaseException as exc:
                logger.exception("Failed to send screen frame")
                self.stop(f"Failed to send screen frame: {exc}")


def _open_mss():
    """Open an mss capture context, supporting both old and new mss APIs."""
    try:
        import mss
        factory = getattr(mss, "MSS", None) or getattr(mss, "mss")
        return factory()
    except BaseException:
        logger.error("Unable to initialize mss:\n%s", traceback.format_exc())
        raise


def _select_monitor(sct) -> tuple[dict, object]:
    """Pick a monitor that produces usable pixels.

    mss exposes monitor 0 as the "all monitors" composite and monitor 1+ as
    physical displays. Some Linux display setups report a first physical
    monitor that grabs as all black while the composite still contains the
    real desktop, so preflight tries every candidate and prefers a non-blank
    first frame.
    """
    monitors = getattr(sct, "monitors", None) or []
    if not monitors:
        raise RuntimeError("No monitors reported by screen capture backend")

    if len(monitors) > 1:
        candidates = list(monitors[1:]) + [monitors[0]]
    else:
        candidates = [monitors[0]]

    first_success: tuple[dict, object] | None = None
    first_error: BaseException | None = None
    for monitor in candidates:
        try:
            shot = sct.grab(monitor)
        except BaseException as exc:
            if first_error is None:
                first_error = exc
            logger.warning("Screen grab failed for monitor %s: %s", monitor, exc)
            continue
        if first_success is None:
            first_success = (monitor, shot)
        if _looks_non_blank(shot):
            return monitor, shot

    if first_success is not None:
        monitor, _shot = first_success
        logger.warning(
            "All screen capture candidates look blank; using monitor %s anyway",
            monitor,
        )
        return first_success
    if first_error is not None:
        raise first_error
    raise RuntimeError("No monitor could be captured")


def _looks_non_blank(shot) -> bool:
    """Return True when a captured frame has visible pixel variation."""
    raw = getattr(shot, "rgb", None) or getattr(shot, "bgra", None) or getattr(shot, "raw", b"")
    if not raw:
        return False
    sample = raw[:: max(1, len(raw) // 8192)]
    return max(sample) - min(sample) > 2 and max(sample) > 8


def _qimage_from_mss(shot) -> QImage:
    """Convert an mss screenshot to a detached QImage using explicit RGB bytes."""
    try:
        rgb = shot.rgb
    except BaseException:
        logger.exception("Failed to read RGB bytes from mss frame")
        raise
    return QImage(
        rgb,
        shot.width,
        shot.height,
        shot.width * 3,
        QImage.Format.Format_RGB888,
    ).copy()


def _encode_jpeg(qimage: QImage, quality: int) -> bytes | None:
    """Encode a QImage to JPEG via QBuffer. Returns None on failure."""
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    try:
        ok = qimage.save(buf, "JPG", quality)
        if not ok:
            return None
        return bytes(buf.data())
    finally:
        buf.close()


def decode_jpeg(jpeg_b64: str) -> QImage | None:
    """Decode a base64-encoded JPEG frame into a QImage (UI-thread helper)."""
    try:
        raw = base64.b64decode(jpeg_b64)
    except Exception:
        return None
    qimg = QImage()
    if not qimg.loadFromData(QByteArray(raw), "JPG"):
        return None
    return qimg
