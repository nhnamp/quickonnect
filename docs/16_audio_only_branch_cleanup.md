# Audio-Only Branch Cleanup

## What Was Done
Removed the old screen sharing, remote control, camera, and whiteboard code paths from the current branch. The remaining feature scope is the network core plus room audio streaming, server-side audio mixing, speech-to-text, and subtitle translation.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/audio_widget.py` | Created | Adds a focused Audio tab for mixed audio playback and subtitles. |
| `client/ui/main_window.py` | Modified | Replaces the Screen tab routing with the Audio tab. |
| `server/client_handler.py` | Modified | Removes non-audio media packet handlers and keeps room/chat/friend/audio handling. |
| `server/room_manager.py` | Modified | Keeps only room participants and per-room audio state. |
| `shared/constants.py` | Modified | Removes packet types for screen, camera, remote control, and whiteboard. |
| `scripts/setup_db.py` | Modified | Removes whiteboard database tables from the setup schema. |
| `requirements.txt` | Modified | Removes dependencies used only by screen sharing and remote control. |

## Why It Matters
The new branch now represents the intended audio translation scope without carrying unrelated feature code. This keeps the pull request smaller and reduces merge conflicts because the branch starts from the latest main history and adds one focused cleanup commit.
