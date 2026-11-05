"""Answer drills, typed in the terminal instead of coded: probability problems and mental
arithmetic.

    proba/<theme>.toml   probability problems, a [[problems]] table each

A probability problem is scheduled like an exercise (Leitner boxes, language "proba").
Once answered or skipped, its worked solution is shown, with the trick when there is one,
so that a long calculation that had a shortcut does not go unnoticed.

Mental arithmetic tests are generated: an Optiver-style test (80 questions in 8 minutes,
decimals and fractions) or a Zetamac-style sprint (integers, 2 minutes). Each test's
score is kept in the history, per category of question.
"""

from __future__ import annotations

import ast
import math
import operator
import random
import shutil
import textwrap
import time
import tomllib
from collections import deque
from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path

from . import term
from .session import Clock, grade_reason, level_note
from .store import Store, pick
from .term import bold, cyan, dim, fmt_time, green, red, spark, yellow

PROBA = "proba"  # the language key of probability attempts
DEFAULT_TOLERANCE = 1e-3  # relative, for an approximate answer to an exact one


class QuizError(Exception):
    pass


# ---------------------------------------------------------------------------
# Numbers typed by the user


_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow,
}
_NAMES = {"pi": math.pi, "π": math.pi, "e": math.e}
_FUNCS = {"sqrt": math.sqrt, "exp": math.exp, "ln": math.log, "log": math.log}


def _evaluate(node):
    """Fractions stay exact; pi, e, functions and fractional powers turn the result into a
    float."""
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Fraction(repr(node.value)) if isinstance(node.value, float) else Fraction(node.value)
    if isinstance(node, ast.Name) and node.id in _NAMES:
        return _NAMES[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _evaluate(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow) and not (
            isinstance(right, Fraction) and right.denominator == 1 and abs(right) <= 64
        ):
            return float(left) ** float(right)
        return _OPS[type(node.op)](left, right)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS and len(node.args) == 1 and not node.keywords):
        return _FUNCS[node.func.id](float(_evaluate(node.args[0])))
    raise ValueError("not a number")


def parse_number(text: str, expressions: bool = True) -> Fraction | float | None:
    """A typed answer: 6, -2.5, 0,375, 3/8, 37.5%, and with `expressions`, 1 - (5/6)^4,
    sqrt(2)/2 or pi/4. None when it is not one."""
    text = text.strip().replace("−", "-").replace("×", "*").replace("÷", "/").replace(" ", "")
    if not text:
        return None
    percent = text.endswith("%")
    if percent:
        text = text[:-1]
    if text.count(",") == 1 and "." not in text:
        text = text.replace(",", ".")  # a French decimal comma
    text = text.replace("^", "**")
    if not expressions:
        try:
            value = Fraction(text)
        except (ValueError, ZeroDivisionError):
            return None
    else:
        try:
            value = _evaluate(ast.parse(text, mode="eval"))
        except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
            return None
    return value / 100 if percent else value


def same(given, expected, tolerance: float = DEFAULT_TOLERANCE) -> bool:
    """An exact match, or an approximation within `tolerance` (relative)."""
    if isinstance(given, Fraction) and isinstance(expected, Fraction) and given == expected:
        return True
    g, x = float(given), float(expected)
    return abs(g - x) <= tolerance * max(abs(x), 1e-12)


def show_number(value) -> str:
    """A fraction as a decimal when it has a finite one, else a/b ≈ decimal."""
    if isinstance(value, float):
        return f"{value:.6g}"
    den = value.denominator
    while den % 2 == 0:
        den //= 2
    while den % 5 == 0:
        den //= 5
    if den == 1:
        with localcontext() as ctx:
            ctx.prec = 30
            text = format((Decimal(value.numerator) / Decimal(value.denominator)).normalize(), "f")
        return text.replace("-", "−")
    sign = "−" if value < 0 else ""
    return f"{sign}{abs(value.numerator)}/{value.denominator} ≈ {float(value):.4g}".replace("-", "−")


# ---------------------------------------------------------------------------
# Probability problems


