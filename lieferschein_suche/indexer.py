from __future__ import annotations

import logging
import multiprocessing
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import fitz

from .database import IndexDatabase
from .ocr import normalize_search_text, ocr_page, text_is_usable

LOGGER = logging.getLogger(__name__)
PageRow = tuple[int, str, str, bool, str | None]
ExtractionResult = tuple[str, int, int, list[PageRow], str | None]


@dataclass(frozen=True, slots=True)
class FileCandidate:
    path: Path
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class IndexProgress:
    current: int
    total: int
    filename: str
    message: str
    files_per_second: float = 0.0


@dataclass(frozen=True, slots=True)
class IndexResult:
    discovered: int
    processed: int
    skipped: int
    removed: int
    errors: int
    cancelled: bool


def _extract_pdf_job(job: tuple[str, int, int, str]) -> ExtractionResult:
    """Process-safe extraction function used by the Windows worker pool."""
    path_text, size, modified_ns, languages = job
    path = Path(path_text)
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    output: list[PageRow] = []
    try:
        with fitz.open(path) as document:
            if document.needs_pass:
                raise PermissionError("Die PDF ist passwortgeschützt.")
            for page_index, page in enumerate(document):
                text = page.get_text("text", sort=True)
                used_ocr = False
                words_json = None
                if not text_is_usable(text):
                    text, words_json = ocr_page(page, languages)
                    used_ocr = True
                output.append((page_index + 1, text, normalize_search_text(text), used_ocr, words_json))
        return path_text, size, modified_ns, output, None
    except Exception as exc:
        return path_text, size, modified_ns, [], f"{type(exc).__name__}: {exc}"


class PdfIndexer:
    def __init__(self, database: IndexDatabase, ocr_languages: str = "deu+eng", workers: int | None = None):
        self.database = database
        self.ocr_languages = ocr_languages
        cpu_count = os.cpu_count() or 4
        self.workers = workers or max(2, min(8, cpu_count - 1))

    def discover(self, root: Path, recursive: bool) -> list[FileCandidate]:
        """Enumerate PDFs with one scandir/stat pass, optimized for very large folders."""
        if not root.is_dir():
            raise NotADirectoryError(f"Ordner nicht erreichbar: {root}")
        output: list[FileCandidate] = []
        directories = [root]
        while directories:
            directory = directories.pop()
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if recursive:
                                    directories.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False) or not entry.name.casefold().endswith(".pdf"):
                                continue
                            stat = entry.stat(follow_symlinks=False)
                            output.append(FileCandidate(Path(entry.path), stat.st_size, stat.st_mtime_ns))
                        except OSError as exc:
                            LOGGER.warning("Pfad konnte nicht geprüft werden: %s: %s", entry.path, exc)
            except OSError as exc:
                LOGGER.warning("Ordner konnte nicht gelesen werden: %s: %s", directory, exc)
        return output

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
        if progress:
            progress(IndexProgress(0, 0, "", "PDF-Bestand wird schnell erfasst"))
        files = self.discover(root, recursive)
        existing = {str(item.path) for item in files}
        known = self.database.known_signatures()
        changed = [item for item in files if known.get(str(item.path)) != (item.size, item.modified_ns)]
        skipped = len(files) - len(changed)
        processed, errors, cancelled = self._process(changed, progress, cancel)
        removed = 0 if cancelled else self.database.remove_missing(existing, root)
        if progress:
            progress(IndexProgress(len(changed), len(changed), "", "Indexierung abgeschlossen"))
        return IndexResult(len(files), processed, skipped, removed, errors, cancelled)

    def run_paths(
        self,
        paths: Iterable[str | Path],
        progress: Callable[[IndexProgress], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> IndexResult:
        """Update only watcher paths; never rescan the complete PDF tree."""
        cancel = cancel or threading.Event()
        candidates: list[FileCandidate] = []
        deleted: list[Path] = []
        for raw_path in dict.fromkeys(str(path) for path in paths):
            path = Path(raw_path)
            if path.suffix.casefold() != ".pdf":
                continue
            try:
                stat = path.stat()
                if path.is_file():
                    candidates.append(FileCandidate(path, stat.st_size, stat.st_mtime_ns))
            except OSError:
                deleted.append(path)
        removed = self.database.remove_paths(deleted)
        known = self.database.known_signatures()
        changed = [item for item in candidates if known.get(str(item.path)) != (item.size, item.modified_ns)]
        processed, errors, cancelled = self._process(changed, progress, cancel)
        return IndexResult(len(candidates), processed, len(candidates) - len(changed), removed, errors, cancelled)

    def index_file(self, path: Path) -> bool:
        if not path.is_file() or path.suffix.casefold() != ".pdf":
            return False
        stat = path.stat()
        if self.database.known_signatures().get(str(path)) == (stat.st_size, stat.st_mtime_ns):
            return False
        result = _extract_pdf_job((str(path), stat.st_size, stat.st_mtime_ns, self.ocr_languages))
        self._write_batch([result])
        return result[4] is None

    def _process(
        self,
        candidates: list[FileCandidate],
        progress: Callable[[IndexProgress], None] | None,
        cancel: threading.Event,
    ) -> tuple[int, int, bool]:
        total = len(candidates)
        if not total:
            return 0, 0, False
        started = time.monotonic()
        processed = errors = completed = 0
        batch: list[ExtractionResult] = []
        last_flush = started

        def accept(result: ExtractionResult) -> None:
            nonlocal processed, errors, completed, last_flush
            batch.append(result)
            completed += 1
            if result[4] is None:
                processed += 1
            else:
                errors += 1
                LOGGER.error("Indexierungsfehler bei %s: %s", result[0], result[4])
            now = time.monotonic()
            if len(batch) >= 25 or now - last_flush >= 2:
                self._write_batch(batch)
                batch.clear()
                last_flush = now
            if progress:
                rate = completed / max(now - started, 0.001)
                progress(IndexProgress(completed, total, Path(result[0]).name, f"Parallele Verarbeitung mit {min(self.workers, total)} Prozessen", rate))

        if total == 1:
            item = candidates[0]
            accept(_extract_pdf_job((str(item.path), item.size, item.modified_ns, self.ocr_languages)))
        else:
            context = multiprocessing.get_context("spawn")
            executor = ProcessPoolExecutor(max_workers=min(self.workers, total), mp_context=context)
            iterator = iter(candidates)
            pending: dict[Future[ExtractionResult], FileCandidate] = {}

            def submit_next() -> bool:
                try:
                    item = next(iterator)
                except StopIteration:
                    return False
                future = executor.submit(_extract_pdf_job, (str(item.path), item.size, item.modified_ns, self.ocr_languages))
                pending[future] = item
                return True

            for _ in range(min(total, self.workers * 2)):
                submit_next()
            try:
                while pending and not cancel.is_set():
                    done, _ = wait(pending, return_when=FIRST_COMPLETED)
                    for future in done:
                        item = pending.pop(future)
                        try:
                            accept(future.result())
                        except Exception as exc:
                            accept((str(item.path), item.size, item.modified_ns, [], f"Workerfehler: {exc}"))
                        if not cancel.is_set():
                            submit_next()
            finally:
                if cancel.is_set():
                    for future in pending:
                        future.cancel()
                executor.shutdown(wait=True, cancel_futures=True)

        if batch:
            self._write_batch(batch)
        return processed, errors, cancel.is_set()

    def _write_batch(self, batch: list[ExtractionResult]) -> None:
        rows = [(Path(path), size, modified_ns, pages, error) for path, size, modified_ns, pages, error in batch]
        self.database.write_results_batch(rows)
