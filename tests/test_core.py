from __future__ import annotations

import os
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from lieferschein_suche.database import IndexDatabase
from lieferschein_suche.indexer import PdfIndexer
from lieferschein_suche.ocr import normalize_search_text, text_is_usable


def create_pdf(path: Path, pages: list[str]) -> None:
    document = fitz.open()
    for content in pages:
        page = document.new_page()
        page.insert_text((72, 100), content)
    document.save(path)
    document.close()


def test_normalization_handles_hyphens_and_spaces() -> None:
    assert normalize_search_text("LS-2026 / 00 1284") == "ls2026001284"


def test_useful_text_detection() -> None:
    assert text_is_usable("Lieferscheinnummer LS-2026-001284 für Kunde Muster GmbH")
    assert not text_is_usable("  12  ")


def test_index_search_incremental_and_removed(tmp_path: Path) -> None:
    pdf = tmp_path / "Lieferschein Ä 01.pdf"
    create_pdf(pdf, ["Lieferscheinnummer LS-2026-001284 Kunde Muster", "Zweite Seite mit ausreichend langem Textinhalt"])
    database = IndexDatabase(tmp_path / "index.sqlite3")
    indexer = PdfIndexer(database)

    first = indexer.run(tmp_path, recursive=True)
    assert first.processed == 1
    assert len(database.search("LS-2026-001284", normalize_search_text("LS-2026-001284"))) == 1
    assert database.search("LS2026001284", normalize_search_text("LS2026001284"))[0].page_number == 1

    second = indexer.run(tmp_path, recursive=True)
    assert second.processed == 0
    assert second.skipped == 1

    pdf.unlink()
    third = indexer.run(tmp_path, recursive=True)
    assert third.removed == 1
    assert database.stats()[0] == 0


def test_changed_pdf_is_reindexed(tmp_path: Path) -> None:
    pdf = tmp_path / "changed.pdf"
    create_pdf(pdf, ["Lieferscheinnummer LS-1000 mit ausreichend Textinhalt"])
    database = IndexDatabase(tmp_path / "index.sqlite3")
    indexer = PdfIndexer(database)
    indexer.run(tmp_path, recursive=False)

    pdf.unlink()
    create_pdf(pdf, ["Lieferscheinnummer LS-2000 mit ausreichend Textinhalt"])
    stat = pdf.stat()
    os.utime(pdf, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    result = indexer.run(tmp_path, recursive=False)
    assert result.processed == 1
    assert not database.search("LS-1000", normalize_search_text("LS-1000"))
    assert database.search("LS-2000", normalize_search_text("LS-2000"))


def test_scan_pdf_uses_local_ocr(tmp_path: Path, monkeypatch) -> None:
    if not Path("/usr/bin/tesseract").exists():
        return
    monkeypatch.setenv("TESSERACT_CMD", "/usr/bin/tesseract")
    image = Image.new("RGB", (1800, 700), "white")
    draw = ImageDraw.Draw(image)
    draw.text((120, 220), "DELIVERY NOTE LS-987654321", fill="black", font_size=76)
    image_path = tmp_path / "scan.png"
    image.save(image_path)
    pdf = tmp_path / "scan only.pdf"
    document = fitz.open()
    page = document.new_page(width=900, height=350)
    page.insert_image(page.rect, filename=str(image_path))
    document.save(pdf)
    document.close()

    database = IndexDatabase(tmp_path / "scan-index.sqlite3")
    result = PdfIndexer(database, ocr_languages="eng").run(tmp_path, recursive=False)
    assert result.errors == 0
    hits = database.search("LS-987654321", normalize_search_text("LS-987654321"))
    assert hits and hits[0].ocr_used


def test_many_pdfs_and_existing_index_after_restart(tmp_path: Path) -> None:
    for number in range(30):
        create_pdf(tmp_path / f"Lieferung {number:02d}.pdf", [f"Lieferscheinnummer BATCH-{number:05d} mit ausreichend Textinhalt"])
    db_path = tmp_path / "persistent.sqlite3"
    first_database = IndexDatabase(db_path)
    result = PdfIndexer(first_database).run(tmp_path, recursive=False)
    assert result.processed == 30

    reopened_database = IndexDatabase(db_path)
    hits = reopened_database.search("BATCH-00017", normalize_search_text("BATCH-00017"))
    assert len(hits) == 1
    assert hits[0].filename == "Lieferung 17.pdf"


def test_number_search_uses_dedicated_fast_index(tmp_path: Path) -> None:
    pdf = tmp_path / "fast.pdf"
    create_pdf(pdf, ["Lieferscheinnummer LS-2026-778899 mit ausreichend Textinhalt"])
    database = IndexDatabase(tmp_path / "fast.sqlite3")
    PdfIndexer(database, workers=2).run(tmp_path, recursive=False)
    with database.connect() as conn:
        conn.execute("UPDATE pages SET normalized_text='keinfallbacktreffer'")
    hits = database.search("LS-2026-778899", normalize_search_text("LS-2026-778899"))
    assert len(hits) == 1


def test_targeted_update_does_not_rescan_folder(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    create_pdf(first, ["Lieferscheinnummer TARGET-10001 mit ausreichend Textinhalt"])
    create_pdf(second, ["Lieferscheinnummer TARGET-20002 mit ausreichend Textinhalt"])
    database = IndexDatabase(tmp_path / "targeted.sqlite3")
    indexer = PdfIndexer(database, workers=2)
    indexer.run(tmp_path, recursive=False)

    first.unlink()
    create_pdf(second, ["Lieferscheinnummer TARGET-30003 mit ausreichend Textinhalt"])
    stat = second.stat()
    os.utime(second, ns=(stat.st_atime_ns, stat.st_mtime_ns + 20_000_000))
    result = indexer.run_paths([first, second])
    assert result.removed == 1
    assert result.processed == 1
    assert database.search("TARGET-30003", normalize_search_text("TARGET-30003"))
    assert not database.search("TARGET-10001", normalize_search_text("TARGET-10001"))
