"""Curated references to the official NixOS documentation.

NIXTUNE never downloads or executes anything from the web. Documentation links
are opened in the user's own browser, and only https links to these official
hosts are accepted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from ..constants import DOCS_URL

ALLOWED_HOSTS = ("nixos.org", "search.nixos.org", "wiki.nixos.org", "nix.dev")
LOCAL_MANUAL_CANDIDATES = (
    "/run/current-system/sw/share/doc/nixos/index.html",
)


@dataclass(frozen=True)
class DocLink:
    title: str
    url: str
    description: str
    topic: str


DOC_LINKS: tuple[DocLink, ...] = (
    DocLink("NixOS Manual (stable)", DOCS_URL,
            "The official reference for installing, configuring and administering NixOS.", "manual"),
    DocLink("Installation", DOCS_URL + "#ch-installation",
            "Installing NixOS, partitioning and first boot.", "install"),
    DocLink("Configuration", DOCS_URL + "#ch-configuration",
            "Declarative configuration.nix: users, networking, desktop, services.", "config"),
    DocLink("Administration", DOCS_URL + "#ch-running",
            "Running NixOS day to day: rebuilds, service management, boot, maintenance.", "admin"),
    DocLink("Cleaning the Nix Store", DOCS_URL + "#sec-nix-gc",
            "Garbage collection, generations and automatic cleanup.", "gc"),
    DocLink("Upgrading NixOS", DOCS_URL + "#sec-upgrading",
            "Channels, release upgrades and nixos-rebuild.", "upgrade"),
    DocLink("Service Management", DOCS_URL + "#sec-systemctl",
            "Inspecting and controlling systemd services on NixOS.", "services"),
    DocLink("Troubleshooting", DOCS_URL + "#ch-troubleshooting",
            "Boot problems, rollback, rebuilding when things go wrong.", "troubleshooting"),
    DocLink("Configuration Options", DOCS_URL + "options",
            "Every NixOS option with type, default and description.", "options"),
    DocLink("Package & option search", "https://search.nixos.org/options",
            "Search NixOS options (and packages at search.nixos.org/packages).", "search"),
    DocLink("Nixpkgs Manual", "https://nixos.org/manual/nixpkgs/stable/",
            "Packaging, overlays, language ecosystems and the standard environment.", "nixpkgs"),
    DocLink("Nix Reference Manual", "https://nix.dev/manual/nix/latest/",
            "The Nix language, nix-store, nix-collect-garbage and nix commands.", "nix"),
)

OFFLINE_COMMANDS: tuple[tuple[str, str], ...] = (
    ("nixos-help", "Open the manual that ships with your system in a browser."),
    ("man configuration.nix", "Read the options reference in a terminal."),
    ("sudo nixos-rebuild test", "Build and activate the configuration without making it the boot default."),
    ("sudo nixos-rebuild switch", "Build, activate and make the configuration the boot default."),
    ("sudo nixos-rebuild switch --rollback", "Switch back to the previous system generation."),
    ("nix-collect-garbage", "Delete unreachable store paths (keeps all generations)."),
)

TOPIC_FOR_CHECK = {
    "gc": DOCS_URL + "#sec-nix-gc",
    "services": DOCS_URL + "#sec-systemctl",
    "config": DOCS_URL + "#ch-configuration",
    "admin": DOCS_URL + "#ch-running",
    "options": DOCS_URL + "options",
    "troubleshooting": DOCS_URL + "#ch-troubleshooting",
    "upgrade": DOCS_URL + "#sec-upgrading",
}


def is_allowed_doc_url(url: str) -> bool:
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS)


def local_manual() -> Optional[str]:
    for cand in LOCAL_MANUAL_CANDIDATES:
        if os.path.isfile(cand):
            return cand
    return None
