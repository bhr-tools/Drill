"""Language backends: starter files, generated test harnesses, build and run.

Every exercise is written once with language-neutral types and test data. Each backend
turns it into a starter file and a harness that reads the test cases from a data file,
calls the user's function on each one and prints one `@@DRILL {json}` line per case.

Performance cases carry a time limit, enforced inside the harness around the call:
the first case over its limit is reported with `"timeout": true` and the run stops.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import textwrap
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .exercises import Exercise

MARKER = "@@DRILL "
TIMEOUT = 10  # seconds, for each build step, and for a run on top of its time limits
MAX_ERROR_LINES = 15


@dataclass
class Outcome:
    total: int
    results: list[dict] = field(default_factory=list)
    error: str | None = None  # compilation error, crash or timeout

    @property
    def n_ok(self) -> int:
        return sum(1 for r in self.results if r.get("ok"))

    @property
    def passed(self) -> bool:
        return self.error is None and self.n_ok == self.total


def camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def type_spec(t) -> str:
    return f"list[{type_spec(t[1])}]" if isinstance(t, tuple) else t


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "drill"


def _unlimited_stack() -> None:
    """Let deep recursion (DFS on 10^5 nodes) use more than the default 8 MB stack."""
    _, hard = resource.getrlimit(resource.RLIMIT_STACK)
    resource.setrlimit(resource.RLIMIT_STACK, (hard, hard))


def _execute(
    cmd: list[str], cwd: Path, timeout: float = TIMEOUT, big_stack: bool = False
) -> tuple[subprocess.CompletedProcess | None, str | None]:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
            preexec_fn=_unlimited_stack if big_stack else None,
        )
        return proc, None
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:g}s (infinite loop?)"
    except FileNotFoundError:
        return None, f"command not found: {cmd[0]}"


def _tidy(text: str, paths: dict[str, str]) -> list[str]:
    """Shorten temporary paths in compiler or runtime output."""
    for path, short in paths.items():
        text = text.replace(path, short)
    return text.strip().splitlines()


def _collect(proc: subprocess.CompletedProcess, total: int | None, paths: dict[str, str]) -> Outcome:
    """Parse the harness output. `total` is None when the tests are code that counts
    its own checks: it then reports `{"done": n}` once every check has run."""
    outcome = Outcome(total or 0)
    done = None
    for line in proc.stdout.splitlines():
        # find() rather than startswith(): user output may lack a trailing newline
        at = line.find(MARKER)
        if at >= 0:
            entry = json.loads(line[at + len(MARKER):])
            if "done" in entry:
                done = entry["done"]
            else:
                outcome.results.append(entry)
    if total is None:
        # Without the done marker, at least one more check never reported
        outcome.total = done if done is not None else len(outcome.results) + 1
    if outcome.results and outcome.results[-1].get("timeout"):
        return outcome  # stopped on purpose at the case over its time limit
    if len(outcome.results) < outcome.total:
        code = proc.returncode
        if code < 0:
            try:
                what = f"crashed ({signal.Signals(-code).name})"
            except ValueError:
                what = f"crashed (signal {-code})"
        else:
            what = f"exited with status {code}" if code else "stopped before running every test"
        outcome.error = "\n".join([what, *_tidy(proc.stderr, paths)[-MAX_ERROR_LINES:]])
    return outcome


def _run_timeout(cases: list[dict]) -> float:
    return TIMEOUT + sum(case.get("limit", 0) for case in cases)


def _encode(t, value, out: list[bytes]) -> None:
    """Serialise a value as whitespace-separated tokens, read back by the C++ and Java harnesses.

    Lists are a length followed by their items; strings a byte length, one space and
    the raw UTF-8 bytes.
    """
    if isinstance(t, tuple):
        out.append(str(len(value)).encode())
        for item in value:
            _encode(t[1], item, out)
    elif t == "str":
        raw = value.encode()
        out.append(f"{len(raw)} ".encode() + raw)
    elif t == "bool":
        out.append(b"1" if value else b"0")
    else:
        out.append(str(value).encode())


def _data_file(ex: Exercise, cases: list[dict], tag: str, build: Path) -> Path:
    """`cases` in the token format, written once per build folder.

    Each case starts with its time limit (0: none) and whether to repeat fast calls
    to time them precisely (1) or call once (0).
    """
    path = build / f"{ex.key}.{tag}.data"
    if not path.exists():
        out = [str(len(cases)).encode()]
        for case in cases:
            out.append(f"{case.get('limit', 0)} {int(case.get('repeat', False))}".encode())
            for (_, t), value in zip(ex.params, case["in"]):
                _encode(t, value, out)
            _encode(ex.returns, case["out"], out)
        path.write_bytes(b" ".join(out) + b"\n")
    return path


class Language:
    key: str
    label: str
    filename: str
    comment: str
    measurable = True  # runs timed cases, for performance tests and complexity measurement

    def ident(self, name: str) -> str:
        return camel(name)

    def literal(self, value) -> str:
        """A value written in the language, for statements and failure reports."""
        return json.dumps(value)

    def call(self, ex: Exercise, test: dict) -> str:
        return f"{self.ident(ex.name)}({', '.join(self.literal(a) for a in test['in'])})"

    def filename_for(self, ex: Exercise) -> str:
        return ex.file or self.filename

    def fixtures(self, ex: Exercise) -> dict[str, str]:
        """The files written next to the student's file."""
        return ex.files

    def header(self, lines: list[str]) -> str:
        return "\n".join(f"{self.comment} {line}".rstrip() for line in lines)

    def starter(self, ex: Exercise) -> str:
        body = ex.starters[self.key].strip("\n") + "\n" if ex.starters else self.skeleton(ex)
        return f"{self.header(ex.describe(self))}\n\n{body}"

    def reference(self, ex: Exercise) -> str | None:
        """The exercise's reference solution as a complete source file."""
        code = ex.solutions.get(self.key)
        if code is None:
            return None
        # Code exercises store whole files; function ones skip the boilerplate
        return code.strip("\n") + "\n" if ex.kind == "code" else self.complete(code.strip("\n"))

    def run(
        self, ex: Exercise, source: Path, build: Path, cases: list[dict] | None = None,
        tag: str = "tests",
    ) -> Outcome:
        """Run the solution in `source` on `cases` (default: the exercise's tests).

        `tag` names the data file of those cases, cached in `build`.
        """
        build.mkdir(parents=True, exist_ok=True)
        if ex.kind == "code":
            return self._run_code(ex, source.resolve(), build.resolve())
        cases = ex.cases if cases is None else cases
        return self._run(ex, source.resolve(), build.resolve(), cases, tag)

    def _run_code(self, ex: Exercise, source: Path, build: Path) -> Outcome:
        raise NotImplementedError

    def warm_up(self) -> None:
        """Prepare anything that makes the first run faster, in the background."""

    def skeleton(self, ex: Exercise) -> str:
        raise NotImplementedError

    def complete(self, code: str) -> str:
        return code + "\n"

    def _run(self, ex: Exercise, source: Path, build: Path, cases: list[dict], tag: str) -> Outcome:
        raise NotImplementedError


# Fast calls of a repeated case are timed again until they add up to this
REPEAT_BUDGET_US = 50_000

