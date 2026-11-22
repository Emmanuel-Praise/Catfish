import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import settings

SCHEMA_FILE = __import__("pathlib").Path(__file__).parent / "schema.sql"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows_to_dicts(rows) -> list[dict]:
    return [dict(row) for row in rows]
