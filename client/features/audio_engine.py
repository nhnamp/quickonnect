"""Client-side audio engine.

Two background threads cooperate when the user is in a room:

  Capture thread: reads mic via PyAudio → base64 encode → send AUDIO_CHUNK
  Playback thread: reads from playback queue → writes to speaker via PyAudio

PyAudio is imported lazily so the module can be loaded even if PyAudio is
not installed (the start() method will return an error in that case).
"""

import base64
import logging
import queue
import threading

from shared.constants import PacketType

logger = logging.getLogger(__name__)

# Audio constants
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2       # 16-bit (paInt16)
CHANNELS = 1            # mono
FRAME_DURATION_MS = 20
CHUNK_SIZE = 320        # samples per read/write


class AudioEngine:
    """Captures microphone input and plays back mixed audio from the server.

    The engine owns two daemon threads that run while the user is in a room.
    All interaction with the network goes through *connection_manager.send()*
    which is thread-safe.  Playback data arrives via :meth:`feed_playback`,
    called from the UI thread when a ``MIXED_AUDIO`` packet is received.
    """

    def __init__(self, connection_manager) -> None:
        self._conn = connection_manager

        self._running = False
        self._muted = False
        self._mute_lock = threading.Lock()

        self._room_code: str | None = None
        self._playback_queue: queue.Queue[bytes] = queue.Queue(maxsize=50)

        self._pa = None  # PyAudio instance, created in start()
        self._seq = 0

        self._capture_thread: threading.Thread | None = None
        self._playback_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, room_code: str) -> tuple[bool, str | None]:
        """Start capture and playback threads for *room_code*.

        Returns ``(True, None)`` on success or ``(False, error_message)``
        on failure.
        """
        if self._running:
            return False, "Already running"

        try:
            import pyaudio  # noqa: F401
            self._pa = pyaudio.PyAudio()
        except Exception as exc:
            logger.error("Failed to initialise PyAudio: %s", exc)
            return False, f"Audio system unavailable: {exc}"

        self._room_code = room_code
        self._running = True
        self._seq = 0

        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="audio-capture", daemon=True,
        )
        self._playback_thread = threading.Thread(
            target=self._playback_loop, name="audio-playback", daemon=True,
        )
        self._capture_thread.start()
        self._playback_thread.start()

        logger.info("AudioEngine started for room %s", room_code)
        return True, None

    def stop(self) -> None:
        """Stop both threads and release PyAudio resources."""
        if not self._running:
            return
        self._running = False

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                logger.debug("PyAudio terminate error (ignored)")
            self._pa = None

        # Drain the playback queue so nothing is left over for a future
        # session and so the playback thread (if still blocking on get)
        # can wake up via the timeout and notice _running is False.
        while not self._playback_queue.empty():
            try:
                self._playback_queue.get_nowait()
            except queue.Empty:
                break

        logger.info("AudioEngine stopped")

    # ------------------------------------------------------------------
    # Mute control (thread-safe)
    # ------------------------------------------------------------------

    def set_muted(self, muted: bool) -> None:
        """Set the microphone mute state."""
        with self._mute_lock:
            self._muted = muted
        logger.debug("Mute set to %s", muted)

    def is_muted(self) -> bool:
        """Return the current mute state."""
        with self._mute_lock:
            return self._muted

    # ------------------------------------------------------------------
    # Playback feed (called from UI thread)
    # ------------------------------------------------------------------

    def feed_playback(self, pcm_b64: str) -> None:
        """Enqueue decoded PCM for the playback thread.

        Called from the main/UI thread when a ``MIXED_AUDIO`` packet is
        received.  If the playback queue is full the frame is silently
        dropped to avoid blocking the UI thread.
        """
        try:
            pcm_data = base64.b64decode(pcm_b64)
        except Exception:
            logger.warning("Failed to decode playback audio data")
            return
        try:
            self._playback_queue.put_nowait(pcm_data)
        except queue.Full:
            logger.debug("Playback queue full — dropping audio frame")

    # ------------------------------------------------------------------
    # Capture thread
    # ------------------------------------------------------------------

    def _capture_loop(self) -> None:
        """Read microphone samples and send them as AUDIO_CHUNK packets."""
        try:
            import pyaudio
        except Exception:
            logger.error("pyaudio import failed in capture thread")
            return

        stream = None
        try:
            stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                frames_per_buffer=CHUNK_SIZE,
            )
            logger.debug("Capture stream opened")
        except Exception as exc:
            logger.error("Cannot open microphone: %s", exc)
            return

        try:
            while self._running:
                try:
                    pcm_data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                except Exception:
                    if self._running:
                        logger.warning("Mic read error — skipping frame")
                    continue

                if self.is_muted():
                    continue

                self._seq += 1
                pcm_b64 = base64.b64encode(pcm_data).decode("ascii")

                self._conn.send(PacketType.AUDIO_CHUNK, {
                    "room_code": self._room_code,
                    "pcm_b64": pcm_b64,
                    "seq": self._seq,
                    "codec": "pcm",
                    "sample_rate": SAMPLE_RATE,
                    "channels": CHANNELS,
                    "sample_width": SAMPLE_WIDTH,
                })
        except Exception:
            if self._running:
                logger.exception("Capture loop crashed")
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                logger.debug("Error closing capture stream (ignored)")
            logger.debug("Capture thread exiting")

    # ------------------------------------------------------------------
    # Playback thread
    # ------------------------------------------------------------------

    def _playback_loop(self) -> None:
        """Consume PCM from the playback queue and write to speakers."""
        try:
            import pyaudio
        except Exception:
            logger.error("pyaudio import failed in playback thread")
            return

        stream = None
        try:
            stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                output=True,
                frames_per_buffer=CHUNK_SIZE,
            )
            logger.debug("Playback stream opened")
        except Exception as exc:
            logger.error("Cannot open speaker output: %s", exc)
            return

        try:
            while self._running:
                try:
                    pcm_data = self._playback_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                try:
                    stream.write(pcm_data)
                except Exception:
                    if self._running:
                        logger.warning("Speaker write error — skipping frame")
        except Exception:
            if self._running:
                logger.exception("Playback loop crashed")
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                logger.debug("Error closing playback stream (ignored)")
            logger.debug("Playback thread exiting")