PY_HARNESS = """\
import copy, importlib.util, json, signal, sys, time, traceback

sys.setrecursionlimit(1_000_000)
source, cases_path, name = sys.argv[1:4]
budget_us = float(sys.argv[4])


class TimeLimit(BaseException):
    pass


def on_alarm(signum, frame):
    raise TimeLimit


def user_frames(e):
    return [f for f in traceback.extract_tb(e.__traceback__) if f.filename == source]


try:
    spec = importlib.util.spec_from_file_location("solution", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    function = getattr(module, name)
except Exception as e:
    lines = traceback.format_list(user_frames(e)) + traceback.format_exception_only(e)
    sys.stderr.write("".join(lines))
    sys.exit(1)

signal.signal(signal.SIGALRM, on_alarm)
for i, case in enumerate(json.load(open(cases_path))):
    report = {"i": i, "ok": False}
    try:
        total = calls = 0
        while True:
            args = copy.deepcopy(case["in"])  # each call gets inputs it may modify
            if case.get("limit"):
                signal.setitimer(signal.ITIMER_REAL, case["limit"])
            start = time.perf_counter()
            result = function(*args)
            total += (time.perf_counter() - start) * 1e6
            calls += 1
            signal.setitimer(signal.ITIMER_REAL, 0)
            if not case.get("repeat") or total >= budget_us or calls >= 20:
                break
        report["us"] = total / calls
        # The JSON round trip turns tuples into lists, like the expected values
        got = json.loads(json.dumps(result))
        report["ok"] = got == case["out"] and type(got) is type(case["out"])
        if not report["ok"]:
            report["got"] = got
    except TimeLimit:
        report["timeout"] = True
    except Exception as e:
        signal.setitimer(signal.ITIMER_REAL, 0)
        frames = user_frames(e)
        where = f" (line {frames[-1].lineno})" if frames else ""
        report["error"] = f"{type(e).__name__}: {e}{where}"
    print("@@DRILL " + json.dumps(report), flush=True)
    if report.get("timeout"):
        break
"""


PY_CODE_HARNESS = """\
import importlib.util, json, sys, traceback

sys.setrecursionlimit(1_000_000)
source, checks_path = sys.argv[1:3]
count = 0


def emit(**report):
    global count
    print("@@DRILL " + json.dumps({"i": count, **report}), flush=True)
    count += 1


def check(label, got, expected=True):
    \"\"\"One test case: `got` must equal `expected` (True by default).\"\"\"
    ok = bool(got == expected)
    emit(label=label, ok=ok, **({} if ok else {"got": repr(got), "expected": repr(expected)}))


def raises(label, exception, function, *args, **kwargs):
    \"\"\"One test case: calling `function` must raise `exception`.\"\"\"
    try:
        function(*args, **kwargs)
    except exception:
        return emit(label=label, ok=True)
    except Exception as e:
        return emit(label=label, ok=False, got=f"{type(e).__name__}: {e}", expected=exception.__name__)
    emit(label=label, ok=False, got="no exception", expected=exception.__name__)


def user_frames(e):
    return [f for f in traceback.extract_tb(e.__traceback__) if f.filename == source]


try:
    spec = importlib.util.spec_from_file_location("solution", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
except Exception as e:
    lines = traceback.format_list(user_frames(e)) + traceback.format_exception_only(e)
    sys.stderr.write("".join(lines))
    sys.exit(1)

scope = {**vars(module), "check": check, "raises": raises}
try:
    exec(compile(open(checks_path).read(), "checks", "exec"), scope)
except Exception as e:
    frames = user_frames(e)
    where = f" (line {frames[-1].lineno})" if frames else ""
    emit(label="the remaining checks", ok=False, error=f"{type(e).__name__}: {e}{where}")
print("@@DRILL " + json.dumps({"done": count}), flush=True)
"""


class Python(Language):
    key, label, filename, comment = "python", "Python", "solution.py", "#"

    def literal(self, value) -> str:
        return repr(value)

    def _run_code(self, ex: Exercise, source: Path, build: Path) -> Outcome:
        harness, checks = build / "code_harness.py", build / f"{ex.key}.checks.py"
        harness.write_text(PY_CODE_HARNESS)
        setup = textwrap.dedent(ex.setup.get(self.key, ""))
        checks.write_text(f"{setup}\n{textwrap.dedent(ex.checks[self.key])}")
        proc, error = _execute([sys.executable, str(harness), str(source), str(checks)], build)
        if error:
            return Outcome(1, error=error)
        return _collect(proc, None, {str(source): self.filename, str(build) + "/": ""})

    def ident(self, name: str) -> str:
        return name

    def type_name(self, t) -> str:
        if isinstance(t, tuple):
            return f"list[{self.type_name(t[1])}]"
        return {"int": "int", "long": "int", "bool": "bool", "str": "str", "any": "object"}[t]

    def skeleton(self, ex: Exercise) -> str:
        params = ", ".join(f"{p}: {self.type_name(t)}" for p, t in ex.params)
        return f"def {ex.name}({params}) -> {self.type_name(ex.returns)}:\n    pass\n"

    def _run(self, ex: Exercise, source: Path, build: Path, cases: list[dict], tag: str) -> Outcome:
        harness, data = build / "harness.py", build / f"{ex.key}.{tag}.json"
        harness.write_text(PY_HARNESS)
        if not data.exists():
            data.write_text(json.dumps(cases))
        cmd = [sys.executable, str(harness), str(source), str(data), ex.name, str(REPEAT_BUDGET_US)]
        proc, error = _execute(cmd, build, _run_timeout(cases))
        if error:
            return Outcome(len(cases), error=error)
        return _collect(proc, len(cases), {str(source): self.filename, str(build) + "/": ""})


CPP_HARNESS = r"""
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <exception>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>
#include <sys/time.h>
#include <unistd.h>

static std::string drill_json(int v) { return std::to_string(v); }
static std::string drill_json(long long v) { return std::to_string(v); }
static std::string drill_json(bool v) { return v ? "true" : "false"; }
static std::string drill_json(const std::string& s) {
    std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (c < 0x20) { char buf[8]; std::snprintf(buf, sizeof buf, "\\u%04x", c); out += buf; }
        else out += c;
    }
    return out + "\"";
}
template <class T>
static std::string drill_json(const std::vector<T>& v) {
    std::string out = "[";
    for (std::size_t i = 0; i < v.size(); ++i) {
        if (i) out += ", ";
        out += drill_json(static_cast<T>(v[i]));
    }
    return out + "]";
}

static void drill_read(std::istream& in, int& v) { in >> v; }
static void drill_read(std::istream& in, long long& v) { in >> v; }
static void drill_read(std::istream& in, bool& v) { int x; in >> x; v = x; }
static void drill_read(std::istream& in, std::string& v) {
    std::size_t n;
    in >> n;
    in.get();
    v.resize(n);
    in.read(v.data(), n);
}
template <class T>
static void drill_read(std::istream& in, std::vector<T>& v) {
    std::size_t n;
    in >> n;
    v.clear();
    v.reserve(n);
    for (std::size_t i = 0; i < n; ++i) { T x; drill_read(in, x); v.push_back(std::move(x)); }
}

static volatile std::sig_atomic_t drill_current = 0;

// Runs in a signal handler: only async-signal-safe calls
static void drill_on_alarm(int) {
    char buf[96] = "@@DRILL {\"i\": ";
    std::size_t n = std::strlen(buf);
    char digits[12];
    int k = 0;
    long i = drill_current;
    do { digits[k++] = char('0' + i % 10); i /= 10; } while (i);
    while (k) buf[n++] = digits[--k];
    for (const char* p = ", \"ok\": false, \"timeout\": true}\n"; *p; ++p) buf[n++] = *p;
    ssize_t written = write(1, buf, n);
    (void)written;
    _exit(0);
}

static void drill_arm(double seconds) {
    itimerval timer{};
    timer.it_value.tv_sec = (time_t)seconds;
    timer.it_value.tv_usec = (suseconds_t)((seconds - (double)timer.it_value.tv_sec) * 1e6);
    setitimer(ITIMER_REAL, &timer, nullptr);
}

static void drill_report(int i, bool ok, double us, const std::string& got) {
    std::cout << "@@DRILL {\"i\": " << i << ", \"ok\": " << (ok ? "true" : "false") << ", \"us\": " << us;
    if (!ok) std::cout << ", \"got\": " << got;
    std::cout << "}" << std::endl;
}
static void drill_error(int i, const std::string& what) {
    std::cout << "@@DRILL {\"i\": " << i << ", \"ok\": false, \"error\": " << drill_json(what)
              << "}" << std::endl;
}
"""


