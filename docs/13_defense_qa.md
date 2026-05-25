# Defense Q&A Notes

## What Was Done
Prepared defense notes for the main technical decisions in QuicKonNect. These answers are written for a project presentation: direct, concrete, and tied to the implemented code.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `docs/13_defense_qa.md` | Created | Provides ready answers for likely defense questions. |

## Why It Matters
The defense is not only about showing that the app runs. The team also needs to explain why the architecture was chosen, where networking concepts appear, how data is protected, and what trade-offs were accepted. These notes help the team answer clearly and consistently.

## Questions And Answers

### Why use TCP instead of UDP for audio and screen data?
The course focuses on socket programming with reliable client/server communication. TCP guarantees ordered delivery and simplifies the custom protocol because every packet arrives as a stream we can frame with a header and payload length. The trade-off is higher latency for media compared with UDP, but for a LAN classroom demo with a few clients this is acceptable.

### How does the custom protocol work?
Packets use a fixed header plus a JSON payload. The header identifies the packet type and payload length. After the RSA handshake, normal packets are encrypted with AES-GCM. Packet types include auth, room join, chat, screen frame, audio chunk, mixed audio, whiteboard draw event, and load-balancer health checks.

### How is encryption handled?
Each client starts with an RSA key exchange. The server generates an AES session key and sends it encrypted with the client's RSA public key. After that, application packets use AES-GCM. AES-GCM gives confidentiality and tamper detection, so changed ciphertext or header-associated data is rejected.

### Why not true end-to-end encryption for audio, screen, and whiteboard?
The server must process those data types. Audio is mixed server-side, screen frames are relayed by room membership, and whiteboard events need server-assigned sequence numbers. If those payloads were true E2E encrypted, the server could not do that processing. The project uses transport encryption for media and event data instead.

### Why build a custom load balancer?
The rubric gives credit for load balancing, and building it ourselves demonstrates server routing logic. The load balancer accepts a short TCP request, checks server health and connection counts, returns a target server, and then the client connects directly to that chat server.

### Why are normal rooms pinned to one server?
Screen sharing, audio, and whiteboard are real-time room features. If people in one room were split across multiple servers, the servers would need to relay media/events between each other. That adds latency and complexity. Pinning keeps one room on one server, so all room state is local.

### Why are DMs not pinned to one server?
DMs only carry small chat messages and are already persisted in PostgreSQL. They do not need real-time media mixing or whiteboard ordering. Letting each DM participant stay on their current server avoids unnecessary redirects. Cross-server DM delivery uses Redis pub/sub.

### What does Redis do?
Redis stores or transports fast-changing coordination data:
- Online user IDs.
- Server registry data.
- Normal room-to-server mapping.
- Friend status events.
- Cross-server DM message notifications.

PostgreSQL remains the durable database for users, sessions, rooms, messages, and whiteboard events.

### What does PostgreSQL store?
PostgreSQL stores persistent application data:
- Users and password hashes.
- Sessions/JWT tracking.
- Friendships.
- Rooms and participants.
- Message history.
- Whiteboard event history.

### Where is multi-threading used?
Threading appears in both client and server:
- One server handler thread per client.
- Server acceptor thread.
- Load balancer health checker thread.
- Redis pub/sub listener thread.
- Per-room audio mixer thread.
- Optional subtitle worker thread.
- Client network receiver thread.
- Client heartbeat thread.
- Client screen capture/send threads.
- Client audio capture/playback threads.
- Remote-control executor thread.

### How does screen sharing work?
The sharer captures screen frames with `mss`, encodes them as JPEG, base64-encodes the bytes inside the JSON payload, and sends `SCREEN_FRAME` packets. The server validates that the sender is the active sharer and relays `SCREEN_RELAY` packets to the other room participants.

### How does remote control work?
A viewer sends a remote-control request. The sharer sees an approval dialog. Only after approval does the server relay `REMOTE_EVENT` packets from that viewer to the sharer. The sharer can revoke control, and stale events after revoke are ignored.

### How does audio mixing work?
Clients send 20 ms PCM audio chunks. The server keeps short per-user buffers and ticks every 20 ms. For each recipient, it mixes all active speakers except that recipient, then sends a `MIXED_AUDIO` packet. Excluding the recipient's own stream prevents echo.

### Why use raw PCM instead of Opus?
Raw PCM is easier to install and debug on Windows and is reliable for a LAN demo. It uses more bandwidth than Opus, but the classroom scale is small. Opus is a good future optimization if bandwidth becomes a problem.

### How do subtitles work?
Subtitles are optional. If `QUICKONNECT_STT_ENABLED=1`, the server batches speaker audio and uses `faster-whisper` to produce transcript text, then broadcasts `SUBTITLE` packets. If Whisper is unavailable, audio still works.

### How does the whiteboard stay consistent?
Clients send draw events such as stroke, rectangle, text, erase, undo, and clear. The server validates each event, assigns a sequence number, stores it in PostgreSQL, and broadcasts it. Clients render events in server sequence order. New joiners receive `WHITEBOARD_SYNC` and replay the event history.

### How do file and image messages work?
The client reads the file bytes, base64-encodes them, and sends them as a structured JSON message with filename, MIME type, and size. The server validates the attachment before storing and broadcasting it. The receiver can save the attachment from the chat UI.

### What automated tests are available?
The test suite covers protocol encoding/encryption, crypto helpers, audio mixing, whiteboard helpers, and attachment validation. A protocol-level E2E smoke test also verifies register, join room, chat, attachment, whiteboard event, and mixed audio through a running local stack.

### What are the current limitations?
- Audio uses raw PCM, not Opus.
- Subtitle quality and latency depend on the local machine.
- Internet/ngrok demo still needs a live network test.
- GUI/hardware features like mic, screen capture, and remote control should be manually tested before presentation.
