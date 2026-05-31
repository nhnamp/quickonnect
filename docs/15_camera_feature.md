# Camera Streaming

## What Was Done
Added room camera support to the desktop client. Users can turn their camera on while they are in a room, see their own local preview, and receive small live camera tiles from other participants in the same room. Camera frames use QtMultimedia capture, are downscaled and JPEG encoded on the client, and are relayed through the existing authenticated TCP connection.

The server now tracks active camera users per room, announces active cameras to newly joined users, validates that camera frames come from room members with an active camera, limits camera frame payload size, and broadcasts camera start/stop/frame events to the rest of the room. Leaving a room or disconnecting clears camera state and notifies remaining participants.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `shared/constants.py` | Modified | Added camera packet types for start, stop, frame, and relay messages. |
| `client/features/camera_engine.py` | Created | Captures camera frames with QtMultimedia, downscales/encodes JPEG frames, and sends them through the connection manager. |
| `client/ui/screen_share_widget.py` | Modified | Added camera toggle controls, local preview, remote camera tiles, camera event handlers, and cleanup on room changes. |
| `client/ui/main_window.py` | Modified | Routed camera packets and active-camera room state into the screen/media widget. |
| `client/ui/chat_widget.py` | Modified | Emits a room change when leaving a room so local media stops cleanly. |
| `server/features/camera_state.py` | Created | Tracks active camera users for each room. |
| `server/room_manager.py` | Modified | Creates and cleans up per-room camera state. |
| `server/client_handler.py` | Modified | Handles camera start/stop/frame packets and broadcasts camera events to room members. |
| `tests/test_camera_state.py` | Created | Covers per-room camera state behavior. |
| `tests/test_camera_engine.py` | Created | Covers camera image scaling and JPEG decode/encode helpers. |

## Why It Matters
Camera sharing is a real-time room feature like microphone audio, so it needs the same room membership checks and cleanup guarantees. Tracking active cameras server-side prevents stale or unauthorized camera frames from being relayed, while client-side downscaling keeps LAN bandwidth predictable and avoids large payload spikes.

QtMultimedia is already available through PyQt6 in this project, so no new OpenCV dependency is required. On macOS and Linux, camera access still depends on operating-system camera permissions and an available video input device.

## Manual Verification
1. Start the server and two clients on the same LAN.
2. Join both clients to the same room.
3. Click `Camera On` on one client and confirm the local preview tile appears.
4. Confirm the other client sees a camera tile for that user.
5. Click `Camera On` on the second client and confirm both users see both camera tiles.
6. Click `Camera Off` and confirm the tile disappears on both clients.
7. Leave the room while the camera is on and confirm the remaining client receives a camera stop update.
8. Test on macOS and Linux with OS camera permissions denied once to confirm the app shows a clear startup error.
