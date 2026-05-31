# Bug Fix: Screen Share Startup Crash

## What Was Done
Fixed a failure path where clicking **Share Screen** could make the client exit immediately or leave the UI in a half-started sharing state when the local environment could not support screen capture or remote-control setup.

The main issue was that `ScreenCaptureEngine.start()` only checked whether `mss` could be imported. The actual display connection and first screen grab happened later inside the capture thread, after the UI had already continued into share startup. On systems without a usable capture backend, such as blocked X11 access, Wayland restrictions, or missing native libraries, that meant the failure happened asynchronously and was easy to miss. The share button path now performs a real one-frame capture preflight before declaring startup successful.

The share button handler is also wrapped so unexpected Python-side startup errors are logged and shown to the user instead of falling through PyQt slot handling. Capture-thread and send-thread failures now stop the share, reset the UI state, and emit a readable terminal log.

## Files Created / Modified
| File | Action | Purpose |
|------|--------|---------|
| `client/features/screen_engine.py` | Modified | Added a real `mss` initialization + one-frame grab preflight, readable traceback logging for `mss` startup failures, hard stop on capture/send/JPEG encode failures, and kept the fixed 30 FPS / quality 75 / 100% scale values unchanged. |
| `client/features/remote_control.py` | Modified | Hardened remote-control executor startup and event execution with readable logging if `pyautogui` cannot initialize or execute an event. |
| `client/ui/screen_share_widget.py` | Modified | Wrapped Share Screen startup in a defensive error boundary, reset the UI on unexpected engine stops, showed clear error dialogs, and sent `SCREEN_STOP` if a local share fails after startup. |
| `docs/07_bugfix_screen_share_startup_crash.md` | Created | This document. |

## Why It Matters
Screen sharing depends on native desktop capture support, which varies by platform and display server. A research/demo app should not disappear when the host cannot capture the screen. It should explain what failed, keep the process alive, and reset the controls so the user can continue using chat or try again after fixing the environment.

This change keeps the network protocol and server path unchanged. It only makes the local client startup path safer and more explicit.

## Verification
- `pytest tests/ -q` reports `36 passed`.
- `python3 -m py_compile client/features/screen_engine.py client/features/remote_control.py client/ui/screen_share_widget.py` passes.
- A local no-display probe now returns a clean failure and logs the `mss` traceback instead of starting a broken share:
  `Screen capture unavailable: Cannot connect to display...`
