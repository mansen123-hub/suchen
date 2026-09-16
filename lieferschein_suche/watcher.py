from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

LOGGER = logging.getLogger(__name__)


class _PdfEventHandler(FileSystemEventHandler):
    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def on_any_event(self, event: FileSystemEvent) -> None:
        paths = [getattr(event, "src_path", ""), getattr(event, "dest_path", "")]
        if event.is_directory or not any(str(path).casefold().endswith(".pdf") for path in paths):
            return
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(2.0, self.callback)
            self._timer.daemon = True
            self._timer.start()


class FolderWatcher:
    def __init__(self, callback: Callable[[], None]):
        self.callback = callback
        self.observer: Observer | None = None

    def start(self, path: Path, recursive: bool) -> None:
        self.stop()
        # ReadDirectoryChangesW is fast locally; polling is more reliable on many SMB shares.
        observer = PollingObserver(timeout=4) if str(path).startswith("\\\\") else Observer(timeout=2)
        observer.schedule(_PdfEventHandler(self.callback), str(path), recursive=recursive)
        observer.start()
        self.observer = observer
        LOGGER.info("Ordnerüberwachung gestartet: %s", path)

    def stop(self) -> None:
        if self.observer:
            self.observer.stop()
            self.observer.join(timeout=5)
            self.observer = None
