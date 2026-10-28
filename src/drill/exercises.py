"""The exercise bank: TOML files describing a statement, a signature and tests."""

from __future__ import annotations

import copy
import json
import random
import re
import textwrap
import tomllib
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .complexity import CLASSES, canonical
from .term import fmt_time

MODES = ("sprint", "normal", "hard", "optim")
DEFAULT_LIMIT = 2.0  # seconds allowed for a performance test
SCALE_LIMIT = 1.5  # seconds allowed for one size of a complexity measurement
SCALE_SIZES = tuple(1000 * 2**k for k in range(9))  # 1 000 to 256 000
BASE_TYPES = ("int", "long", "bool", "str", "any")
# Languages that serve function exercises written without them in mind. The others
# (OCaml, Nix) only get exercises that have a solution in them, written for them.
GENERAL_LANGS = ("python", "cpp", "java")
ANY_LANGS = ("python", "nix")  # languages with a dynamic type for `any` (any JSON value)
# Keys tied to a signature: a variant that changes the signature does not inherit them
SIGNATURE_KEYS = ("tests", "solutions", "starter", "perf", "scale", "complexity", "examples")
SIGNATURE = re.compile(r"^\s*(\w+)\s*\((.*)\)\s*->\s*(.+?)\s*$")


class ExerciseError(Exception):
    pass


def parse_type(spec: str):
    """Parse a type such as `list[list[int]]` into "int" or ("list", "int") form."""
    spec = spec.replace(" ", "")
    if spec.startswith("list[") and spec.endswith("]"):
        return ("list", parse_type(spec[5:-1]))
    if spec in BASE_TYPES:
        return spec
    raise ExerciseError(f"unknown type {spec!r} (use {', '.join(BASE_TYPES)} or list[...])")


def parse_signature(text: str):
    match = SIGNATURE.match(text)
    if not match:
        raise ExerciseError(f"bad signature {text!r}, expected `name(arg: type, ...) -> type`")
    name, params, returns = match.groups()
    parsed = []
    for part in filter(None, (p.strip() for p in params.split(","))):
        pname, _, ptype = part.partition(":")
        parsed.append((pname.strip(), parse_type(ptype)))
    return name, tuple(parsed), parse_type(returns)


def placeholder(t):
    """A value of type t, standing for an expected output that is not checked."""
    if isinstance(t, tuple):
        return []
    return {"str": "", "bool": False, "any": None}.get(t, 0)


def uses_any(t) -> bool:
    return uses_any(t[1]) if isinstance(t, tuple) else t == "any"


def relative_file(name: str) -> str:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ExerciseError(f"{name!r} must be a relative path inside the exercise folder")
    return name


def _generate(spec: dict, seed: str, **names):
    """Arguments from a spec's Python `in` expression or `code` block (which sets `args`)."""
    # Seeded by the exercise, so the data is the same on every run and every machine
    scope = {"rng": random.Random(seed), **names}
    if "code" in spec:
        exec(spec["code"], scope)
        return scope["args"]
    return eval(spec["in"], scope)


