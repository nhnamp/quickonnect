# Phase 1: Foundation (Core Infrastructure)

## What Was Built

Phase 1 establishes the complete TCP communication foundation for QuicKonNect. After this phase, the system supports:

- **Binary protocol** with a 40-byte header (magic number, version, packet type, payload length, AES-GCM nonce and auth tag) and JSON payloads
- **RSA-2048 key exchange** on every new connection, establishing a per-session AES-256-GCM encrypted channel
- **Load balancer** with room-aware routing (least-connections algorithm, periodic health checks to all chat servers)
- **Chat server** with thread-per-client model, accepting connections, performing handshakes, and routing packets
- **Authentication** — register with username/password (BCrypt hashed), login, and JWT-based session persistence
- **Room management** — create rooms (auto-generated codes), join by code, leave rooms, room state sync
- **Text messaging** — send/receive messages in rooms, message history stored in PostgreSQL and loaded on join
- **Friend system** — send friend requests, accept/reject, see online/offline status synced across servers via Redis pub/sub
- **Client UI** — PyQt6 desktop app with login/register screen, chat panel with room list and message view, friend list with online status and pending request handling

## Files Created / Modified

### Shared Layer (`shared/`)
| File | Action | Purpose |
|------|--------|---------|
| `shared/__init__.py` | Created | Package marker |
| `shared/constants.py` | Created | All protocol constants: magic number, header size, packet type enum (35 types), port defaults, heartbeat intervals, plaintext packet type set |
| `shared/models.py` | Created | Data classes: User, Room, Message, Friend, Participant, RoomState — each with `to_dict()` for serialization |
| `shared/protocol.py` | Created | Binary protocol: `encode_packet()`, `decode_header()`, `read_packet()`, `send_packet()` — handles both plaintext and AES-encrypted packets with AAD |
| `shared/crypto.py` | Created | RSA-2048 key generation/serialization/encrypt/decrypt, AES-256-GCM encrypt/decrypt, BCrypt password hashing, HMAC-SHA256 JWT creation/validation (self-implemented, no external JWT library) |

### Server (`server/`)
| File | Action | Purpose |
|------|--------|---------|
| `server/__init__.py` | Created | Package marker |
| `server/config.py` | Created | Server configuration from environment variables (host, port, DB, Redis, JWT secret) |
| `server/services/__init__.py` | Created | Package marker |
| `server/services/db.py` | Created | PostgreSQL connection pool (psycopg v3 + psycopg_pool) with `init_pool()`, `close_pool()`, `get_connection()` context manager |
| `server/services/auth_service.py` | Created | Register, login, JWT token validation, session storage. BCrypt cost=12 for password hashing. |
| `server/services/message_service.py` | Created | Store messages in DB, retrieve history (last 100 messages per room, ordered oldest-first) |
| `server/services/friend_service.py` | Created | Send friend request, accept/reject, get friend list (accepted + incoming pending), user lookup |
| `server/room_manager.py` | Created | Thread-safe room management: create/join/leave rooms, room→server mapping in Redis, participant tracking in DB, auto-cleanup when all clients leave |
| `server/client_handler.py` | Created | Per-client thread: handles RSA handshake, auth flow (register/login/JWT), main packet dispatch loop (rooms, messaging, friends, heartbeat), cleanup on disconnect |
| `server/acceptor.py` | Created | TCP listener thread: accepts connections, spawns ClientHandler threads, 1-second timeout for clean shutdown |
| `server/main.py` | Created | ChatServer orchestrator: initializes DB pool, Redis, services, acceptor. Redis pub/sub listener for cross-server online status and friend events. Signal handling for graceful shutdown. |
| `server/features/__init__.py` | Created | Package marker (Phase 2-4 features go here) |

### Load Balancer (`loadbalancer/`)
| File | Action | Purpose |
|------|--------|---------|
| `loadbalancer/__init__.py` | Created | Package marker |
| `loadbalancer/config.py` | Created | LB configuration: host, port, Redis, chat server list (from env or defaults to two servers on 9001/9002) |
| `loadbalancer/health_checker.py` | Created | Background thread: queries each chat server every 5 seconds via TCP (HEALTH_QUERY/HEALTH_RESPONSE), tracks connection count, CPU load, up/down status. `get_least_loaded()` returns best server. |
| `loadbalancer/router.py` | Created | Room-aware routing: checks Redis for room→server mapping, routes to existing server or picks least-loaded for new rooms. Short-lived TCP handler per client. |
| `loadbalancer/main.py` | Created | LoadBalancer: starts health checker, listens on port 9000, spawns router threads per incoming connection. Signal handling for shutdown. |

