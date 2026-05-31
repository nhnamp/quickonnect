# RESEARCH.md — Network Programming Course Project
## Video Call & Messaging Application

> **Purpose of this document:** Full technical specification for Claude Code to understand the project requirements, architecture, and feature scope. This is a university course project for *Network Programming*, where the grading criteria emphasize TCP socket usage, multi-threading, multi-server architecture, and cryptography.

---

## 1. Project Overview

A desktop/web application centered on **video calling** with advanced collaborative features. Messaging is a secondary feature. The system must demonstrate mastery of client-server architecture using raw TCP sockets.

**Team size:** 3 members, each owning one core feature.  
**Course:** Network Programming  
**Key constraint:** All real-time data transfer (audio, video frames, events, messages) must go through self-built TCP socket infrastructure — not WebRTC, not third-party SDKs for the transport layer.

---

## 2. Grading Criteria (from course rubric)

| Criterion | Description | Max Score |
|---|---|---|
| App Logic + Socket Logic | Difficulty and creativity of socket usage | **5.0** |
| I/O (File, Network…) | Handle input/output streams over network | 0.5 |
| Database | Connect and work with a DBMS | 0.5 |
| Thread | Apply multi-threading | 0.5 |
| Sign up / Sign in | Registration, login, session persistence | 0.5 |
| Multi Client | Support multiple simultaneous clients | 0.5 |
| Multi Server | Multiple server instances running in parallel | 0.5 |
| Cryptography | Encrypt data to protect information | 0.5 |
| Demo via LAN | Run on LAN using internal IP | 0.5 |
| Demo via Internet | Expose via Ngrok or similar | 0.5 |
| Load Balancing | Custom load balancer (self-built for full score) | 1.0 |

**Total: 10.0 points**

---

## 3. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLIENTS                              │
│   [Client A]      [Client B]      [Client C]      [Client D]│
│   Desktop App     Desktop App     Desktop App     Desktop App│
└────────┬──────────────┬───────────────┬──────────────┬──────┘
         │  TCP Socket  │               │              │
         ▼              ▼               ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LOAD BALANCER                             │
│  - Accepts new client TCP connections                        │
│  - Queries all chat servers for current connection count     │
│  - Responds with IP:Port of least-loaded server             │
│  - Client then connects directly to assigned server          │
│  Port: 9000                                                  │
└──────────────┬──────────────────────────────────────────────┘
               │ Internal TCP
       ┌───────┴────────┐
       ▼                ▼
┌─────────────┐  ┌─────────────┐
│  CHAT       │  │  CHAT       │   (expandable to N servers)
│  SERVER 1   │  │  SERVER 2   │
│  Port: 9001 │  │  Port: 9002 │
│             │  │             │
│  - Thread   │  │  - Thread   │
│    per client│  │    per client│
│  - Handles  │  │  - Handles  │
│    messaging │  │    messaging │
│  - Relays   │  │  - Relays   │
│    audio/   │  │    audio/   │
│    video    │  │    video    │
└──────┬──────┘  └──────┬──────┘
       │                │
       └───────┬────────┘
               ▼
┌──────────────────────────┐     ┌─────────────────────┐
│      REDIS / SHARED DB   │     │      DATABASE        │
│  - Session sync          │     │  - User accounts     │
│  - Online user list      │     │  - Friend list       │
│  - Room/session state    │     │  - Message history   │
│  - Audio mixer state     │     │  - Room metadata     │
└──────────────────────────┘     └─────────────────────┘
```

---

## 4. Core Features

### 4.1 Feature 1 — Screen Sharing + Remote Control
**Owner:** Member 1  
**Network core:** Pixel stream + input event relay over TCP

#### Description
During a video call, any participant can share their screen. Other participants can request remote control permission, after which their mouse/keyboard events are sent over TCP and executed on the sharing machine.

#### Technical Implementation

**Screen Capture & Streaming:**
```
[Capturer Thread] → capture frame (e.g. 1280x720 @ 15fps)
                  → compress (JPEG/PNG or H.264 via ffmpeg)
                  → serialize: [Header: frame_id, width, height, size] + [bytes]
                  → send over TCP socket to server
                  → server relays to all participants in room
