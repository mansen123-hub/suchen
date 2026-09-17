from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

LOGGER = logging.getLogger(__name__)


class _PdfEventHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[list[str]], None]):
        self.callback = callback
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._pending: set[str] = set()

    def on_any_event(self, event: FileSystemEvent) -> None:
        paths = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
        if event.is_directory or not any(str(path).casefold().endswith(".pdf") for path in paths):
            return
        with self._lock:
            self._pending.update(str(path) for path in paths if str(path).casefold().endswith(".pdf"))
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(1.5, self._flush)
            self._timer.daemon = True
            self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            paths = sorted(self._pending)
            self._pending.clear()
            self._timer = None
        if paths:
            self.callback(paths)

    def cancel(self) -> None:
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = None
            self._pending.clear()


class FolderWatcher:
    def __init__(self, callback: Callable[[list[str]], None]):
        self.callback = callback
        self.observer: Observer | None = None
        self.handler: _PdfEventHandler | None = None

    def start(self, path: Path, recursive: bool) -> None:
        self.stop()
        # Native filesystem events avoid repeatedly walking 100,000+ files.
        observer = Observer(timeout=2)
        self.handler = _PdfEventHandler(self.callback)
        observer.schedule(self.handler, str(path), recursive=recursive)
        observer.start()
        self.observer = observer
        LOGGER.info("Ordnerüberwachung gestartet: %s", path)

    def stop(self) -> None:
        if self.handler:
            self.handler.cancel()
            self.handler = None
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)
            self.observer = None
