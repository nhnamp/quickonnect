"""Remote control: viewer-side input capture + host-side pyautogui execution.

Two roles share this module:

  Viewer (controller) — installs a Qt event filter on the displayed image
    widget. On every accepted mouse / key / wheel event it converts the
    position to normalized (0..1) coordinates relative to the displayed
    frame and sends a REMOTE_EVENT packet immediately (no batching).

  Host (sharer) — receives REMOTE_EVENT packets from the server. The host
    converts the normalized coordinates back to absolute pixels on the
    primary monitor and replays the gesture via pyautogui. Execution runs
    on a background thread so it never blocks the UI thread.

pyautogui only works where there is a real screen, so it is imported
lazily and any ImportError becomes a clean "Remote control unavailable"
state instead of crashing the client.
"""

import logging
import queue
import threading
from typing import Callable

from PyQt6.QtCore import QObject, QEvent, Qt, QPoint
from PyQt6.QtGui import QMouseEvent, QKeyEvent, QWheelEvent

from shared.constants import PacketType

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Qt -> pyautogui key name translation
# --------------------------------------------------------------------------

_QT_TO_PYAUTOGUI_KEY = {
    Qt.Key.Key_Return: "enter",
    Qt.Key.Key_Enter: "enter",
    Qt.Key.Key_Backspace: "backspace",
    Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Escape: "esc",
    Qt.Key.Key_Space: "space",
    Qt.Key.Key_Delete: "delete",
    Qt.Key.Key_Home: "home",
    Qt.Key.Key_End: "end",
    Qt.Key.Key_PageUp: "pageup",
    Qt.Key.Key_PageDown: "pagedown",
    Qt.Key.Key_Left: "left",
    Qt.Key.Key_Right: "right",
    Qt.Key.Key_Up: "up",
    Qt.Key.Key_Down: "down",
    Qt.Key.Key_Shift: "shift",
    Qt.Key.Key_Control: "ctrl",
    Qt.Key.Key_Alt: "alt",
    Qt.Key.Key_Meta: "win",
    Qt.Key.Key_CapsLock: "capslock",
    Qt.Key.Key_F1: "f1", Qt.Key.Key_F2: "f2", Qt.Key.Key_F3: "f3",
    Qt.Key.Key_F4: "f4", Qt.Key.Key_F5: "f5", Qt.Key.Key_F6: "f6",
    Qt.Key.Key_F7: "f7", Qt.Key.Key_F8: "f8", Qt.Key.Key_F9: "f9",
    Qt.Key.Key_F10: "f10", Qt.Key.Key_F11: "f11", Qt.Key.Key_F12: "f12",
}


def _qt_key_to_pyautogui(qt_key: int, text: str) -> str | None:
    name = _QT_TO_PYAUTOGUI_KEY.get(qt_key)
    if name is not None:
        return name
    if text and len(text) == 1 and text.isprintable():
        return text
    return None


_QT_MOUSE_BUTTON = {
    Qt.MouseButton.LeftButton: "left",
    Qt.MouseButton.RightButton: "right",
    Qt.MouseButton.MiddleButton: "middle",
}


# --------------------------------------------------------------------------
# Viewer: capture input on a widget and send REMOTE_EVENT immediately
# --------------------------------------------------------------------------

