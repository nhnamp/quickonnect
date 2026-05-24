"""Client-side screen sharing engine.

Two background threads cooperate when the local user is sharing their screen:

  capture thread ──► bounded queue ──► send thread ──► ConnectionManager.send
       │
       └── grabs the primary monitor with mss, builds a QImage, encodes JPEG
           via QBuffer at the configured quality, and tries to enqueue the
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
from collections import deque

from PyQt6.QtCore import QObject, QBuffer, QByteArray, QIODevice, pyqtSignal
from PyQt6.QtGui import QImage

from shared.constants import PacketType

logger = logging.getLogger(__name__)


# Bounded queue depth. With drop-oldest semantics this caps how much
# in-flight latency the network layer can introduce: at 30 FPS, 3 frames
# is ~100 ms worst case before frames start being dropped.
SEND_QUEUE_MAX = 3


class ScreenCaptureEngine(QObject):
    """Drives capture + encode + send threads while the local user is sharing.

    Quality and FPS are tunable at runtime via set_quality / set_fps. The
    engine never touches Qt widgets — frame display lives in the widget,
    which receives a `frame_dropped` signal so the UI can show diagnostics.
    """

    frame_sent = pyqtSignal(int)        # seq number of the frame just sent
    frame_dropped = pyqtSignal(int)     # cumulative dropped-frame count
    stopped = pyqtSignal(str)           # reason (empty string = normal stop)

    def __init__(self, connection_manager, parent=None) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._room_code: str | None = None

        self._quality: int = 70   # JPEG quality 30-95
        self._fps: int = 30       # 5..30
        self._scale: float = 1.0  # capture scale 0.25..1.0
        self._params_lock = threading.Lock()

        self._queue: deque = deque()
        self._queue_lock = threading.Lock()
        self._queue_cond = threading.Condition(self._queue_lock)

        self._running = False
        self._capture_thread: threading.Thread | None = None
        self._send_thread: threading.Thread | None = None
        self._seq = 0
        self._dropped_total = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_running(self) -> bool:
        return self._running

    def start(self, room_code: str) -> tuple[bool, str | None]:
        if self._running:
            return False, "Already sharing"
        try:
            import mss  # noqa: F401  (probe import — fails fast on headless hosts)
        except Exception as exc:
            return False, f"Screen capture unavailable: {exc}"
        self._room_code = room_code
        self._running = True
        self._seq = 0
        self._dropped_total = 0
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

    # ------------------------------------------------------------------
    # Runtime tuning
    # ------------------------------------------------------------------

    def set_quality(self, quality: int) -> None:
        with self._params_lock:
            self._quality = max(30, min(95, int(quality)))

    def set_fps(self, fps: int) -> None:
        with self._params_lock:
            self._fps = max(5, min(30, int(fps)))

    def set_scale(self, scale: float) -> None:
        with self._params_lock:
            self._scale = max(0.25, min(1.0, float(scale)))

    def _read_params(self) -> tuple[int, int, float]:
        with self._params_lock:
            return self._quality, self._fps, self._scale

    # ------------------------------------------------------------------
    # Capture / encode loop
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        try:
            import mss
        except Exception:
            logger.exception("mss import failed in capture thread")
            self.stop("Screen capture not available on this system")
            return

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                while self._running:
                    frame_start = time.monotonic()
                    quality, fps, scale = self._read_params()
                    frame_interval = 1.0 / max(1, fps)

                    try:
                        shot = sct.grab(monitor)
                    except Exception:
                        logger.exception("mss.grab failed")
                        time.sleep(0.1)
                        continue

                    # mss returns BGRA. Build a QImage from the raw buffer,
                    # then convert to RGB (smaller, JPEG-natural) and scale.
                    qimg = QImage(
                        shot.bgra, shot.width, shot.height, shot.width * 4,
                        QImage.Format.Format_RGB32,
                    ).copy()  # copy() detaches from mss's buffer

                    if scale < 1.0:
                        new_w = max(2, int(shot.width * scale))
                        new_h = max(2, int(shot.height * scale))
                        from PyQt6.QtCore import Qt
                        qimg = qimg.scaled(
                            new_w, new_h,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )

                    jpeg_bytes = _encode_jpeg(qimg, quality)
                    if jpeg_bytes is None:
                        time.sleep(frame_interval)
                        continue

                    self._enqueue_frame(jpeg_bytes, qimg.width(), qimg.height())

                    # Pace to the configured FPS.
                    elapsed = time.monotonic() - frame_start
                    sleep_for = frame_interval - elapsed
                    if sleep_for > 0:
                        time.sleep(sleep_for)
        except Exception:
            logger.exception("Capture loop crashed")
            self.stop("Capture loop crashed")

    def _enqueue_frame(self, jpeg_bytes: bytes, width: int, height: int) -> None:
        with self._queue_cond:
            while len(self._queue) >= SEND_QUEUE_MAX:
                self._queue.popleft()
                self._dropped_total += 1
                self.frame_dropped.emit(self._dropped_total)
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
            except Exception:
                logger.exception("Failed to send screen frame")


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
