from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import fitz

from .paths import resource_path

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class OcrWord:
    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float


def find_tesseract() -> Path:
    configured = os.environ.get("TESSERACT_CMD")
    candidates = [
        Path(configured) if configured else None,
        resource_path("ocr", "tesseract.exe"),
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR" / "tesseract.exe",
        Path(shutil.which("tesseract")) if shutil.which("tesseract") else None,
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return candidate
    raise FileNotFoundError("Die gebündelte OCR-Engine wurde nicht gefunden.")


def text_is_usable(text: str) -> bool:
    stripped = "".join(text.split())
    if len(stripped) < 20:
        return False
    readable = sum(ch.isalnum() or ch in "-_/.:,äöüÄÖÜß" for ch in stripped)
    return readable / max(len(stripped), 1) >= 0.65


def normalize_search_text(text: str) -> str:
    # Lieferscheinnummern werden unabhängig von Leerzeichen und Trennzeichen auffindbar.
    return re.sub(r"[^0-9a-zäöüß]+", "", text.casefold())


def ocr_page(page: fitz.Page, languages: str = "deu+eng", dpi: int = 300) -> tuple[str, str]:
    executable = find_tesseract()
    scale = dpi / 72.0
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False, colorspace=fitz.csRGB)
    with tempfile.TemporaryDirectory(prefix="lieferschein_ocr_") as temporary:
        image_path = Path(temporary) / "page.png"
        pixmap.save(str(image_path))
        env = os.environ.copy()
        # Each PDF worker runs its own Tesseract process. Keep one OCR process to one CPU thread.
        env.setdefault("OMP_THREAD_LIMIT", "1")
        tessdata = executable.parent / "tessdata"
        if tessdata.is_dir():
            env["TESSDATA_PREFIX"] = str(tessdata)
        command = [str(executable), str(image_path), "stdout", "-l", languages, "--psm", "6", "tsv"]
        result = subprocess.run(command, capture_output=True, check=False, env=env, timeout=180)
        if result.returncode != 0:
            message = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"OCR fehlgeschlagen: {message or result.returncode}")
        tsv = result.stdout.decode("utf-8", errors="replace")

    words: list[OcrWord] = []
    lines: dict[tuple[str, str, str, str], list[str]] = {}
    reader = csv.DictReader(io.StringIO(tsv), delimiter="\t")
    for row in reader:
        text = (row.get("text") or "").strip()
        try:
            confidence = float(row.get("conf") or -1)
        except ValueError:
            confidence = -1
        if not text or confidence < 20:
            continue
        word = OcrWord(
            text=text,
            x=float(row["left"]) / scale,
            y=float(row["top"]) / scale,
            width=float(row["width"]) / scale,
            height=float(row["height"]) / scale,
            confidence=confidence,
        )
        words.append(word)
        key = (row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", ""), row.get("page_num", ""))
        lines.setdefault(key, []).append(text)
    extracted = "\n".join(" ".join(values) for values in lines.values())
    return extracted, json.dumps([asdict(word) for word in words], ensure_ascii=False, separators=(",", ":"))
