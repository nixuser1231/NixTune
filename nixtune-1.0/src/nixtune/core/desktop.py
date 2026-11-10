"""KDE Plasma / freedesktop application-menu integration.

Everything here is per-user (under XDG_DATA_HOME) and requires no privileges.
The UI previews the exact files and commands first and only writes after the
user confirms.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..constants import APP_ID, DESKTOP_FILE_NAME, ICON_NAME
from . import runner


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def desktop_file_path() -> Path:
    return data_home() / "applications" / DESKTOP_FILE_NAME


def icon_file_path() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg"


def packaged_icon() -> Optional[Path]:
    path = Path(__file__).resolve().parents[1] / "assets" / "nixtune.svg"
    return path if path.is_file() else None


def project_root() -> Path:
    # src/nixtune/core/desktop.py -> parents[3] is the repository root in a checkout
    return Path(__file__).resolve().parents[3]


# --------------------------------------------------------------- Exec quoting
_EXEC_SPECIAL = set(' \t\n"\'\\<>~|&;$*?#()`')


def quote_exec_arg(arg: str) -> str:
    """Quote one argument per the Desktop Entry specification."""
    arg = arg.replace("%", "%%")
    if not arg or any(ch in _EXEC_SPECIAL for ch in arg):
        for ch in ('\\', '"', '`', '$'):  # quoting-level escapes
            arg = arg.replace(ch, "\\" + ch)
        arg = '"' + arg + '"'
        arg = arg.replace("\\", "\\\\")  # string-level escape of backslashes
    return arg


def exec_line(argv: list[str]) -> str:
    return " ".join(quote_exec_arg(a) for a in argv)


@dataclass
class LauncherChoice:
    argv: list[str]
    description: str


def determine_launcher() -> LauncherChoice:
    """Pick the most robust way for the menu entry to start NIXTUNE."""
    on_path = shutil.which("nixtune")
    if on_path:
        return LauncherChoice(["nixtune"], f"`nixtune` command on PATH ({on_path})")
    script = project_root() / "nixtune-launch.sh"
    if script.is_file() and os.access(script, os.X_OK):
        return LauncherChoice([str(script)], f"one-click launcher script ({script})")
    src = project_root() / "src"
    return LauncherChoice(
        ["env", f"PYTHONPATH={src}", sys.executable, "-m", "nixtune"],
        "Python module (python -m nixtune)",
    )


def desktop_entry_text(argv: list[str]) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.5\n"
        "Name=NIXTUNE\n"
        "GenericName=NixOS Maintenance\n"
        "Comment=Monitor, clean, diagnose and tune your NixOS system\n"
        f"Exec={exec_line(argv)}\n"
        f"Icon={ICON_NAME}\n"
        "Terminal=false\n"
        "Categories=System;Monitor;Qt;\n"
        "Keywords=nixos;nix;garbage;generations;maintenance;optimize;diagnostics;\n"
        "StartupNotify=true\n"
        f"StartupWMClass={APP_ID}\n"
    )


@dataclass
class PlannedFile:
    path: Path
    description: str
    content: Optional[str] = None
    copy_from: Optional[Path] = None


@dataclass
class InstallPlan:
    launcher: LauncherChoice
    files: list[PlannedFile] = field(default_factory=list)
    commands: list[list[str]] = field(default_factory=list)

    @property
    def desktop_text(self) -> str:
        for f in self.files:
            if f.content is not None:
                return f.content
        return ""


def plan_install() -> InstallPlan:
    launcher = determine_launcher()
    plan = InstallPlan(launcher)
    plan.files.append(PlannedFile(
        desktop_file_path(), "Application-menu entry", content=desktop_entry_text(launcher.argv)))
    icon = packaged_icon()
    if icon:
        plan.files.append(PlannedFile(icon_file_path(), "Application icon (SVG)", copy_from=icon))
    # Cache refresh helpers, only if present.
    kbuild = runner.which("kbuildsycoca6") or runner.which("kbuildsycoca5")
    if kbuild:
        plan.commands.append([kbuild])
    update_db = runner.which("update-desktop-database")
    if update_db:
        plan.commands.append([update_db, str(desktop_file_path().parent)])
    return plan


def is_installed() -> bool:
    return desktop_file_path().is_file()


def install(plan: Optional[InstallPlan] = None) -> list[str]:
    """Write the planned files. Returns human-readable messages."""
    plan = plan or plan_install()
    msgs: list[str] = []
    for item in plan.files:
        item.path.parent.mkdir(parents=True, exist_ok=True)
        if item.content is not None:
            item.path.write_text(item.content, encoding="utf-8")
            os.chmod(item.path, 0o755)  # Plasma trusts executable launchers
        elif item.copy_from is not None:
            shutil.copyfile(item.copy_from, item.path)
            os.chmod(item.path, 0o644)
        msgs.append(f"Wrote {item.path}")
    validator = runner.which("desktop-file-validate")
    if validator:
        res = runner.run([validator, str(desktop_file_path())], timeout=15)
        msgs.append("desktop-file-validate: OK" if res.ok and not res.text
                    else f"desktop-file-validate: {res.text or res.error_summary()}")
    for cmd in plan.commands:
        res = runner.run(cmd, timeout=60)
        msgs.append(f"Ran {' '.join(cmd)}: " + ("ok" if res.ok else res.error_summary()))
    msgs.append("Done. It may take a few seconds for Plasma to show NIXTUNE in the application menu.")
    return msgs


def uninstall() -> list[str]:
    msgs: list[str] = []
    for path in (desktop_file_path(), icon_file_path()):
        if path.is_file():
            path.unlink()
            msgs.append(f"Removed {path}")
    kbuild = runner.which("kbuildsycoca6") or runner.which("kbuildsycoca5")
    if kbuild:
        runner.run([kbuild], timeout=60)
    if not msgs:
        msgs.append("Nothing to remove.")
    return msgs


_EXEC_VALID = re.compile(r"^Exec=.+$", re.M)


def validate_entry_text(text: str) -> bool:
    return text.startswith("[Desktop Entry]") and bool(_EXEC_VALID.search(text))
