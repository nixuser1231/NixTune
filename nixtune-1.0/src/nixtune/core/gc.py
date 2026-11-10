"""Garbage-collection analysis (read-only preview).

`nix-store --gc --print-dead` lists the store paths a collection *would*
delete without deleting anything. Sizes are then queried per path so the user
sees how much space would be reclaimed before confirming.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import runner

STORE_PATH_RE = re.compile(r"^/nix/store/[0-9a-z]{32}-[^/\s]+$")
CHUNK = 200


@dataclass
class DeadPath:
    path: str
    size: Optional[int] = None  # NAR size in bytes, None if unknown

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]


@dataclass
class RootSummary:
    total: int = 0
    profiles: int = 0   # /nix/var/nix/profiles/* (generations)
    system: int = 0     # current/booted system, gcroots dir
    running: int = 0    # {memory}, /proc/... (running processes)
    other: int = 0
    result_links: list[tuple[str, str]] = field(default_factory=list)  # (link, target)


@dataclass
class GcAnalysis:
    ok: bool = False
    error: str = ""
    dead: list[DeadPath] = field(default_factory=list)
    total_bytes: int = 0
    estimated: bool = False
    sized_count: int = 0
    roots: Optional[RootSummary] = None
    seconds: float = 0.0

    @property
    def count(self) -> int:
        return len(self.dead)


def parse_dead_paths(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if STORE_PATH_RE.match(line) and line not in seen:
            seen.add(line)
            out.append(line)
    return out


def parse_sizes(text: str, expected: int) -> Optional[list[int]]:
    values: list[int] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.isdigit():
            return None
        values.append(int(line))
    return values if len(values) == expected else None


def parse_roots(text: str) -> RootSummary:
    summary = RootSummary()
    for line in text.splitlines():
        if " -> " not in line:
            continue
        root, target = line.split(" -> ", 1)
        root, target = root.strip(), target.strip()
        summary.total += 1
        if root.startswith("/nix/var/nix/profiles/"):
            summary.profiles += 1
        elif root in ("/run/current-system", "/run/booted-system") or root.startswith("/nix/var/nix/gcroots/"):
            summary.system += 1
        elif root.startswith(("{", "/proc/")):
            summary.running += 1
        else:
            summary.other += 1
            if root.startswith("/") and STORE_PATH_RE.match(target):
                summary.result_links.append((root, target))
    return summary


def _size_batch(paths: list[str]) -> list[Optional[int]]:
    res = runner.run(["nix-store", "--query", "--size", *paths], timeout=180)
    if res.ok:
        parsed = parse_sizes(res.stdout, len(paths))
        if parsed is not None:
            return list(parsed)
    # One bad path poisons a batch query; retry individually (bounded).
    sizes: list[Optional[int]] = []
    for p in paths:
        one = runner.run(["nix-store", "--query", "--size", p], timeout=30)
        parsed = parse_sizes(one.stdout, 1) if one.ok else None
        sizes.append(parsed[0] if parsed else None)
    return sizes


def analyze(
    progress: Optional[Callable[[str], None]] = None,
    time_budget: float = 90.0,
    max_sized: int = 20000,
) -> GcAnalysis:
    """Preview what a garbage collection would remove. Deletes nothing."""
    say = progress or (lambda _msg: None)
    start = time.monotonic()
    result = GcAnalysis()

    say("Finding unreachable store paths (nix-store --gc --print-dead)...")
    res = runner.run(["nix-store", "--gc", "--print-dead"], timeout=900)
    if res.missing:
        result.error = "nix-store was not found. Is Nix installed and on PATH?"
        return result
    if not res.ok:
        result.error = res.error_summary()
        return result

    paths = parse_dead_paths(res.stdout)
    result.dead = [DeadPath(p) for p in paths]
    say(f"{len(paths)} unreachable paths found. Measuring sizes...")

    deadline = start + time_budget
    measured = 0
    total = 0
    for i in range(0, min(len(paths), max_sized), CHUNK):
        if time.monotonic() > deadline:
            break
        chunk = paths[i:i + CHUNK]
        for item, size in zip(result.dead[i:i + CHUNK], _size_batch(chunk)):
            item.size = size
            if size is not None:
                total += size
                measured += 1
        say(f"Measured {min(i + CHUNK, len(paths))} of {len(paths)} paths...")

    result.sized_count = measured
    if measured and measured < len(paths):
        total = int(total * len(paths) / measured)
        result.estimated = True
    result.total_bytes = total
    result.dead.sort(key=lambda d: d.size or 0, reverse=True)

    say("Inspecting garbage-collector roots...")
    roots = runner.run(["nix-store", "--gc", "--print-roots"], timeout=180)
    if roots.ok:
        result.roots = parse_roots(roots.stdout)

    result.ok = True
    result.seconds = time.monotonic() - start
    return result
