# QuicKonNect

QuicKonNect is a desktop video-call and messaging project for the Introduction to Network Programming course (NT106) at UIT, contributed by @nhnamp, @ComGa999ms, and @Qusy64.

The project demonstrates a self-built TCP client/server system with multiple chat servers, a custom load balancer, PostgreSQL persistence, Redis coordination, encrypted transport, multi-client rooms, audio streaming, live subtitles, and file/image messaging.

## Features

- Account registration, login, and JWT session resume.
- Friend requests, friend list, and online/offline updates through Redis.
- Room chat and direct messages.
- File and image messages over the custom TCP protocol.
- Room-aware load balancing across two chat servers.
- Audio streaming with server-side per-room mixing.
- Local Whisper subtitles with bilingual English/Vietnamese display enabled by default.

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
44 passed
```

## Manual Demo Checklist

Use [docs/11_e2e_test_preparation.md](docs/11_e2e_test_preparation.md) for a full manual test checklist covering:

- Register/login.
- Create/join room.
- Text chat.
- File/image messages.
- Audio.
- Multi-server behavior.

## Important Notes

- Audio currently uses raw PCM for reliable LAN testing. It is heavier than Opus but simpler to install and debug.
- Subtitles require `faster-whisper` and run in bilingual mode by default. Disable with `QUICKONNECT_STT_ENABLED=0` if you only want audio.
- If your local PostgreSQL on `5432` already belongs to another project, keep using `DB_PORT=55432` for QuicKonNect tests.
- `AGENTS.md` and [CLAUDE.md](CLAUDE.md) describe project-specific development rules and documentation expectations.
