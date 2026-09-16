from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import fitz

from .database import IndexDatabase
from .ocr import normalize_search_text, ocr_page, text_is_usable

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IndexProgress:
    current: int
    total: int
    filename: str
    message: str


@dataclass(frozen=True, slots=True)
class IndexResult:
    discovered: int
    processed: int
    skipped: int
    removed: int
    errors: int
    cancelled: bool


class PdfIndexer:
    def __init__(self, database: IndexDatabase, ocr_languages: str = "deu+eng"):
        self.database = database
        self.ocr_languages = ocr_languages

    def discover(self, root: Path, recursive: bool) -> list[Path]:
        if not root.is_dir():
            raise NotADirectoryError(f"Ordner nicht erreichbar: {root}")
        iterator: Iterable[Path] = root.rglob("*") if recursive else root.iterdir()
        files: list[Path] = []
        for path in iterator:
            try:
                if path.is_file() and path.suffix.casefold() == ".pdf":
                    files.append(path)
            except OSError as exc:
                LOGGER.warning("Pfad konnte nicht geprüft werden: %s: %s", path, exc)
        return sorted(files, key=lambda item: str(item).casefold())

    def run(
        self,
        root: Path,
        recursive: bool,
        rebuild: bool = False,
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> IndexResult:
        cancel = cancel or threading.Event()
        if rebuild:
            self.database.clear()
        files = self.discover(root, recursive)
        existing = {str(path) for path in files}
        known = self.database.known_signatures()
        changed: list[tuple[Path, int, int]] = []
        skipped = 0
        for path in files:
            try:
                stat = path.stat()
            except OSError as exc:
                LOGGER.error("Metadatenfehler %s: %s", path, exc)
                continue
            signature = (stat.st_size, stat.st_mtime_ns)
            if known.get(str(path)) == signature:
                skipped += 1
            else:
                changed.append((path, *signature))

        processed = errors = 0
        for number, (path, size, modified_ns) in enumerate(changed, start=1):
            if cancel.is_set():
                return IndexResult(len(files), processed, skipped, 0, errors, True)
            if progress:
                progress(IndexProgress(number - 1, len(changed), path.name, "PDF wird verarbeitet"))
            try:
                pages = self._extract(path, progress, number, len(changed), cancel)
                if cancel.is_set():
                    return IndexResult(len(files), processed, skipped, 0, errors, True)
                self.database.replace_document(path, size, modified_ns, pages)
                processed += 1
            except Exception as exc:  # Indexing must continue with the next document.
                errors += 1
                LOGGER.exception("Indexierungsfehler bei %s", path)
                self.database.record_error(path, size, modified_ns, str(exc))
        removed = self.database.remove_missing(existing, root)
        if progress:
            progress(IndexProgress(len(changed), len(changed), "", "Indexierung abgeschlossen"))
        return IndexResult(len(files), processed, skipped, removed, errors, False)

    def index_file(self, path: Path) -> bool:
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            return False
        stat = path.stat()
        if self.database.known_signatures().get(str(path)) == (stat.st_size, stat.st_mtime_ns):
            return False
        pages = self._extract(path, None, 1, 1, threading.Event())
        self.database.replace_document(path, stat.st_size, stat.st_mtime_ns, pages)
        return True

    def _extract(
        self,
        path: Path,
        progress: Callable[[IndexProgress], None] | None,
        document_number: int,
        document_total: int,
        cancel: threading.Event,
    ) -> list[tuple[int, str, str, bool, str | None]]:
        output: list[tuple[int, str, str, bool, str | None]] = []
        with fitz.open(path) as document:
            if document.needs_pass:
                raise PermissionError("Die PDF ist passwortgeschützt.")
            for page_index, page in enumerate(document):
                if cancel.is_set():
                    break
                text = page.get_text("text", sort=True)
                used_ocr = False
                words_json = None
                if not text_is_usable(text):
                    if progress:
                        progress(IndexProgress(document_number - 1, document_total, path.name, f"OCR Seite {page_index + 1}/{document.page_count}"))
                    text, words_json = ocr_page(page, self.ocr_languages)
                    used_ocr = True
                output.append((page_index + 1, text, normalize_search_text(text), used_ocr, words_json))
        return output

