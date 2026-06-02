# Remove Whiteboard Code

## What Was Done
Removed the collaborative whiteboard feature from the active source code. The current app no longer creates a Whiteboard tab, no longer sends or handles whiteboard packet types, and no longer creates the `whiteboard_events` database table during setup.

The audio translation path was kept intact: `AUDIO_CHUNK`, `MIXED_AUDIO`, and `SUBTITLE` packets are still present and the audio mixer/subtitle worker code was not removed.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/main_window.py` | Modified | Removed the Whiteboard tab, widget wiring, and whiteboard packet dispatch. |
| `client/features/whiteboard_engine.py` | Deleted | Removed client-side whiteboard helper code. |
| `client/ui/whiteboard_widget.py` | Deleted | Removed the whiteboard UI and canvas code. |
| `server/client_handler.py` | Modified | Removed draw/export packet handlers and whiteboard sync on room join. |
| `server/room_manager.py` | Modified | Removed per-room whiteboard state creation and lookup. |
| `server/features/whiteboard.py` | Deleted | Removed server-side whiteboard event state and persistence code. |
| `shared/constants.py` | Modified | Removed whiteboard-specific packet types. |
| `scripts/setup_db.py` | Modified | Removed the `whiteboard_events` table from schema setup. |
| `scripts/check_e2e_readiness.py` | Modified | Removed whiteboard files from required readiness checks. |
| `scripts/smoke_e2e_protocol.py` | Modified | Removed whiteboard draw/sync expectations from the protocol smoke test. |
| `tests/test_whiteboard.py` | Deleted | Removed tests for deleted whiteboard helpers. |
| `README.md` | Modified | Updated the feature list and verified unit test count. |
| `README_SETUP.md` | Modified | Updated the expected database table count. |
| `docs/31_remove_whiteboard_code.md` | Created | Documents this cleanup step. |

## Why It Matters
The project scope now matches the features being kept for the demo and report. Removing unused whiteboard code lowers the chance of stale UI buttons, missing packet handlers, or database tables causing confusion during testing.

This also keeps the audio translation feature isolated. The media path for microphone capture, server-side PCM mixing, subtitle generation, and bilingual subtitle display remains available for focused testing.
