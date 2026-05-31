# Verify

**Baseline Setup**
Run this before most demos:

```bash
cd /home/nhaatjnamphan/Workspace/coding/QuicKonNect
source .venv/bin/activate
docker compose up -d
python scripts/setup_db.py
python scripts/run_server.py 9001
python scripts/run_server.py 9002
python scripts/run_lb.py
python scripts/run_client.py
```

Open extra terminals for the second/third clients.

## 1. I/O: File And Network I/O
**Evidence in code**

- TCP packet read/write: [shared/protocol.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:28), [shared/protocol.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:107)
- Client socket connection: [client/network/connection.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:50)
- Load balancer TCP request: [client/network/lb_client.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/lb_client.py:16)
- File I/O for saved session: [client/storage/local_store.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/storage/local_store.py:16)
- Screen capture input: [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:129)

**How to verify**

1. Register or login once.
2. Check session file was written:

```bash
cat ~/.quickonnect/session.json
```

3. Send a chat message between two clients.
4. Confirm network I/O with:

```bash
ss -tnp | grep -E '9000|9001|9002'
```

This proves both file I/O and socket I/O are used.

## 2. Database
**Evidence in code**

- PostgreSQL pool: [server/services/db.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/db.py:12)
- Users/sessions schema: [scripts/setup_db.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/scripts/setup_db.py:27)
- Message storage: [server/services/message_service.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:12)
- Friend storage: [server/services/friend_service.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/friend_service.py:10)

**How to verify**

After registering users and sending messages:

```bash
psql -U quickonnect -d quickonnect -c "\dt"
psql -U quickonnect -d quickonnect -c "SELECT id, username, password_hash FROM users;"
psql -U quickonnect -d quickonnect -c "SELECT room_id, sender_id, content, sent_at FROM messages ORDER BY sent_at DESC LIMIT 5;"
psql -U quickonnect -d quickonnect -c "SELECT * FROM friendships;"
```

Point out that `password_hash` is BCrypt text, not the plain password.

## 3. Thread
**Evidence in code**

- One server thread accepts clients: [server/acceptor.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:10)
- One `ClientHandler` thread per client: [server/acceptor.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:33)
- Client receiver and heartbeat threads: [client/network/connection.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:60)
- Screen capture/send threads: [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:88)
- Remote-control execution thread: [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:279)
- Load balancer per-client threads: [loadbalancer/main.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/main.py:41)

**How to verify**

Run several clients, then on Linux:

```bash
ps -eLf | grep -E 'run_server|run_client|run_lb'
```

During screen sharing, explain the active thread model: capture thread, send thread, receiver thread, heartbeat thread, UI thread, and remote-control executor thread.

## 4. Sign Up / Sign In
**Evidence in code**

- Register/login UI worker: [client/ui/login_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/login_window.py:18)
- Register request: [client/ui/login_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/login_window.py:37)
- Login request: [client/ui/login_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/login_window.py:41)
- Server register/login handling: [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:121)
- BCrypt + JWT: [server/services/auth_service.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/auth_service.py:24)

**How to verify**

1. Register `user1`.
2. Logout.
3. Login as `user1`.
4. Close and reopen the app.
5. It resumes using saved JWT from `~/.quickonnect/session.json`.

Database proof:

```bash
psql -U quickonnect -d quickonnect -c "SELECT username, password_hash FROM users;"
psql -U quickonnect -d quickonnect -c "SELECT user_id, expires_at FROM sessions;"
```

## 5. Multi Client
**Evidence in code**

- Server listens with queue size 64: [server/acceptor.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:25)
- Each accepted socket starts a new handler: [server/acceptor.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:33)
- Server tracks connected clients: [server/main.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:32)
- Room broadcast loop for messages: [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:408)

**How to verify**

1. Open 3 clients.
2. Register/login as `user1`, `user2`, `user3`.
3. One user creates a regular room.
4. Other users join the same room code.
5. Send chat messages from all three clients.
6. Start screen sharing from one client and verify others receive the screen.

## 6. Multi Server
**Evidence in code**

