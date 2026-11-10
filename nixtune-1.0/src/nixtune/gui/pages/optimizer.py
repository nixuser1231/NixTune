from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QScrollArea, QVBoxLayout, QWidget

from ...core import optimizer
from ..jobs import get_jobs
from ..state import shared
from ..widgets import Card, SnippetBox, escape, make_badge, make_button, open_doc_url
from .base import Page

RISK_LABEL = {"info": ("INFO", "info"), "low": ("LOW RISK", "low"), "review": ("REVIEW FIRST", "review")}


class RecommendationCard(Card):
    def __init__(self, rec: optimizer.Recommendation, parent: Optional[QWidget] = None) -> None:
        super().__init__("", parent)
        head = QHBoxLayout()
        title = QLabel(rec.title)
        title.setObjectName("h2")
        title.setWordWrap(True)
        text, level = RISK_LABEL.get(rec.risk, ("INFO", "info"))
        head.addWidget(title, 1)
        head.addWidget(make_badge(text, level))
        self.body.addLayout(head)

        def line(label: str, text: str) -> None:
            lbl = QLabel(f"<b>{escape(label)}</b> {escape(text)}")
            lbl.setWordWrap(True)
            self.body.addWidget(lbl)

        summary = QLabel(escape(rec.summary))
        summary.setWordWrap(True)
        self.body.addWidget(summary)
        line("Why you see this:", rec.evidence)
        line("What it changes:", rec.effect)
        line("How to undo:", rec.revert)
        if rec.snippet:
            self.body.addWidget(QLabel("<b>Configuration snippet</b> (NIXTUNE does not apply it for you):"))
            self.body.addWidget(SnippetBox(rec.snippet))
            how = QLabel(escape(rec.how_to_apply).replace("\n", "<br>"))
            how.setObjectName("muted")
            how.setWordWrap(True)
            self.body.addWidget(how)
        if rec.doc_url:
            btn = make_button("Read the official documentation")
            btn.clicked.connect(lambda _checked=False, url=rec.doc_url: open_doc_url(url, self))
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch(1)
            self.body.addLayout(row)


class OptimizerPage(Page):
    TITLE = "Optimizer"
    SUBTITLE = ("Safe, explained recommendations. Each one shows why it appears, what it changes and how to undo it. "
                "NIXTUNE never modifies your configuration - you decide what to copy.")

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._busy = False
        self._first = True
        bar = QHBoxLayout()
        self.btn = make_button("Analyze system", "primary")
        self.btn.clicked.connect(self._run)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        bar.addWidget(self.btn)
        bar.addWidget(self.status, 1)
        self.root.addLayout(bar)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.root.addWidget(self.progress)

        self.area = QScrollArea()
        self.area.setWidgetResizable(True)
        self.container = QWidget()
        self.cards = QVBoxLayout(self.container)
        self.cards.setContentsMargins(0, 0, 6, 0)
        self.cards.setSpacing(12)
        self.cards.addStretch(1)
        self.area.setWidget(self.container)
        self.root.addWidget(self.area, 1)

    def on_show(self) -> None:
        if self._first and not self._busy:
            self._first = False
            self._run()

    def _run(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText("Inspecting system...")
        dead = shared.dead_bytes
        get_jobs().submit(lambda: optimizer.recommend(optimizer.gather(dead_bytes=dead)),
                          self._done, self._failed)

    def _failed(self, message: str) -> None:
        self._busy = False
        self.btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText(f"Analysis failed: {message}")

    def _done(self, recs: list) -> None:
        self._busy = False
        self.btn.setEnabled(True)
        self.progress.setVisible(False)
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, rec in enumerate(recs):
            self.cards.insertWidget(i, RecommendationCard(rec))
        self.status.setText(f"{len(recs)} recommendation(s).")
