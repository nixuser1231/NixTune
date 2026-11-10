"""Detection of the NixOS / Nix environment."""

from __future__ import annotations

import os
import re
import time
from typing import Optional

from . import runner


def read_os_release(path: str = "/etc/os-release") -> dict[str, str]:
    data: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return data


def is_nixos(os_release_path: str = "/etc/os-release", marker: str = "/etc/NIXOS") -> bool:
    return os.path.exists(marker) or read_os_release(os_release_path).get("ID") == "nixos"


def nix_version() -> Optional[str]:
    res = runner.run(["nix", "--version"], timeout=10)
    if not res.ok:
        return None
    return res.stdout.strip() or None


def nixos_version() -> Optional[str]:
    res = runner.run(["nixos-version"], timeout=10)
    if res.ok and res.stdout.strip():
        return res.stdout.strip()
    rel = read_os_release()
    if rel.get("ID") == "nixos":
        return rel.get("VERSION") or rel.get("PRETTY_NAME")
    return None


def pretty_os_name() -> str:
    rel = read_os_release()
    return rel.get("PRETTY_NAME") or rel.get("NAME") or "Linux"


def current_system_path() -> Optional[str]:
    try:
        return os.path.realpath("/run/current-system")
    except OSError:
        return None


def parse_nix_config(text: str) -> dict[str, str]:
    cfg: dict[str, str] = {}
    for line in text.splitlines():
        if " = " in line:
            key, value = line.split(" = ", 1)
            cfg[key.strip()] = value.strip()
    return cfg


_cfg_cache: tuple[float, dict[str, str]] = (0.0, {})


def nix_config(max_age: float = 30.0) -> dict[str, str]:
    """Effective Nix configuration ({} if it cannot be read)."""
    global _cfg_cache
    stamp, cached = _cfg_cache
    if cached and time.monotonic() - stamp < max_age:
        return cached
    attempts = (
        ["nix", "--extra-experimental-features", "nix-command", "config", "show"],
        ["nix", "--extra-experimental-features", "nix-command", "show-config"],
        ["nix-instantiate", "--show-config"],
    )
    for argv in attempts:
        res = runner.run(argv, timeout=20)
        if res.ok and res.stdout.strip():
            cfg = parse_nix_config(res.stdout)
            if cfg:
                _cfg_cache = (time.monotonic(), cfg)
                return cfg
    return {}


def flakes_enabled(cfg: Optional[dict[str, str]] = None) -> Optional[bool]:
    """True/False if known, None if the config could not be read."""
    cfg = nix_config() if cfg is None else cfg
    if not cfg:
        return None
    features = set(cfg.get("experimental-features", "").split())
    return "flakes" in features and "nix-command" in features


def truthy(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    return value.strip().lower() in ("1", "true", "yes", "on")


SYSTEM_PROFILE_DIR = "/nix/var/nix/profiles"
_KERNEL_RE = re.compile(r"linux-([0-9][^/]*?)(?:-modules)?(?:/|$)")


def kernel_version_of(system_path: str) -> str:
    """Extract the kernel version from a system closure (best effort)."""
    try:
        target = os.path.realpath(os.path.join(system_path, "kernel"))
    except OSError:
        return ""
    match = _KERNEL_RE.search(target)
    return match.group(1) if match else ""