@dataclass
class Problem:
    id: str
    title: str
    tags: tuple[str, ...]
    target: int  # seconds
    statement: str
    answer: Fraction | float
    answer_text: str
    tolerance: float
    hint: str | None
    solution: str
    trick: str | None
    theme: str  # the file it comes from
    # Variants ask the same idea with other numbers or another twist, so that the method is
    # learnt rather than the answer. They share the id, and so the schedule.
    variant: int = 0
    variants: tuple[Problem, ...] = ()  # on the problem itself only
    n_variants: int = 1  # on every instance

    @property
    def instances(self) -> tuple[Problem, ...]:
        return (self, *self.variants)

    def matches(self, query: str) -> bool:
        query = query.lower()
        return any(query in f.lower() for f in (self.id, self.title, self.theme, *self.tags))


def load_problems(root: Path) -> tuple[list[Problem], list[str]]:
    """Every problem of the library's proba/ folder, and the errors met reading it."""
    problems, errors, seen = [], [], {}
    for path in sorted((root / "proba").glob("*.toml")):
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as e:
            errors.append(f"{path.name}: not valid TOML: {e}")
            continue
        for index, entry in enumerate(data.get("problems", []), 1):
            try:
                problem = parse_problem(entry, path.stem)
            except (KeyError, QuizError) as e:
                detail = f"missing key {e}" if isinstance(e, KeyError) else str(e)
                errors.append(f"{path.name}, problem {index}: {detail}")
                continue
            if problem.id in seen:
                errors.append(f"{path.name}: id {problem.id} is also in {seen[problem.id]}")
                continue
            seen[problem.id] = path.name
            problems.append(problem)
    return problems, errors


def parse_problem(data: dict, theme: str) -> Problem:
    """A problem and its [[problems.variants]], each a table that replaces the keys it sets."""
    base = {k: v for k, v in data.items() if k != "variants"}
    problem = _parse_one(base, theme, 0)
    variants = []
    for number, overrides in enumerate(data.get("variants", ()), 1):
        if "id" in overrides:
            raise QuizError(f"variant {number + 1}: a variant shares its problem's id")
        try:
            variants.append(_parse_one({**base, **overrides}, theme, number))
        except QuizError as e:
            raise QuizError(f"variant {number + 1}: {e}") from None
    problem.variants = tuple(variants)
    for instance in problem.instances:
        instance.n_variants = len(problem.instances)
    return problem


def _parse_one(data: dict, theme: str, variant: int) -> Problem:
    answer = parse_number(str(data["answer"]))
    if answer is None:
        raise QuizError(f"answer {data['answer']!r} is not a number or an expression")
    return Problem(
        id=data["id"], title=data["title"], tags=tuple(data.get("tags", ())),
        target=int(data["target"]), statement=data["statement"], answer=answer,
        answer_text=str(data["answer"]), tolerance=float(data.get("tolerance", DEFAULT_TOLERANCE)),
        hint=data.get("hint"), solution=data["solution"], trick=data.get("trick"), theme=theme,
        variant=variant,
    )


@dataclass(frozen=True)
class _Key:
    """Stands for a language in store.pick, which schedules (item, language) pairs."""
    key: str = PROBA


def wrap(text: str, indent: str = "  ") -> list[str]:
    """Paragraphs wrapped to the terminal; lists, formulas and indented lines kept as is."""
    width = max(40, min(100, shutil.get_terminal_size().columns - len(indent) - 2))
    lines = []
    for paragraph in textwrap.dedent(text).strip().split("\n\n"):
        raw = paragraph.splitlines()
        if any(line.startswith(("-", " ", "*", "|")) for line in raw) or len(raw) > 1 and all(
            len(line) < 60 for line in raw
        ):
            lines += [indent + line for line in raw]
        else:
            lines += [indent + line for line in textwrap.wrap(" ".join(paragraph.split()), width)]
        lines.append("")
    return lines[:-1]


