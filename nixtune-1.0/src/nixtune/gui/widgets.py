"""Reusable widgets: cards, stat tiles, sparkline, usage bar, dialogs."""

from __future__ import annotations

import html
from collections import deque
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFontDatabase, QLinearGradient,
                           QPainter, QPainterPath, QPen)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import docs
from .theme import PALETTE, SEVERITY_COLORS


def mono_font():
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)


def copy_to_clipboard(text: str) -> None:
    QApplication.clipboard().setText(text)


def open_doc_url(url: str, parent: Optional[QWidget] = None) -> bool:
    """Open an official-docs link in the user's browser (https + allow-listed hosts only)."""
    if not docs.is_allowed_doc_url(url):
        QMessageBox.warning(parent, "Link blocked", "Only official NixOS documentation links can be opened from NIXTUNE.")
        return False
    return bool(QDesktopServices.openUrl(QUrl(url)))


def make_button(text: str, variant: str = "", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def make_badge(text: str, level: str) -> QLabel:
    colour = SEVERITY_COLORS.get(level, PALETTE["blue"])
    lbl = QLabel(text)
    lbl.setStyleSheet(
        f"background: {colour}22; color: {colour}; border: 1px solid {colour}66; "
        "border-radius: 9px; padding: 2px 10px; font-weight: 700; font-size: 11px;")
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return lbl


def make_table(headers: list[str], stretch_col: int = -1) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.verticalHeader().setVisible(False)
    table.setWordWrap(False)
    header = table.horizontalHeader()
    header.setHighlightSections(False)
    for col in range(len(headers)):
        header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
    if stretch_col >= 0:
        header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    return table


def table_item(text: str, colour: Optional[str] = None, right: bool = False, data=None) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    if colour:
        item.setForeground(QBrush(QColor(colour)))
    if right:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if data is not None:
        item.setData(Qt.ItemDataRole.UserRole, data)
    return item


def escape(text: str) -> str:
    return html.escape(text, quote=True)


# ------------------------------------------------------------------- layout
class Card(QFrame):
    def __init__(self, title: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(16, 14, 16, 14)
        self._body.setSpacing(8)
        if title:
            lbl = QLabel(title.upper())
            lbl.setObjectName("cardtitle")
            self._body.addWidget(lbl)

    @property
    def body(self) -> QVBoxLayout:
        return self._body


class Sparkline(QWidget):
    def __init__(self, maxlen: int = 60, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data: deque[float] = deque([0.0] * maxlen, maxlen=maxlen)
        self.setMinimumHeight(44)

    def push(self, value: float) -> None:
        self._data.append(float(value))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt API)
        w, h = self.width(), self.height()
        n = len(self._data)
        if n < 2 or w < 4 or h < 4:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        step = w / (n - 1)
        points = [QPointF(i * step, h - 2 - (min(max(v, 0.0), 100.0) / 100.0) * (h - 4))
                  for i, v in enumerate(self._data)]
        line = QPainterPath()
        line.moveTo(points[0])
        for pt in points[1:]:
            line.lineTo(pt)
        area = QPainterPath(line)
        area.lineTo(QPointF(w, h))
        area.lineTo(QPointF(0, h))
        area.closeSubpath()
        top = QColor(PALETTE["blue"])
        top.setAlpha(90)
        bottom = QColor(PALETTE["purple_deep"])
        bottom.setAlpha(0)
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bottom)
        painter.fillPath(area, QBrush(grad))
        painter.setPen(QPen(QColor(PALETTE["blue"]), 2))
        painter.drawPath(line)
        painter.end()


class UsageBar(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self.setFixedHeight(10)
        self.setMinimumWidth(60)

    def set_value(self, percent: float) -> None:
        self._value = min(100.0, max(0.0, float(percent)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        w, h = float(self.width()), float(self.height())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(PALETTE["surface2"]))
        painter.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        fill = w * self._value / 100.0
        if fill >= 1:
            if self._value >= 90:
                brush = QBrush(QColor(PALETTE["err"]))
            elif self._value >= 75:
                brush = QBrush(QColor(PALETTE["warn"]))
            else:
                grad = QLinearGradient(0, 0, w, 0)
                grad.setColorAt(0.0, QColor(PALETTE["blue_deep"]))
                grad.setColorAt(1.0, QColor(PALETTE["purple"]))
                brush = QBrush(grad)
            painter.setBrush(brush)
            painter.drawRoundedRect(QRectF(0, 0, max(fill, h), h), h / 2, h / 2)
        painter.end()


class StatTile(Card):
    def __init__(self, title: str, sparkline: bool = False, bar: bool = False,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(title, parent)
        self.value = QLabel("--")
        self.value.setObjectName("bigvalue")
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        self.body.addWidget(self.value)
        self.body.addWidget(self.sub)
        self.spark: Optional[Sparkline] = Sparkline() if sparkline else None
        self.bar: Optional[UsageBar] = UsageBar() if bar else None
        if self.spark:
            self.body.addWidget(self.spark)
        if self.bar:
            self.body.addWidget(self.bar)

    def set_value(self, text: str) -> None:
        self.value.setText(text)

    def set_sub(self, text: str) -> None:
        self.sub.setText(text)

    def push(self, percent: float) -> None:
        if self.spark:
            self.spark.push(percent)

    def set_bar(self, percent: float) -> None:
        if self.bar:
            self.bar.set_value(percent)


# ----------------------------------------------------------- copyable boxes
class CommandBox(QWidget):
    """A read-only, monospaced single command with a Copy button."""

    def __init__(self, command: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.edit = QLineEdit(command)
        self.edit.setReadOnly(True)
        self.edit.setFont(mono_font())
        self.button = make_button("Copy")
        self.button.clicked.connect(self._copy)
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)

    def set_command(self, text: str) -> None:
        self.edit.setText(text)
        self.edit.setCursorPosition(0)

    def command(self) -> str:
        return self.edit.text()

    def _copy(self) -> None:
        copy_to_clipboard(self.edit.text())
        self.button.setText("Copied")
        QTimer.singleShot(1200, self._reset)

    def _reset(self) -> None:
        self.button.setText("Copy")


class SnippetBox(QWidget):
    """A read-only multi-line code block with a Copy button."""

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        self.edit = QPlainTextEdit(text)
        self.edit.setReadOnly(True)
        self.edit.setFont(mono_font())
        self.edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        lines = max(2, min(12, text.count("\n") + 1))
        self.edit.setFixedHeight(24 * lines + 18)
        self.button = make_button("Copy snippet")
        self.button.clicked.connect(self._copy)
        col.addWidget(self.edit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.button)
        col.addLayout(row)

    def _copy(self) -> None:
        copy_to_clipboard(self.edit.toPlainText())
        self.button.setText("Copied")
        QTimer.singleShot(1200, self._reset)

    def _reset(self) -> None:
        self.button.setText("Copy snippet")


# ------------------------------------------------------------------ dialogs
class ConfirmDialog(QDialog):
    """Preview + explicit confirmation. Cancel is the default; OK needs a tick box."""

    def __init__(self, parent: Optional[QWidget], title: str, heading: str, body_html: str,
                 command: str = "", confirm_text: str = "Continue",
                 checkbox_text: str = "I have read the above and want to continue",
                 danger: bool = False, preview_text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(680, 420)
        col = QVBoxLayout(self)
        col.setContentsMargins(22, 20, 22, 18)
        col.setSpacing(12)
        head = QLabel(heading)
        head.setObjectName("h2")
        head.setWordWrap(True)
        col.addWidget(head)
        body = QLabel(body_html)
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        col.addWidget(body)
        if preview_text:
            preview = QPlainTextEdit(preview_text)
            preview.setReadOnly(True)
            preview.setFont(mono_font())
            preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            preview.setMinimumHeight(120)
            col.addWidget(preview, 1)
        if command:
            label = QLabel("Command:")
            label.setObjectName("muted")
            col.addWidget(label)
            col.addWidget(CommandBox(command))
        self.check = QCheckBox(checkbox_text)
        col.addWidget(self.check)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = make_button("Cancel")
        self.cancel_btn.setDefault(True)
        self.ok_btn = make_button(confirm_text, "danger" if danger else "primary")
        self.ok_btn.setEnabled(False)
        self.check.toggled.connect(self.ok_btn.setEnabled)
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self.accept)
        row.addWidget(self.cancel_btn)
        row.addWidget(self.ok_btn)
        col.addLayout(row)

    @classmethod
    def ask(cls, parent: Optional[QWidget], *args, **kwargs) -> bool:
        return bool(cls(parent, *args, **kwargs).exec())


class ManualCommandDialog(QDialog):
    """Shown when a privileged action is unavailable: gives the command to run yourself."""

    def __init__(self, parent: Optional[QWidget], title: str, reason: str, command: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(620, 280)
        col = QVBoxLayout(self)
        col.setContentsMargins(22, 20, 22, 18)
        col.setSpacing(12)
        head = QLabel("Run this in a terminal instead")
        head.setObjectName("h2")
        col.addWidget(head)
        body = QLabel(
            f"<p>NIXTUNE cannot elevate privileges here:<br><i>{escape(reason)}</i></p>"
            "<p>You can run the equivalent command yourself. NIXTUNE has changed nothing.</p>")
        body.setTextFormat(Qt.TextFormat.RichText)
        body.setWordWrap(True)
        col.addWidget(body)
        col.addWidget(CommandBox(command))
        col.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        close = make_button("Close", "primary")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        col.addLayout(row)
