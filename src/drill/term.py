"""Terminal helpers: colours, a redrawable status line and single-key input."""

from __future__ import annotations

import os
import select
import sys
import termios
import tty

_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def _style(code: str):
    def apply(text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if _COLOR else text

    return apply


bold, dim, red, green, yellow, cyan = (_style(c) for c in ("1", "2", "31", "32", "33", "36"))


def fmt_time(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def fmt_duration(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes // 60}h{minutes % 60:02d}" if minutes >= 60 else f"{minutes} min"


def say(text: str = "") -> None:
    """Print a line, replacing the status line if one is shown."""
    sys.stdout.write(f"\r\033[2K{text}\n")
    sys.stdout.flush()


def status(text: str) -> None:
    """Show `text` on the bottom line, to be overwritten by the next call."""
    sys.stdout.write(f"\r\033[2K{text}")
    sys.stdout.flush()


def clear() -> None:
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


class Keys:
    """Puts the terminal in cbreak mode so single key presses are read without Enter."""

    def __enter__(self) -> Keys:
        self.fd = sys.stdin.fileno()
        self.saved = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\033[?25l")  # hide the cursor
        return self

    def __exit__(self, *exc) -> None:
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)
        sys.stdout.write("\033[?25h")
        say()

    def get(self, timeout: float | None) -> str | None:
        """Return the key pressed within `timeout` seconds (lowercased), if any."""
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return None
        data = os.read(self.fd, 64).decode(errors="ignore")
        # Escape sequences (arrows, function keys) are ignored
        return data[0].lower() if data and not data.startswith("\033") else None

    def wait(self, keys: str) -> str:
        """Block until one of `keys` is pressed and return it."""
        while True:
            key = self.get(None)
            if key is not None and key in keys:
                return key