class ProbaSession:
    """Problems one at a time: answer in the terminal, then read the worked solution."""

    def __init__(self, problems: list[Problem], store: Store, minutes: float | None):
        self.problems = problems
        self.store = store
        self.minutes = minutes
        self.n_solved = 0
        self.name = "proba"

    def run(self) -> None:
        session = self.store.start_session(PROBA, [PROBA])
        started = time.monotonic()
        recent: deque[str] = deque(maxlen=min(3, max(0, len(self.problems) - 1)))
        pool = [(p, _Key()) for p in self.problems]
        tried = 0
        try:
            while True:
                if self.minutes and time.monotonic() - started >= self.minutes * 60:
                    term.say(cyan(f"{self.minutes:g} minutes are up."))
                    break
                chosen = pick(pool, self.store.cards(), set(recent))
                if chosen is None:
                    term.say(cyan("Nothing left to review today: every problem is up to date."))
                    break
                problem, _ = chosen
                recent.append(problem.id)
                if not self.ask(session, self.instance(problem)):
                    break
                tried += 1
        except (KeyboardInterrupt, EOFError):
            print()
        finally:
            self.store.end_session(session)
        elapsed = time.monotonic() - started
        print(bold(f"\n{self.n_solved}/{tried} solved in {fmt_time(elapsed)}."))

    def instance(self, problem: Problem) -> Problem:
        """The variant practised least recently (never practised first)."""
        if problem.n_variants == 1:
            return problem
        seen = self.store.variants_seen(problem.id, PROBA)
        return min(problem.instances,
                   key=lambda p: (seen.get(p.variant, float("-inf")), random.random()))

    def ask(self, session: int, problem: Problem) -> bool:
        """One problem. False when the user quits."""
        term.clear()
        card = self.store.card(problem.id, PROBA)
        level = f"level {card.box}" if card else "new"
        variant = (f"  ·  variant {problem.variant + 1}/{problem.n_variants}"
                   if problem.n_variants > 1 else "")
        print(bold(problem.title) + dim(f"  ·  {problem.theme}  ·  target {fmt_time(problem.target)}"
                                        f"  ·  {level}{variant}"))
        print()
        print("\n".join(wrap(problem.statement, "")))
        print()
        print(dim("Answer with a number, a fraction (1/3), a percentage (37.5%) or an expression "
                  "(1-(5/6)^4, pi/4).\nh hint · s skip and see the solution · p pause · q quit"))
        clock = Clock()
        hinted = skipped = False
        wrong = 0
        while True:
            text = input(cyan("> ")).strip()
            command = text.lower()
            if command == "q":
                return False
            if command == "h":
                print(yellow(f"Hint: {problem.hint}") if problem.hint else dim("No hint for this one."))
                hinted = hinted or bool(problem.hint)
                continue
            if command == "p":
                clock.pause()
                input(dim("Paused. Enter to go on."))
                clock.resume()
                continue
            if command == "s":
                skipped = True
                break
            value = parse_number(text)
            if value is None:
                print(dim("Not a number. Type h, s, p or q, or an answer."))
                continue
            if same(value, problem.answer, problem.tolerance):
                break
            wrong += 1
            print(red("✗ Not that.") + dim(" Try again, h for a hint, s for the solution."))
        seconds = clock.elapsed()
        # A wrong answer weighs like a hint: the attempt can no longer be graded good
        before = card
        after = self.store.record(
            session, problem.id, PROBA, PROBA, seconds, problem.target, wrong + 1,
            hinted or wrong > 0, skipped, problem.variant,
        )
        print()
        if skipped:
            print(yellow(f"Answer: {show_number(problem.answer)}"))
        else:
            self.n_solved += 1
            tries = f", {wrong} wrong answer{'s' * (wrong > 1)} first" if wrong else ""
            print(green(f"✓ {show_number(problem.answer)} in {fmt_time(seconds)}") +
                  dim(f" (target {fmt_time(problem.target)}{tries})"))
        reason = "Wrong answer first" if wrong and not skipped and not hinted else grade_reason(
            seconds, problem.target, hinted or wrong > 0, skipped)
        print(dim(level_note(before, after, reason)))
        print()
        print(cyan("Solution"))
        print("\n".join(wrap(problem.solution)))
        if problem.trick:
            print()
            print(cyan("Trick"))
            print("\n".join(wrap(problem.trick)))
        print()
        answer = input(dim("Enter for the next problem, q to quit. ")).strip().lower()
        return answer != "q"