CPP_CODE_HARNESS = r"""
#include <cstdio>
#include <exception>
#include <iostream>
#include <iterator>
#include <sstream>
#include <string>
#include <type_traits>

static int drill_count = 0;

static std::string drill_quote(const std::string& s) {
    std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += c; }
        else if (c < 0x20) { char buf[8]; std::snprintf(buf, sizeof buf, "\\u%04x", c); out += buf; }
        else out += c;
    }
    return out + "\"";
}

// A readable rendering of any value, for failure reports
template <class T>
static std::string drill_show(const T& v) {
    if constexpr (std::is_same_v<T, bool>) return v ? "true" : "false";
    else if constexpr (requires { v.has_value(); *v; })
        return v.has_value() ? "optional(" + drill_show(*v) + ")" : "nullopt";
    else if constexpr (requires { v.first; v.second; })
        return "(" + drill_show(v.first) + ", " + drill_show(v.second) + ")";
    else if constexpr (requires(std::ostream& os) { os << v; }) {
        std::ostringstream os;
        os << v;
        return os.str();
    } else if constexpr (requires { std::begin(v); std::end(v); }) {
        std::string out = "[";
        for (auto it = std::begin(v); it != std::end(v); ++it)
            out += (it == std::begin(v) ? "" : ", ") + drill_show(*it);
        return out + "]";
    } else return "<value>";
}

static void drill_emit(const std::string& label, bool ok, const std::string& got, const std::string& expected) {
    std::cout << "@@DRILL {\"i\": " << drill_count++ << ", \"label\": " << drill_quote(label)
              << ", \"ok\": " << (ok ? "true" : "false");
    if (!ok) std::cout << ", \"got\": " << drill_quote(got) << ", \"expected\": " << drill_quote(expected);
    std::cout << "}" << std::endl;
}

static void drill_stopped(const std::string& what) {
    std::cout << "@@DRILL {\"i\": " << drill_count++ << ", \"label\": \"the remaining checks\", "
              << "\"ok\": false, \"error\": " << drill_quote(what) << "}" << std::endl;
}

#define CHECK(...) drill_emit(#__VA_ARGS__, static_cast<bool>(__VA_ARGS__), "false", "true")
#define CHECK_EQ(a, ...)                                                                   \
    do {                                                                                   \
        const auto& drill_got = (a);                                                       \
        const auto& drill_want = (__VA_ARGS__);                                            \
        bool drill_ok = drill_got == drill_want;                                           \
        drill_emit(#a " == " #__VA_ARGS__, drill_ok, drill_ok ? "" : drill_show(drill_got), \
                   drill_ok ? "" : drill_show(drill_want));                                \
    } while (0)
#define CHECK_THROWS(type, ...)                                                            \
    do {                                                                                   \
        bool drill_ok = false;                                                             \
        std::string drill_what = "no exception";                                           \
        try { __VA_ARGS__; }                                                               \
        catch (const type&) { drill_ok = true; }                                           \
        catch (const std::exception& e) { drill_what = e.what(); }                         \
        catch (...) { drill_what = "another exception"; }                                  \
        drill_emit(#__VA_ARGS__ " throws " #type, drill_ok, drill_what, #type);            \
    } while (0)
"""


class Cpp(Language):
    key, label, filename, comment = "cpp", "C++", "solution.cpp", "//"
    PRELUDE = "#include <bits/stdc++.h>\nusing namespace std;\n"
    FLAGS = ["-std=c++20", "-O1", "-pipe"]
    _pch_lock = threading.Lock()

    def warm_up(self) -> None:
        threading.Thread(target=self.pch, daemon=True).start()

    def pch(self) -> Path | None:
        """A precompiled <bits/stdc++.h>, built once per compiler and cached.

        Parsing that header is most of the compile time: this takes each run from
        about 1.4s down to 0.4s.
        """
        with self._pch_lock:
            compiler = shutil.which("g++")
            if compiler is None:
                return None
            key = f"{os.path.realpath(compiler)} {' '.join(self.FLAGS)}"
            folder = cache_dir() / f"pch-{hashlib.sha1(key.encode()).hexdigest()[:12]}"
            header, compiled = folder / "drill.h", folder / "drill.h.gch"
            if compiled.exists():
                return header
            folder.mkdir(parents=True, exist_ok=True)
            header.write_text("#include <bits/stdc++.h>\n")
            partial = folder / f"drill.h.gch.{os.getpid()}"
            cmd = ["g++", *self.FLAGS, "-x", "c++-header", str(header), "-o", str(partial)]
            proc, error = _execute(cmd, folder, timeout=120)
            if error or proc.returncode != 0:
                partial.unlink(missing_ok=True)
                return None
            partial.rename(compiled)
            return header

    def type_name(self, t, std: str = "") -> str:
        if isinstance(t, tuple):
            return f"{std}vector<{self.type_name(t[1], std)}>"
        return {"int": "int", "long": "long long", "bool": "bool", "str": f"{std}string"}[t]

    def param(self, name: str, t) -> str:
        if isinstance(t, tuple):
            return f"{self.type_name(t)}& {camel(name)}"
        if t == "str":
            return f"const string& {camel(name)}"
        return f"{self.type_name(t)} {camel(name)}"

    def skeleton(self, ex: Exercise) -> str:
        params = ", ".join(self.param(p, t) for p, t in ex.params)
        signature = f"{self.type_name(ex.returns)} {camel(ex.name)}({params})"
        return f"{self.PRELUDE}\n{signature} {{\n    \n}}\n"

    def complete(self, code: str) -> str:
        return f"{self.PRELUDE}\n{code}\n"

    def harness(self, ex: Exercise, source: Path) -> str:
        ret = self.type_name(ex.returns, "std::")
        reads = [
            f"        {self.type_name(t, 'std::')} drill_a{j};\n        drill_read(drill_in, drill_a{j});"
            for j, (_, t) in enumerate(ex.params)
        ]
        # Each call gets fresh copies, since solutions may modify their inputs
        copies = "\n".join(f"                auto drill_c{j} = drill_a{j};" for j in range(len(ex.params)))
        call_args = ", ".join(f"drill_c{j}" for j in range(len(ex.params)))
        return CPP_HARNESS + f"""
#include {json.dumps(str(source))}

int main(int argc, char** argv) {{
    std::signal(SIGALRM, drill_on_alarm);
    std::ifstream drill_in(argv[1], std::ios::binary);
    int drill_total;
    drill_in >> drill_total;
    for (int drill_i = 0; drill_i < drill_total; ++drill_i) {{
        double drill_limit;
        int drill_repeat;
        drill_in >> drill_limit >> drill_repeat;
{chr(10).join(reads)}
        {ret} drill_expected;
        drill_read(drill_in, drill_expected);
        drill_current = drill_i;
        try {{
            {ret} drill_got;
            double drill_us = 0;
            int drill_calls = 0;
            do {{
{copies}
                if (drill_limit > 0) drill_arm(drill_limit);
                auto drill_start = std::chrono::steady_clock::now();
                drill_got = {camel(ex.name)}({call_args});
                drill_us += std::chrono::duration<double, std::micro>(
                    std::chrono::steady_clock::now() - drill_start).count();
                drill_arm(0);
                ++drill_calls;
            }} while (drill_repeat && drill_us < {REPEAT_BUDGET_US} && drill_calls < 200);
            bool drill_ok = drill_got == drill_expected;
            drill_report(drill_i, drill_ok, drill_us / drill_calls,
                         drill_ok ? std::string() : drill_json(drill_got));
        }} catch (const std::exception& e) {{
            drill_arm(0);
            drill_error(drill_i, e.what());
        }} catch (...) {{
            drill_arm(0);
            drill_error(drill_i, "unknown exception");
        }}
    }}
}}
"""

    def code_harness(self, ex: Exercise, source: Path) -> str:
        return CPP_CODE_HARNESS + f"""
#include {json.dumps(str(source))}

{textwrap.dedent(ex.setup.get(self.key, ""))}
static void drill_checks() {{
{textwrap.indent(textwrap.dedent(ex.checks[self.key]), "    ")}
}}

int main() {{
    try {{
        drill_checks();
    }} catch (const std::exception& e) {{
        drill_stopped(std::string("exception: ") + e.what());
    }} catch (...) {{
        drill_stopped("unknown exception");
    }}
    std::cout << "@@DRILL {{\\"done\\": " << drill_count << "}}" << std::endl;
}}
"""

    def _run(self, ex: Exercise, source: Path, build: Path, cases: list[dict], tag: str) -> Outcome:
        main = self.harness(ex, source)
        args = [str(_data_file(ex, cases, tag, build))]
        return self._build_and_run(main, args, len(cases), source, build, _run_timeout(cases))

    def _run_code(self, ex: Exercise, source: Path, build: Path) -> Outcome:
        return self._build_and_run(self.code_harness(ex, source), [], None, source, build, TIMEOUT)

    def _build_and_run(
        self, main_source: str, args: list[str], total: int | None, source: Path, build: Path,
        timeout: float,
    ) -> Outcome:
        paths = {str(source): self.filename, str(build) + "/": ""}
        main, exe = build / "main.cpp", build / "run"
        main.write_text(main_source)
        exe.unlink(missing_ok=True)
        pch = self.pch()
        cmd = ["g++", *self.FLAGS, "-fdiagnostics-color=never", "-Werror=return-type"]
        cmd += ["-include", str(pch)] if pch else []
        proc, error = _execute([*cmd, "-o", str(exe), str(main)], build)
        if error:
            return Outcome(total or 1, error=error)
        if proc.returncode != 0:
            details = _tidy(proc.stderr, paths)[:MAX_ERROR_LINES]
            return Outcome(total or 1, error="\n".join(["compilation failed", *details]))
        proc, error = _execute([str(exe), *args], build, timeout, big_stack=True)
        return Outcome(total or 1, error=error) if error else _collect(proc, total, paths)