```

**Remote Control:**
```
[Viewer Client] → mouse/keyboard event occurs
               → serialize: [EventType: MOUSE_MOVE/CLICK/KEY_PRESS] + [x, y, keycode]
               → send over TCP to server
               → server relays to host client
               → host executes event via OS automation (e.g. Robot class in Java, pyautogui in Python)
```

**Packet Structure:**
```
SCREEN_FRAME packet:
| 4 bytes: packet_type (0x01) |
| 4 bytes: frame_id           |
| 4 bytes: payload_size       |
| N bytes: compressed frame   |

REMOTE_EVENT packet:
| 4 bytes: packet_type (0x02)  |
| 1 byte:  event_type          |
| 4 bytes: x coordinate        |
| 4 bytes: y coordinate        |
| 4 bytes: key_code            |
| 1 byte:  modifiers (shift/ctrl/alt) |
```

**Multi-threading at server:**
- 1 thread per client connection
- 1 broadcast thread per room to relay frames to all viewers
- Frame queue with max size to handle slow receivers (drop old frames)

**Security:**
- Screen stream encrypted (AES-256) before sending
- Remote control requires explicit permission grant from host
- Host can revoke control at any time

**Covers grading criteria:** App Logic + Socket, I/O, Thread, Multi Client, Cryptography

---

### 4.2 Feature 2 — Audio Stream Processing + Real-time Subtitle
**Owner:** Member 2  
**Network core:** Audio chunk streaming, server-side mixing, subtitle broadcast over TCP

#### Description
During a video call, all participants' microphone audio is streamed to the server over TCP. The server mixes audio from all speakers into one stream and broadcasts it back. In parallel, the server runs Speech-to-Text on each audio stream and optionally translates the text, sending subtitle packets to all participants for overlay display.

#### Technical Implementation

**Audio Capture & Sending:**
```
[Mic Thread] → capture raw PCM audio (e.g. 16kHz, 16-bit, mono)
             → chunk into 20ms frames (~640 bytes each)
             → encode (optional: Opus codec for compression)
             → serialize: [sender_id, timestamp, chunk_size] + [audio bytes]
             → send over TCP socket to server continuously
```

**Server-side Audio Mixer:**
```
[Per-client receiver thread] → receives audio chunks from client X
                             → places in client X's jitter buffer (reorder by timestamp)
                             → signals mixer thread

[Mixer thread] → every 20ms, pulls one chunk from each client's buffer
              → normalizes amplitude of each chunk to prevent clipping
              → sums all samples (with normalization: output = sum / num_active_speakers)
              → produces one mixed audio chunk
              → broadcasts mixed chunk to ALL clients in room
```

**Jitter Buffer (handles network reordering):**
```
Client A's buffer: [chunk_t=100] [chunk_t=120] [chunk_t=140] ...
                    ^--- sorted by timestamp, playback always from oldest
```

**Speech-to-Text + Translation pipeline:**
```
[STT thread per client] → receives audio chunks from client X's buffer copy
                        → batches into 2–3 second windows
                        → sends to STT engine (Google Speech API or local Whisper)
                        → receives transcript text + detected language
                        → if language != room default language:
                              call Translate API (Google Translate / LibreTranslate)
                        → create subtitle packet:
                              {speaker_id, original_text, translated_text, timestamp}
                        → broadcast subtitle packet to all clients over TCP
```

**Packet Structure:**
```
AUDIO_CHUNK packet:
| 4 bytes: packet_type (0x03)  |
| 4 bytes: sender_id           |
| 8 bytes: timestamp (ms)      |
| 4 bytes: chunk_size          |
| N bytes: audio data (PCM/Opus)|

