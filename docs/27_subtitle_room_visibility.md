# Subtitle Room Visibility

## What Was Done
Adjusted the Audio tab subtitle display so incoming subtitle packets are shown even when their room code does not match the currently selected local room. If the packet room differs from the selected room, the UI appends the packet room code next to the speaker name.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/audio_widget.py` | Modified | Shows subtitle packets more reliably during demo testing and labels room mismatches. |
| `docs/27_subtitle_room_visibility.md` | Created | Documents this subtitle visibility update. |

## Why It Matters
During reconnects, redirects, or fast demo switching, the Audio tab can have a stale selected room while the server is still producing subtitle packets for the active audio room. Showing those packets makes debugging and live demos clearer instead of silently dropping subtitles.
