"""Durable outbox: spans wait here until the server has accepted them."""

import json
import sqlite3
import threading
from pathlib import Path


class Outbox:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        self._db.commit()

    def put(self, events: list[dict]) -> None:
        if not events:
            return
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO outbox (seq, body) VALUES (?, ?)",
                                 [(e["seq"], json.dumps(e)) for e in events])
            self._db.commit()

    def peek(self, limit: int = 2000) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT body FROM outbox ORDER BY seq LIMIT ?", (limit,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def remove(self, seqs: list[int]) -> None:
        with self._lock:
            self._db.executemany("DELETE FROM outbox WHERE seq = ?", [(s,) for s in seqs])
            self._db.commit()

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def close(self) -> None:
        with self._lock:
            self._db.close()
