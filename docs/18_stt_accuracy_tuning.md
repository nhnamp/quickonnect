# STT Accuracy Tuning

## What Was Done
Improved the subtitle worker configuration so speech-to-text accuracy can be tuned without code changes. The server now supports configurable subtitle window length, beam search size, VAD filtering, language forcing, and an initial prompt. Transcript output is also written to the server log for easier debugging.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Modified | Added STT tuning environment variables and transcript logging. |
| `docs/18_stt_accuracy_tuning.md` | Created | Documents this subtitle accuracy improvement. |

## Why It Matters
The previous default used a tiny model with automatic language detection and a short audio window. That is fast, but it can misrecognize Vietnamese speech. Exposing these settings lets the team choose between speed and accuracy for the demo machine instead of accepting one fixed behavior.
