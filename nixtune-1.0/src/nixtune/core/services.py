"""Read-only view of systemd services."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from . import runner

UNIT_NAME_RE = re.compile(r"^[A-Za-z0-9:_.@\\-]+\.service$")
SCOPES = ("system", "user")


@dataclass
class Unit:
    name: str
    load: str
    active: str
    sub: str
    description: str
    enabled: str = ""  # unit-file state (enabled, disabled, static, ...)

    @property
    def is_failed(self) -> bool:
        return self.active == "failed" or self.sub == "failed"

    @property
    def is_running(self) -> bool:
        return self.active == "active" and self.sub == "running"


def _scope_args(scope: str) -> list[str]:
    if scope not in SCOPES:
        raise ValueError(f"invalid scope {scope!r}")
    return ["--user"] if scope == "user" else []


def parse_list_units(text: str) -> list[Unit]:
    units: list[Unit] = []
    for line in text.splitlines():
        line = line.strip().lstrip("●*").strip()  # failed units may start with a bullet
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 4 or not parts[0].endswith(".service"):
            continue
        units.append(Unit(parts[0], parts[1], parts[2], parts[3], parts[4] if len(parts) > 4 else ""))
    return units


def parse_unit_files(text: str) -> dict[str, str]:
    states: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].endswith(".service"):
            states[parts[0]] = parts[1]
    return states


def list_units(scope: str = "system") -> tuple[list[Unit], str]:
    """Return (units, error_message). error_message is '' on success."""
    base = ["systemctl", *_scope_args(scope), "--no-pager", "--plain", "--no-legend", "--full"]
    res = runner.run([*base, "list-units", "--type=service", "--all"], timeout=30)
    if res.missing:
        return [], "systemctl was not found."
    units = parse_list_units(res.stdout)
    if not units:
        reason = res.stderr.strip() or res.stdout.strip() or "no services returned"
        return [], f"Could not list services: {reason}"
    files = runner.run([*base, "list-unit-files", "--type=service"], timeout=30)
    if files.ok:
        states = parse_unit_files(files.stdout)
        for unit in units:
            unit.enabled = states.get(unit.name, "")
    return units, ""


def summarize(units: list[Unit]) -> dict[str, int]:
    return {
        "total": len(units),
        "running": sum(1 for u in units if u.is_running),
        "failed": sum(1 for u in units if u.is_failed),
        "inactive": sum(1 for u in units if u.active == "inactive"),
    }


def unit_details(name: str, scope: str = "system") -> str:
    """Human-readable status text for one unit (read-only)."""
    if not UNIT_NAME_RE.match(name):
        return "Refusing to query an unexpected unit name."
    base = ["systemctl", *_scope_args(scope), "--no-pager"]
    props = ",".join((
        "Id", "Description", "LoadState", "ActiveState", "SubState", "UnitFileState",
        "MainPID", "MemoryCurrent", "ActiveEnterTimestamp", "FragmentPath", "Result",
    ))
    show = runner.run([*base, "show", f"--property={props}", "--", name], timeout=15)
    status = runner.run([*base, "status", "--lines=15", "--", name], timeout=15)
    parts = []
    if show.stdout.strip():
        parts.append(show.stdout.strip())
    if status.stdout.strip():
        parts.append("─" * 40 + "\n" + status.stdout.strip())
    if not parts:
        parts.append(show.stderr.strip() or status.stderr.strip() or "No details available.")
    return "\n".join(parts)


def filter_units(
    units: list[Unit],
    text: str = "",
    state: str = "all",
) -> list[Unit]:
    text = text.strip().lower()
    out = []
    for unit in units:
        if text and text not in unit.name.lower() and text not in unit.description.lower():
            continue
        if state == "running" and not unit.is_running:
            continue
        if state == "failed" and not unit.is_failed:
            continue
        if state == "inactive" and unit.active != "inactive":
            continue
        if state == "enabled" and unit.enabled != "enabled":
            continue
        out.append(unit)
    return out
