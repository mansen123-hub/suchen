from __future__ import annotations

import tempfile
import traceback
from pathlib import Path

import fitz

from .database import IndexDatabase
from .indexer import PdfIndexer
from .ocr import normalize_search_text


def run_self_test() -> int:
    """Exercise packaged multiprocessing, PDF extraction, database and fast search."""
    log_path = Path(tempfile.gettempdir()) / "LieferscheinSuche_selftest.log"

    def log(message: str) -> None:
        with log_path.open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")

    try:
        log("START")
        with tempfile.TemporaryDirectory(prefix="lieferschein_selftest_") as temporary:
            root = Path(temporary)
            for number in range(4):
                document = fitz.open()
                page = document.new_page()
                page.insert_text((72, 100), f"Lieferscheinnummer SELFTEST-{number:05d} mit ausreichend Textinhalt")
                document.save(root / f"test {number}.pdf")
                document.close()
            log("PDFS_CREATED")
            database = IndexDatabase(root / "selftest.sqlite3")
            log("DATABASE_READY")
            result = PdfIndexer(database, workers=2).run(root, recursive=False)
            log(f"INDEX_DONE processed={result.processed} errors={result.errors}")
            hits = database.search("SELFTEST-00003", normalize_search_text("SELFTEST-00003"))
            log(f"SEARCH_DONE hits={len(hits)}")
            return 0 if result.processed == 4 and len(hits) == 1 else 2
    except Exception:
        log("FAILED\n" + traceback.format_exc())
        return 3
