from pathlib import Path
import os
import sqlite3
import threading
import time
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("SUBLEARN_DATA_DIR", str(ROOT / "data")))
DB_PATH = DATA_DIR / "vocab.db"
_db_lock = threading.RLock()


def init_vocab_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _db_lock:
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vocabulary (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    word TEXT NOT NULL,
                    translation TEXT NOT NULL,
                    context TEXT NOT NULL DEFAULT '',
                    saved_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_vocab_word_ctx "
                "ON vocabulary(word COLLATE NOCASE, context)"
            )
            conn.commit()
        finally:
            conn.close()


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_item(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "word": row["word"],
        "translation": row["translation"],
        "context": row["context"] or "",
        "savedAt": row["saved_at"],
    }


def vocab_list() -> list:
    with _db_lock:
        conn = _db()
        try:
            rows = conn.execute(
                "SELECT id, word, translation, context, saved_at "
                "FROM vocabulary ORDER BY saved_at DESC, id DESC"
            ).fetchall()
            return [_row_to_item(r) for r in rows]
        finally:
            conn.close()


def vocab_add(
    word: str,
    translation: str,
    context: str = "",
    *,
    saved_at: Optional[int] = None,
) -> dict:
    word = (word or "").strip()
    translation = (translation or "").strip()
    context = (context or "").strip()
    if not word or not translation:
        raise ValueError("Нужны word и translation")
    ts = int(saved_at) if saved_at is not None else int(time.time() * 1000)
    with _db_lock:
        conn = _db()
        try:
            existing = conn.execute(
                "SELECT id FROM vocabulary "
                "WHERE lower(word)=lower(?) AND context=? LIMIT 1",
                (word, context),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE vocabulary SET translation=?, saved_at=? WHERE id=?",
                    (translation, ts, existing["id"]),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT id, word, translation, context, saved_at "
                    "FROM vocabulary WHERE id=?",
                    (existing["id"],),
                ).fetchone()
                return _row_to_item(row)
            cur = conn.execute(
                "INSERT INTO vocabulary (word, translation, context, saved_at) "
                "VALUES (?, ?, ?, ?)",
                (word, translation, context, ts),
            )
            conn.commit()
            row = conn.execute(
                "SELECT id, word, translation, context, saved_at "
                "FROM vocabulary WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
            return _row_to_item(row)
        finally:
            conn.close()


def vocab_import_many(items: list) -> int:
    prepared = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        word = str(raw.get("word") or "").strip()
        translation = str(raw.get("translation") or "").strip()
        if not word or not translation:
            continue
        context = str(raw.get("context") or "").strip()
        saved_at = raw.get("savedAt")
        ts = int(saved_at) if saved_at is not None else int(time.time() * 1000)
        prepared.append((word, translation, context, ts))
    if not prepared:
        return 0

    imported = 0
    with _db_lock:
        conn = _db()
        try:
            for word, translation, context, ts in prepared:
                existing = conn.execute(
                    "SELECT id FROM vocabulary "
                    "WHERE lower(word)=lower(?) AND context=? LIMIT 1",
                    (word, context),
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE vocabulary SET translation=?, saved_at=? WHERE id=?",
                        (translation, ts, existing["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO vocabulary (word, translation, context, saved_at) "
                        "VALUES (?, ?, ?, ?)",
                        (word, translation, context, ts),
                    )
                imported += 1
            conn.commit()
        finally:
            conn.close()
    return imported


def vocab_delete(item_id: int) -> bool:
    with _db_lock:
        conn = _db()
        try:
            cur = conn.execute("DELETE FROM vocabulary WHERE id=?", (item_id,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def vocab_clear() -> None:
    with _db_lock:
        conn = _db()
        try:
            conn.execute("DELETE FROM vocabulary")
            conn.commit()
        finally:
            conn.close()
