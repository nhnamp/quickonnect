"""Client-side microphone capture and mixed-audio playback."""

from __future__ import annotations

import base64
import logging
import queue
import threading
import time

from PyQt6.QtCore import QObject, pyqtSignal

from shared.constants import PacketType

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
BYTES_PER_FRAME = SAMPLES_PER_FRAME * SAMPLE_WIDTH
PLAYBACK_QUEUE_MAX = 20


class AudioEngine(QObject):
    """Owns capture and playback threads for one selected room."""

    level_changed = pyqtSignal(int)
    playback_queue_changed = pyqtSignal(int)
    stopped = pyqtSignal(str)

    def __init__(self, connection_manager, parent=None) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._room_code: str | None = None
        self._muted = False
        self._running = False
        self._seq = 0
        self._lock = threading.Lock()
        self._playback_queue: queue.Queue[bytes] = queue.Queue(maxsize=PLAYBACK_QUEUE_MAX)
        self._capture_thread: threading.Thread | None = None
        self._playback_thread: threading.Thread | None = None
        self._pa = None
        self._input_stream = None
        self._output_stream = None

    def is_running(self) -> bool:
        return self._running

    def is_muted(self) -> bool:
        with self._lock:
            return self._muted

    def start(self, room_code: str) -> tuple[bool, str | None]:
        if self._running:
            return False, "Audio is already running"
        try:
            self._open_audio_devices()
        except Exception as exc:
            self._close_audio_devices()
            return False, f"Could not open microphone/speaker: {exc}"

        self._room_code = room_code
        self._running = True
        self._seq = 0
        self._clear_playback_queue()
        self._capture_thread = threading.Thread(target=self._capture_loop, name="audio-capture", daemon=True)
        self._playback_thread = threading.Thread(target=self._playback_loop, name="audio-playback", daemon=True)
        self._capture_thread.start()
        self._playback_thread.start()
        return True, None

    def stop(self, reason: str = "") -> None:
        if not self._running:
            return
        self._running = False
        self._send_muted(True)
        self._clear_playback_queue()
        current = threading.current_thread()
        for worker in (self._capture_thread, self._playback_thread):
            if worker is not None and worker is not current and worker.is_alive():
                worker.join(timeout=1.0)
        self._close_audio_devices()
        self.stopped.emit(reason)

    def set_room(self, room_code: str | None) -> None:
        if room_code == self._room_code:
            return
        was_running = self._running
        if was_running:
            self.stop("Switched room")
        self._room_code = room_code

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            self._muted = bool(muted)
        self._send_muted(self._muted)

    def handle_mixed_audio(self, payload: dict) -> None:
        if payload.get("room_code") != self._room_code:
            return
        pcm_b64 = payload.get("pcm_b64", "")
        if not pcm_b64:
            return
        try:
            pcm = base64.b64decode(pcm_b64)
        except Exception:
            return
        if len(pcm) != BYTES_PER_FRAME:
            return
        if self._playback_queue.full():
            try:
                self._playback_queue.get_nowait()
            except queue.Empty:
                pass
        try:
            self._playback_queue.put_nowait(pcm)
            self.playback_queue_changed.emit(self._playback_queue.qsize())
        except queue.Full:
            pass

    def _capture_loop(self) -> None:
        try:
            stream = self._input_stream
            if stream is None:
                raise RuntimeError("Microphone stream is not open")
            while self._running:
                if self.is_muted():
                    time.sleep(FRAME_MS / 1000.0)
                    continue
                try:
                    pcm = stream.read(SAMPLES_PER_FRAME, exception_on_overflow=False)
                except Exception:
                    logger.exception("Microphone read failed")
                    time.sleep(0.05)
                    continue
                if len(pcm) != BYTES_PER_FRAME:
                    continue
                self._seq += 1
                self._conn.send(PacketType.AUDIO_CHUNK, {
                    "room_code": self._room_code,
                    "seq": self._seq,
                    "timestamp_ms": int(time.time() * 1000),
                    "sample_rate": SAMPLE_RATE,
                    "channels": CHANNELS,
                    "sample_width": SAMPLE_WIDTH,
                    "pcm_b64": base64.b64encode(pcm).decode("ascii"),
                })
                self.level_changed.emit(_pcm_level(pcm))
        except Exception as exc:
            logger.exception("Audio capture stopped")
            self.stop(f"Audio capture failed: {exc}")

    def _playback_loop(self) -> None:
        try:
            stream = self._output_stream
            if stream is None:
                raise RuntimeError("Speaker stream is not open")
            silence = b"\x00" * BYTES_PER_FRAME
            while self._running:
                try:
                    pcm = self._playback_queue.get(timeout=0.1)
                except queue.Empty:
                    pcm = silence
                stream.write(pcm)
        except Exception as exc:
            logger.exception("Audio playback stopped")
            self.stop(f"Audio playback failed: {exc}")

    def _send_muted(self, muted: bool) -> None:
        if not self._room_code:
            return
        self._conn.send(PacketType.AUDIO_CHUNK, {
            "room_code": self._room_code,
            "muted": bool(muted),
            "timestamp_ms": int(time.time() * 1000),
        })

    def _clear_playback_queue(self) -> None:
        while True:
            try:
                self._playback_queue.get_nowait()
            except queue.Empty:
                break

    def _open_audio_devices(self) -> None:
        import pyaudio

        pa = pyaudio.PyAudio()
        try:
            input_stream = pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=SAMPLES_PER_FRAME,
            )
            output_stream = pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=SAMPLES_PER_FRAME,
            )
        except Exception:
            pa.terminate()
            raise

        self._pa = pa
        self._input_stream = input_stream
        self._output_stream = output_stream

    def _close_audio_devices(self) -> None:
        for attr in ("_input_stream", "_output_stream"):
            stream = getattr(self, attr)
            if stream is None:
                continue
            try:
                if stream.is_active():
                    stream.stop_stream()
                stream.close()
            except Exception:
                logger.debug("Could not close audio stream", exc_info=True)
            setattr(self, attr, None)
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                logger.debug("Could not terminate PyAudio", exc_info=True)
            self._pa = None


def _pcm_level(pcm: bytes) -> int:
    """Return a 0..100 approximate RMS level for UI diagnostics."""
    if not pcm:
        return 0
    import struct

    count = len(pcm) // SAMPLE_WIDTH
    if count <= 0:
        return 0
    samples = struct.unpack("<" + "h" * count, pcm[:count * SAMPLE_WIDTH])
    mean_square = sum(sample * sample for sample in samples) / count
    rms = mean_square ** 0.5
    return max(0, min(100, int((rms / 32768.0) * 100)))
