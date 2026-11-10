from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from ...constants import DOCS_URL
from ...core import docs
from ..widgets import Card, CommandBox, copy_to_clipboard, escape, make_button, open_doc_url
from .base import Page


class DocsPage(Page):
    TITLE = "Documentation"
    SUBTITLE = ("Quick access to the official NixOS documentation. Links open in your own browser; "
                "NIXTUNE downloads nothing.")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        hero = Card("Official NixOS manual")
        hero_text = QLabel(f"The authoritative reference: <b>{escape(DOCS_URL)}</b>")
        hero_text.setWordWrap(True)
        hero.body.addWidget(hero_text)
        row = QHBoxLayout()
        self.btn_open = make_button("Open the NixOS manual", "primary")
        self.btn_open.clicked.connect(lambda: open_doc_url(DOCS_URL, self))
        self.btn_copy = make_button("Copy link")
        self.btn_copy.clicked.connect(lambda: copy_to_clipboard(DOCS_URL))
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_copy)
        local = docs.local_manual()
        if local:
            self.btn_local = make_button("Open the manual installed on this system")
            self.btn_local.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(local)))
            row.addWidget(self.btn_local)
        row.addStretch(1)
        hero.body.addLayout(row)
        self.root.addWidget(hero)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter topics (gc, services, options, install...)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.root.addWidget(self.search)

        area = QScrollArea()
        area.setWidgetResizable(True)
        holder = QWidget()
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 6, 0)
        col.setSpacing(12)

        self._cards: list[tuple[DocLinkCard, docs.DocLink]] = []
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        col.addLayout(self.grid)
        for link in docs.DOC_LINKS:
            self._cards.append((DocLinkCard(link, self), link))
        self._layout_cards("")

        offline = Card("Handy commands (work offline)")
        for cmd, desc in docs.OFFLINE_COMMANDS:
            label = QLabel(escape(desc))
            label.setObjectName("muted")
            offline.body.addWidget(label)
            offline.body.addWidget(CommandBox(cmd))
        col.addWidget(offline)
        col.addStretch(1)
        area.setWidget(holder)
        self.root.addWidget(area, 1)

    def _layout_cards(self, needle: str) -> None:
        needle = needle.strip().lower()
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().setVisible(False)
        slot = 0
        for card, link in self._cards:
            hay = f"{link.title} {link.description} {link.topic}".lower()
            if needle and needle not in hay:
                continue
            card.setVisible(True)
            self.grid.addWidget(card, slot // 2, slot % 2)
            slot += 1
        self.grid.setColumnStretch(0, 1)
        self.grid.setColumnStretch(1, 1)

    def _filter(self, text: str) -> None:
        self._layout_cards(text)


class DocLinkCard(Card):
    def __init__(self, link: docs.DocLink, page: QWidget) -> None:
        super().__init__("")
        title = QLabel(link.title)
        title.setObjectName("h2")
        desc = QLabel(link.description)
        desc.setObjectName("muted")
        desc.setWordWrap(True)
        self.body.addWidget(title)
        self.body.addWidget(desc)
        row = QHBoxLayout()
        open_btn = make_button("Open")
        open_btn.clicked.connect(lambda _checked=False, u=link.url: open_doc_url(u, page))
        copy_btn = make_button("Copy link")
        copy_btn.clicked.connect(lambda _checked=False, u=link.url: copy_to_clipboard(u))
        row.addWidget(open_btn)
        row.addWidget(copy_btn)
        row.addStretch(1)
        self.body.addLayout(row)
