"""Safe subprocess helpers.

Rules enforced here:
  * Commands are always argument lists - a shell is never involved.
  * Every call has a timeout (or an explicit watchdog when streaming).
  * Functions never raise for "normal" failures; they return a CmdResult.
  * Output is parsed under the C locale so parsing is predictable.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence

log = logging.getLogger("nixtune.runner")

# A GUI launched from an application menu often has a trimmed PATH, so these
# well-known NixOS / Nix locations are searched as a fallback.
SYSTEM_BIN_DIRS = (
    "/run/wrappers/bin",
    "/run/current-system/sw/bin",
    "/nix/var/nix/profiles/default/bin",
)


def extra_bin_dirs() -> list[str]:
    dirs = list(SYSTEM_BIN_DIRS)
    user = os.environ.get("USER") or os.environ.get("LOGNAME")
    if user:
        dirs.append(f"/etc/profiles/per-user/{user}/bin")
    dirs.append(os.path.join(os.path.expanduser("~"), ".nix-profile", "bin"))
    return dirs


def which(name: str) -> Optional[str]:
    """Find an executable on PATH, falling back to well-known Nix locations."""
    found = shutil.which(name)
    if found:
        return found
    for directory in extra_bin_dirs():
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def command_env(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["LANG"] = "C"
    path_parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    for directory in extra_bin_dirs():
        if directory not in path_parts and os.path.isdir(directory):
            path_parts.append(directory)
    env["PATH"] = os.pathsep.join(path_parts)
    if extra:
        env.update(extra)
    return env


@dataclass
class CmdResult:
    argv: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    missing: bool = False
    duration: float = 0.0

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.missing

    @property
    def text(self) -> str:
        parts = [p for p in (self.stdout.strip(), self.stderr.strip()) if p]
        return "\n".join(parts)

    def error_summary(self) -> str:
        if self.missing:
            return self.stderr or f"{self.argv[0]}: command not found"
        if self.timed_out:
            return f"{self.argv[0]} timed out after {self.duration:.0f}s"
        detail = self.stderr.strip() or self.stdout.strip()
        detail = detail.splitlines()[-1] if detail else "no output"
        return f"{self.argv[0]} exited with status {self.returncode}: {detail}"


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _resolve(argv: Sequence[str]) -> tuple[list[str], Optional[str]]:
    argv = [str(a) for a in argv]
    exe = argv[0]
    if os.sep in exe:
        return argv, None
    resolved = which(exe)
    if resolved is None:
        return argv, f"{exe}: command not found"
    return [resolved] + argv[1:], None


def run(
    argv: Sequence[str],
    timeout: float = 30.0,
    env: Optional[Mapping[str, str]] = None,
    input_text: Optional[str] = None,
    cwd: Optional[str] = None,
) -> CmdResult:
    """Run a command and capture its output. Never raises for command failure."""
    resolved, err = _resolve(argv)
    if err:
        return CmdResult(list(map(str, argv)), 127, "", err, missing=True)
    start = time.monotonic()
    log.debug("run: %s", resolved)
    try:
        cp = subprocess.run(
            resolved,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=command_env(env),
            input=input_text,
            cwd=cwd,
            stdin=None if input_text is not None else subprocess.DEVNULL,
        )
        return CmdResult(
            resolved, cp.returncode, cp.stdout or "", cp.stderr or "",
            duration=time.monotonic() - start,
        )
    except subprocess.TimeoutExpired as exc:
        return CmdResult(
            resolved, 124, _to_text(exc.stdout), _to_text(exc.stderr),
            timed_out=True, duration=time.monotonic() - start,
        )
    except FileNotFoundError:
        return CmdResult(resolved, 127, "", f"{resolved[0]}: not found", missing=True)
    except OSError as exc:
        return CmdResult(resolved, 126, "", f"{resolved[0]}: {exc}")


def stream(
    argv: Sequence[str],
    on_line: Callable[[str], None],
    timeout: Optional[float] = None,
    env: Optional[Mapping[str, str]] = None,
) -> CmdResult:
    """Run a command, delivering merged stdout/stderr line by line."""
    resolved, err = _resolve(argv)
    if err:
        return CmdResult(list(map(str, argv)), 127, "", err, missing=True)
    start = time.monotonic()
    log.debug("stream: %s", resolved)
    collected: list[str] = []
    timed_out = threading.Event()
    try:
        proc = subprocess.Popen(
            resolved,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            errors="replace",
            bufsize=1,
            env=command_env(env),
        )
    except FileNotFoundError:
        return CmdResult(resolved, 127, "", f"{resolved[0]}: not found", missing=True)
    except OSError as exc:
        return CmdResult(resolved, 126, "", f"{resolved[0]}: {exc}")

    timer: Optional[threading.Timer] = None
    if timeout:
        def _kill() -> None:
            timed_out.set()
            try:
                proc.kill()
            except OSError:
                pass
        timer = threading.Timer(timeout, _kill)
        timer.daemon = True
        timer.start()
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            collected.append(line)
            try:
                on_line(line)
            except Exception:  # a broken callback must not kill the command
                log.exception("stream callback failed")
        proc.wait()
    finally:
        if timer:
            timer.cancel()
    return CmdResult(
        resolved, proc.returncode, "\n".join(collected), "",
        timed_out=timed_out.is_set(), duration=time.monotonic() - start,
    )


def pkexec_path() -> Optional[str]:
    """Return a *setuid* pkexec, or None.

    On NixOS the working pkexec is the setuid wrapper in /run/wrappers/bin; the
    copy inside the polkit package is not setuid and cannot elevate.
    """
    candidates = ["/run/wrappers/bin/pkexec", "/usr/bin/pkexec", "/bin/pkexec"]
    on_path = shutil.which("pkexec")
    if on_path:
        candidates.append(on_path)
    for cand in candidates:
        try:
            st = os.stat(cand)
        except OSError:
            continue
        if st.st_mode & stat.S_ISUID and os.access(cand, os.X_OK):
            return cand
    return None
