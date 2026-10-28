"""The library: the folder, a git repository of its own, that holds every exercise.

    drill/<theme>/<id>.toml   the base: one exercise per file, practised for good
    pack/<slug>.toml          packs: exercises aimed at one goal (a course, an exam)
    learn/<slug>.toml         learn courses: lessons and exercises, in order

Its location comes from $DRILL_LIBRARY, which must be set.
"""

from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass
from datetime import date
from functools import cached_property
from pathlib import Path

from .exercises import MODES, Exercise, ExerciseError, load, parse

KINDS = ("pack", "learn")  # the kinds of collections, each in the folder of its name
SLUG = re.compile(r"[^a-z0-9]+")


class LibraryError(Exception):
    pass


def root() -> Path:
    value = os.environ.get("DRILL_LIBRARY")
    if not value:
        raise LibraryError(
            "DRILL_LIBRARY is not set. Point it to your exercise library, a folder with "
            "drill/, pack/ and learn/ in it:\n  export DRILL_LIBRARY=~/Dev/Drill-library"
        )
    path = Path(value).expanduser()
    if not path.is_dir():
        raise LibraryError(f"DRILL_LIBRARY is {value}, which is not a folder.")
    return path


def slugify(text: str) -> str:
    return SLUG.sub("-", text.lower()).strip("-") or "collection"


def theme(ex: Exercise) -> str:
    """The drill/ folder of an exercise: its language if it has only one, else shared."""
    from .langs import LANGUAGES

    langs = [key for key in LANGUAGES if any(i.supports(key) for i in ex.instances)]
    return langs[0] if len(langs) == 1 else "shared"


@dataclass
class Collection:
    kind: str  # pack or learn
    slug: str
    name: str
    description: str
    locale: str | None
    deadline: date | None
    path: Path
    exercises: list[Exercise]
    errors: list[str]  # exercises that could not be read

    def counts(self) -> str:
        per_mode = [(mode, sum(ex.mode == mode for ex in self.exercises)) for mode in MODES]
        return " · ".join(f"{mode} {n}" for mode, n in per_mode if n)

    def langs(self) -> list[str]:
        from .langs import LANGUAGES

        return [key for key in LANGUAGES if any(ex.supports(key) for ex in self.exercises)]

    def days_left(self) -> int | None:
        return (self.deadline - date.today()).days if self.deadline else None


def parse_collection(text: str, path: Path, slug: str | None = None) -> Collection:
    """A pack or learn course from its TOML text. Exercises that fail to parse are
    reported in Collection.errors; a file that cannot be read raises ExerciseError."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ExerciseError(f"{path.name} is not valid TOML: {e}") from None
    kinds = [kind for kind in KINDS if kind in data]
    if len(kinds) != 1:
        raise ExerciseError(f"{path.name} needs one [pack] or [learn] table at the top")
    kind = kinds[0]
    meta = data[kind]
    slug = slug or slugify(meta.get("name", path.stem))
    deadline = meta.get("deadline")
    if isinstance(deadline, str):
        try:
            deadline = date.fromisoformat(deadline)
        except ValueError:
            raise ExerciseError(f"deadline {deadline!r} is not a YYYY-MM-DD date") from None
    exercises, errors, seen = [], [], set()
    chapter = None
    for index, entry in enumerate(data.get("exercises", []), 1):
        local = entry.get("id", f"exercise-{index}")
        if local in seen:
            errors.append(f"{local}: duplicate id")
            continue
        seen.add(local)
        # A chapter goes on until the next one starts
        chapter = entry.setdefault("chapter", chapter) if kind == "learn" else None
        try:
            exercises.append(parse(entry, f"{slug}:{local}", None, pack=slug, origin=kind))
        except (KeyError, ExerciseError) as e:
            detail = f"missing key {e}" if isinstance(e, KeyError) else str(e)
            errors.append(f"{local}: {detail}")
    if not exercises and not errors:
        errors.append("no [[exercises]] found")
    return Collection(
        kind, slug, meta.get("name", slug), meta.get("description", ""), meta.get("locale"),
        deadline, path, exercises, errors,
    )


class Library:
    def __init__(self, path: Path | None = None):
        self.root = path or root()
        self.errors: list[str] = []  # files that could not be read
        self.paths: dict[str, Path] = {}  # file of each exercise of the base

    @cached_property
    def drill(self) -> list[Exercise]:
        """The base, sorted by mode then id."""
        found: dict[str, Exercise] = {}
        for path in sorted((self.root / "drill").rglob("*.toml")):
            try:
                exercise = load(path)
            except ExerciseError as e:
                self.errors.append(str(e))
                continue
            if exercise.id in found:
                self.errors.append(f"{path}: id {exercise.id} is also in {self.paths[exercise.id]}")
                continue
            found[exercise.id] = exercise
            self.paths[exercise.id] = path
        return sorted(found.values(), key=lambda e: (MODES.index(e.mode), e.id))

    @cached_property
    def collections(self) -> list[Collection]:
        found = []
        for kind in KINDS:
            for path in sorted((self.root / kind).glob("*.toml")):
                try:
                    found.append(parse_collection(path.read_text(), path, path.stem))
                except ExerciseError as e:
                    self.errors.append(str(e))
        return found

    def of_kind(self, kind: str) -> list[Collection]:
        return [c for c in self.collections if c.kind == kind]

    def exercises(self) -> list[Exercise]:
        """The base, then every pack and course."""
        return [*self.drill, *(ex for c in self.collections for ex in c.exercises)]

    def collection(self, name: str, kind: str | None = None) -> Collection | None:
        """A collection by slug, by name, or by a part of either that only one has."""
        options = [c for c in self.collections if kind in (None, c.kind)]
        for c in options:
            if name in (c.slug, c.name):
                return c
        matches = [c for c in options if name.lower() in c.slug or name.lower() in c.name.lower()]
        return matches[0] if len(matches) == 1 else None

    def warn(self) -> None:
        for error in self.errors:
            print(f"drill: skipping {error}", file=sys.stderr)
