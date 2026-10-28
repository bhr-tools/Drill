"""`drill add` and `drill rm`: filing an AI's reply in the library, and taking it out.

A reply is one of:
- a single exercise, its keys at the top level, filed in drill/<theme>/<id>.toml;
- a [pack] or a [learn] course, filed in pack/ or learn/ under the slug of its name;
- new variants of an exercise (`variant_of = "<id>"` and [[variants]] tables), appended
  to that exercise in its file, without rewriting anything that is already there.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

from .checking import check, copy_to_clipboard, fix_request, paste, unfence
from .exercises import Exercise, ExerciseError, load_text
from .langs import LANGUAGES
from .library import Library, parse_collection, theme
from .term import bold, dim, green, red, yellow

HEADER = re.compile(r"^\s*(\[\[?)\s*([A-Za-z0-9_.\-]+)\s*(\]\]?)\s*(#.*)?$")
QUOTES = ("'''", '"""')


def headers(lines: list[str]) -> list[tuple[int, str, bool]]:
    """The table headers of TOML lines, outside multi-line strings: (index, name, array)."""
    found = []
    inside = None  # the quotes of the multi-line string being read
    for index, line in enumerate(lines):
        if inside is None and (match := HEADER.match(line)):
            found.append((index, match.group(2), match.group(1) == "[["))
            continue
        position = 0
        while True:
            if inside:
                end = line.find(inside, position)
                if end < 0:
                    break
                inside, position = None, end + 3
            else:
                starts = [(line.find(q, position), q) for q in QUOTES if line.find(q, position) >= 0]
                if not starts:
                    break
                start, inside = min(starts)
                position = start + 3
    return found


def ask(question: str) -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes", "o", "oui")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def reject(problems: list[str]) -> int:
    """Report the problems, and hand the AI a request to fix them."""
    request = fix_request(problems)
    if copy_to_clipboard(request):
        print(yellow("\nNot added. A request to fix it is in the clipboard: paste it to the AI,"))
        print(yellow("in the same conversation, then copy its reply and run `drill add` again."))
    else:
        print(yellow("\nNot added. Paste this to the AI, in the same conversation:\n"))
        print(request)
    return 1


def read_reply(file: Path | None) -> str | None:
    if file is not None:
        if not file.is_file():
            print(red(f"No such file: {file}"))
            return None
        return unfence(file.read_text())
    text = paste()
    if text is None:
        print(red("No clipboard tool found (wl-paste, xclip, pbpaste): give the file instead."))
        return None
    if not text.strip():
        print(red("The clipboard is empty: copy the AI's reply first."))
        return None
    return unfence(text)


def add(lib: Library, file: Path | None, to: str | None, force: bool) -> int:
    text = read_reply(file)
    if text is None:
        return 1
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        print(red(f"Not valid TOML: {e}"))
        return reject([f"- the file is not valid TOML: {e}"])
    if "variant_of" in data:
        return add_variants(lib, text, data, force)
    if "pack" in data or "learn" in data:
        return add_collection(lib, text, force)
    if "exercises" in data:
        print(red("A file of [[exercises]] needs a [pack] or [learn] table."))
        return reject(["- the file has [[exercises]] but no [pack] or [learn] table"])
    return add_exercise(lib, text, data, to, force)


def checked(exercises: list[Exercise], errors: list[str], force: bool) -> list[str] | None:
    """Check the exercises; the problems found, or None if there are none or `force`."""
    for error in errors:
        print(red(f"  ✗ {error}"))
    problems = [f"- {error}" for error in errors]
    problems += check(exercises, list(LANGUAGES.values()))
    if problems and force:
        print(yellow(f"{len(problems)} problem(s), added anyway (--force)."))
        return None
    return problems or None


def write(lib: Library, target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text if text.endswith("\n") else text + "\n")
    print(green(f"✓ {target.relative_to(lib.root)}"))


def add_exercise(lib: Library, text: str, data: dict, to: str | None, force: bool) -> int:
    if "id" not in data:
        print(red("The exercise has no id."))
        return reject(["- the exercise needs an `id` at the top of the file"])
    try:
        exercise = load_text(text, Path(f"{data['id']}.toml"))
    except ExerciseError as e:
        print(red(str(e)))
        return reject([f"- {e}"])
    print(bold(exercise.title) + dim(f"  ·  {exercise.id}  ·  {exercise.mode}"
                                     f"  ·  {exercise.n_variants} variant(s)"))
    if (problems := checked([exercise], [], force)) is not None:
        return reject(problems)
    lib.drill  # loads the paths of the base
    old = lib.paths.get(exercise.id)
    if old is not None:
        print(yellow(f"{exercise.id} is already in {old.relative_to(lib.root)}."))
        if not ask("Replace it?"):
            print("Not added.")
            return 1
        target = old
    else:
        folder = lib.root / to if to else lib.root / "drill" / theme(exercise)
        target = folder / f"{exercise.id}.toml"
    write(lib, target, text)
    print(f"Practise it with `drill run {exercise.id}`.")
    return 0


