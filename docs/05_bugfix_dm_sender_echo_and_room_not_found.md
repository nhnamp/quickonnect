# Bug Fix: DM Sender Echo & "Room not found" on Reply

## What Was Done

Fixed two related DM bugs that share a single root cause. After the server-agnostic DM change in `docs/04_dm_server_agnostic.md`, a user who receives a DM through the Redis push fallback has the room in their client UI (because `ChatWidget.add_message` auto-creates an entry on an unknown `room_code`) but is **not** a member of that room on their chat server — `_handle_dm_message` just forwards the `CHAT_MESSAGE` packet, it never calls `RoomManager.join_room`. When that user later tries to send into the same DM, the server's `_handle_chat_message` looks the room up with `RoomManager.get_room()`, finds nothing, and returns `ERROR 404 Room not found`. The send is rejected — which means there is no broadcast echo back to the sender either, so the sender does not see their own message.

The fix is a single, server-side **lazy join for DM rooms on send**: in `_handle_chat_message`, if `get_room()` returns `None` and the `room_code` begins with `DM-`, the server now calls `room_manager.join_room()` for the sender, then proceeds with the normal store-and-broadcast path. The room is created in PostgreSQL (or fetched if another server already created it), the sender is added to that server's in-memory `_rooms[room_code]["clients"]`, and the existing broadcast loop sends the `CHAT_MESSAGE` back to the sender — fixing Bug 1 — while the existing DM push fallback fires when the recipient is on a different server — fixing Bug 2's other direction.

### Why The Same Fix Addresses Both Bugs

- **Bug 1 — sender does not see own DM.** What the user observes: User 2 sends, the other side receives, but User 2's own chat view stays empty. Root cause: when User 2's `CHAT_MESSAGE` arrives for a DM they were only a passive recipient of, `get_room` returns None and the 404 short-circuit prevents both the DB store and the broadcast, so the sender gets no echo. How the lazy-join fixes it: lazy-joining the sender before the broadcast loop means the sender is in `clients` when the broadcast runs, so `handler.send(CHAT_MESSAGE, msg_data)` fires for them, the client's `add_message` appends it, and the message view updates.
- **Bug 2 — "Room not found" on reply to unsolicited DM.** What the user observes: User 1 receives a DM via push, types a reply, gets the error. Root cause: same — User 1 was never in the local `_rooms` map because the Redis pub/sub handler doesn't `join_room`, so `get_room` returns None and the server replies with ERROR 404. How the lazy-join fixes it: same lazy-join — User 1 is added to the room, the message is stored, the broadcast echoes to User 1, and the DM push delivers it to User 2 on the other server.

The fix is symmetric: it has no notion of "initiator" vs "replier". Whichever side sends first into an unjoined DM room is the one who gets lazy-joined.

### Why Lazy-Join Only In `_handle_chat_message`, Not In `_handle_dm_message`

I considered also lazy-joining the recipient inside `_handle_dm_message` (the pub/sub receive path) so the room would be locally present before they reply. Two reasons not to:

1. `_record_participant` inserts a row into `room_participants` on every join. The primary key is `(room_id, user_id, joined_at)` and `joined_at` defaults to `NOW()`, so every lazy-join writes a new row. Joining purely on receive — even for users who never reply — would accumulate participation rows for passive recipients, polluting the audit trail.
2. The send-side lazy-join is sufficient. A user who only reads incoming DMs and never replies has no need to be a server-side participant; nothing breaks. The moment they reply, the send path joins them.

### What Did Not Need To Change

- **Client UI** — `ChatWidget.add_message` already auto-creates the room entry on first incoming DM, and the existing broadcast echo path now works again after the lazy-join, so the sender's view updates without any client changes.
- **Binary protocol / encryption** — unchanged; the same `CHAT_MESSAGE` packet flows through the same encrypted transport.
- **Regular rooms** — the lazy-join branch is gated on `room_code.startswith("DM-")`. Regular rooms still return `ERROR 404 Room not found` when an unjoined user tries to send into them, preserving the existing behavior described in Phase 1.
- **`_handle_dm_message`** — unchanged; still pushes the `CHAT_MESSAGE` to the local user without altering room state.
- **Deterministic DM code format `DM-{sorted_name_1}-{sorted_name_2}`** — unchanged.

