from __future__ import annotations

import os
import sys
from pathlib import Path


APP_NAME = "LieferscheinSuche"


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        path = Path(base) / APP_NAME
    else:
        path = Path.home() / ".local" / "share" / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base.joinpath(*parts)


def database_path() -> Path:
    return app_data_dir() / "index.sqlite3"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def log_path() -> Path:
    return app_data_dir() / "lieferschein-suche.log"

