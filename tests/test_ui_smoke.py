from pathlib import Path

from PySide6.QtWidgets import QApplication

from lieferschein_suche.database import IndexDatabase
from lieferschein_suche.main_window import MainWindow
from lieferschein_suche.settings import AppSettings


def test_main_window_constructs(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(IndexDatabase(tmp_path / "ui.sqlite3"), AppSettings())
    assert "Lieferschein-Suche" in window.windowTitle()
    window.close()