def list_problems(problems: list[Problem], store: Store) -> None:
    cards = store.cards()
    now = time.time()
    by_theme: dict[str, list[Problem]] = {}
    for p in problems:
        by_theme.setdefault(p.theme, []).append(p)
    for theme, items in by_theme.items():
        print(bold(theme))
        for p in items:
            card = cards.get((p.id, PROBA))
            if card is None:
                state = dim("new")
            else:
                due = "due" if card.due <= now else f"in {term.ago(card.due - now)}"
                state = f"level {card.box} · {due}"
            count = f"×{p.n_variants}" if p.n_variants > 1 else ""
            print(f"  {p.id:32} {p.title:44} {count:>3}  {state}")
    total = sum(p.n_variants for p in problems)
    print(dim(f"\n{len(problems)} problems, {total} with their variants (×N, served in turn). "
              "`drill proba <theme|tag|id>` practises some of them."))


# ---------------------------------------------------------------------------
# Mental arithmetic


@dataclass
class Question:
    text: str
    answer: Fraction
    category: str  # add, mul, div, dec, frac, pct
    pattern: str = ""  # a trick that applies, for the tips: near-square, x11, x25…


def _f(x) -> Fraction:
    return Fraction(x)


def _dec(x: Fraction) -> str:
    return show_number(x).split(" ")[0]


def _frac(x: Fraction) -> str:
    return f"{x.numerator}/{x.denominator}"


def q_add(rng: random.Random, decimals: bool) -> Question:
    if decimals and rng.random() < 0.5:
        a = _f(rng.randint(100, 999)) / 10
        b = _f(rng.randint(10, 999)) / (10 if rng.random() < 0.7 else 100)
    else:
        a, b = _f(rng.randint(12, 999)), _f(rng.randint(12, 999))
    if rng.random() < 0.5:
        return Question(f"{_dec(a)} + {_dec(b)}", a + b, "add")
    a, b = max(a, b), min(a, b)
    if rng.random() < 0.25:
        a, b = b, a  # a negative result
    return Question(f"{_dec(a)} − {_dec(b)}", a - b, "add")


def q_mul(rng: random.Random, hard: bool) -> Question:
    roll = rng.random()
    if roll < 0.2:
        m, d = rng.randint(2, 9) * 10 + rng.choice((0, 5)) * (rng.random() < 0.3), rng.randint(1, 4)
        a, b = m - d, m + d
        return Question(f"{a} × {b}", _f(a * b), "mul", "near-square")
    if roll < 0.3:
        a = rng.randint(11, 99)
        return Question(f"{a} × {a}" if rng.random() < 0.5 else f"{a}²", _f(a * a), "mul", "square")
    if roll < 0.4:
        a = rng.randint(12, 98)
        b = rng.choice((11, 101, 9, 99, 999 if hard else 99))
        return Question(f"{a} × {b}", _f(a * b), "mul", f"x{b}")
    if roll < 0.5:
        a = rng.randint(3, 99) * rng.choice((1, 2, 4))
        b = rng.choice((5, 25, 50, 125))
        return Question(f"{a} × {b}", _f(a * b), "mul", f"x{b}")
    if hard or roll < 0.75:
        a, b = rng.randint(12, 99), rng.randint(12, 99)
    else:
        a, b = rng.randint(12, 999), rng.randint(3, 9)
    return Question(f"{a} × {b}", _f(a * b), "mul", "split")


def q_div(rng: random.Random) -> Question:
    d = rng.choice((3, 4, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16, 17, 18, 19, 24, 25))
    q = rng.randint(4, 99)
    return Question(f"{d * q} ÷ {d}", _f(q), "div", "x25" if d == 25 else "")


