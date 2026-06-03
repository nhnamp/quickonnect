# Audio Widget Single Source

## What Was Done
Moved client-side audio ownership to one shared `AudioEngine` controlled by the Audio tab, removed audio and subtitle handling from the Screen tab, and disabled audio startup for `DM-` direct-message rooms.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/main_window.py` | Modified | Creates one shared `AudioEngine`, passes it to `AudioWidget`, and routes `MIXED_AUDIO` / `SUBTITLE` packets only to the Audio tab. |
| `client/ui/audio_widget.py` | Modified | Accepts the shared engine and blocks auto-start/manual start for `DM-` rooms because direct-message rooms may live on different servers. |
| `client/ui/screen_share_widget.py` | Modified | Removed the Screen tab's separate `AudioEngine`, mute button, mixed-audio playback, and subtitle overlay handling. |
| `docs/17_audio_widget_single_source.md` | Created | Documents this audio ownership change. |

## Why It Matters
The previous client created two independent audio engines: one in the Screen tab and one in the Audio tab. Both could capture the same microphone, send duplicate audio frames, open duplicate speaker streams, and expose mute controls that did not agree with each other. A single shared engine keeps microphone, playback, mute state, and diagnostics consistent.

Audio is also now limited to regular rooms. Regular rooms are pinned to one chat server, which is required because the mixer is server-local. Direct-message rooms are server-agnostic, so users in the same DM may be connected to different servers; enabling audio there would silently fail or behave inconsistently without a cross-server media relay.
