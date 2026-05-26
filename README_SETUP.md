# QuicKonNect — Setup and Launch Guide

Complete guide to running the QuicKonNect application from Phase 1. Covers infrastructure setup, launching all components, verifying everything works, and troubleshooting.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Installation](#2-installation)
3. [Infrastructure Setup](#3-infrastructure-setup)
4. [Environment Variables](#4-environment-variables)
5. [Launch Order](#5-launch-order)
6. [Verify It's Working](#6-verify-its-working)
7. [Feature Smoke Test](#7-feature-smoke-test)
8. [Common Errors and Fixes](#8-common-errors-and-fixes)
9. [Docker Compose Alternative](#9-docker-compose-alternative)

---

## 1. Prerequisites

| Dependency | Minimum Version | Why |
|------------|----------------|-----|
| **Python** | 3.11+ | Uses `X | None` union syntax (PEP 604), `match` statements, and modern `typing` features. Python 3.12 recommended. |
| **PostgreSQL** | 14+ | Database. Needs `JSONB`, `TIMESTAMPTZ`, `CREATE TYPE ... AS ENUM`. |
| **Redis** | 6+ | In-memory store for room-to-server mapping, online user tracking, and pub/sub for cross-server notifications. |
| **pip** | 22+ | For installing Python packages into the virtualenv. |

### OS-specific notes

**Linux (Ubuntu/Debian)** — PyQt6 requires X11/Wayland libraries:

```bash
sudo apt update
sudo apt install -y python3-dev python3-venv \
    libxcb-xinerama0 libxcb-cursor0 libxkbcommon0 \
    libegl1 libgl1-mesa-glx \
    postgresql redis-server
```

**macOS** — Install via Homebrew:

```bash
brew install python@3.12 postgresql@15 redis
brew services start postgresql@15
brew services start redis
```

**Windows** — Install Python 3.12 from python.org, PostgreSQL from postgresql.org, and Redis via WSL2 or Memurai (native Windows Redis alternative). PyQt6 works natively on Windows without extra libraries.

---

## 2. Installation

```bash
# Clone or navigate to the project directory
cd QuicKonNect

# Create a virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows

# Install all dependencies
pip install -r requirements.txt
```

**Verify the install worked:**

```bash
python -c "import cryptography, bcrypt, psycopg, redis, PyQt6; print('All dependencies OK')"
```

---

## 3. Infrastructure Setup

### 3.1 PostgreSQL

**Start PostgreSQL** (if not already running):

```bash
# Linux (systemd)
sudo systemctl start postgresql
sudo systemctl enable postgresql   # auto-start on boot

# macOS (Homebrew)
brew services start postgresql@15
```

**Create the database user and database:**

```bash
sudo -u postgres psql -c "CREATE USER quickonnect WITH PASSWORD 'quickonnect';"
sudo -u postgres psql -c "CREATE DATABASE quickonnect OWNER quickonnect;"
```

> On macOS, if you installed via Homebrew, drop the `sudo -u postgres` prefix — just run `psql postgres -c "..."`.

**Run the schema setup script:**

```bash
# Make sure the virtualenv is activated
python scripts/setup_db.py
```

Expected output:

```
Connecting to PostgreSQL at 127.0.0.1:5432/quickonnect as quickonnect...
Schema created successfully.
```

**Verify the tables exist:**

```bash
psql -U quickonnect -d quickonnect -c "\dt"
```

You should see 7 tables: `users`, `sessions`, `friendships`, `rooms`, `room_participants`, `messages`, `whiteboard_events`.

### 3.2 Redis

**Start Redis:**

```bash
# Linux (systemd)
sudo systemctl start redis-server
sudo systemctl enable redis-server

# macOS (Homebrew)
brew services start redis

# Or run directly in a terminal
redis-server
```

**Verify Redis is reachable:**

```bash
redis-cli ping
```

Expected output: `PONG`

---

## 4. Environment Variables

All components read configuration from environment variables with sensible defaults. If you're running everything on `localhost` with the default PostgreSQL and Redis setup from Section 3, **you don't need to set any variables** — the defaults work out of the box.

### Chat Server (`server/config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SERVER_HOST` | `0.0.0.0` | IP address the server listens on. `0.0.0.0` means all interfaces. |
| `SERVER_PORT` | `9001` | TCP port for client connections. Set to `9002` for the second server. |
| `SERVER_ID` | `server-{port}` | Unique identifier for this server instance. Used in Redis room mapping. |
| `DB_HOST` | `127.0.0.1` | PostgreSQL host. |
| `DB_PORT` | `5432` | PostgreSQL port. |
| `DB_NAME` | `quickonnect` | PostgreSQL database name. |
| `DB_USER` | `quickonnect` | PostgreSQL user. |
| `DB_PASSWORD` | `quickonnect` | PostgreSQL password. |
| `REDIS_HOST` | `127.0.0.1` | Redis host. |
| `REDIS_PORT` | `6379` | Redis port. |
| `JWT_SECRET` | `quickonnect-dev-secret-change-in-production` | HMAC-SHA256 secret for signing JWT tokens. **All server instances must use the same value.** |
| `LB_HOST` | `127.0.0.1` | Load balancer host (unused by server in Phase 1, reserved for future use). |
| `LB_PORT` | `9000` | Load balancer port (unused by server in Phase 1, reserved for future use). |

### Load Balancer (`loadbalancer/config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LB_HOST` | `0.0.0.0` | IP address the load balancer listens on. |
| `LB_PORT` | `9000` | TCP port for client routing requests. |
| `REDIS_HOST` | `127.0.0.1` | Redis host (for room-to-server mapping lookups). |
| `REDIS_PORT` | `6379` | Redis port. |
| `CHAT_SERVERS` | *(empty — uses built-in defaults)* | Comma-separated list of chat servers in `server_id:host:port` format. Example: `server-9001:127.0.0.1:9001,server-9002:127.0.0.1:9002`. When empty, defaults to two servers on ports 9001 and 9002. |

### Client (`client/config.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `LB_HOST` | `127.0.0.1` | Load balancer host to connect to. Also configurable in the login UI. |
| `LB_PORT` | `9000` | Load balancer port. Also configurable in the login UI. |
| `QUICKONNECT_DATA` | `~/.quickonnect` | Directory for storing the JWT session file (`session.json`). |

### Database Setup Script (`scripts/setup_db.py`)

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_HOST` | `127.0.0.1` | PostgreSQL host. |
| `DB_PORT` | `5432` | PostgreSQL port. |
| `DB_NAME` | `quickonnect` | PostgreSQL database name. |
| `DB_USER` | `quickonnect` | PostgreSQL user. |
| `DB_PASSWORD` | `quickonnect` | PostgreSQL password. |

---

## 5. Launch Order

The components must be started in a specific order because of startup dependencies:

```
PostgreSQL ──> Redis ──> Chat Server 1 ──> Chat Server 2 ──> Load Balancer ──> Client
```

**Why this order:**

1. **PostgreSQL** must be running first because the chat servers open a connection pool to it on startup. If PostgreSQL is unreachable, the server crashes.
2. **Redis** must be running before the chat servers because they publish their identity to Redis on startup (`servers` hash) and subscribe to pub/sub channels (`user_status`, `friend_events`).
3. **Chat servers** must be running before the load balancer because the LB immediately starts health-checking them every 5 seconds. If no servers are up, the LB marks them all as DOWN and can't route clients.
4. **Load balancer** must be running before any client tries to connect, because the client's first step is asking the LB for a server assignment.

**You need 5 separate terminal windows** (or use `tmux`/`screen`). Activate the virtualenv in each:

```bash
source .venv/bin/activate
```

### Terminal 1 — Chat Server 1 (port 9001)

```bash
python scripts/run_server.py 9001
```

Expected log:

```
INFO server.main: Starting chat server server-9001 on 0.0.0.0:9001
INFO server.services.db: Database connection pool initialized (min=2, max=10)
INFO server.acceptor: Acceptor listening on 0.0.0.0:9001
INFO server.main: Chat server server-9001 is ready
```

### Terminal 2 — Chat Server 2 (port 9002)

```bash
python scripts/run_server.py 9002
```

Expected log (same pattern, different port):

```
INFO server.main: Starting chat server server-9002 on 0.0.0.0:9002
...
INFO server.main: Chat server server-9002 is ready
```

### Terminal 3 — Load Balancer (port 9000)

```bash
python scripts/run_lb.py
```

Expected log:

```
INFO loadbalancer.main: Starting load balancer on 0.0.0.0:9000
INFO loadbalancer.health_checker: Health checker started for 2 servers
INFO loadbalancer.main: Load balancer is ready
```

### Terminal 4 — Client 1

```bash
python scripts/run_client.py
```

A login window should appear.

### Terminal 5 — Client 2

```bash
python scripts/run_client.py
```

A second login window should appear.

---

## 6. Verify It's Working

Run this checklist after each component starts, before starting the next one.

### After Chat Server 1 starts

```bash
# Check the server registered itself in Redis
redis-cli hget servers server-9001
```

Expected output: `{"host": "127.0.0.1", "port": 9001}`

### After Chat Server 2 starts

```bash
redis-cli hget servers server-9002
```

Expected output: `{"host": "127.0.0.1", "port": 9002}`

### After Load Balancer starts

Wait 5-6 seconds for the first health check cycle, then check the LB terminal log. You should see no `is DOWN` messages. If you do, the LB can't reach a chat server — check that the server is running on the expected port.

You can also test routing manually:

```bash
# Quick test: connect to the LB and see if it responds
python -c "
import sys; sys.path.insert(0, '.')
from client.network.lb_client import request_server
host, port = request_server('127.0.0.1', 9000)
print(f'LB assigned server: {host}:{port}')
"
```

Expected output: `LB assigned server: 127.0.0.1:9001` (or 9002).

### After Client starts

The login window should appear with:
- LB Host field pre-filled with `127.0.0.1`
- LB Port field pre-filled with `9000`
- Username and password fields
- Login and Register buttons

If the window doesn't appear, check the terminal for errors (see Section 8).

---

## 7. Feature Smoke Test

This is a step-by-step walkthrough to verify all Phase 1 features work. You need two client windows running (Terminal 4 and Terminal 5).

### 7.1 Register two accounts

**Client 1:**
1. Enter username: `alice`
2. Enter password: `password123`
3. Click **Register**
4. Status should briefly show "Registering..." then the main window appears
5. The top bar should say "Logged in as: alice"

**Client 2:**
1. Enter username: `bob`
2. Enter password: `password456`
3. Click **Register**
4. Main window appears, top bar says "Logged in as: bob"

**Verify in the database:**

```bash
psql -U quickonnect -d quickonnect -c "SELECT id, username FROM users;"
```

You should see both `alice` and `bob` with auto-incremented IDs.

### 7.2 Send a friend request and accept it

**Client 1 (alice):**
1. Click **Friends** in the sidebar
2. In the "Username to add..." field, type `bob`
3. Click **Add**
4. A dialog should say "Request sent to bob"

**Client 2 (bob):**
1. Click **Friends** in the sidebar
2. Under "Pending Requests", you should see `alice` with **Accept** and **Reject** buttons
3. Click **Accept**
4. `alice` should now appear under "Online / Offline" in green (since she's currently connected)

**Client 1 (alice):**
1. The friend list should update automatically — `bob` should appear with `[online]`

### 7.3 Create a room and join from the second client

**Client 1 (alice):**
1. Click **Chat** in the sidebar
2. Click the **Create** button
3. A new room appears in the room list (e.g., `K7X-B2M4`) — note the room code
4. The room header on the right shows "Room: K7X-B2M4"

**Client 2 (bob):**
1. Click **Chat** in the sidebar
2. Click **Join**
3. Enter the room code from alice's screen (e.g., `K7X-B2M4`)
4. Click OK
5. The room should appear in bob's room list
6. On alice's message view, a system message should appear: "bob joined the room"

### 7.4 Send a message and confirm it appears on both clients

**Client 1 (alice):**
1. Make sure the room is selected
2. Type `Hello Bob!` in the message input
3. Press Enter or click **Send**
4. The message should appear in alice's message view: `[HH:MM:SS] alice: Hello Bob!`

**Client 2 (bob):**
1. The same message should appear in bob's message view: `[HH:MM:SS] alice: Hello Bob!`
2. Type `Hi Alice!` and press Enter
3. Both clients should now show both messages

### 7.5 Test JWT session resume

**Client 1 (alice):**
1. Close the main window (click the X button or click **Logout**)
   - **If you click Logout**: the session is cleared. You'll need to type credentials again. This tests fresh login.
   - **If you click the X (window close)**: the session file is preserved at `~/.quickonnect/session.json`.

**Test session resume (close window without logging out):**
1. Close alice's client window by clicking X
2. Restart the client: `python scripts/run_client.py`
3. The login window should briefly show "Resuming session..." then jump straight to the main window
4. Alice is logged in without typing credentials — the JWT from `~/.quickonnect/session.json` was validated

**Test that Logout clears the session:**
1. In the main window, click **Logout**
2. The login window reappears
3. Restart the client: `python scripts/run_client.py`
4. The login window appears and asks for credentials (session was cleared)
5. Log in with `alice` / `password123` — should work

---

## 8. Common Errors and Fixes

### PostgreSQL connection refused

```
psycopg.OperationalError: connection to server at "127.0.0.1", port 5432 failed:
Connection refused
```

**Cause:** PostgreSQL is not running, or it's on a different port.

**Fix:**
```bash
# Check if PostgreSQL is running
sudo systemctl status postgresql

# Start it
sudo systemctl start postgresql

# If the port is different, check with:
sudo -u postgres psql -c "SHOW port;"
# Then set DB_PORT accordingly:
export DB_PORT=5433
```

### PostgreSQL authentication failed

```
psycopg.OperationalError: FATAL: password authentication failed for user "quickonnect"
```

**Cause:** The database user doesn't exist or the password is wrong.

**Fix:**
```bash
sudo -u postgres psql -c "CREATE USER quickonnect WITH PASSWORD 'quickonnect';"
sudo -u postgres psql -c "CREATE DATABASE quickonnect OWNER quickonnect;"
```

If the user exists but the password is wrong:
```bash
sudo -u postgres psql -c "ALTER USER quickonnect WITH PASSWORD 'quickonnect';"
```

### PostgreSQL database does not exist

```
psycopg.OperationalError: FATAL: database "quickonnect" does not exist
```

**Fix:**
```bash
sudo -u postgres psql -c "CREATE DATABASE quickonnect OWNER quickonnect;"
```

### Redis connection refused

```
redis.exceptions.ConnectionError: Error 111 connecting to 127.0.0.1:6379. Connection refused.
```

**Cause:** Redis server is not running.

**Fix:**
```bash
# Start Redis
sudo systemctl start redis-server

# Or run it directly
redis-server --daemonize yes

# Verify
redis-cli ping   # should print PONG
```

### PyQt6 display errors on Linux

```
qt.qpa.xcb: could not connect to display
```

or

```
Could not load the Qt platform plugin "xcb"
```

**Cause:** No display server available (common on headless servers or SSH without X forwarding).

**Fix — if you have a desktop environment but it's not detected:**
```bash
export DISPLAY=:0
python scripts/run_client.py
```

**Fix — over SSH with X forwarding:**
```bash
ssh -X user@host
# Then run the client normally
```

**Fix — missing X11 libraries:**
```bash
sudo apt install -y libxcb-xinerama0 libxcb-cursor0 libxkbcommon0 libegl1
```

**Fix — on Wayland (GNOME on Ubuntu 22.04+):**
```bash
export QT_QPA_PLATFORM=wayland
# or force X11:
export QT_QPA_PLATFORM=xcb
```

### Port already in use

```
OSError: [Errno 98] Address already in use
```

**Cause:** Another process is using the port (a previous server that didn't shut down cleanly).

**Fix:**
```bash
# Find what's using the port (e.g., 9001)
lsof -i :9001

# Kill it
kill <PID>

# Or pick a different port
SERVER_PORT=9003 python scripts/run_server.py 9003
```

### Load Balancer health check failures

The LB terminal shows repeated messages like:

```
DEBUG loadbalancer.health_checker: Server server-9001 (127.0.0.1:9001) is DOWN
```

**Cause:** The chat server isn't running, or it's on a different host/port than what the LB expects.

**Fix:**
1. Confirm the chat server is running: check its terminal for the "is ready" log message.
2. Confirm the ports match. The LB defaults to checking `127.0.0.1:9001` and `127.0.0.1:9002`. If your servers are on different ports, set `CHAT_SERVERS`:

```bash
CHAT_SERVERS="server-9003:127.0.0.1:9003,server-9004:127.0.0.1:9004" python scripts/run_lb.py
```

### Client shows "Connection refused" on login

**Cause:** The LB isn't running, or the host/port in the login window is wrong.

**Fix:**
1. Make sure the LB is running and shows "Load balancer is ready".
2. In the client login window, verify the LB Host is `127.0.0.1` and LB Port is `9000`.

### Client shows "No available servers"

**Cause:** The LB is running, but all chat servers are marked as DOWN.

**Fix:** Check that at least one chat server is running and the LB can reach it (see "health check failures" above). Wait 5-10 seconds for the next health check cycle after starting a chat server.

---

## 9. Docker Compose Alternative

If you don't want to install PostgreSQL and Redis locally, use this `docker-compose.yml` to spin them up in containers. You still run the Python components (servers, LB, clients) on your host machine.

Create `docker-compose.yml` in the project root:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: quickonnect
      POSTGRES_PASSWORD: quickonnect
      POSTGRES_DB: quickonnect
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U quickonnect"]
      interval: 5s
      timeout: 3s
      retries: 5

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  pgdata:
```

### Usage

```bash
# Start PostgreSQL and Redis
docker compose up -d

# Wait a few seconds for them to become healthy
docker compose ps   # both should show "healthy"

# Run the schema setup (connects to localhost:5432)
source .venv/bin/activate
python scripts/setup_db.py

# Then launch the Python components normally (Terminals 1-5 from Section 5)
python scripts/run_server.py 9001
python scripts/run_server.py 9002
python scripts/run_lb.py
python scripts/run_client.py
```

### Stopping

```bash
# Stop PostgreSQL and Redis containers (data is preserved in the pgdata volume)
docker compose down

# To also delete the database data:
docker compose down -v
```

### Troubleshooting Docker

- If port 5432 is already taken by a local PostgreSQL, either stop the local one (`sudo systemctl stop postgresql`) or change the host port mapping in `docker-compose.yml` to `"5433:5432"` and set `export DB_PORT=5433`.
- If port 6379 is already taken by a local Redis, stop it (`sudo systemctl stop redis-server`) or remap to `"6380:6379"` and set `export REDIS_PORT=6380`.
