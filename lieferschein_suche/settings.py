from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import settings_path


@dataclass(slots=True)
class AppSettings:
    pdf_folder: str = ""
    include_subfolders: bool = True
    watch_folder: bool = True
    ocr_languages: str = "deu+eng"
    window_width: int = 1380
    window_height: int = 860

    @classmethod
    def load(cls, path: Path | None = None) -> "AppSettings":
        target = path or settings_path()
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__.keys()
            return cls(**{k: v for k, v in raw.items() if k in allowed})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path | None = None) -> None:
        target = path or settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

