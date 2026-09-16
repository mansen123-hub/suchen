from __future__ import annotations

import json
import logging
from pathlib import Path

import fitz
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .database import IndexDatabase
from .ocr import normalize_search_text

LOGGER = logging.getLogger(__name__)


class PdfPreview(QWidget):
    page_changed = Signal(int)

    def __init__(self, database: IndexDatabase, parent: QWidget | None = None):
        super().__init__(parent)
        self.database = database
        self.path: Path | None = None
        self.query = ""
        self.page_number = 1
        self.page_count = 0
        self.zoom = 1.35

        self.image = QLabel("Wähle einen Treffer aus, um die PDF anzuzeigen.")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setObjectName("previewImage")
        self.image.setMinimumSize(500, 500)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.image)
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.previous = QPushButton("‹")
        self.next = QPushButton("›")
        self.page_label = QLabel("– / –")
        self.zoom_out = QPushButton("−")
        self.zoom_in = QPushButton("+")
        self.previous.clicked.connect(lambda: self.show_page(self.page_number - 1))
        self.next.clicked.connect(lambda: self.show_page(self.page_number + 1))
        self.zoom_out.clicked.connect(lambda: self._change_zoom(-0.2))
        self.zoom_in.clicked.connect(lambda: self._change_zoom(0.2))

        toolbar = QHBoxLayout()
        toolbar.addWidget(self.previous)
        toolbar.addWidget(self.next)
        toolbar.addWidget(self.page_label)
        toolbar.addStretch()
        toolbar.addWidget(QLabel("Zoom"))
        toolbar.addWidget(self.zoom_out)
        toolbar.addWidget(self.zoom_in)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(toolbar)
        layout.addWidget(self.scroll, 1)

    def load(self, path: str, page_number: int, query: str) -> None:
        self.path = Path(path)
        self.query = query
        try:
            with fitz.open(self.path) as document:
                self.page_count = document.page_count
            self.show_page(page_number)
        except Exception as exc:
            LOGGER.exception("Vorschaufehler")
            self.image.setText(f"Vorschau konnte nicht geladen werden.\n{exc}")

    def show_page(self, page_number: int) -> None:
        if not self.path or not self.page_count:
            return
        self.page_number = max(1, min(page_number, self.page_count))
        try:
            with fitz.open(self.path) as document:
                page = document[self.page_number - 1]
                matrix = fitz.Matrix(self.zoom, self.zoom)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=fitz.csRGB)
                image = QImage(pixmap.samples, pixmap.width, pixmap.height, pixmap.stride, QImage.Format.Format_RGB888).copy()
                self._draw_highlights(image, page, matrix)
                self.image.setPixmap(QPixmap.fromImage(image))
                self.image.resize(image.size())
        except Exception as exc:
            self.image.setText(f"Seite konnte nicht angezeigt werden.\n{exc}")
        self.page_label.setText(f"{self.page_number} / {self.page_count}")
        self.previous.setEnabled(self.page_number > 1)
        self.next.setEnabled(self.page_number < self.page_count)
        self.page_changed.emit(self.page_number)

    def _draw_highlights(self, image: QImage, page: fitz.Page, matrix: fitz.Matrix) -> None:
        rects = list(page.search_for(self.query)) if self.query else []
        if not rects and self.query:
            compact = normalize_search_text(self.query)
            for word in page.get_text("words", sort=True):
                if compact and compact in normalize_search_text(str(word[4])):
                    rects.append(fitz.Rect(word[:4]))
        if not rects:
            raw = self.database.ocr_words(str(self.path), self.page_number)
            rects = _ocr_match_rects(raw, self.query)
        painter = QPainter(image)
        painter.setBrush(QColor(255, 215, 0, 105))
        painter.setPen(QPen(QColor(255, 167, 38), 2))
        for rect in rects:
            painter.drawRect(QRectF(QPointF(rect.x0 * matrix.a, rect.y0 * matrix.d), QPointF(rect.x1 * matrix.a, rect.y1 * matrix.d)))
        painter.end()

    def _change_zoom(self, change: float) -> None:
        self.zoom = max(0.6, min(3.0, self.zoom + change))
        self.show_page(self.page_number)


def _ocr_match_rects(raw: str | None, query: str) -> list[fitz.Rect]:
    if not raw or not query:
        return []
    try:
        words = json.loads(raw)
    except (ValueError, TypeError):
        return []
    needle = normalize_search_text(query)
    if not needle:
        return []
    output: list[fitz.Rect] = []
    for start in range(len(words)):
        combined = ""
        for end in range(start, min(start + 8, len(words))):
            combined += normalize_search_text(words[end].get("text", ""))
            if needle in combined:
                selected = words[start : end + 1]
                x0 = min(word["x"] for word in selected)
                y0 = min(word["y"] for word in selected)
                x1 = max(word["x"] + word["width"] for word in selected)
                y1 = max(word["y"] + word["height"] for word in selected)
                output.append(fitz.Rect(x0, y0, x1, y1))
                break
            if len(combined) > len(needle) * 2:
                break
    return output

