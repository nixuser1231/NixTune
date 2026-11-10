from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QSplitter, QWidget)
from PySide6.QtCore import Qt

from ...core import services
from ..jobs import get_jobs
from ..theme import PALETTE
from ..widgets import make_button, make_table, mono_font, table_item
from .base import Page

MAX_ROWS = 2500


class ServicesPage(Page):
    TITLE = "Services"
    SUBTITLE = ("systemd services and their state (read-only). On NixOS, services are managed "
                "declaratively in your configuration.")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._units: list[services.Unit] = []
        self._shown: list[services.Unit] = []
        self._token = 0
        self._loaded = False

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter by name or description...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._populate)
        self.state_box = QComboBox()
        for label, key in (("All", "all"), ("Running", "running"), ("Failed", "failed"),
                           ("Inactive", "inactive"), ("Enabled", "enabled")):
            self.state_box.addItem(label, key)
        self.state_box.currentIndexChanged.connect(self._populate)
        self.scope_box = QComboBox()
        self.scope_box.addItem("System services", "system")
        self.scope_box.addItem("User services", "user")
        self.scope_box.currentIndexChanged.connect(self._load)
        self.btn_refresh = make_button("Refresh", "primary")
        self.btn_refresh.clicked.connect(self._load)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.state_box)
        bar.addWidget(self.scope_box)
        bar.addWidget(self.btn_refresh)
        self.root.addLayout(bar)

        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        self.root.addWidget(self.summary)

        split = QSplitter(Qt.Orientation.Vertical)
        self.table = make_table(["Unit", "Active", "Sub", "Enabled", "Description"], stretch_col=4)
        self.table.itemSelectionChanged.connect(self._selected)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setFont(mono_font())
        self.details.setPlaceholderText("Select a service to see its details.")
        split.addWidget(self.table)
        split.addWidget(self.details)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.root.addWidget(split, 1)

    def on_show(self) -> None:
        if not self._loaded:
            self._loaded = True
            self._load()

    def _scope(self) -> str:
        return self.scope_box.currentData() or "system"

    def _load(self) -> None:
        self.summary.setText("Loading services...")
        scope = self._scope()
        get_jobs().submit(lambda: services.list_units(scope), self._on_loaded,
                          lambda m: self.summary.setText(f"Error: {m}"))

    def _on_loaded(self, result) -> None:
        units, error = result
        self._units = units
        if error:
            self.summary.setText(error)
            self.table.setRowCount(0)
            return
        self._populate()

    def _populate(self) -> None:
        self._shown = services.filter_units(
            self._units, self.search.text(), self.state_box.currentData() or "all")[:MAX_ROWS]
        stats = services.summarize(self._units)
        self.summary.setText(
            f"{stats['total']} services - {stats['running']} running, {stats['failed']} failed, "
            f"{stats['inactive']} inactive. Showing {len(self._shown)}.")
        self.table.setRowCount(len(self._shown))
        for row, u in enumerate(self._shown):
            colour = PALETTE["err"] if u.is_failed else PALETTE["ok"] if u.is_running else PALETTE["muted"]
            self.table.setItem(row, 0, table_item(u.name))
            self.table.setItem(row, 1, table_item(u.active, colour))
            self.table.setItem(row, 2, table_item(u.sub, colour))
            self.table.setItem(row, 3, table_item(u.enabled or "-"))
            self.table.setItem(row, 4, table_item(u.description))

    def _selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows or rows[0] >= len(self._shown):
            return
        name = self._shown[rows[0]].name
        scope = self._scope()
        self._token += 1
        token = self._token
        self.details.setPlainText("Loading...")
        get_jobs().submit(lambda: services.unit_details(name, scope),
                          lambda text: self._show_details(token, text),
                          lambda m: self._show_details(token, f"Error: {m}"))

    def _show_details(self, token: int, text: str) -> None:
        if token == self._token:  # ignore stale answers from earlier selections
            self.details.setPlainText(text)
