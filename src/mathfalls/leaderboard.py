from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScoreRow:
    nickname: str
    score: float
    created_at: str
    eliminated: bool = False


class Leaderboard:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scores (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nickname TEXT NOT NULL,
                    score REAL NOT NULL,
                    eliminated INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(scores)").fetchall()}
            if "eliminated" not in columns:
                conn.execute("ALTER TABLE scores ADD COLUMN eliminated INTEGER NOT NULL DEFAULT 0")

    def add_score(self, nickname: str, score: float, eliminated: bool = False) -> None:
        clean_name = nickname.strip()[:16] or "PLAYER"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO scores (nickname, score, eliminated) VALUES (?, ?, ?)",
                (clean_name, float(score), int(eliminated)),
            )

    def top(self, limit: int = 10) -> list[ScoreRow]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT nickname, score, created_at, eliminated
                FROM scores
                ORDER BY eliminated ASC, score DESC, created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [ScoreRow(nickname=row[0], score=row[1], created_at=row[2], eliminated=bool(row[3])) for row in rows]