## Files Created / Modified

- `server/client_handler.py` — modified. In `_handle_chat_message`, when `get_room` returns `None` and `room_code` is a DM code, lazy-join the sender via `room_manager.join_room` and then continue into the normal store + broadcast + DM-push flow. For non-DM rooms the previous `ERROR 404 Room not found` short-circuit is preserved. The sender's `_current_rooms` set is updated so disconnect cleanup also drops them from the lazy-joined DM.
- `docs/05_bugfix_dm_sender_echo_and_room_not_found.md` — created. This document.

## Why It Matters

After `docs/04_dm_server_agnostic.md` removed the LB pin for DM rooms, both participants in a DM may be on different chat servers and neither is forced to formally join a room before exchanging messages — the in-memory `_rooms` entry on each server only existed if that specific user explicitly issued JOIN_ROOM. That left a gap: receiving via Redis push but not via JOIN_ROOM meant the user looked like a room member to themselves (the UI showed the room and let them type) but not to the server (no `_rooms` entry). Lazy-joining on send closes that gap. The user experience is now what people expect from any chat app: open a conversation, type, send — see your own message, and the other side sees it too, regardless of which server either of you happens to be connected through.

## Verification

- All 36 existing protocol and cryptography unit tests still pass (`pytest tests/ -q`).
- Manual flow to verify end-to-end:
  1. Start Redis, PostgreSQL, the load balancer, and two chat servers (ports 9001 and 9002).
  2. Run two clients. Register two accounts (User 1 and User 2); add each as the other's friend. Confirm both users land on different servers via the LB's least-loaded routing.
  3. **Bug 1 / forward path:** User 2 double-clicks User 1 in the friend list and sends "hello". User 1's chat panel shows the new room with the message. User 2's chat panel **also** shows "hello" in the DM room (sender now sees own message).
  4. **Bug 2 / reply path:** Without User 1 ever double-clicking User 2, User 1 clicks the freshly-arrived DM room and types "hi back". The send succeeds — no "Room not found" toast appears. User 1's own chat panel shows "hi back". User 2's chat panel updates with "hi back" via the Redis push fallback in the opposite direction.
  5. Repeat the exchange a few more times in both directions; each user always sees their own messages immediately and the other user's messages within the normal latency.
  6. `redis-cli KEYS 'room:DM-*'` still returns an empty result — DM rooms remain unpinned. `psql ... -c "SELECT room_code, COUNT(*) FROM room_participants p JOIN rooms r ON p.room_id = r.id WHERE r.room_code LIKE 'DM-%' GROUP BY room_code;"` shows one participant row per (user, lazy-join) — no flood of duplicate rows from passive receives.

---

## Follow-up: Same-Server DM Reply Echo (additional finding)

The original fix above triggered the lazy-join only when `get_room(room_code)` returned `None`. That was sufficient for the cross-server case but missed a same-server case that surfaced in the next round of testing.

### Scenario

1. User 1 sends a friend request to User 2; User 2 accepts.
2. Both clients connect through the LB; in this case they happen to land on the **same** chat server (server A) — e.g. one server is running, or the LB's least-loaded routing assigns both to the same instance.
3. User 1 double-clicks User 2 → `JOIN_ROOM "DM-test1-test2"` → server A's `_rooms["DM-..."]["clients"] = {user1_id: User1_handler}`.
4. User 1 sends "hi". Server A's `_handle_chat_message`: `get_room` returns the room; the broadcast goes to clients (just User 1, who sees their own echo); the DM push at the bottom sees recipient "test2" not in `clients`, finds User 2 connected locally to the same server, and calls `local.send(CHAT_MESSAGE, …)`. **User 2 is never added to `_rooms`.**
5. User 2's client receives the message, auto-creates the room in its UI, and User 2 sees "hi".
6. User 2 types "hi back" and presses Send. Server A's `_handle_chat_message`:
   - `get_room("DM-...")` returns the room (User 1 is still in it).
   - `room is None` is **False**, so the prior docs/05 lazy-join branch is skipped.
   - `clients = {user1_id: User1_handler}` — User 2 is absent.
   - The broadcast loop sends only to User 1 → User 1 sees the reply. The DM push sees `already_delivered = True` (User 1 is in `clients`) and skips. **Nothing is ever sent back to User 2.**

