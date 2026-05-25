# Phase 3: Audio Streaming & Subtitles

## What Was Done
Implemented the first production-ready pass of Phase 3 audio calling. The application now has a dedicated Audio tab where a participant can join audio for the currently selected room, mute/unmute their microphone, hear a server-generated mix of other participants, and view subtitles when server-side STT is enabled.

The audio path uses 16 kHz, 16-bit, mono PCM frames at 20 ms per packet. This keeps the implementation reliable for LAN demos and avoids fragile codec setup on Windows while still exercising the custom TCP transport, encryption layer, per-room server state, and multi-threaded processing required by the course.

Implemented behavior:

- Client microphone capture runs on a background thread using PyAudio.
- Client playback runs on a separate background thread with a bounded playback queue.
- Audio packets reuse the existing encrypted TCP protocol through `AUDIO_CHUNK`.
- Server keeps one audio state per active room.
- Server keeps small per-user jitter buffers and mixes audio every 20 ms.
- Each recipient receives a mix of everyone else through `MIXED_AUDIO`, so users do not hear their own microphone echoed back.
- Mute/unmute is signaled to the server and clears stale sender buffers.
- Optional subtitle transcription is integrated through `faster-whisper`.
- Subtitles are disabled by default and can be enabled with `QUICKONNECT_STT_ENABLED=1`.
- If Whisper is not available or cannot start, audio still works and the server logs that subtitles are disabled.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Created | Per-room audio mixer, PCM mixing helper, jitter buffers, and optional Whisper subtitle worker. |
| `server/room_manager.py` | Modified | Creates and owns `AudioRoomState` alongside each active room, removes users from audio state on leave, and stops the mixer when a room becomes empty. |
| `server/client_handler.py` | Modified | Handles `AUDIO_CHUNK` packets, validates room membership, decodes PCM payloads, applies mute state, and forwards frames into the room mixer. |
| `client/features/audio_engine.py` | Created | PyAudio microphone capture, mixed-audio playback, mute signaling, bounded playback queue, and microphone level reporting. |
| `client/ui/audio_widget.py` | Created | Audio tab with join/leave audio, mute/unmute, microphone level meter, playback buffer status, and subtitle list. |
| `client/ui/main_window.py` | Modified | Adds the Audio sidebar tab, wires room selection into the audio widget, dispatches `MIXED_AUDIO` and `SUBTITLE`, and shuts audio threads down on logout/disconnect/close. |
| `requirements.txt` | Modified | Adds PyAudio for audio devices and faster-whisper for optional local subtitles. |
| `tests/test_audio_mixer.py` | Created | Unit tests for PCM frame mixing behavior. |
| `docs/07_phase_3_audio_streaming_and_subtitles.md` | Created | This documentation file. |

## Why It Matters
Phase 3 adds the missing real-time voice layer to the call experience. This is one of the strongest parts of the project from a network-programming perspective because it combines continuous TCP streaming, background capture/playback threads, per-room server processing, multi-client fanout, and encrypted packet transport.

The subtitle path is implemented as an optional real integration instead of placeholder logic. That means the team can run lighter demos with audio only, or enable local Whisper when the machine is strong enough and the model dependency has been installed.

## How To Use
1. Install dependencies from `requirements.txt`.
2. Start PostgreSQL, Redis, chat servers, load balancer, and clients as usual.
3. Join or create a room from the Chat tab.
4. Open the Audio tab.
5. Click **Join Audio**.
6. Use **Mute** / **Unmute** to control microphone sending.

To enable subtitles on the server:

```bash
QUICKONNECT_STT_ENABLED=1 QUICKONNECT_STT_MODEL=tiny python scripts/run_server.py 9001
```

On Windows PowerShell:

```powershell
$env:QUICKONNECT_STT_ENABLED = "1"
$env:QUICKONNECT_STT_MODEL = "tiny"
python scripts/run_server.py 9001
```

## Verification
- Python syntax compilation passed for the new and modified Phase 3 files.
- A direct smoke test verified that two PCM frames are mixed into the expected average output.
- Full pytest was not run because the current system Python does not have `pytest` installed and there is no local `.venv` in this workspace.

## Notes And Follow-Ups
- The current implementation sends raw PCM instead of Opus-compressed audio. This is acceptable for LAN demos and keeps the first audio version easier to install and debug. Opus can be added later if bandwidth becomes a problem.
- Subtitle latency depends on the local machine and Whisper model size. The default documented model is `tiny` because it is the most practical for classroom demos.
- A future hardening pass should add an end-to-end manual audio demo checklist with two or three machines on the same LAN.
