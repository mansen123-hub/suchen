from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True, slots=True)
class SearchHit:
    path: str
    filename: str
    page_number: int
    snippet: str
    ocr_used: bool
    modified_ns: int
    query: str


class IndexDatabase:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

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
                """
            )
            try:
                conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS page_fts USING fts5(normalized_text, content='pages', content_rowid='id', tokenize='unicode61')"
                )
                conn.executescript(
                    """
                    CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
                      INSERT INTO page_fts(rowid, normalized_text) VALUES (new.id, new.normalized_text);
                    END;
                    CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
                      INSERT INTO page_fts(page_fts, rowid, normalized_text) VALUES('delete', old.id, old.normalized_text);
                    END;
                    CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
                      INSERT INTO page_fts(page_fts, rowid, normalized_text) VALUES('delete', old.id, old.normalized_text);
                      INSERT INTO page_fts(rowid, normalized_text) VALUES (new.id, new.normalized_text);
                    END;
                    """
                )
            except sqlite3.OperationalError:
                pass

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
        page_rows = list(pages)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO documents(path,filename,size,modified_ns,indexed_at,page_count,error)
                   VALUES(?,?,?,?,CURRENT_TIMESTAMP,?,NULL)
                   ON CONFLICT(path) DO UPDATE SET filename=excluded.filename,size=excluded.size,
                   modified_ns=excluded.modified_ns,indexed_at=CURRENT_TIMESTAMP,page_count=excluded.page_count,error=NULL""",
                (str(path), path.name, size, modified_ns, len(page_rows)),
            )
            document_id = conn.execute("SELECT id FROM documents WHERE path=?", (str(path),)).fetchone()[0]
            conn.execute("DELETE FROM pages WHERE document_id=?", (document_id,))
            conn.executemany(
                "INSERT INTO pages(document_id,page_number,text,normalized_text,ocr_used,ocr_words_json) VALUES(?,?,?,?,?,?)",
                ((document_id, *row) for row in page_rows),
            )

    def record_error(self, path: Path, size: int, modified_ns: int, message: str) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO documents(path,filename,size,modified_ns,indexed_at,page_count,error)
                   VALUES(?,?,?,?,CURRENT_TIMESTAMP,0,?)
                   ON CONFLICT(path) DO UPDATE SET size=excluded.size,modified_ns=excluded.modified_ns,
                   indexed_at=CURRENT_TIMESTAMP,page_count=0,error=excluded.error""",
                (str(path), path.name, size, modified_ns, message[:2000]),
            )

    def remove_missing(self, existing_paths: set[str], root: Path) -> int:
        root_text = str(root).rstrip("\\/").casefold()
        with self.connect() as conn:
            rows = conn.execute("SELECT id,path FROM documents").fetchall()
            ids = [r["id"] for r in rows if r["path"].casefold().startswith(root_text) and r["path"] not in existing_paths]
            conn.executemany("DELETE FROM documents WHERE id=?", ((value,) for value in ids))
            return len(ids)

    def clear(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM documents")

    def stats(self) -> tuple[int, int, int]:
        with self.connect() as conn:
            docs = conn.execute("SELECT COUNT(*) FROM documents WHERE error IS NULL").fetchone()[0]
            pages = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
            errors = conn.execute("SELECT COUNT(*) FROM documents WHERE error IS NOT NULL").fetchone()[0]
            return docs, pages, errors

    def search(self, query: str, normalized_query: str, limit: int = 500) -> list[SearchHit]:
        if not normalized_query:
            return []
        escaped = normalized_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        sql = """
            SELECT d.path,d.filename,d.modified_ns,p.page_number,p.text,p.ocr_used,p.normalized_text
            FROM pages p JOIN documents d ON d.id=p.document_id
            WHERE p.normalized_text LIKE ? ESCAPE '\\'
            ORDER BY d.modified_ns DESC,d.filename COLLATE NOCASE,p.page_number
            LIMIT ?
        """
        hits: list[SearchHit] = []
        with self.connect() as conn:
            for row in conn.execute(sql, (pattern, limit)):
                hits.append(
                    SearchHit(
                        path=row["path"], filename=row["filename"], page_number=row["page_number"],
                        snippet=_snippet(row["text"], query), ocr_used=bool(row["ocr_used"]),
                        modified_ns=row["modified_ns"], query=query,
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
