# Demo Playbook

## What Was Done
Created a step-by-step demonstration plan for presenting QuicKonNect. This playbook lists what to start, what to click, what to say, and what the expected result should be for each grading-relevant feature.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `docs/12_demo_playbook.md` | Created | Provides a repeatable demo sequence for project defense. |

## Why It Matters
A network programming demo has many moving parts. A fixed playbook reduces mistakes during the presentation and makes sure every scoring area is shown: socket logic, I/O, database, threads, authentication, multi-client, multi-server, cryptography, LAN/Internet readiness, and load balancing.

## Pre-Demo Setup

Use a clean terminal in the project folder.

```powershell
$env:DB_PORT = "55432"
.venv\Scripts\python.exe scripts\check_e2e_readiness.py --check-ports
.venv\Scripts\python.exe -m pytest tests -q
```

Start the stack:

```powershell
$env:DB_PORT = "55432"
.venv\Scripts\python.exe scripts\run_demo_stack.py
```

Open two client terminals:

```powershell
.venv\Scripts\python.exe scripts\run_client.py
```

Optional automated proof before the live UI demo:

```powershell
$env:DB_PORT = "55432"
.venv\Scripts\python.exe scripts\smoke_e2e_protocol.py
```

## Demo Sequence

### 1. Architecture Overview
Say:
- The client uses PyQt6 and talks over custom TCP sockets.
- The load balancer routes clients to one of two chat servers.
- PostgreSQL stores users, sessions, messages, rooms, and whiteboard events.
- Redis coordinates online users, room mapping, and cross-server events.
- Every client/server connection uses RSA key exchange and AES-GCM transport encryption.

Show:
- One terminal running the demo stack.
- Two client windows.

Expected:
- Server 9001, server 9002, and load balancer 9000 are running.

### 2. Sign Up / Sign In
Action:
- Register or log in as two different users.

Say:
- Passwords are stored with BCrypt.
- Sessions use JWT tokens and can be resumed.

Expected:
- Both users reach the main window.

### 3. Friend And Direct Message
Action:
- User A sends a friend request to User B.
- User B accepts.
- User A opens a DM and sends a message.
- User B replies.

Say:
- DMs are server-agnostic. They do not need room pinning.
- Cross-server DM delivery uses Redis pub/sub.

Expected:
- Both users see messages in real time.

### 4. Room Chat
Action:
- User A creates a room.
- User B joins with the room code.
- Both users send messages.

Say:
- Normal rooms are pinned to a single server so real-time media does not need cross-server relay.
- Message history is stored in PostgreSQL and loaded on join.

Expected:
- Messages appear on both clients.
- Join notifications appear.

### 5. File And Image Messages
Action:
- Send a small file.
- Send an image.
- Save the received attachment.

Say:
- File/image messages go through the same encrypted TCP channel.
- The server validates type, filename, base64 content, and size before storing.

Expected:
- The receiver sees `[file: ...]` or `[image: ...]`.
- The attachment saves correctly.

### 6. Screen Sharing
Action:
- User A opens Screen tab and starts sharing.
- User B opens Screen tab and watches.

Say:
- The client captures frames in a background thread.
- The server relays frames to room participants.
- Only one sharer is allowed per room.

Expected:
- User B sees User A's screen frames.

### 7. Remote Control
Action:
- User B requests control.
- User A approves.
- User B moves/clicks in the shared view.
- User A revokes.

Say:
- Remote control always requires explicit host approval.
- The server only relays control events from the granted controller.

Expected:
- Control works only after approval and stops after revoke.

### 8. Audio
Action:
- Both users open Audio tab.
- Both click Join Audio.
- Speak from one side, then mute/unmute.

Say:
- Audio uses 20 ms PCM frames over TCP.
- The server mixes per room.
- Each recipient receives everyone else's audio, excluding their own stream to avoid echo.

Expected:
- The other client hears the speaker.
- Muting stops audio.

### 9. Whiteboard
Action:
- Both users open Whiteboard tab.
- Draw strokes, shapes, text, and eraser marks.
- Use Undo and Clear.
- Export PNG.

Say:
- Whiteboard sends vector-like events, not pixels.
- The server assigns sequence numbers and persists events.
- Late joiners receive `WHITEBOARD_SYNC`.

Expected:
- Both clients see the same board state.
- Export creates a PNG.

### 10. Multi-Server And Load Balancing
Action:
- Point to server logs and load balancer logs.
- Mention health checks and least-connections routing.

Say:
- The load balancer checks both chat servers.
- Normal rooms are pinned to a server.
- DMs can cross servers using Redis.

Expected:
- Logs show clients routed and health checks occurring.

## Backup Plan

If the live GUI demo has device issues:
- Run `scripts/smoke_e2e_protocol.py` to prove protocol-level E2E behavior.
- Show `47 passed` from pytest.
- Explain that mic/screen capture are hardware/UI-dependent but the socket paths are verified.

## Demo Close

End by mapping features to rubric:

| Rubric Area | Demo Evidence |
|------------|---------------|
| Socket logic | Custom TCP protocol, LB, chat, media, whiteboard |
| I/O | File/image messages, whiteboard PNG export |
| Database | Users, sessions, messages, rooms, whiteboard events |
| Threads | Client receiver, heartbeat, screen capture, audio, server client handlers, mixers |
| Auth | Register/login/JWT |
| Multi-client | Two clients in same room |
| Multi-server | Two chat servers behind LB |
| Cryptography | RSA handshake and AES-GCM transport |
| LAN/Internet | LAN-ready stack; ngrok can expose LB port |
| Load balancing | Self-built LB on port 9000 |
