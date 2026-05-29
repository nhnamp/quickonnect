# Feature Logic

This document explains the current logic of two core feature groups in QuicKonNect: user management and messaging, then screen sharing and remote control. It is written for a new developer who has not read the source code yet. The goal is to make the end-to-end behavior clear before diving into implementation details.

## Part 1: User Management & Messaging

### Authentication Flow

Authentication starts after the client has already established an encrypted connection to a chat server. That ordering matters: the client does not send credentials over a raw plaintext TCP stream. It first goes through the load balancer, connects to the assigned chat server, completes the RSA/AES transport handshake, and only then sends account data.

When a new user registers, the client sends a registration request containing the username and password. The architecture originally listed registration as username plus hashed password, but the finalized security model uses server-side password hashing: the client sends the password through the encrypted transport channel, and the server hashes it with BCrypt using cost factor 12. PostgreSQL stores the user in the `users` table, where the username is unique and the stored password field is a BCrypt hash, not the original password. This means a database leak does not reveal users' passwords directly; attackers would still need to crack BCrypt hashes, which is deliberately expensive.

Login is a separate flow from registration and token resume. Phase 1 added explicit `LOGIN_REQUEST` and `LOGIN_RESPONSE` packet types because the architecture had `AUTH_REQUEST` for JWT validation and `REGISTER_REQUEST` for account creation, but no clean packet for username/password login. On login, the client sends username and password over the encrypted channel. The server finds the user, compares the submitted password against the stored BCrypt hash, and, if the credentials are valid, issues a JWT. The token contains the user's identity and timing claims: user id, username, issued-at time, and expiration time. The documented expiry is 24 hours.

The client persists the JWT locally so the user can resume a session on the next launch. On startup, if a saved token exists, the login window does not require the user to type credentials again. Instead, it sends an `AUTH_REQUEST` containing the token. The server validates the HMAC-SHA256 signature and expiration claims and logs the user in if the token is still valid. The important design property is that the token is self-contained: the signature proves the server issued it, and the embedded claims say who the user is and when the token expires. The database schema still includes a `sessions` table for session tracking and revocation support, but the resume logic is intentionally built around signed JWT validation rather than re-checking a password.

JWT handling was implemented directly instead of using PyJWT. The trade-off is that the project takes responsibility for a small piece of security-sensitive code. The benefit is reduced dependency surface and a clearer demonstration of the underlying mechanism: base64url-encoded header and payload, HMAC-SHA256 signature, and expiration validation. The team accepted that trade-off because the implemented JWT subset is narrow and covered by tests for valid tokens, wrong secrets, tampering, expiration, and malformed input.

### Connection and Encryption

Every client begins by contacting the load balancer, not a chat server directly. The load balancer listens on port 9000 and has a short-lived role: it accepts a routing request, chooses or looks up the right chat server, replies with that server's host and port, and closes the load-balancer connection. The client then opens a new TCP connection to the assigned chat server.

The chat-server connection starts with a key exchange. The client generates an ephemeral RSA-2048 key pair and sends the public key in a plaintext `CLIENT_HELLO`. The server generates its own ephemeral RSA-2048 key pair and a fresh random 32-byte AES session key. It sends a `SERVER_HELLO` containing the server public key and the AES session key encrypted with the client's RSA public key. The client decrypts that AES key with its private key. From that point onward, both sides share a per-connection AES-256-GCM key, and all ordinary packets on that connection are encrypted.

AES-GCM provides confidentiality and integrity: it hides the payload and detects tampering. Phase 1 added Associated Authenticated Data, or AAD, to protect part of the packet header too. AAD is not encrypted, but it is authenticated. In this protocol, the first 12 bytes of the header are used as AAD: magic number, protocol version, packet type, and payload length. This prevents an attacker from changing metadata such as "this is a chat message" into "this is a screen frame" or altering the length field without invalidating the authentication tag. The gain is meaningful tamper resistance with almost no performance cost. The cost is that encryption/decryption must be consistent about which header bytes are authenticated, so protocol tests become important.

The load balancer fits into this model before encryption with the chat server begins. The load balancer itself receives a plaintext `CONNECT_REQUEST` and returns a plaintext `CONNECT_RESPONSE` because it is only doing routing. It does not participate in the client-server RSA/AES session. That keeps the load balancer simple and avoids turning it into a long-lived proxy. The trade-off is that clients must be able to reach both the load balancer and whichever chat server the load balancer returns.

For LAN testing, one subtle bug was fixed in that returned address. The chat servers and load balancer already listen on `0.0.0.0`, so they can accept both localhost and LAN connections. However, the load balancer may health-check local chat servers through `127.0.0.1`. A second laptop cannot use `127.0.0.1` to reach the host laptop; it would connect to itself. The LAN fix makes the load balancer advertise a client-reachable interface address when the configured server host is loopback, `localhost`, or wildcard.

### Room Management

Regular rooms are designed around room-pinned load balancing. A room code identifies the room, and Redis stores which chat server owns that room. The first user to create or join a new regular room causes that room to become associated with the current chat server. That server creates or finds the room in PostgreSQL, tracks active clients in memory, and registers the room-to-server mapping in Redis. From then on, that server owns the real-time state for the room.

The reason for this pin is practical: screen sharing, future audio, and future whiteboard synchronization all require low-latency in-memory fan-out. If participants in one room were split across several chat servers, the system would need a cross-server media relay, likely through Redis or another broker. That would add latency and substantial complexity. The architecture explicitly chooses room pinning so all real-time room participants land on one chat server.

