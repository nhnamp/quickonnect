"""Server-side audio mixing and optional subtitle transcription.

The mixer receives 20 ms PCM frames from each participant in a room, keeps a
small jitter buffer per sender, and emits one mixed frame per recipient. Each
recipient gets a mix of everyone else, which avoids echoing a user's own mic
back to them.
"""

from __future__ import annotations

import base64
import logging
import os
import queue
import struct
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from shared.constants import PacketType

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2
FRAME_MS = 20
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_MS // 1000
BYTES_PER_FRAME = SAMPLES_PER_FRAME * SAMPLE_WIDTH
MAX_BUFFERED_FRAMES = 12


@dataclass
class AudioFrame:
    user_id: int
    username: str
    seq: int
    timestamp_ms: int
    pcm: bytes


class AudioRoomState:
    """Thread-safe audio state for one active room."""

    def __init__(self, room_code: str, get_clients: Callable[[str], dict[int, object]]):
        self._room_code = room_code
        self._get_clients = get_clients
        self._buffers: dict[int, deque[AudioFrame]] = defaultdict(deque)
        self._speaking: dict[int, bool] = {}
        self._lock = threading.Lock()
        self._running = True
        self._mixer_thread = threading.Thread(
            target=self._mix_loop,
            name=f"audio-mixer-{room_code}",
            daemon=True,
        )
        self._subtitles = SubtitleWorker(room_code, get_clients)
        self._mixer_thread.start()
        self._subtitles.start()

    def stop(self) -> None:
        self._running = False
        self._subtitles.stop()

    def set_speaking(self, user_id: int, enabled: bool) -> None:
        with self._lock:
            self._speaking[user_id] = enabled
            if not enabled:
                self._buffers.pop(user_id, None)
                self._subtitles.clear_user(user_id)

    def remove_user(self, user_id: int) -> None:
        with self._lock:
            self._speaking.pop(user_id, None)
            self._buffers.pop(user_id, None)
        self._subtitles.clear_user(user_id)

    def add_chunk(self, frame: AudioFrame) -> None:
        if len(frame.pcm) != BYTES_PER_FRAME:
            logger.debug(
                "Dropping audio frame from %s in %s: expected %d bytes, got %d",
                frame.username,
                self._room_code,
                BYTES_PER_FRAME,
                len(frame.pcm),
            )
            return
        with self._lock:
            if not self._speaking.get(frame.user_id, True):
                return
            buf = self._buffers[frame.user_id]
            buf.append(frame)
            while len(buf) > MAX_BUFFERED_FRAMES:
                buf.popleft()
        self._subtitles.add_chunk(frame)

    def _mix_loop(self) -> None:
        next_tick = time.monotonic()
        while self._running:
            next_tick += FRAME_MS / 1000.0
            frames = self._pop_frames()
            if frames:
                self._send_mixes(frames)
            sleep_for = next_tick - time.monotonic()
            if sleep_for > 0:
                time.sleep(sleep_for)
            else:
                next_tick = time.monotonic()

    def _pop_frames(self) -> dict[int, AudioFrame]:
        with self._lock:
            out: dict[int, AudioFrame] = {}
            for uid, buf in list(self._buffers.items()):
                if buf:
                    out[uid] = buf.popleft()
            return out

    def _send_mixes(self, frames: dict[int, AudioFrame]) -> None:
        clients = self._get_clients(self._room_code)
        timestamp_ms = int(time.time() * 1000)
        for recipient_id, handler in clients.items():
            source_frames = [
                frame.pcm for uid, frame in frames.items()
                if uid != recipient_id and self._speaking.get(uid, True)
            ]
            if not source_frames:
                continue
            mixed = mix_pcm16(source_frames)
            handler.send(PacketType.MIXED_AUDIO, {
                "room_code": self._room_code,
                "timestamp_ms": timestamp_ms,
                "sample_rate": SAMPLE_RATE,
                "channels": CHANNELS,
                "sample_width": SAMPLE_WIDTH,
                "pcm_b64": base64.b64encode(mixed).decode("ascii"),
            })