- Two default chat servers in LB config: [loadbalancer/config.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/config.py:24)
- Server id/port config: [server/config.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/config.py:6)
- LB health checks multiple servers: [loadbalancer/health_checker.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/health_checker.py:26)
- Server registry in Redis: [server/main.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:243)

**How to verify**

Start both:

```bash
python scripts/run_server.py 9001
python scripts/run_server.py 9002
python scripts/run_lb.py
```

Then:

```bash
redis-cli HGETALL servers
```

You should see entries for `server-9001` and `server-9002`.

## 7. Cryptography
**Evidence in code**

- RSA-2048 key generation: [shared/crypto.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/crypto.py:23)
- AES-256-GCM key generation: [shared/crypto.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/crypto.py:70)
- AES nonce/tag encryption: [shared/crypto.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/crypto.py:75)
- Packet encryption with AAD: [shared/protocol.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:47)
- Encrypted read/decrypt: [shared/protocol.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:96)
- BCrypt password hashing: [shared/crypto.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/crypto.py:99)

**How to verify with tests**

```bash
.venv/bin/pytest tests/ -q
```

Current result: `36 passed`.

**How to verify with packet sniffing**

Run this before sending a message:

```bash
sudo tcpdump -i any -s0 -w /tmp/qknt.pcap 'tcp port 9001 or tcp port 9002'
```

Send a unique message, for example:

```text
SECRET_QKNT_ENCRYPTION_TEST_123
```

Stop tcpdump, then check:

```bash
strings /tmp/qknt.pcap | grep SECRET_QKNT_ENCRYPTION_TEST_123
```

Expected result: no match. You may see `QKNT` headers, but not the plaintext message, because normal packets are AES-GCM encrypted after handshake.

## 8. Demo Via LAN
**Evidence in code**

- Server binds to all interfaces by default: [server/config.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/config.py:6)
- LB binds to all interfaces by default: [loadbalancer/config.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/config.py:6)
- LB advertises LAN-reachable address instead of bad localhost address: [loadbalancer/router.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/router.py:90)

**How to verify**

On host laptop:

```bash
hostname -I
```

On second laptop:

```powershell
Test-NetConnection <host-ip> -Port 9000
Test-NetConnection <host-ip> -Port 9001
Test-NetConnection <host-ip> -Port 9002
```

Then run client on second laptop and set:

```text
LB Host: <host-ip>
LB Port: 9000
```

Demo regular room chat, screen sharing, and remote control. Use a **regular room**, not a DM room, for screen sharing.

## 9. Demo Via Internet
Use ngrok TCP tunnels or VPN. For ngrok, expose all three app ports:

```text
9000 load balancer
9001 chat server 1
9002 chat server 2
```

Example ngrok output:

```text
LB:          0.tcp.ngrok.io:11111 -> localhost:9000
Server9001: 2.tcp.ngrok.io:22222 -> localhost:9001
Server9002: 4.tcp.ngrok.io:33333 -> localhost:9002
```

Start LB with public server addresses:

```bash
CHAT_SERVERS="server-9001:2.tcp.ngrok.io:22222,server-9002:4.tcp.ngrok.io:33333" python scripts/run_lb.py
```

Remote client login:

```text
LB Host: 0.tcp.ngrok.io
LB Port: 11111
```

Then repeat regular-room chat and screen-sharing demo.

## 10. Load Balancing
**Evidence that it is self-built**

- Custom LB socket server: [loadbalancer/main.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/main.py:30)
- Per-client LB routing thread: [loadbalancer/main.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/main.py:41)
- Health checker queries chat servers: [loadbalancer/health_checker.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/health_checker.py:63)
- Least-loaded selection by connection count and CPU: [loadbalancer/health_checker.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/health_checker.py:46)
- Room-aware routing and Redis room pin: [loadbalancer/router.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/router.py:66)
- Writes room pin to Redis: [loadbalancer/router.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/router.py:137)

**How to verify**

1. Start two servers and LB.
2. Create a regular room.
3. Check Redis pin:

```bash
redis-cli KEYS 'room:*'
redis-cli GET 'room:<ROOM_CODE>'
```

Expected result:

```text
server-9001
```

or:

```text
server-9002
```

4. Join the same room from another client.
5. LB should route that client to the same pinned server.
6. Stop one server and observe LB stops routing to it after health checks.

