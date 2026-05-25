# Bug Fix: Message History Routed To The Correct Room

## What Was Done
Fixed a client/server integration bug where `MESSAGE_HISTORY` packets did not include the room code. The client previously had to guess which room should receive the history by looking at local room state. That could put history into the wrong room when a user had already joined more than one room.

The server now includes `room_code` in every `MESSAGE_HISTORY` payload after a successful room join. The client `ChatWidget.load_history()` now accepts that room code and uses it as the primary target room before falling back to local state.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `server/client_handler.py` | Modified | Added `room_code` to the `MESSAGE_HISTORY` packet sent after room join. |
| `client/ui/main_window.py` | Modified | Passes the received `room_code` into `ChatWidget.load_history()`. |
| `client/ui/chat_widget.py` | Modified | Uses explicit `room_code` to attach history to the correct room. |
| `docs/10_bugfix_message_history_room_routing.md` | Created | This documentation file. |

## Why It Matters
Phase 5 added file and image messages, so correct message history routing became more important. If history is attached to the wrong room, users can see unrelated messages or attachments in the wrong conversation. Explicitly carrying `room_code` removes that ambiguity and makes room history loading predictable.