def add_collection(lib: Library, text: str, force: bool) -> int:
    try:
        collection = parse_collection(text, Path("reply.toml"))
    except ExerciseError as e:
        print(red(str(e)))
        return reject([f"- {e}"])
    print(bold(collection.name) + dim(f"  ·  {collection.kind}  ·  {len(collection.exercises)}"
                                      f" exercises  ·  {collection.counts()}"))
    if (problems := checked(collection.exercises, collection.errors, force)) is not None:
        return reject(problems)
    target = lib.root / collection.kind / f"{collection.slug}.toml"
    clash = [c for c in lib.collections if c.slug == collection.slug]
    if any(c.kind != collection.kind for c in clash):
        print(red(f"A {clash[0].kind} is already named {collection.slug}: rename this one."))
        return 1
    if clash:
        print(yellow(f"{collection.kind} {collection.slug} already exists."))
        if not ask("Replace it? Its history is kept."):
            print("Not added.")
            return 1
    write(lib, target, text)
    print(f"Practise it with `drill {collection.kind} {collection.slug}`.")
    return 0


def find_exercise(lib: Library, exercise_id: str) -> tuple[Exercise, Path] | None:
    """An exercise of the library, by id, with the file it is in."""
    for ex in lib.drill:
        if ex.id == exercise_id:
            return ex, lib.paths[ex.id]
    for collection in lib.collections:
        for ex in collection.exercises:
            if ex.id == exercise_id:
                return ex, collection.path
    return None


def exercise_text(ex: Exercise, path: Path) -> str:
    """The TOML of an exercise: its file, or its [[exercises]] block in a collection."""
    text = path.read_text()
    if ex.origin == "drill":
        return text
    lines = text.splitlines(keepends=True)
    start, end = block(lines, ex)
    return "".join(lines[start:end])


def block(lines: list[str], ex: Exercise) -> tuple[int, int]:
    """The lines of a collection exercise's [[exercises]] block."""
    starts = [i for i, name, array in headers(lines) if array and name == "exercises"]
    data = tomllib.loads("".join(lines))
    local = ex.id.split(":", 1)[1]
    index = next(
        i for i, entry in enumerate(data["exercises"]) if entry.get("id", f"exercise-{i + 1}") == local
    )
    end = starts[index + 1] if index + 1 < len(starts) else len(lines)
    return starts[index], end


def add_variants(lib: Library, text: str, data: dict, force: bool) -> int:
    target_id = data["variant_of"]
    extra = set(data) - {"variant_of", "variants"}
    if extra or not data.get("variants"):
        problem = "- the file must hold only `variant_of` and [[variants]] tables"
        if extra:
            problem += f" (it also has {', '.join(sorted(extra))})"
        print(red(problem[2:]))
        return reject([problem])
    found = find_exercise(lib, target_id)
    if found is None:
        print(red(f"No exercise {target_id} in the library."))
        return 1
    ex, path = found
    lines = text.splitlines(keepends=True)
    tables = headers(lines)
    body = lines[tables[0][0]:]  # from the first table: without variant_of
    old_text = path.read_text()
    old_lines = old_text.splitlines(keepends=True)
    if not old_text.endswith("\n"):
        old_lines[-1] += "\n"
    if ex.origin == "drill":
        new_lines = [*old_lines, "\n", *body]
    else:
        # In a collection, tables are written [[exercises.variants]] and go at the end
        # of the exercise's block
        offset = tables[0][0]
        for index, name, array in tables:
            opening, closing = ("[[", "]]") if array else ("[", "]")
            body[index - offset] = f"{opening}exercises.{name}{closing}\n"
        _, end = block(old_lines, ex)
        new_lines = [*old_lines[:end], "\n", *body, *(["\n"] if end < len(old_lines) else []),
                     *old_lines[end:]]
    new_text = "".join(new_lines)
    try:
        updated = reparse(new_text, path, ex)
    except ExerciseError as e:
        print(red(str(e)))
        return reject([f"- {e}"])
    added = updated.n_variants - ex.n_variants
    if added != len(data["variants"]):
        print(red("The variants could not be appended to the exercise's file safely."))
        return 1
    print(bold(updated.title) + dim(f"  ·  {updated.id}  ·  +{added} variant(s)"))
    new_instances = updated.instances[ex.n_variants:]
    # A variant's instances are itself alone: only the new ones are checked
    if (problems := checked(list(new_instances), [], force)) is not None:
        return reject(problems)
    path.write_text(new_text)
    print(green(f"✓ {path.relative_to(lib.root)}: {updated.id} has {updated.n_variants} variants "
                f"(+{added})"))
    return 0


def reparse(text: str, path: Path, ex: Exercise) -> Exercise:
    """The exercise `ex` read again from the new text of its file."""
    if ex.origin == "drill":
        return load_text(text, path)
    collection = parse_collection(text, path, path.stem)
    for error in collection.errors:
        if error.startswith(ex.id.split(":", 1)[1] + ":"):
            raise ExerciseError(error)
    return next(e for e in collection.exercises if e.id == ex.id)


def remove(lib: Library, target: str, yes: bool) -> int:
    found = find_exercise(lib, target)
    if found and found[0].origin != "drill":
        ex, path = found
        print(red(f"{target} is part of {ex.origin} {ex.pack}: edit {path} to take it out, "
                  f"or remove the whole {ex.origin}."))
        return 1
    if found:
        path, what = found[1], f"exercise {target}"
    elif (collection := lib.collection(target)) is not None:
        path, what = collection.path, f"{collection.kind} {collection.slug}"
    else:
        print(red(f"Nothing named {target} in the library. `drill list` shows what is there."))
        return 1
    relative = path.relative_to(lib.root)
    if not yes and not ask(f"Remove {what} ({relative})? Its history is kept."):
        print("Nothing removed." + ("" if sys.stdin.isatty() else " (-y removes without asking.)"))
        return 1
    path.unlink()
    print(f"Removed {relative}.")
    return 0

