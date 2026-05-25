# English Subtitle Translation

## What Was Done
Added an English subtitle translation mode for the Whisper subtitle worker. The server now reads `QUICKONNECT_STT_TASK`, which can be `transcribe` for same-language captions or `translate` for English captions. The client marks translated subtitle lines with `→ EN`.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Modified | Passes `task=transcribe/translate` into `faster-whisper` and includes the task in subtitle payloads and logs. |
| `client/ui/audio_widget.py` | Modified | Labels translated subtitle lines so users can distinguish English translation from same-language transcription. |
| `docs/19_english_subtitle_translation.md` | Created | Documents this translation feature. |

## Why It Matters
The demo can now show both real-time speech recognition and English subtitle translation without adding an external translation API. This keeps the feature local and easier to run in a classroom or LAN setting while still demonstrating a more advanced audio pipeline.
