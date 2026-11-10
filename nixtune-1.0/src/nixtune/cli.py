"""Command-line tools that work without Qt (dependency checker, diagnostics)."""

from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from .constants import APP_NAME, APP_VERSION


def check_deps_main(argv: Optional[Sequence[str]] = None) -> int:
    """Print a dependency report. Exit 0 if all required deps exist, else 1."""
    parser = argparse.ArgumentParser(
        prog="nixtune-check-deps",
        description=f"Check the dependencies {APP_NAME} needs and explain how to fix gaps on NixOS.")
    parser.add_argument("--explain", action="store_true", help="explain every missing dependency in detail")
    ns = parser.parse_args(list(argv) if argv is not None else None)

    from .core import deps  # imported lazily: nothing here needs Qt

    items = deps.check_all()
    print(f"{APP_NAME} {APP_VERSION} - dependency check\n")
    print(deps.render_table(items))
    missing = deps.missing(items)
    required_missing = deps.missing(items, required_only=True)
    if missing and ns.explain:
        print()
        for dep in missing:
            print(dep.explain())
            print("-" * 60)
    snippet = deps.nix_snippet(items)
    if snippet:
        print("\nSuggested NixOS configuration (review before use):\n")
        print(snippet)
    print()
    if required_missing:
        print(f"{len(required_missing)} required dependency(ies) missing. Run with --explain for details.")
        return 1
    print("All required dependencies are present." + (" Some optional ones are missing." if missing else ""))
    return 0


def diagnose_main(report_path: Optional[str] = None) -> int:
    from .core import diagnostics, reporting

    findings = diagnostics.run_all()
    text = diagnostics.render_text(findings)
    print(text)
    if report_path:
        reporting.save_report(report_path, {"Diagnostics": text})
        print(f"\nReport written to {report_path}")
    return 1 if diagnostics.counts(findings)["error"] else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(check_deps_main())
