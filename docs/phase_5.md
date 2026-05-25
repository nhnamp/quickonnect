# Phase 5: Integration, Polish & Hardening

**Status**: Complete  
**Depends on**: Phases 1–4  
**Tests**: 17 new tests (53 total, all passing)

---

## Overview

Phase 5 integrates and hardens the features built in Phases 1–4, adding room
management UI, file/image messaging, E2E encryption for DMs, automatic
reconnection, graceful server shutdown, error hardening, and demo setup scripts.

---

## Features Delivered

### 5.1 Room Management UI

**New UI controls in `client/ui/chat_widget.py`:**
- **Participant list** — right panel showing all users in the current room
  with `👤` avatar indicators, updated in real-time on join/leave events
- **Copy room code** — `📋 Copy Code` button copies the room code to clipboard
  with a brief `✓ Copied!` confirmation
- **Invite friend** — `📨 Invite` button opens a dialog to enter a username;
  sends `ROOM_INVITE` (0x0024) to the server, which forwards
  `ROOM_INVITE_NOTIFY` (0x0025) to the target user
- **Leave room** — `🚪 Leave` button sends `LEAVE_ROOM` and removes the room
  from the local list

**Server-side (`server/client_handler.py`):**
- `_handle_room_invite()` — looks up the target user locally; if found, sends
  `ROOM_INVITE_NOTIFY` directly; otherwise publishes to Redis `room_invites`
  channel for cross-server delivery
- `_handle_room_invite_pubsub()` in `server/main.py` — subscribes to
  `room_invites` and delivers to local clients

**Client-side (`client/ui/main_window.py`):**
- `_handle_room_invite()` — shows a `QMessageBox.question` dialog with accept/
  reject; on accept, sends `JOIN_ROOM`

### 5.2 File & Image Messaging

**Chat widget (`client/ui/chat_widget.py`):**
- `📎` attach button opens `QFileDialog` with file type filters
- File size limit: 10 MB (validated client-side and server-side)
- Images (`.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`) are base64-encoded and sent
  with `msg_type: "image"`; they render inline as thumbnails (max 300px wide)
- Other files are sent with `msg_type: "file"` and display as
  `📁 filename (size)` in the message view
- `filename` and `filesize` metadata are passed through the server untouched

**Server-side validation (`server/client_handler.py`):**
- `msg_type` validation: rejects anything other than `text`, `image`, `file`
- Content length validation: base64 content capped at ~14 MB (→ 10 MB decoded)
  with a `413` error response

### 5.3 E2E Encryption

**Crypto layer (`shared/crypto.py`):**
- `e2e_encrypt_message(plaintext, recipient_pub_key) → dict` — generates a
  random AES-256 key, encrypts the message body with AES-GCM, wraps the AES
  key with the recipient's RSA-2048 public key, returns a dict with four
  base64 fields: `encrypted_content`, `encrypted_key`, `nonce`, `tag`
- `e2e_decrypt_message(encrypted_data, private_key) → str` — unwraps the AES
  key, decrypts the message; raises `ValueError` on any failure
- `serialize_private_key(key) → bytes` — PEM-encodes the private key (no
  password) for persistent storage
- `deserialize_private_key(pem) → key` — loads a PEM private key from bytes

**Key storage (`client/storage/local_store.py`):**
- `save_user_keypair(username, priv_pem, pub_pem)` — persists the long-term
  RSA keypair to `<data_dir>/keys/<username>_private.pem`
- `load_user_keypair(username) → (priv_pem, pub_pem) | None`
- `save_peer_public_key(username, pub_pem)` — caches in `keys/peers/`
- `load_peer_public_key(username) → bytes | None`

**Key exchange protocol:**
- `PUBLIC_KEY_ANNOUNCE` (0x0090) — client sends its E2E public key on login
  and after reconnection
- `PUBLIC_KEY_REQUEST` (0x0091) — client requests a peer's E2E public key
- `PUBLIC_KEY_RESPONSE` (0x0092) — server responds with the peer's public key
  (or `found: false` if not online)
- Server stores `_e2e_public_key` per `ClientHandler`; keys are ephemeral to
  the connection (re-announced on reconnect)

### 5.4 Reconnection Handling

**ConnectionManager (`client/network/connection.py`):**
- `enable_reconnect(host, port, auth_payload, auth_type, room_codes)` — stores
  credentials and server address for automatic reconnection
- `disable_reconnect()` — disables auto-reconnect (called during intentional
  logout via `disconnect()`)
