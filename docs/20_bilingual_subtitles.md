# Bilingual Subtitles

## What Was Done
Added bilingual subtitle output for audio rooms. When `QUICKONNECT_STT_TASK=bilingual`, the server sends both the detected original transcription and a translated line. Vietnamese speech is shown as Vietnamese plus English. English speech is shown as English plus Vietnamese.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Modified | Added bilingual subtitle mode, language normalization, Whisper English translation, and English-to-Vietnamese text translation. |
| `client/ui/audio_widget.py` | Modified | Displays subtitle payloads with multiple language lines under the speaker name. |
| `requirements.txt` | Modified | Added `deep-translator` for English-to-Vietnamese subtitle translation. |
| `docs/20_bilingual_subtitles.md` | Created | Documents this subtitle improvement. |

## Why It Matters
Showing both the original speech and translated text makes the subtitle feature easier to verify during demos. It also supports the practical classroom case where speakers may switch between Vietnamese and English.