JAVA_HARNESS = r"""
import java.lang.reflect.Array;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.*;

public class Main {
    static byte[] data;
    static int pos;
    static volatile int current = -1;
    static volatile long deadline = Long.MAX_VALUE;

    static void skipSpace() {
        while (data[pos] == ' ' || data[pos] == '\n') pos++;
    }

    static long nextLong() {
        skipSpace();
        boolean negative = data[pos] == '-';
        if (negative) pos++;
        long v = 0;
        while (pos < data.length && data[pos] >= '0' && data[pos] <= '9') v = v * 10 + (data[pos++] - '0');
        return negative ? -v : v;
    }

    static double nextDouble() {
        skipSpace();
        int start = pos;
        while (pos < data.length && data[pos] != ' ' && data[pos] != '\n') pos++;
        return Double.parseDouble(new String(data, start, pos - start, StandardCharsets.US_ASCII));
    }

    static Class<?> component(String spec) {
        switch (spec) {
            case "int": return int.class;
            case "long": return long.class;
            case "bool": return boolean.class;
            case "str": return String.class;
            default: return component(spec.substring(5, spec.length() - 1)).arrayType();
        }
    }

    static Object read(String spec) {
        switch (spec) {
            case "int": return (int) nextLong();
            case "long": return nextLong();
            case "bool": return nextLong() != 0;
            case "str": {
                int n = (int) nextLong();
                pos++;
                String s = new String(data, pos, n, StandardCharsets.UTF_8);
                pos += n;
                return s;
            }
            default: {
                String inner = spec.substring(5, spec.length() - 1);
                int n = (int) nextLong();
                Object array = Array.newInstance(component(inner), n);
                for (int i = 0; i < n; i++) Array.set(array, i, read(inner));
                return array;
            }
        }
    }

    static String json(Object o) {
        if (o == null) return "null";
        if (o instanceof String s) return quote(s);
        if (o instanceof Number || o instanceof Boolean) return o.toString();
        if (o.getClass().isArray()) {
            StringBuilder sb = new StringBuilder("[");
            for (int i = 0; i < Array.getLength(o); i++) {
                if (i > 0) sb.append(", ");
                sb.append(json(Array.get(o, i)));
            }
            return sb.append("]").toString();
        }
        if (o instanceof Iterable<?> items) {
            StringJoiner sj = new StringJoiner(", ", "[", "]");
            for (Object item : items) sj.add(json(item));
            return sj.toString();
        }
        return quote(o.toString());
    }

    static String quote(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') sb.append('\\').append(c);
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        return sb.append('"').toString();
    }

    // A deep copy of an input, since solutions may modify their arrays
    static Object copy(Object o) {
        if (o instanceof int[] a) return a.clone();
        if (o instanceof long[] a) return a.clone();
        if (o instanceof boolean[] a) return a.clone();
        if (o instanceof Object[] a) {
            Object[] c = a.clone();
            for (int i = 0; i < c.length; i++) c[i] = copy(c[i]);
            return c;
        }
        return o;  // boxed primitives and strings are immutable
    }

    static void report(int i, Object got, Object expected, double us) {
        boolean ok = Objects.deepEquals(got, expected);
        String line = "@@DRILL {\"i\": " + i + ", \"ok\": " + ok + ", \"us\": " + us;
        System.out.println(line + (ok ? "" : ", \"got\": " + json(got)) + "}");
        System.out.flush();
    }

    static void error(int i, Throwable e) {
        System.out.println("@@DRILL {\"i\": " + i + ", \"ok\": false, \"error\": " + quote(e.toString()) + "}");
        System.out.flush();
    }

    // Stops the run as soon as the current case goes over its time limit
    static void startWatchdog() {
        Thread watchdog = new Thread(() -> {
            while (true) {
                try {
                    Thread.sleep(5);
                } catch (InterruptedException e) {
                    return;
                }
                if (System.nanoTime() > deadline) {
                    System.out.println("@@DRILL {\"i\": " + current + ", \"ok\": false, \"timeout\": true}");
                    System.out.flush();
                    Runtime.getRuntime().halt(0);
                }
            }
        });
        watchdog.setDaemon(true);
        watchdog.start();
    }
"""


