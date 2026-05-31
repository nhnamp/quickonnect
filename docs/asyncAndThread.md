**Key Point**

QuicKonNect does not use Python `asyncio`. Its asynchronous behavior is built with:

- Qt event loop + `QTimer`
- `QThread` workers for UI-safe background work
- Python `threading.Thread`
- thread-safe `Queue`
- `threading.Lock` / `Condition`
- one server thread per client socket

**Client-Side Async Workflow**

Login/auth runs off the UI thread. `_AuthWorker` extends `QThread` in [login_window.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/login_window.py:18). Its `run()` method calls the load balancer, connects to the chat server, sends login/register/token packets, then waits for the auth response. The worker is started at [login_window.py:174](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/login_window.py:174), so the login screen does not freeze while network I/O happens.

After connection, `ConnectionManager` creates two background threads in [connection.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:60):

- [connection.py:60](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:60): receiver thread
- [connection.py:63](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:63): heartbeat thread

The receiver thread runs `_receiver_loop()` at [connection.py:111](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:111). It blocks on `read_packet()` at [line 114](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:114), then puts incoming packets into `packet_queue` at [line 115](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:115). That queue is created at [connection.py:37](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:37).

The UI does not update directly from the receiver thread. Instead, [main_window.py:187](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:187) starts a `QTimer` every 16 ms, roughly 60 Hz. `_poll_packets()` drains the queue at [main_window.py:192](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:192), then calls `_handle_packet()` on the UI thread. This is the main async UI pattern:

```text
socket receiver thread
-> packet_queue
-> Qt timer on UI thread
-> UI update
```

For sending, `ConnectionManager.send()` is thread-safe. [connection.py:86](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:86) wraps socket writes with `_send_lock`, preventing heartbeat, chat, screen-frame, and remote-control packets from writing bytes into the same TCP stream at the same time.

**Message Feature Thread Workflow**

For a chat message:

1. UI thread: user presses Send in [chat_widget.py:141](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:141).
2. UI thread: `ChatWidget` emits `CHAT_MESSAGE` at [chat_widget.py:148](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/chat_widget.py:148).
3. UI thread or worker context: `MainWindow._send_packet()` forwards it to `ConnectionManager.send()` at [main_window.py:271](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/ui/main_window.py:271).
4. Client network send lock: [connection.py:86](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/network/connection.py:86).
5. Server client thread: one `ClientHandler` reads that packet in its own thread at [client_handler.py:191](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:191).
6. Server stores and broadcasts the message.
7. Client receiver thread receives the broadcast and puts it into `packet_queue`.
8. UI timer drains the packet and renders it through `ChatWidget.add_message()`.

So message receive is asynchronous; the UI is never blocked waiting for the socket.

**Server-Side Thread Workflow**

The chat server uses a classic thread-per-client model.

- [acceptor.py:10](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:10): `Acceptor` extends `threading.Thread`.
- [acceptor.py:33](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:33): accepts a client socket.
- [acceptor.py:34](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:34): creates a `ClientHandler`.
- [acceptor.py:35](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/acceptor.py:35): starts that handler thread.

Each client connection is handled by [client_handler.py:20](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:20), where `ClientHandler` extends `threading.Thread`. Its lifecycle is described directly in the code: accept, handshake, auth, main loop, disconnect. The main loop reads packets at [client_handler.py:195](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:195) and dispatches them at [line 203](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:203).

Server socket writes are also protected. [client_handler.py:73](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/client_handler.py:73) uses `_send_lock` before calling `send_packet()`. This prevents two server-side events from corrupting one client’s socket stream.

Shared server state is protected too:

- [server/main.py:32](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:32): `_clients_lock` protects connected clients.
- [server/main.py:75](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:75): registering clients uses the lock.
- [room_manager.py:34](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/room_manager.py:34): room state has its own lock.
- [room_manager.py:81](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/room_manager.py:81): joining a room modifies room state under that lock.
- [room_manager.py:127](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/room_manager.py:127): room client reads are lock-protected and returned as a copy.

**Load Balancer Threads**

The load balancer also uses background threads.

- [health_checker.py:23](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/health_checker.py:23): `HealthChecker` extends `threading.Thread`.
- [health_checker.py:39](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/health_checker.py:39): it loops while running.
- [health_checker.py:40](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/health_checker.py:40): checks all servers.
- [health_checker.py:41](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/health_checker.py:41): sleeps between checks.

For incoming LB clients, [loadbalancer/main.py:41](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/main.py:41) accepts a socket, then [line 42](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/loadbalancer/main.py:42) creates a new thread per routing request.

**Screen And Remote-Control Threads**

Screen sharing has two explicit background threads in [screen_engine.py](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:88):

- [screen_engine.py:88](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:88): capture thread
- [screen_engine.py:91](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:91): send thread

The capture thread grabs frames and enqueues them. The queue is guarded by a condition variable at [screen_engine.py:63](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:63). The send thread waits for frames at [screen_engine.py:194](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:194), then sends `SCREEN_FRAME` at [line 204](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/screen_engine.py:204).

Remote control has another worker thread on the sharer side. [remote_control.py:279](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:279) creates the `remote-control-exec` thread. Incoming remote events are queued at [remote_control.py:303](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:303), then executed by the worker loop at [line 308](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/client/features/remote_control.py:308). This keeps `pyautogui` mouse/keyboard execution away from the UI thread.

**Redis Pub/Sub Async Workflow**

The server also has a Redis pub/sub listener thread.

- [server/main.py:152](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:152): subscribes to Redis channels.
- [server/main.py:154](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:154): creates the pub/sub thread.
- [server/main.py:157](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:157): loops over Redis messages.
- [server/main.py:173](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:173): handles cross-server DM messages.
- [server/main.py:237](/home/nhaatjnamphan/Workspace/coding/QuicKonNect/server/main.py:237): forwards DM packets to the local client if present.

**Summary**

The project’s async model is thread-based and event-loop-based:

```text
Client UI thread
+ QThread auth/join workers
+ socket receiver thread
+ heartbeat thread
+ Qt timer packet polling
+ screen capture thread
+ screen send thread
+ remote-control executor thread

Server acceptor thread
+ one ClientHandler thread per TCP client
+ Redis pub/sub thread

Load balancer main accept loop
+ one router thread per LB request
+ health checker thread
```

The important safety design is that background threads do not directly mutate Qt widgets, and socket writes are serialized with locks on both client and server.