def q_dec(rng: random.Random) -> Question:
    roll = rng.random()
    if roll < 0.35:
        factor = rng.choice(("0.5", "0.25", "0.125", "0.2", "0.4", "0.75", "1.5", "2.5", "0.05",
                             "0.04", "0.15", "1.25"))
        f = Fraction(factor)
        base = rng.randint(2, 99) * f.denominator * rng.choice((1, 1, 2))
        if rng.random() < 0.3:
            base = Fraction(base, 10)
        return Question(f"{_dec(base)} × {factor}", base * f, "dec", "dec-factor")
    if roll < 0.65:
        a = _f(rng.randint(11, 99)) / 10
        b = _f(rng.randint(2, 99)) / rng.choice((1, 10))
        return Question(f"{_dec(a)} × {_dec(b)}", a * b, "dec", "dec-shift")
    divisor = _f(rng.randint(2, 19)) / rng.choice((10, 100))
    result = _f(rng.randint(2, 90)) / rng.choice((1, 1, 10))
    return Question(f"{_dec(divisor * result)} ÷ {_dec(divisor)}", result, "dec", "dec-div")


def q_frac(rng: random.Random) -> Question:
    roll = rng.random()
    if roll < 0.4:
        n = rng.choice((3, 4, 5, 6, 8, 12, 16, 20, 25))
        k = rng.choice([k for k in range(1, n) if math.gcd(k, n) == 1])
        total = n * rng.randint(2, 40)
        return Question(f"{k}/{n} × {total}", Fraction(k, n) * total, "frac", "frac-of")
    if roll < 0.75:
        x, y = (Fraction(rng.randint(1, d - 1), d) for d in
                (rng.choice((2, 3, 4, 5, 6, 8)), rng.choice((2, 3, 4, 5, 6, 8, 10, 12))))
        if rng.random() < 0.5:
            return Question(f"{_frac(x)} + {_frac(y)}", x + y, "frac", "frac-sum")
        return Question(f"{_frac(x)} × {_frac(y)}", x * y, "frac", "frac-sum")
    d = rng.choice((8, 16, 20, 25, 40, 5, 4))
    k = rng.choice([k for k in range(1, d) if math.gcd(k, d) == 1])
    return Question(f"{k}/{d} in decimal", Fraction(k, d), "frac", "frac-dec")


def q_pct(rng: random.Random) -> Question:
    p = Fraction(rng.choice(("5", "10", "12.5", "15", "20", "25", "30", "35", "40", "60", "75",
                             "2.5", "1.5", "120", "7.5", "45")))
    base = rng.randint(2, 99) * 20
    return Question(f"{_dec(p)}% of {base}", p / 100 * base, "pct", "pct")


def zetamac(rng: random.Random) -> Question:
    """Zetamac's defaults: add 2–100, multiply 2–12 by 2–100, and their reverses."""
    kind = rng.randrange(4)
    a, b = rng.randint(2, 100), rng.randint(2, 100)
    if kind == 0:
        return Question(f"{a} + {b}", _f(a + b), "add")
    if kind == 1:
        return Question(f"{a + b} − {a}", _f(b), "add")
    c = rng.randint(2, 12)
    if kind == 2:
        return Question(f"{c} × {b}", _f(c * b), "mul")
    return Question(f"{c * b} ÷ {c}", _f(b), "div")


GENERATORS = {
    "add": lambda rng: q_add(rng, decimals=True),
    "mul": lambda rng: q_mul(rng, hard=rng.random() < 0.3),
    "div": q_div,
    "dec": q_dec,
    "frac": q_frac,
    "pct": q_pct,
}
CATEGORIES = tuple(GENERATORS)
# The Optiver mix: decimals and fractions as much as integers
WEIGHTS = {"add": 2, "mul": 3, "div": 1, "dec": 3, "frac": 2, "pct": 1}


@dataclass(frozen=True)
class Preset:
    name: str
    count: int | None  # None: as many as time allows
    minutes: float
    about: str


