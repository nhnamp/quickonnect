# Inline Image Chat Preview

## What Was Done
Updated the chat transcript so image messages display an inline thumbnail instead of only showing a text attachment label. Attachments with an image MIME type also render as thumbnails even if the sender selected them through the File button. Non-image files still display as compact file labels, and the existing Save Attachment flow remains available for both image and file messages.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/chat_widget.py` | Modified | Renders chat history as rich HTML and registers decoded image thumbnails as Qt document resources. |
| `docs/16_inline_image_chat_preview.md` | Created | Documents this UI improvement. |

## Why It Matters
Image messages should be visually recognizable during a live demo. Showing a thumbnail in the conversation makes the feature easier to understand for users and evaluators while preserving the safer attachment validation and save behavior already implemented.
