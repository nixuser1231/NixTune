"""Live system metrics read straight from /proc and statvfs (no psutil needed)."""

from __future__ import annotations

import os
import platform
import socket
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------- formatting
def format_bytes(value: float) -> str:
    n = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024.0 or unit == "TiB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TiB"  # pragma: no cover


def format_duration(seconds: float) -> str:
    total = int(max(0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# ----------------------------------------------------------------------- CPU
def parse_cpu_lines(text: str) -> list[tuple[str, int, int]]:
    """Parse /proc/stat text -> [(label, total_ticks, idle_ticks)]."""
    rows: list[tuple[str, int, int]] = []
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        try:
            vals = [int(x) for x in parts[1:]]
        except ValueError:
            continue
        if len(vals) < 4:
            continue
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)  # idle + iowait
        total = sum(vals[:8]) if len(vals) >= 8 else sum(vals)  # excl. guest
        rows.append((parts[0], total, idle))
    return rows


class CpuSampler:
    """Computes CPU utilisation from deltas between successive samples."""

    def __init__(self, stat_path: str = "/proc/stat") -> None:
        self.stat_path = stat_path
        self._prev: dict[str, tuple[int, int]] = {}
        self._prev = self._read()

    def _read(self) -> dict[str, tuple[int, int]]:
        try:
            with open(self.stat_path, "r", encoding="ascii", errors="replace") as fh:
                rows = parse_cpu_lines(fh.read())
        except OSError:
            return {}
        return {label: (total, idle) for label, total, idle in rows}

    def sample(self) -> tuple[float, list[float]]:
        """Return (overall_percent, [per_core_percent])."""
        now = self._read()
        overall = 0.0
        cores: list[tuple[int, float]] = []
        for label, (total, idle) in now.items():
            prev = self._prev.get(label)
            pct = 0.0
            if prev:
                d_total = total - prev[0]
                d_idle = idle - prev[1]
                if d_total > 0:
                    pct = max(0.0, min(100.0, 100.0 * (d_total - d_idle) / d_total))
            if label == "cpu":
                overall = pct
            else:
                try:
                    cores.append((int(label[3:]), pct))
                except ValueError:
                    pass
        self._prev = now
        cores.sort()
        return overall, [p for _, p in cores]


# -------------------------------------------------------------------- memory
@dataclass
class MemInfo:
    total: int = 0
    available: int = 0
    swap_total: int = 0
    swap_free: int = 0

    @property
    def used(self) -> int:
        return max(0, self.total - self.available)

    @property
    def percent(self) -> float:
        return 100.0 * self.used / self.total if self.total else 0.0

    @property
    def swap_used(self) -> int:
        return max(0, self.swap_total - self.swap_free)

    @property
    def swap_percent(self) -> float:
        return 100.0 * self.swap_used / self.swap_total if self.swap_total else 0.0


def parse_meminfo(text: str) -> MemInfo:
    values: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        bits = rest.split()
        if not bits:
            continue
        try:
            number = int(bits[0])
        except ValueError:
            continue
        values[key.strip()] = number * (1024 if len(bits) > 1 and bits[1].lower() == "kb" else 1)
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable")
    if available is None:  # very old kernels
        available = values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
    return MemInfo(total, available, values.get("SwapTotal", 0), values.get("SwapFree", 0))


def memory(path: str = "/proc/meminfo") -> MemInfo:
    try:
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            return parse_meminfo(fh.read())
    except OSError:
        return MemInfo()


# ---------------------------------------------------------------------- disk
@dataclass
class DiskUsage:
    path: str
    total: int
    used: int
    free: int

    @property
    def percent(self) -> float:
        denom = self.used + self.free
        return 100.0 * self.used / denom if denom else 0.0


def disk_usage(path: str) -> Optional[DiskUsage]:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    frsize = st.f_frsize or st.f_bsize
    total = st.f_blocks * frsize
    free = st.f_bavail * frsize
    used = (st.f_blocks - st.f_bfree) * frsize
    return DiskUsage(path, total, used, free)


def interesting_mounts() -> list[tuple[str, str]]:
    """Return [(label, path)] for distinct filesystems worth showing."""
    candidates = [
        ("Root (/)", "/"),
        ("Nix store (/nix)", "/nix"),
        ("Boot (/boot)", "/boot"),
        ("Home (/home)", "/home"),
    ]
    seen: set[int] = set()
    result: list[tuple[str, str]] = []
    for label, path in candidates:
        try:
            dev = os.stat(path).st_dev
        except OSError:
            continue
        if dev in seen:
            continue
        seen.add(dev)
        result.append((label, path))
    return result


# --------------------------------------------------------------------- misc
def uptime_seconds(path: str = "/proc/uptime") -> float:
    try:
        with open(path, "r", encoding="ascii") as fh:
            return float(fh.read().split()[0])
    except (OSError, ValueError, IndexError):
        return 0.0


def load_average() -> tuple[float, float, float]:
    try:
        return os.getloadavg()
    except OSError:
        return (0.0, 0.0, 0.0)


def cpu_model(path: str = "/proc/cpuinfo") -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith(("model name", "hardware", "cpu model")):
                    return line.split(":", 1)[1].strip()
    except (OSError, IndexError):
        pass
    return platform.processor() or platform.machine() or "unknown"


@dataclass
class StaticInfo:
    hostname: str = ""
    kernel: str = ""
    cpu: str = ""
    cores: int = 0
    session: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def static_info() -> StaticInfo:
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
    return StaticInfo(
        hostname=socket.gethostname(),
        kernel=platform.release(),
        cpu=cpu_model(),
        cores=os.cpu_count() or 0,
        session=f"{desktop} ({session_type})",
    )