When a second or third user joins an existing regular room, the correct flow is to ask the load balancer first. The client sends the desired room code in the `CONNECT_REQUEST`. The load balancer checks Redis for `room:{room_code}`, finds the pinned server id, and returns that server's address. If the client is already connected to that exact server, it can send `JOIN_ROOM` immediately. If not, it disconnects from its current chat server, reconnects to the pinned one, re-authenticates with the saved JWT, and then sends `JOIN_ROOM`. The chat server adds the user to the room's active client map, records participation in PostgreSQL, returns `ROOM_STATE`, and notifies other participants with `ROOM_UPDATE`.

A real bug exposed why this flow matters. The Join button initially bypassed the load balancer and sent `JOIN_ROOM` over whichever server connection the user happened to have from login. If the user was already connected to the room's pinned server, the join worked. If they were connected to a different server, that server correctly detected the room belonged elsewhere and returned a 307-style redirect error. The Redis pin was not wrong; the client had skipped the routing step. The fix split "Create" and "Join" behavior: room creation can stay on the current server, but joining an entered room code goes through the load balancer, reconnects if necessary, resumes authentication with JWT, and only then sends `JOIN_ROOM`.

### Text Messaging

Text messages reuse the same encrypted connection and packet envelope as every other feature. In the normal room-message path, a user sends a `CHAT_MESSAGE` containing the room code, content, and message type. The server verifies the room exists locally, stores the message in PostgreSQL, attaches the sender identity for display, and broadcasts the message to active room participants. Each client receives the packet through its connection manager, the UI thread polls the incoming queue on a timer, and the chat widget renders the message in the current room view.

Message history is loaded when a user joins a room. The server retrieves the most recent 100 messages from PostgreSQL and sends them as `MESSAGE_HISTORY`, ordered oldest-first so the client can render them naturally from top to bottom. This gives late joiners or reconnecting users enough recent context without loading an unbounded room history into memory.

The friend system is also built on PostgreSQL plus Redis. Friend requests are stored with a pending or accepted status. A user can send a request by username, and the recipient can accept or reject it. Once accepted, each user's friend list can show the other user's online/offline state. Online status is distributed across chat servers through Redis pub/sub: when a user connects or disconnects, their server publishes a status event, and other servers forward the update to their locally connected clients. The same pub/sub pattern later became useful for cross-server DM delivery.

### DM System Evolution

Direct messages started as a special case of rooms. The client generates a deterministic room code from the two usernames: `DM-{sorted_name_1}-{sorted_name_2}`. Sorting the names means both users independently compute the same code for the same conversation. No separate "find DM room" API is needed. In the original design, double-clicking a friend triggered `JOIN_ROOM` for that deterministic DM room, and sending a message reused the normal `CHAT_MESSAGE` path.

That worked only for the user who explicitly joined the DM. The first bug appeared when User 1 opened a DM and sent a message to User 2. The normal broadcast only sent to clients currently joined to that room. User 2 had not joined the room yet, so User 2 never received the message in real time. The message was persisted, but the live chat behavior was wrong. The fix added DM-aware delivery after the normal room broadcast. If the room code starts with `DM-`, the server extracts the other username from the deterministic room code. If that recipient is connected to the same chat server, the server pushes the `CHAT_MESSAGE` directly to that client's socket. If the recipient is connected to another server, the sender's server publishes a small JSON envelope to a Redis channel named `dm_messages`. Every chat server subscribes, and the one that has the recipient locally delivers the packet. The event includes an originating server id so the publishing server can ignore its own Redis echo.

That first fix made unsolicited incoming DMs appear for the recipient, but it did not solve the whole room model. DM rooms were still pinned like regular rooms. If User 1 started `DM-A-B` on server 9001, Redis recorded that DM room as belonging to server 9001. When User 2 tried to reply from server 9002 by double-clicking User 1, the load balancer and room manager treated it like a regular room and redirected User 2 to the pinned server. That created a 307 redirect problem for what should be a lightweight, location-independent conversation.

The design changed: DM rooms became server-agnostic logical rooms. The load balancer skips Redis lookup and Redis pin writes for room codes beginning with `DM-`. The room manager also skips regular room registration for DMs. This means each user can remain on whichever chat server they are already using. PostgreSQL remains the durable source of message history, while Redis `dm_messages` handles real-time cross-server delivery. Regular rooms keep pinning because they carry real-time media and collaborative state; DM rooms avoid pinning because they only need small text packets and persisted history.

The next bug was that a DM recipient could see an incoming message in the UI but still not be a server-side participant in the local DM room. That happened because the Redis delivery path simply forwarded the `CHAT_MESSAGE` packet to the client; it did not call `JOIN_ROOM`. When the recipient typed a reply, the server looked for a local room entry, found none, and returned "Room not found." Even when the recipient's message reached the other user through a push path, the sender sometimes did not see their own message because the broadcast loop only echoes to clients in the room's local client map.

The fix was lazy-join on send. If a user sends into a DM room and is not currently in that server's local client map for the room, the server joins them to the DM room at that moment, then proceeds with normal store-and-broadcast logic. This is deliberately done on send, not on passive receive. Joining on receive would create participant rows for users who merely received a DM but never interacted, which would pollute room participation history. Send-side lazy-join records participation only when the user actually speaks.

