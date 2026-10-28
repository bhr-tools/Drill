"""History and Leitner-box scheduling of exercises.

The history lives in the library, in history/<machine>.jsonl: one line per attempt or
complexity estimate, appended by that machine only, so that git merges the machines'
histories without conflicts. The SQLite database is a local cache of them, rebuilt
whenever a file has changed (after a pull), the levels replayed from the attempts.
"""

from __future__ import annotations

import json
import os
import random
import re
import socket
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
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
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


def advance(card: Card | None, exercise: str, lang: str, attempt: dict) -> Card:
    """The card after an attempt: up a box when good, down when ok, back to 0 on a fail."""
    box = card.box if card else 0
    box = {"good": min(box + 1, len(INTERVALS) - 1), "ok": max(box - 1, 1), "fail": 0}[attempt["grade"]]
    best = card.best if card else None
    seconds = attempt["seconds"]
    if attempt["outcome"] == "pass" and not attempt["hinted"] and (best is None or seconds < best):
        best = seconds
    return Card(exercise, lang, box, attempt["finished"] + INTERVALS[box] * DAY, best)


def machine() -> str:
    name = os.environ.get("DRILL_MACHINE") or socket.gethostname()
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name) or "machine"


class Store:
    def __init__(self, history: Path | None = None, path: Path | None = None):
        """`history`: the library's history folder; None keeps the history in the cache only."""
        path = path or data_dir() / "history.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(attempts)")}
        if "variant" not in columns:  # history from before variants
            with self.db:
                self.db.execute("ALTER TABLE attempts ADD COLUMN variant INTEGER NOT NULL DEFAULT 0")
        self.history = history
        if history is not None:
            self.own = history / f"{machine()}.jsonl"
            self.export_local()
            if self.signature() != self.meta("signature"):
                self.rebuild()

    def meta(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def signature(self) -> str:
        """Changes when a history file does."""
        files = sorted(self.history.glob("*.jsonl")) if self.history.is_dir() else []
        return "|".join(f"{f.name}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files)

    def append(self, entry: dict) -> None:
        """Add an entry to this machine's history file; the cache already has it."""
        if self.history is None:
            return
        current = self.signature() == self.meta("signature")
        self.own.parent.mkdir(parents=True, exist_ok=True)
        with self.own.open("a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        if current:  # else another file changed too: rebuild next time
            self.set_meta("signature", self.signature())

    def export_local(self) -> None:
        """Once: write the history kept only in the cache (from before the library held
        it) to this machine's file."""
        if self.meta("exported") is not None:
            return
        if not self.own.exists():
            entries = [
                {"type": "attempt", **{k: r[k] for k in r.keys() if k not in ("id", "session")},
                 "session": f"{machine()}/{r['session']}"}
                for r in self.attempts()
            ] + [
                {"type": "estimate", **{k: r[k] for k in r.keys() if k != "id"},
                 "measured": r["measured"].split(",") if r["measured"] else []}
                for r in self.estimates()
            ]
            if entries:
                entries.sort(key=lambda e: e["finished"])
                self.own.parent.mkdir(parents=True, exist_ok=True)
                with self.own.open("w") as f:
                    for entry in entries:
                        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self.set_meta("exported", "1")

    def rebuild(self) -> None:
        """Rebuild the cache from every machine's history file."""
        entries = []
        for path in sorted(self.history.glob("*.jsonl")) if self.history.is_dir() else []:
            for line in path.read_text().splitlines():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # a line cut short
        entries.sort(key=lambda e: e.get("finished", 0))
        cards: dict[tuple[str, str], Card] = {}
        with self.db:
            for table in ("attempts", "estimates", "cards"):
                self.db.execute(f"DELETE FROM {table}")
            for e in entries:
                if e.get("type") == "estimate":
                    self.db.execute(
                        "INSERT INTO estimates (finished, exercise, lang, guess, measured, slope,"
                        " correct) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (e["finished"], e["exercise"], e["lang"], e["guess"],
                         ",".join(e["measured"]), e["slope"], e["correct"]),
                    )
                    continue
                key = (e["exercise"], e["lang"])
                cards[key] = advance(cards.get(key), *key, e)
                self.db.execute(
                    "INSERT INTO attempts (session, exercise, lang, mode, finished, seconds,"
                    " target, runs, hinted, outcome, grade, variant)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (e.get("session"), e["exercise"], e["lang"], e["mode"], e["finished"],
                     e["seconds"], e["target"], e["runs"], e["hinted"], e["outcome"], e["grade"],
                     e.get("variant", 0)),
                )
            self.db.executemany(
                "INSERT INTO cards (exercise, lang, box, due, best) VALUES (?, ?, ?, ?, ?)",
                [(c.exercise, c.lang, c.box, c.due, c.best) for c in cards.values()],
            )
        self.set_meta("signature", self.signature())

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

    def passed(self) -> set[str]:
        """The exercises solved at least once, in any language."""
        rows = self.db.execute("SELECT DISTINCT exercise FROM attempts WHERE outcome = 'pass'")
        return {r["exercise"] for r in rows}

    def attempts(self) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM attempts ORDER BY finished").fetchall()

    def record_estimate(
        self, exercise: str, lang: str, guess: str, measured: list[str], slope: float
    ) -> None:
        """Store a complexity estimate and what the measurement found."""
        entry = {"type": "estimate", "finished": time.time(), "exercise": exercise, "lang": lang,
                 "guess": guess, "measured": measured, "slope": slope, "correct": guess in measured}
        with self.db:
            self.db.execute(
                "INSERT INTO estimates (finished, exercise, lang, guess, measured, slope, correct)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (entry["finished"], exercise, lang, guess, ",".join(measured), slope,
                 entry["correct"]),
            )
        self.append(entry)

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
        attempt = {
            "type": "attempt", "session": f"{machine()}/{session}", "exercise": exercise,
            "lang": lang, "mode": mode, "finished": time.time(), "seconds": seconds,
            "target": target, "runs": runs, "hinted": hinted,
            "outcome": "skip" if skipped else "pass",
            "grade": grade(seconds, target, hinted, skipped), "variant": variant,
        }
        updated = advance(self.card(exercise, lang), exercise, lang, attempt)
        with self.db:
            self.db.execute(
                "INSERT INTO attempts (session, exercise, lang, mode, finished, seconds, target,"
                " runs, hinted, outcome, grade, variant) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (session, exercise, lang, mode, attempt["finished"], seconds, target, runs, hinted,
                 attempt["outcome"], attempt["grade"], variant),
            )
            self.db.execute(
                "INSERT INTO cards (exercise, lang, box, due, best) VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (exercise, lang) DO UPDATE"
                " SET box = excluded.box, due = excluded.due, best = excluded.best",
                (exercise, lang, updated.box, updated.due, updated.best),
            )
        self.append(attempt)
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
