from __future__ import annotations

import tempfile
from pathlib import Path

import fitz

from .database import IndexDatabase
from .indexer import PdfIndexer
from .ocr import normalize_search_text


def run_self_test() -> int:
    """Exercise packaged multiprocessing, PDF extraction, database and fast search."""
    with tempfile.TemporaryDirectory(prefix="lieferschein_selftest_") as temporary:
        root = Path(temporary)
        for number in range(4):
            document = fitz.open()
            page = document.new_page()
            page.insert_text((72, 100), f"Lieferscheinnummer SELFTEST-{number:05d} mit ausreichend Textinhalt")
            document.save(root / f"test {number}.pdf")
            document.close()
        database = IndexDatabase(root / "selftest.sqlite3")
        result = PdfIndexer(database, workers=2).run(root, recursive=False)
        hits = database.search("SELFTEST-00003", normalize_search_text("SELFTEST-00003"))
        return 0 if result.processed == 4 and len(hits) == 1 else 2

