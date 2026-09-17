from __future__ import annotations

import sys
import multiprocessing

from PySide6.QtWidgets import QApplication

from .database import IndexDatabase
from .logging_setup import configure_logging
from .main_window import MainWindow
from .paths import database_path
from .settings import AppSettings
from .style import APP_STYLE


def main() -> int:
    multiprocessing.freeze_support()
    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Lieferschein-Suche")
    app.setOrganizationName("LieferscheinSuche")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    window = MainWindow(IndexDatabase(database_path()), AppSettings.load())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