PRESETS = {
    "optiver": Preset("optiver", 80, 8, "80 questions in 8 minutes: integers, decimals, "
                                        "fractions and percentages, as in Optiver's test"),
    "zetamac": Preset("zetamac", None, 2, "2 minutes of integer arithmetic, Zetamac's defaults"),
}

TIPS = {
    "near-square": "(a−b)(a+b) = a² − b²: 27 × 33 = 30² − 3² = 891.",
    "square": "Square from the nearest ten: 47² = 50² − 2·50·3 + 9 = 2209; or (a−d)(a+d) + d².",
    "x11": "×11 = ×10 + itself: 47 × 11 = 470 + 47 = 517 (write the digit sum in the middle).",
    "x101": "×101: 47 × 101 = 4700 + 47 = 4747.",
    "x9": "×9 = ×10 − itself: 47 × 9 = 470 − 47 = 423.",
    "x99": "×99 = ×100 − itself: 47 × 99 = 4700 − 47 = 4653.",
    "x999": "×999 = ×1000 − itself.",
    "x5": "×5 = ×10 ÷ 2.",
    "x25": "×25 = ×100 ÷ 4, and ÷25 = ÷100 × 4.",
    "x50": "×50 = ×100 ÷ 2.",
    "x125": "×125 = ×1000 ÷ 8.",
    "split": "Split the smaller factor: 67 × 8 = 60×8 + 7×8; for 2 digits, 34 × 67 = 34×70 − 34×3.",
    "dec-factor": "Know the decimal as a fraction: 0.125 = 1/8, 0.75 = 3/4, 0.04 = 1/25, "
                  "1.25 = 5/4.",
    "dec-shift": "Multiply the integers, then place the point: 4.7 × 3.2 → 47 × 32 = 1504 → 15.04.",
    "dec-div": "Shift the point in both: 3.6 ÷ 0.12 = 360 ÷ 12 = 30.",
    "frac-of": "Divide first, then multiply: 3/8 of 96 = 96 ÷ 8 × 3 = 36.",
    "frac-sum": "Common denominator = lcm; for a product, simplify across before multiplying.",
    "frac-dec": "Know the eighths (0.125 steps), sixteenths (0.0625) and twentieths (0.05).",
    "pct": "x% of y = y% of x; 15% = 10% + half of it; 12.5% = 1/8.",
}


def tip(q: Question) -> str | None:
    return TIPS.get(q.pattern)


