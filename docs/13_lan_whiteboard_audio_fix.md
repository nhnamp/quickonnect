# LAN Whiteboard And Audio Fix

## What Was Done
Reviewed and fixed the LAN-critical paths for collaborative whiteboard events and microphone voice chat.

Whiteboard undo/redo broadcasts now include the server-canonical active event list, so every client can redraw to the same state after an undo or redo. The client applies that canonical list without clearing the user's local undo history. Additional whiteboard validation and debug logs were added around draw-event send, server receive, and client render paths.

Voice chat mixing now normalizes mixed samples by active speaker count before clipping. The client also preflights microphone and speaker stream startup before reporting audio as active, and the server rejects oversized audio frames and logs ignored audio for non-joined rooms, making LAN debugging clearer.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/audio_mixer.py` | Modified | Normalize mixed PCM by active speaker count and log queued audio frames. |
| `server/client_handler.py` | Modified | Validate audio and whiteboard packets, log routing decisions, and include canonical whiteboard state on undo broadcasts. |
| `client/features/audio_engine.py` | Modified | Preflight microphone and speaker streams so startup failures are visible instead of silent. |
| `client/ui/whiteboard_widget.py` | Modified | Add canonical whiteboard redraw support while preserving local undo/redo stacks. |
| `client/ui/screen_share_widget.py` | Modified | Log outgoing local draw events, apply canonical whiteboard state after undo/redo, and surface audio startup failures in the UI. |
| `tests/test_audio_mixer.py` | Modified | Update mixer tests to verify normalization rather than raw summing. |
| `tests/test_whiteboard.py` | Modified | Add coverage for undoing an undo restoring the original event. |
| `docs/13_lan_whiteboard_audio_fix.md` | Created | This document. |

## Why It Matters
Two users on separate LAN machines depend on both clients receiving the same room-scoped event stream. Drawing events were already broadcast, but undo/redo required more than a single "remove this item" action because redo is represented as undoing an undo. Sending the canonical active event list keeps all clients visually consistent.

For voice chat, raw summing can distort or clip audio when multiple people speak. Normalizing the mixed frame keeps volume predictable and makes the TCP audio path easier to validate during a two-machine LAN test.

## Manual LAN Verification
1. Start PostgreSQL, Redis, one or two chat servers, and the load balancer on the host machine.
2. On the second machine, connect the client to the host machine's LAN IP as the load balancer host.
3. Have User A create a regular room. Have User B join the same room code.
4. Open the Screen tab, enable Whiteboard on both clients, and draw pen, rectangle, oval, text, and eraser marks from each side. Confirm each action appears on the other client.
5. Use Undo and Redo from both clients. Confirm both whiteboards converge to the same visible state.
6. Keep both users in the same regular room and verify microphone permission is granted by the OS. Speak from User A and confirm User B hears audio; speak from User B and confirm User A hears audio.
7. Toggle Mute on one client and confirm that client stops transmitting while still receiving the other user's audio.
