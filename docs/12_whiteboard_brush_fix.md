# Whiteboard Brush Fix

## What Was Done
Updated the whiteboard preview and render paths to pass a QBrush to setBrush instead of a BrushStyle enum.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/ui/whiteboard_widget.py` | Modified | Fix NoBrush usage for rect/oval preview and playback. |
| `docs/12_whiteboard_brush_fix.md` | Created | Document this fix. |

## Why It Matters
PyQt6 requires setBrush to receive a QBrush (or QColor), so passing BrushStyle directly raises a TypeError and crashes the client when drawing shapes. The fix restores stable whiteboard drawing.
