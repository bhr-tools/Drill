# Drill

Rapid-fire coding exercises, solved in your own editor.

Drill gives you one exercise at a time. You write the solution in your usual
editor, and every time you save, the tests run. As soon as they pass, drill
shows the reference solution, and the next exercise starts on `enter`. You never leave the keyboard, and you train with your own
shortcuts, snippets and language server.

```
$ drill                      # the whole base: reviews due first, then new exercises
$ drill sprint -l cpp -m 30  # one mode, in C++, for 30 minutes
$ drill learn automates      # a learn module: the practical work of a course
```

## The library

Drill holds no exercises itself: they live in your library, a folder of TOML
files that is best kept in a git repository of its own. Point `$DRILL_LIBRARY`
to it; drill refuses to start without it.

```
drill/<theme>/<id>.toml   the base: exercises practised for good, one per file
                          (theme: shared, python, cpp, java, ocaml or nix)
learn/<slug>.toml         learn modules: the practical work of a course, in order
proba/<theme>.toml        probability problems, answered in the terminal (drill proba)
history/<machine>.jsonl   your history: one line per attempt, one file per machine
```

Changing the library needs no rebuild: drill reads it on every run. Folders
under `drill/` are only for tidiness; you can move files around with `git mv`.

### Syncing with git

When the library is a git repository with a remote, drill keeps it in step:

- it pulls when it starts (before every session, and at most every 5 minutes
  for the other commands);
- it commits and pushes at the end of a session and after `drill add` or
  `drill rm`. A commit that could not be pushed goes with the next push.

Without network, or on a conflict, drill says so in one line and goes on.
`DRILL_SYNC=0` turns syncing off.

Each machine appends only to its own history file, so the histories of several
machines merge without conflicts, and your levels are the same on all of them:
drill replays every machine's attempts in order. `~/.local/share/drill/history.db`
is only a local cache of these files, rebuilt when they change. The machine's
name is its hostname, or `$DRILL_MACHINE`.

## Modes

`drill` alone serves every mode; a mode narrows the session to it.

- `drill sprint`: very short exercises (1–2 min targets). Idioms, classic
  patterns, the reflexes you want instant.
- `drill normal`: exercises that need a bit more thought (5–10 min targets).
  Choosing the right structure is part of the drill: sliding window,
  monotonic stack, union-find, Dijkstra, DP…
- `drill hard`: data structures and language subtleties (12–20 min targets).
  An LRU cache, a versioned store or a trie, written idiomatically in each
  language. Also decorators, generators and dataclasses in Python; move
  semantics, custom iterators and variadic templates in C++; generics with
  wildcards and `equals`/`hashCode`/`compareTo` in Java.
- `drill optim`: the code you start with works, but it is too slow. Estimate
  its complexity, measure it, then make it fast enough for the performance
  test. Once it is solved, an explanation covers the theory: why the first
  version was slow and why the new one is faster.

Each mode also has language idioms (ids starting with `py-`, `cpp-`, `java-`),
served only when you train in that language.

## Probability and mental arithmetic

Two drills are answered in the terminal instead of coded, for the tests of trading firms.

```
$ drill proba                 # probability problems, scheduled like the exercises
$ drill proba jeux            # only one theme (a file of proba/), a tag or an id
$ drill proba --list          # the problems and your level on each
$ drill mental                # Optiver-style: 80 questions in 8 minutes
$ drill mental zetamac        # Zetamac-style: 2 minutes of integer arithmetic
$ drill mental --only dec,frac -m 3   # 3 minutes of decimals and fractions only
```

`drill proba` serves the problems of the library's `proba/` folder, one at a time.
Type the answer as a number, a fraction (`1/3`), a percentage (`37.5%`) or an expression
(`1-(5/6)^4`, `sqrt(2)/2`, `pi/4`); an approximate decimal is accepted within the problem's
tolerance (0.1 % by default). `h` shows the hint, `s` gives up, `p` pauses, `q` quits.
After the answer (or a skip), drill shows the worked solution and, when there is one, the
trick: the shortcut that made a long calculation unnecessary. Problems have levels and
reviews like the exercises (language `proba` in `drill stats`), and a wrong answer weighs
like the hint: the attempt can no longer go up a level.

