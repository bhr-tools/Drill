"""Learn courses: the steps in order, each unlocked once the one before is solved, and the
steps already solved coming back for review."""

from __future__ import annotations

import random
import textwrap
import time

from .exercises import Exercise
from .library import Collection
from .store import Store, pick

REVIEW_SHARE = 1 / 3  # at most this share of a session goes to reviews while steps remain


def demote(markdown: str) -> str:
    """Headings two levels down, under the chapter's and the step's, code blocks aside."""
    lines, fence = [], None
    for line in markdown.splitlines():
        mark = line.lstrip()[:3]
        if mark in ("```", "~~~") and fence in (None, mark):
            fence = None if fence else mark
        elif fence is None and line.startswith("#"):
            line = "##" + line
        lines.append(line)
    return "\n".join(lines)


class Course:
    def __init__(self, collection: Collection, store: Store):
        self.steps = collection.exercises
        self.index = {ex.id: i for i, ex in enumerate(self.steps)}
        self.store = store
        self.served = self.reviews = 0

    def next_step(self, done: set[str], available: set[str]) -> Exercise | None:
        return next((ex for ex in self.steps if ex.id not in done and ex.id in available), None)

    def progress(self) -> tuple[int, int]:
        """Steps done, and steps in all."""
        done = self.store.passed()
        return sum(ex.id in done for ex in self.steps), len(self.steps)

    def is_new(self, ex: Exercise) -> bool:
        return ex.id not in self.store.passed()

    def reached(self) -> list[Exercise]:
        """The steps done, and the next one: the lessons there is to read again."""
        done = self.store.passed()
        upto = next((i for i, ex in enumerate(self.steps) if ex.id not in done), len(self.steps) - 1)
        return self.steps[: upto + 1]

    def lesson_for(self, ex: Exercise) -> Exercise | None:
        """The step whose lesson `ex` practises: its own, or the last one before it."""
        before = self.steps[: self.index.get(ex.id, -1) + 1]
        return next((step for step in reversed(before) if step.lesson), None)

    def notes(self, steps: list[Exercise] | None = None) -> str:
        """The lessons of `steps` (the steps reached by default) as one Markdown document,
        a heading per chapter and per lesson."""
        lines, chapter = [], None
        for ex in self.reached() if steps is None else steps:
            if not ex.lesson:
                continue
            if ex.chapter and ex.chapter != chapter:
                chapter = ex.chapter
                lines += [f"# {chapter}", ""]
            lines += [f"## Step {self.index[ex.id] + 1} · {ex.title}", "",
                      demote(textwrap.dedent(ex.lesson).strip()), ""]
        return "\n".join(lines)

    def label(self, ex: Exercise) -> str:
        position = f"step {self.index[ex.id] + 1}/{len(self.steps)}"
        kind = "review" if not self.is_new(ex) else "new step"
        return " · ".join(filter(None, [ex.chapter, position, kind]))

    def pick(self, pool, cards, recent, rng=random):
        """Reviews that are due, up to REVIEW_SHARE of the session, else the next step."""
        done = self.store.passed()
        step = self.next_step(done, {p[0].id for p in pool})
        now = time.time()
        reviews = [
            p for p in pool
            if p[0].id in done and p[0].id not in recent
            and (card := cards.get((p[0].id, p[1].key))) and card.due <= now
        ]
        self.served += 1
        if reviews and (step is None or self.reviews < REVIEW_SHARE * self.served):
            self.reviews += 1
            return min(reviews, key=lambda p: (cards[p[0].id, p[1].key].due, rng.random()))
        if step is not None:
            return next(p for p in pool if p[0].id == step.id)
        # The course is done: practise it like a pack
        return pick(pool, cards, recent, rng)
