from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel, QSpinBox,
                               QVBoxLayout, QWidget)

from ...core import generations
from ..jobs import get_jobs
from ..theme import PALETTE
from ..widgets import Card, CommandBox, make_button, make_table, table_item
from .base import Page


class GenerationsPage(Page):
    TITLE = "Generations"
    SUBTITLE = ("Every rebuild creates a generation you can boot back into. NIXTUNE only lists them; "
                "it never deletes any.")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._profiles: list[generations.ProfileRef] = []
        self._gens: list[generations.Generation] = []
        self._loaded = False

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.profile_box = QComboBox()
        self.profile_box.setMinimumWidth(240)
        self.profile_box.currentIndexChanged.connect(self._load)
        self.btn_refresh = make_button("Refresh", "primary")
        self.btn_refresh.clicked.connect(self._load)
        self.summary = QLabel("")
        self.summary.setObjectName("muted")
        bar.addWidget(QLabel("Profile:"))
        bar.addWidget(self.profile_box)
        bar.addWidget(self.btn_refresh)
        bar.addWidget(self.summary, 1)
        self.root.addLayout(bar)

        self.table = make_table(["#", "Created", "Version", "Kernel", "State"], stretch_col=2)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.root.addWidget(self.table, 1)

        card = Card("Cleanup commands - for you to review and run yourself")
        note = QLabel(
            "NIXTUNE will not remove generations. If you decide to, copy a command and run it in a terminal. "
            "Keep at least one known-good generation so you can roll back. After deleting system generations, "
            "run <code>sudo nixos-rebuild boot</code> to refresh the boot menu, then collect garbage.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        card.body.addWidget(note)

        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setValue(30)
        self.days.setSuffix(" days")
        self.keep = QSpinBox()
        self.keep.setRange(1, 500)
        self.keep.setValue(5)
        self.keep.setPrefix("keep ")
        self.cmd_days = CommandBox()
        self.cmd_keep = CommandBox()
        self.cmd_sel = CommandBox()
        self.sel_hint = QLabel("")
        self.sel_hint.setObjectName("muted")
        self.sel_hint.setWordWrap(True)
        for label, spin, box in (("Delete generations older than", self.days, self.cmd_days),
                                 ("Keep only the newest", self.keep, self.cmd_keep)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(spin)
            row.addStretch(1)
            card.body.addLayout(row)
            card.body.addWidget(box)
        card.body.addWidget(QLabel("Delete the generations selected above:"))
        card.body.addWidget(self.cmd_sel)
        card.body.addWidget(self.sel_hint)
        self.days.valueChanged.connect(self._update_commands)
        self.keep.valueChanged.connect(self._update_commands)
        self.root.addWidget(card)

    def on_show(self) -> None:
        if not self._loaded:
            self._loaded = True
            self._profiles = generations.discover_profiles()
            self.profile_box.blockSignals(True)
            self.profile_box.clear()
            for i, ref in enumerate(self._profiles):
                self.profile_box.addItem(ref.label, i)
            self.profile_box.blockSignals(False)
            self._load()

    # ------------------------------------------------------------ loading
    def _current_ref(self) -> Optional[generations.ProfileRef]:
        idx = self.profile_box.currentIndex()
        return self._profiles[idx] if 0 <= idx < len(self._profiles) else None

    def _load(self) -> None:
        ref = self._current_ref()
        if ref is None:
            self.summary.setText("No Nix profiles with generations were found on this machine.")
            self.table.setRowCount(0)
            return
        self.summary.setText("Loading...")
        get_jobs().submit(lambda: generations.list_generations(ref), self._on_loaded,
                          lambda m: self.summary.setText(f"Error: {m}"))

    def _on_loaded(self, gens: list) -> None:
        self._gens = gens
        self.table.setRowCount(len(gens))
        for row, g in enumerate(gens):
            state = []
            if g.is_current:
                state.append("current")
            if g.is_booted:
                state.append("booted")
            if g.is_default:
                state.append("next boot")
            colour = PALETTE["ok"] if g.is_current else None
            self.table.setItem(row, 0, table_item(str(g.number), colour, right=True, data=g.number))
            self.table.setItem(row, 1, table_item(g.created.strftime("%Y-%m-%d %H:%M")))
            self.table.setItem(row, 2, table_item(g.version or "-"))
            self.table.setItem(row, 3, table_item(g.kernel or "-"))
            self.table.setItem(row, 4, table_item(", ".join(state), colour))
        self.summary.setText(f"{len(gens)} generation(s)")
        self._update_commands()
        self._selection_changed()

    # ----------------------------------------------------------- commands
    def _update_commands(self) -> None:
        ref = self._current_ref()
        if ref is None:
            return
        self.cmd_days.set_command(generations.older_than_command(self.days.value(), ref))
        self.cmd_keep.set_command(generations.keep_last_command(self.keep.value(), ref))

    def _selection_changed(self) -> None:
        ref = self._current_ref()
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if ref is None or not rows:
            self.cmd_sel.set_command("")
            self.sel_hint.setText("Select one or more rows to build a command.")
            return
        chosen = [self._gens[r] for r in rows if r < len(self._gens)]
        protected = [g.number for g in chosen if g.is_current or g.is_booted or g.is_default]
        if protected:
            self.cmd_sel.set_command("")
            self.sel_hint.setText(
                "Generation(s) " + ", ".join(map(str, protected)) +
                " are in use (current, booted or next-boot). Deselect them: they must not be deleted.")
            return
        try:
            self.cmd_sel.set_command(generations.delete_command(ref, [g.number for g in chosen]))
            self.sel_hint.setText(f"{len(chosen)} generation(s) selected.")
        except ValueError as exc:
            self.cmd_sel.set_command("")
            self.sel_hint.setText(str(exc))
