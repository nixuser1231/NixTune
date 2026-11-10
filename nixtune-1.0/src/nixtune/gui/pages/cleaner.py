from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QProgressBar,
                               QWidget)

from ...core import gc, privileged, sysinfo
from ..jobs import get_jobs
from ..state import shared
from ..widgets import (ConfirmDialog, ManualCommandDialog, StatTile, escape, make_button,
                       make_table, mono_font, table_item)
from .base import Page

MAX_ROWS = 300


class CleanerPage(Page):
    TITLE = "Nix Cleaner"
    SUBTITLE = ("Preview which store paths garbage collection would remove and how much space that frees. "
                "Nothing is deleted until you confirm.")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.analysis: Optional[gc.GcAnalysis] = None
        self._busy = False

        tiles = QHBoxLayout()
        tiles.setSpacing(14)
        self.t_paths = StatTile("Unreachable store paths")
        self.t_size = StatTile("Reclaimable space")
        self.t_roots = StatTile("Garbage-collector roots")
        for t in (self.t_paths, self.t_size, self.t_roots):
            tiles.addWidget(t, 1)
        self.root.addLayout(tiles)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.btn_analyze = make_button("Analyze", "primary", "Read-only preview (nix-store --gc --print-dead)")
        self.btn_gc = make_button("Collect garbage...", "danger", "Delete the unreachable paths listed below")
        self.btn_opt = make_button("Optimise store...", "", "Hard-link identical files to save space")
        self.btn_gc.setEnabled(False)
        self.btn_analyze.clicked.connect(self._analyze)
        self.btn_gc.clicked.connect(lambda: self._confirm("gc"))
        self.btn_opt.clicked.connect(lambda: self._confirm("optimise"))
        actions.addWidget(self.btn_analyze)
        actions.addWidget(self.btn_gc)
        actions.addWidget(self.btn_opt)
        actions.addStretch(1)
        self.root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.status = QLabel("Click Analyze to scan the Nix store.")
        self.status.setObjectName("muted")
        self.root.addWidget(self.progress)
        self.root.addWidget(self.status)

        self.table = make_table(["Largest unreachable store paths", "Size"], stretch_col=0)
        self.root.addWidget(self.table, 1)

        self.roots_note = QLabel("")
        self.roots_note.setObjectName("note")
        self.roots_note.setWordWrap(True)
        self.roots_note.setVisible(False)
        self.root.addWidget(self.roots_note)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font())
        self.log.setMaximumBlockCount(5000)
        self.log.setPlaceholderText("Output of cleanup actions appears here.")
        self.log.setMaximumHeight(130)
        self.root.addWidget(self.log)

        safety = QLabel("Safety: NIXTUNE never deletes system generations and never edits your configuration. "
                        "Collecting garbage removes only store paths nothing references.")
        safety.setObjectName("note")
        safety.setWordWrap(True)
        self.root.addWidget(safety)

    def on_show(self) -> None:
        if self.analysis is None and not self._busy:
            self._analyze()

    # ----------------------------------------------------------- analysis
    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._busy = busy
        self.progress.setVisible(busy)
        self.btn_analyze.setEnabled(not busy)
        self.btn_opt.setEnabled(not busy)
        self.btn_gc.setEnabled(not busy and bool(self.analysis and self.analysis.ok and self.analysis.count))
        if message:
            self.status.setText(message)

    def _analyze(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "Analyzing the Nix store...")
        get_jobs().submit_streaming(
            lambda emit: gc.analyze(progress=emit),
            on_line=self.status.setText, on_result=self._on_analysis, on_error=self._on_error)

    def _on_analysis(self, result: gc.GcAnalysis) -> None:
        self.analysis = result
        if not result.ok:
            self._set_busy(False, f"Analysis failed: {result.error}")
            self.t_paths.set_value("--")
            self.t_size.set_value("--")
            return
        approx = "~" if result.estimated else ""
        self.t_paths.set_value(f"{result.count:,}")
        self.t_paths.set_sub("not referenced by any root")
        self.t_size.set_value(f"{approx}{sysinfo.format_bytes(result.total_bytes)}")
        self.t_size.set_sub("estimate extrapolated from a sample" if result.estimated else "NAR size of those paths")
        shared.dead_bytes = result.total_bytes
        if result.roots:
            r = result.roots
            self.t_roots.set_value(f"{r.total:,}")
            self.t_roots.set_sub(f"{r.profiles} profile, {r.system} system, {r.running} running, {r.other} other")
            if r.result_links:
                shown = "<br>".join(f"&bull; {escape(link)}" for link, _t in r.result_links[:6])
                more = f"<br>... and {len(r.result_links) - 6} more" if len(r.result_links) > 6 else ""
                self.roots_note.setText(
                    "These `result` links or direct roots keep build outputs alive. Deleting a link you no longer "
                    f"need (yourself, in a terminal) lets the next collection free more:<br>{shown}{more}")
                self.roots_note.setVisible(True)
            else:
                self.roots_note.setVisible(False)
        self.table.setRowCount(0)
        rows = result.dead[:MAX_ROWS]
        self.table.setRowCount(len(rows))
        for i, item in enumerate(rows):
            self.table.setItem(i, 0, table_item(item.name))
            self.table.setItem(i, 1, table_item(
                sysinfo.format_bytes(item.size) if item.size is not None else "?", right=True))
        suffix = f" Showing the {len(rows)} largest." if result.count > MAX_ROWS else ""
        self._set_busy(False, f"Analysis finished in {result.seconds:.1f}s.{suffix}")

    def _on_error(self, message: str) -> None:
        self._set_busy(False, f"Error: {message}")

    # ------------------------------------------------------------ actions
    def _confirm(self, action: str) -> None:
        if self._busy:
            return
        plan = privileged.plan(action)
        if action == "gc":
            if not (self.analysis and self.analysis.ok and self.analysis.count):
                QMessageBox.information(self, "Nothing to collect", "Run Analyze first; no unreachable paths were found.")
                return
            a = self.analysis
            size = ("about " if a.estimated else "") + sysinfo.format_bytes(a.total_bytes)
            body = (f"<p>This will <b>permanently delete {a.count:,} unreachable store paths</b>, freeing {size}.</p>"
                    "<ul><li>System generations are <b>not</b> deleted.</li>"
                    "<li>Your configuration is <b>not</b> modified.</li>"
                    "<li>Administrator authentication is requested through polkit.</li>"
                    "<li>Once started it cannot be cancelled from here; letting it finish is safe.</li></ul>")
            heading, confirm, danger = "Delete unreachable store paths?", "Delete paths", True
        else:
            body = (f"<p>{plan.action.description}</p><ul><li>No store path is removed.</li>"
                    "<li>It can take a long time on large stores.</li>"
                    "<li>Administrator authentication is requested through polkit.</li></ul>")
            heading, confirm, danger = "Optimise the Nix store?", "Optimise", False

        if not plan.available:
            ManualCommandDialog(self, plan.action.title, plan.unavailable_reason, plan.manual_command).exec()
            return
        if ConfirmDialog.ask(self, plan.action.title, heading, body, command=plan.display_command,
                             confirm_text=confirm, danger=danger):
            self._run_action(action)

    def _run_action(self, action: str) -> None:
        self.log.clear()
        self._set_busy(True, "Waiting for authentication, then running...")
        get_jobs().submit_streaming(
            lambda emit: privileged.run_action(action, emit),
            on_line=self.log.appendPlainText, on_result=self._on_action_done, on_error=self._on_error)

    def _on_action_done(self, result) -> None:
        if result.ok:
            self._set_busy(False, "Completed successfully. Re-analyzing...")
            self.analysis = None
            self._analyze()
            return
        hint = privileged.PKEXEC_HINTS.get(result.returncode, result.error_summary())
        self.log.appendPlainText(f"\n[exit status {result.returncode}] {hint}")
        self._set_busy(False, f"The action did not complete: {hint}")
