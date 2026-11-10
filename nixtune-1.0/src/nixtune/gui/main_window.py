"""Main window: sidebar navigation + stacked pages + error reporting dialog."""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QObject, QSize, Qt, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QStackedWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..constants import APP_NAME
from ..core import desktop, nixenv, reporting
from .jobs import get_jobs
from .pages.base import Page
from .pages.cleaner import CleanerPage
from .pages.dashboard import DashboardPage
from .pages.deps import DependenciesPage
from .pages.desktop import DesktopPage
from .pages.diagnostics import DiagnosticsPage
from .pages.docs import DocsPage
from .pages.generations import GenerationsPage
from .pages.optimizer import OptimizerPage
from .pages.services import ServicesPage
from .widgets import make_button, mono_font

PAGES = (
    ("Dashboard", DashboardPage),
    ("Nix Cleaner", CleanerPage),
    ("Generations", GenerationsPage),
    ("Services", ServicesPage),
    ("Diagnostics", DiagnosticsPage),
    ("Optimizer", OptimizerPage),
    ("Dependencies", DependenciesPage),
    ("Documentation", DocsPage),
    ("Desktop Integration", DesktopPage),
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        get_jobs()  # create the job runner on the GUI thread
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)
        icon = desktop.packaged_icon()
        if icon:
            self.setWindowIcon(QIcon(str(icon)))

        central = QWidget()
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 18, 0, 14)
        side.setSpacing(4)

        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(18, 0, 14, 8)
        if icon:
            logo = QLabel()
            logo.setPixmap(QIcon(str(icon)).pixmap(QSize(38, 38)))
            brand_row.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        sub = QLabel(f"v{__version__} for NixOS")
        sub.setObjectName("brandsub")
        titles.addWidget(brand)
        titles.addWidget(sub)
        brand_row.addLayout(titles)
        brand_row.addStretch(1)
        side.addLayout(brand_row)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        side.addWidget(self.nav, 1)

        self.btn_report = make_button("Save error report...")
        self.btn_report.setToolTip("Writes a redacted diagnostic report to a file you choose. Nothing is uploaded.")
        self.btn_report.clicked.connect(self.save_report)
        foot = QVBoxLayout()
        foot.setContentsMargins(14, 0, 14, 0)
        foot.addWidget(self.btn_report)
        side.addLayout(foot)
        outer.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.pages: list[Page] = []
        for title, cls in PAGES:
            page = cls()
            self.pages.append(page)
            self.stack.addWidget(page)
            self.nav.addItem(QListWidgetItem(title))
        outer.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._current = -1
        self.nav.currentRowChanged.connect(self._switch)
        self.nav.setCurrentRow(0)

        self.statusBar().showMessage(self._status_text())
        get_jobs().submit(nixenv.nix_version, self._set_nix_status)

    # --------------------------------------------------------- navigation
    def _switch(self, row: int) -> None:
        if row < 0 or row >= len(self.pages) or row == self._current:
            return
        if 0 <= self._current < len(self.pages):
            self.pages[self._current].on_hide()
        self._current = row
        self.stack.setCurrentIndex(row)
        self.pages[row].on_show()

    def _status_text(self, nix: str = "") -> str:
        base = "Running as a normal user (privileged actions go through polkit, one at a time)"
        return f"{base}  |  {nix}" if nix else base

    def _set_nix_status(self, nix: Optional[str]) -> None:
        self.statusBar().showMessage(self._status_text(nix or "Nix not found"))

    # -------------------------------------------------------------- report
    def save_report(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, "Save error report", "nixtune-report.txt", "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(reporting.build_report())
        except OSError as exc:
            QMessageBox.warning(self, "Could not save", str(exc))
            return
        self.statusBar().showMessage(f"Report saved to {path}", 8000)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt API)
        if 0 <= self._current < len(self.pages):
            self.pages[self._current].on_hide()
        super().closeEvent(event)


# --------------------------------------------------------- error dialog
class ErrorBridge(QObject):
    """Receives error text from any thread and shows the dialog on the GUI thread."""

    raised = Signal(str)

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._open = False
        self._suppressed = 0
        self.raised.connect(self._show, Qt.ConnectionType.QueuedConnection)

    @Slot(str)
    def _show(self, text: str) -> None:
        if self._open:
            self._suppressed += 1
            return
        self._open = True
        try:
            dlg = QDialog(self._window)
            dlg.setWindowTitle("NIXTUNE - unexpected error")
            dlg.resize(720, 460)
            col = QVBoxLayout(dlg)
            col.setContentsMargins(20, 18, 20, 16)
            head = QLabel("Something went wrong")
            head.setObjectName("h2")
            col.addWidget(head)
            info = QLabel("NIXTUNE hit an unexpected error but keeps running. Nothing was changed on your system "
                          "by this error. Details are in the log; you can save a redacted report to share.")
            info.setWordWrap(True)
            info.setObjectName("muted")
            col.addWidget(info)
            box = QPlainTextEdit(text)
            box.setReadOnly(True)
            box.setFont(mono_font())
            col.addWidget(box, 1)
            row = QHBoxLayout()
            row.addStretch(1)
            copy = make_button("Copy details")
            copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
            save = make_button("Save report...")
            save.clicked.connect(lambda: self._window.save_report())
            close = make_button("Close", "primary")
            close.clicked.connect(dlg.accept)
            for b in (copy, save, close):
                row.addWidget(b)
            col.addLayout(row)
            dlg.exec()
        finally:
            self._open = False
            self._suppressed = 0


def install_error_dialog(window: MainWindow) -> ErrorBridge:
    bridge = ErrorBridge(window)
    reporting.install_excepthooks(bridge.raised.emit)
    return bridge
