"""Real-Qt smoke test. Run where PySide6 exists:
    QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
Builds the main window, visits every page, renders screenshots to ./shots/."""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from nixtune.gui import theme
from nixtune.gui.main_window import MainWindow, PAGES

app = QApplication([])
app.setStyle("Fusion")
theme.apply_palette(app)
app.setStyleSheet(theme.stylesheet())
w = MainWindow()
w.show()
os.makedirs("shots", exist_ok=True)
state = {"i": 0}


def step():
    i = state["i"]
    if i:
        w.grab().save(f"shots/{i - 1:02d}-{PAGES[i - 1][0].replace(' ', '_')}.png")
    if i >= len(PAGES):
        print("GUI smoke test OK:", len(PAGES), "pages")
        app.quit()
        return
    w.nav.setCurrentRow(i)
    state["i"] += 1
    QTimer.singleShot(2500, step)


QTimer.singleShot(500, step)
sys.exit(app.exec())
