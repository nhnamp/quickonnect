"""Subtitle overlay widget.

Shows speaker name and transcript text. Auto-hides after a configurable
timeout. Designed to be placed at the bottom of the screen-share view.
"""

import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel

logger = logging.getLogger(__name__)


class SubtitleWidget(QWidget):
    """Semi-transparent overlay that displays live speech-to-text subtitles.

    The widget is initially hidden.  Call :meth:`show_subtitle` to display
    a new subtitle line; after *duration_ms* milliseconds the widget hides
    itself automatically.  Call :meth:`clear` to hide immediately.

    Typical usage::

        subtitle = SubtitleWidget(parent=screen_share_view)
        # ... when a SUBTITLE packet arrives:
        subtitle.show_subtitle(speaker="Alice", text="Hello everyone")
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # ── Hide timer ────────────────────────────────────────────────
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

        # ── Build UI ─────────────────────────────────────────────────
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            "SubtitleWidget {"
            "  background-color: rgba(0, 0, 0, 180);"
            "  border-radius: 8px;"
            "  padding: 8px;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(2)

        # Main subtitle text
        self._text_label = QLabel()
        self._text_label.setWordWrap(True)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setStyleSheet(
            "color: white;"
            "font-size: 14px;"
            "background: transparent;"
        )
        layout.addWidget(self._text_label)

        # Speaker name
        self._speaker_label = QLabel()
        self._speaker_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._speaker_label.setStyleSheet(
            "color: #aaaaaa;"
            "font-size: 11px;"
            "background: transparent;"
        )
        layout.addWidget(self._speaker_label)

        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_subtitle(
        self,
        speaker: str,
        text: str,
        translated: str = "",
        duration_ms: int = 5000,
    ) -> None:
        """Display a subtitle line and auto-hide after *duration_ms*.

        Parameters
        ----------
        speaker:
            Name of the person speaking.
        text:
            Original transcript text.
        translated:
            Optional translated text shown below the original.
        duration_ms:
            How long the subtitle remains visible (default 5 s).
        """
        if translated:
            display_text = f"{text}\n{translated}"
        else:
            display_text = text

        self._text_label.setText(display_text)
        self._speaker_label.setText(f"\U0001f3a4 {speaker}")

        self.show()
        self.raise_()

        self._hide_timer.stop()
        self._hide_timer.start(duration_ms)

        logger.debug("Subtitle shown: [%s] %s", speaker, text)

    def clear(self) -> None:
        """Immediately hide the subtitle and cancel the auto-hide timer."""
        self._hide_timer.stop()
        self.hide()