JAVA_CODE_HARNESS = r"""
import java.util.*;
import java.util.function.*;
import java.util.stream.*;

public class Main {
    static int count = 0;

    interface Body {
        void run() throws Throwable;
    }

    static String quote(String s) {
        StringBuilder sb = new StringBuilder("\"");
        for (char c : s.toCharArray()) {
            if (c == '"' || c == '\\') sb.append('\\').append(c);
            else if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
            else sb.append(c);
        }
        return sb.append('"').toString();
    }

    static String show(Object o) {
        if (o == null) return "null";
        if (o instanceof String s) return "\"" + s + "\"";
        if (o instanceof Object[] a) return Arrays.deepToString(a);
        if (o instanceof int[] a) return Arrays.toString(a);
        if (o instanceof long[] a) return Arrays.toString(a);
        if (o instanceof double[] a) return Arrays.toString(a);
        if (o instanceof char[] a) return Arrays.toString(a);
        if (o instanceof boolean[] a) return Arrays.toString(a);
        return String.valueOf(o);
    }

    static void emit(String label, boolean ok, String got, String expected) {
        String line = "@@DRILL {\"i\": " + count++ + ", \"label\": " + quote(label) + ", \"ok\": " + ok;
        if (!ok) line += ", \"got\": " + quote(got) + ", \"expected\": " + quote(expected);
        System.out.println(line + "}");
    }

    /** One test case: the condition must hold. */
    static void check(String label, boolean ok) {
        emit(label, ok, "false", "true");
    }

    /** One test case: got must equal expected (arrays are compared deeply). */
    static void check(String label, Object got, Object expected) {
        emit(label, Objects.deepEquals(got, expected), show(got), show(expected));
    }

    /** One test case: body must throw an exception of the given type. */
    static void checkThrows(String label, Class<? extends Throwable> type, Body body) {
        try {
            body.run();
            emit(label, false, "no exception", type.getSimpleName());
        } catch (Throwable e) {
            emit(label, type.isInstance(e), e.toString(), type.getSimpleName());
        }
    }

    static void stopped(Throwable e) {
        System.out.println("@@DRILL {\"i\": " + count++ + ", \"label\": \"the remaining checks\", "
            + "\"ok\": false, \"error\": " + quote(e.toString()) + "}");
    }
"""


class Java(Language):
    key, label, filename, comment = "java", "Java", "Solution.java", "//"
    IMPORTS = "import java.util.*;\nimport java.util.stream.*;\n"

    def type_name(self, t) -> str:
        if isinstance(t, tuple):
            return self.type_name(t[1]) + "[]"
        return {"int": "int", "long": "long", "bool": "boolean", "str": "String"}[t]

    def skeleton(self, ex: Exercise) -> str:
        params = ", ".join(f"{self.type_name(t)} {camel(p)}" for p, t in ex.params)
        signature = f"public {self.type_name(ex.returns)} {camel(ex.name)}({params})"
        return f"{self.IMPORTS}\nclass Solution {{\n    {signature} {{\n        \n    }}\n}}\n"

    def complete(self, code: str) -> str:
        return f"{self.IMPORTS}\nclass Solution {{\n{textwrap.indent(code, '    ')}\n}}\n"

    def harness(self, ex: Exercise) -> str:
        ret = self.type_name(ex.returns)
        args = ", ".join(f"a{j}" for j in range(len(ex.params)))
        reads = [
            f'            {self.type_name(t)} a{j} = ({self.type_name(t)}) read("{type_spec(t)}");'
            for j, (_, t) in enumerate(ex.params)
        ]
        # Each call gets fresh copies of the arrays, since solutions may modify them
        copies = "\n".join(
            f"                    {self.type_name(t)} c{j} = ({self.type_name(t)}) copy(a{j});"
            if isinstance(t, tuple) else f"                    {self.type_name(t)} c{j} = a{j};"
            for j, (_, t) in enumerate(ex.params)
        )
        args = ", ".join(f"c{j}" for j in range(len(ex.params)))
        return JAVA_HARNESS + f"""
    public static void main(String[] args) throws Exception {{
        data = Files.readAllBytes(java.nio.file.Path.of(args[0]));
        startWatchdog();
        int total = (int) nextLong();
        for (int i = 0; i < total; i++) {{
            double limit = nextDouble();
            boolean repeat = nextLong() != 0;
{chr(10).join(reads)}
            {ret} expected = ({ret}) read("{type_spec(ex.returns)}");
            current = i;
            try {{
                {ret} got;
                double us = 0;
                int calls = 0;
                do {{
{copies}
                    long start = System.nanoTime();
                    if (limit > 0) deadline = start + (long) (limit * 1e9);
                    got = new Solution().{camel(ex.name)}({args});
                    us += (System.nanoTime() - start) / 1e3;
                    deadline = Long.MAX_VALUE;
                    calls++;
                }} while (repeat && us < {REPEAT_BUDGET_US} && calls < 200);
                report(i, got, expected, us / calls);
            }} catch (Throwable e) {{
                deadline = Long.MAX_VALUE;
                error(i, e);
            }}
        }}
    }}
}}
"""

    def code_harness(self, ex: Exercise) -> str:
        setup = textwrap.indent(textwrap.dedent(ex.setup.get(self.key, "")), "    ")
        checks = textwrap.indent(textwrap.dedent(ex.checks[self.key]), "        ")
        return JAVA_CODE_HARNESS + f"""
{setup}
    static void checks() throws Throwable {{
{checks}
    }}

    public static void main(String[] args) {{
        try {{
            checks();
        }} catch (Throwable e) {{
            stopped(e);
        }}
        System.out.println("@@DRILL {{\\"done\\": " + count + "}}");
    }}
}}
"""

    def _run(self, ex: Exercise, source: Path, build: Path, cases: list[dict], tag: str) -> Outcome:
        args = [str(_data_file(ex, cases, tag, build))]
        return self._build_and_run(self.harness(ex), args, len(cases), source, build, _run_timeout(cases))

    def _run_code(self, ex: Exercise, source: Path, build: Path) -> Outcome:
        return self._build_and_run(self.code_harness(ex), [], None, source, build, TIMEOUT)

    def _build_and_run(
        self, main_source: str, args: list[str], total: int | None, source: Path, build: Path,
        timeout: float,
    ) -> Outcome:
        paths = {str(source): self.filename, str(build) + "/": ""}
        main, classes = build / "Main.java", build / "classes"
        main.write_text(main_source)
        shutil.rmtree(classes, ignore_errors=True)
        cmd = ["javac", "-d", str(classes), "-encoding", "UTF-8", "-nowarn", str(source), str(main)]
        proc, error = _execute(cmd, build)
        if error:
            return Outcome(total or 1, error=error)
        if proc.returncode != 0:
            details = _tidy(proc.stderr, paths)[:MAX_ERROR_LINES]
            return Outcome(total or 1, error="\n".join(["compilation failed", *details]))
        # The watchdog's halt() needs a safepoint: without polls inside counted loops, a
        # hot O(n²) loop would only be stopped once it finishes
        cmd = ["java", "-Xss512m", "-XX:+UseSerialGC", "-Xms1g", "-Xmn512m", "-XX:+UseCountedLoopSafepoints",
               "-XX:LoopStripMiningIter=1000", "-cp", str(classes), "Main"]
        proc, error = _execute([*cmd, *args], build, timeout)
        return Outcome(total or 1, error=error) if error else _collect(proc, total, paths)


OCAML_COMMON = r"""
let drill_quote s =
  let b = Buffer.create (String.length s + 2) in
  Buffer.add_char b '"';
  String.iter
    (fun c ->
      if c = '"' || c = '\\' then (Buffer.add_char b '\\'; Buffer.add_char b c)
      else if Char.code c < 0x20 then Buffer.add_string b (Printf.sprintf "\\u%04x" (Char.code c))
      else Buffer.add_char b c)
    s;
  Buffer.add_char b '"';
  Buffer.contents b

let drill_print line = print_string ("@@DRILL " ^ line ^ "\n"); flush stdout
"""

