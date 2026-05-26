# Phase 2: Screen Sharing & Remote Control

## What Was Built

Phase 2 adds a complete screen-sharing pipeline and a remote-control workflow on top of the Phase 1 foundation. A new dedicated "Screen" tab in the desktop client lets any participant of a room share their screen at runtime-tunable resolution, FPS, and JPEG quality. Other participants in the same room see the share in real time. While a share is active, viewers can ask for remote control of the sharer's mouse and keyboard; the sharer is shown an explicit allow/deny prompt and can revoke control with one click at any time.

Concretely the following features are live end-to-end:

- A dedicated **Screen tab** alongside Chat and Friends, with a frame display, share / stop buttons, request-control / revoke buttons, and live sliders for FPS (5–30), JPEG quality (30–95) and capture scale (25%–100%).
- **Screen capture** with `mss`, JPEG encoding via `QImage` + `QBuffer` (no Pillow dependency), default 30 FPS native resolution with quality 70.
- **Capture and send live on separate threads** with a bounded 3-frame queue using drop-oldest semantics — the capture thread never blocks waiting for the network, and a slow receiver simply causes older frames to be skipped.
- **Server relays frames** through a per-room `ScreenRelayState`. The server never decodes the JPEG bytes; it only validates the sender, copies the payload, and fans it out as `SCREEN_RELAY` to every other room participant.
- **One-sharer-per-room** enforcement at the server. A `SCREEN_START` from someone while another share is active returns `ERROR 409`. The "Share Screen" button is disabled on every other client.
- **Remote control workflow**: `REMOTE_REQUEST` from a viewer is forwarded to the sharer, who sees a confirmation dialog. The server only forwards `REMOTE_EVENT` packets from the user the sharer explicitly granted. A single "Revoke Control" click on the sharer's UI sends `REMOTE_GRANT { granted=false }` which the server broadcasts so the controller's local input is disabled immediately.
- **Coordinate normalization** — viewers send normalized `(0.0–1.0)` x/y in `REMOTE_EVENT`, the sharer multiplies by their real screen size. This makes the controller's viewport size and the sharer's monitor resolution independent.
- **Host-side execution** runs `pyautogui` calls on a dedicated background thread fed by a queue, so the host UI never blocks while replaying events. `pyautogui.FAILSAFE` is disabled to avoid corner-of-screen aborts during a legitimate session.
- **Graceful cleanup** — if the sharer or controller disconnects (or explicitly leaves the room), the server stops the share / clears the grant and broadcasts the appropriate `SCREEN_STOP` / `REMOTE_GRANT(granted=false)` to the remaining members.
- **Late joiners** see the existing share immediately: when a client joins a room with an active share, the `ROOM_STATE` payload now carries a `screen` block with the current sharer (and controller, if any), so the Screen tab can render the next incoming frame without a separate setup packet.

## Files Created / Modified

### Server

- `server/features/screen_relay.py` — **created**. `ScreenRelayState`, a thread-safe per-room state object that tracks the current sharer and (optional) controller. Exposes idempotent `start_share / stop_share / set_controller / clear_controller_if / stop_if_sharer / get_state`, all guarded by an internal lock.
- `server/room_manager.py` — **modified**. Every newly-tracked room now also constructs a `ScreenRelayState` and stores it under `_rooms[room_code]["screen"]`. Added `get_screen_state(room_code)` for callers to fetch the state.
- `server/client_handler.py` — **modified**. Added six new dispatch handlers (`SCREEN_START`, `SCREEN_STOP`, `SCREEN_FRAME`, `REMOTE_REQUEST`, `REMOTE_GRANT`, `REMOTE_EVENT`) plus two small helpers (`_resolve_screen_room` and `_broadcast_to_room`). `_handle_join_room` now also includes any existing screen state in the outgoing `ROOM_STATE`. `_handle_leave_room` and `_cleanup` now stop the share / clear the controller and notify the remaining members before the participant is removed.

### Client