class RemoteControlSender(QObject):
    """Installs a Qt event filter on a widget that displays the shared screen.

    `get_displayed_geometry()` must return (offset_x, offset_y, draw_w, draw_h)
    of the actually-drawn frame inside the watched widget — letterboxing /
    aspect-ratio scaling means the frame doesn't always fill the widget.
    """

    def __init__(
        self,
        connection_manager,
        get_room_code: Callable[[], str | None],
        get_displayed_geometry: Callable[[], tuple[int, int, int, int] | None],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._conn = connection_manager
        self._get_room_code = get_room_code
        self._get_geom = get_displayed_geometry
        self._enabled = False
        self._watched_widget = None

    def attach(self, widget) -> None:
        if self._watched_widget is widget:
            return
        if self._watched_widget is not None:
            self.detach()
        widget.installEventFilter(self)
        widget.setMouseTracking(True)
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._watched_widget = widget

    def detach(self) -> None:
        if self._watched_widget is not None:
            try:
                self._watched_widget.removeEventFilter(self)
            except Exception:
                pass
            self._watched_widget = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    # ------------------------------------------------------------------
    # Qt event filter
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):  # noqa: N802 (Qt naming)
        if not self._enabled or obj is not self._watched_widget:
            return False

        etype = event.type()
        if etype == QEvent.Type.MouseMove:
            self._handle_mouse(event, kind="move")
            return False
        if etype == QEvent.Type.MouseButtonPress:
            self._handle_mouse(event, kind="down")
            return True
        if etype == QEvent.Type.MouseButtonRelease:
            self._handle_mouse(event, kind="up")
            return True
        if etype == QEvent.Type.Wheel:
            self._handle_wheel(event)
            return True
        if etype == QEvent.Type.KeyPress:
            self._handle_key(event, kind="key_down")
            return True
        if etype == QEvent.Type.KeyRelease:
            self._handle_key(event, kind="key_up")
            return True
        return False

    def _normalized_xy(self, pos: QPoint) -> tuple[float, float] | None:
        geom = self._get_geom()
        if geom is None:
            return None
        ox, oy, w, h = geom
        if w <= 0 or h <= 0:
            return None
        nx = (pos.x() - ox) / w
        ny = (pos.y() - oy) / h
        if nx < 0.0 or nx > 1.0 or ny < 0.0 or ny > 1.0:
            return None
        return nx, ny

    def _handle_mouse(self, event: QMouseEvent, kind: str) -> None:
        room = self._get_room_code()
        if not room:
            return
        nxy = self._normalized_xy(event.position().toPoint())
        if nxy is None:
            return
        nx, ny = nxy
        button = _QT_MOUSE_BUTTON.get(event.button(), "left") if kind != "move" else None
        payload = {
            "room_code": room,
            "kind": kind,
            "x": nx,
            "y": ny,
        }
        if button is not None:
            payload["button"] = button
        try:
            self._conn.send(PacketType.REMOTE_EVENT, payload)
        except Exception:
            logger.exception("Failed to send remote mouse event")

    def _handle_wheel(self, event: QWheelEvent) -> None:
        room = self._get_room_code()
        if not room:
            return
        nxy = self._normalized_xy(event.position().toPoint())
        if nxy is None:
            return
        nx, ny = nxy
        # Qt reports angleDelta in 1/8th of a degree per notch (120 per notch).
        # Translate to a small integer scroll amount.
        delta_units = int(event.angleDelta().y() / 120)
        if delta_units == 0:
            return
        try:
            self._conn.send(PacketType.REMOTE_EVENT, {
                "room_code": room,
                "kind": "scroll",
                "x": nx,
                "y": ny,
                "amount": delta_units,
            })
        except Exception:
            logger.exception("Failed to send remote wheel event")

    def _handle_key(self, event: QKeyEvent, kind: str) -> None:
        room = self._get_room_code()
        if not room:
            return
        name = _qt_key_to_pyautogui(event.key(), event.text())
        if name is None:
            return
        try:
            self._conn.send(PacketType.REMOTE_EVENT, {
                "room_code": room,
                "kind": kind,
                "key": name,
            })
        except Exception:
            logger.exception("Failed to send remote key event")


# --------------------------------------------------------------------------
# Host: execute REMOTE_EVENT via pyautogui on a worker thread
# --------------------------------------------------------------------------

class RemoteControlExecutor:
    """Runs incoming REMOTE_EVENT packets through pyautogui.

    The dispatcher (main UI thread) hands events to `submit()`; a single
    worker thread pulls from the queue and replays them. Putting all
    pyautogui calls on a dedicated thread guarantees the UI never blocks.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = False
        self._screen_size: tuple[int, int] | None = None
        self._pyautogui = None
        self._error: str | None = None

    def start(self) -> tuple[bool, str | None]:
        if self._running:
            return True, None
        try:
            import pyautogui
            # Disable the corner-of-screen fail-safe and the inter-call sleep:
            # we already throttle on the viewer side and the fail-safe makes
            # legitimate corner-of-screen moves abort the session.
            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0
            self._pyautogui = pyautogui
            self._screen_size = pyautogui.size()
        except Exception as exc:
            self._error = f"Remote control unavailable: {exc}"
            return False, self._error
        self._running = True
        self._thread = threading.Thread(
            target=self._loop, name="remote-control-exec", daemon=True,
        )
        self._thread.start()
        return True, None

    def stop(self) -> None:
        self._running = False
        # Push a sentinel to wake the thread.
        self._queue.put(None)

    def submit(self, payload: dict) -> None:
        if not self._running:
            return
        self._queue.put(payload)

    def _loop(self) -> None:
        pg = self._pyautogui
        while self._running:
            item = self._queue.get()
            if item is None or not self._running:
                break
            try:
                self._execute(pg, item)
            except Exception:
                logger.exception("Failed to execute remote event")

    def _execute(self, pg, payload: dict) -> None:
        if self._screen_size is None:
            return
        screen_w, screen_h = self._screen_size
        kind = payload.get("kind")
        if kind in ("move", "down", "up", "scroll"):
            nx = float(payload.get("x", 0.0))
            ny = float(payload.get("y", 0.0))
            px = max(0, min(screen_w - 1, int(nx * screen_w)))
            py = max(0, min(screen_h - 1, int(ny * screen_h)))
            if kind == "move":
                pg.moveTo(px, py, duration=0)
            elif kind == "down":
                button = payload.get("button", "left")
                pg.mouseDown(px, py, button=button)
            elif kind == "up":
                button = payload.get("button", "left")
                pg.mouseUp(px, py, button=button)
            elif kind == "scroll":
                pg.moveTo(px, py, duration=0)
                pg.scroll(int(payload.get("amount", 0)))
        elif kind == "key_down":
            key = payload.get("key")
            if key:
                pg.keyDown(key)
        elif kind == "key_up":
            key = payload.get("key")
            if key:
                pg.keyUp(key)