The first lazy-join condition checked whether the room existed locally. That fixed the cross-server case where the sender's server had no local DM room entry. But a same-server edge case remained. Imagine User 1 joined the DM room on server A, then User 2 received a same-server push without being added to the room's client map. When User 2 replied, the room existed locally because User 1 had created it, so the old "room missing" check did not fire. The broadcast went only to User 1, and User 2 still did not see their own reply. The correct condition is not "does the room exist?" It is "is the sender present in this room's local client map?" The final lazy-join check is membership-based. If the sender is absent, join them. If they are already present, do nothing. This covers both cross-server missing-room cases and same-server present-room-but-missing-sender cases without inserting redundant participant rows.

The final DM behavior is symmetric. Either user can open a DM from any server. Either user can send first or reply later. The sender always sees their own message because they are lazy-joined before broadcast if needed. The recipient sees the message either through the local room broadcast, a same-server direct push, or the cross-server Redis `dm_messages` channel. Offline recipients rely on PostgreSQL-backed history the next time they open or join the conversation. The design reuses the same Redis pub/sub idea already used for online status, but keeps it limited to small text-message envelopes rather than real-time media.

## Part 2: Screen Sharing & Remote Control

### Screen Sharing Architecture

Screen sharing was added on top of the Phase 1 connection, packet, encryption, and room systems. There is no separate media socket. Screen frames, screen status packets, and remote-control events all use the same encrypted chat-server connection as chat messages. This choice keeps the protocol surface small and reuses the existing `ConnectionManager.send` behavior, including its thread-safe write lock and AES-GCM transport encryption.

The client-side screen-sharing pipeline uses three major execution contexts. The capture thread grabs frames from the local display using `mss`, converts the capture into a `QImage`, and encodes it as JPEG. The send thread takes encoded frames from a bounded queue and sends them as `SCREEN_FRAME` packets through the connection manager. The UI thread receives relayed frames through the normal incoming packet queue, decodes the JPEG, converts it into a `QPixmap`, and renders it in the Screen tab. The network receiver thread from Phase 1 still exists underneath this, reading packets from the socket and placing them into the queue that the UI polls at roughly 60 Hz.

Capture and send are deliberately separated. Screen capture should run at a predictable pace and should not block just because the network is slow. The send side can stall on TCP, encryption, JSON/base64 payload size, or a slow receiver path. If capture and send were one loop, every send delay would freeze capture. The bounded queue between them has depth 3 and uses drop-oldest semantics. "Drop-oldest" means that when the queue is full and a newer frame arrives, the stale frame at the front is discarded to make room. The viewer may see fewer frames under pressure, but the frames they do see are recent. That is the right trade-off for screen sharing: freshness is more important than replaying every frame in order if the display has already moved on.

Frames are transported as base64-encoded JPEG inside the existing JSON payload rather than through a new binary frame protocol. The cost is about 33 percent base64 overhead and the need to serialize a large string in JSON. The benefit is protocol stability. The same 40-byte packet header, packet-type routing, AES-GCM encryption, and tests continue to apply. The server only needs to parse the JSON envelope and copy the base64 JPEG string into a `SCREEN_RELAY` packet; it never needs to understand image pixels. For the expected LAN demo size, a 1080p JPEG at quality 75 remains comfortably below the documented 16 MB maximum payload limit, even after base64 expansion.

The implementation uses `QImage` and `QBuffer` for JPEG encoding and decoding instead of Pillow. The architecture initially listed Pillow as the image compression library, but Phase 2 chose Qt's built-in image support because PyQt6 already provides JPEG save/load functionality. This reduced dependencies and avoided another image-conversion layer. The trade-off is that the screen engine becomes more Qt-specific, which is acceptable because the client is already a PyQt6 desktop application.

Screen-sharing parameters are fixed rather than user-tunable: 30 FPS, JPEG quality 75, and 100 percent scale. Quality 75 was chosen because it preserves readable desktop text and UI edges better than lower quality values while still keeping frame sizes reasonable for LAN use. Scale matters even more than quality for perceived performance because it changes the number of pixels captured, encoded, transmitted, decoded, and rendered. Halving the scale can reduce the pixel workload much more than small JPEG quality adjustments. The current default keeps native resolution because visual clarity is important for a demo and because LAN bandwidth is expected to be sufficient. The cost is that remote internet use through tunnels can be heavier than a lower-scale stream.

On the server, screen state lives with the room. Each active room gets a `ScreenRelayState` object that tracks the current sharer and optional remote controller. The server validates that incoming screen packets come from a user who is actually in the room and, for frame packets, that the sender is the current sharer. It does not decode JPEG bytes, inspect pixels, or transform frames. It fans out a valid `SCREEN_FRAME` as `SCREEN_RELAY` to the other participants in the room. This keeps CPU work on the clients and keeps the server's media role simple: state validation plus relay.

Only one participant can share in a room at a time. When a user starts sharing, the server records that user as the sharer in `ScreenRelayState` and broadcasts `SCREEN_START`. If another participant tries to send `SCREEN_START` while a share is active, the server rejects it with an error code 409. Clients use the broadcast state to disable the Share button for viewers, so the common path prevents a second sharer in the UI, while the server still enforces the rule as the source of truth.

### Late Joiners

Late joiners do not need a separate "screen setup" packet. The room-join response already returns `ROOM_STATE`, so Phase 2 extended that payload with a `screen` block when a share is active. That block includes the current sharer and, if present, the current controller. When the joining client receives the room state, the Screen tab can immediately show that someone is sharing and prepare to render the next `SCREEN_RELAY` frame. This is a small but important design choice: it keeps room state consolidated in one packet and avoids a race where a late joiner would have to wait for a future `SCREEN_START` event that already happened before they joined.

### Remote Control Workflow