- `client/features/screen_engine.py` — **created**. `ScreenCaptureEngine` owns the capture thread (mss → QImage → JPEG-via-QBuffer) and the send thread that reads a bounded `deque` and pushes `SCREEN_FRAME` packets through `ConnectionManager.send`. Runtime tuning (`set_fps`, `set_quality`, `set_scale`) is thread-safe. Also exports a `decode_jpeg(b64)` helper that the screen widget uses on the UI thread to decode incoming `SCREEN_RELAY` frames.
- `client/features/remote_control.py` — **created**. `RemoteControlSender` is a Qt event filter installed on the frame display widget; it converts mouse / wheel / key events into `REMOTE_EVENT` packets with normalized coordinates and translates a curated set of Qt special keys into pyautogui key names. `RemoteControlExecutor` runs a dedicated worker thread that pulls from a `queue.Queue` and executes events via pyautogui — never on the UI thread. Both are inert until enabled by an actual grant.
- `client/ui/screen_share_widget.py` — **created**. The Screen tab. Owns a `FrameLabel` that scales the latest frame into the available widget area while preserving aspect ratio (and reports the drawn letterbox geometry so the input sender can translate coordinates back). Hosts the share / stop / request / revoke buttons and the three tuning sliders. Drives the engine, the sender, and the executor based on `SCREEN_*` and `REMOTE_*` packets pushed in from `main_window`. Surfaces dropped-frame counts in a diagnostic line.
- `client/ui/chat_widget.py` — **modified**. Added a `room_changed(room_code)` signal emitted from `add_room` and `_on_room_selected`, so the Screen tab can follow whichever room the user has open in Chat without the Screen tab knowing about chat internals.
- `client/ui/main_window.py` — **modified**. Adds the Screen sidebar tab and the `ScreenShareWidget` instance, wires its `send_packet` and the chat widget's `room_changed` signal, dispatches `SCREEN_START / SCREEN_STOP / SCREEN_RELAY / REMOTE_REQUEST / REMOTE_GRANT / REMOTE_EVENT` from `_handle_packet` to the widget, forwards `ROOM_STATE["screen"]` on join, and calls `_screen_widget.shutdown()` on logout / disconnect / window close so the capture / executor threads exit cleanly.

### Tooling

- `requirements.txt` — **modified**. Added `mss` (cross-platform screen capture) and `pyautogui` (mouse/keyboard execution). Pillow was deliberately **not** added — `QImage.save("JPG")` + `QImage.loadFromData("JPG")` cover encode and decode without it, keeping the dep surface smaller.

## How Phase 2 Connects to Phase 1

- **Packet plumbing.** All seven packet types used by Phase 2 (`SCREEN_START / STOP / FRAME / RELAY`, `REMOTE_REQUEST / GRANT / EVENT`) were already declared in `shared/constants.py` from Phase 1. No protocol-layer change was needed: the existing 40-byte header, AES-GCM encrypted JSON envelope, and `read_packet` / `send_packet` helpers handle frame packets just like text messages. JPEG bytes are base64-encoded into the JSON `jpeg_b64` field — the ~33% overhead is comfortably within the LAN bandwidth target and below the 16 MB `MAX_PAYLOAD_SIZE` ceiling.
- **Room membership gates everything.** A user must already have joined a room (`JOIN_ROOM`, Phase 1) before they can `SCREEN_START`, send frames, request control, or be granted control. The server's `_resolve_screen_room` rejects packets for rooms the sender isn't in with `ERROR 403`. The Phase 1 cleanup that fires on disconnect was extended — not replaced — to also stop the share or clear the controller.
- **Connection layer is reused unchanged.** `ConnectionManager.send` already serializes concurrent writes through `_send_lock`, so the screen-engine send thread, the remote-control viewer thread, and the existing chat / friend traffic can all share one TCP socket without any additional plumbing. The receiver thread / 60 Hz `QTimer` polling pattern from Phase 1 covers the new packet types — `_handle_packet` simply gained more branches.
- **DM & friend systems unaffected.** Phase 2 only touches code paths gated on a screen / remote-control packet type, on `JOIN_ROOM` (for the new `screen` field in the response), and on cleanup. The DM-specific lazy-join in `_handle_chat_message` from docs/05 is untouched. All 36 Phase 1 unit tests still pass without modification.

## Key Decisions

