# Bilingual Subtitle Display Order

## What Was Done
Updated bilingual subtitle output so the server sends a consistent two-line display order: English first, Vietnamese second. English speech is transcribed as the English line and translated into Vietnamese. Non-English speech in the classroom demo path is treated as Vietnamese, then translated into English, so the UI can still show a clear `en:` and `vi:` pair.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Modified | Changed bilingual subtitle line ordering to always emit `en` then `vi`. |
| `testing.md` | Modified | Changed subtitle testing commands to use `QUICKONNECT_STT_TASK=bilingual` by default. |
| `docs/28_bilingual_subtitle_display_order.md` | Created | Documents this subtitle display update. |

## Why It Matters
The demo requirement is easier to understand when subtitles always appear in a predictable pair such as `en: Hello` and `vi: Xin chào`. A stable order also makes screenshots and live explanations clearer.
