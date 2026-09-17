from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .database import IndexDatabase, SearchHit
from .indexer import IndexProgress, IndexResult, PdfIndexer
from .ocr import normalize_search_text
from .paths import app_data_dir, log_path
from .preview import PdfPreview
from .settings import AppSettings
from .watcher import FolderWatcher

LOGGER = logging.getLogger(__name__)


class IndexWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, indexer: PdfIndexer, root: Path, recursive: bool, rebuild: bool, paths: list[str] | None = None):
        super().__init__()
        self.indexer = indexer
        self.root = root
        self.recursive = recursive
        self.rebuild = rebuild
        self.paths = paths
        self.cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            if self.paths is None:
                result = self.indexer.run(self.root, self.recursive, self.rebuild, self.progress.emit, self.cancel_event)
            else:
                result = self.indexer.run_paths(self.paths, self.progress.emit, self.cancel_event)
            self.finished.emit(result)
        except Exception as exc:
            LOGGER.exception("Indexierung konnte nicht gestartet werden")
            self.failed.emit(str(exc))

    @Slot()
    def cancel(self) -> None:
        self.cancel_event.set()


class MainWindow(QMainWindow):
    watcher_change = Signal(object)

    def __init__(self, database: IndexDatabase, settings: AppSettings):
        super().__init__()
        self.database = database
        self.settings = settings
        self.indexer = PdfIndexer(database, settings.ocr_languages)
        self.watcher = FolderWatcher(self._watcher_triggered)
        self.index_thread: QThread | None = None
        self.index_worker: IndexWorker | None = None
        self.current_hits: list[SearchHit] = []
        self._pending_watch_paths: set[str] = set()
        self._closing = False
        self.watcher_change.connect(self._handle_watch_paths)

        self.setWindowTitle(f"Lieferschein-Suche {__version__}")
        self.resize(settings.window_width, settings.window_height)
        self.setMinimumSize(1050, 680)
        self._build_ui()
        self._build_menu()
        self._refresh_stats()
        self._apply_settings()

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(14, 14, 14, 8)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(290)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(18, 22, 18, 20)
        title = QLabel("Lieferschein-Suche")
        title.setObjectName("appTitle")
        subtitle = QLabel("PDFs lokal finden – mit OCR")
        subtitle.setObjectName("appSubtitle")
        side.addWidget(title)
        side.addWidget(subtitle)
        side.addSpacing(22)
        side.addWidget(QLabel("PDF-Ordner"))

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(r"C:\Scans oder \\Server\Freigabe")
        self.folder_edit.setClearButtonEnabled(True)
        browse = QPushButton("Ordner auswählen")
        browse.clicked.connect(self._select_folder)
        self.subfolders = QCheckBox("Unterordner durchsuchen")
        self.watch = QCheckBox("Ordner automatisch überwachen")
        self.watch.toggled.connect(self._configure_watcher)
        self.subfolders.toggled.connect(self._configure_watcher)
        self.start_button = QPushButton("Jetzt indexieren")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(lambda: self._start_index(False))
        self.cancel_button = QPushButton("Abbrechen")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_index)
        side.addWidget(self.folder_edit)
        side.addWidget(browse)
        side.addWidget(self.subfolders)
        side.addWidget(self.watch)
        side.addSpacing(8)
        side.addWidget(self.start_button)
        side.addWidget(self.cancel_button)
        side.addSpacing(20)
        self.progress_label = QLabel("Bereit")
        self.progress_label.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        side.addWidget(self.progress_label)
        side.addWidget(self.progress)
        side.addStretch()
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        side.addWidget(self.stats_label)
        privacy = QLabel("Lokale Verarbeitung – keine Cloud")
        privacy.setObjectName("appSubtitle")
        side.addWidget(privacy)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(14, 2, 0, 0)
        heading = QLabel("Lieferscheinnummer suchen")
        heading.setObjectName("sectionTitle")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("z. B. LS-2026-001284")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._search)
        self.search_edit.textChanged.connect(self._search_delayed)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self._search)
        search_button = QPushButton("Suchen")
        search_button.setObjectName("primary")
        search_button.clicked.connect(self._search)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search_edit, 1)
        search_row.addWidget(search_button)
        main.addWidget(heading)
        main.addLayout(search_row)

        self.results = QTreeWidget()
        self.results.setColumnCount(4)
        self.results.setHeaderLabels(["Datei", "Seite", "Trefferumgebung", "Quelle"])
        self.results.setColumnWidth(0, 250)
        self.results.setColumnWidth(1, 65)
        self.results.setColumnWidth(2, 460)
        self.results.setAlternatingRowColors(True)
        self.results.itemSelectionChanged.connect(self._show_selected)
        self.results.itemDoubleClicked.connect(lambda *_: self._open_pdf())

        self.preview = PdfPreview(self.database)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.results)
        splitter.addWidget(self.preview)
        splitter.setSizes([310, 480])
        main.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.open_button = QPushButton("PDF öffnen")
        self.location_button = QPushButton("Im Explorer anzeigen")
        self.open_button.clicked.connect(self._open_pdf)
        self.location_button.clicked.connect(self._open_location)
        self.open_button.setEnabled(False)
        self.location_button.setEnabled(False)
        actions.addWidget(self.open_button)
        actions.addWidget(self.location_button)
        actions.addStretch()
        main.addLayout(actions)

        outer.addWidget(sidebar)
        outer.addWidget(content, 1)
        self.setCentralWidget(root)
        self.statusBar().showMessage("Bereit")

    def _build_menu(self) -> None:
        menu = self.menuBar().addMenu("Datei")
        choose = QAction("PDF-Ordner auswählen", self)
        choose.triggered.connect(self._select_folder)
        logs = QAction("Fehlerprotokoll öffnen", self)
        logs.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(log_path()))))
        data = QAction("Anwendungsdaten öffnen", self)
        data.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(app_data_dir()))))
        menu.addActions([choose, logs, data])
        index_menu = self.menuBar().addMenu("Index")
        rebuild = QAction("Index komplett neu aufbauen", self)
        rebuild.triggered.connect(self._confirm_rebuild)
        index_menu.addAction(rebuild)
        help_menu = self.menuBar().addMenu("Hilfe")
        about = QAction("Über Lieferschein-Suche", self)
        about.triggered.connect(lambda: QMessageBox.about(self, "Über", f"Lieferschein-Suche {__version__}\n\nLokale PDF-Suche mit automatischer OCR.\nEs werden keine Dokumente übertragen."))
        help_menu.addAction(about)

    def _apply_settings(self) -> None:
        self.folder_edit.setText(self.settings.pdf_folder)
        self.subfolders.setChecked(self.settings.include_subfolders)
        self.watch.setChecked(self.settings.watch_folder)
        QTimer.singleShot(0, self._configure_watcher)

    def _select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "PDF-Ordner auswählen", self.folder_edit.text())
        if folder:
            self.folder_edit.setText(folder)
            self._save_settings()
            self._configure_watcher()

    def _start_index(self, rebuild: bool, paths: list[str] | None = None) -> None:
        if self.index_thread:
            return
        folder = Path(self.folder_edit.text().strip())
        if not folder.is_dir():
            QMessageBox.warning(self, "Ordner nicht erreichbar", "Der gewählte PDF-Ordner ist nicht erreichbar. Prüfe auch die Netzwerkverbindung und Berechtigungen.")
            return
        self._save_settings()
        thread = QThread(self)
        worker = IndexWorker(self.indexer, folder, self.subfolders.isChecked(), rebuild, paths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_index_finished)
        worker.failed.connect(self._on_index_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        self.index_thread = thread
        self.index_worker = worker
        self.start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.progress.setRange(0, 0)
        self.progress_label.setText("PDF-Dateien werden gesucht …" if paths is None else f"{len(paths)} geänderte Dateien werden aktualisiert …")
        self.watcher.stop()
        thread.start()

    @Slot(object)
    def _on_progress(self, state: IndexProgress) -> None:
        if state.total <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, state.total)
        self.progress.setValue(state.current)
        details = state.filename
        if state.files_per_second > 0 and state.total > state.current:
            remaining = int((state.total - state.current) / state.files_per_second)
            hours, remainder = divmod(remaining, 3600)
            minutes, seconds = divmod(remainder, 60)
            eta = f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:d}:{seconds:02d}"
            details = f"{state.current:,}/{state.total:,} · {state.files_per_second:.1f} PDFs/s · Rest ca. {eta}"
        self.progress_label.setText(f"{state.message}\n{details}".strip())

    @Slot(object)
    def _on_index_finished(self, result: IndexResult) -> None:
        if result.cancelled:
            message = "Indexierung abgebrochen."
        else:
            message = f"Fertig: {result.processed} verarbeitet, {result.skipped} unverändert, {result.removed} entfernt"
            if result.errors:
                message += f", {result.errors} Fehler"
        self.progress_label.setText(message)
        self.statusBar().showMessage(message, 12000)
        self._refresh_stats()
        self._search()

    @Slot(str)
    def _on_index_failed(self, message: str) -> None:
        self.progress_label.setText("Indexierung fehlgeschlagen")
        QMessageBox.critical(self, "Indexierung fehlgeschlagen", f"{message}\n\nDetails stehen im Fehlerprotokoll.")

    @Slot()
    def _thread_finished(self) -> None:
        thread = self.index_thread
        self.index_thread = None
        self.index_worker = None
        self.start_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if thread:
            thread.deleteLater()
        self._configure_watcher()
        if self._pending_watch_paths and not self._closing:
            pending = sorted(self._pending_watch_paths)
            self._pending_watch_paths.clear()
            QTimer.singleShot(0, lambda: self._start_index(False, pending))
        if self._closing:
            QTimer.singleShot(0, self.close)

    def _cancel_index(self) -> None:
        if self.index_worker:
            self.index_worker.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_label.setText("Abbruch wird vorbereitet …")

    def _search_delayed(self) -> None:
        self.search_timer.start()

    def _search(self) -> None:
        query = self.search_edit.text().strip()
        self.results.clear()
        self.current_hits = self.database.search(query, normalize_search_text(query)) if query else []
        for index, hit in enumerate(self.current_hits):
            source = "OCR" if hit.ocr_used else "PDF-Text"
            item = QTreeWidgetItem([hit.filename, str(hit.page_number), hit.snippet, source])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(0, hit.path)
            self.results.addTopLevelItem(item)
        self.statusBar().showMessage(f"{len(self.current_hits)} Treffer" if query else "Suchbegriff eingeben")
        if self.current_hits:
            self.results.setCurrentItem(self.results.topLevelItem(0))
        else:
            self.open_button.setEnabled(False)
            self.location_button.setEnabled(False)

    def _selected_hit(self) -> SearchHit | None:
        items = self.results.selectedItems()
        if not items:
            return None
        index = items[0].data(0, Qt.ItemDataRole.UserRole)
        return self.current_hits[index] if isinstance(index, int) and index < len(self.current_hits) else None

    def _show_selected(self) -> None:
        hit = self._selected_hit()
        enabled = hit is not None and Path(hit.path).is_file()
        self.open_button.setEnabled(enabled)
        self.location_button.setEnabled(enabled)
        if hit:
            self.preview.load(hit.path, hit.page_number, self.search_edit.text().strip())

    def _open_pdf(self) -> None:
        hit = self._selected_hit()
        if hit:
            QDesktopServices.openUrl(QUrl.fromLocalFile(hit.path))

    def _open_location(self) -> None:
        hit = self._selected_hit()
        if not hit:
            return
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(hit.path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(hit.path).parent)))

    def _confirm_rebuild(self) -> None:
        answer = QMessageBox.question(self, "Index neu aufbauen", "Der lokale Suchindex wird gelöscht und alle PDFs werden erneut verarbeitet. Fortfahren?")
        if answer == QMessageBox.StandardButton.Yes:
            self._start_index(True)

    def _watcher_triggered(self, paths: list[str]) -> None:
        self.watcher_change.emit(paths)

    @Slot(object)
    def _handle_watch_paths(self, paths: list[str]) -> None:
        if self.index_thread:
            self._pending_watch_paths.update(paths)
        else:
            self._start_index(False, paths)

    def _configure_watcher(self) -> None:
        self.watcher.stop()
        folder = Path(self.folder_edit.text().strip())
        if self.watch.isChecked() and folder.is_dir() and not self.index_thread:
            try:
                self.watcher.start(folder, self.subfolders.isChecked())
            except Exception as exc:
                LOGGER.warning("Ordnerüberwachung nicht verfügbar: %s", exc)
                self.statusBar().showMessage("Ordnerüberwachung konnte nicht gestartet werden", 8000)

    def _refresh_stats(self) -> None:
        documents, pages, errors = self.database.stats()
        self.stats_label.setText(f"Index\n{documents} PDFs · {pages} Seiten" + (f"\n{errors} Fehler" if errors else ""))

    def _save_settings(self) -> None:
        self.settings.pdf_folder = self.folder_edit.text().strip()
        self.settings.include_subfolders = self.subfolders.isChecked()
        self.settings.watch_folder = self.watch.isChecked()
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()
        self.settings.save()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_settings()
        self.watcher.stop()
        if self.index_worker:
            self._closing = True
            self.index_worker.cancel()
            self.statusBar().showMessage("Die laufende Verarbeitung wird beendet …")
            event.ignore()
            return
        event.accept()
