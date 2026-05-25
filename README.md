# QuicKonNect

QuicKonNect is a desktop video-call and messaging project for the Introduction to Network Programming course (NT106) at UIT, contributed by @nhnamp, @ComGa999ms, and @Qusy64.

The project demonstrates a self-built TCP client/server system with multiple chat servers, a custom load balancer, PostgreSQL persistence, Redis coordination, encrypted transport, multi-client rooms, screen sharing, remote control, audio streaming, file/image messaging, and a collaborative whiteboard.

## Features

- Account registration, login, and JWT session resume.
- Friend requests, friend list, and online/offline updates through Redis.
- Room chat and direct messages.
- File and image messages over the custom TCP protocol.
- Room-aware load balancing across two chat servers.
- Screen sharing with one active sharer per room.
- Remote control request, grant, revoke, and input relay.
- Audio streaming with server-side per-room mixing.
- Optional local Whisper subtitles.
- Collaborative whiteboard with draw events, server ordering, persistence, sync for late joiners, undo, clear, and PNG export.

## Architecture

Runtime components:

- PyQt6 desktop client.
- Load balancer on port `9000`.
- Chat server 1 on port `9001`.
- Chat server 2 on port `9002`.
- PostgreSQL database.
- Redis for room routing, online users, friend events, and cross-server DM delivery.

The full design is in [ARCHITECTURE.md](ARCHITECTURE.md). Build-step documentation is in [docs/](docs/).

## Quick Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Start Redis and PostgreSQL. If local PostgreSQL on `5432` is already used by another project, use the test database container on port `55432`:

```powershell
docker compose up -d redis
docker run --name quickonnect-postgres-e2e `
  -e POSTGRES_USER=quickonnect `
  -e POSTGRES_PASSWORD=quickonnect `
  -e POSTGRES_DB=quickonnect `
  -p 55432:5432 `
  -d postgres:16-alpine
```

Set the database port and initialize the schema:

```powershell
$env:DB_PORT = "55432"
.venv\Scripts\python.exe scripts\setup_db.py
```

Check readiness:

```powershell
$env:DB_PORT = "55432"
.venv\Scripts\python.exe scripts\check_e2e_readiness.py --check-ports
```

## Run The App

Start two chat servers and the load balancer:

```powershell
$env:DB_PORT = "55432"
.venv\Scripts\python.exe scripts\run_demo_stack.py
```

Open one or more clients in separate terminals:

```powershell
.venv\Scripts\python.exe scripts\run_client.py
```

## Automated Tests

Run the unit/helper tests:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Run protocol-level E2E smoke test after the demo stack is running:

```powershell
$env:DB_PORT = "55432"
.venv\Scripts\python.exe scripts\smoke_e2e_protocol.py
```

Verified locally:

```text
47 passed
Protocol E2E smoke test passed.
```

## Manual Demo Checklist

Use [docs/11_e2e_test_preparation.md](docs/11_e2e_test_preparation.md) for a full manual test checklist covering:

- Register/login.
- Create/join room.
- Text chat.
- File/image messages.
- Screen sharing.
- Remote control.
- Audio.
- Whiteboard.
- Multi-server behavior.

## Important Notes

- Audio currently uses raw PCM for reliable LAN testing. It is heavier than Opus but simpler to install and debug.
- Subtitles require `faster-whisper` and are disabled by default. Enable with `QUICKONNECT_STT_ENABLED=1`.
- If your local PostgreSQL on `5432` already belongs to another project, keep using `DB_PORT=55432` for QuicKonNect tests.
- `AGENTS.md` and [CLAUDE.md](CLAUDE.md) describe project-specific development rules and documentation expectations.