def mix_pcm16(frames: list[bytes]) -> bytes:
    """Average signed 16-bit little-endian PCM frames with clipping."""
    if not frames:
        return b""
    sample_count = min(len(frame) for frame in frames) // SAMPLE_WIDTH
    if sample_count <= 0:
        return b""

    totals = [0] * sample_count
    for frame in frames:
        samples = struct.unpack("<" + "h" * sample_count, frame[:sample_count * SAMPLE_WIDTH])
        for i, sample in enumerate(samples):
            totals[i] += sample

    divisor = max(1, len(frames))
    mixed = bytearray(sample_count * SAMPLE_WIDTH)
    for i, total in enumerate(totals):
        value = int(total / divisor)
        if value > 32767:
            value = 32767
        elif value < -32768:
            value = -32768
        struct.pack_into("<h", mixed, i * SAMPLE_WIDTH, value)
    return bytes(mixed)


class SubtitleWorker:
    """Optional local Whisper worker.

    Set QUICKONNECT_STT_ENABLED=1 to enable. If faster-whisper is unavailable,
    the audio path still works and subtitles are simply disabled.
    """

    def __init__(self, room_code: str, get_clients: Callable[[str], dict[int, object]]):
        self._room_code = room_code
        self._get_clients = get_clients
        self._enabled = os.environ.get("QUICKONNECT_STT_ENABLED", "0") == "1"
        self._model_name = os.environ.get("QUICKONNECT_STT_MODEL", "tiny")
        self._language = os.environ.get("QUICKONNECT_STT_LANGUAGE", "")
        self._task = os.environ.get("QUICKONNECT_STT_TASK", "transcribe").strip().lower()
        if self._task not in {"transcribe", "translate", "bilingual"}:
            logger.warning("Invalid QUICKONNECT_STT_TASK=%s; falling back to transcribe", self._task)
            self._task = "transcribe"
        self._window_seconds = _env_float("QUICKONNECT_STT_WINDOW_SECONDS", 5.0, minimum=1.0)
        self._beam_size = _env_int("QUICKONNECT_STT_BEAM_SIZE", 5, minimum=1)
        self._vad_filter = os.environ.get("QUICKONNECT_STT_VAD_FILTER", "1") != "0"
        self._initial_prompt = os.environ.get(
            "QUICKONNECT_STT_INITIAL_PROMPT",
            "The user may speak Vietnamese or English in a QuicKonNect audio call.",
        )
        self._window_bytes = int(SAMPLE_RATE * SAMPLE_WIDTH * self._window_seconds)
        self._buffers: dict[int, bytearray] = defaultdict(bytearray)
        self._names: dict[int, str] = {}
        self._lock = threading.Lock()
        self._jobs: queue.Queue[tuple[int, str, bytes]] = queue.Queue(maxsize=16)
        self._running = False
        self._thread: threading.Thread | None = None
        self._model = None

    def start(self) -> None:
        if not self._enabled:
            return
        logger.info(
            "Subtitles enabled for room %s: model=%s language=%s task=%s window=%.1fs beam=%d vad=%s",
            self._room_code,
            self._model_name,
            self._language or "auto",
            self._task,
            self._window_seconds,
            self._beam_size,
            self._vad_filter,
        )
        self._running = True
        self._thread = threading.Thread(target=self._loop, name=f"subtitle-{self._room_code}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def clear_user(self, user_id: int) -> None:
        with self._lock:
            self._buffers.pop(user_id, None)
            self._names.pop(user_id, None)

    def add_chunk(self, frame: AudioFrame) -> None:
        if not self._enabled:
            return
        job = None
        with self._lock:
            buf = self._buffers[frame.user_id]
            buf.extend(frame.pcm)
            self._names[frame.user_id] = frame.username
            if len(buf) >= self._window_bytes:
                job = (frame.user_id, frame.username, bytes(buf))
                buf.clear()
        if job is not None:
            try:
                self._jobs.put_nowait(job)
            except queue.Full:
                logger.debug("Subtitle queue full for room %s; dropping window", self._room_code)

    def _loop(self) -> None:
        try:
            from faster_whisper import WhisperModel
            import numpy as np
            self._model = WhisperModel(self._model_name, device="cpu", compute_type="int8")
        except Exception as exc:
            logger.warning("Subtitles disabled: faster-whisper could not start: %s", exc)
            self._enabled = False
            return

        while self._running:
            try:
                user_id, username, pcm = self._jobs.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                if self._task == "bilingual":
                    subtitle = self._transcribe_bilingual(samples)
                else:
                    subtitle = self._transcribe_single(samples, self._task)
                if not subtitle or not subtitle["text"]:
                    continue
                logger.info(
                    "Subtitle transcript room=%s speaker=%s language=%s task=%s text=%r translation=%r",
                    self._room_code,
                    username,
                    subtitle["language"],
                    subtitle["task"],
                    subtitle["text"],
                    subtitle.get("translation", ""),
                )
                self._broadcast(user_id, username, subtitle)
            except Exception:
                logger.exception("Subtitle transcription failed")

    def _transcribe_single(self, samples, task: str) -> dict | None:
        segments, info = self._model.transcribe(
            samples,
            language=self._language or None,
            task=task,
            vad_filter=self._vad_filter,
            beam_size=self._beam_size,
            initial_prompt=self._initial_prompt or None,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if not text:
            return None
        lang = _normalize_language(getattr(info, "language", "") or "")
        return {
            "task": task,
            "language": lang,
            "text": text,
            "lines": [{"lang": "en" if task == "translate" else lang, "text": text}],
        }

    def _transcribe_bilingual(self, samples) -> dict | None:
        original = self._transcribe_single(samples, "transcribe")
        if not original:
            return None

        source_lang = _normalize_language(original["language"])
        original_text = original["text"]
        if source_lang == "en":
            target_lang = "vi"
            translated = _translate_text(original_text, "en", "vi")
        else:
            target_lang = "en"
            translated = self._whisper_translate_to_english(samples)

        lines = [{"lang": source_lang, "text": original_text}]
        if translated:
            lines.append({"lang": target_lang, "text": translated})
        return {
            "task": "bilingual",
            "language": source_lang,
            "text": original_text,
            "translation": translated,
            "target_language": target_lang,
            "lines": lines,
        }

    def _whisper_translate_to_english(self, samples) -> str:
        try:
            segments, _info = self._model.transcribe(
                samples,
                language=self._language or None,
                task="translate",
                vad_filter=self._vad_filter,
                beam_size=self._beam_size,
                initial_prompt=self._initial_prompt or None,
            )
            return " ".join(seg.text.strip() for seg in segments).strip()
        except Exception:
            logger.exception("Whisper English translation failed")
            return ""

    def _broadcast(self, user_id: int, username: str, subtitle: dict) -> None:
        payload = {
            "room_code": self._room_code,
            "speaker_user_id": user_id,
            "speaker_username": username,
            "text": subtitle["text"],
            "language": subtitle["language"],
            "translation": subtitle.get("translation", ""),
            "target_language": subtitle.get("target_language", ""),
            "lines": subtitle.get("lines", []),
            "task": subtitle["task"],
            "timestamp_ms": int(time.time() * 1000),
        }
        for handler in self._get_clients(self._room_code).values():
            handler.send(PacketType.SUBTITLE, payload)


def _normalize_language(language: str) -> str:
    value = (language or "").strip().lower()
    if value.startswith("en"):
        return "en"
    if value.startswith("vi"):
        return "vi"
    return value or "unknown"


def _translate_text(text: str, source: str, target: str) -> str:
    try:
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source=source, target=target).translate(text) or ""
    except Exception:
        logger.exception("Text translation failed from %s to %s", source, target)
        return ""


def _env_int(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _env_float(name: str, default: float, minimum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)