`drill mental` generates its questions: integers (sums, products with the classic tricks:
near squares, ×11, ×25, ×99), divisions, decimals, fractions and percentages. Enter alone
skips a question, `q` stops. At the end come the score, the accuracy and speed per category,
the slowest questions with the trick for each, and your progress. `--negative` also counts
−1 per wrong answer. Only a test run in its preset's conditions (no `-n`, `-m` or
`--only`) counts in the preset's history; the others are kept under their own name.

A problem file holds `[[problems]]` tables:

```toml
[[problems]]
id = "first-six"                 # unique across proba/
title = "Attendre le premier 6"
tags = ["géométrique"]
target = 30                      # seconds
statement = "On lance un dé jusqu'à obtenir un 6. Combien de lancers en moyenne ?"
answer = "6"                     # a number, a fraction or an expression: "161/36", "pi/4"
tolerance = 0.001                # optional, relative, for approximate answers
hint = "…"                       # optional
solution = """…"""               # the worked solution, shown after the answer
trick = """…"""                  # optional: the shortcut worth remembering

[[problems.variants]]            # optional: the same idea with other numbers or a twist
title = "Attendre le premier 20"
statement = "On lance un dé à 20 faces jusqu'à obtenir un 20. Combien de lancers en moyenne ?"
answer = "20"
solution = "…"                   # each key replaces the problem's; the others are inherited
```

Variants share their problem's level and schedule. Each time it comes back, drill serves
the variant practised least recently, so that the method is learnt rather than the answer.
`drill proba --list` shows the number of versions (`×3`).

## Languages

Python, C++ and Java share the general exercises (algorithms and data
structures), on top of their own idioms. OCaml and Nix only get exercises
written for them, about what each language is for:

- OCaml (`-l ocaml`, ids `ml-`): pattern matching, variant types, recursion with
  accumulators, `Option`, `Result` and `let*`, `Map.Make` and `Set.Make`,
  functors, lazy `Seq`. A few list-friendly classics (merging, parentheses,
  maximum subarray) also have an OCaml version.
- Nix (`-l nix`, ids `nix-`): the language and `lib` (attribute sets, lists,
  strings, fixed points), packaging (`mkDerivation`, `writeShellApplication`,
  raw `derivation`), overlays (`final` and `prev`), flakes (dev shells, outputs
  per system, NixOS modules and configurations), the NixOS module system
  (options, `mkIf`, priorities and merging), and exploring a configuration in
  `nix repl`. For those, the folder contains the files the exercise is about (a
  flake, a project to package, a base module), and the file to edit is the one
  the exercise names: `flake.nix`, `package.nix`, `module.nix`, `answer.nix`…

Nix exercises are checked by evaluating your file with `nix-instantiate`,
without network: a flake's `nixpkgs` input is the nixpkgs drill was built with
(`$DRILL_NIXPKGS`, else `<nixpkgs>`), and checks build only small things. The
`c` key and performance tests do not apply to Nix.

## Variants

Many exercises come in several variants: the same concept on other data, or
with a twist (a lower bound instead of an exact search, a difference instead of
a sum, a dev shell for Node instead of Python). The variants share the schedule
of their exercise, and each time it comes back, drill serves the variant you
have practised least recently, so that you learn the concept rather than one
answer. `drill list` shows the number of variants (`×3`).

To practise specific exercises:

```
$ drill list iterator            # by id, title, tag or mode
$ drill run lru-cache -l cpp     # one exercise, again and again (kata)
$ drill run graph hard           # the hard exercises about graphs
$ drill run two-sum trie         # exact ids: both exercises
$ drill run two-sum#2            # always its second variant
```

A query is an exact id, or else a part of an id, a title or a tag, a mode, or
`drill` or `learn`; an exercise must match every query that is not an
exact id.

Without `-l`, `drill run` uses your default language when the exercises
support it, and otherwise every language they support.

A run is a sandbox: it records nothing, neither the level nor the record, so
replaying an exercise in a loop cannot raise its score. In any session, after
an exercise is solved or skipped, `enter` goes on and `r` runs it again in the
sandbox; `enter` then takes you back to the session.

Options for both:

| Option | |
|---|---|
| `-l python`, `-l cpp,java`, `-l nix`, `-l mix` | language(s); `mix` alternates all of them |
| `-m 30` | stop after 30 minutes |
| `-e code`, `-e none` | command that opens the exercise file (default: `$DRILL_EDITOR`, else `code` if found) |
| `--keep` | keep the session folder at the end |

