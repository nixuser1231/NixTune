"""Small shared state so pages can reuse each other's results."""

from __future__ import annotations

from typing import Optional


class SharedState:
    dead_bytes: Optional[int] = None  # last Nix Cleaner analysis result


shared = SharedState()
