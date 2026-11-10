from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit, QWidget

from ...core import desktop
from ..widgets import Card, ConfirmDialog, escape, make_button, mono_font
from .base import Page


class DesktopPage(Page):
    TITLE = "Desktop Integration"
    SUBTITLE = ("Adds NIXTUNE to the KDE Plasma application menu (kickoff / application launcher). "
                "Per-user only - no administrator rights needed.")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        card = Card("Status")
        self.status = QLabel("")
        self.status.setWordWrap(True)
        card.body.addWidget(self.status)
        row = QHBoxLayout()
        self.btn_install = make_button("Install launcher...", "primary")
        self.btn_install.clicked.connect(self._install)
        self.btn_remove = make_button("Remove launcher...", "danger")
        self.btn_remove.clicked.connect(self._remove)
        row.addWidget(self.btn_install)
        row.addWidget(self.btn_remove)
        row.addStretch(1)
        card.body.addLayout(row)
        self.root.addWidget(card)

        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(mono_font())
        self.root.addWidget(QLabel("What will be written:"))
        self.root.addWidget(self.preview, 1)

        note = QLabel(
            "If you installed NIXTUNE through the flake or NixOS module, the package already provides its own "
            "menu entry and icon; this page is mainly for running from a source checkout or a ZIP.")
        note.setObjectName("note")
        note.setWordWrap(True)
        self.root.addWidget(note)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        self.result.setObjectName("muted")
        self.root.addWidget(self.result)

    def on_show(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        installed = desktop.is_installed()
        self.status.setText(
            f"<b>{'Installed' if installed else 'Not installed'}</b> - "
            f"{escape(str(desktop.desktop_file_path()))}")
        self.btn_remove.setEnabled(installed)
        self.btn_install.setText("Re-install launcher..." if installed else "Install launcher...")
        plan = desktop.plan_install()
        lines = [f"Starts NIXTUNE via: {plan.launcher.description}", ""]
        for item in plan.files:
            lines.append(f"-> {item.path}   ({item.description})")
        for cmd in plan.commands:
            lines.append(f"-> runs: {' '.join(cmd)}")
        lines += ["", "--- nixtune.desktop ---", plan.desktop_text]
        self.preview.setPlainText("\n".join(lines))

    def _install(self) -> None:
        plan = desktop.plan_install()
        body = ("<p>These files will be created or overwritten in your user directory only:</p>"
                + "<ul>" + "".join(f"<li>{escape(str(i.path))}</li>" for i in plan.files) + "</ul>"
                "<p>No system files are touched and no privileges are used.</p>")
        preview = plan.desktop_text
        if ConfirmDialog.ask(self, "Install launcher", "Add NIXTUNE to the application menu?", body,
                             confirm_text="Install", preview_text=preview):
            try:
                messages = desktop.install(plan)
            except OSError as exc:
                QMessageBox.warning(self, "Could not install", str(exc))
                return
            self.result.setText("\n".join(messages))
            self._refresh()

    def _remove(self) -> None:
        body = ("<p>These files will be deleted:</p><ul>"
                f"<li>{escape(str(desktop.desktop_file_path()))}</li>"
                f"<li>{escape(str(desktop.icon_file_path()))}</li></ul>")
        if ConfirmDialog.ask(self, "Remove launcher", "Remove NIXTUNE from the application menu?", body,
                             confirm_text="Remove", danger=True):
            try:
                messages = desktop.uninstall()
            except OSError as exc:
                QMessageBox.warning(self, "Could not remove", str(exc))
                return
            self.result.setText("\n".join(messages))
            self._refresh()
