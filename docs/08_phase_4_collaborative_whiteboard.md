# Phase 4: Collaborative Whiteboard

## What Was Done
Implemented the first complete collaborative whiteboard pass. Participants in a room now have a Whiteboard tab where they can draw freehand strokes, rectangles, ovals, text, and eraser marks. Drawing actions are sent over the existing encrypted TCP connection, ordered by the server, persisted in PostgreSQL, and broadcast to every participant in the room.

Implemented behavior:

- Client whiteboard canvas with pen, rectangle, oval, text, eraser, stroke width, color picker, undo, clear, and PNG export.
- `DRAW_EVENT` packets from the client to the server.
- Server-side validation of whiteboard event payloads.
- Server-assigned `seq_num` for canonical draw ordering.
- Persistence to the existing `whiteboard_events` PostgreSQL table.
- `DRAW_BROADCAST` packets from the server to all room participants.
- `DRAW_ACK` response to the sender with the accepted server sequence number.
- `WHITEBOARD_SYNC` sent when a user joins a room so late joiners reconstruct the existing board.
- Undo implemented as a server-ordered `UNDO` event targeting a previous sequence number.
- Clear implemented as a server-ordered `CLEAR` event.
- PNG export implemented on the client from the currently rendered canvas.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/features/whiteboard.py` | Created | Per-room whiteboard event log, event validation, PostgreSQL persistence, DB reload, and sync payload generation. |
| `server/room_manager.py` | Modified | Creates a `WhiteboardState` for each active room and exposes it to packet handlers. |
| `server/client_handler.py` | Modified | Handles `DRAW_EVENT` and `EXPORT_REQUEST`; sends `WHITEBOARD_SYNC` after room join; broadcasts accepted draw events. |
| `client/features/whiteboard_engine.py` | Created | Small whiteboard event helper functions for packet creation, rectangle normalization, and undo target lookup. |
| `client/ui/whiteboard_widget.py` | Created | Whiteboard tab, canvas renderer, drawing tools, undo, clear, and PNG export UI. |
| `client/ui/main_window.py` | Modified | Adds the Whiteboard sidebar tab and dispatches `WHITEBOARD_SYNC`, `DRAW_BROADCAST`, and `FILE_TRANSFER` packets. |
| `tests/test_whiteboard.py` | Created | Unit tests for client-side whiteboard helper behavior. |
| `docs/08_phase_4_collaborative_whiteboard.md` | Created | This documentation file. |

## Why It Matters
This completes the third major feature area from the original project plan. The whiteboard is a strong network-programming feature because it demonstrates ordered event synchronization, server authority, multi-client broadcast, persistence, and late-join state reconstruction over the project's own TCP protocol.

The implementation also keeps the design simple enough for a course demo. Instead of synchronizing pixels, clients send compact vector-like events. This makes the network traffic small, keeps the server logic readable, and gives PostgreSQL a clean event history that can be replayed for new participants.

## How To Use
1. Start the normal infrastructure and app components.
2. Join or create a room from the Chat tab.
3. Open the Whiteboard tab.
4. Select a tool and draw on the canvas.
5. Other participants in the same room should see the drawing appear in the same order.
6. Use **Undo** to undo your last non-clear event.
7. Use **Clear** to clear the board for everyone.
8. Use **Export PNG** to save the current canvas as an image.

## Verification
- Python syntax compilation passed for the new and modified Phase 4 files.
- Direct whiteboard helper tests passed.
- Existing direct audio mixer smoke tests still passed.
- Full pytest was not run because the current system Python does not have `pytest` installed and there is no local `.venv` in this workspace.

## Notes And Follow-Ups
- PNG export is currently client-side. This is intentional for the first pass because the client already has a rendered Qt canvas, while server-side PNG rendering would add GUI/headless complexity to the server process.
- `EXPORT_REQUEST` currently returns the server event log through `FILE_TRANSFER`; the main user-facing export path is the client PNG export button.
- A polish pass should test two or three clients drawing at the same time on LAN and verify the replayed state after a late join.
