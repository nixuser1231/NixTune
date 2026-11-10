"""Logging, crash handling and diagnostic reports.

Reports are written only to a file the user chooses (or copied to the
clipboard). Nothing is ever uploaded. Paths, user and host names are redacted.
"""

from __future__ import annotations

import getpass
import logging
import logging.handlers
import os
import platform
import socket
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from ..constants import APP_NAME, APP_VERSION

LOGGER_NAME = "nixtune"
_installed = False


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "nixtune"


def log_file() -> Path:
    return state_dir() / "nixtune.log"


def setup_logging(level: int = logging.INFO) -> Path:
    path = log_file()
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(level)
    if any(getattr(h, "_nixtune", False) for h in root.handlers):
        return path
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler._nixtune = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    return path


def redact(text: str) -> str:
    """Remove home directory, user name and host name from free text."""
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = ""
    if user and len(user) > 2:
        text = text.replace(f"/{user}/", "/<user>/").replace(f"/{user}", "/<user>")
    host = socket.gethostname()
    if host and len(host) > 2:
        text = text.replace(host, "<host>")
    return text


def recent_log(lines: int = 200) -> str:
    try:
        with open(log_file(), "r", encoding="utf-8", errors="replace") as fh:
            return "".join(fh.readlines()[-lines:])
    except OSError:
        return "(no log file yet)"


def _qt_versions() -> str:
    try:
        import PySide6  # noqa: WPS433
        from PySide6 import QtCore  # noqa: WPS433
        return f"PySide6 {PySide6.__version__}, Qt {QtCore.qVersion()}"
    except Exception as exc:  # noqa: BLE001
        return f"PySide6 not importable ({exc.__class__.__name__})"


SAFE_ENV = ("XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "QT_QPA_PLATFORM", "QT_QPA_PLATFORMTHEME",
            "LANG", "NIXTUNE_HELPER")


def build_report(extra_sections: Optional[dict[str, str]] = None, include_log: bool = True) -> str:
    from . import nixenv  # local import keeps this module light

    parts = [
        f"{APP_NAME} {APP_VERSION} diagnostic report",
        f"Created: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "== Environment ==",
        f"Python:   {sys.version.split()[0]} ({sys.executable})",
        f"Qt:       {_qt_versions()}",
        f"Platform: {platform.platform()}",
        f"OS:       {nixenv.pretty_os_name()}",
        f"NixOS:    {nixenv.is_nixos()}",
        f"Nix:      {nixenv.nix_version() or 'not found'}",
        f"euid:     {os.geteuid() if hasattr(os, 'geteuid') else 'n/a'}",
    ]
    for key in SAFE_ENV:
        if os.environ.get(key):
            parts.append(f"{key}={os.environ[key]}")
    for title, body in (extra_sections or {}).items():
        parts += ["", f"== {title} ==", body]
    if include_log:
        parts += ["", "== Recent log ==", recent_log()]
    return redact("\n".join(parts)) + "\n"


def save_report(path: str, extra_sections: Optional[dict[str, str]] = None) -> Path:
    target = Path(path)
    target.write_text(build_report(extra_sections), encoding="utf-8")
    return target


def format_exception(exc_type, exc, tb) -> str:
    return "".join(traceback.format_exception(exc_type, exc, tb))


def install_excepthooks(on_error: Optional[Callable[[str], None]] = None) -> None:
    """Log every uncaught exception (main thread and worker threads)."""
    global _installed
    log = logging.getLogger(LOGGER_NAME)

    def handle(exc_type, exc, tb) -> None:
        text = format_exception(exc_type, exc, tb)
        log.error("Uncaught exception:\n%s", text)
        if on_error is not None:
            try:
                on_error(redact(text))
            except Exception:  # noqa: BLE001
                log.exception("error handler failed")

    def sys_hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        handle(exc_type, exc, tb)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        handle(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = sys_hook
    threading.excepthook = thread_hook
    _installed = True
