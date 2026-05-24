# Bug Fix: Real-Time Delivery of DM Messages to Recipient

## What Was Done

Fixed a bug where DM (direct message) messages sent by User 1 were not delivered to User 2 in real-time. Previously, User 2 had to manually double-click User 1's name in the friend list to join the same deterministic DM room before any of User 1's messages appeared.

### Root Cause

In `server/client_handler.py`, the `_handle_chat_message` method broadcast incoming chat messages only to clients currently joined to the room (via `RoomManager.get_room_clients`). DM rooms are special: when User 1 double-clicks a friend, only User 1 sends `JOIN_ROOM`. User 2 never joined that room, so the broadcast loop skipped them entirely.

### Fix Summary

After the normal room broadcast, the server now detects DM rooms (room code starting with `DM-`), extracts the recipient's username from the room code, and pushes the message to that recipient using one of two paths:

1. **Same-server path** — if the recipient is connected to this chat server (looked up by username from the in-memory `_clients` map), the server sends `CHAT_MESSAGE` directly to their socket.
2. **Cross-server path** — if the recipient is on a different chat server, the message is published to a new Redis pub/sub channel `dm_messages`. Every chat server subscribes to this channel; whichever server has the recipient locally delivers the packet. The originating server skips its own published echoes via an `originating_server_id` field.

If the recipient happens to be in the room already (e.g. they previously joined and stayed), the normal room broadcast already delivered the message, and the DM push code skips them to avoid duplicates. If the recipient is offline, no delivery is attempted; the message is already persisted in PostgreSQL and will appear via `MESSAGE_HISTORY` the next time they join the room.

The client side required no changes. `ChatWidget.add_message` already auto-creates an entry for an unknown `room_code`, so an incoming DM message for a never-before-seen room appears in the room list and message view automatically.

### Why The Existing Constraints Were Preserved

- **Binary protocol header unchanged** — no new packet types or header fields; the existing `CHAT_MESSAGE` packet is reused.
- **AES-GCM encryption unchanged** — `handler.send()` already encrypts every outgoing packet with the per-connection AES session key.
- **Regular rooms unaffected** — the DM push only runs for room codes prefixed with `DM-`; ordinary room codes (e.g. `ABC-1234`) take the same path as before.
- **DM room code format preserved** — recipient parsing anchors on `self.username` as either a prefix or suffix of the room code's inner part, so the canonical `DM-{sorted_name_1}-{sorted_name_2}` format is unchanged. Hyphens inside usernames are handled correctly by the anchor approach.
- **Thread safety** — the same patterns already used by the friend pub/sub (`_clients_lock`, per-handler `_send_lock`) are reused for the new path. The new Redis channel is added to the existing subscription set inside the existing `_pubsub_loop` thread, so no new threads are introduced.

## Files Created / Modified

| File | Action | Purpose |
|------|--------|---------|
| `server/client_handler.py` | Modified | Added DM detection and recipient push at the end of `_handle_chat_message`. Added helper `_extract_dm_recipient` that anchors on `self.username` to handle usernames containing hyphens. |
| `server/main.py` | Modified | Added `get_client_by_username` lookup, `publish_dm_message` Redis publisher, subscription to the new `dm_messages` channel, and the `_handle_dm_message` pub/sub handler with originating-server deduplication. |
| `docs/03_bugfix_dm_realtime_delivery.md` | Created | This document. |

## Why It Matters

DM conversations are the most common use of a chat app — a feature that requires the recipient to manually click into a room before seeing any messages is effectively broken. With this fix, DMs behave the way users expect: the recipient sees an incoming message immediately, even if they have never opened that conversation before, and the same flow works whether both users are connected to the same chat server or split across two servers behind the load balancer.

The pattern used here (publish a small JSON envelope on a dedicated Redis channel, have every server subscribe and deliver only to its local clients, skip own echoes with `originating_server_id`) is the same pattern already used for `user_status` and `friend_events`. Reusing it keeps the cross-server delivery story uniform and easy to reason about, and avoids introducing any new threads or sockets.

## Verification

- All 36 existing protocol and cryptography unit tests still pass (`pytest tests/ -q`).
- Manual flow to verify end-to-end:
  1. Start Redis, PostgreSQL, the load balancer, and two chat servers (ports 9001 and 9002).
  2. Run two clients. Register two accounts; add each as the other's friend.
  3. From the LB routing, push the two clients onto different chat servers (the load balancer picks the least-loaded server, so the second connection should land on the second server).
  4. User 1 double-clicks User 2 in the friend list and types a message.
  5. User 2's chat panel automatically shows a new entry `DM-{name1}-{name2}` with User 1's message — no manual action required.