SUBTITLE packet:
| 4 bytes: packet_type (0x04)  |
| 4 bytes: speaker_id          |
| 8 bytes: timestamp           |
| 2 bytes: original_lang       |
| 2 bytes: translated_lang     |
| 2 bytes: original_text_len   |
| M bytes: original_text (UTF-8)|
| 2 bytes: translated_text_len |
| K bytes: translated_text (UTF-8)|
```

**Multi-threading at server:**
- 1 receiver thread per connected client (audio input)
- 1 jitter buffer per client
- 1 central mixer thread (runs at fixed 20ms interval)
- 1 STT worker thread per active speaker (or thread pool)
- 1 broadcaster thread per room

**Latency trade-off (discussion point for defense):**
- Jitter buffer depth = 60ms → stable audio but 60ms added delay
- Jitter buffer depth = 20ms → lower delay but risk of gaps
- Tune based on network quality

**Covers grading criteria:** App Logic + Socket, I/O, Thread, Multi Client, Multi Server (session sync via Redis), Cryptography (encrypt audio chunks)

---

### 4.3 Feature 3 — Collaborative Whiteboard
**Owner:** Member 3  
**Network core:** Vector draw event sync over TCP, server as source of truth

#### Description
During a video call, any participant can open a shared whiteboard. All drawing actions (strokes, shapes, text, eraser) are immediately synchronized to all other participants in real-time via TCP socket. The whiteboard state is persisted on the server and new joiners receive the full canvas state on join.

#### Technical Implementation

**Draw Event Capture & Sending:**
```
[User draws on canvas] → capture draw event
                      → serialize as DrawEvent:
                            {type, x, y, color, stroke_width, shape_data, user_id, seq_num}
                      → send over TCP to server immediately (no batching for low latency)
```

**Server-side Event Processing:**
```
[Per-client receiver thread] → receives DrawEvent from client X
                             → assigns server-side sequence number (global order)
                             → appends to room's event log (in-memory + DB)
                             → broadcasts to ALL other clients in room
                             → sends ACK back to sender with server seq_num
```

**New joiner sync:**
```
[New client joins room] → server sends WHITEBOARD_SYNC packet:
                              {total_events: N, snapshot_png: base64}
                        → client renders snapshot, then applies any events after snapshot
```

**Draw Event Types:**
```
STROKE_START   → {x, y, color, width, pressure}
STROKE_POINT   → {x, y, pressure}              (sent continuously while drawing)
STROKE_END     → {}
SHAPE_ADD      → {shape_type, x, y, w, h, color, fill}
TEXT_ADD       → {x, y, text, font_size, color}
ERASE          → {x, y, radius}
CLEAR_ALL      → {}
UNDO           → {target_seq_num}
```

**Packet Structure:**
```
DRAW_EVENT packet:
| 4 bytes: packet_type (0x05)    |
| 4 bytes: user_id               |
| 4 bytes: room_id               |
| 4 bytes: client_seq_num        |
| 1 byte:  event_type            |
| 2 bytes: payload_size          |
| N bytes: event payload (JSON)  |

WHITEBOARD_SYNC packet:
| 4 bytes: packet_type (0x06)    |
| 4 bytes: room_id               |
| 4 bytes: event_count           |
| 4 bytes: snapshot_size         |
| N bytes: snapshot PNG bytes    |
```

**Conflict resolution:**
- Server is the single source of truth
- Server seq_num defines canonical draw order
- If two users erase the same area simultaneously, server order determines outcome
- Clients always trust server seq_num over their own

**Export feature (covers I/O criterion):**
```
[User clicks Export] → client sends EXPORT_REQUEST to server
                     → server renders full canvas to PNG using server-side renderer
                     → sends FILE_TRANSFER packet with PNG bytes over TCP
                     → client saves to local disk
