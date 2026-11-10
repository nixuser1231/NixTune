"""Application entry point.

PySide6 is imported lazily so `--version`, `--check-deps` and `--diagnose`
work even when Qt is missing (which is exactly when you need them).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

from .constants import APP_ID, APP_NAME, APP_VERSION

EXIT_OK = 0
EXIT_ROOT = 2
EXIT_NO_QT = 3
EXIT_NO_DISPLAY = 4

PYSIDE_HELP = (
    "PySide6 (Qt for Python) is not installed in this Python environment.\n"
    "On NixOS:\n"
    "  * Quick start:   nix-shell shell.nix --run 'python -m nixtune'\n"
    "  * With flakes:   nix run .\n"
    "  * Permanently:   add this flake's package (or python3Packages.pyside6) to your configuration.\n"
    "Run `nixtune --check-deps --explain` for a full dependency report."
)


def refuse_root() -> bool:
    """The GUI must never run as root. Returns True if it should abort."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nixtune", description=f"{APP_NAME} - maintenance and tuning for NixOS",
        epilog="Unrecognised options are passed to Qt (for example -platform xcb).")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    p.add_argument("--check-deps", action="store_true", help="check dependencies and exit")
    p.add_argument("--explain", action="store_true", help="with --check-deps: explain every gap")
    p.add_argument("--diagnose", action="store_true", help="run diagnostics in the terminal and exit")
    p.add_argument("--report", metavar="FILE", help="with --diagnose: also write a redacted report file")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    ns, qt_args = build_parser().parse_known_args(list(sys.argv[1:] if argv is None else argv))

    if refuse_root():
        sys.stderr.write(
            f"{APP_NAME} refuses to run as root. Start it as your normal user; it asks for admin "
            "rights only for individual actions, through polkit.\n")
        return EXIT_ROOT

    if ns.check_deps:
        from .cli import check_deps_main
        return check_deps_main(["--explain"] if ns.explain else [])
    if ns.diagnose:
        from .cli import diagnose_main
        return diagnose_main(ns.report)

    return launch_gui(qt_args)


def launch_gui(qt_args: Sequence[str]) -> int:
    from .core import reporting

    reporting.setup_logging()
    try:
        from PySide6.QtCore import Qt  # noqa: F401
        from PySide6.QtGui import QGuiApplication, QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        sys.stderr.write(f"{APP_NAME}: cannot start the GUI ({exc}).\n\n{PYSIDE_HELP}\n")
        return EXIT_NO_QT

    from .core import desktop
    from .gui import theme
    from .gui.main_window import MainWindow, install_error_dialog

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("nixtune")
    QGuiApplication.setDesktopFileName(APP_ID)  # Plasma/Wayland: match nixtune.desktop for icon + grouping
    app.setStyle("Fusion")
    theme.apply_palette(app)
    app.setStyleSheet(theme.stylesheet())
    icon = desktop.packaged_icon()
    if icon:
        app.setWindowIcon(QIcon(str(icon)))

    window = MainWindow()
    install_error_dialog(window)
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