This proves the project implements its own room-aware load balancer instead of relying on an external load-balancing library.

## 11. Core features
This section focuses on the two core user-facing features that should be demonstrated clearly: sending messages, and screen sharing with remote control. Both features run on top of the same Phase 1 foundation: an authenticated client, a room, the encrypted `ConnectionManager.send()` path, server-side packet dispatch, and UI-thread packet polling.

### 11.1 Send messages
**Feature logic**

Sending a message starts in the chat UI. The user must first be in a room, either a regular room created/joined from the Chat tab or a deterministic DM room opened from the Friends tab. When the user presses Enter or clicks Send, `ChatWidget._on_send()` reads the input text, ignores empty messages, and emits a `CHAT_MESSAGE` packet payload containing `room_code`, `content`, and `msg_type`. `MainWindow._send_packet()` forwards that signal into `ConnectionManager.send()`, which serializes concurrent writes with `_send_lock` and calls the shared protocol `send_packet()` helper.

At the wire level, the message is a JSON payload carried by the custom TCP protocol. Since `CHAT_MESSAGE` is not in the plaintext packet set, the shared protocol encrypts the JSON payload with the AES session key before writing to the socket. The server's `ClientHandler._main_loop()` reads and decrypts packets, then `_dispatch()` routes `CHAT_MESSAGE` into `_handle_chat_message()`.

For a regular room, `_handle_chat_message()` verifies that the room exists locally, stores the message in PostgreSQL through `MessageService.store_message()`, attaches the sender name and room code, then broadcasts the stored message back to every connected client in that room. The sender receives their own stored message through the same broadcast path as everyone else, which proves that the UI is rendering the server-confirmed message rather than a fake local echo. On the receiving client, the network receiver thread puts the decoded packet into `packet_queue`; the UI timer in `MainWindow` polls the queue, sees `PacketType.CHAT_MESSAGE`, and calls `ChatWidget.add_message()` to append and render it.

Message history is loaded on room join. After a successful `JOIN_ROOM`, the server sends `ROOM_STATE`, then asks `MessageService.get_history()` for the latest 100 messages. The query reads newest-first from PostgreSQL for efficiency, then reverses the list so the client receives messages oldest-first. The client handles `MESSAGE_HISTORY` by loading those messages into the room view before new live messages arrive.

Direct messages use the same `CHAT_MESSAGE` packet and storage path, but add server-agnostic delivery behavior. A DM room code begins with `DM-`, and the server checks whether the sender is actually present in the local room client map before sending. If not, it lazy-joins the sender first, which ensures the sender sees their own message. After the normal local broadcast, the server extracts the other username from the DM room code. If that recipient is connected to the same server but is not in the local room, it sends directly to that handler. If the recipient is on another server, the message is published to Redis `dm_messages`; the recipient's server receives the pub/sub event and forwards the same `CHAT_MESSAGE` packet to the local client. PostgreSQL remains the durable source of history.

**Source code evidence**

| Evidence | Source |
|---|---|
| `CHAT_MESSAGE` and `MESSAGE_HISTORY` packet IDs are defined as protocol-level packet types. | [shared/constants.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/constants.py:38) |
| The Send button and Enter key produce a `CHAT_MESSAGE` payload with `room_code`, `content`, and `msg_type`. | [client/ui/chat_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:141) |
| Incoming messages auto-create a room entry if needed and append to the local message list. | [client/ui/chat_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:155) |
| Message history is merged into the room view when `MESSAGE_HISTORY` arrives. | [client/ui/chat_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:167) |
| The main window dispatches `MESSAGE_HISTORY` and `CHAT_MESSAGE` packets to the chat widget on the UI thread. | [client/ui/main_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:213), [client/ui/main_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:221) |
| All UI-originated sends go through `ConnectionManager.send()`. | [client/ui/main_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:271) |
| Concurrent sends are protected by `_send_lock` before calling the shared `send_packet()` function. | [client/network/connection.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:82) |
| Shared protocol JSON-encodes payloads, encrypts non-plaintext packets, and writes with `sock.sendall()`. | [shared/protocol.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:39), [shared/protocol.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/protocol.py:107) |
| Server packet dispatch maps `CHAT_MESSAGE` to `_handle_chat_message()`. | [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:205) |
| The server lazy-joins DM senders by membership, stores messages, broadcasts to local room clients, and uses direct or Redis delivery for DM recipients. | [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:348) |
| Messages are inserted into the PostgreSQL `messages` table and returned as `Message` models. | [server/services/message_service.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:13) |
| History reads the last 100 room messages and returns them oldest-first. | [server/services/message_service.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/services/message_service.py:50) |
| Redis `dm_messages` publishes and receives cross-server DM delivery events. | [server/main.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:137), [server/main.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:219) |
| The database schema includes durable `rooms`, `room_participants`, and `messages` tables. | [scripts/setup_db.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/scripts/setup_db.py:55), [scripts/setup_db.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/scripts/setup_db.py:72) |

