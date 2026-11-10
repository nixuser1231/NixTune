"""Smoke test of every GUI module using the stand-in Qt (see qt_stub.py).
Skipped when real PySide6 is installed - tests/gui_smoke.py covers that case."""
import importlib
import pkgutil

import pytest

try:
    import PySide6.QtWidgets  # noqa: F401
    pytest.skip("real PySide6 present", allow_module_level=True)
except ImportError:
    pass

import qt_stub


def test_all_gui_modules_import_and_main_window_builds():
    qt_stub.install()
    import nixtune.gui as g
    for m in pkgutil.walk_packages(g.__path__, "nixtune.gui."):
        importlib.import_module(m.name)
    from nixtune.gui.main_window import MainWindow, PAGES
    w = MainWindow()
    assert len(w.pages) == len(PAGES) == 9
