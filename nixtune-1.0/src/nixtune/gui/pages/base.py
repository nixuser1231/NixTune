from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class Page(QWidget):
    """Base class: title, subtitle and show/hide hooks used by the main window."""

    TITLE = ""
    SUBTITLE = ""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(28, 24, 28, 20)
        self.root.setSpacing(14)
        head = QLabel(self.TITLE)
        head.setObjectName("h1")
        sub = QLabel(self.SUBTITLE)
        sub.setObjectName("subtitle")
        sub.setWordWrap(True)
        self.root.addWidget(head)
        self.root.addWidget(sub)

    def on_show(self) -> None:
        """Called every time the page becomes visible."""

    def on_hide(self) -> None:
        """Called when the user navigates away."""
