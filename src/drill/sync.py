"""Keeping the library in step with its git remote: a pull when drill starts, a commit and
a push when it changes the library (a session's history, `add`, `rm`).

Only for a library that is a git repository with a remote, and unless $DRILL_SYNC is 0.
A failure (no network, a conflict) is reported in one line and never stops drill.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from .store import data_dir, machine
from .term import dim, yellow

PULL_EVERY = 300  # seconds between two pulls, except before a session
TIMEOUT = 15  # seconds for a pull or a push
ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",  # fail instead of asking for a password
    "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=5"),
}


def git(root: Path, *args: str, timeout: float = TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, env=ENV, timeout=timeout,
    )


def enabled(root: Path) -> bool:
    if os.environ.get("DRILL_SYNC", "1") in ("0", "no", "off", "false"):
        return False
    if not (root / ".git").exists():
        return False
    try:
        return bool(git(root, "remote").stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def warn(text: str) -> None:
    print(yellow(f"drill: {text}"), file=sys.stderr)


def first_line(result: subprocess.CompletedProcess) -> str:
    lines = (result.stderr or result.stdout).strip().splitlines()
    return lines[0].removeprefix("fatal: ") if lines else f"git exited with {result.returncode}"


def pull(root: Path, force: bool = False) -> None:
    """Fetch what the other machines pushed; at most every PULL_EVERY seconds unless `force`."""
    if not enabled(root):
        return
    stamp = data_dir() / "last-pull"
    try:
        if not force and time.time() - stamp.stat().st_mtime < PULL_EVERY:
            return
    except FileNotFoundError:
        pass
    try:
        result = git(root, "pull", "--rebase", "--autostash", "--quiet")
    except subprocess.TimeoutExpired:
        warn("the library could not be updated (git pull took too long); going on offline.")
        return
    if result.returncode != 0:
        if (root / ".git" / "rebase-merge").exists() or (root / ".git" / "rebase-apply").exists():
            git(root, "rebase", "--abort")
            warn(f"the library could not be updated: a conflict to resolve by hand in {root}.")
        else:
            warn(f"the library could not be updated ({first_line(result)}); going on offline.")
        return
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()


def push(root: Path, message: str) -> None:
    """Commit everything that changed in the library, then push it."""
    if not enabled(root):
        return
    try:
        git(root, "add", "-A")
        if git(root, "diff", "--cached", "--quiet").returncode != 0:
            changed = git(root, "diff", "--cached", "--name-only").stdout.split()
            files = [f for f in changed if not f.startswith("history/")]
            detail = f": {', '.join(files[:3])}{' …' if len(files) > 3 else ''}" if files else ""
            result = git(root, "commit", "--quiet", "-m", f"drill: {message}{detail} ({machine()})")
            if result.returncode != 0:
                warn(f"the library could not be committed ({first_line(result)}).")
                return
        ahead = git(root, "rev-list", "--count", "@{upstream}..HEAD")
        if ahead.returncode != 0:  # no upstream branch yet
            result = git(root, "push", "--quiet", "--set-upstream", "origin", "HEAD")
        elif ahead.stdout.strip() == "0":
            return  # nothing to push, earlier commits included
        else:
            result = git(root, "push", "--quiet")
        if result.returncode != 0:
            # Behind the remote: catch up, then try once more
            if git(root, "pull", "--rebase", "--autostash", "--quiet").returncode == 0:
                result = git(root, "push", "--quiet")
    except subprocess.TimeoutExpired:
        warn("the library was committed but not pushed (git push took too long).")
        return
    if result.returncode != 0:
        warn(f"the library was committed but not pushed ({first_line(result)}).")
    else:
        print(dim("Library synced."), file=sys.stderr)
