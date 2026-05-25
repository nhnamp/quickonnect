# Phase 3: Audio Streaming & Subtitles

## What Was Built

Phase 3 adds real-time voice chat, server-side audio mixing, automated Speech-to-Text (STT) transcription, and subtitle relaying (with optional LibreTranslate translation) to QuicKonNect call rooms.

Concretely, the following features are live end-to-end:
- **Audio Capture and Playback**: The client-side `AudioEngine` uses `PyAudio` to capture raw mono PCM audio from the user's microphone at 16 kHz, 16-bit, in 20 ms frames (320 samples per frame). A background playback thread consumes mixed audio and writes it to the user's speakers.
- **Server-Side Audio Mixing**: The server-side `AudioMixerState` maintains jitter buffers (bounded to 10 frames to absorb network variance) for each participant. A background mixing thread runs at a fixed 20 ms tick, pulls the latest frame from each buffer, mixes them together (excluding the recipient's own audio to prevent echo), normalizes the samples with clipping protection, and broadcasts the mixed audio back to the clients.
- **Microphone Control**: Users can mute/unmute their microphone directly from the Screen Share / Call Room UI. Muted states cease packet transmission to conserve network bandwidth.
- **Speech-to-Text (STT) Transcription**: When `ENABLE_STT=1` is set in the server's environment, the server-side `STTManager` accumulates 3 seconds of raw PCM audio per speaker and submits it to a thread pool where `faster-whisper` (the `small` model running locally on CPU/int8) generates a transcript.
- **Live Translation**: When `LIBRETRANSLATE_URL` is set, transcripts are translated using a self-hosted LibreTranslate instance before broadcasting.
- **Subtitle Overlay**: The client-side `SubtitleWidget` displays speaker transcripts (and translations) in a sleek, semi-transparent black overlay parented to the screen share view, auto-hiding after 5 seconds of silence.

---

## Files Created / Modified

### Server

| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Created | Manages per-client jitter buffers, mixes other participants' audio (clipping-aware), and runs the 20 ms mixing thread. |
| `server/features/stt_worker.py` | Created | Buffers raw PCM per speaker and runs CPU-friendly Whisper transcription lazily. |
| `server/features/subtitle.py` | Created | Relays transcripts to room participants with optional LibreTranslate POST translation. |
| `server/room_manager.py` | Modified | Links the room lifecycle to its audio mixing, STT, and subtitle pipelines; cleans up audio threads on room destruction. |
| `server/client_handler.py` | Modified | Registers the `AUDIO_CHUNK` packet handler, routes incoming audio, and triggers cleanup. |

### Client

| File | Action | Purpose |
|------|--------|---------|
| `client/features/audio_engine.py` | Created | Background thread-driven mic capturer and speaker writer using PyAudio. |
| `client/ui/subtitle_widget.py` | Created | Overlay widget displaying transcriptions dynamically. |
| `client/ui/screen_share_widget.py` | Modified | Houses the mute button, starts/stops client audio engine, and hosts the subtitle overlay. |
| `client/ui/main_window.py` | Modified | Routes `MIXED_AUDIO` and `SUBTITLE` packets to the screen share view. |

### Testing

| File | Action | Purpose |
|------|--------|---------|
| `tests/test_audio_mixer.py` | Created | Unit tests verifying buffer size normalization, correct receiver exclusion, and sample clipping. |
| `tests/test_subtitle_stt.py` | Created | Unit tests verifying STT accumulation gating, Whisper ThreadPool submission, and translation fallbacks. |

---

## How Phase 3 Connects to Phase 1 & 2

- **Room Boundaries**: Jitter buffering, mixing, and STT are scoped strictly per room. When a participant joins a room, their client handler hooks into that room's specific `AudioMixerState`. Leaving the room automatically disconnects them from the mixer, avoiding cross-talk or processing dead streams.
- **Connection Pipeline**: All audio chunks, mixed audio, and subtitle packets reuse the same encrypted TCP connection from Phase 1. Packet queues and locks protect transport integrity.
- **Call UI Integration**: The audio controls and subtitle overlays reside directly inside the Screen Share widget built in Phase 2, keeping call-related interactions centralized.

---

## Key Decisions

1. **Uncompressed PCM over LAN**: Instead of integrating `opuslib` (which requires native `libopus` binaries, which are notoriously difficult to configure portably on different developer machines), raw 16 kHz mono PCM is transported. At 32 KB/s (256 kbps) per client, LAN bandwidth is more than sufficient, avoiding fragile dependencies.
2. **Lazy-loading STT**: To prevent loading heavy ML libraries if STT is disabled, `faster-whisper` modules are only imported when first requested, and the Whisper model itself is loaded lazily on the first transcription task.
3. **Double-buffered thread pool for STT**: Since speech-to-text can be slower than real-time on CPU, a thread pool with 2 workers isolates transcription from the main network loop, ensuring transcription delays never bottleneck client packet handling.

---

## Threading Summary

| Thread | Lives in | Responsibilities |
|---|---|---|
| Mic Capture Thread | `AudioEngine._capture_loop` | Reads PyAudio mic → base64 → sends `AUDIO_CHUNK`. |
| Speaker Playback Thread | `AudioEngine._playback_loop` | Consumes playback queue → writes to PyAudio speakers. |
| Server Mixing Thread | `AudioMixerState._mixer_loop` | Runs 20 ms ticks → mixes audio → sends `MIXED_AUDIO`. |
| STT Worker Pool | `STTManager._pool` | Transcribes wav bytes using local Whisper. |

---

## Verification

- **Automated Tests**: Running `py -m pytest` executes 49 unit tests covering cryptographic protocols, packet envelopes, audio mixing, STT queuing, and translation requests.
- **Mute Functionality**: Mute toggles immediately stop client capturing and network transmission, while unmute resumes capturing seamlessly.
