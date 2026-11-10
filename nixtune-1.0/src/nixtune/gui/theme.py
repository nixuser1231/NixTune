"""Dark blue/purple, Nix-inspired theme (original design, not the NixOS logo)."""

from __future__ import annotations

from string import Template

PALETTE = {
    "bg": "#0e1126",
    "sidebar": "#0b0e20",
    "surface": "#161a35",
    "surface_alt": "#1a1f3d",
    "surface2": "#1f2550",
    "border": "#2c3366",
    "text": "#e8ebff",
    "muted": "#8f98c8",
    "muted_dim": "#5b6397",
    "blue": "#7ebae4",
    "blue_deep": "#5277c3",
    "purple": "#a78bfa",
    "purple_deep": "#7c5cff",
    "ok": "#5ee6a8",
    "warn": "#ffc46b",
    "err": "#ff6b81",
    "err_bg": "#3a1530",
    "sel": "#2b3270",
}

SEVERITY_COLORS = {
    "error": PALETTE["err"],
    "warning": PALETTE["warn"],
    "info": PALETTE["blue"],
    "ok": PALETTE["ok"],
    "low": PALETTE["ok"],
    "review": PALETTE["warn"],
}

_QSS = Template("""
* { font-size: 13px; }
QWidget { color: $text; }
QMainWindow, QDialog, QMessageBox { background-color: $bg; }
QStackedWidget { background-color: $bg; }
QLabel, QCheckBox, QRadioButton { background: transparent; }
QToolTip { background: $surface2; color: $text; border: 1px solid $border; padding: 4px; }

QFrame#sidebar { background-color: $sidebar; border-right: 1px solid $border; }
QLabel#brand { font-size: 20px; font-weight: 800; letter-spacing: 3px; color: $blue; }
QLabel#brandsub { color: $muted; font-size: 11px; }
QListWidget#nav { background: transparent; border: none; outline: none; }
QListWidget#nav::item { padding: 11px 14px; margin: 2px 10px; border-radius: 10px; color: $muted; }
QListWidget#nav::item:hover { background: $surface2; color: $text; }
QListWidget#nav::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $blue_deep, stop:1 $purple_deep);
    color: white;
}

QFrame#card { background-color: $surface; border: 1px solid $border; border-radius: 14px; }
QLabel#h1 { font-size: 26px; font-weight: 800; color: $text; }
QLabel#h2 { font-size: 16px; font-weight: 700; color: $text; }
QLabel#subtitle { color: $muted; }
QLabel#cardtitle { color: $muted; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#bigvalue { font-size: 30px; font-weight: 800; color: $blue; }
QLabel#muted { color: $muted; }
QLabel#note { color: $muted; background: $surface_alt; border: 1px solid $border; border-radius: 10px; padding: 10px; }

QPushButton {
    background-color: $surface2; border: 1px solid $border; border-radius: 9px; padding: 8px 16px; color: $text;
}
QPushButton:hover { border-color: $blue; }
QPushButton:pressed { background-color: $sel; }
QPushButton:disabled { color: $muted_dim; background-color: $surface; border-color: $surface2; }
QPushButton[variant="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $blue_deep, stop:1 $purple_deep);
    border: none; color: white; font-weight: 700;
}
QPushButton[variant="primary"]:disabled { background: $surface2; color: $muted_dim; }
QPushButton[variant="danger"] { background-color: $err_bg; border: 1px solid $err; color: $err; font-weight: 700; }
QPushButton[variant="danger"]:disabled { background-color: $surface; border-color: $surface2; color: $muted_dim; }

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextBrowser, QTextEdit {
    background-color: $surface; border: 1px solid $border; border-radius: 8px; padding: 6px;
    selection-background-color: $purple_deep; selection-color: white;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $blue; }
QComboBox QAbstractItemView { background: $surface; selection-background-color: $sel; border: 1px solid $border; }
QComboBox::drop-down { border: none; width: 22px; }

QTableWidget {
    background-color: $surface; alternate-background-color: $surface_alt; gridline-color: transparent;
    border: 1px solid $border; border-radius: 10px; selection-background-color: $sel; selection-color: $text;
}
QTableWidget::item { padding: 4px 6px; }
QHeaderView::section { background-color: $surface2; color: $muted; border: none; padding: 8px; font-weight: 700; }
QTableCornerButton::section { background-color: $surface2; border: none; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $blue_deep; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 5px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QProgressBar { background: $surface2; border: none; border-radius: 4px; max-height: 8px; text-align: center; }
QProgressBar::chunk { background: $purple_deep; border-radius: 4px; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 4px; border: 1px solid $border; background: $surface; }
QCheckBox::indicator:checked { background: $purple_deep; border-color: $purple; }
QStatusBar { background: $sidebar; color: $muted; border-top: 1px solid $border; }
QSplitter::handle { background: $border; }
""")


def stylesheet() -> str:
    return _QSS.substitute(PALETTE)


def apply_palette(app) -> None:
    """Dark QPalette so any widget the stylesheet does not cover is still readable."""
    from PySide6.QtGui import QColor, QPalette

    p = QPalette()
    roles = {
        QPalette.ColorRole.Window: PALETTE["bg"],
        QPalette.ColorRole.WindowText: PALETTE["text"],
        QPalette.ColorRole.Base: PALETTE["surface"],
        QPalette.ColorRole.AlternateBase: PALETTE["surface_alt"],
        QPalette.ColorRole.Text: PALETTE["text"],
        QPalette.ColorRole.Button: PALETTE["surface2"],
        QPalette.ColorRole.ButtonText: PALETTE["text"],
        QPalette.ColorRole.Highlight: PALETTE["purple_deep"],
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.ToolTipBase: PALETTE["surface2"],
        QPalette.ColorRole.ToolTipText: PALETTE["text"],
        QPalette.ColorRole.PlaceholderText: PALETTE["muted_dim"],
        QPalette.ColorRole.Link: PALETTE["blue"],
    }
    for role, colour in roles.items():
        p.setColor(role, QColor(colour))
    app.setPalette(p)