User 1 receives correctly; User 2 never sees their own reply. The result looks identical to the earlier "sender does not see own message" symptom but happens on a path the original fix could not detect.

### Root cause

The correct trigger for "this DM send needs to lazy-join" is **"the sender is not in this server's local clients map for this DM room"**, not **"the room is missing on this server"**. When the OTHER participant has joined locally, the room exists, so the missing-room test fires `False` and the lazy-join is silently bypassed even though the sender is still not a member.

### Fix

In `_handle_chat_message`, replace the previous `if room is None and room_code.startswith("DM-"):` guarded lazy-join with an unconditional same-condition check for DM rooms:

```python
is_dm = room_code.startswith("DM-")
if is_dm:
    clients_now = self._server.room_manager.get_room_clients(room_code)
    if self.user_id not in clients_now:
        state, lazy_error = self._server.room_manager.join_room(
            room_code, self.user_id, self.username, self,
        )
        ...
        self._current_rooms.add(room_code)
```

`get_room_clients` returns `{}` when the room is missing entirely, so `self.user_id not in clients_now` is `True` in **both** problem cases — the original cross-server case (room absent locally) and the new same-server case (room present locally but sender not in it). `join_room` is idempotent on `room_data["clients"]` (the assignment overwrites the same handler), and gating the call on actual absence prevents redundant `room_participants` inserts when the sender is already a local member.

The `room is None` check that followed the prior lazy-join is now a single generic check: if the room is still missing after the DM lazy-join branch ran (or for any non-DM message), reply with `ERROR 404 Room not found`.

### Why both bugs in this file share one fix now

- **Sender's server has no `_rooms` entry at all** (cross-server case, the original Bug 2). Before: `room is None` triggered the lazy-join, so it worked. After: `self.user_id not in clients_now` (where `clients_now == {}`) triggers the lazy-join — same outcome.
- **Sender's server has an `_rooms` entry created by the other participant** (same-server case, this follow-up). Before: `room is not None` so the lazy-join was skipped and the sender was never echoed. After: `self.user_id not in clients_now` (User 1 is in clients_now but User 2 is not) triggers the lazy-join — the broadcast now includes the sender and the echo works.
- **Sender already in local clients** (normal case, e.g. they used `_on_start_dm` and JOIN_ROOM'd first). Before: no lazy-join, normal broadcast. After: `self.user_id in clients_now` so the lazy-join is skipped — identical behaviour, no extra `room_participants` row written.

### Files Modified (follow-up)

- `server/client_handler.py` — replaced the `if room is None` lazy-join branch in `_handle_chat_message` with a membership-based check: `if is_dm and self.user_id not in get_room_clients(room_code): join_room(...)`. The subsequent `if room is None: ERROR 404` is now a generic guard that fires only for non-DM rooms that genuinely do not exist locally. The lower DM-push block was tightened to reuse the `is_dm` local instead of recomputing the prefix check.

### Verification (follow-up)

- All 36 unit tests still pass (`pytest tests/ -q`).
- Manual same-server scenario (the exact one in the bug report):
  1. Start one chat server only (server-9001), Redis, PostgreSQL, and the LB. Both clients are forced onto the same server.
  2. Register User 1 and User 2; add each as the other's friend.
  3. User 1 double-clicks User 2 → DM room opens.
  4. User 1 sends "hi" → User 1 and User 2 both see "hi" (User 2 via the local DM push).
  5. User 2 types "hi back" and sends → **User 2 now sees their own "hi back" immediately** (broadcast echo via the newly lazy-joined membership). User 1 also sees "hi back" via the same broadcast.
  6. Continue the exchange; each subsequent message echoes correctly for both sides because both are now in `_rooms["DM-..."]["clients"]` on the shared server, and the broadcast loop covers both ends without needing the DM push at all.
- Cross-server scenario (the original docs/05 case) is unchanged in behaviour: `get_room_clients` returns `{}` on the sender's server, the lazy-join fires, the broadcast echoes the sender, and the DM push forwards the message to the other server via Redis.
