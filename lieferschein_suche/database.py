from __future__ import annotations

import sqlite3
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    filename: str
    page_number: int
    snippet: str
    ocr_used: bool
    modified_ns: int
    query: str
    verified_delivery_number: bool = False


class IndexDatabase:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA cache_size=-65536")
            conn.execute("PRAGMA mmap_size=268435456")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    filename TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    modified_ns INTEGER NOT NULL,
                    indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS pages (
                    id INTEGER PRIMARY KEY,
                    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    page_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    ocr_used INTEGER NOT NULL DEFAULT 0,
                    ocr_words_json TEXT,
                    UNIQUE(document_id, page_number)
                );
                CREATE INDEX IF NOT EXISTS idx_pages_document ON pages(document_id);
                CREATE TABLE IF NOT EXISTS number_index (
                    page_id INTEGER NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    value TEXT NOT NULL,
                    PRIMARY KEY(page_id, value)
                ) WITHOUT ROWID;
                CREATE INDEX IF NOT EXISTS idx_number_index_value ON number_index(value);
                """
            )
            # Version 1.0 maintained an unused full-page FTS table. Removing it cuts
            # database writes and disk usage significantly for six-figure PDF sets.
            conn.executescript(
                """
                DROP TRIGGER IF EXISTS pages_ai;
                DROP TRIGGER IF EXISTS pages_ad;
                DROP TRIGGER IF EXISTS pages_au;
                DROP TABLE IF EXISTS page_fts;
                PRAGMA user_version=2;
                """
            )

    def known_signatures(self) -> dict[str, tuple[int, int]]:
        with self.connect() as conn:
            return {row["path"]: (row["size"], row["modified_ns"]) for row in conn.execute("SELECT path,size,modified_ns FROM documents")}

    def replace_document(
        self,
        path: Path,
        size: int,
        modified_ns: int,
        pages: Iterable[tuple[int, str, str, bool, str | None]],
    ) -> None:
        self.write_results_batch([(path, size, modified_ns, list(pages), None)])

    def write_results_batch(
        self,
        results: Iterable[tuple[Path, int, int, list[tuple[int, str, str, bool, str | None]], str | None]],
    ) -> None:
        """Persist several extraction results in one durable transaction."""
        with self.connect() as conn:
            for path, size, modified_ns, page_rows, error in results:
                if error:
                    self._record_error(conn, path, size, modified_ns, error)
                    continue
                conn.execute(
                """INSERT INTO documents(path,filename,size,modified_ns,indexed_at,page_count,error)
                   VALUES(?,?,?,?,CURRENT_TIMESTAMP,?,NULL)
                   ON CONFLICT(path) DO UPDATE SET filename=excluded.filename,size=excluded.size,
                   modified_ns=excluded.modified_ns,indexed_at=CURRENT_TIMESTAMP,page_count=excluded.page_count,error=NULL""",
                (str(path), path.name, size, modified_ns, len(page_rows)),
                )
                document_id = conn.execute("SELECT id FROM documents WHERE path=?", (str(path),)).fetchone()[0]
                conn.execute("DELETE FROM pages WHERE document_id=?", (document_id,))
                for row in page_rows:
                    cursor = conn.execute(
                        "INSERT INTO pages(document_id,page_number,text,normalized_text,ocr_used,ocr_words_json) VALUES(?,?,?,?,?,?)",
                        (document_id, *row),
                    )
                    tokens = _number_tokens(row[1])
                    if tokens:
                        conn.executemany(
                            "INSERT OR IGNORE INTO number_index(page_id,value) VALUES(?,?)",
                            ((cursor.lastrowid, token) for token in tokens),
                        )

    def record_error(self, path: Path, size: int, modified_ns: int, message: str) -> None:
        with self.connect() as conn:
            self._record_error(conn, path, size, modified_ns, message)

    def _record_error(self, conn: sqlite3.Connection, path: Path, size: int, modified_ns: int, message: str) -> None:
        conn.execute(
                """INSERT INTO documents(path,filename,size,modified_ns,indexed_at,page_count,error)
                   VALUES(?,?,?,?,CURRENT_TIMESTAMP,0,?)
                   ON CONFLICT(path) DO UPDATE SET size=excluded.size,modified_ns=excluded.modified_ns,
                   indexed_at=CURRENT_TIMESTAMP,page_count=0,error=excluded.error""",
                (str(path), path.name, size, modified_ns, message[:2000]),
        )
        document_id = conn.execute("SELECT id FROM documents WHERE path=?", (str(path),)).fetchone()[0]
        conn.execute("DELETE FROM pages WHERE document_id=?", (document_id,))

    def remove_missing(self, existing_paths: set[str], root: Path) -> int:
        root_text = str(root).rstrip("\\/").casefold()
        with self.connect() as conn:
            rows = conn.execute("SELECT id,path FROM documents").fetchall()
            ids = [r["id"] for r in rows if r["path"].casefold().startswith(root_text) and r["path"] not in existing_paths]
            conn.executemany("DELETE FROM documents WHERE id=?", ((value,) for value in ids))
            return len(ids)

    def remove_paths(self, paths: Iterable[str | Path]) -> int:
        values = [(str(path),) for path in paths]
        if not values:
            return 0
        with self.connect() as conn:
            placeholders = ",".join("?" for _ in values)
            count = conn.execute(
                f"SELECT COUNT(*) FROM documents WHERE path IN ({placeholders})",
                tuple(value[0] for value in values),
            ).fetchone()[0]
            conn.executemany("DELETE FROM documents WHERE path=?", values)
            return count

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM documents")

    def stats(self) -> tuple[int, int, int]:
        with self.connect() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM documents WHERE error IS NULL").fetchone()[0]
            pages = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            errors = conn.execute("SELECT COUNT(*) FROM documents WHERE error IS NOT NULL").fetchone()[0]
            return docs, pages, errors

    def search(
        self,
        query: str,
        normalized_query: str,
        limit: int = 500,
        precise_carl_eichhorn: bool = False,
    ) -> list[SearchHit]:
        if not normalized_query:
            return []
        indexed_sql = """
            SELECT DISTINCT d.path,d.filename,d.modified_ns,p.page_number,p.text,p.ocr_used
            FROM number_index n
            JOIN pages p ON p.id=n.page_id
            JOIN documents d ON d.id=p.document_id
            WHERE n.value=?
            ORDER BY d.modified_ns DESC,d.filename COLLATE NOCASE,p.page_number
            LIMIT ?
        """
        fallback_sql = """
            SELECT d.path,d.filename,d.modified_ns,p.page_number,p.text,p.ocr_used,p.normalized_text
            FROM pages p JOIN documents d ON d.id=p.document_id
            WHERE p.normalized_text LIKE ? ESCAPE '\\'
            ORDER BY d.modified_ns DESC,d.filename COLLATE NOCASE,p.page_number
            LIMIT ?
        """
        hits: list[SearchHit] = []
        with self.connect() as conn:
            rows = conn.execute(indexed_sql, (normalized_query, limit)).fetchall()
            if not rows:
                escaped = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                rows = conn.execute(fallback_sql, (f"%{escaped}%", limit)).fetchall()
            for row in rows:
                verified = _is_carl_eichhorn(row["text"]) and normalized_query in _delivery_note_numbers(row["text"])
                if precise_carl_eichhorn and not verified:
                    continue
                hits.append(
                    SearchHit(
                        path=row["path"], filename=row["filename"], page_number=row["page_number"],
                        snippet=_snippet(row["text"], query), ocr_used=bool(row["ocr_used"]),
                        modified_ns=row["modified_ns"], query=query,
                        verified_delivery_number=verified,
                    )
                )
        return hits

    def ocr_words(self, path: str, page_number: int) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT p.ocr_words_json FROM pages p JOIN documents d ON d.id=p.document_id WHERE d.path=? AND p.page_number=?",
                (path, page_number),
            ).fetchone()
            return row[0] if row else None


def _snippet(text: str, query: str, radius: int = 90) -> str:
    flat = " ".join(text.split())
    index = flat.casefold().find(query.casefold())
    if index < 0:
        compact_query = "".join(c for c in query.casefold() if c.isalnum())
        compact = "".join(c for c in flat.casefold() if c.isalnum())
        index = compact.find(compact_query)
        if index < 0:
            return flat[: radius * 2] + (" …" if len(flat) > radius * 2 else "")
        index = min(index, len(flat))
    start = max(0, index - radius)
    end = min(len(flat), index + len(query) + radius)
    return ("… " if start else "") + flat[start:end] + (" …" if end < len(flat) else "")


_NUMBER_PATTERN = re.compile(
    r"(?<![\w])(?:[A-Za-zÄÖÜäöüß]{1,10}[-_/]?)?\d(?:[A-Za-z0-9ÄÖÜäöüß_./-]*\d)?(?![\w])"
)


def _number_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _NUMBER_PATTERN.finditer(text):
        value = "".join(character for character in match.group(0).casefold() if character.isalnum())
        if 5 <= len(value) <= 48 and sum(character.isdigit() for character in value) >= 3:
            tokens.add(value)
    return tokens


_DELIVERY_NUMBER_PATTERN = re.compile(
    r"liefer\s*schein\s*[-.:/]?\s*(?:nr|nummer)\s*[-.:#]*\s*([0-9][0-9\s./-]{2,20})",
    re.IGNORECASE,
)


def _delivery_note_numbers(text: str) -> set[str]:
    """Return only numbers explicitly assigned to a Lieferschein-Nr. label."""
    numbers: set[str] = set()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        matches = list(_DELIVERY_NUMBER_PATTERN.finditer(line))
        # Some PDF text layers place the value in a separate column/line.
        if not matches and index + 1 < len(lines):
            matches = list(_DELIVERY_NUMBER_PATTERN.finditer(f"{line} {lines[index + 1]}"))
        for match in matches:
            value = "".join(character for character in match.group(1) if character.isdigit())
            if 4 <= len(value) <= 12:
                numbers.add(value)
    return numbers


def _is_carl_eichhorn(text: str) -> bool:
    compact = re.sub(r"[^a-z0-9]+", "", text.casefold())
    # Tolerate the common OCR substitution O -> 0 in EICHHORN.
    return bool(re.search(r"eichh[o0]rn", compact)) and ("carl" in compact or "wellpappen" in compact)