@dataclass
class Exercise:
    id: str
    title: str
    mode: str
    tags: tuple[str, ...]
    target: int  # seconds
    statement: str
    hint: str | None
    solutions: dict[str, str]
    langs: tuple[str, ...] | None  # None: every language
    # "function": one signature and data tests, shared by every language.
    # "code": a starter and tests written in each language, for what a signature
    # cannot express (classes, generators, templates, iterators…).
    kind: str = "function"
    name: str = ""  # function name, snake_case
    params: tuple[tuple[str, object], ...] = ()
    returns: object = None
    tests: tuple[dict, ...] = ()
    examples: int = 2  # how many tests are shown in the statement
    perf: tuple[dict, ...] = ()  # performance test specs, generated on demand
    # Starting code per language. Required for "code" exercises; for function ones it
    # replaces the empty skeleton (optim exercises start from a slow solution).
    starters: dict[str, str] = field(default_factory=dict)
    checks: dict[str, str] = field(default_factory=dict)  # "code" kind only
    setup: dict[str, str] = field(default_factory=dict)  # "code" kind: file-level test helpers
    complexity: str | None = None  # the optimal complexity, in the notation of complexity.py
    scale: dict | None = None  # how to build an input of size n, to measure complexity
    explanation: str | None = None  # the theory, shown with the reference solution
    pack: str | None = None  # the slug of the pack or learn course it comes from, if any
    origin: str = "drill"  # drill (the base), pack or learn
    # learn courses: the chapter, and the lesson read before the exercise
    chapter: str | None = None
    lesson: str | None = None
    # "code" kind: the file the student edits, instead of the language's solution file
    # (flake.nix, module.nix…), and files written next to it (a project to package…)
    file: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    # Variants practise the same concept on other data or with another twist, so that
    # the concept is learnt rather than one answer. They share the id, and so the
    # schedule; `variant` numbers them from 0, the exercise itself.
    variant: int = 0
    variants: tuple[Exercise, ...] = ()
    n_variants: int = 1

    @property
    def key(self) -> str:
        """Tells variants apart, where `id` does not."""
        return f"{self.id}~{self.variant}" if self.variant else self.id

    @property
    def instances(self) -> tuple[Exercise, ...]:
        return (self, *self.variants)

    def supports(self, lang: str) -> bool:
        if self.kind == "code":
            return lang in self.checks
        if self.langs is not None and lang not in self.langs:
            return False
        if self.starters:
            return lang in self.starters
        types = [t for _, t in self.params] + [self.returns]
        if any(uses_any(t) for t in types) and lang not in ANY_LANGS:
            return False
        return lang in self.solutions if self.solutions else lang in GENERAL_LANGS

    def matches(self, query: str) -> bool:
        """Search by a mode, an origin (drill, pack, learn), or a part of the id, the title or
        a tag, ignoring case."""
        query = query.lower()
        if query in MODES:
            return self.mode == query
        if query in ("drill", "pack", "learn"):
            return self.origin == query
        fields = [self.id, self.title.lower(), *self.tags]
        return any(query in f for f in fields)

    def describe(self, lang) -> list[str]:
        """Statement lines for the top of the solution file, with `lang`'s syntax."""
        variant = f"  ·  variant {self.variant + 1}/{self.n_variants}" if self.n_variants > 1 else ""
        lines = [f"{self.title}  ·  {self.mode}  ·  target {fmt_time(self.target)}{variant}", ""]
        lines += textwrap.dedent(self.statement).strip().splitlines()
        if self.files:
            lines += ["", "Files given in this folder: " + ", ".join(sorted(self.files))]
        if self.tests:
            lines += ["", "Examples:"]
        for test in self.tests[: self.examples]:
            lines.append(f"  {lang.call(self, test)}  ->  {lang.literal(test['out'])}")
        if self.perf:
            lines += ["", "Performance:"]
            for spec in self.perf:
                lines.append(f"  {spec['label']}, in under {spec.get('limit', DEFAULT_LIMIT):g}s")
        if self.scale:
            lines += ["", f"Complexity: press c in drill to measure yours ({self.scale_label})."]
        return lines

    @property
    def scale_label(self) -> str:
        return self.scale.get("label", "n = size of the input") if self.scale else ""

    @cached_property
    def cases(self) -> list[dict]:
        """Every case a solution runs on: the listed tests, then the performance tests."""
        return [*self.tests, *(self._perf_case(i, spec) for i, spec in enumerate(self.perf))]

    @cached_property
    def scale_cases(self) -> list[dict]:
        """Inputs of growing size n, timed to measure a solution's complexity.

        Their outputs are not checked; each size gets SCALE_LIMIT seconds and the run
        stops at the first size over it.
        """
        sizes = self.scale.get("sizes", SCALE_SIZES)
        return [
            {
                "in": _generate(self.scale, f"{self.id}/scale/{n}", n=n),
                "out": placeholder(self.returns),
                "limit": self.scale.get("limit", SCALE_LIMIT),
                "repeat": True,
                "n": n,
            }
            for n in sizes
        ]

    def _perf_case(self, index: int, spec: dict) -> dict:
        args = _generate(spec, f"{self.id}/{index}")
        out = spec["out"] if "out" in spec else self._reference_output(args)
        return {"in": args, "out": out, "label": spec["label"], "limit": spec.get("limit", DEFAULT_LIMIT)}

    def _reference_output(self, args: list):
        code = self.solutions.get("python")
        if code is None:
            raise ExerciseError(f"{self.id}: a performance test needs `out` or a Python reference")
        scope: dict = {}
        exec(code, scope)
        return json.loads(json.dumps(scope[self.name](*copy.deepcopy(args))))