Remote control is layered on top of screen sharing. The state machine is: idle, requested, granted, then revoked or stopped. In idle state, nobody has control. When a viewer wants control, they send `REMOTE_REQUEST` for the current room. The server checks that a share exists and forwards the request only to the active sharer. Other viewers do not need to see the request because only the sharer can grant permission.

On the sharer's client, a confirmation dialog asks whether to allow the requester to control the mouse and keyboard. If the sharer accepts, the client sends `REMOTE_GRANT` with `granted=true` and the target user id. The server records that target as the controller in `ScreenRelayState` and broadcasts the grant state to the room. From then on, the server forwards `REMOTE_EVENT` packets only from that controller. Events from anyone else are rejected or ignored. This server-side gate is important because UI state can be stale, clients can misbehave, and a permission decision must not depend only on the controller's local button state.

On the viewer side, input capture is handled by `RemoteControlSender` as a Qt event filter installed on the frame display widget. The event filter is only attached and enabled while the viewer has been granted control. The frame widget must accept focus with `StrongFocus`, track mouse movement, and receive keyboard focus when control is granted. Without those details, the UI may show that control was granted but Qt will not deliver key or mouse events to the expected object. The sender captures mouse move, mouse press, mouse release, wheel scroll, key press, and key release events. It translates those events into `REMOTE_EVENT` packets.

Mouse coordinates are sent as normalized values from 0.0 to 1.0 instead of raw pixels. The viewer's displayed frame may be smaller than the sharer's real monitor, may be letterboxed, and may change size when the viewer resizes the window. If the viewer sent raw local pixels, the sharer would not know how those pixels map to the real desktop. With normalized coordinates, the viewer sends "this point is 25 percent from the left and 40 percent from the top of the displayed frame." The sharer multiplies those normalized values by the real screen size reported by `pyautogui.size()` and moves or clicks at the corresponding real desktop coordinate. This decouples viewer viewport size from host monitor resolution.

On the sharer's side, `RemoteControlExecutor` runs `pyautogui` calls on a dedicated worker thread. This is necessary because mouse and keyboard automation can block or fail depending on the operating system, focused application, and desktop environment. Running those calls on the UI thread would risk freezing the entire client while processing remote input. The executor receives events through a queue and maps event kinds such as move, press, release, scroll, key press, and key release to pyautogui operations.

`pyautogui.FAILSAFE` is disabled for the remote-control session. By default, pyautogui can abort if the mouse reaches a screen corner. That is useful in local scripts, but it is a poor fit for remote control because a legitimate remote user may move the mouse to a corner during normal work. The trade-off is that the corner gesture is no longer an emergency stop. The intended safety controls are explicit revoke, stop sharing, disconnect, or closing the app.

Revocation is controlled by the sharer. When the sharer clicks Revoke, the client sends `REMOTE_GRANT` with `granted=false`. The server clears the controller in room state and broadcasts the update. The controller's client disables its event filter, so it stops sending input. On the sharer side, events from the former controller are no longer accepted by the server, so even stale packets after revoke do not continue controlling the host. If the entire share stops, remote control stops with it.

Disconnect cleanup follows room ownership. If the sharer disconnects or leaves the room, the server stops the share and clears any controller, then notifies remaining participants with `SCREEN_STOP`. If the controller disconnects but the sharer stays, only the controller grant is cleared and the share continues. This keeps cleanup proportional: losing the host ends the session, losing the guest only removes permission.

### Bugs Found and Fixed in Screen Sharing and Remote Control

One class of screen-share failure was startup fragility after desktop environment changes. Installing Linux desktop dependencies for remote control, such as GUI and Python development packages, exposed situations where `mss` could be imported but could not actually capture a usable frame. The older startup path only checked importability and then allowed the UI to enter a half-started sharing state. The actual display connection or first grab happened later in the capture thread, where failure was asynchronous and easy to miss. The fix was to perform a real preflight: initialize `mss`, grab one frame, convert it, and verify JPEG encoding before declaring screen sharing started. Startup errors are now caught, logged with readable tracebacks, shown to the user, and the UI is reset instead of crashing or remaining in a misleading state.

A related black-frame bug appeared when capture technically succeeded but produced no useful desktop pixels. The capture pipeline had an ambiguous BGRA-to-Qt conversion path, and some monitor entries could capture as black while another entry, often the all-monitors composite, contained the real desktop. The fix changed frame construction to use `mss` normalized RGB bytes with explicit `QImage.Format_RGB888`, added monitor selection that tries reported monitors and prefers a non-blank first frame, validates JPEG encoding during preflight, and wires the sharer's local preview directly from the capture engine. That preview is diagnostically useful: if the sharer preview is black, the bug is at capture time; if the preview is correct but the viewer is black, the bug is downstream in relay, decode, or rendering.

Remote-control grants also had a client-side input-chain bug. The grant packet reached clients, and the server-side route for `REMOTE_EVENT` was reviewed and found to be conceptually correct: only the granted controller should be forwarded to the active sharer. The broken link was on the viewer and host client setup. On the viewer side, the input event filter was not reliably installed on the actual frame widget, focus was not guaranteed, and mouse tracking was too loose. On the sharer side, the executor was not guaranteed to be running before forwarded events arrived. The fix made the frame label focusable from construction, enabled mouse tracking, installed `RemoteControlSender` as an event filter on the frame label when `REMOTE_GRANT(granted=true)` arrives, immediately focused the frame, and removed the filter on revoke or share stop. The sharer's executor now starts when sharing begins, so it is ready before the first remote event arrives. Event names were also normalized to the forms the executor expects, while preserving compatibility with earlier names.

