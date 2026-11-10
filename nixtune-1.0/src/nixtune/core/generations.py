"""Read-only listing of Nix profile / NixOS system generations.

NIXTUNE never deletes generations. For cleanup it only *builds a command* that
the user may review and run themselves in a terminal.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from . import nixenv

SYSTEM_PROFILE_DIR = nixenv.SYSTEM_PROFILE_DIR


@dataclass
class Generation:
    number: int
    link: str
    store_path: str
    created: datetime
    version: str = ""
    kernel: str = ""
    is_current: bool = False
    is_booted: bool = False
    is_default: bool = False  # what the next boot will use (profile symlink target)


@dataclass
class ProfileRef:
    label: str
    directory: str
    name: str            # e.g. "system" -> system-12-link
    needs_root: bool

    @property
    def profile_path(self) -> str:
        return os.path.join(self.directory, self.name)


def _real(path: str) -> str:
    try:
        return os.path.realpath(path)
    except OSError:
        return path


def list_generations(ref: ProfileRef, is_system: Optional[bool] = None) -> list[Generation]:
    """List generations of a profile, newest first. Returns [] if unreadable."""
    is_system = ref.name == "system" if is_system is None else is_system
    pattern = re.compile(rf"^{re.escape(ref.name)}-(\d+)-link$")
    try:
        entries = os.listdir(ref.directory)
    except OSError:
        return []

    current = _real("/run/current-system") if is_system else ""
    booted = _real("/run/booted-system") if is_system else ""
    default_link = ""
    try:
        default_link = os.readlink(ref.profile_path)
    except OSError:
        pass

    gens: list[Generation] = []
    for entry in entries:
        match = pattern.match(entry)
        if not match:
            continue
        link = os.path.join(ref.directory, entry)
        try:
            created = datetime.fromtimestamp(os.lstat(link).st_mtime)
        except OSError:
            continue
        target = _real(link)
        version = ""
        kernel = ""
        if is_system:
            try:
                with open(os.path.join(target, "nixos-version"), "r", encoding="utf-8") as fh:
                    version = fh.read().strip()
            except OSError:
                pass
            kernel = nixenv.kernel_version_of(target)
        gens.append(Generation(
            number=int(match.group(1)),
            link=link,
            store_path=target,
            created=created,
            version=version,
            kernel=kernel,
            is_current=bool(current) and target == current,
            is_booted=bool(booted) and target == booted,
            is_default=os.path.basename(default_link) == entry,
        ))
    gens.sort(key=lambda g: g.number, reverse=True)
    return gens


def discover_profiles(home: Optional[str] = None, user: Optional[str] = None) -> list[ProfileRef]:
    """Profiles that exist on this machine and are worth listing."""
    home = home or os.path.expanduser("~")
    user = user or os.environ.get("USER") or ""
    refs: list[ProfileRef] = []
    candidates = [
        ProfileRef("NixOS system", SYSTEM_PROFILE_DIR, "system", True),
        ProfileRef("User profile", os.path.join(home, ".local/state/nix/profiles"), "profile", False),
        ProfileRef("User profile (legacy)", os.path.join(SYSTEM_PROFILE_DIR, "per-user", user), "profile", False),
        ProfileRef("Home Manager", os.path.join(home, ".local/state/nix/profiles"), "home-manager", False),
    ]
    for ref in candidates:
        if not ref.directory or not os.path.isdir(ref.directory):
            continue
        pat = re.compile(rf"^{re.escape(ref.name)}-\d+-link$")
        try:
            if any(pat.match(e) for e in os.listdir(ref.directory)):
                refs.append(ref)
        except OSError:
            continue
    # keep the system profile listed even when empty so the page is never blank
    if not any(r.name == "system" for r in refs) and os.path.isdir(SYSTEM_PROFILE_DIR):
        refs.insert(0, candidates[0])
    return refs


# ------------------------------------------------------------ command builders
def delete_command(ref: ProfileRef, numbers: list[int]) -> str:
    """A command (to be run by the *user*) deleting specific generations."""
    clean = sorted({int(n) for n in numbers})
    if not clean:
        raise ValueError("no generations selected")
    base = ["nix-env", "-p", ref.profile_path, "--delete-generations", *map(str, clean)]
    text = " ".join(shlex.quote(p) for p in base)
    return f"sudo {text}" if ref.needs_root else text


def older_than_command(days: int, ref: Optional[ProfileRef] = None) -> str:
    days = int(days)
    if days < 1:
        raise ValueError("days must be >= 1")
    if ref is not None and ref.needs_root:
        return f"sudo nix-collect-garbage --delete-older-than {days}d"
    return f"nix-collect-garbage --delete-older-than {days}d"


def keep_last_command(count: int, ref: ProfileRef) -> str:
    count = int(count)
    if count < 1:
        raise ValueError("must keep at least one generation")
    base = ["nix-env", "-p", ref.profile_path, "--delete-generations", f"+{count}"]
    text = " ".join(shlex.quote(p) for p in base)
    return f"sudo {text}" if ref.needs_root else text