**How to verify regular room messaging**

1. Start the baseline setup from the top of this file.
2. Open two clients and login as two different users, for example `alice` and `bob`.
3. In Alice's Chat tab, click Create. Note the generated room code.
4. In Bob's Chat tab, click Join and enter the same room code. This must be a regular room code, not a `DM-...` room.
5. From Alice, send a unique message:

```text
MSG_VERIFY_ALICE_001
```

6. Expected result: Bob sees `[time] alice: MSG_VERIFY_ALICE_001`, and Alice also sees the message because the server broadcasted the stored message back to the sender.
7. From Bob, send:

```text
MSG_VERIFY_BOB_001
```

8. Expected result: Alice sees Bob's reply in the same room.
9. Verify PostgreSQL persistence:

```bash
psql -U quickonnect -d quickonnect -c "SELECT r.room_code, u.username, m.content, m.sent_at FROM messages m JOIN rooms r ON m.room_id = r.id JOIN users u ON m.sender_id = u.id WHERE m.content LIKE 'MSG_VERIFY_%' ORDER BY m.sent_at DESC LIMIT 10;"
```

10. Close Bob's client, reopen it, login again, and join the same room code.
11. Expected result: Bob receives `MESSAGE_HISTORY` and sees the recent messages without Alice resending them.

**How to verify DM messaging**

1. Start two clients as two users who are friends.
2. Have Alice double-click Bob in the Friends tab to open the deterministic `DM-alice-bob` room.
3. Alice sends:

```text
DM_VERIFY_ALICE_001
```

4. Expected result: Bob sees the DM room appear and sees Alice's message even if Bob did not manually open the DM first.
5. Without restarting or rejoining, Bob replies:

```text
DM_VERIFY_BOB_001
```

6. Expected result: Bob sees their own reply immediately, and Alice sees it too. This verifies the membership-based lazy-join fix for sender echo.
7. If two chat servers are running, repeat the test while Alice and Bob are connected to different servers. The result should be the same, proving Redis `dm_messages` handles cross-server DM delivery.

### 11.2 Screen sharing and remote control
**Feature logic**

Screen sharing is a regular-room feature. The user first joins a room through the chat flow, and the Chat widget emits `room_changed` so the Screen tab knows which room it is attached to. When the sharer clicks Share Screen, `ScreenShareWidget` starts `ScreenCaptureEngine` and also starts the `RemoteControlExecutor` so the host is ready if another user later requests control. After local capture startup succeeds, the widget emits `SCREEN_START` to the server.

The capture engine uses a two-thread pipeline. The capture thread performs a real `mss` screen grab, converts the frame to a detached `QImage` using explicit RGB bytes, encodes it to JPEG with Qt's `QBuffer`, emits a local preview image for the sharer, and enqueues the JPEG. The queue is bounded to 3 frames and uses drop-oldest behavior, so a slow network cannot build up stale frames. The send thread dequeues the newest available JPEG frames, base64-encodes them, and sends `SCREEN_FRAME` packets through the same `ConnectionManager.send()` path used by chat messages.