## During a session

The exercise is written to a temporary folder (`/tmp/drill-…`), with the
statement and examples as a comment at the top of the file. The folder is
removed when the session ends.

| Key | |
|---|---|
| save the file | run the tests |
| `h` | show the hint (the attempt then cannot set a record) |
| `s` | skip: shows the reference solution, and the exercise comes back soon |
| `p` | pause the clock |
| `r` | rerun the tests |
| `o` | reopen the file in the editor |
| `c` | measure the complexity of your code (exercises that support it) |
| `q` | quit |

After a solve, as after a skip, drill shows the reference solution (and its
explanation, if any) and waits: `enter` for the next exercise, `q` to quit.

With VS Code, the most comfortable setup is running `drill` in the integrated
terminal. With a terminal editor, use `-e none` and open the printed path in
another pane. The file is rewritten in place for each exercise.

## Measuring complexity

On most function exercises, `c` asks for your estimate of your code's time
complexity, then times it on inputs of growing size (1 000, 2 000, 4 000…, up to
the first size that takes over 1.5 s). The reference solution gets the same
treatment, and you see both side by side:

```
            n          yours      reference
        1,000         144 µs          68 µs
        …
       64,000       452.4 ms         5.2 ms
      128,000     over 1.5 s        11.2 ms
  your code   ~ n^2.09 → O(n²)
  reference   ~ n^1.06 → O(n) or O(n log n)
✓ Your estimate O(n²) matches the measurement.
↗ The optimal complexity is O(n): this code can do better.
```

A running time in O(nᵏ) is a line of slope k on a log-log scale, so the slope
measured over the largest sizes gives the growth. Timing cannot tell n from
n log n, or 1 from log n: both are then reported as consistent. On large inputs,
cache misses make each operation slower, which makes the slope read a little
high. The comparison allows for that. The clock is paused during the
measurement, and `drill stats` keeps track of how often your estimates are right.

## Adding exercises: the AI loop

Every addition goes through the same loop: drill writes the request, an AI
writes the TOML, and drill checks it before filing it.

```
$ drill prompt "an exercise I saw: ..."   # the request, copied
    → paste it to Claude, copy its reply
$ drill add                               # reads the clipboard, checks, files
    → if a check fails, the request to fix it is copied: paste it back, then add again
```

| Request | For |
|---|---|
| `drill prompt "idea"` | one exercise for the base, from an idea or a statement seen elsewhere (or read from stdin). The AI picks the languages where it makes sense. |
| `drill prompt learn` | a learn module, from the course you attach (notes in Markdown, slides, lab sheets as PDFs). The AI replies with the whole module. |
| `drill prompt variant <id>` | `-n` new variants of an exercise of the library. |

Options: `-l nix,ocaml` the languages (for `learn`, by default the ones the
course uses, else `$DRILL_LANG`), `-L fr` the language of the statements
(default `$DRILL_LOCALE`, else English; code stays in English), `--print` to
print the request instead of copying it.

`drill add` files what it gets by what it is: a single exercise in
`drill/<its language>/` (`drill/shared/` when it has several, or `--to`), a
`[learn]` in `learn/`, and `variant_of = "<id>"` with `[[variants]]` appended
to that exercise in its own file, leaving the rest untouched. Something with
the same id or name is replaced only after you confirm.

`drill add file.toml` reads a file instead of the clipboard.

`drill rm <id|module>` deletes a file of the library. The history is kept, and
git keeps the file.

## Learn modules

A learn module is the practical work of a course, kept apart from the base:
`drill` never serves it, `drill learn` does.

```
$ drill prompt learn          # paste it, rewrite Behaviour if you want, attach your course
$ drill add                   # the whole module
$ drill learn automates       # reviews due first, then the exercises never done, in order
$ drill list automates        # where you stand, part by part
```

The request opens with a short **Behaviour** paragraph, which says what the
module is for. By default: the practical work of the course, every concept,
algorithm and lab question that code can check, in the course's order, with
lab questions that overlap merged. Replace it, once pasted, with a few lines of
your own:

> Follow the labs exactly, question by question, giving the code of the
> previous questions as the starter.

> Have me code each algorithm of the course, from the most naive to the most
> efficient, one part per problem.

