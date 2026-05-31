# Audio Engine Stop Stability

## What Was Done
Adjusted audio shutdown to wait for capture and playback threads to finish before terminating the PyAudio instance.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/features/audio_engine.py` | Modified | Avoid terminating PyAudio while streams are active. |
| `docs/11_audio_engine_stop_fix.md` | Created | Document this fix. |

## Why It Matters
Terminating PyAudio while streams are still active can crash the process on macOS. Waiting for threads to exit allows streams to close cleanly and prevents the trace trap.