The server keeps screen state inside the room through `ScreenRelayState`. `SCREEN_START` calls `start_share()`, which allows one active sharer per room and returns an error if another participant is already sharing. `SCREEN_FRAME` is accepted only from the current sharer. The server does not decode the JPEG; it copies `jpeg_b64`, frame size, and sequence number into a `SCREEN_RELAY` payload and broadcasts it to every other participant in the room. Viewers decode the base64 JPEG on the UI thread and render it in `FrameLabel`.

Late joiners receive screen state through `ROOM_STATE`. When a user joins a room that already has an active share, `_handle_join_room()` includes a `screen` block containing the current sharer and controller. The Screen tab applies that state immediately, then renders the next incoming `SCREEN_RELAY` frame. No separate setup packet is needed.

Remote control is an explicit grant flow. A viewer clicks Request Control, sending `REMOTE_REQUEST`. The server forwards that request only to the active sharer. The sharer sees a confirmation dialog. If they allow it, the sharer sends `REMOTE_GRANT` with `granted=true` and the target user id. The server records the controller in `ScreenRelayState` and broadcasts the grant to the room. On the controller client, `RemoteControlSender` is installed as a Qt event filter on the frame widget. It captures mouse movement, mouse press/release, scroll, and key press/release, converts frame-relative mouse positions into normalized `0.0` to `1.0` coordinates, and sends `REMOTE_EVENT`.

The server forwards `REMOTE_EVENT` only if the sender is the currently granted controller. On the sharer client, `ScreenShareWidget.on_remote_event()` submits the event into `RemoteControlExecutor`. The executor runs pyautogui calls on a dedicated background thread, converts normalized coordinates to the sharer's real screen pixels using `pyautogui.size()`, and performs mouse or keyboard actions. Revocation is also server-authoritative: the sharer clicks Revoke Control, sends `REMOTE_GRANT(granted=false)`, the server clears the controller, broadcasts the update, and the viewer removes the event filter so input stops immediately.

Disconnect cleanup is handled on the server. If the sharer disconnects or leaves the room, the server clears the share and broadcasts `SCREEN_STOP`. If the controller disconnects, only the controller grant is cleared and the share can continue.

**Source code evidence**

| Evidence | Source |
|---|---|
| Screen and remote-control packet IDs are part of the shared protocol enum. | [shared/constants.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/constants.py:45), [shared/constants.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/shared/constants.py:50) |
| The main window creates the Screen tab, wires it to the chat room selection, and dispatches all `SCREEN_*` and `REMOTE_*` packets to it. | [client/ui/main_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:172), [client/ui/main_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:234) |
| The Screen tab tracks the current room and applies late-join screen state from `ROOM_STATE`. | [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:147), [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:160) |
| The Share button starts capture, starts the remote-control executor, sends `SCREEN_START`, and updates controls. | [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:295), [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:311) |
| Incoming `SCREEN_RELAY` packets are decoded from base64 JPEG and rendered into the frame label. | [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:195) |
| Remote-control request, grant, event submission, input enable, and input disable are implemented in the Screen tab. | [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:206), [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:242), [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:276), [client/ui/screen_share_widget.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/screen_share_widget.py:457) |
| Capture settings are fixed at queue depth 3, 30 FPS, JPEG quality 75, and scale 100%. | [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:37) |
| `ScreenCaptureEngine.start()` performs a capture preflight, then starts separate capture and send threads. | [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:78) |
| The capture loop grabs with `mss`, builds a `QImage`, encodes JPEG, emits a local preview, and enqueues frames. | [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:129) |
| The bounded queue drops oldest frames when full. | [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:178) |
| The send loop sends `SCREEN_FRAME` with `room_code`, frame size, sequence number, and `jpeg_b64`. | [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:190) |
| Frame conversion, JPEG encoding, and JPEG decoding are implemented with Qt image APIs. | [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:282), [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:298), [client/features/screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:311) |
| Viewer-side remote input is attached as an event filter and uses focus plus mouse tracking. | [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:107) |
| Mouse, wheel, and keyboard events are captured and sent as `REMOTE_EVENT` packets. | [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:136), [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:176), [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:198), [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:222) |
| Viewer coordinates are normalized against the actually displayed frame geometry. | [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:163) |
| Host-side pyautogui execution runs on a dedicated worker thread, maps normalized coordinates to screen pixels, and performs mouse/key actions. | [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:260), [client/features/remote_control.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:319) |
| Each active room stores a `ScreenRelayState`. | [server/room_manager.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/room_manager.py:58), [server/room_manager.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/room_manager.py:89) |
| `ScreenRelayState` enforces one sharer and records/clears the controller. | [server/features/screen_relay.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/features/screen_relay.py:24), [server/features/screen_relay.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/features/screen_relay.py:50), [server/features/screen_relay.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/features/screen_relay.py:74) |
| The server adds active screen state into `ROOM_STATE` for late joiners. | [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:244) |
| The server validates room membership, starts/stops sharing, relays frames without decoding JPEG, handles request/grant/event packets, and cleans up on disconnect. | [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:445), [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:472), [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:499), [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:519), [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:540), [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:589), [server/client_handler.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:675) |

