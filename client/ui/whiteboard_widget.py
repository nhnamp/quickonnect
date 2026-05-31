"""Collaborative whiteboard widget.

Provides a vector graphics canvas using QGraphicsView and QGraphicsScene
with drawing tools (pen, rect, oval, text, eraser), undo stack, and exports.
"""

import logging
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import (
    QColor, QFont, QImage, QPainter, QPainterPath,
    QPen, QBrush, QAction, QIcon, QPixmap,
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsPathItem, QGraphicsRectItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QInputDialog, QColorDialog, QButtonGroup,
    QFileDialog, QMessageBox,
)

logger = logging.getLogger(__name__)

# Constants matching server
CANVAS_WIDTH = 1920
CANVAS_HEIGHT = 1080
BACKGROUND_COLOR = "#1e1e1e"


class WhiteboardScene(QGraphicsScene):
    """Custom QGraphicsScene that captures drawing mouse events.

    During dragging, it renders a dotted preview shape. Upon release, it
    removes the preview and fires the completed shape payload.
    """

    shape_completed = pyqtSignal(str, dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSceneRect(0, 0, CANVAS_WIDTH, CANVAS_HEIGHT)
        self.setBackgroundBrush(QColor(BACKGROUND_COLOR))

        # Tool configuration
        self.active_tool = "pen"  # pen, rect, oval, text, eraser
        self.pen_color = QColor("#ffffff")
        self.stroke_width = 4

        # Drag state
        self._start_pos: QPointF | None = None
        self._temp_item = None
        self._temp_points: list[list[int]] = []

    def set_tool(self, tool: str) -> None:
        self.active_tool = tool
        logger.debug("Whiteboard tool set to: %s", tool)

    def set_color(self, color: QColor) -> None:
        self.pen_color = color

    def set_stroke_width(self, width: int) -> None:
        self.stroke_width = width

    # ── Mouse event overrides ──────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        self._start_pos = event.scenePos()
        x, y = int(self._start_pos.x()), int(self._start_pos.y())

        # Determine effective drawing color
        color = QColor(BACKGROUND_COLOR) if self.active_tool == "eraser" else self.pen_color
        width = self.stroke_width * 3 if self.active_tool == "eraser" else self.stroke_width

        preview_pen = QPen(
            color,
            width,
            Qt.PenStyle.DashLine if self.active_tool in ("rect", "oval") else Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )

        if self.active_tool in ("pen", "eraser"):
            self._temp_points = [[x, y]]
            path = QPainterPath()
            path.moveTo(self._start_pos)
            self._temp_item = QGraphicsPathItem()
            self._temp_item.setPath(path)
            self._temp_item.setPen(preview_pen)
            self.addItem(self._temp_item)

        elif self.active_tool == "rect":
            self._temp_item = QGraphicsRectItem()
            self._temp_item.setRect(self._start_pos.x(), self._start_pos.y(), 0, 0)
            self._temp_item.setPen(preview_pen)
            self._temp_item.setBrush(Qt.BrushStyle.NoBrush)
            self.addItem(self._temp_item)

        elif self.active_tool == "oval":
            self._temp_item = QGraphicsEllipseItem()
            self._temp_item.setRect(self._start_pos.x(), self._start_pos.y(), 0, 0)
            self._temp_item.setPen(preview_pen)
            self._temp_item.setBrush(Qt.BrushStyle.NoBrush)
            self.addItem(self._temp_item)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._start_pos is None or self._temp_item is None:
            super().mouseMoveEvent(event)
            return

        curr_pos = event.scenePos()
        x, y = int(curr_pos.x()), int(curr_pos.y())

        if self.active_tool in ("pen", "eraser"):
            self._temp_points.append([x, y])
            path = self._temp_item.path()
            path.lineTo(curr_pos)
            self._temp_item.setPath(path)

        elif self.active_tool in ("rect", "oval"):
            # Calculate coordinates
            x1, y1 = self._start_pos.x(), self._start_pos.y()
            x2, y2 = curr_pos.x(), curr_pos.y()
            rx = min(x1, x2)
            ry = min(y1, y2)
            rw = abs(x2 - x1)
            rh = abs(y2 - y1)
            self._temp_item.setRect(rx, ry, rw, rh)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return

        curr_pos = event.scenePos()

        # Remove preview item
        if self._temp_item is not None:
            self.removeItem(self._temp_item)
            self._temp_item = None

        if self._start_pos is not None:
            x1, y1 = int(self._start_pos.x()), int(self._start_pos.y())
            x2, y2 = int(curr_pos.x()), int(curr_pos.y())

            if self.active_tool in ("pen", "eraser"):
                if len(self._temp_points) >= 1:
                    payload = {
                        "points": self._temp_points,
                        "color": self.pen_color.name(),
                        "width": self.stroke_width,
                    }
                    self.shape_completed.emit(self.active_tool, payload)

            elif self.active_tool in ("rect", "oval"):
                rx = min(x1, x2)
                ry = min(y1, y2)
                rw = abs(x2 - x1)
                rh = abs(y2 - y1)
                if rw > 2 and rh > 2:
                    payload = {
                        "rect": [rx, ry, rw, rh],
                        "color": self.pen_color.name(),
                        "width": self.stroke_width,
                    }
                    self.shape_completed.emit(self.active_tool, payload)

            elif self.active_tool == "text":
                text, ok = QInputDialog.getText(
                    None, "Text Tool", "Enter text to place on whiteboard:"
                )
                if ok and text.strip():
                    payload = {
                        "text": text.strip(),
                        "text_pos": [x2, y2],
                        "color": self.pen_color.name(),
                        "width": self.stroke_width,
                    }
                    self.shape_completed.emit("text", payload)

        self._start_pos = None
        self._temp_points.clear()
        super().mouseReleaseEvent(event)


class WhiteboardWidget(QWidget):
    """Drawing panel widget including shape tools, color picker, and stroke options.

    Synchronizes actions with the server via custom Qt signals and event slots.
    """

    # Emitted when drawing is finalized locally: (event_type, payload)
    draw_created = pyqtSignal(str, dict)
    # Emitted when export requested
    export_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # local seq stack for undo/redo
        self._my_drawn_seqs: list[int] = []
        self._my_undone_seqs: list[int] = []
        # Maps target_seq -> undo event's seq_num assigned by server
        self._undo_to_redo_map: dict[int, int] = {}

        # Graphics item tracker: seq_num -> QGraphicsItem
        self._scene_items: dict[int, Any] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Toolbar Row ──────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(4, 2, 4, 2)
        toolbar.setSpacing(8)

        # Tool buttons
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        tools = [
            ("✏️ Pen", "pen"),
            ("🔲 Rect", "rect"),
            ("⚪ Oval", "oval"),
            ("🔤 Text", "text"),
            ("🧹 Eraser", "eraser"),
        ]
        for label, code in tools:
            btn = QPushButton(label)
            btn.setCheckable(True)
            if code == "pen":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, c=code: self._on_tool_changed(c))
            toolbar.addWidget(btn)
            self._tool_group.addButton(btn)

        toolbar.addSpacing(16)
        toolbar.addWidget(QLabel("Color:"))

        # Colors presets
        self._color_group = QButtonGroup(self)
        colors = [
            ("White", "#ffffff"),
            ("Red", "#ff5555"),
            ("Green", "#55ff55"),
            ("Blue", "#5555ff"),
            ("Yellow", "#ffff55"),
        ]
        for name, hex_code in colors:
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFixedWidth(24)
            btn.setFixedHeight(24)
            btn.setStyleSheet(f"background-color: {hex_code}; border: 1px solid #555;")
            if name == "White":
                btn.setChecked(True)
            btn.clicked.connect(lambda checked, h=hex_code: self._on_color_preset(h))
            toolbar.addWidget(btn)
            self._color_group.addButton(btn)

        custom_color_btn = QPushButton("🎨 Custom")
        custom_color_btn.clicked.connect(self._on_custom_color)
        toolbar.addWidget(custom_color_btn)

        toolbar.addSpacing(16)
        toolbar.addWidget(QLabel("Width:"))

        self._width_slider = QSlider(Qt.Orientation.Horizontal)
        self._width_slider.setRange(1, 20)
        self._width_slider.setValue(4)
        self._width_slider.setFixedWidth(100)
        self._width_slider.valueChanged.connect(self._on_width_changed)
        toolbar.addWidget(self._width_slider)

        self._width_label = QLabel("4")
        toolbar.addWidget(self._width_label)

        toolbar.addStretch()

        # Action buttons
        self._undo_btn = QPushButton("↩️ Undo")
        self._undo_btn.clicked.connect(self._on_undo_clicked)
        toolbar.addWidget(self._undo_btn)

        self._redo_btn = QPushButton("🔁 Redo")
        self._redo_btn.clicked.connect(self._on_redo_clicked)
        toolbar.addWidget(self._redo_btn)

        self._export_btn = QPushButton("💾 Save PNG")
        self._export_btn.clicked.connect(lambda: self.export_requested.emit())
        toolbar.addWidget(self._export_btn)

        layout.addLayout(toolbar)

        # ── QGraphicsView Area ────────────────────────────────────────
        self.scene = WhiteboardScene(self)
        self.scene.shape_completed.connect(self._on_shape_completed)

        self.view = QGraphicsView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setStyleSheet("border: 1px solid #333; background-color: #1e1e1e;")
        # Keep aspect ratio when scaling
        self.view.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)

        layout.addWidget(self.view, stretch=1)

    # ── Tool / Settings updates ────────────────────────────────────────

    def _on_tool_changed(self, tool: str) -> None:
        self.scene.set_tool(tool)

    def _on_color_preset(self, hex_code: str) -> None:
        self.scene.set_color(QColor(hex_code))

    def _on_custom_color(self) -> None:
        color = QColorDialog.getColor(self.scene.pen_color, self, "Pick stroke color")
        if color.isValid():
            self.scene.set_color(color)
            # Uncheck preset color buttons
            for btn in self._color_group.buttons():
                btn.setChecked(False)

    def _on_width_changed(self, value: int) -> None:
        self._width_label.setText(str(value))
        self.scene.set_stroke_width(value)

    # ── Draw action handler ──────────────────────────────────────────

    def _on_shape_completed(self, tool: str, payload: dict) -> None:
        # Clear redo stack when drawing a new shape
        self._my_undone_seqs.clear()
        self._undo_to_redo_map.clear()
        self.draw_created.emit(tool, payload)

    def _on_undo_clicked(self) -> None:
        if not self._my_drawn_seqs:
            QMessageBox.information(self, "Undo", "No drawing history to undo in this room session.")
            return
        target_seq = self._my_drawn_seqs.pop()
        self._my_undone_seqs.append(target_seq)
        self.draw_created.emit("undo", {"target_seq": target_seq})

    def _on_redo_clicked(self) -> None:
        if not self._my_undone_seqs:
            QMessageBox.information(self, "Redo", "No undone drawing history to redo.")
            return
        target_seq = self._my_undone_seqs.pop()
        undo_seq = self._undo_to_redo_map.get(target_seq)
        if undo_seq is not None:
            # Undoing the undo event (undo_seq) acts as Redo
            self.draw_created.emit("undo", {"target_seq": undo_seq})
            self._my_drawn_seqs.append(target_seq)

    # ── Public drawing application ────────────────────────────────────

    def clear_all(self) -> None:
        """Wipe the scene and clear all sequence cache."""
        self.scene.clear()
        self._scene_items.clear()
        self._my_drawn_seqs.clear()
        self._my_undone_seqs.clear()
        self._undo_to_redo_map.clear()

    def record_own_draw(self, seq_num: int) -> None:
        """Record a successful seq_num drawn by the local user so they can undo it."""
        self._my_drawn_seqs.append(seq_num)

    def record_own_undo(self, target_seq: int, undo_seq: int) -> None:
        """Record that a local draw event target_seq was undone by undo_seq."""
        self._undo_to_redo_map[target_seq] = undo_seq

    def apply_snapshot(self, snapshot_b64: str) -> None:
        """Decode and set a background snapshot image on the canvas."""
        import base64
        try:
            png_bytes = base64.b64decode(snapshot_b64)
            img = QImage.fromData(png_bytes)
            if not img.isNull():
                pixmap = QPixmap.fromImage(img)
                bg_item = self.scene.addPixmap(pixmap)
                bg_item.setZValue(-1000)
                # Cache as special key -1
                self._scene_items[-1] = bg_item
        except Exception:
            logger.exception("Failed to apply snapshot to whiteboard scene")

    def apply_event(
        self, seq_num: int, user_id: int, username: str, event_type: str, payload: dict
    ) -> None:
        """Apply a validated server DRAW_BROADCAST to the canvas view."""
        # Clean up any existing item for this seq_num to be idempotent
        self.remove_item(seq_num)

        color_str = payload.get("color", "#ffffff")
        width = payload.get("width", 2)

        if event_type == "eraser":
            pen_color = QColor(BACKGROUND_COLOR)
        else:
            pen_color = QColor(color_str)

        pen = QPen(
            pen_color,
            width if event_type != "eraser" else width * 3,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )

        item = None

        if event_type in ("pen", "eraser"):
            points = payload.get("points", [])
            if len(points) >= 2:
                path = QPainterPath()
                path.moveTo(points[0][0], points[0][1])
                for pt in points[1:]:
                    path.lineTo(pt[0], pt[1])
                item = QGraphicsPathItem()
                item.setPath(path)
                item.setPen(pen)
                self.scene.addItem(item)
            elif len(points) == 1:
                # Single dot
                path = QPainterPath()
                path.moveTo(points[0][0], points[0][1])
                path.lineTo(points[0][0] + 0.1, points[0][1] + 0.1)
                item = QGraphicsPathItem()
                item.setPath(path)
                item.setPen(pen)
                self.scene.addItem(item)

        elif event_type == "rect":
            r = payload.get("rect", [0, 0, 0, 0])
            if len(r) == 4:
                item = QGraphicsRectItem(r[0], r[1], r[2], r[3])
                item.setPen(pen)
                item.setBrush(Qt.BrushStyle.NoBrush)
                self.scene.addItem(item)

        elif event_type == "oval":
            r = payload.get("rect", [0, 0, 0, 0])
            if len(r) == 4:
                item = QGraphicsEllipseItem(r[0], r[1], r[2], r[3])
                item.setPen(pen)
                item.setBrush(Qt.BrushStyle.NoBrush)
                self.scene.addItem(item)

        elif event_type == "text":
            text = payload.get("text", "")
            pos = payload.get("text_pos", [0, 0])
            if text and len(pos) == 2:
                item = QGraphicsTextItem(text)
                item.setDefaultTextColor(pen_color)
                # Matches render_png font properties
                item.setFont(QFont("Arial", 16))
                item.setPos(pos[0], pos[1])
                self.scene.addItem(item)

        elif event_type == "undo":
            target = payload.get("target_seq")
            if isinstance(target, int):
                self.remove_item(target)

        # Cache item for future reference or undos
        if item is not None:
            self._scene_items[seq_num] = item

    def remove_item(self, seq_num: int) -> None:
        """Remove a cached shape item from the canvas."""
        item = self._scene_items.pop(seq_num, None)
        if item is not None:
            try:
                self.scene.removeItem(item)
            except Exception:
                pass

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Scale QGraphicsView contents to fit the viewport aspect ratio."""
        super().resizeEvent(event)
        self.view.fitInView(self.scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
