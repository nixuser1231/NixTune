"""Narrowly scoped privileged operations.

Design
------
* The GUI never runs as root and never uses sudo.
* The only way to gain privileges is `pkexec <helper> <action>` where
  <action> is one of a tiny fixed allow-list (see ACTIONS).
* The helper is only used if it is *trusted*: owned by root and not writable by
  anyone else (this is naturally true for a file in the Nix store). A helper
  sitting in a user-writable checkout is refused - running it as root would be
  a local privilege-escalation hole. In that case the UI shows the equivalent
  command for the user to run in their own terminal instead.
* The helper itself re-validates the action and never accepts free-form
  arguments (see helper/nixtune-helper).
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..constants import HELPER_NAME
from . import runner


@dataclass(frozen=True)
class ActionSpec:
    key: str
    title: str
    argv: tuple[str, ...]        # what the helper executes (documentation only here)
    manual_command: str          # what the user can run themselves
    destructive: bool
    description: str


ACTIONS: dict[str, ActionSpec] = {
    "gc": ActionSpec(
        key="gc",
        title="Collect garbage",
        argv=("nix-store", "--gc"),
        manual_command="sudo nix-collect-garbage",
        destructive=True,
        description=(
            "Deletes store paths that no garbage-collector root references. "
            "It does NOT delete system generations and does NOT touch your configuration."
        ),
    ),
    "optimise": ActionSpec(
        key="optimise",
        title="Optimise the Nix store",
        argv=("nix-store", "--optimise"),
        manual_command="sudo nix-store --optimise",
        destructive=False,
        description=(
            "Replaces duplicate files in the store with hard links to save space. "
            "No store path is removed; this can take a while on large stores."
        ),
    ),
}


@dataclass
class HelperInfo:
    path: str
    trusted: bool
    reason: str


def is_trusted_path(path: str) -> tuple[bool, str]:
    """True if `path` is a root-owned file that no non-root user can replace."""
    try:
        real = os.path.realpath(path)
        st = os.lstat(real)
    except OSError as exc:
        return False, f"cannot inspect {path}: {exc}"
    if not stat.S_ISREG(st.st_mode):
        return False, f"{real} is not a regular file"
    if st.st_uid != 0:
        return False, f"{real} is not owned by root"
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False, f"{real} is writable by non-root users"
    cur = os.path.dirname(real)
    while True:
        try:
            dst = os.lstat(cur)
        except OSError as exc:
            return False, f"cannot inspect {cur}: {exc}"
        if dst.st_uid != 0:
            return False, f"{cur} is not owned by root"
        # group/other-writable directories are only safe with the sticky bit
        # (e.g. /tmp, /nix/store), which stops others replacing root's files.
        if dst.st_mode & (stat.S_IWGRP | stat.S_IWOTH) and not dst.st_mode & stat.S_ISVTX:
            return False, f"{cur} is writable by non-root users"
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return True, "root-owned and not writable by other users"


def helper_candidates() -> list[str]:
    cands: list[str] = []
    env = os.environ.get("NIXTUNE_HELPER")
    if env:
        cands.append(env)
    here = Path(__file__).resolve()
    # installed layout: <prefix>/lib/pythonX/site-packages/nixtune/core/privileged.py
    for up in (6, 5, 4):
        if len(here.parents) > up:
            cands.append(str(here.parents[up] / "libexec" / "nixtune" / HELPER_NAME))
    # source checkout: <root>/helper/nixtune-helper
    if len(here.parents) > 3:
        cands.append(str(here.parents[3] / "helper" / HELPER_NAME))
    cands.append(f"/run/current-system/sw/libexec/nixtune/{HELPER_NAME}")
    return cands


def find_helper() -> Optional[HelperInfo]:
    for cand in helper_candidates():
        if os.path.isfile(cand):
            trusted, reason = is_trusted_path(cand)
            return HelperInfo(os.path.realpath(cand), trusted, reason)
    return None


@dataclass
class Plan:
    action: ActionSpec
    helper: Optional[HelperInfo]
    pkexec: Optional[str]
    available: bool
    unavailable_reason: str
    display_command: str

    @property
    def manual_command(self) -> str:
        return self.action.manual_command


def plan(action: str) -> Plan:
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}")
    spec = ACTIONS[action]
    helper = find_helper()
    pkexec = runner.pkexec_path()
    reason = ""
    if pkexec is None:
        reason = ("No setuid pkexec found. On NixOS enable polkit with "
                  "`security.polkit.enable = true;`.")
    elif helper is None:
        reason = "The NIXTUNE privileged helper was not found."
    elif not helper.trusted:
        reason = (f"The helper at {helper.path} is not trusted ({helper.reason}). "
                  "Install NIXTUNE through the flake/NixOS module so the helper lives "
                  "in the read-only Nix store.")
    available = not reason
    display = (f"pkexec {helper.path} {action}" if helper else f"pkexec {HELPER_NAME} {action}")
    return Plan(spec, helper, pkexec, available, reason, display)


PKEXEC_HINTS = {
    126: "Authentication was dismissed or you are not authorised. Nothing was changed.",
    127: "Authentication failed or no polkit agent is running. Nothing was changed.",
}


def run_action(action: str, on_line: Callable[[str], None]) -> runner.CmdResult:
    """Execute an allow-listed action through pkexec, streaming output."""
    p = plan(action)
    if not p.available or p.pkexec is None or p.helper is None:
        return runner.CmdResult(
            ["pkexec", HELPER_NAME, action], 126, "", p.unavailable_reason or "unavailable",
        )
    return runner.stream([p.pkexec, p.helper.path, action], on_line, timeout=None)