**How to verify screen sharing**

1. Start the baseline setup from the top of this file.
2. Use two clients, preferably on two laptops on the same LAN. If the host laptop runs the servers, the second laptop should connect to the host laptop's LAN IP as the LB host.
3. If the server/LB are running on Windows, allow Python through Windows Defender Firewall on Private networks, or open inbound TCP ports `9000`, `9001`, and `9002`. If Windows is only the client laptop, outbound connections are usually allowed by default.
4. Login as two different users.
5. User A creates a regular room. User B joins the same room code through the Join button. Do not use a DM room for this test.
6. Optional but useful: confirm the regular room is pinned in Redis:

```bash
redis-cli GET 'room:<ROOM_CODE>'
```

7. User A opens the Screen tab and clicks Share Screen.
8. Expected result on User A: the local preview updates with User A's actual desktop, not a black frame.
9. Expected result on User B: the Screen tab status says User A is sharing, and User B sees User A's desktop after the next relayed frame.
10. While User A is sharing, User B should not be able to start a second share. If a second `SCREEN_START` reaches the server, the server returns `ERROR 409` because `ScreenRelayState.start_share()` rejects another sharer.
11. Start a third client, login as User C, and join the same room while User A is already sharing.
12. Expected result: User C receives the active share state in `ROOM_STATE` and sees User A's screen when the next `SCREEN_RELAY` frame arrives.

**How to verify remote control**

1. Keep User A sharing in the regular room.
2. On User A's laptop, open a harmless target app such as Notepad, TextEdit, or a blank text editor window.
3. User B clicks Request Control.
4. Expected result: User A receives a dialog asking whether User B can control the screen.
5. User A clicks Allow.
6. Expected result on User B: the Screen tab shows that User B has remote control, and the frame widget receives focus.
7. User B clicks inside the shared frame, moves the mouse, scrolls, and types:

```text
RC_VERIFY_001
```

8. Expected result on User A's machine: the mouse/keyboard input is executed in the target app. This verifies the full chain: viewer event filter -> normalized `REMOTE_EVENT` -> server controller validation -> sharer executor -> pyautogui.
9. User A clicks Revoke Control.
10. Expected result: User B's input no longer affects User A's machine. Further stale `REMOTE_EVENT` packets are dropped by the server because User B is no longer the recorded controller.
11. User A clicks Stop Sharing.
12. Expected result: all clients return to "no active screen share", the viewer frame clears, and any remote-control grant is removed.
13. Start sharing again, grant control, then close User B's client. Expected result: the server clears only the controller grant and the share can continue.
14. Start sharing again, then close User A's client. Expected result: the server broadcasts `SCREEN_STOP`; viewers return to no active share.

**Common failure checks**

- If User B cannot see User A's screen, first check User A's local preview. If User A's preview is black, the failure is local capture (`mss`, monitor selection, display permissions). If User A's preview is correct but User B sees nothing, check room routing, firewall, and whether both users joined the same regular room.
- If screen sharing works on one laptop but not across LAN, verify the second laptop receives a reachable server address from the load balancer. The LB advertises a LAN-reachable host when local servers are configured as `127.0.0.1` or `0.0.0.0`.
- If remote control is granted but input does nothing, click once inside the viewer's shared frame to focus it, then test mouse movement and typing again. The implementation requires the event filter to be attached to the frame widget and the frame to have keyboard focus.
