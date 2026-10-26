"""Persistent history (SQLite) and Leitner-box scheduling of exercises."""

from __future__ import annotations

import os
import random
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

# Days until the next review, indexed by Leitner box. Box 0 means "again, this session".
INTERVALS = (0, 1, 3, 7, 16, 35)
DAY = 86400

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    mode TEXT NOT NULL,
    langs TEXT NOT NULL,
    started REAL NOT NULL,
    ended REAL
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY,
    session INTEGER REFERENCES sessions(id),
    exercise TEXT NOT NULL,
    lang TEXT NOT NULL,
    mode TEXT NOT NULL,
    finished REAL NOT NULL,
    seconds REAL NOT NULL,
    target REAL NOT NULL,
    runs INTEGER NOT NULL,
    hinted INTEGER NOT NULL,
    outcome TEXT NOT NULL,   -- pass | skip
    grade TEXT NOT NULL,     -- good | ok | fail
    variant INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS estimates (
    id INTEGER PRIMARY KEY,
    finished REAL NOT NULL,
    exercise TEXT NOT NULL,
    lang TEXT NOT NULL,
    guess TEXT NOT NULL,
    measured TEXT NOT NULL,  -- the consistent classes, comma-separated
    slope REAL NOT NULL,
    correct INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    exercise TEXT NOT NULL,
    lang TEXT NOT NULL,
    box INTEGER NOT NULL,
    due REAL NOT NULL,
    best REAL,
    PRIMARY KEY (exercise, lang)
);
"""


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / "drill"


@dataclass
class Card:
    exercise: str
    lang: str
    box: int
    due: float
    best: float | None


def grade(seconds: float, target: float, hinted: bool, skipped: bool) -> str:
    if skipped or seconds > 2 * target:
        return "fail"
    if hinted or seconds > target:
        return "ok"
    return "good"


class Store:
    def __init__(self, path: Path | None = None):
        path = path or data_dir() / "history.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(attempts)")}
        if "variant" not in columns:  # history from before variants
            with self.db:
                self.db.execute("ALTER TABLE attempts ADD COLUMN variant INTEGER NOT NULL DEFAULT 0")

    def start_session(self, mode: str, langs: list[str]) -> int:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO sessions (mode, langs, started) VALUES (?, ?, ?)",
                (mode, ",".join(langs), time.time()),
            )
        return cur.lastrowid

    def end_session(self, session: int) -> None:
        with self.db:
            self.db.execute("UPDATE sessions SET ended = ? WHERE id = ?", (time.time(), session))

    def cards(self) -> dict[tuple[str, str], Card]:
        rows = self.db.execute("SELECT exercise, lang, box, due, best FROM cards")
        return {(r["exercise"], r["lang"]): Card(*r) for r in rows}

    def card(self, exercise: str, lang: str) -> Card | None:
        row = self.db.execute(
            "SELECT exercise, lang, box, due, best FROM cards WHERE exercise = ? AND lang = ?",
            (exercise, lang),
        ).fetchone()
        return Card(*row) if row else None

    def variants_seen(self, exercise: str, lang: str) -> dict[int, float]:
        """When each variant of an exercise was last practised in a language."""
        rows = self.db.execute(
            "SELECT variant, MAX(finished) AS last FROM attempts WHERE exercise = ? AND lang = ?"
            " GROUP BY variant",
            (exercise, lang),
        )
        return {r["variant"]: r["last"] for r in rows}

    def attempts(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM attempts ORDER BY finished").fetchall()

    def record_estimate(
        self, exercise: str, lang: str, guess: str, measured: list[str], slope: float
    ) -> None:
        """Store a complexity estimate and what the measurement found."""
        with self.db:
            self.db.execute(
                "INSERT INTO estimates (finished, exercise, lang, guess, measured, slope, correct)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (time.time(), exercise, lang, guess, ",".join(measured), slope, guess in measured),
            )

    def estimates(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM estimates ORDER BY finished").fetchall()

    def record(
        self,
        session: int,
        exercise: str,
        lang: str,
        mode: str,
        seconds: float,
        target: float,
        runs: int,
        hinted: bool,
        skipped: bool,
        variant: int = 0,
    ) -> Card:
        """Store an attempt and move the exercise to its next Leitner box."""
        now = time.time()
        result = grade(seconds, target, hinted, skipped)
        card = self.card(exercise, lang)
        box = card.box if card else 0
        box = {"good": min(box + 1, len(INTERVALS) - 1), "ok": max(box - 1, 1), "fail": 0}[result]
        best = card.best if card else None
        if not skipped and not hinted and (best is None or seconds < best):
            best = seconds
        updated = Card(exercise, lang, box, now + INTERVALS[box] * DAY, best)
        with self.db:
            self.db.execute(
                "INSERT INTO attempts (session, exercise, lang, mode, finished, seconds, target,"
                " runs, hinted, outcome, grade, variant) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session, exercise, lang, mode, now, seconds, target, runs, hinted,
                 "skip" if skipped else "pass", result, variant),
            )
            self.db.execute(
                "INSERT INTO cards (exercise, lang, box, due, best) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (exercise, lang) DO UPDATE"
                " SET box = excluded.box, due = excluded.due, best = excluded.best",
                (exercise, lang, box, updated.due, best),
            )
        return updated


def pick(pool: list, cards: dict[tuple[str, str], Card], recent, rng=random):
    """Choose the next (exercise, language) pair from `pool`.

    Due reviews come first (most overdue first), mixed with unseen exercises so new
    material keeps flowing. Exercises in `recent` are avoided when possible.
    """
    now = time.time()
    fresh = [p for p in pool if p[0].id not in recent] or pool

    def key(pair):
        return pair[0].id, pair[1].key

    due = [p for p in fresh if key(p) in cards and cards[key(p)].due <= now]
    new = [p for p in fresh if key(p) not in cards]
    if due and (not new or rng.random() < 0.7):
        return min(due, key=lambda p: (cards[key(p)].due, rng.random()))
    if new:
        return rng.choice(new)
    # Nothing due: practise ahead, starting with what would come back soonest
    return min(fresh, key=lambda p: (cards[key(p)].due, rng.random()))