These fixes follow the same principle used throughout the project: the server remains the authority for shared state and permission, while the client is responsible for local OS-dependent capabilities like screen capture and input execution. When local desktop capabilities fail, the client should fail visibly and recoverably; when permission or room membership is wrong, the server should reject or ignore the packet.

## Part 3: Protocol, Packet Structure, and Encryption

### 3.1 Binary Packet Structure

Every packet on the custom TCP protocol begins with the same fixed-size 40-byte header. The format is defined as network byte order with the layout `4s, H, H, I, 12s, 16s`. In plain terms, the first 4 bytes are the magic number, the next 2 bytes are the protocol version, the next 2 bytes are the packet type, the next 4 bytes are the payload length, the next 12 bytes are the AES-GCM nonce, and the final 16 bytes are the AES-GCM authentication tag.

The magic number is exactly `b"QKNT"`, which is the protocol's signature. It lets the receiver reject data that is not a QuicKonNect packet before trying to interpret packet type or payload length. The protocol version is the unsigned 16-bit value `1`; any other version is rejected as unsupported. The packet type is also an unsigned 16-bit value, and it must map to one of the `PacketType` enum values from `shared/constants.py`. The payload length is an unsigned 32-bit value, but the implementation also enforces `MAX_PAYLOAD_SIZE`, which is `16 * 1024 * 1024` bytes, or 16 MB. The nonce field is 12 bytes because AES-GCM uses a 96-bit nonce in this implementation. The tag field is 16 bytes because the cryptography library returns a 128-bit GCM authentication tag.

The fixed-size header is what makes the TCP stream parseable. TCP is a byte stream, not a message protocol, so the receiver cannot assume that one `recv()` call equals one packet. `read_packet()` first calls `_recv_exact()` for `HEADER_SIZE`, which is 40 bytes. After `decode_header()` validates the magic number, version, packet type, and maximum payload size, the receiver knows exactly how many payload bytes to read next. This two-step read, fixed header first and then length-defined payload, is the core framing mechanism that allows many packets to travel safely over one long-lived TCP connection.

The trade-off is that every packet pays a constant 40-byte overhead, even tiny packets such as heartbeat responses. The gain is much more important for this project: packet parsing is simple, deterministic, and identical for chat messages, room updates, screen frames, remote-control events, and health checks.

### 3.2 Plaintext vs Encrypted Packets

Most packets are encrypted after the RSA handshake, but a small set must remain plaintext because they happen before an AES key exists or because they are used by the load balancer and health checker outside the encrypted client session. The plaintext set is defined directly in `PLAINTEXT_PACKET_TYPES`:

- `CLIENT_HELLO` (`0x0001`) is sent from client to chat server before the AES key exists.
- `SERVER_HELLO` (`0x0002`) is sent from chat server to client and carries the encrypted AES key.
- `CONNECT_REQUEST` (`0x00F0`) is sent from client to load balancer on the short-lived routing connection.
- `CONNECT_RESPONSE` (`0x00F1`) is sent from load balancer to client with the assigned chat server address.
- `HEALTH_QUERY` (`0x00F2`) is sent from load balancer to chat server during health checks.
- `HEALTH_RESPONSE` (`0x00F3`) is sent from chat server back to the load balancer.

Structurally, plaintext and encrypted packets use the same 40-byte header. The difference is in the nonce, tag, and payload fields. For a plaintext packet, `encode_packet()` writes twelve zero bytes into the nonce field and sixteen zero bytes into the tag field. The payload bytes are the raw UTF-8 JSON encoding of the payload dictionary.

For an encrypted packet, the nonce field contains a random 12-byte nonce generated for that packet, and the tag field contains the 16-byte AES-GCM authentication tag. The payload bytes after the header are ciphertext, not JSON text. The receiver determines whether a packet is encrypted by checking whether the nonce is all zeros. If the nonce is nonzero, `read_packet()` requires an AES key, reconstructs the AAD, decrypts the ciphertext with `aes_decrypt()`, and then parses the resulting JSON.

Keeping the header shape identical is a useful design choice. A receiver can always read and validate the first 40 bytes the same way, whether the packet is a plaintext load-balancer routing packet or an encrypted `SCREEN_FRAME`. The trade-off is that plaintext packets still carry unused nonce and tag fields filled with zeros, but that small overhead keeps framing uniform.

### 3.3 RSA Handshake and AES Session Key Establishment

The encrypted chat-server connection begins in `ConnectionManager.connect()`, which opens a TCP socket to the assigned chat server and then calls `_do_handshake()`. The client generates a fresh RSA-2048 key pair with `generate_rsa_keypair()`. It serializes the public key to PEM bytes with `serialize_public_key()`, base64-encodes those PEM bytes, and sends a plaintext `CLIENT_HELLO` with a `public_key` field.

The server-side `ClientHandler.run()` reads the first packet with `read_packet(..., aes_key=None)`. A `HEALTH_QUERY` is handled as a special unauthenticated health-check packet. Otherwise, the first real client packet must be `CLIENT_HELLO`. In `_do_handshake()`, the server base64-decodes and deserializes the client's public key, generates its own ephemeral RSA-2048 key pair, and generates a fresh 256-bit AES key with `generate_aes_key()`.

