from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...core import nixenv, sysinfo
from ..jobs import get_jobs
from ..widgets import Card, StatTile, UsageBar, escape
from .base import Page


def _gather_static() -> dict[str, str]:
    info = sysinfo.static_info()
    system = nixenv.current_system_path() or "n/a"
    return {
        "Host": info.hostname,
        "Operating system": nixenv.pretty_os_name(),
        "NixOS version": nixenv.nixos_version() or "not NixOS",
        "Nix": nixenv.nix_version() or "not found",
        "Kernel": info.kernel,
        "CPU": f"{info.cpu} ({info.cores} threads)",
        "Session": info.session,
        "Current system": system,
    }


class DashboardPage(Page):
    TITLE = "Dashboard"
    SUBTITLE = "Live view of this machine: CPU, memory, storage and uptime."

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.sampler = sysinfo.CpuSampler()
        self._ticks = 0
        self._static_loaded = False
        self._core_bars: list[UsageBar] = []
        self._core_labels: list[QLabel] = []
        self._fs_rows: dict[str, tuple[UsageBar, QLabel]] = {}

        tiles = QGridLayout()
        tiles.setSpacing(14)
        self.cpu_tile = StatTile("CPU", sparkline=True)
        self.mem_tile = StatTile("Memory", sparkline=True)
        self.disk_tile = StatTile("Disk (/)", bar=True)
        self.up_tile = StatTile("Uptime")
        for col, tile in enumerate((self.cpu_tile, self.mem_tile, self.disk_tile, self.up_tile)):
            tiles.addWidget(tile, 0, col)
            tiles.setColumnStretch(col, 1)
        self.root.addLayout(tiles)

        lower = QHBoxLayout()
        lower.setSpacing(14)
        left = QVBoxLayout()
        right = QVBoxLayout()

        self.cores_card = Card("CPU cores")
        self.cores_grid = QGridLayout()
        self.cores_grid.setHorizontalSpacing(14)
        self.cores_grid.setVerticalSpacing(6)
        self.cores_card.body.addLayout(self.cores_grid)
        left.addWidget(self.cores_card)
        left.addStretch(1)

        self.fs_card = Card("Filesystems")
        self.fs_layout = QVBoxLayout()
        self.fs_layout.setSpacing(8)
        self.fs_card.body.addLayout(self.fs_layout)
        right.addWidget(self.fs_card)

        self.info_card = Card("System")
        self.info_label = QLabel("Loading...")
        self.info_label.setWordWrap(True)
        self.info_label.setTextFormat(Qt.TextFormat.RichText)
        self.info_card.body.addWidget(self.info_label)
        right.addWidget(self.info_card)
        right.addStretch(1)

        lower.addLayout(left, 1)
        lower.addLayout(right, 1)
        self.root.addLayout(lower, 1)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

    # -------------------------------------------------------------- hooks
    def on_show(self) -> None:
        self._tick()
        self.timer.start()
        if not self._static_loaded:
            self._static_loaded = True
            get_jobs().submit(_gather_static, self._on_static, self._on_static_error)

    def on_hide(self) -> None:
        self.timer.stop()

    # ------------------------------------------------------------ updates
    def _tick(self) -> None:
        overall, cores = self.sampler.sample()
        load = sysinfo.load_average()
        self.cpu_tile.set_value(f"{overall:.0f}%")
        self.cpu_tile.set_sub(f"Load average {load[0]:.2f}  {load[1]:.2f}  {load[2]:.2f}")
        self.cpu_tile.push(overall)

        mem = sysinfo.memory()
        self.mem_tile.set_value(f"{mem.percent:.0f}%")
        swap = (f"Swap {sysinfo.format_bytes(mem.swap_used)} / {sysinfo.format_bytes(mem.swap_total)}"
                if mem.swap_total else "No swap configured")
        self.mem_tile.set_sub(f"{sysinfo.format_bytes(mem.used)} of {sysinfo.format_bytes(mem.total)} - {swap}")
        self.mem_tile.push(mem.percent)

        self.up_tile.set_value(sysinfo.format_duration(sysinfo.uptime_seconds()))
        self.up_tile.set_sub("since last boot")

        self._update_cores(cores)
        if self._ticks % 5 == 0:
            self._update_disks()
        self._ticks += 1

    def _update_cores(self, cores: list[float]) -> None:
        if len(cores) != len(self._core_bars):
            for w in self._core_labels + self._core_bars:
                w.deleteLater()
            self._core_bars.clear()
            self._core_labels.clear()
            for i in range(len(cores)):
                label = QLabel(f"CPU {i}")
                label.setObjectName("muted")
                bar = UsageBar()
                pair, col = divmod(i, 2)
                self.cores_grid.addWidget(label, pair, col * 3)
                self.cores_grid.addWidget(bar, pair, col * 3 + 1)
                self._core_labels.append(label)
                self._core_bars.append(bar)
            for c in (1, 4):
                self.cores_grid.setColumnStretch(c, 1)
        for i, pct in enumerate(cores):
            self._core_bars[i].set_value(pct)
            self._core_labels[i].setText(f"CPU {i}  {pct:3.0f}%")

    def _update_disks(self) -> None:
        root = sysinfo.disk_usage("/")
        if root:
            self.disk_tile.set_value(f"{root.percent:.0f}%")
            self.disk_tile.set_sub(f"{sysinfo.format_bytes(root.free)} free of {sysinfo.format_bytes(root.total)}")
            self.disk_tile.set_bar(root.percent)
        for label, path in sysinfo.interesting_mounts():
            usage = sysinfo.disk_usage(path)
            if usage is None:
                continue
            if path not in self._fs_rows:
                title = QLabel(label)
                bar = UsageBar()
                detail = QLabel("")
                detail.setObjectName("muted")
                holder = QWidget()
                col = QVBoxLayout(holder)
                col.setContentsMargins(0, 0, 0, 0)
                col.setSpacing(3)
                col.addWidget(title)
                col.addWidget(bar)
                col.addWidget(detail)
                self.fs_layout.addWidget(holder)
                self._fs_rows[path] = (bar, detail)
            bar, detail = self._fs_rows[path]
            bar.set_value(usage.percent)
            detail.setText(f"{usage.percent:.0f}% used - {sysinfo.format_bytes(usage.used)} of "
                           f"{sysinfo.format_bytes(usage.total)} ({sysinfo.format_bytes(usage.free)} free)")

    def _on_static(self, info: dict) -> None:
        rows = "".join(
            f"<tr><td style='color:#8f98c8; padding-right:14px; padding-bottom:4px'>{escape(k)}</td>"
            f"<td>{escape(str(v))}</td></tr>" for k, v in info.items())
        self.info_label.setText(f"<table>{rows}</table>")

    def _on_static_error(self, message: str) -> None:
        self.info_label.setText(f"Could not read system information: {escape(message)}")
