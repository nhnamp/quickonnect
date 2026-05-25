"""Speech-to-text manager using faster-whisper.

Buffers raw PCM audio per speaker and runs transcription when enough
audio is accumulated (approximately 3 seconds).

Enabled only when the ENABLE_STT=1 environment variable is set.
The whisper model is loaded lazily on the first transcription request.
"""

import io
import logging
import os
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

logger = logging.getLogger(__name__)

# Audio constants — must match the mixer
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2       # 16-bit
CHANNELS = 1           # mono
FRAME_BYTES = 640      # bytes per frame

# Number of frames to accumulate before submitting a transcription job.
# 150 frames × 20 ms = 3 000 ms ≈ 3 seconds of speech.
_FRAMES_PER_CHUNK = 150


class STTManager:
    """Per-room speech-to-text manager.

    Parameters
    ----------
    room_code:
        The room this manager belongs to.
    on_transcript_fn:
        Callback ``(user_id, username, text) -> None`` invoked when a
        non-empty transcription is produced.
    """

    def __init__(
        self,
        room_code: str,
        on_transcript_fn: Callable[[int, str, str], None],
    ) -> None:
        self._room_code = room_code
        self._on_transcript = on_transcript_fn
        self._enabled = os.environ.get("ENABLE_STT", "0") == "1"

        self._lock = threading.Lock()
        # user_id -> list[bytes]  (accumulated PCM frames)
        self._speaker_buffers: dict[int, list[bytes]] = {}
        # user_id -> str
        self._speaker_names: dict[int, str] = {}

        self._running = True
        self._model = None
        self._model_lock = threading.Lock()
        self._pool: ThreadPoolExecutor | None = (
            ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"stt-{room_code}")
            if self._enabled
            else None
        )

        if self._enabled:
            logger.info("Room %s: STT enabled", room_code)
        else:
            logger.debug("Room %s: STT disabled (ENABLE_STT != 1)", room_code)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_enabled(self) -> bool:
        """Return True if speech-to-text is active for this room."""
        return self._enabled

    def feed_audio(self, user_id: int, username: str, pcm_data: bytes) -> None:
        """Accumulate a PCM frame for *user_id*.

        When the buffer reaches ``_FRAMES_PER_CHUNK`` frames the accumulated
        audio is submitted to the thread pool for transcription and the
        buffer is reset.
        """
        if not self._enabled or not self._running:
            return

        submit_frames: list[bytes] | None = None

        with self._lock:
            if user_id not in self._speaker_buffers:
                self._speaker_buffers[user_id] = []
                self._speaker_names[user_id] = username

            buf = self._speaker_buffers[user_id]
            buf.append(pcm_data)

            if len(buf) >= _FRAMES_PER_CHUNK:
                submit_frames = list(buf)
                buf.clear()

        if submit_frames is not None and self._pool is not None:
            uname = self._speaker_names.get(user_id, username)
            self._pool.submit(self._transcribe, user_id, uname, submit_frames)

    def remove_speaker(self, user_id: int) -> None:
        """Clear the buffer for a departing speaker."""
        with self._lock:
            self._speaker_buffers.pop(user_id, None)
            self._speaker_names.pop(user_id, None)

    def stop(self) -> None:
        """Shut down the transcription pool and release resources."""
        self._running = False
        self._enabled = False
        if self._pool is not None:
            self._pool.shutdown(wait=False)
            self._pool = None
        logger.info("Room %s: STT manager stopped", self._room_code)

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def _get_model(self):
        """Lazily load the faster-whisper model.

        Returns the ``WhisperModel`` instance or ``None`` if the library is
        unavailable.  On import failure STT is disabled for the remainder of
        this manager's lifetime so we only log the warning once.
        """
        if self._model is not None:
            return self._model

        with self._model_lock:
            # Double-check after acquiring the lock
            if self._model is not None:
                return self._model

            try:
                from faster_whisper import WhisperModel  # type: ignore[import-untyped]
            except ImportError:
                logger.warning(
                    "Room %s: faster-whisper is not installed — disabling STT",
                    self._room_code,
                )
                self._enabled = False
                return None

            try:
                self._model = WhisperModel("small", device="cpu", compute_type="int8")
                logger.info("Room %s: whisper model loaded (small/cpu/int8)", self._room_code)
            except Exception:
                logger.exception("Room %s: failed to load whisper model", self._room_code)
                self._enabled = False
                return None

            return self._model

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def _transcribe(
        self, user_id: int, username: str, frames: list[bytes],
    ) -> None:
        """Join accumulated PCM frames, transcribe, and invoke the callback.

        The audio is written to an in-memory WAV file because faster-whisper
        accepts file paths or file-like objects.
        """
        if not self._running:
            return

        model = self._get_model()
        if model is None:
            return

        pcm = b"".join(frames)

        # Build an in-memory WAV
        wav_buf = io.BytesIO()
        try:
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(SAMPLE_WIDTH)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(pcm)
        except Exception:
            logger.exception(
                "Room %s: failed to create WAV for uid=%d", self._room_code, user_id,
            )
            return

        wav_buf.seek(0)

        try:
            segments, _info = model.transcribe(wav_buf, beam_size=1)
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        except Exception:
            logger.exception(
                "Room %s: transcription failed for uid=%d", self._room_code, user_id,
            )
            return

        if text:
            try:
                self._on_transcript(user_id, username, text)
            except Exception:
                logger.exception(
                    "Room %s: on_transcript callback failed for uid=%d",
                    self._room_code, user_id,
                )