The server then encrypts the AES key with the client's RSA public key using RSA-OAEP with SHA-256. Its plaintext `SERVER_HELLO` contains two base64 fields: `public_key`, which is the server's serialized public key, and `encrypted_session_key`, which is the RSA-encrypted AES key. The current client uses the encrypted session key field to recover the AES key: it base64-decodes `encrypted_session_key`, decrypts it with the client's ephemeral RSA private key using `rsa_decrypt()`, and stores the result as `self._aes_key`.

At the end of the handshake, both sides hold the same AES-256 session key. The client stores it in `ConnectionManager._aes_key`; the server stores it in `ClientHandler._aes_key`. All subsequent non-plaintext packets on that chat-server connection use this key.

The RSA key pairs are ephemeral rather than long-lived. That avoids local key storage and reduces the damage if an in-memory key is lost after a connection ends. It also keeps setup simple for a course-scale application because there is no certificate chain, key registry, or persistent server identity to manage. The cost is that this is transport encryption without strong public-key identity verification: the server public key is sent in the handshake, but the client does not pin or verify it against a certificate authority. For the project's LAN-oriented threat model, the simplicity was accepted; for production internet security, authenticated server identity would be the next step.

### 3.4 AES-256-GCM Encryption

`send_packet()` calls `encode_packet()`, and `encode_packet()` first serializes the payload dictionary with `json.dumps(..., ensure_ascii=False)` and UTF-8 encoding. For an encrypted packet, those JSON bytes are the plaintext passed into AES-GCM. The key is the per-connection AES key established during the RSA handshake. `aes_encrypt()` creates a random 12-byte nonce with `os.urandom(12)`, constructs an `AESGCM` object, and encrypts the JSON bytes with the nonce and AAD.

The AAD is exactly the first 12 bytes of the logical header: magic number, protocol version, packet type, and payload length, packed as `!4sHHI`. In this implementation, the encrypted payload length is the same as the JSON plaintext length because the GCM tag is stored separately in the header, not appended to the payload. `aes_encrypt()` returns three values: nonce, ciphertext, and tag. `encode_packet()` places the nonce in bytes 12-23 of the header, the tag in bytes 24-39, and writes the ciphertext as the packet body.

On receive, `read_packet()` reads the fixed header, calls `decode_header()`, and then reads exactly `payload_len` bytes. If the nonce is nonzero, it reconstructs the same AAD using the decoded magic/version/type/length values, then calls `aes_decrypt()` with the AES key, nonce, ciphertext, tag, and AAD. `aes_decrypt()` appends the tag back to the ciphertext in the format expected by the cryptography library and verifies the GCM tag during decryption. If any authenticated input was modified, decryption fails instead of returning corrupted JSON.

AAD protects fields that are not encrypted but still security-sensitive. Without AAD, an attacker who cannot read the payload might still try to change the packet type or length in the header. That could create type-confusion attacks, such as making one encrypted payload appear to be a different kind of packet, or framing attacks that make the receiver read the wrong number of bytes. Because packet type and payload length are authenticated as AAD, changing them invalidates the GCM tag. Pure encryption hides the payload; AES-GCM with AAD also binds the visible routing metadata to that payload.

### 3.5 Packet Types

Packet types are unsigned 16-bit values. The current enum is grouped by feature area, with some gaps left between ranges so new packets can be added without reshuffling existing values.

Connection handshake:

- `CLIENT_HELLO` (`0x0001`, plaintext): client to chat server, starts the RSA handshake by sending the client's base64 PEM public key.
- `SERVER_HELLO` (`0x0002`, plaintext): chat server to client, returns the server public key and the RSA-encrypted AES session key.

Authentication:

- `AUTH_REQUEST` (`0x0010`): client to chat server, resumes a saved JWT session.
- `AUTH_RESPONSE` (`0x0011`): chat server to client, reports JWT validation success or failure.
- `REGISTER_REQUEST` (`0x0012`): client to chat server, creates a new account with username and password.
- `REGISTER_RESPONSE` (`0x0013`): chat server to client, reports registration success and returns session data when successful.
- `LOGIN_REQUEST` (`0x0014`): client to chat server, submits username and password for login.
- `LOGIN_RESPONSE` (`0x0015`): chat server to client, reports login success and returns session data when successful.

Room lifecycle:

- `JOIN_ROOM` (`0x0020`): client to chat server, asks to join or create a room code on that server.
- `ROOM_STATE` (`0x0021`): chat server to client, returns room id, room code, participants, and any attached feature state such as active screen share metadata.
- `LEAVE_ROOM` (`0x0022`): client to chat server, leaves the current room.
- `ROOM_UPDATE` (`0x0023`): chat server to room participants, announces joins and leaves.

Messaging:

- `CHAT_MESSAGE` (`0x0030`): client to chat server for sending text, then chat server to recipients after storage and routing.
- `MESSAGE_HISTORY` (`0x0031`): chat server to client after room join, sends recent stored messages.

Audio and subtitles:

- `AUDIO_CHUNK` (`0x0040`): client to chat server, carries microphone audio for future audio streaming.
- `MIXED_AUDIO` (`0x0041`): chat server to client, carries server-mixed playback audio.
- `SUBTITLE` (`0x0042`): chat server to room participants, carries speech-to-text or translated subtitle text.

Screen sharing:

- `SCREEN_FRAME` (`0x0050`): sharer client to chat server, carries a JSON envelope containing frame metadata and a base64 JPEG.
- `SCREEN_RELAY` (`0x0051`): chat server to viewers, relays the sharer's frame without decoding the JPEG.
- `SCREEN_START` (`0x0052`): client to chat server to request share start, then chat server to room participants to announce the active sharer.
- `SCREEN_STOP` (`0x0053`): sharer client to chat server, then chat server to room participants to end the share.

