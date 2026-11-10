"""Dependency detection and explanation (Qt-free).

For every external tool or Python module NIXTUNE can use, this module reports
whether it is present, why NIXTUNE wants it, and how to obtain it *the NixOS
way* (declaratively, or ad hoc with nix-shell / nix shell). It never installs
anything itself.
"""

from __future__ import annotations

import glob
import importlib.util
import os
import sys
from dataclasses import dataclass
from typing import Optional

from . import runner


@dataclass
class Dependency:
    name: str
    kind: str                 # "command" | "python" | "plugin" | "file"
    required: bool
    purpose: str
    nixpkg: str               # attribute in nixpkgs, e.g. "kdePackages.kservice"
    found: bool = False
    location: str = ""
    note: str = ""            # extra NixOS-specific guidance

    @property
    def status(self) -> str:
        if self.found:
            return "found"
        return "MISSING (required)" if self.required else "missing (optional)"

    def explain(self) -> str:
        lines = [f"{self.name} - {'required' if self.required else 'optional'}",
                 "", f"Why NIXTUNE uses it: {self.purpose}", ""]
        if self.found:
            lines.append(f"Status: found at {self.location}")
            if self.note:
                lines += ["", self.note]
            return "\n".join(lines)
        impact = ("NIXTUNE cannot work correctly without it."
                  if self.required else "The related feature is disabled or degraded; everything else works.")
        lines += [f"Status: NOT found. {impact}", "", "How to get it on NixOS:"]
        lines += [
            f"  - Permanently: add `pkgs.{self.nixpkg}` to environment.systemPackages in your configuration.nix, then run",
            "    `sudo nixos-rebuild switch`.",
            f"  - Try it first without installing: `nix-shell -p {self.nixpkg}`",
            f"    (with flakes enabled: `nix shell nixpkgs#{self.nixpkg}`).",
        ]
        if self.note:
            lines += ["", self.note]
        lines += ["", "NIXTUNE does not install packages or edit your configuration for you."]
        return "\n".join(lines)


def _command(name: str, required: bool, purpose: str, nixpkg: str, note: str = "") -> Dependency:
    dep = Dependency(name, "command", required, purpose, nixpkg, note=note)
    path = runner.pkexec_path() if name == "pkexec" else runner.which(name)
    if path:
        dep.found, dep.location = True, path
    return dep


def _python(module: str, required: bool, purpose: str, nixpkg: str, note: str = "") -> Dependency:
    dep = Dependency(module, "python", required, purpose, nixpkg, note=note)
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ValueError):
        spec = None
    if spec is not None:
        dep.found = True
        dep.location = spec.origin or "built-in"
        dep.note = dep.note or ""
    return dep


def _qt_wayland_plugin() -> Dependency:
    dep = Dependency(
        "qtwayland (Qt Wayland platform plugin)", "plugin", False,
        "Lets the GUI run natively on a Wayland session (the KDE Plasma 6 default).",
        "qt6.qtwayland",
        note=("The packaged NIXTUNE already wraps this in. In a dev shell it is provided by shell.nix; "
              "without it Qt falls back to XWayland if available."),
    )
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    dirs = [d for d in os.environ.get("QT_PLUGIN_PATH", "").split(os.pathsep) if d]
    spec = None
    try:
        spec = importlib.util.find_spec("PySide6")
    except (ImportError, ValueError):
        pass
    if spec and spec.submodule_search_locations:
        dirs += [os.path.join(p, "Qt", "plugins") for p in spec.submodule_search_locations]
    hits: list[str] = []
    for d in dirs:
        hits += glob.glob(os.path.join(d, "platforms", "libqwayland*"))
    if hits:
        dep.found, dep.location = True, os.path.dirname(hits[0])
    elif session != "wayland":
        dep.found = True  # not needed in an X11 / unknown session
        dep.location = f"not needed (session: {session or 'unknown'})"
    return dep


