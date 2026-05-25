# End-to-End Test Preparation

## What Was Done
Prepared the project for manual end-to-end testing before Phase 6 documentation and defense prep. This step adds a readiness script and a clear checklist for testing the integrated application locally with multiple clients.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `scripts/check_e2e_readiness.py` | Created | Checks Python version, required files, required Python packages, optional subtitle/test packages, environment variables, and optionally local service ports. |
| `scripts/smoke_e2e_protocol.py` | Created | Runs an automated protocol-level smoke test against a running local stack. |
| `docs/11_e2e_test_preparation.md` | Created | This E2E preparation and checklist document. |

## Why It Matters
Phase 3, Phase 4, and the first Phase 5 integration pass added several moving parts: audio devices, whiteboard event sync, file/image messages, PostgreSQL, Redis, two chat servers, and the load balancer. A readiness check helps catch missing dependencies and services before opening the app. A fixed checklist also makes testing repeatable, so bugs can be reproduced and fixed instead of relying on memory during demo practice.

## Readiness Check
Run this first:

```bash
python scripts/check_e2e_readiness.py
```

To also check whether PostgreSQL, Redis, and app ports are listening:

```bash
python scripts/check_e2e_readiness.py --check-ports
```

If required packages are missing:

```bash
python -m pip install -r requirements.txt
```

On Windows, PyAudio may require a prebuilt wheel if normal pip installation fails. If that happens, install the matching wheel for your Python version, then rerun the readiness check.

## Local E2E Test Checklist

### 0. Automated protocol smoke test
After starting PostgreSQL, Redis, two chat servers, and the load balancer, run:

```bash
python scripts/smoke_e2e_protocol.py
```

Expected:
- Two temporary users are registered.
- Both join the same room through the load balancer.
- Text chat is delivered.
- A file attachment message is delivered.
- A whiteboard draw event is broadcast.
- A mixed-audio packet is produced.

### 1. Start infrastructure
Start PostgreSQL and Redis. The Docker Compose path is:

```bash
docker compose up -d
python scripts/setup_db.py
```

Confirm readiness:

```bash
python scripts/check_e2e_readiness.py --check-ports
```

Expected:
- Required Python modules are installed.
- PostgreSQL `127.0.0.1:5432` is reachable.
- Redis `127.0.0.1:6379` is reachable.

### 2. Start app servers
Start the local demo stack:

```bash
python scripts/run_demo_stack.py
```

Expected:
- Chat server 9001 starts.
- Chat server 9002 starts.
- Load balancer 9000 starts.
- The terminal stays open until stopped with Ctrl+C.

### 3. Start two clients
Open two separate terminals:

```bash
python scripts/run_client.py
```

Expected:
- Both clients show the login window.
- Register or log in with two different users.
- Both users reach the main app window.

### 4. Test rooms and chat
In Client A:
- Create a room.
- Send the room code to Client B.

In Client B:
- Join the room.

Expected:
- Both clients show the same room.
- Join/leave system messages appear.
- Text messages appear on both clients.
- Message history appears in the correct room after rejoining.

### 5. Test file and image messaging
In either client:
- Click **File** and send a small text or PDF file.
- Click **Image** and send a PNG/JPG image.

Expected:
- The other client sees `[file: ...]` or `[image: ...]`.
- **Save Attachment** can save the received attachment.
- Oversized files above 8 MB are rejected before sending.

### 6. Test screen sharing and remote control
In Client A:
- Open the Screen tab.
- Click **Share Screen**.

In Client B:
- Open the Screen tab.
- Confirm frames are visible.
- Click **Request Control**.

In Client A:
- Allow remote control.
- Revoke remote control after confirming input works.

Expected:
- Only one user can share at a time.
- Remote control requires explicit approval.
- Revoke disables control.
- Stopping share clears the viewer state.

### 7. Test audio
In both clients:
- Open the Audio tab.
- Click **Join Audio**.
- Speak into one microphone.
- Toggle **Mute** and **Unmute**.

Expected:
- The other client hears the speaker.
- The speaker does not hear their own echoed audio from the server.
- Muting stops outgoing audio.
- If `QUICKONNECT_STT_ENABLED=1`, subtitles may appear after a few seconds depending on machine speed.

### 8. Test whiteboard
In both clients:
- Open the Whiteboard tab.
- Draw with Pen, Rect, Oval, Text, and Eraser.
- Use Undo.
- Use Clear.
- Export PNG.

Expected:
- Draw events appear on both clients in the same order.
- A late-joining client receives the current board state through sync.
- Undo removes the last eligible local event.
- Clear clears the board for everyone.
- Export PNG saves the current canvas.

### 9. Test multi-server behavior
Keep both chat servers running. Log in two clients and observe load-balancer distribution from server logs.

Expected:
- Normal rooms stay pinned to one server.
- DMs still work even if users are connected to different servers.
- Friend status updates across servers.

### 10. Capture bugs
For every failure, write down:
- Which client performed the action.
- Which room code was active.
- Which server the client was connected to if visible in logs.
- Exact action taken.
- What appeared on both clients.
- Any traceback or server log line.

## Current Known Limits
- Audio currently uses raw PCM for reliability. It is suitable for LAN testing but heavier than Opus.
- Subtitle support is optional and depends on `faster-whisper`.
- Reconnection handling is not complete yet.
- Internet/ngrok testing is still pending for the next hardening pass.