```

**Multi-threading at server:**
- 1 receiver thread per client
- 1 broadcaster thread per room
- 1 snapshot generator thread (periodic, every 60 seconds → saves to DB)
- 1 export handler thread (on-demand)

**Covers grading criteria:** App Logic + Socket, I/O (file export over TCP), Thread, Multi Client, Multi Server (whiteboard state sync via Redis/shared DB), Cryptography (encrypt canvas events)

---

## 5. Shared / Supporting Features

### 5.1 Authentication (Sign up / Sign in)
- User registers with username + password
- Password hashed with **BCrypt** before storing in DB
- On login: server validates credentials, issues **JWT token** or **Session ID**
- JWT stored on client, sent in every subsequent request header
- Session persists after app restart (stored in local file on client)
- Server validates token on every connection

### 5.2 Messaging (secondary feature)
- 1-on-1 private chat
- Group chat (linked to a video call room or standalone)
- Send text messages, images, files over TCP
- Message history stored in DB, loaded on login
- Messages encrypted end-to-end (AES-256, key exchanged via RSA handshake)
- Unread message count synced via Redis across servers

### 5.3 Friend List & Room Management
- Add friends by username
- See online/offline status (synced via Redis pub/sub across servers)
- Create video call room → get room_id to share
- Invite friends to room

---

## 6. Load Balancer (self-built)

> **Must be self-built** to achieve full score on Load Balancing criterion.

### How it works:
```
1. Client opens TCP connection to Load Balancer (port 9000)
2. Load Balancer sends HELLO_REQUEST to all registered Chat Servers:
      "How many active connections do you have?"
3. Each Chat Server responds: {server_id, ip, port, connection_count}
4. Load Balancer selects server with lowest connection_count
5. Load Balancer sends to client:
      {assigned_server_ip, assigned_server_port}
6. Client closes LB connection, opens new TCP connection directly to assigned server
```

### Load Balancer packet protocol:
```
CLIENT → LB:
| CONNECT_REQUEST | client_id | preferred_region |

LB → CLIENT:
| CONNECT_RESPONSE | server_ip (4 bytes) | server_port (2 bytes) |

LB → CHAT_SERVER (internal health check):
| HEALTH_QUERY |

