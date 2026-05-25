# Bug Fix: Audio Device Startup Stability

## What Was Done
Changed the client audio engine so microphone and speaker streams are opened during the Join Audio action before capture/playback worker threads are started. If the local audio device cannot be opened, the UI can show a clear warning instead of letting the background audio threads fail unpredictably.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/features/audio_engine.py` | Modified | Opens PyAudio input/output streams up front, reuses them from worker threads, and closes audio resources during stop. |
| `docs/17_bugfix_audio_device_startup_stability.md` | Created | Documents this audio stability fix. |

## Why It Matters
Bluetooth headsets and Windows audio devices can behave inconsistently when input and output streams are opened in parallel from separate threads. Opening the devices first makes Join Audio more predictable and gives users a normal error message if the microphone or speaker is unavailable.