The exercises come in parts (`chapter`), and each one cites the part of your
course it trains: `cf. AUT - 01 · 5. Subset construction` under its title in a
session, and on its sheet in `drill list`. Drill does not open the course; the
reference is there for you to look it up. Modules carry no lessons: your course
is the lesson.

If the AI's reply is cut short, ask it to continue and `drill add` the rest: it
is appended to the module.

`examples/sorting-learn.toml` is a small example module.

## How drill schedules

`drill help` prints this, and more.

Every session serves first what is due for review, the most overdue first,
then the exercises you have never done: in order in a learn module, at random
in the base. When nothing is left, the session says so and ends. `drill run`
serves its exercises in turn, as long as you like, and records nothing.

```
Levels and reviews (the Leitner system)
  Each exercise has a level from 0 to 5 in each language, and comes back for review
  after a delay that grows with its level:
    level      0                1      2      3      4       5
    review     this session     1 d    3 d    7 d    16 d    35 d
  After each attempt:
    within the target time, without the hint     up one level
    over the target (up to 2×), or with the hint  down one level (1 at least)
    skipped, or over twice the target             back to 0: again this session
  So what you know comes back less and less often, and what resists comes back until
  it no longer does. An exercise is "known" from level 3.
```

After each exercise, a line says what happened, e.g. `Within the target: level 2 → 3,
next review in 7 days.`

## Your progress

```
$ drill list                 # the base, then your learn modules
$ drill list nix --due       # the exercises about Nix due for review
$ drill list -l ocaml --new  # the OCaml exercises never done
$ drill list two-sum         # one exercise: its variants and your history
$ drill stats                # practice, mastery, reviews to come, speed, weak spots
```

`drill list` shows, for each exercise, its number of variants (`×3`), its
target, your best time, your tries, your level (`▮▮▮▯▯`) and when it comes
back. With `-l`, the progress is the one in those languages.

`drill stats` compares your last 7 days with the 7 before, shows your daily
practice over 30 days, how many exercises you know (level 3 or more) in the
base and in each learn module, the reviews of the coming week, your
time/target and its trend in each language (solve time over target: 1.0× is on
target, lower is faster), and the tags and exercises that resist most.

