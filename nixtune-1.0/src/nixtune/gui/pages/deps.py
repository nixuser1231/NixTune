from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QSplitter, QWidget

from ...core import deps
from ..jobs import get_jobs
from ..theme import PALETTE
from ..widgets import SnippetBox, make_button, make_table, mono_font, table_item
from .base import Page


class DependenciesPage(Page):
    TITLE = "Dependency Manager"
    SUBTITLE = ("Detects missing dependencies and explains how to get them the NixOS way. "
                "NIXTUNE never installs packages or edits your configuration.")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._deps: list[deps.Dependency] = []
        self._first = True

        bar = QHBoxLayout()
        self.btn = make_button("Re-check", "primary")
        self.btn.clicked.connect(self._check)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        bar.addWidget(self.btn)
        bar.addWidget(self.summary, 1)
        self.root.addLayout(bar)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = make_table(["Dependency", "Type", "Status", "Location"], stretch_col=3)
        self.table.itemSelectionChanged.connect(self._selected)
        self.explain = QPlainTextEdit()
        self.explain.setReadOnly(True)
        self.explain.setFont(mono_font())
        self.explain.setPlaceholderText("Select a dependency to see why it is needed and how to get it.")
        split.addWidget(self.table)
        split.addWidget(self.explain)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.root.addWidget(split, 1)

        self.snippet_label = QLabel("")
        self.snippet_label.setObjectName("muted")
        self.snippet_box = SnippetBox("")
        self.snippet_label.setVisible(False)
        self.snippet_box.setVisible(False)
        self.root.addWidget(self.snippet_label)
        self.root.addWidget(self.snippet_box)

    def on_show(self) -> None:
        if self._first:
            self._first = False
            self._check()

    def _check(self) -> None:
        self.btn.setEnabled(False)
        self.summary.setText("Checking...")
        get_jobs().submit(deps.check_all, self._done,
                          lambda m: (self.btn.setEnabled(True), self.summary.setText(f"Error: {m}")))

    def _done(self, items: list) -> None:
        self._deps = items
        self.btn.setEnabled(True)
        self.table.setRowCount(len(items))
        for row, d in enumerate(items):
            colour = PALETTE["ok"] if d.found else (PALETTE["err"] if d.required else PALETTE["warn"])
            self.table.setItem(row, 0, table_item(d.name))
            self.table.setItem(row, 1, table_item(d.kind))
            self.table.setItem(row, 2, table_item(d.status, colour))
            self.table.setItem(row, 3, table_item(d.location))
        required = len(deps.missing(items, required_only=True))
        optional = len(deps.missing(items)) - required
        self.summary.setText(f"{len(items)} checked - {required} required missing, {optional} optional missing.")
        snippet = deps.nix_snippet(items)
        self.snippet_label.setVisible(bool(snippet))
        self.snippet_box.setVisible(bool(snippet))
        if snippet:
            self.snippet_label.setText("Declarative fix for everything missing (review, then add to configuration.nix):")
            self.snippet_box.edit.setPlainText(snippet)
        if items:
            self.table.selectRow(next((i for i, d in enumerate(items) if not d.found), 0))

    def _selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if rows and rows[0] < len(self._deps):
            self.explain.setPlainText(self._deps[rows[0]].explain())