Remote control:

- `REMOTE_EVENT` (`0x0060`): controller client to chat server, then chat server to sharer if that controller is currently granted.
- `REMOTE_REQUEST` (`0x0061`): viewer client to chat server, then chat server to the active sharer to ask for control.
- `REMOTE_GRANT` (`0x0062`): sharer client to chat server to grant, deny, or revoke control, then chat server to room participants with the current grant state.

Whiteboard and export:

- `DRAW_EVENT` (`0x0070`): client to chat server, sends a local whiteboard drawing operation.
- `DRAW_BROADCAST` (`0x0071`): chat server to clients, relays a drawing operation with server-defined ordering.
- `DRAW_ACK` (`0x0072`): chat server to drawing client, acknowledges the server sequence number.
- `WHITEBOARD_SYNC` (`0x0073`): chat server to client, sends full whiteboard state to a joining participant.
- `EXPORT_REQUEST` (`0x0074`): client to chat server, requests whiteboard export.
- `FILE_TRANSFER` (`0x0075`): chat server to client, sends exported file bytes.

Friends:

- `FRIEND_REQUEST` (`0x0080`): client to chat server, sends a friend request by username.
- `FRIEND_RESPONSE` (`0x0081`): client to chat server, accepts or rejects a pending friend request.
- `FRIEND_LIST` (`0x0082`): chat server to client, sends the current friend list and online states.
- `FRIEND_UPDATE` (`0x0083`): chat server to client, sends a single friend-related event such as status change, incoming request, or accepted request.

Load balancer, health, and system:

- `CONNECT_REQUEST` (`0x00F0`, plaintext): client to load balancer, requests a chat server assignment, optionally for a room code.
- `CONNECT_RESPONSE` (`0x00F1`, plaintext): load balancer to client, returns `server_ip` and `server_port`.
- `HEALTH_QUERY` (`0x00F2`, plaintext): load balancer to chat server, asks for health and connection count.
- `HEALTH_RESPONSE` (`0x00F3`, plaintext): chat server to load balancer, returns connection count and CPU load.
- `HEARTBEAT` (`0x00FE`): client and chat server, keeps the encrypted chat connection active and responsive.
- `ERROR` (`0x00FF`): server or load balancer to client, reports a protocol, routing, auth, room, or feature error. It is plaintext only when sent on a plaintext connection with no AES key; otherwise it follows the normal encrypted path.

### 3.6 How a Packet Is Sent and Received End to End

Consider a normal `CHAT_MESSAGE`. At the UI level, the user presses Send and the client prepares a payload containing the room code, message content, and message type. That payload eventually reaches `ConnectionManager.send(packet_type, payload)`. `ConnectionManager.send()` first checks that the connection is running and has a socket, then enters `_send_lock` so no other thread can write to the same TCP stream at the same time. Inside the lock it calls `shared.protocol.send_packet(self._sock, packet_type, payload, self._aes_key)`.

`send_packet()` delegates packet construction to `encode_packet()`. `encode_packet()` JSON-encodes the payload dictionary using UTF-8. Because `CHAT_MESSAGE` is not in the plaintext set and the connection manager has an AES key after the handshake, `encode_packet()` builds the 12-byte AAD prefix, calls `aes_encrypt()`, receives a random nonce, ciphertext, and authentication tag, packs the 40-byte header, concatenates the ciphertext, and returns the final bytes. `send_packet()` then writes the complete encoded packet with `sock.sendall()`.

On the chat server, `ClientHandler._main_loop()` is blocked in `read_packet(self._sock, self._aes_key)`. `read_packet()` reads exactly 40 bytes with `_recv_exact()`, validates and decodes the header with `decode_header()`, then reads exactly the announced payload length. Since the nonce is nonzero, it rebuilds the AAD, calls `aes_decrypt()`, decodes the resulting UTF-8 JSON, and returns a `Packet` object containing `PacketType.CHAT_MESSAGE` and the decoded payload dictionary.

The server then calls `_dispatch()`, which maps `PacketType.CHAT_MESSAGE` to `_handle_chat_message()`. The handler validates the room context, stores the message through the message service, converts the stored message model to a dictionary, attaches the room code, and sends the resulting `CHAT_MESSAGE` to each target client handler. Each server-side `ClientHandler.send()` uses its own `_send_lock` and the same `send_packet()` function, this time with the recipient connection's AES key, so each recipient gets a packet encrypted specifically for their TCP session.

On the recipient client, `ConnectionManager._receiver_loop()` continuously calls `read_packet(self._sock, self._aes_key)`. When the relayed `CHAT_MESSAGE` arrives, it is decoded and decrypted in the same fixed-header, length-read, AAD-verified way. The receiver thread puts the resulting `Packet` into `packet_queue`. As described in Parts 1 and 2, the UI thread polls that queue on a timer instead of letting the socket thread update Qt widgets directly. When the UI sees `CHAT_MESSAGE`, it appends the message to the room's message list and refreshes the chat view.

The important cross-feature point is that the same lifecycle carries `SCREEN_FRAME`, `SCREEN_RELAY`, and `REMOTE_EVENT`. The packet type and JSON payload change, but `ConnectionManager.send()`, `send_packet()`, `encode_packet()`, `_recv_exact()`, `decode_header()`, and `read_packet()` are the common wire path.

### 3.7 Load Balancer Packet Flow

