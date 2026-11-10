from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QSplitter, QTextBrowser, QWidget)

from ...core import diagnostics, reporting
from ..jobs import get_jobs
from ..theme import PALETTE, SEVERITY_COLORS
from ..widgets import copy_to_clipboard, escape, make_badge, make_button, make_table, open_doc_url, table_item
from .base import Page


class DiagnosticsPage(Page):
    TITLE = "Diagnostics"
    SUBTITLE = "Detects missing dependencies, common errors and configuration problems. Read-only."

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.findings: list[diagnostics.Finding] = []
        self._busy = False
        self._first = True

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.btn_run = make_button("Run diagnostics", "primary")
        self.btn_run.clicked.connect(self._run)
        self.btn_save = make_button("Save report...")
        self.btn_save.clicked.connect(self._save)
        self.btn_copy = make_button("Copy report")
        self.btn_copy.clicked.connect(self._copy)
        self.badges = QHBoxLayout()
        self.badges.setSpacing(6)
        bar.addWidget(self.btn_run)
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_copy)
        bar.addSpacing(10)
        bar.addLayout(self.badges)
        bar.addStretch(1)
        self.root.addLayout(bar)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        self.root.addWidget(self.progress)
        self.root.addWidget(self.status)

        split = QSplitter(Qt.Orientation.Horizontal)
        self.table = make_table(["Severity", "Category", "Finding"], stretch_col=2)
        self.table.itemSelectionChanged.connect(self._selected)
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.anchorClicked.connect(lambda url: open_doc_url(url.toString(), self))
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.root.addWidget(split, 1)

    def on_show(self) -> None:
        if self._first and not self._busy:
            self._first = False
            self._run()

    def _run(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.progress.setVisible(True)
        self.btn_run.setEnabled(False)
        get_jobs().submit_streaming(lambda emit: diagnostics.run_all(progress=emit),
                                    on_line=self.status.setText, on_result=self._done, on_error=self._failed)

    def _failed(self, message: str) -> None:
        self._busy = False
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        self.status.setText(f"Diagnostics failed to run: {message}")

    def _done(self, findings: list) -> None:
        self._busy = False
        self.findings = findings
        self.progress.setVisible(False)
        self.btn_run.setEnabled(True)
        c = diagnostics.counts(findings)
        self.status.setText(f"{len(findings)} checks completed.")
        while self.badges.count():
            item = self.badges.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for level, label in (("error", "errors"), ("warning", "warnings"), ("info", "notes"), ("ok", "ok")):
            self.badges.addWidget(make_badge(f"{c[level]} {label}", level))
        self.table.setRowCount(len(findings))
        for row, f in enumerate(findings):
            colour = SEVERITY_COLORS.get(f.severity, PALETTE["text"])
            self.table.setItem(row, 0, table_item(f.severity.upper(), colour))
            self.table.setItem(row, 1, table_item(f.category))
            self.table.setItem(row, 2, table_item(f.title))
        if findings:
            self.table.selectRow(0)

    def _selected(self) -> None:
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if not rows or rows[0] >= len(self.findings):
            return
        f = self.findings[rows[0]]
        colour = SEVERITY_COLORS.get(f.severity, PALETTE["text"])
        parts = [f"<h3 style='color:{colour}'>{escape(f.title)}</h3>",
                 f"<p style='color:#8f98c8'>{escape(f.category)} &middot; {escape(f.severity)}</p>"]
        if f.detail:
            parts.append(f"<p><b>Details</b><br><pre>{escape(f.detail)}</pre></p>")
        if f.remedy:
            parts.append(f"<p><b>Suggested fix</b><br><pre>{escape(f.remedy)}</pre></p>")
        if f.doc_url:
            parts.append(f"<p><a href='{escape(f.doc_url)}'>Open the official documentation</a></p>")
        self.detail.setHtml("".join(parts))

    # ------------------------------------------------------------- report
    def _report_text(self) -> str:
        return reporting.build_report({"Diagnostics": diagnostics.render_text(self.findings)}
                                      if self.findings else None)

    def _save(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save diagnostic report", "nixtune-report.txt", "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self._report_text())
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self.status.setText(f"Report saved to {path}. Home directory and host name were redacted.")

    def _copy(self) -> None:
        copy_to_clipboard(self._report_text())
        self.status.setText("Report copied to the clipboard (home directory and host name redacted).")
