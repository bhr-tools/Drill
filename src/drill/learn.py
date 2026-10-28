"""Learn courses: the steps in order, each unlocked once the one before is solved, and the
steps already solved coming back for review."""

from __future__ import annotations

import random
import time

from .exercises import Exercise
from .library import Collection
from .store import Store, pick

REVIEW_SHARE = 1 / 3  # at most this share of a session goes to reviews while steps remain


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
