# Subtitle Silence Filtering

## What Was Done
Improved subtitle stability by filtering quiet audio windows before sending them to Whisper. The subtitle worker now checks normalized RMS volume and peak amplitude, then skips windows that are likely silence or background noise. The default Whisper initial prompt was also changed to empty text so the model does not hallucinate the prompt when the microphone signal is too weak.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Modified | Added `QUICKONNECT_STT_MIN_RMS` and `QUICKONNECT_STT_MIN_PEAK` thresholds, logged the active thresholds, skipped quiet subtitle windows, and removed the non-empty default initial prompt. |
| `docs/21_subtitle_silence_filtering.md` | Created | Documents this subtitle reliability fix. |

## Why It Matters
Speech-to-text models can invent text when they receive silence or very weak microphone input. That is especially visible when an initial prompt is present, because the model may repeat the prompt instead of transcribing real speech. Filtering quiet windows makes subtitles more predictable during live audio tests and reduces confusing repeated lines.