- `update_room_codes(codes)` — updates the room list for reconnection (called
  on each `ROOM_STATE` received)
- On disconnect:
  1. Spawns a reconnect thread with exponential backoff (1s → 2s → 4s → 8s →
     max 30s, up to 10 attempts)
  2. On each attempt: calls `on_reconnecting(attempt, max_attempts)` callback,
     then connects, handshakes, re-authenticates, and rejoins rooms
  3. On success: calls `on_reconnected()` and restarts receiver/heartbeat
  4. On final failure: calls `on_disconnected(reason)`

**Login window (`client/ui/login_window.py`):**
- After successful auth, calls `enable_reconnect()` with the JWT token and
  the actual server address (not the LB address, since the connection was
  already redirected by the load balancer)

**Main window (`client/ui/main_window.py`):**
- Shows an orange reconnection banner: `⟳ Reconnecting... attempt N/10`
- Hides the banner and shows a status bar message on success
- Re-announces E2E public key after successful reconnection

### 5.5 Graceful Server Shutdown

**Server (`server/main.py`):**
- `ChatServer.stop()` now sends `SERVER_SHUTDOWN` (0x00FD) to all connected
  clients with `{"message": "Server is shutting down", "reconnect_delay": 5}`
  before disconnecting them
- Waits 1 second for clients to process the notification

**Client (`client/ui/main_window.py`):**
- Handles `SERVER_SHUTDOWN` by showing a status bar warning

### 5.6 Error Handling Pass

- Chat message `msg_type` is validated against `("text", "image", "file")`
- File content length is capped at ~10 MB with a `413` error response
- Room invite validates `target_username` and `room_code` before forwarding
- Public key request validates `target_username` before lookup
- Server graceful shutdown wraps `send()` calls in try/except
- ConnectionManager `_handle_disconnect` closes the socket before triggering
  callbacks to avoid blocking recv

### 5.7 Performance Tuning

- Reconnection uses exponential backoff to avoid thundering herd
- Room codes are updated lazily on each ROOM_STATE (no separate sync)
- QTimer packet polling remains at 60 Hz (16ms)

### 5.8–5.10 Demo Scripts

**`scripts/demo_launch.py`:**
- Checks Redis and PostgreSQL connectivity before starting
- Starts N chat servers (configurable, default 1) on sequential ports
- Starts the load balancer
- Waits for all services to be ready, prints connection instructions
- Clean shutdown on Ctrl+C

**`scripts/ngrok_setup.py`:**
- Starts an ngrok TCP tunnel for the load balancer port
- Queries ngrok's local API for the public URL
- Prints connection instructions for remote clients

---

## Protocol Changes

| Packet Type | Code | Direction | Purpose |
|---|---|---|---|
| `ROOM_INVITE` | 0x0024 | C→S | Request to invite a user to a room |
| `ROOM_INVITE_NOTIFY` | 0x0025 | S→C | Invitation notification to target user |
| `PUBLIC_KEY_ANNOUNCE` | 0x0090 | C→S | Announce E2E public key to server |
| `PUBLIC_KEY_REQUEST` | 0x0091 | C→S | Request a peer's E2E public key |
| `PUBLIC_KEY_RESPONSE` | 0x0092 | S→C | Respond with a peer's E2E public key |
| `SERVER_SHUTDOWN` | 0x00FD | S→C | Server shutdown notification |

---

## Files Modified

| File | Changes |
|---|---|
| `shared/constants.py` | Added 6 new packet types |
| `shared/crypto.py` | Added 4 E2E encryption functions |
| `client/network/connection.py` | Added auto-reconnect with exponential backoff |
| `client/storage/local_store.py` | Added keypair and peer key storage |
| `client/ui/chat_widget.py` | Added file/image messaging, participant list, invite, leave |
| `client/ui/main_window.py` | Added reconnect banner, invite handler, E2E keys, shutdown |
| `client/ui/login_window.py` | Enabled auto-reconnect after successful auth |
| `server/client_handler.py` | Added room invite, public key exchange, file validation |
| `server/main.py` | Added graceful shutdown, room invite pub/sub |

## Files Created

| File | Purpose |
|---|---|
| `scripts/demo_launch.py` | Demo environment launcher |
| `scripts/ngrok_setup.py` | Ngrok tunnel setup for remote demos |
| `tests/test_phase5.py` | 17 tests for Phase 5 features |

---

## Test Results

```
tests/test_phase5.py     17 passed
tests/test_crypto.py     22 passed
tests/test_protocol.py   14 passed
Total:                   53 passed, 0 failed
```
