# Bug Fix: Regular Room Join Routing

## What Was Done
Fixed the inconsistent "Room is on another server. Please rejoin with the room code." error when a user joined an existing regular room from a client already connected to a different chat server.

The Redis room pin itself was not mismatched: both the chat server and load balancer use `room:{room_code}`, and both use server IDs such as `server-9001`. The real problem was that the Join button bypassed the load balancer. It sent `JOIN_ROOM` over the user's current server connection, so the join only worked when that current server happened to be the pinned room server. If the user was logged into another server, the receiving server correctly returned the redirect error.

Regular room joins now ask the load balancer for an assignment using the entered room code, reconnect to the assigned chat server, authenticate with the saved JWT, and only then send `JOIN_ROOM`. Creating rooms is unchanged, and DM rooms still bypass pinning as intended.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/chat_widget.py` | Modified | Added a dedicated `join_room_requested` signal so the Join button can be routed through the load balancer, while Create still uses the existing direct `JOIN_ROOM` path. |
| `client/network/connection.py` | Modified | Tracks the currently connected server address so a Join operation can avoid reconnecting when the load balancer assigns the same server. |
| `client/ui/login_window.py` | Modified | Preserves the active load balancer host and port in the login success payload, including when the user overrides the defaults in the login screen. |
| `client/ui/main_window.py` | Modified | Handles regular room join requests by calling the load balancer with the room code. If the assigned server is already connected, it sends `JOIN_ROOM` directly; otherwise it reconnects to the assigned server, re-authenticates with the saved JWT, and then sends `JOIN_ROOM`. DM joins are left on the existing server-agnostic path. |
| `docs/06_bugfix_room_routing.md` | Created | This document. |

## Why It Matters
Regular rooms carry screen sharing, future audio, and future whiteboard state, so all participants must land on the same chat server. The server-side redirect check was doing its job by rejecting joins on the wrong server; the client simply needed to route through the load balancer before attempting the join.

With this fix, the user-facing Join flow matches the architecture: the room code reaches the load balancer before the server connection is chosen, the load balancer reads the existing Redis pin, and every participant joins the pinned server instead of depending on whichever server they used for login.

## Verification
- All existing unit tests still pass: `pytest tests/ -q` reports `36 passed`.
- Expected manual flow:
  1. Start Redis, PostgreSQL, the load balancer, and two chat servers.
  2. User 1 creates a regular room and lands on `server-9001`; Redis contains `room:{code} -> server-9001`.
  3. User 2 and User 3 click Join and enter the same code.
  4. Their clients call the load balancer with that room code, reconnect to `server-9001`, authenticate, and send `JOIN_ROOM`.
  5. No redirect dialog appears, and all three users are participants in the same room on the pinned server.
  6. DM rooms remain unaffected because `DM-` room codes still use the existing server-agnostic join path.
