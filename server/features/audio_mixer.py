"""Per-room audio mixer with jitter buffers.

Manages per-client jitter buffers and runs a mixer thread at 20ms ticks.
For each client, mixes all other participants' audio (excluding their own)
and sends the result as a MIXED_AUDIO packet.

The mixer thread starts lazily on the first call to feed_audio() and
stops when stop() is called or all participants are removed.
"""

import base64
import logging
import struct
import threading
import time
from collections import deque
from typing import Callable

from shared.constants import PacketType

logger = logging.getLogger(__name__)

# Audio constants
SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2       # 16-bit
CHANNELS = 1           # mono
FRAME_DURATION_MS = 20
FRAME_SIZE = 320       # samples per frame
FRAME_BYTES = 640      # bytes per frame


class AudioMixerState:
    """Per-room audio mixer state.

    Holds jitter buffers for each participant and drives a background thread
    that mixes audio at 20 ms intervals.

    Parameters
    ----------
    room_code:
        The room this mixer belongs to.
    get_clients_fn:
        Callable returning ``dict[int, handler]`` — the current room members.
    stt_feed_fn:
        Optional callable ``(user_id, username, pcm_bytes) -> None`` invoked
        for every incoming audio frame so STT can accumulate speech.
    """

    def __init__(
        self,
        room_code: str,
        get_clients_fn: Callable[[], dict],
        stt_feed_fn: Callable[[int, str, bytes], None] | None = None,
    ) -> None:
        self._room_code = room_code
        self._get_clients = get_clients_fn
        self._stt_feed = stt_feed_fn

        self._lock = threading.Lock()
        # user_id -> deque of raw PCM frames (bytes, each FRAME_BYTES long)
        self._buffers: dict[int, deque[bytes]] = {}
        # user_id -> username (needed for stt callback)
        self._usernames: dict[int, str] = {}

        self._running = False
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_participant(self, user_id: int, username: str) -> None:
        """Register a participant with a fresh jitter buffer."""
        with self._lock:
            if user_id not in self._buffers:
                self._buffers[user_id] = deque(maxlen=10)
                self._usernames[user_id] = username
                logger.debug(
                    "Room %s: added audio participant %s (uid=%d)",
                    self._room_code, username, user_id,
                )

    def remove_participant(self, user_id: int) -> None:
        """Remove a participant's jitter buffer.

        If no buffers remain the mixer thread is stopped automatically.
        """
        stop_needed = False
        with self._lock:
            self._buffers.pop(user_id, None)
            self._usernames.pop(user_id, None)
            if not self._buffers and self._running:
                stop_needed = True

        if stop_needed:
            self.stop()

    def feed_audio(
        self, user_id: int, pcm_b64: str, seq: int = 0,
    ) -> None:
        """Ingest a base64-encoded PCM frame from a participant.

        The frame is decoded, normalised to exactly ``FRAME_BYTES`` bytes
        (padded with silence or truncated), and appended to the participant's
        jitter buffer.  The optional *stt_feed_fn* callback is invoked with
        the raw PCM so speech-to-text can accumulate audio.

        The mixer thread is started lazily on the first call.
        """
        try:
            pcm = base64.b64decode(pcm_b64)
        except Exception:
            logger.warning(
                "Room %s: invalid base64 audio from uid=%d", self._room_code, user_id,
            )
            return

        # Normalise frame length
        if len(pcm) < FRAME_BYTES:
            pcm = pcm + b"\x00" * (FRAME_BYTES - len(pcm))
        elif len(pcm) > FRAME_BYTES:
            pcm = pcm[:FRAME_BYTES]

        username = ""
        with self._lock:
            buf = self._buffers.get(user_id)
            if buf is None:
                # Auto-register if the caller hasn't explicitly added the
                # participant yet (defensive).
                self._buffers[user_id] = deque(maxlen=10)
                buf = self._buffers[user_id]
            username = self._usernames.get(user_id, "")
            buf.append(pcm)

        # Feed STT (outside lock to avoid holding it during potentially
        # expensive work in the callback).
        if self._stt_feed is not None:
            try:
                self._stt_feed(user_id, username, pcm)
            except Exception:
                logger.debug("Room %s: stt_feed_fn error for uid=%d", self._room_code, user_id)

        # Lazy-start the mixer thread
        if not self._running:
            self.start()

    def has_participants(self) -> bool:
        """Return True if at least one jitter buffer exists."""
        with self._lock:
            return bool(self._buffers)

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background mixer thread (idempotent)."""
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(
            target=self._mixer_loop,
            name=f"mixer-{self._room_code}",
            daemon=True,
        )
        self._thread.start()
        logger.info("Room %s: mixer thread started", self._room_code)

    def stop(self) -> None:
        """Signal the mixer thread to stop and wait for it to finish."""
        self._running = False
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        logger.info("Room %s: mixer thread stopped", self._room_code)

    # ------------------------------------------------------------------
    # Mixer internals
    # ------------------------------------------------------------------

    def _mixer_loop(self) -> None:
        """Run the mixer at ~20 ms intervals until stopped."""
        tick = FRAME_DURATION_MS / 1000.0  # 0.020 s
        while self._running:
            t0 = time.monotonic()
            try:
                self._mix_tick()
            except Exception:
                logger.exception("Room %s: error in mixer tick", self._room_code)
            elapsed = time.monotonic() - t0
            sleep_time = tick - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    def _mix_tick(self) -> None:
        """Pull one frame from each non-empty buffer and distribute mixes."""
        # --- snapshot under lock ---
        with self._lock:
            pulled: dict[int, bytes] = {}
            for uid, buf in self._buffers.items():
                if buf:
                    pulled[uid] = buf.popleft()

        if not pulled:
            return

        # --- send personalised mixes (no lock needed) ---
        clients = self._get_clients()
        for recipient_uid, handler in clients.items():
            # Collect frames from everyone *except* the recipient
            others = [frame for uid, frame in pulled.items() if uid != recipient_uid]
            if not others:
                continue
            mixed = self._mix_frames(others)
            try:
                handler.send(PacketType.MIXED_AUDIO, {
                    "room_code": self._room_code,
                    "pcm_b64": base64.b64encode(mixed).decode("ascii"),
                    "sample_rate": SAMPLE_RATE,
                    "channels": CHANNELS,
                    "sample_width": SAMPLE_WIDTH,
                })
            except Exception:
                logger.debug(
                    "Room %s: failed to send mixed audio to uid=%d",
                    self._room_code, recipient_uid,
                )

    @staticmethod
    def _mix_frames(frames: list[bytes]) -> bytes:
        """Sum PCM int16 frames with clipping to [-32768, 32767].

        Each frame is expected to be ``FRAME_BYTES`` bytes of signed
        little-endian 16-bit samples.
        """
        if len(frames) == 1:
            return frames[0]

        num_samples = FRAME_SIZE
        fmt = f"<{num_samples}h"
        mixed = [0] * num_samples

        for frame in frames:
            try:
                samples = struct.unpack(fmt, frame)
            except struct.error:
                # Frame is the wrong length — skip it
                continue
            for i in range(num_samples):
                mixed[i] += samples[i]

        # Clip to int16 range
        for i in range(num_samples):
            if mixed[i] > 32767:
                mixed[i] = 32767
            elif mixed[i] < -32768:
                mixed[i] = -32768

        return struct.pack(fmt, *mixed)