def parse(
    data: dict, id: str, mode: str | None, pack: str | None = None, origin: str = "drill"
) -> Exercise:
    """An exercise and its variants from TOML data. `mode` is the default when data has none.

    A variant is a table of [[variants]] that replaces any key it sets.
    """
    base = {k: v for k, v in data.items() if k != "variants"}
    exercise = _parse_one(base, id, mode, pack, origin)
    variants = []
    for number, overrides in enumerate(data.get("variants", ()), 1):
        merged = dict(base)
        if "signature" in overrides or "kind" in overrides:
            for key in SIGNATURE_KEYS:
                merged.pop(key, None)
        merged.update(overrides)
        try:
            variants.append(_parse_one(merged, id, mode, pack, origin, variant=number))
        except (KeyError, ExerciseError) as e:
            detail = f"missing key {e}" if isinstance(e, KeyError) else str(e)
            raise ExerciseError(f"variant {number + 1}: {detail}") from None
    exercise.variants = tuple(variants)
    for instance in exercise.instances:
        instance.n_variants = len(exercise.instances)
    return exercise


def _parse_one(
    data: dict, id: str, mode: str | None, pack: str | None, origin: str, variant: int = 0
) -> Exercise:
    mode = data.get("mode", mode)
    if mode not in MODES:
        raise ExerciseError(f"mode must be one of {', '.join(MODES)}, not {mode!r}")
    common = dict(
        id=id,
        title=data["title"],
        mode=mode,
        tags=tuple(data.get("tags", ())),
        target=int(data["target"]),
        statement=data["statement"],
        hint=data.get("hint"),
        solutions=data.get("solutions", {}),
        langs=tuple(data["langs"]) if "langs" in data else None,
        explanation=data.get("explanation"),
        pack=pack,
        origin=origin,
        chapter=data.get("chapter"),
        lesson=data.get("lesson"),
        variant=variant,
        files={relative_file(name): text for name, text in data.get("files", {}).items()},
    )
    if pack and common["langs"] is None:
        # A generated exercise is only offered where its reference solution vouches for it
        common["langs"] = tuple(common["solutions"])
    if data.get("kind", "function") == "code":
        checks = data["checks"]
        missing = set(checks) - set(data.get("starter", {}))
        if missing:
            raise ExerciseError(f"no starter for {', '.join(sorted(missing))}")
        return Exercise(
            **common, kind="code", starters=data["starter"], checks=checks,
            setup=data.get("setup", {}), file=relative_file(data["file"]) if "file" in data else None,
        )
    if data.get("kind", "function") != "function":
        raise ExerciseError(f"kind must be function or code, not {data['kind']!r}")
    name, params, returns = parse_signature(data["signature"])
    tests = tuple(data["tests"])
    for i, test in enumerate(tests):
        if len(test["in"]) != len(params):
            raise ExerciseError(f"test {i} has {len(test['in'])} arguments, expected {len(params)}")
    for spec in [*data.get("perf", ()), *([data["scale"]] if "scale" in data else [])]:
        if ("in" in spec) == ("code" in spec):
            raise ExerciseError("perf and scale entries need either `in` or `code`")
    if any("label" not in spec for spec in data.get("perf", ())):
        raise ExerciseError("a perf entry needs a label")
    complexity = data.get("complexity")
    if complexity is not None:
        complexity = canonical(complexity)
        if complexity is None:
            raise ExerciseError(f"complexity must be one of {', '.join(CLASSES)}")
    if mode == "optim" and not data.get("starter"):
        raise ExerciseError("an optim exercise needs a [starter] with the slow solution")
    return Exercise(
        **common,
        name=name,
        params=params,
        returns=returns,
        tests=tests,
        examples=data.get("examples", 2),
        perf=tuple(data.get("perf", ())),
        starters=data.get("starter", {}),
        complexity=complexity,
        scale=data.get("scale"),
    )


def load(path: Path) -> Exercise:
    """A library exercise file. Its id and mode default to the file and folder names."""
    return load_text(path.read_text(), path)


def load_text(text: str, path: Path) -> Exercise:
    try:
        data = tomllib.loads(text)
        folder = path.parent.name
        return parse(data, data.get("id", path.stem), folder if folder in MODES else None)
    except (KeyError, tomllib.TOMLDecodeError, ExerciseError) as e:
        detail = f"missing key {e}" if isinstance(e, KeyError) else str(e)
        raise ExerciseError(f"{path}: {detail}") from None
