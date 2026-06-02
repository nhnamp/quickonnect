# Default Bilingual Subtitles

## What Was Done
Changed the audio subtitle worker so subtitles are enabled by default when the server has `faster-whisper` available. The default subtitle task is now bilingual, so audio rooms produce both English and Vietnamese lines without requiring manual environment variables.

The subtitle window now defaults to 4 seconds so the demo shows text sooner than the older 5-second window. The default silence thresholds were also lowered to make laptop microphones less likely to be rejected before transcription.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Modified | Enables subtitles by default, uses bilingual mode by default, keeps `QUICKONNECT_STT_ENABLED=0` as the opt-out switch, and logs subtitle windows for demo debugging. |
| `client/ui/audio_widget.py` | Modified | Updates the Audio tab hint so it no longer says subtitles require a manual server flag. |
| `scripts/check_e2e_readiness.py` | Modified | Reports the new default subtitle settings. |
| `README.md` | Modified | Documents the new default bilingual subtitle behavior. |
| `docs/32_default_bilingual_subtitles.md` | Created | Documents this configuration change. |

## Why It Matters
The audio demo should show subtitles and translation without the user remembering extra environment variables. This keeps the default run path aligned with the classroom test case: speak English or Vietnamese and display both `en:` and `vi:` lines in the Audio tab.

Audio streaming remains unchanged. The microphone still sends PCM frames, the server still mixes room audio, and subtitle packets are still broadcast separately as `SUBTITLE`.
