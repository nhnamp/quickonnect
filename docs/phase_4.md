# Phase 4: Collaborative Whiteboard

## What Was Built

Phase 4 adds a real-time collaborative vector graphics whiteboard to QuicKonNect call rooms. This allows participants in the same room to draw, write text, undo/redo actions, see updates in real-time, synchronize canvas state upon joining, and export the canvas as a PNG file.

Concretely, the following features are live end-to-end:
- **Vector Canvas**: A fixed aspect-ratio `1920x1080` canvas (`WhiteboardScene` built on `QGraphicsScene`) that fits and scales inside the client's screen-sharing area.
- **Drawing Tools**: Supports Pen (freehand), Rectangle, Oval, Text (with interactive input dialog), and Eraser (which matches the dark-theme canvas color `#1e1e1e`).
- **Tool Options**: Features preset color buttons (White, Red, Green, Blue, Yellow), a custom system color picker, and a stroke width slider (1–20px).
- **Real-Time Vector Sync**: Every finalized shape is transmitted to the server as a `DRAW_EVENT` packet, assigned a canonical sequence number by the server, and broadcast to all room clients as a `DRAW_BROADCAST` packet.
- **Idempotency & Replay Protection**: Events carry a unique `client_event_id` to prevent duplicate processing on the server. On the client, rendering a sequence number first deletes any existing graphics item matching that sequence (`remove_item`), preventing duplicate overlay layers or visual clutter during connection recovery replays.
- **Dynamic Undo/Redo (Undo-the-Undo)**: Redo is modeled as undoing an undo event. The server-side `WhiteboardState` resolves active canvas elements dynamically using a reverse-traversal algorithm that handles nested undo/redo actions of arbitrary depth.
- **Periodic Snapshotting**: A background loop in the active room's `WhiteboardState` takes a snapshot of the whiteboard every 60 seconds by rendering the active vector items offscreen onto a `QImage`, saving it to PostgreSQL as a PNG byte array (`BYTEA`), and pruning the baked-in events from the in-memory cache to prevent memory bloat.
- **Late-Joiner Synchronization**: When a client joins a room, it receives a `WHITEBOARD_SYNC` packet containing the base64-encoded latest snapshot and subsequent active events. The client applies the snapshot as a background pixmap (`zValue = -1000`) and replays the subsequent drawing events on top of it.
- **Client-Side Export**: The toolbar's "Save PNG" button exports the high-resolution vector whiteboard client-side using `QGraphicsScene.render()` onto a local `QImage`, avoiding network transport and server CPU spikes.

---

## Files Created / Modified

### Server

| File | Action | Purpose |
|------|--------|---------|
| `server/features/whiteboard.py` | Created | Manages per-room whiteboard state, database queries/inserts, sequence management, reentrant lock protection, and offscreen `QImage` PNG rendering. |
| `server/room_manager.py` | Modified | Initializes `WhiteboardState` when a room is created, and stops the periodic snapshot background thread on room destruction. |
| `server/client_handler.py` | Modified | Registers `DRAW_EVENT` and `EXPORT_REQUEST` packet handlers, broadcasts events, and sends `WHITEBOARD_SYNC` upon room join. |
| `scripts/setup_db.py` | Modified | Defines the schema for `whiteboard_events` and `whiteboard_snapshots` PostgreSQL tables. |

### Client

| File | Action | Purpose |
|------|--------|---------|
| `client/features/whiteboard_engine.py` | Created | Handles formatting and sending drawing events and export requests over TCP. |
| `client/ui/whiteboard_widget.py` | Created | Drawing toolbar and vector canvas view utilizing PyQt6's `QGraphicsView` and `QGraphicsScene`. Handles local undo/redo stacks. |
| `client/ui/screen_share_widget.py` | Modified | Integrates the stacked whiteboard view, toolbar toggle button, local PNG export logic, and incoming packet routing slots. |
| `client/ui/main_window.py` | Modified | Routes `DRAW_BROADCAST`, `DRAW_ACK`, `WHITEBOARD_SYNC`, and `FILE_TRANSFER` packets to the screen share view. |

### Testing

| File | Action | Purpose |
|------|--------|---------|
| `tests/test_whiteboard.py` | Created | Unit tests verifying sequence numbering, dynamic undo/redo calculations, and offscreen rendering. |

---

## How Phase 4 Connects to Previous Phases

- **Room Boundaries**: Whiteboard states, snaps, and client drawing broadcasts are scoped strictly per room. When a participant joins a room, their client handler hooks into that room's specific `WhiteboardState`. Leaving the room triggers cleanup when the room becomes empty.
- **Connection Pipeline**: All drawing events, acknowledgments, synchronizations, and exports reuse the same encrypted TCP connection from Phase 1.
- **Stacked Interface**: The whiteboard canvas sits alongside the screen share frame in a `QStackedWidget` managed within the Phase 2 screen-sharing widget. Toggling the whiteboard button switches views cleanly without interrupting ongoing audio streaming or active session metrics.

---

## Key Decisions

1. **Preview-Only Optimistic Rendering**: To avoid visual lag or client-side divergence on sequence collision, clients only draw a temporary dotted preview shape during active mouse dragging. The final solid shape is only drawn when the server broadcasts the event with its canonical `seq_num`, keeping all participants synchronized.
2. **Reentrant Lock (`threading.RLock`) on Server**: The `WhiteboardState` uses an `RLock` to allow the owner thread to acquire the lock multiple times recursively (e.g., when calling `get_active_events()` inside another locked method like `load_from_db()`), eliminating potential deadlocks.
3. **Database-Bake Snapshot Pruning**: Events that are successfully saved to the 60s snapshot are pruned from the server's in-memory event cache. This keeps memory usage flat regardless of how long the room is open.

---

## Verification

- **Automated Tests**: Running `pytest -v tests/test_whiteboard.py` runs all 4 unit tests covering sequence numbering, database mocking, undo filtering, and offscreen QImage PNG exports.
- **Full Suite**: The complete 53 unit tests in the project pass successfully.
