# Remove Screen And Remote Code

## What Was Done
Removed the active screen sharing and remote control feature code so the current project scope focuses on audio streaming, bilingual subtitles, chat, rooms, friends, and the networking foundation.

The audio path was kept intact: `AUDIO_CHUNK`, `MIXED_AUDIO`, and `SUBTITLE` packet types remain, and the client Audio tab is still wired to the room lifecycle.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/main_window.py` | Modified | Removed the Screen sidebar tab, screen widget wiring, screen packet dispatch, and screen shutdown calls. |
| `client/features/screen_engine.py` | Deleted | Removed client-side screen capture and JPEG frame sending code. |
| `client/features/remote_control.py` | Deleted | Removed client-side remote input capture and host-side input execution code. |
| `client/ui/screen_share_widget.py` | Deleted | Removed the Screen tab UI. |
| `server/client_handler.py` | Modified | Removed `SCREEN_*` and `REMOTE_*` dispatch handlers and cleanup logic. |
| `server/room_manager.py` | Modified | Removed per-room screen relay state. |
| `server/features/screen_relay.py` | Deleted | Removed server-side screen sharing and remote control state. |
| `shared/constants.py` | Modified | Removed screen and remote packet types. |
| `requirements.txt` | Modified | Removed `mss` and `pyautogui`, which were only used by screen sharing and remote control. |
| `scripts/check_e2e_readiness.py` | Modified | Removed screen/remote-only dependencies from readiness checks. |
| `README.md` | Modified | Updated the feature summary and demo checklist to match the current audio-focused source. |
| `docs/33_remove_screen_remote_code.md` | Created | Documents this cleanup step. |

## Why It Matters
Removing unused screen and remote-control code keeps the repository aligned with the user's assigned part. It also reduces demo confusion: the visible client now presents only Chat, Friends, and Audio, while the server only keeps room/chat/friend/audio packet handling.

This cleanup does not change how audio works. Microphone PCM frames still go to the server, the server still mixes room audio, and subtitles/translations still travel as separate `SUBTITLE` packets.
