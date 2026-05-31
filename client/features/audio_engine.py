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
import struct
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
        self._input_device_index: int | None = None
        self._output_device_index: int | None = None
        self._input_rate = SAMPLE_RATE
        self._output_rate = SAMPLE_RATE
        self._capture_chunk_size = CHUNK_SIZE
        self._playback_chunk_size = CHUNK_SIZE

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

        ok, error = self._preflight_streams()
        if not ok:
            try:
                self._pa.terminate()
            except Exception:
                logger.debug("PyAudio terminate error after failed preflight (ignored)")
            self._pa = None
            return False, error

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

        # Let worker threads close their streams before terminating PyAudio.
        if self._capture_thread is not None:
            self._capture_thread.join(timeout=1.5)
        if self._playback_thread is not None:
            self._playback_thread.join(timeout=1.5)

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

        self._capture_thread = None
        self._playback_thread = None

        logger.info("AudioEngine stopped")

    def _preflight_streams(self) -> tuple[bool, str | None]:
        """Verify microphone and speaker streams can open before claiming success.

        Linux audio stacks frequently expose default devices whose native rate is
        44.1/48 kHz rather than this app's network rate of 16 kHz. We choose a
        usable device/rate pair and resample at the client boundary so the wire
        protocol still carries stable 16 kHz mono PCM.
        """
        try:
            import pyaudio
        except Exception as exc:
            return False, f"PyAudio import failed: {exc}"

        input_stream = None
        output_stream = None
        try:
            input_stream, input_rate, input_index, input_name = self._open_best_stream(
                pyaudio, is_input=True,
            )
            output_stream, output_rate, output_index, output_name = self._open_best_stream(
                pyaudio, is_input=False,
            )
            self._input_device_index = input_index
            self._output_device_index = output_index
            self._input_rate = input_rate
            self._output_rate = output_rate
            self._capture_chunk_size = self._frames_per_packet(input_rate)
            self._playback_chunk_size = self._frames_per_packet(output_rate)
            logger.info(
                "Audio preflight succeeded: input=%s rate=%d output=%s rate=%d",
                input_name, input_rate, output_name, output_rate,
            )
            return True, None
        except Exception as exc:
            logger.error("Audio preflight failed: %s", exc)
            return False, f"Microphone or speaker unavailable: {exc}"
        finally:
            for stream in (input_stream, output_stream):
                if stream is None:
                    continue
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    logger.debug("Error closing preflight audio stream (ignored)")

    def _open_best_stream(self, pyaudio_module, *, is_input: bool):
        """Open the first usable mono int16 stream for input or output.

        Returns ``(stream, rate, device_index, device_name)``.
        """
        direction = "input" if is_input else "output"
        for info in self._candidate_devices(is_input):
            device_index = int(info.get("index"))
            device_name = str(info.get("name", f"{direction}-{device_index}"))
            for rate in self._candidate_rates(info):
                kwargs = {
                    "format": pyaudio_module.paInt16,
                    "channels": CHANNELS,
                    "rate": rate,
                    "frames_per_buffer": self._frames_per_packet(rate),
                }
                if is_input:
                    kwargs["input"] = True
                    kwargs["input_device_index"] = device_index
                else:
                    kwargs["output"] = True
                    kwargs["output_device_index"] = device_index
                try:
                    stream = self._pa.open(**kwargs)
                    logger.debug(
                        "Opened %s audio device index=%d name=%s rate=%d",
                        direction, device_index, device_name, rate,
                    )
                    return stream, rate, device_index, device_name
                except Exception as exc:
                    logger.debug(
                        "Audio %s candidate failed index=%d name=%s rate=%d: %s",
                        direction, device_index, device_name, rate, exc,
                    )

        raise RuntimeError(f"No usable {direction} audio device found")

    def _candidate_devices(self, is_input: bool) -> list[dict]:
        devices: list[dict] = []
        seen: set[int] = set()

        try:
            default = (
                self._pa.get_default_input_device_info()
                if is_input
                else self._pa.get_default_output_device_info()
            )
            index = int(default.get("index"))
            devices.append(default)
            seen.add(index)
        except Exception as exc:
            logger.warning(
                "No default %s audio device reported: %s",
                "input" if is_input else "output",
                exc,
            )

        try:
            count = self._pa.get_device_count()
        except Exception:
            count = 0

        channel_key = "maxInputChannels" if is_input else "maxOutputChannels"
        for index in range(count):
            try:
                info = self._pa.get_device_info_by_index(index)
            except Exception:
                continue
            if int(info.get(channel_key, 0)) < 1 or int(info.get("index", index)) in seen:
                continue
            devices.append(info)
            seen.add(int(info.get("index", index)))

        logger.info(
            "Found %d candidate %s audio devices",
            len(devices), "input" if is_input else "output",
        )
        return devices

    @staticmethod
    def _candidate_rates(device_info: dict) -> list[int]:
        rates: list[int] = []
        for rate in (
            SAMPLE_RATE,
            int(float(device_info.get("defaultSampleRate", SAMPLE_RATE) or SAMPLE_RATE)),
            48000,
            44100,
        ):
            if rate > 0 and rate not in rates:
                rates.append(rate)
        return rates

    @staticmethod
    def _frames_per_packet(rate: int) -> int:
        return max(1, int(rate * FRAME_DURATION_MS / 1000))

    @staticmethod
    def _fit_pcm_frame(pcm_data: bytes, target_bytes: int = CHUNK_SIZE * SAMPLE_WIDTH) -> bytes:
        if len(pcm_data) < target_bytes:
            return pcm_data + b"\x00" * (target_bytes - len(pcm_data))
        if len(pcm_data) > target_bytes:
            return pcm_data[:target_bytes]
        return pcm_data

    @staticmethod
    def _resample_pcm_mono16(pcm_data: bytes, source_rate: int, target_rate: int) -> bytes:
        """Linearly resample little-endian mono int16 PCM.

        This avoids relying on the removed stdlib ``audioop`` module and keeps
        the app portable on Python 3.14+.
        """
        if source_rate == target_rate or not pcm_data:
            return pcm_data
        if len(pcm_data) % SAMPLE_WIDTH:
            pcm_data = pcm_data[:-1]
        if not pcm_data:
            return b""

        sample_count = len(pcm_data) // SAMPLE_WIDTH
        samples = struct.unpack(f"<{sample_count}h", pcm_data)
        target_count = max(1, int(round(sample_count * target_rate / source_rate)))
        ratio = source_rate / target_rate
        out: list[int] = []

        for i in range(target_count):
            pos = i * ratio
            left = int(pos)
            if left >= sample_count - 1:
                out.append(samples[-1])
                continue
            frac = pos - left
            value = int(samples[left] * (1.0 - frac) + samples[left + 1] * frac)
            if value > 32767:
                value = 32767
            elif value < -32768:
                value = -32768
            out.append(value)

        return struct.pack(f"<{len(out)}h", *out)

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
                rate=self._input_rate,
                input=True,
                input_device_index=self._input_device_index,
                frames_per_buffer=self._capture_chunk_size,
            )
            logger.info(
                "Capture stream opened device=%s rate=%d chunk=%d",
                self._input_device_index, self._input_rate, self._capture_chunk_size,
            )
        except Exception as exc:
            logger.error("Cannot open microphone: %s", exc)
            return

        try:
            while self._running:
                try:
                    pcm_data = stream.read(self._capture_chunk_size, exception_on_overflow=False)
                except Exception:
                    if self._running:
                        logger.warning("Mic read error — skipping frame")
                    continue

                if self.is_muted():
                    continue

                if self._input_rate != SAMPLE_RATE:
                    try:
                        pcm_data = self._resample_pcm_mono16(
                            pcm_data, self._input_rate, SAMPLE_RATE,
                        )
                    except Exception:
                        logger.warning("Mic resample error — skipping frame")
                        continue
                pcm_data = self._fit_pcm_frame(pcm_data)

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
                rate=self._output_rate,
                output=True,
                output_device_index=self._output_device_index,
                frames_per_buffer=self._playback_chunk_size,
            )
            logger.info(
                "Playback stream opened device=%s rate=%d chunk=%d",
                self._output_device_index, self._output_rate, self._playback_chunk_size,
            )
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
                    if self._output_rate != SAMPLE_RATE:
                        pcm_data = self._resample_pcm_mono16(
                            pcm_data, SAMPLE_RATE, self._output_rate,
                        )
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
