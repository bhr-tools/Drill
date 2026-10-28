"""Tab completion. The shell scripts ask `drill __complete`, which reads the command line
the way drill's own parser does, so the completion cannot drift from the commands."""

from __future__ import annotations

import argparse

from .langs import LANGUAGES

ZSH = r"""#compdef drill
# drill's completion: the candidates come from `drill __complete`.
_drill() {
  local -a lines
  lines=("${(@f)$(drill __complete zsh $((CURRENT - 1)) "${(@)words[2,-1]}" 2>/dev/null)}")
  case $lines[1] in
    __files__) _files ;;
    __dirs__) _files -/ ;;
    '') return 1 ;;
    *) _describe -t values drill lines ;;
  esac
}
_drill "$@"
"""

BASH = r"""# drill's completion: the candidates come from `drill __complete`.
_drill() {
  local cur=${COMP_WORDS[COMP_CWORD]} out
  out=$(drill __complete bash "$COMP_CWORD" "${COMP_WORDS[@]:1}" 2>/dev/null)
  case $out in
    __files__) COMPREPLY=($(compgen -f -- "$cur")) ;;
    __dirs__) COMPREPLY=($(compgen -d -- "$cur")) ;;
    *) local IFS=$'\n'; COMPREPLY=($(compgen -W "$out" -- "$cur")) ;;
  esac
}
complete -F _drill drill
"""

SCRIPTS = {"zsh": ZSH, "bash": BASH}


def subcommands(parser: argparse.ArgumentParser):
    return next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)


def option(parser: argparse.ArgumentParser, word: str):
    return parser._option_string_actions.get(word.split("=", 1)[0])


def positionals(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    return [
        a for a in parser._actions
        if not a.option_strings and not isinstance(a, argparse._SubParsersAction)
    ]


def library_values(kind: str, prefix: str) -> list[tuple[str, str]]:
    """Exercise ids, or collection names, from the library: nothing if it is not set."""
    from .library import Library, LibraryError

    try:
        lib = Library()
        if kind in ("pack", "learn"):
            return [(c.slug, c.name) for c in lib.of_kind(kind)]
        values = [(ex.id, ex.title) for ex in lib.exercises()]
        if kind == "any":
            values += [(c.slug, f"{c.kind}: {c.name}") for c in lib.collections]
        return values
    except LibraryError:
        return []


def languages(current: str) -> list[tuple[str, str]]:
    """Languages, after the ones already written in a comma-separated list."""
    head, _, _ = current.rpartition(",")
    done = set(head.split(",")) if head else set()
    prefix = head + "," if head else ""
    values = [(prefix + key, lang.label) for key, lang in LANGUAGES.items() if key not in done]
    return values if head else [*values, ("mix", "every language")]


def values_for(action: argparse.Action, parser: argparse.ArgumentParser, current: str):
    if action.choices and not isinstance(action.choices, dict):
        return [(str(c), "") for c in action.choices]
    dest = action.dest
    command = parser.prog.split()[-1]
    if dest == "lang":
        return languages(current)
    if dest in ("file",):
        return "__files__"
    if dest == "to":
        return "__dirs__"
    if dest == "name" and command in ("pack", "learn"):
        return library_values(command, current)
    if dest == "queries":
        return library_values("any", current)
    if dest == "target":
        return library_values("any", current)
    if dest == "id":
        return library_values("exercise", current)
    return []


def candidates(parser: argparse.ArgumentParser, words: list[str], position: int):
    """What can be written at `words[position - 1]`: (value, description) pairs, or
    __files__ / __dirs__ to let the shell complete paths."""
    current = words[position - 1] if 0 < position <= len(words) else ""
    expecting = None
    seen = 0  # positionals given so far to the current parser
    for word in words[: max(0, position - 1)]:
        if expecting is not None:
            expecting = None
            continue
        if word.startswith("-"):
            action = option(parser, word)
            if action is not None and action.nargs != 0 and "=" not in word:
                expecting = action
            continue
        sub = subcommands(parser)
        if sub is not None and seen == 0 and word in sub.choices:
            parser, seen = sub.choices[word], 0
            continue
        seen += 1
    if expecting is not None:
        return values_for(expecting, parser, current)
    if current.startswith("-"):
        return [
            (string, action.help or "")
            for action in parser._actions
            if action.help != argparse.SUPPRESS
            for string in action.option_strings
            if string.startswith("--") or len(action.option_strings) == 1
        ]
    sub = subcommands(parser)
    if sub is not None and seen == 0:
        return [(c.dest, c.help or "") for c in sub._choices_actions]
    for action in positionals(parser):
        many = action.nargs in ("*", "+")
        if many or seen == 0:
            return values_for(action, parser, current)
        seen -= 1
    return []


def complete(parser: argparse.ArgumentParser, shell: str, position: int, words: list[str]) -> str:
    found = candidates(parser, words, position)
    if isinstance(found, str):
        return found
    if shell == "zsh":
        return "\n".join(
            value.replace(":", r"\:") + (f":{help}" if help else "") for value, help in found
        )
    return "\n".join(value for value, _ in found)