class MentalSession:
    """A timed arithmetic test, answered line by line."""

    def __init__(self, store: Store, preset: Preset, count: int | None, minutes: float,
                 only: list[str] | None, negative: bool, seed: int | None = None):
        self.store = store
        self.preset = preset
        self.count = count
        self.minutes = minutes
        self.only = only
        self.negative = negative
        self.rng = random.Random(seed)
        self.n_solved = 0
        # Only a test in the preset's own conditions counts in its history
        standard = (count, minutes, only) == (preset.count, preset.minutes, None)
        self.key = preset.name if standard else "+".join(
            [preset.name, *(only or []), *([f"{count}q"] if count else []), f"{minutes:g}min"]
        )
        self.name = f"mental:{self.key}"

    def question(self) -> Question:
        if self.preset.name == "zetamac" and not self.only:
            return zetamac(self.rng)
        cats = self.only or list(CATEGORIES)
        weights = [WEIGHTS[c] for c in cats]
        return GENERATORS[self.rng.choices(cats, weights)[0]](self.rng)

    def run(self) -> None:
        term.clear()
        label = self.only and ", ".join(self.only) or self.preset.about
        total = f"{self.count} questions in " if self.count else ""
        print(bold(f"Mental arithmetic · {self.preset.name}") +
              dim(f"  ·  {total}{self.minutes:g} min  ·  {label}"))
        print(dim("Type the answer and Enter (decimals, or a fraction like 7/12). "
                  "Enter alone skips. q quits."))
        input(dim("Enter to start the clock. "))
        start = time.monotonic()
        deadline = start + self.minutes * 60
        done: list[tuple[Question, str, float]] = []  # question, right|wrong|skip, seconds
        stopped = False
        try:
            while self.count is None or len(done) < self.count:
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                q = self.question()
                n = f"{len(done) + 1}/{self.count}" if self.count else f"{len(done) + 1}"
                asked = time.monotonic()
                text = input(f"{dim(f'[{n} · {fmt_time(left)}]')} {q.text} = ").strip()
                took = time.monotonic() - asked
                if time.monotonic() > deadline:
                    break  # answered after the bell: not counted
                if text.lower() == "q":
                    stopped = True
                    break
                if not text:
                    done.append((q, "skip", took))
                    continue
                value = parse_number(text, expressions=False)
                if value is not None and same(value, q.answer, 1e-9 if q.category != "frac"
                                              else DEFAULT_TOLERANCE):
                    done.append((q, "right", took))
                else:
                    done.append((q, "wrong", took))
                    print(red(f"  ✗ {show_number(q.answer)}"))
        except (KeyboardInterrupt, EOFError):
            print()
            stopped = True
        elapsed = min(time.monotonic(), deadline) - start
        self.report(done, elapsed, stopped)

    def report(self, done, elapsed: float, stopped: bool) -> None:
        right = sum(r == "right" for _, r, _ in done)
        wrong = sum(r == "wrong" for _, r, _ in done)
        self.n_solved = right
        print()
        if not done:
            print("No answer, nothing recorded.")
            return
        score = right - wrong if self.negative else right
        rate = right / max(elapsed, 1) * 60
        total = f"/{self.count}" if self.count else ""
        print(bold(f"{right}{total} right") + f", {wrong} wrong, "
              f"{sum(r == 'skip' for _, r, _ in done)} skipped in {fmt_time(elapsed)}"
              + dim(f"  ·  {rate:.1f} right per minute"))
        if self.negative:
            print(f"Score with −1 per wrong answer: {bold(str(score))}")
        detail: dict[str, list] = {}
        for q, result, took in done:
            entry = detail.setdefault(q.category, [0, 0, 0.0])
            entry[0] += 1
            entry[1] += result == "right"
            entry[2] += took
        print()
        print(bold("By category") + dim("  right/asked · seconds per question"))
        for cat, (asked, ok, seconds) in sorted(detail.items(), key=lambda kv: -kv[1][2] / kv[1][0]):
            colour = green if ok == asked else yellow if ok >= asked * 0.8 else red
            print(f"  {cat:6} {colour(f'{ok}/{asked}'):>16}   {seconds / asked:5.1f} s")
        slow = sorted(done, key=lambda d: -d[2])[:5]
        tips = []
        for q, result, took in slow:
            hint = tip(q)
            mark = {"right": green("✓"), "wrong": red("✗"), "skip": dim("·")}[result]
            print(f"  {mark} {q.text} = {show_number(q.answer)}" + dim(f"   {took:.1f} s"))
            if hint and hint not in tips:
                tips.append(hint)
        if tips:
            print()
            print(cyan("Tricks for the slowest ones"))
            for hint in tips:
                print(f"  - {hint}")
        if stopped and (self.count and len(done) < self.count):
            print(dim("\nStopped early: not recorded."))
            return
        self.store.record_mental(self.key, len(done), right, wrong, elapsed, detail)
        history = [r["correct"] for r in self.store.mentals(self.key)][-12:]
        if len(history) > 1:
            print()
            print(dim(f"Your last {len(history)} {self.key} tests: ") +
                  spark(history) + dim(f"  best {max(history)}, now {history[-1]}"))


def mental_stats(store: Store) -> None:
    rows = store.mentals()
    if not rows:
        return
    print(bold("Mental arithmetic"))
    for preset in sorted({r["preset"] for r in rows}):
        scores = [r["correct"] for r in rows if r["preset"] == preset]
        print(f"  {preset:18} {len(scores):>3} tests   best {max(scores):>3}   "
              f"last {scores[-1]:>3}   {spark(scores[-20:])}")
    print()