The history is in the library, in `history/` (see [Syncing with git](#syncing-with-git)).

## Tab completion

The package installs completion for zsh and bash: commands, options, languages
after `-l` (also after a comma), exercise ids, learn modules. Elsewhere,
`drill completion zsh` prints the script.

## Writing exercises

There are two kinds of exercises. A function exercise is one TOML file,
written once for every language:

```toml
title = "Two sum"
tags = ["hashmap"]
target = 90                       # seconds
signature = "two_sum(nums: list[int], target: int) -> list[int]"
statement = """
Return the indices [i, j], with i < j, of the two numbers that add up to target.
"""
hint = "Remember each value's index in a hashmap."
tests = [
  { in = [[2, 7, 11, 15], 9], out = [0, 1] },
  { in = [[3, 3], 6], out = [0, 1] },
]

[solutions]
python = '''
def two_sum(nums, target): ...
'''
cpp = '''
vector<int> twoSum(vector<int>& nums, int target) { ... }
'''
java = '''
public int[] twoSum(int[] nums, int target) { ... }
'''
```

- `[[perf]]` entries add performance tests, generated from Python with a
  seeded `rng` (`random.Random`), so they are identical on every run. The
  expected output comes from the Python reference solution unless `out` is
  given. `limit` is in seconds (default 2). The harness stops the solution as
  soon as it goes over the limit:

  ```toml
  [[perf]]
  label = "n = 200 000"
  in = "[[rng.randint(-10_000, 10_000) for _ in range(200_000)]]"

  [[perf]]
  label = "n = 300 000, the pair at the very end"
  code = '''
  nums = [2 * x for x in rng.sample(range(-10**8, 10**8), 300_000)]
  nums[-2] += 1
  args = [nums, nums[-2] + nums[-1]]
  '''
  ```

  Size them so the naive solution fails even in C++ and Java (around 10¹⁰
  operations), while the reference stays well under the limit. `drill check`
  shows how much of the limit each reference uses.
- `complexity` (the optimal one: `O(1)`, `O(log n)`, `O(n)`, `O(n log n)`,
  `O(n²)`, `O(n³)` or `O(2ⁿ)`) and a `[scale]` table enable the `c` key. The
  `[scale]` table takes an `in` expression or a `code` block, like `[[perf]]` but
  with `n` defined, plus optional `label`, `sizes` and `limit` (seconds per
  size, default 1.5). Its outputs are not checked.
- `explanation`: the theory behind the solution, shown with the reference
  solution, and after each solve in optim mode.
- `[starter]` gives the starting code per language, instead of an empty
  function. An optim exercise starts from its slow solution this way.
- Types: `int`, `long`, `bool`, `str` and `list[...]` of those, nested as
  deep as needed. They map to `vector<>` in C++, arrays in Java and lists in
  OCaml. `any` is any JSON value (attribute sets in Nix), for Python and Nix
  only. Function and parameter names are written in snake_case and become
  camelCase in C++, Java and Nix.
- `[[variants]]` add variants: each replaces any key it sets (statement,
  signature, tests, solutions, starter, checks, files…). One that sets a
  signature needs its own tests and solutions.
- The mode comes from the folder (`sprint/`, `normal/`, `hard/`, `optim/`), or a `mode` key.
- Reference solutions skip the boilerplate: no includes in C++, no `class
  Solution` wrapper in Java.
- `langs = ["python"]` restricts an exercise to some languages. Without it, a
  function exercise is offered in the languages of its solutions (in Python,
  C++ and Java when it has none).
- OCaml function solutions are top-level definitions; Nix ones are the function
  itself (`xs: target: …`), with `{ lib }:` added above.

A code exercise (`kind = "code"`) is for what a signature cannot express:
classes, generators, templates, iterators. It has a starter and tests written
in each language it supports:

```toml
title = "Generic LRU cache"
kind = "code"
target = 900
statement = "..."

[starter]
python = '''
class LRUCache: ...
'''

[setup]      # optional: file-level helpers for the checks
python = "..."

[checks]
python = '''
cache = LRUCache(2)
check("get a", cache.get("a"), None)            # check(label, got, expected=True)
raises("bad capacity", ValueError, LRUCache, -1)
'''
cpp = '''
CHECK(cache.size() == 0);
CHECK_EQ(cache.get("a"), std::optional<int>());
CHECK_THROWS(std::invalid_argument, LRUCache<int, int>(-1));
'''
java = '''
check("get a", cache.get("a"), null);           // or check(label, condition)
checkThrows("bad capacity", IllegalArgumentException.class, () -> new LRUCache<>(-1));
'''

[solutions]  # whole files
python = "..."
```

Each check counts as one test. C++ checks run inside a function body, Java
checks inside a static method of `Main`. C++ is compiled with
`-Werror=return-type`, so a function that is missing a return fails to
compile instead of crashing.

OCaml checks run after `open Solution`, separated by `;`: `check label cond`,
`check_eq ~show:Show.(list int) label got expected`, `check_raises label (fun
() -> …)`.

Nix checks are a list of `(check "label" got expected)` and `(checkThrows
"label" value)`, with `[setup]` holding let bindings. In scope: `lib`, `pkgs`,
`nixpkgs`, `system`, `dir` (the folder) and `file` (your file), plus
`loadFlake dir`, `nixos [ modules ]`, `sh "script"` (the output of a script run
in a build), `contains` and `packageNames`. A code exercise can name the file to
edit (`file = "flake.nix"`) and give files next to it (`[files]`), where
`@NIXPKGS@` stands for the local nixpkgs:

```toml
kind = "code"
file = "package.nix"

[files]
"src/greet.c" = "…"

[setup]
nix = "greet = pkgs.callPackage file { };"

[checks]
nix = '''
(check "pname" (greet.pname or null) "greet")
(check "it runs" (sh "${greet}/bin/greet") "Hello\n")
'''
```

An exercise file of the library also starts with its `id` and `mode`. Check
the library with:

```
$ drill check              # every reference solution against its tests
$ drill check two-sum -l cpp
```

## Development

```
$ nix develop
$ drill check      # runs the working tree
$ nix build        # the packaged app, with g++, the JDK and OCaml on its PATH
```

The first C++ run builds a precompiled `<bits/stdc++.h>` in `~/.cache/drill`
(about 150 MB, a few seconds). After that, each C++ build takes about 0.5 s.