def _polkit_policy() -> Dependency:
    dep = Dependency(
        "NIXTUNE polkit policy", "file", False,
        "Gives the admin-authentication prompt a clear, specific description for NIXTUNE's helper.",
        "nixtune",
        note=("Installed automatically by the NixOS module (`programs.nixtune.enable = true;`) or by adding the "
              "package to environment.systemPackages together with `environment.pathsToLink = [ \"/share/polkit-1\" ];`. "
              "Without it, pkexec still works but shows a generic prompt."),
    )
    for base in ("/run/current-system/sw/share/polkit-1/actions", "/usr/share/polkit-1/actions"):
        cand = os.path.join(base, "org.nixtune.helper.policy")
        if os.path.isfile(cand):
            dep.found, dep.location = True, cand
            break
    return dep


def check_all() -> list[Dependency]:
    deps: list[Dependency] = []
    deps.append(Dependency(
        "Python 3.10+", "python", True, "Runtime for NIXTUNE itself.", "python3",
        found=sys.version_info >= (3, 10), location=sys.executable,
    ))
    deps.append(_python("PySide6", True, "Qt 6 bindings for the graphical interface.", "python3Packages.pyside6"))
    deps.append(_command("nix", True, "Reads Nix configuration and version information.", "nix"))
    deps.append(_command("nix-store", True,
                         "Garbage-collection preview (--gc --print-dead) and store-size queries.", "nix"))
    deps.append(_command("systemctl", True, "Lists systemd services and their status.", "systemd"))
    deps.append(_command("journalctl", False, "Diagnostics: recent boot errors and journal size.", "systemd"))
    deps.append(_command(
        "pkexec", False,
        "Asks for admin authentication for the two privileged actions (collect garbage, optimise store).",
        "polkit",
        note=("On NixOS the working pkexec is the setuid wrapper in /run/wrappers/bin, created when you set "
              "`security.polkit.enable = true;` (already enabled by default on KDE Plasma). "
              "Without it NIXTUNE shows the equivalent `sudo` command for you to run in a terminal."),
    ))
    deps.append(_command("nixos-version", False, "Shows the exact NixOS release.", "nixos-version",
                         note="Part of every NixOS installation."))
    deps.append(_command("nixos-rebuild", False,
                         "Not called by NIXTUNE; recommendations tell you to use it to test and apply changes.",
                         "nixos-rebuild", note="Part of every NixOS installation."))
    deps.append(_command("xdg-open", False, "Fallback for opening documentation links in your browser.", "xdg-utils"))
    deps.append(_command("kbuildsycoca6", False,
                         "Refreshes the KDE Plasma application-menu cache after installing the launcher.",
                         "kdePackages.kservice"))
    deps.append(_command("desktop-file-validate", False,
                         "Validates the generated .desktop launcher.", "desktop-file-utils"))
    deps.append(_command("update-desktop-database", False,
                         "Refreshes the desktop MIME/application database after installing the launcher.",
                         "desktop-file-utils"))
    deps.append(_qt_wayland_plugin())
    deps.append(_polkit_policy())
    return deps


def missing(deps: Optional[list[Dependency]] = None, required_only: bool = False) -> list[Dependency]:
    deps = check_all() if deps is None else deps
    return [d for d in deps if not d.found and (d.required or not required_only)]


def nix_snippet(deps: list[Dependency]) -> str:
    pkgs = sorted({d.nixpkg for d in deps if not d.found and d.kind in ("command", "python")
                   and d.nixpkg not in ("nix", "systemd", "python3", "nixos-version", "nixos-rebuild")})
    if not pkgs:
        return ""
    body = "\n".join(f"    {p}" for p in pkgs)
    return f"environment.systemPackages = with pkgs; [\n{body}\n];"


def render_table(deps: Optional[list[Dependency]] = None) -> str:
    deps = check_all() if deps is None else deps
    width = max(len(d.name) for d in deps)
    rows = []
    for d in deps:
        mark = "OK " if d.found else ("!! " if d.required else "-- ")
        rows.append(f"{mark} {d.name.ljust(width)}  {d.status:<20} {d.location}")
    return "\n".join(rows)