OCAML_HARNESS = OCAML_COMMON + r"""
let drill_data = In_channel.with_open_bin Sys.argv.(1) In_channel.input_all
let drill_pos = ref 0

let drill_token () =
  let n = String.length drill_data in
  while !drill_pos < n && (drill_data.[!drill_pos] = ' ' || drill_data.[!drill_pos] = '\n') do incr drill_pos done;
  let start = !drill_pos in
  while !drill_pos < n && drill_data.[!drill_pos] <> ' ' && drill_data.[!drill_pos] <> '\n' do incr drill_pos done;
  String.sub drill_data start (!drill_pos - start)

let read_int () = int_of_string (drill_token ())
let read_float () = float_of_string (drill_token ())
let read_bool () = read_int () <> 0
let read_string () =
  let n = read_int () in
  incr drill_pos;
  let s = String.sub drill_data !drill_pos n in
  drill_pos := !drill_pos + n;
  s
let read_list item () =
  let rec go acc k = if k = 0 then List.rev acc else go (item () :: acc) (k - 1) in
  go [] (read_int ())

let json_int = string_of_int
let json_bool b = if b then "true" else "false"
let json_string = drill_quote
let json_list item l = "[" ^ String.concat ", " (List.map item l) ^ "]"

let drill_current = ref 0
let drill_arm seconds =
  ignore (Unix.setitimer Unix.ITIMER_REAL { Unix.it_interval = 0.; it_value = seconds })

let () =
  Sys.set_signal Sys.sigalrm
    (Sys.Signal_handle
       (fun _ ->
         drill_print (Printf.sprintf "{\"i\": %d, \"ok\": false, \"timeout\": true}" !drill_current);
         exit 0));
  let total = read_int () in
  for i = 0 to total - 1 do
    let limit = read_float () in
    let repeat = read_int () <> 0 in
@READS@
    let expected = @READ_RETURN@ () in
    drill_current := i;
    try
      let got = ref None and us = ref 0. and calls = ref 0 and again = ref true in
      while !again do
        if limit > 0. then drill_arm limit;
        let start = Unix.gettimeofday () in
        let result = Solution.@NAME@ @ARGS@ in
        us := !us +. ((Unix.gettimeofday () -. start) *. 1e6);
        drill_arm 0.;
        incr calls;
        got := Some result;
        again := repeat && !us < @BUDGET@. && !calls < 200
      done;
      let got = Option.get !got in
      let ok = got = expected in
      drill_print
        (Printf.sprintf "{\"i\": %d, \"ok\": %b, \"us\": %f%s}" i ok (!us /. float !calls)
           (if ok then "" else ", \"got\": " ^ @JSON_RETURN@ got))
    with e ->
      drill_arm 0.;
      drill_print (Printf.sprintf "{\"i\": %d, \"ok\": false, \"error\": %s}" i (drill_quote (Printexc.to_string e)))
  done
"""

OCAML_CODE_HARNESS = OCAML_COMMON + r"""
let drill_count = ref 0

let drill_emit label ok got expected =
  let fields = if ok then "" else Printf.sprintf ", \"got\": %s, \"expected\": %s" (drill_quote got) (drill_quote expected) in
  drill_print (Printf.sprintf "{\"i\": %d, \"label\": %s, \"ok\": %b%s}" !drill_count (drill_quote label) ok fields);
  incr drill_count

(* Printers for check_eq ~show *)
module Show = struct
  let int = string_of_int
  let bool = string_of_bool
  let float = string_of_float
  let string s = Printf.sprintf "%S" s
  let char c = Printf.sprintf "%C" c
  let list item l = "[" ^ String.concat "; " (List.map item l) ^ "]"
  let array item a = "[|" ^ String.concat "; " (Array.to_list (Array.map item a)) ^ "|]"
  let option item = function None -> "None" | Some x -> "Some (" ^ item x ^ ")"
  let pair f g (a, b) = "(" ^ f a ^ ", " ^ g b ^ ")"
  let result ok error = function Ok x -> "Ok (" ^ ok x ^ ")" | Error e -> "Error (" ^ error e ^ ")"
end

(* One test case: the condition must hold *)
let check label ok = drill_emit label ok "false" "true"

(* One test case: got must equal expected (structural equality) *)
let check_eq ?(show = fun _ -> "<value>") label got expected =
  let ok = got = expected in
  drill_emit label ok (if ok then "" else show got) (if ok then "" else show expected)

(* One test case: f () must raise an exception, one that `matches` accepts *)
let check_raises ?(matches = fun _ -> true) label f =
  match f () with
  | _ -> drill_emit label false "no exception" "an exception"
  | exception e -> drill_emit label (matches e) (Printexc.to_string e) "another exception"

open Solution

@SETUP@

let drill_checks () = begin
@CHECKS@
end

(* The line of main.ml where an exception escaped the checks: the check that raised it *)
let drill_line () =
  match Printexc.backtrace_slots (Printexc.get_raw_backtrace ()) with
  | None -> 0
  | Some slots ->
      Array.fold_left
        (fun found slot ->
          match Printexc.Slot.location slot with
          | Some { Printexc.filename = "main.ml"; line_number; _ } when found = 0 -> line_number
          | _ -> found)
        0 slots

let () =
  Printexc.record_backtrace true;
  (try drill_checks ()
   with e ->
     drill_print
       (Printf.sprintf "{\"i\": %d, \"label\": \"the remaining checks\", \"line\": %d, \"ok\": false, \"error\": %s}"
          !drill_count (drill_line ()) (drill_quote (Printexc.to_string e)));
     incr drill_count);
  drill_print (Printf.sprintf "{\"done\": %d}" !drill_count)
"""


class OCaml(Language):
    key, label, filename, comment = "ocaml", "OCaml", "solution.ml", "(*"

    def ident(self, name: str) -> str:
        return name

    def header(self, lines: list[str]) -> str:
        return "\n".join(["(*", *(f"   {line}".rstrip() for line in lines), "*)"])

    def literal(self, value, nested: bool = False) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return f"({value})" if value < 0 and not nested else str(value)
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return "[" + "; ".join(self.literal(v, nested=True) for v in value) + "]"

    def call(self, ex: Exercise, test: dict) -> str:
        return " ".join([ex.name, *(self.literal(a) for a in test["in"])])

    def type_name(self, t) -> str:
        if isinstance(t, tuple):
            return f"{self.type_name(t[1])} list"
        return {"int": "int", "long": "int", "bool": "bool", "str": "string"}[t]

    def skeleton(self, ex: Exercise) -> str:
        params = " ".join(f"({p} : {self.type_name(t)})" for p, t in ex.params)
        return f"let {ex.name} {params} : {self.type_name(ex.returns)} =\n  failwith \"todo\"\n"

    @staticmethod
    def _reader(t) -> str:
        if isinstance(t, tuple):
            return f"(read_list {OCaml._reader(t[1])})"
        return {"int": "read_int", "long": "read_int", "bool": "read_bool", "str": "read_string"}[t]

    @staticmethod
    def _printer(t) -> str:
        if isinstance(t, tuple):
            return f"(json_list {OCaml._printer(t[1])})"
        return {"int": "json_int", "long": "json_int", "bool": "json_bool", "str": "json_string"}[t]

    def harness(self, ex: Exercise) -> str:
        reads = "\n".join(f"    let a{j} = {self._reader(t)} () in" for j, (_, t) in enumerate(ex.params))
        args = " ".join(f"a{j}" for j in range(len(ex.params))) or "()"
        return (
            OCAML_HARNESS.replace("@READS@", reads)
            .replace("@READ_RETURN@", self._reader(ex.returns))
            .replace("@JSON_RETURN@", self._printer(ex.returns))
            .replace("@NAME@", ex.name)
            .replace("@ARGS@", args)
            .replace("@BUDGET@", str(REPEAT_BUDGET_US))
        )

    def code_harness(self, ex: Exercise) -> str:
        return (
            OCAML_CODE_HARNESS.replace("@SETUP@", textwrap.dedent(ex.setup.get(self.key, "")))
            .replace("@CHECKS@", textwrap.indent(textwrap.dedent(ex.checks[self.key]).strip(), "  "))
        )

    def _run(self, ex: Exercise, source: Path, build: Path, cases: list[dict], tag: str) -> Outcome:
        args = [str(_data_file(ex, cases, tag, build))]
        return self._build_and_run(self.harness(ex), args, len(cases), source, build, _run_timeout(cases))

    def _run_code(self, ex: Exercise, source: Path, build: Path) -> Outcome:
        return self._build_and_run(self.code_harness(ex), [], None, source, build, TIMEOUT)

    def _build_and_run(
        self, main_source: str, args: list[str], total: int | None, source: Path, build: Path,
        timeout: float,
    ) -> Outcome:
        # Compiled from the build folder, so the module is Solution and errors name solution.ml
        paths = {str(build) + "/": "", 'File "main.ml"': 'File "harness"'}
        shutil.copyfile(source, build / "solution.ml")
        (build / "main.ml").write_text(main_source)
        exe = build / "run"
        exe.unlink(missing_ok=True)
        # Not ocamlfind: it may belong to another OCaml than the ocamlopt on PATH
        cmd = ["ocamlopt", "-I", "+unix", "unix.cmxa", "-w", "-a", "-g"]
        proc, error = _execute([*cmd, "solution.ml", "main.ml", "-o", "run"], build)
        if error:
            return Outcome(total or 1, error=error)
        if proc.returncode != 0:
            details = _tidy(proc.stderr, paths)[:MAX_ERROR_LINES]
            return Outcome(total or 1, error="\n".join(["compilation failed", *details]))
        proc, error = _execute([str(exe), *args], build, timeout, big_stack=True)
        if error:
            return Outcome(total or 1, error=error)
        outcome = _collect(proc, total, paths)
        lines = main_source.splitlines()
        for result in outcome.results:
            if 0 < result.get("line", 0) <= len(lines):
                result["label"] = lines[result["line"] - 1].strip()
        return outcome


