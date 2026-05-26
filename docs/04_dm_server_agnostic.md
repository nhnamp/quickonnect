# DM Rooms Made Server-Agnostic

## What Was Done

Removed Load Balancer pinning for DM rooms so both participants can connect to whichever chat server is least loaded for them, independently. All cross-server delivery — in both directions — goes through the existing Redis `dm_messages` pub/sub channel introduced in the previous fix (`docs/03_bugfix_dm_realtime_delivery.md`). The deterministic DM room code format `DM-{sorted_name_1}-{sorted_name_2}` is unchanged, and regular (non-DM) rooms keep the existing pin-to-server behavior unchanged.

### Why The Previous Fix Was Incomplete

The previous fix pushed a sender's DM message to the recipient via Redis pub/sub, so the recipient finally saw it without manually joining. But the room itself was still pinned: the first user to start a DM caused the LB to pin `DM-X-Y` to that user's server. When the other user tried to reply (by double-clicking the friend), the LB redirected them to the original server, and `room_manager.join_room` also rejected the join with a 307 because the Redis pin mapped to a different server. Result: reply path failed.

### The Approach

DM rooms are now treated as "logical, location-free" rooms. There is no room→server mapping anywhere for them. Two users in the same DM may be on two different chat servers; each server holds an in-memory entry for the room with only its local participant inside. PostgreSQL is the single source of truth for messages and history; it does not care which server stored them. Cross-server real-time delivery is handled by the existing `dm_messages` pub/sub channel, which is fully symmetric:

- Sender on server A: room broadcast delivers to local participants; the DM push fallback fires for any recipient not present locally and either delivers directly (same-server recipient) or publishes to Redis (cross-server recipient).
- Recipient on server B: subscribes to `dm_messages`; on receipt of a message addressed to its local user, sends `CHAT_MESSAGE` to that client.
- Replies from server B work the same way in reverse — the logic is anchored on `self.username`, not on who "started" the DM.
- The `originating_server_id` field in each pub/sub envelope suppresses self-echoes on the publisher's own server.

Regular rooms still hit the Redis pin path, so a room created via "Create Room" is still pinned to one chat server and clients are still redirected as before.

### Symmetry Verification

The DM push logic in `server/client_handler.py` (`_handle_chat_message` + `_extract_dm_recipient`) extracts the recipient by anchoring on the sender's own username — either prefix-match or suffix-match against the inner part of the room code. This works regardless of who is sending, so User 2 replying to User 1 produces exactly the same flow as User 1 messaging User 2.

The `_handle_dm_message` pub/sub handler in `server/main.py` already filters out messages whose `originating_server_id` matches this server's id. Combined with the in-room `already_delivered` check in `_handle_chat_message`, this means:

- If both users are on the same server: room broadcast delivers to both, the DM-push fallback notes the recipient is already in the room and skips. No duplicates.
- If users are on different servers: the originating server delivers to its own local user via room broadcast, then publishes to Redis; the other server receives the pub/sub message and delivers. No echo back to the originator because of the `originating_server_id` check.
- Either direction (User 1 → User 2 or User 2 → User 1) follows the same code paths.

### What Did Not Need To Change

- **Client UI** — `ChatWidget.add_message` already auto-creates a room entry when a `CHAT_MESSAGE` arrives for an unknown `room_code`, so the recipient sees the conversation appear automatically.
- **Client LB call** — `client/network/lb_client.py` already passes the room code to the LB; with the LB change, DM codes simply return least-loaded instead of a pinned server. No client-side awareness of "DM" is required.
- **Generic 307 redirect message** in `client/ui/main_window.py` — it is not DM-specific; it remains valid and necessary for regular pinned rooms. With the LB and server changes, it can no longer fire for DM rooms because no DM redirect is ever produced.
- **`_handle_dm_message` echo suppression** in `server/main.py` — already symmetric since the previous fix.

## Files Created / Modified

| File | Action | Purpose |
|------|--------|---------|
| `loadbalancer/router.py` | Modified | `_resolve` skips both the Redis room→server lookup and the pin write when the room code starts with `DM-`; DMs always return the least-loaded UP server. Regular rooms unchanged. |
| `server/room_manager.py` | Modified | Added module-level `_is_dm_room` helper. `join_room` skips the cross-server redirect check and the Redis register for DM rooms. `leave_room` and `remove_client_from_all_rooms` skip the Redis unregister for DM rooms. Local in-memory tracking, DB participant rows, and message history loading all behave the same. |
| `docs/04_dm_server_agnostic.md` | Created | This document. |

No changes were needed to `server/client_handler.py`, `server/main.py`, `client/network/lb_client.py`, or any client UI file — the previous fix already implemented a symmetric DM delivery path, and removing the pinning was enough to let it work in both directions.

## Why It Matters

This completes the DM story. Both users can open a DM conversation independently, on whichever server the LB happens to assign them, and messages flow in real time in both directions without any 307 redirects or manual rejoin steps. The architecture remains consistent: regular rooms still benefit from room-pinning (no cross-server media relay needed for shared-screen, audio, whiteboard in Phases 2–4), while DMs — which only carry small text payloads that PostgreSQL already persists centrally — are free to live anywhere.

The change is minimal and surgical: two helpers gated on a `room_code.startswith("DM-")` check, in the LB and the room manager. There is no new protocol, no new packet types, no new threads, and no new Redis channels beyond the `dm_messages` channel that already existed from the previous fix.

## Verification

- All 36 existing protocol and cryptography unit tests still pass (`pytest tests/ -q`).
- Manual flow to verify end-to-end:
  1. Start Redis, PostgreSQL, the load balancer, and two chat servers (ports 9001 and 9002).
  2. Run two clients. Register two accounts (User 1 and User 2); add each as the other's friend.
  3. Launch User 1's client first; the LB sends it to server-9001. Launch User 2's client; the LB sends it to server-9002 (the now least-loaded one).
  4. User 1 double-clicks User 2 in the friend list and sends "hello". User 2's chat panel shows the new conversation and the message immediately, with no manual action.
  5. User 2 double-clicks User 1 in their own friend list — no redirect message appears. User 2 sends "hi back". User 1's chat panel updates immediately with the reply.
  6. Both users can scroll up and see the full PostgreSQL-backed message history regardless of which server they are connected through.
  7. `redis-cli KEYS 'room:DM-*'` returns an empty result, confirming DM rooms are not pinned. `redis-cli KEYS 'room:*'` still shows entries for any regular rooms that exist.
