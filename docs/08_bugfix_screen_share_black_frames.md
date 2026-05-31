# Bug Fix: Screen Share Black Frames

## What Was Done
Fixed a screen-sharing failure where the app entered the sharing state but no real screen pixels appeared in the frame view after installing Linux desktop dependencies for remote control.

The capture pipeline now avoids ambiguous BGRA-to-Qt conversion by using `mss`'s normalized RGB bytes and `QImage.Format_RGB888`. Startup also tries every reported monitor and prefers one whose first frame has visible pixel variation. This handles setups where `mss` reports a physical monitor that captures as black while another monitor entry, often the composite monitor, contains the real desktop.

The sharer's local preview is now wired directly from the capture engine, so the sharer can see the same captured frame that is being encoded and sent to the server. The network packet format, encryption, server relay, and fixed capture constants were not changed.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/features/screen_engine.py` | Modified | Added monitor selection with non-blank frame detection, switched frame construction to explicit RGB888 conversion, validated JPEG encoding during preflight, and emitted local preview frames for the sharer. |
| `client/ui/screen_share_widget.py` | Modified | Connected local capture preview frames to the `FrameLabel` so the sharer can verify what is being transmitted. |
| `docs/08_bugfix_screen_share_black_frames.md` | Created | This document. |

## Why It Matters
Screen sharing is only useful if the visible desktop pixels make it through the full capture, encode, relay, decode, and render pipeline. A black frame can come from the capture backend, the wrong monitor entry, or a pixel-format mismatch. By selecting a non-blank monitor and converting through explicit RGB bytes, the sender produces a valid JPEG from real screen content before any network transmission happens.

This also improves debugging: if the sharer's local preview is black, the problem is at capture time; if the sharer's preview is correct but the viewer is black, the problem is downstream.

## Verification
- `pytest tests/ -q` reports `36 passed`.
- `.venv/bin/python -m py_compile client/features/screen_engine.py client/ui/screen_share_widget.py` passes.
- The no-display startup probe still fails cleanly with a readable `mss` error, preserving the previous startup-crash fix.