CHAT_SERVER → LB:
| HEALTH_RESPONSE | connection_count (4 bytes) | cpu_load (1 byte) |
```

### Algorithm: Least Connections
- Primary: lowest `connection_count`
- Tiebreaker: lowest `cpu_load`
- If a server is unreachable: mark as DOWN, exclude from selection

---

## 7. Database Schema

```sql
-- Users
CREATE TABLE users (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    username    VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,  -- BCrypt
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Sessions / JWT blacklist
CREATE TABLE sessions (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    user_id     INT REFERENCES users(id),
    token       VARCHAR(512) NOT NULL,
    expires_at  TIMESTAMP NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Friends
CREATE TABLE friendships (
    user_id     INT REFERENCES users(id),
    friend_id   INT REFERENCES users(id),
    status      ENUM('pending', 'accepted'),
    PRIMARY KEY (user_id, friend_id)
);

-- Rooms (video call rooms)
CREATE TABLE rooms (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    room_code   VARCHAR(20) UNIQUE NOT NULL,
    created_by  INT REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Messages
CREATE TABLE messages (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    room_id     INT REFERENCES rooms(id),
    sender_id   INT REFERENCES users(id),
    content     TEXT NOT NULL,           -- encrypted ciphertext
    msg_type    ENUM('text','image','file'),
    sent_at     TIMESTAMP DEFAULT NOW()
);

-- Whiteboard events (for persistence)
CREATE TABLE whiteboard_events (
    id          BIGINT PRIMARY KEY AUTO_INCREMENT,
    room_id     INT REFERENCES rooms(id),
    user_id     INT REFERENCES users(id),
    seq_num     INT NOT NULL,
    event_type  VARCHAR(30),
    payload     JSON,
    created_at  TIMESTAMP DEFAULT NOW()
);
```

---

## 8. Cryptography Plan

| Data | Algorithm | Notes |
|---|---|---|
| Passwords | BCrypt (cost=12) | Stored in DB, never plaintext |
| JWT tokens | HMAC-SHA256 | Server-side secret key |
| Message content | AES-256-GCM | Key exchanged via RSA-2048 handshake |
| Audio chunks | AES-256-GCM | Per-session key |
| Screen frames | AES-256-GCM | Per-session key |
| Whiteboard events | AES-256-GCM | Per-room key |
| File transfers | AES-256-GCM | Per-file key |

**Key exchange flow (RSA handshake on connect):**
```
Client → Server: ClientHello {client_public_key_RSA}
Server → Client: ServerHello {server_public_key_RSA, session_key_AES encrypted with client_public_key}
Client:          Decrypts session_key_AES using client_private_key
Both:            Use session_key_AES for all subsequent communication
```

---

## 9. Technology Stack (Recommended)

| Layer | Technology | Reason |
|---|---|---|
| Client UI | Java Swing / JavaFX **or** Python + PyQt | Easy TCP socket integration |
| Server | Java (multi-threading) **or** Python (threading/asyncio) | Course familiarity |
| Load Balancer | Same language as server | Simple TCP server |
| Database | MySQL or PostgreSQL | SQL, well-supported |
| Cache / Sync | Redis | Pub/sub for cross-server sync |
| Audio codec | Opus (via library) | Low latency, good quality |
| STT | OpenAI Whisper (local) or Google Speech API | Member 2's choice |
| Translation | LibreTranslate (self-host) or Google Translate API | Member 2's choice |
| Tunneling (Internet demo) | Ngrok | Expose local port to internet |

---

## 10. Demo Scenarios

### Demo via LAN
1. Run Load Balancer on `192.168.x.x:9000`
2. Run Chat Server 1 on `192.168.x.x:9001`
3. Run Chat Server 2 on `192.168.x.x:9002`
4. Connect from phone / another laptop on same WiFi → connect to `192.168.x.x:9000`
5. LB assigns to least-loaded server → client connects

### Demo via Internet
1. Run same setup as LAN
2. `ngrok tcp 9000` → get public URL e.g. `tcp://0.tcp.ngrok.io:12345`
3. Client outside LAN connects to ngrok URL → tunneled to Load Balancer → assigned to server

---

## 11. Member Responsibility Summary

| Member | Core Feature | Also responsible for |
|---|---|---|
| **Member 1** | Screen Share + Remote Control | Client UI framework, TCP connection manager |
| **Member 2** | Audio Streaming + Subtitle | Audio pipeline, STT/Translation integration |
| **Member 3** | Collaborative Whiteboard | Load Balancer implementation, DB schema |
| **All** | Authentication, Messaging (shared) | Each integrates their feature into shared codebase |

---

## 12. Key Design Decisions & Discussion Points (for project defense)

1. **Why TCP over UDP for audio/video?** — Course requirement. Trade-off: TCP guarantees delivery but adds latency. Mitigation: jitter buffer at receiver.

2. **Why self-built Load Balancer?** — Grading rubric awards full score for self-built. Demonstrates understanding of the routing logic.

3. **Why server-side audio mixing?** — Reduces bandwidth: N clients send 1 stream each, receive 1 mixed stream. Without mixing: each client would receive N-1 streams.

4. **Why Redis for cross-server sync?** — Stateless servers are easier to scale. Redis pub/sub allows Server 1 to notify Server 2 when a user's status changes.

5. **Jitter buffer depth tuning** — 60ms buffer = stable audio, 60ms delay. 20ms buffer = lower delay, risk of audio gaps. Demo both and explain.

6. **Whiteboard conflict resolution** — Server seq_num is canonical. Client optimistically renders locally, then reconciles with server order. Similar to Operational Transformation concept.