NIX_LIB = r"""
# raw: no tryEval, so that a throw stops the evaluation with its message
{ nixpkgs, raw ? false }:
let
  lib = import (nixpkgs + "/lib");
  system = builtins.currentSystem;
  # Only evaluated when a check uses them
  pkgs = import nixpkgs { inherit system; config = { }; overlays = [ ]; };
  nixpkgsFlake = builtins.getFlake "path:${nixpkgs}";

  # A value that can be shown: functions and derivations become a description
  sanitize = depth: v:
    if builtins.isFunction v then "«lambda»"
    else if lib.isDerivation v then "«derivation ${v.name or "?"}»"
    else if builtins.isPath v then toString v
    else if builtins.isAttrs v then
      (if depth == 0 then "«attrset»" else builtins.mapAttrs (_: sanitize (depth - 1)) v)
    else if builtins.isList v then
      (if depth == 0 then "«list»" else map (sanitize (depth - 1)) v)
    else if builtins.isString v then builtins.unsafeDiscardStringContext v
    else v;
  show = v:
    let r = builtins.tryEval (builtins.toJSON (sanitize 4 v));
    in if r.success then r.value else "«cannot be shown»";
in
rec {
  inherit lib system pkgs nixpkgs;

  # One test case: got must equal expected (true by default)
  check = label: got: expected:
    let r = if raw then { success = true; value = got == expected; } else builtins.tryEval (got == expected);
    in
    if !r.success then { inherit label; ok = false; error = "evaluation failed (a throw or an assert)"; }
    else if r.value then { inherit label; ok = true; }
    else { inherit label; ok = false; got = show got; expected = show expected; };

  # One test case: evaluating value must fail with a throw or an assert
  checkThrows = label: value:
    let r = builtins.tryEval (builtins.deepSeq value value);
    in { inherit label; ok = !r.success; } // lib.optionalAttrs r.success { got = show value; expected = "a throw"; };

  # Whether a string contains another, store paths included
  contains = needle: haystack:
    lib.hasInfix (builtins.unsafeDiscardStringContext needle) (builtins.unsafeDiscardStringContext haystack);

  # The names of the packages a derivation or a shell is built with
  packageNames = drv: map lib.getName (lib.concatMap (attr: drv.${attr} or [ ]) [
    "nativeBuildInputs" "buildInputs" "propagatedBuildInputs" "propagatedNativeBuildInputs"
  ]);

  # The outputs of the flake in dir, with nixpkgs as its only input (no lock, no network)
  loadFlake = dir:
    let
      flake = import (dir + "/flake.nix");
      inputs = { nixpkgs = nixpkgsFlake; self = result; };
      result = flake.outputs inputs // { outPath = dir; inherit inputs; _type = "flake"; };
    in
    result;

  # A NixOS system made of modules, on top of a minimal bootable base
  nixos = modules: nixpkgsFlake.lib.nixosSystem {
    modules = [
      {
        nixpkgs.hostPlatform = system;
        boot.loader.grub.enable = false;
        fileSystems."/" = { device = "/dev/null"; fsType = "ext4"; };
        system.stateVersion = lib.trivial.release;
      }
    ] ++ modules;
  };

  # The output of a shell script run in a build sandbox (it builds what it uses),
  # followed by its exit status when it fails
  sh = script: builtins.readFile (pkgs.runCommand "drill-check" { } ''
    {
      ${script}
    } > $out 2>&1 || echo "exit status $?" >> $out
  '');

  report = only: checks:
    if only == null then checks
    else if only < 0 then builtins.length checks
    else [ (builtins.elemAt checks only) ];
}
"""

NIX_FUNCTION_HARNESS = r"""
{ only ? null, raw ? false }:
let
  drill = import ./drill.nix { nixpkgs = @NIXPKGS@; };
  solution = import @SOURCE@;
  # The file is either the function, or { lib }: the function
  function =
    if builtins.isFunction solution && (builtins.functionArgs solution) ? lib
    then solution { inherit (drill) lib; }
    else solution;
  cases = builtins.fromJSON (builtins.readFile (./. + "/@DATA@"));
  run = case:
    let
      value = builtins.foldl' (f: arg: f arg) function case;
      r = builtins.tryEval (builtins.deepSeq value value);
    in
    if raw then { got = builtins.deepSeq value value; }
    else if !r.success then { error = "evaluation failed (a throw or an assert)"; }
    else if builtins.isFunction r.value then { got = "«lambda»: too few arguments?"; }
    else { got = r.value; };
in
drill.report only (map run cases)
"""

NIX_CODE_HARNESS = r"""
{ only ? null, raw ? false }:
let
  drill = import ./drill.nix { nixpkgs = @NIXPKGS@; inherit raw; };
  inherit (drill) lib pkgs system nixpkgs check checkThrows loadFlake nixos sh contains packageNames;
  # The folder the student works in, and their file
  dir = ./work;
  file = dir + "/@FILE@";
in
let
@SETUP@
in
drill.report only [
@CHECKS@
]
"""

NIX_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_'-]*$")
NIX_FLAGS = ["--option", "extra-experimental-features", "nix-command flakes"]
NIX_TIMEOUT = 300  # seconds: checks may build derivations


def _nix_string(text: str) -> str:
    return json.dumps(text, ensure_ascii=False).replace("${", "\\${")