1. **JSON + base64 for frame transport instead of a new binary mode.** The protocol envelope was defined in Phase 1 around JSON payloads. Adding a binary-payload variant would mean touching `encode_packet` / `read_packet` and re-running the protocol test suite. Base64 inside the existing envelope keeps the binary protocol stable, fits well within `MAX_PAYLOAD_SIZE` (a 1080p JPEG at q=70 is ~150–400 KB, ~200–550 KB after base64), and the existing AES-GCM transport already encrypts the whole thing. The architecture's "server does not decode" intent is honored at the JPEG level — the server only parses JSON, copies the base64 string verbatim into the relay payload, and re-encrypts per recipient.
2. **QImage / QBuffer for JPEG, no Pillow.** PyQt6 already ships with built-in JPEG codecs in `QImage.save` and `QImage.loadFromData`. Pillow would have been a third party dependency that added nothing here, plus its `ImageQt` shim has historically been brittle across PyQt versions. Skipping Pillow keeps the install footprint smaller without giving up any feature.
3. **Per-room `ScreenRelayState` lives in `room_manager._rooms[code]["screen"]`.** This piggybacks on the existing room lifecycle: when the last participant leaves, the room dict is dropped and the screen state goes with it. No second cleanup path to keep in sync.
4. **Coordinate normalization on the wire.** Sending pixel coordinates would have forced the sharer's monitor resolution into every viewer's awareness, and would break the moment the viewer resizes their window. Normalized `(0.0–1.0)` decouples the two ends entirely; the sharer multiplies by the local screen size at execute time.
5. **`pyautogui.FAILSAFE = False`.** pyautogui's default fail-safe aborts the session if the mouse touches the top-left screen corner — exactly the sort of thing a real user does by accident during a demo. Disabling it is correct for a controlled remote-control session; the trade-off is that runaway events can't be killed by mouse gesture, only by revoke / disconnect.
6. **Capture scale slider on top of FPS and quality.** Frame size dominates JPEG cost more than quality does — letting the sharer drop to 75% or 50% scale gives a much better fallback path on a slow host than fiddling with quality alone. Default is 100% (native).
7. **Drop-oldest on a depth-3 bounded queue.** At 30 FPS, 3 frames is ~100 ms of in-flight latency before frames start being skipped. Anything bigger introduces stale frames into the pipeline; anything smaller causes too-aggressive drops on natural network jitter. This is a conservative middle ground that biases toward freshness.
8. **No automatic FPS fallback.** The bounded queue + drop-oldest already implements an implicit, lossy backpressure path. Adding a feedback loop that auto-lowers FPS based on drop rate is a nice-to-have but the manual sliders cover the demo scenario without the extra control-loop complexity (and risk of oscillation). Documented as future work in the engine module.

## Threading Summary

| Thread | Lives in | Responsibilities |
|---|---|---|
| Capture thread | `ScreenCaptureEngine._capture_loop` | mss grab → QImage → JPEG-encode → enqueue (drop-oldest) |
| Send thread | `ScreenCaptureEngine._send_loop` | dequeue → `conn.send(SCREEN_FRAME)` |
| Network receiver | `ConnectionManager._receiver_loop` (Phase 1) | read packets → `packet_queue.put` |
| Main / UI | Qt event loop + 60 Hz `QTimer` | poll queue → `_handle_packet` → decode JPEG → render via `QPixmap` |
| Remote-control executor | `RemoteControlExecutor._loop` | pull from queue → run pyautogui calls |

No UI work is done off the main thread; no network send is done from the capture thread; no pyautogui call runs on the UI thread.

## Verification

- All 36 existing Phase 1 unit tests (`pytest tests/ -q`) still pass.
- Smoke tests run against the new code:
  - `ScreenRelayState` enforces single-sharer (`start_share` returns error if already taken), sharer-only grants (`set_controller` from a non-sharer fails), and clean revoke (`set_controller(None)` clears the slot).
  - JPEG round trip: encode a 160×90 cyan `QImage` at quality 70 → base64 → decode produces a 160×90 image. ~870 bytes for that test image; for a 1080p screenshot the typical size is ~150–400 KB at q=70 (well under `MAX_PAYLOAD_SIZE`).
  - `ScreenShareWidget` instantiates under Qt's `offscreen` platform, handles `set_current_room`, `handle_room_state_screen`, `on_screen_stop`, and `shutdown` without error.
- Manual flow to verify end-to-end (requires a host with a real display):
  1. Start Redis, PostgreSQL, the load balancer, two chat servers.
  2. Launch three clients, A / B / C; all join the same room.
  3. A clicks **Share Screen** → A's tab shows its own monitor; B and C see A's monitor in their Screen tabs. The Share button is disabled on B and C, showing "A is sharing".
  4. B clicks **Request Control** → A sees a "B is asking for remote control" dialog. A clicks **Allow**. B's frame view now sends mouse / key events; A's machine reacts.
  5. A clicks **Revoke Control** → B's input is ignored immediately and A's `pyautogui` executor stops.
  6. A clicks **Stop Sharing** → all three Screen tabs return to "no active screen share".
  7. While A is sharing, A disconnects (close the window). B and C automatically see the share end.