### Client (`client/`)
| File | Action | Purpose |
|------|--------|---------|
| `client/__init__.py` | Created | Package marker |
| `client/config.py` | Created | Client configuration: LB host/port, local data directory |
| `client/storage/__init__.py` | Created | Package marker |
| `client/storage/local_store.py` | Created | JWT persistence to disk (save/load/clear session), creates data directory on init |
| `client/network/__init__.py` | Created | Package marker |
| `client/network/connection.py` | Created | ConnectionManager: TCP connection + RSA handshake + AES session key. Background receiver thread puts packets in a Queue. Background heartbeat thread. Thread-safe `send()`. Disconnect callback. |
| `client/network/lb_client.py` | Created | `request_server()`: connects to LB, sends CONNECT_REQUEST (with optional room code), receives server assignment |
| `client/ui/__init__.py` | Created | Package marker |
| `client/ui/login_window.py` | Created | Login/register UI with LB host/port fields, username/password, async auth via QThread worker, saved session auto-resume |
| `client/ui/chat_widget.py` | Created | Chat panel: room list (create/join), message view with timestamps, message input. Handles ROOM_STATE, CHAT_MESSAGE, MESSAGE_HISTORY, ROOM_UPDATE packets. |
| `client/ui/friend_list_widget.py` | Created | Friend list: add friend by username, pending request handling (accept/reject buttons), online/offline color indicators, double-click to start DM |
| `client/ui/main_window.py` | Created | Main window: top bar with username + logout, sidebar (Chat/Friends tabs), stacked content area, QTimer packet polling at 60Hz, disconnect handling |
| `client/main.py` | Created | App entry point: manages login→main window flow, logout→back to login, creates QApplication |
| `client/features/__init__.py` | Created | Package marker (Phase 2-4 features go here) |

### Scripts (`scripts/`)
| File | Action | Purpose |
|------|--------|---------|
| `scripts/setup_db.py` | Created | Creates all PostgreSQL tables (users, sessions, friendships, rooms, room_participants, messages, whiteboard_events) with enums and indexes. Prints setup instructions on connection failure. |
| `scripts/run_server.py` | Created | Start a chat server instance. Accepts port as CLI argument (e.g., `python run_server.py 9002`). |
| `scripts/run_lb.py` | Created | Start the load balancer |
| `scripts/run_client.py` | Created | Start the desktop client |

### Tests (`tests/`)
| File | Action | Purpose |
|------|--------|---------|
| `tests/__init__.py` | Created | Package marker |
| `tests/test_protocol.py` | Created | 14 tests: header encoding, magic/version validation, plaintext roundtrip, encrypted roundtrip, wrong-key rejection, tampered ciphertext detection, plaintext types bypass encryption, packet type uniqueness |
| `tests/test_crypto.py` | Created | 22 tests: RSA keygen/serialize/encrypt/decrypt/wrong-key, AES encrypt/decrypt/AAD/wrong-key/nonce-uniqueness, BCrypt hash/verify/wrong-password/different-salts, JWT create/decode/wrong-secret/tampered/expired/malformed |

### Other
| File | Action | Purpose |
|------|--------|---------|
| `requirements.txt` | Created | All Python dependencies: cryptography, bcrypt, psycopg, psycopg-pool, redis, PyQt6, pytest |
| `.venv/` | Created | Python virtual environment with all dependencies installed |

## Key Decisions Made

### 1. LOGIN_REQUEST packet type added (0x0014)
The architecture defined AUTH_REQUEST (JWT validation) and REGISTER_REQUEST, but had no packet for username+password login. Added LOGIN_REQUEST (0x0014) and LOGIN_RESPONSE (0x0015) to cleanly separate the three auth flows: register, login, and JWT session resume.

### 2. Self-implemented JWT instead of PyJWT library
Implemented JWT creation and validation using only `hmac` and `hashlib` from the standard library. This reduces dependencies and demonstrates cryptographic understanding for the course — the JWT spec (HMAC-SHA256 + base64url encoding) is simple enough to implement correctly in ~40 lines.

### 3. AAD (Associated Authenticated Data) for AES-GCM
The architecture didn't specify AAD, but I use the first 12 bytes of each packet header (magic + version + packet type + payload length) as AAD during encryption. This means an attacker cannot change the packet type or payload length without invalidating the authentication tag — a meaningful security improvement at zero performance cost.

### 4. QTimer packet polling instead of cross-thread Qt signals
The client uses a QTimer at ~60Hz to poll a thread-safe Queue for incoming packets, rather than emitting Qt signals from the receiver thread. This avoids subtle Qt cross-thread signal delivery issues and keeps the threading model simple: the receiver thread only writes to a Queue, the main thread only reads from it.

### 5. Deterministic DM room codes
When a user double-clicks a friend to start a direct message, the room code is generated deterministically as `DM-{sorted_name_1}-{sorted_name_2}`. This means both users always generate the same room code for their conversation, and the room is created on first use. No server-side lookup needed to find existing DMs.

### 6. Health checks via the main server port
Rather than adding a separate health check port, the load balancer connects to the chat server's main port and sends a HEALTH_QUERY packet. The server's ClientHandler detects this as the first packet (before any CLIENT_HELLO) and responds immediately. This keeps the server architecture simple — one port, one acceptor.

## Why It Matters

Phase 1 is the foundation that all three core features (Screen Sharing, Audio Streaming, Whiteboard) will build on. Every component built here — the protocol, encryption, threading model, room management, and client-server connection — is reused by Phases 2-4. By establishing a solid, tested foundation now, the three team members can develop their features in parallel without stepping on each other's code.

The 36 unit tests covering the protocol and cryptography modules provide a safety net: any future change to the packet format or encryption logic will be caught immediately. The binary protocol is designed with a fixed header and extensible packet types, so adding new packet types for screen frames, audio chunks, and whiteboard events requires no changes to the core protocol code.