class Nix(Language):
    key, label, filename, comment = "nix", "Nix", "solution.nix", "#"
    measurable = False
    _nixpkgs: str | None = None

    def literal(self, value, nested: bool = False) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return f"({value})" if value < 0 and nested else str(value)
        if isinstance(value, str):
            return _nix_string(value)
        if isinstance(value, list):
            return "[ " + " ".join(self.literal(v, nested=True) for v in value) + " ]" if value else "[ ]"
        items = [
            f"{k if NIX_IDENT.match(k) else _nix_string(k)} = {self.literal(v)};" for k, v in value.items()
        ]
        return "{ " + " ".join(items) + " }" if items else "{ }"

    def call(self, ex: Exercise, test: dict) -> str:
        return " ".join([self.ident(ex.name), *(self.literal(a, nested=True) for a in test["in"])])

    def skeleton(self, ex: Exercise) -> str:
        params = " ".join(f"{camel(p)}:" for p, _ in ex.params)
        return f"{{ lib }}:\n\n{params}\n  throw \"todo\"\n"

    def complete(self, code: str) -> str:
        return code + "\n" if code.lstrip().startswith("{ lib") else f"{{ lib }}:\n\n{code}\n"

    @classmethod
    def nixpkgs(cls) -> str | None:
        """The nixpkgs source tree: drill's own (DRILL_NIXPKGS), else <nixpkgs>."""
        if cls._nixpkgs is None:
            path = os.environ.get("DRILL_NIXPKGS")
            if not path:
                proc, _ = _execute(["nix-instantiate", "--find-file", "nixpkgs"], Path.cwd())
                path = proc.stdout.strip() if proc and proc.returncode == 0 else ""
            cls._nixpkgs = os.path.realpath(path) if path else ""
        return cls._nixpkgs or None

    def fixtures(self, ex: Exercise) -> dict[str, str]:
        nixpkgs = self.nixpkgs() or "/nixpkgs-not-found"
        return {name: text.replace("@NIXPKGS@", nixpkgs) for name, text in ex.files.items()}

    def _prepare(self, build: Path) -> str | None:
        nixpkgs = self.nixpkgs()
        if nixpkgs is None:
            return None
        (build / "drill.nix").write_text(NIX_LIB)
        return nixpkgs

    def _run(self, ex: Exercise, source: Path, build: Path, cases: list[dict], tag: str) -> Outcome:
        nixpkgs = self._prepare(build)
        if nixpkgs is None:
            return Outcome(len(cases), error=NO_NIXPKGS)
        data = build / f"{ex.key}.{tag}.json"
        if not data.exists():
            data.write_text(json.dumps([case["in"] for case in cases]))
        main = build / "main.nix"
        main.write_text(
            NIX_FUNCTION_HARNESS.replace("@NIXPKGS@", _nix_string(nixpkgs))
            .replace("@SOURCE@", _nix_string(str(source)))
            .replace("@DATA@", data.name)
        )
        paths = {str(source): self.filename, str(build) + "/": ""}
        outcome = Outcome(len(cases))
        entries, error = self._evaluate(main, build, paths, len(cases), TIMEOUT)
        if error:
            # Reported on the case it stopped at
            entries.append({"error": error.replace("\n", " ")})
        self._explain_throw(entries, main, build, paths)
        for i, entry in enumerate(entries):
            if "error" in entry:
                outcome.results.append({"i": i, "ok": False, "error": entry["error"]})
            else:
                ok = _same(entry["got"], cases[i]["out"])
                outcome.results.append({"i": i, "ok": ok, **({} if ok else {"got": entry["got"]})})
        return outcome

    def _run_code(self, ex: Exercise, source: Path, build: Path) -> Outcome:
        nixpkgs = self._prepare(build)
        if nixpkgs is None:
            return Outcome(1, error=NO_NIXPKGS)
        work = build / "work"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir()
        for name, text in self.fixtures(ex).items():
            (work / name).parent.mkdir(parents=True, exist_ok=True)
            (work / name).write_text(text)
        shutil.copyfile(source, work / self.filename_for(ex))
        setup = textwrap.indent(textwrap.dedent(ex.setup.get(self.key, "")).strip(), "  ")
        checks = textwrap.indent(textwrap.dedent(ex.checks[self.key]).strip(), "  ")
        main = build / "main.nix"
        main.write_text(
            NIX_CODE_HARNESS.replace("@NIXPKGS@", _nix_string(nixpkgs))
            .replace("@FILE@", self.filename_for(ex))
            .replace("@SETUP@", setup)
            .replace("@CHECKS@", checks)
        )
        paths = {str(work) + "/": "", str(build) + "/": ""}
        entries, error = self._evaluate(main, build, paths, None, NIX_TIMEOUT)
        self._explain_throw(entries, main, build, paths)
        outcome = Outcome(len(entries) + (1 if error else 0), error=None)
        for i, entry in enumerate(entries):
            if not isinstance(entry, dict) or "label" not in entry:
                return Outcome(1, error="the checks are malformed: each one is (check label got expected)")
            outcome.results.append({"i": i, **entry})
        if error:
            label = "the remaining checks" if entries else "evaluation"
            first, *rest = error.splitlines() or [""]
            outcome.results.append({
                "i": len(entries), "label": label, "ok": False, "error": " ".join([first, *rest[-2:]]),
            })
        return outcome

    def _explain_throw(self, entries: list[dict], main: Path, build: Path, paths: dict[str, str]) -> None:
        """tryEval drops the message of a throw: evaluate the first such entry again without it."""
        thrown = next((i for i, e in enumerate(entries) if e.get("error", "").startswith("evaluation")), None)
        if thrown is None:
            return
        cmd = ["nix-instantiate", "--eval", "--strict", "--json", *NIX_FLAGS, main.name]
        proc, _ = _execute([*cmd, "--show-trace", "--arg", "only", str(thrown), "--arg", "raw", "true"], build)
        if proc and proc.returncode != 0:
            entries[thrown]["error"] = self._error(proc.stderr, paths).replace("\n", " ")

    def _evaluate(
        self, main: Path, build: Path, paths: dict[str, str], total: int | None, timeout: float
    ) -> tuple[list, str | None]:
        """The list main.nix evaluates to, and the error that stopped it.

        A throw is caught for each case, but a type error stops the whole evaluation:
        the cases are then evaluated one by one, up to the one that fails, with the
        trace that tells where.
        """
        cmd = ["nix-instantiate", "--eval", "--strict", "--json", "--read-write-mode", *NIX_FLAGS, main.name]
        proc, error = _execute(cmd, build, timeout)
        if error:
            return [], error
        if proc.returncode == 0:
            return json.loads(proc.stdout), None
        if total is None:
            count, _ = _execute([*cmd, "--arg", "only", "-1"], build, timeout)
            if count is None or count.returncode != 0:
                return [], self._error(proc.stderr, paths)
            total = int(count.stdout)
        entries = []
        for i in range(total):
            one, error = _execute([*cmd, "--show-trace", "--arg", "only", str(i)], build, timeout)
            if error:
                return entries, error
            if one.returncode != 0:
                return entries, self._error(one.stderr, paths)
            entries += json.loads(one.stdout)
        return entries, None

    @staticmethod
    def _error(stderr: str, paths: dict[str, str]) -> str:
        """The gist of a Nix error: its message and where it happened."""
        lines = [line.strip() for line in _tidy(stderr, paths) if line.strip()]
        messages = [line.removeprefix("error:").strip() for line in lines if line.startswith("error:")]
        message = next((m for m in reversed(messages) if m), lines[-1] if lines else "evaluation failed")
        if message.startswith("Cannot build"):
            # A failed build: its last log lines tell why
            log = [line.lstrip("> ") for line in lines if line.startswith(">")]
            return "\n".join(["a build failed:", *log[-6:]])
        places = [
            line for line in lines
            if line.startswith("at ") and not line.startswith(("at drill.nix", "at main.nix", "at /nix/store"))
        ]
        return "\n".join([message, *places[-1:]])


NO_NIXPKGS = "nixpkgs not found: set DRILL_NIXPKGS to a nixpkgs source tree, or add nixpkgs to NIX_PATH"


def _same(got, expected) -> bool:
    """Equal as JSON values: unlike ==, true is not 1."""
    return json.dumps(got, sort_keys=True) == json.dumps(expected, sort_keys=True)


LANGUAGES: dict[str, Language] = {
    lang.key: lang for lang in (Python(), Cpp(), Java(), OCaml(), Nix())
}
ALIASES = {"py": "python", "c++": "cpp", "cxx": "cpp", "ml": "ocaml"}