The load-balancer flow is separate from the encrypted chat-server connection. The client calls `request_server(lb_host, lb_port, room_code=None)`. That function creates a TCP socket to the load balancer, builds an empty payload for a generic assignment, or a payload containing `room_code` when joining a known room, and sends a plaintext `CONNECT_REQUEST` with `send_packet(..., aes_key=None)`.

The load balancer responds with either `ERROR` or `CONNECT_RESPONSE`. A successful `CONNECT_RESPONSE` contains `server_ip` and `server_port`. `request_server()` verifies that the response type is correct, extracts those two fields, returns them to the caller, and closes the socket in a `finally` block. The client then uses that returned address to establish the real chat-server connection and perform the RSA/AES handshake described earlier.

This connection is plaintext and short-lived by design. It carries no password, JWT, chat content, screen frame, or remote-control event. Its only job is routing. Encrypting it persistently would require the load balancer to participate in session management or act as a proxy, which would complicate the architecture and keep it in the hot path for real-time features. The trade-off is that routing metadata is visible, but the sensitive application data moves only after the client reaches the assigned chat server and establishes AES-GCM transport encryption.

### 3.8 Heartbeat and Connection Health

The client connection manager starts a heartbeat thread after a successful chat-server handshake. `_heartbeat_loop()` sleeps for `HEARTBEAT_INTERVAL`, which is 15 seconds, then sends a `HEARTBEAT` packet containing the current integer timestamp. It uses the normal `ConnectionManager.send()` path, so heartbeats are encrypted on the chat-server connection and protected by `_send_lock` like any other packet.

The server-side `ClientHandler._main_loop()` sets the socket timeout to `HEARTBEAT_TIMEOUT`, which is 45 seconds. Any valid packet read resets activity by updating `_last_heartbeat`, and a received `HEARTBEAT` is dispatched to `_handle_heartbeat()`. The server responds with its own encrypted `HEARTBEAT` packet containing a fresh timestamp. If the server stops receiving packets for 45 seconds, the socket read times out, the loop breaks, and cleanup runs. Cleanup removes the client from rooms, stops or clears screen-share and remote-control state when relevant, notifies remaining participants, unregisters the client, and closes the socket.

The client side does not enforce a separate numeric heartbeat timeout in `ConnectionManager`. It detects failure when `read_packet()` raises `ConnectionError`, when the receiver loop hits another active error, or when `send_packet()` fails. In those cases `_handle_disconnect()` marks the connection stopped and invokes the UI disconnect callback. This means server-side timeout is the primary heartbeat enforcement mechanism, while the client relies on socket read/write failures to discover broken connections.

### 3.9 Thread Safety on Send

Both client and server protect socket writes with a send lock. On the client, `ConnectionManager._send_lock` wraps the call to `send_packet()`. On the server, each `ClientHandler` has its own `_send_lock` that does the same for that client's socket. This matters because many parts of the application can send over the same TCP connection.

On the client, the UI thread can send chat messages, room joins, friend requests, screen-control requests, and revoke actions. The screen-sharing send thread can send `SCREEN_FRAME` packets. The remote-control sender can emit `REMOTE_EVENT` packets while the user moves the mouse or types over the frame widget. The heartbeat thread sends `HEARTBEAT` packets every 15 seconds. Without a lock, two threads could call `sock.sendall()` at nearly the same time, causing one packet's header to be written between another packet's header and payload. TCP would faithfully deliver those bytes, but the receiver would see a corrupted stream. The lock ensures each complete encoded packet is written as one uninterrupted send operation from the application's point of view.

The same reasoning applies on the server. A client handler may send a direct response, a heartbeat reply, a room broadcast, a friend update, a screen-share status update, or a remote-control event relay. The per-handler lock prevents these writes from interleaving on that recipient's socket. It does not serialize the whole server; each client handler has its own lock, so different clients can still be sent to concurrently.

### 3.10 Screen Frame Packets Specifically

`SCREEN_FRAME` uses the same protocol machinery as `CHAT_MESSAGE`, but the payload is much larger and contains binary image data represented as text. The JSON envelope includes the room code, a sequence number, frame width, frame height, and `jpeg_b64`, a base64-encoded JPEG frame. Because JSON cannot directly carry arbitrary bytes, base64 turns the JPEG bytes into ASCII text at the cost of roughly one third additional size. The entire JSON object is then encrypted as one AES-GCM payload like any other non-plaintext packet.

The fixed screen-sharing settings documented in Phase 2 are 30 FPS, JPEG quality 75, and 100 percent scale. The exact packet size is not constant because JPEG size depends on the captured desktop content, resolution, and visual complexity. The protocol limit that matters is exact: `MAX_PAYLOAD_SIZE` is 16 MB, and `decode_header()` rejects packets whose payload length exceeds that limit. Phase 2's notes state that a typical 1080p screenshot at quality 75 remains comfortably under that ceiling even after base64 expansion. If a future setting increased scale, resolution, or quality enough to exceed 16 MB, the receiver would reject the packet before attempting to decode or decrypt an oversized payload.

The server treats `SCREEN_FRAME` differently from a text message at the feature layer, not at the protocol layer. After `read_packet()` has already decrypted and JSON-decoded the packet, the screen handler verifies that the sender is in the room and is the active sharer. It then builds a `SCREEN_RELAY` payload containing the room code, sharer id, original `jpeg_b64`, width, height, and sequence number. The server copies `jpeg_b64` verbatim; it does not decode the JPEG, inspect pixels, resize, recompress, or render anything. That keeps CPU-heavy image work on the clients and lets the same encrypted packet infrastructure carry high-frequency screen frames without changing the wire protocol.
