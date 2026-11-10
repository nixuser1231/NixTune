"""Safe, explainable optimisation recommendations.

NIXTUNE never edits configuration. Every recommendation carries:
  * the evidence that triggered it,
  * what it changes and what risk it carries,
  * how to revert it,
  * a Nix snippet the user may copy into their own configuration.nix.
`recommend()` is a pure function of a `Facts` object so it is easy to test.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from typing import Optional

from . import docs, generations, nixenv, runner, sysinfo

GIB = 1024 ** 3
APPLY_HOWTO = (
    "1. Copy the snippet into your configuration.nix (or the matching module of your flake).\n"
    "2. Try it without making it permanent: `sudo nixos-rebuild test`.\n"
    "3. If everything works, make it the boot default: `sudo nixos-rebuild switch`.\n"
    "Undo any time by removing the snippet and rebuilding, or `sudo nixos-rebuild switch --rollback`."
)


@dataclass
class Facts:
    is_nixos: bool = True
    flakes_enabled: Optional[bool] = None
    auto_optimise_store: Optional[bool] = None
    gc_timer_enabled: Optional[bool] = None
    system_generations: int = 0
    boot_used_percent: Optional[float] = None
    root_used_percent: Optional[float] = None
    store_used_percent: Optional[float] = None
    mem_total: int = 0
    swap_total: int = 0
    has_zram: bool = False
    has_ssd: bool = False
    fstrim_enabled: Optional[bool] = None
    journal_bytes: Optional[int] = None
    failed_units: list[str] = field(default_factory=list)
    reboot_needed: bool = False
    dead_bytes: Optional[int] = None  # from the Nix Cleaner analysis, if available


@dataclass
class Recommendation:
    id: str
    title: str
    risk: str               # "info" | "low" | "review"
    summary: str
    evidence: str
    effect: str
    revert: str
    snippet: str = ""
    doc_url: str = ""

    @property
    def how_to_apply(self) -> str:
        return APPLY_HOWTO if self.snippet else ""


# ----------------------------------------------------------------- gathering
def _parse_journal_bytes(text: str) -> Optional[int]:
    m = re.search(r"take up\s+([\d.]+)\s*([KMGT]?)(?:i?B)?", text)
    if not m:
        return None
    mult = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[m.group(2)]
    return int(float(m.group(1)) * mult)


def _systemd_enabled(unit: str) -> Optional[bool]:
    res = runner.run(["systemctl", "is-enabled", unit], timeout=10)
    if res.missing:
        return None
    out = res.stdout.strip()
    if out in ("enabled", "static", "alias", "enabled-runtime"):
        return True
    if out in ("disabled", "masked", "not-found") or "not-found" in res.stderr:
        return False
    return None


def _detect_ssd() -> bool:
    for path in glob.glob("/sys/block/*/queue/rotational"):
        dev = path.split("/")[3]
        if dev.startswith(("loop", "zram", "ram", "dm-", "sr", "fd", "md")):
            continue
        try:
            with open(path, "r") as fh:
                if fh.read().strip() == "0":
                    return True
        except OSError:
            continue
    return False


def gather(dead_bytes: Optional[int] = None) -> Facts:
    cfg = nixenv.nix_config()
    mem = sysinfo.memory()
    facts = Facts(is_nixos=nixenv.is_nixos(), dead_bytes=dead_bytes)
    facts.flakes_enabled = nixenv.flakes_enabled(cfg) if cfg else None
    facts.auto_optimise_store = nixenv.truthy(cfg.get("auto-optimise-store")) if cfg else None
    facts.gc_timer_enabled = _systemd_enabled("nix-gc.timer")
    facts.system_generations = len(generations.list_generations(
        generations.ProfileRef("NixOS system", generations.SYSTEM_PROFILE_DIR, "system", True)))
    for attr, path in (("root_used_percent", "/"), ("store_used_percent", "/nix")):
        du = sysinfo.disk_usage(path)
        setattr(facts, attr, du.percent if du else None)
    if os.path.ismount("/boot"):
        du = sysinfo.disk_usage("/boot")
        facts.boot_used_percent = du.percent if du else None
    facts.mem_total, facts.swap_total = mem.total, mem.swap_total
    try:
        with open("/proc/swaps", "r") as fh:
            facts.has_zram = "zram" in fh.read()
    except OSError:
        pass
    facts.has_ssd = _detect_ssd()
    facts.fstrim_enabled = _systemd_enabled("fstrim.timer")
    jr = runner.run(["journalctl", "--disk-usage"], timeout=10)
    if jr.ok:
        facts.journal_bytes = _parse_journal_bytes(jr.stdout)
    failed = runner.run(["systemctl", "--failed", "--no-pager", "--plain", "--no-legend"], timeout=15)
    if failed.ok:
        facts.failed_units = [ln.split()[0] for ln in failed.stdout.splitlines() if ln.strip()]
    if os.path.exists("/run/booted-system") and os.path.exists("/run/current-system"):
        facts.reboot_needed = any(
            os.path.realpath(f"/run/booted-system/{p}") != os.path.realpath(f"/run/current-system/{p}")
            for p in ("kernel", "initrd", "kernel-modules"))
    return facts


# ------------------------------------------------------------------- rules
def recommend(f: Facts) -> list[Recommendation]:
    recs: list[Recommendation] = []
    if not f.is_nixos:
        return [Recommendation(
            "not-nixos", "Recommendations apply to NixOS", "info",
            "NIXTUNE's tuning advice is expressed as NixOS configuration options, so none is offered here.",
            "This system does not identify as NixOS.", "Nothing changes.", "Nothing to revert.")]

    if f.dead_bytes is not None and f.dead_bytes >= 5 * GIB:
        recs.append(Recommendation(
            "run-gc", "Reclaim unused store space now", "info",
            "A large amount of the Nix store is not referenced by anything.",
            f"The Nix Cleaner preview found about {sysinfo.format_bytes(f.dead_bytes)} of unreachable paths.",
            "Garbage collection deletes only unreachable store paths. Generations and configuration are untouched.",
            "Deleted paths are re-downloaded or rebuilt if ever needed again.",
            doc_url=docs.TOPIC_FOR_CHECK["gc"]))

    if f.gc_timer_enabled is False:
        recs.append(Recommendation(
            "auto-gc", "Collect garbage automatically every week", "review",
            "Keeps the store from growing without bound, without you remembering to clean it.",
            "The nix-gc.timer unit is not enabled.",
            "Runs `nix-collect-garbage` weekly. In this form it removes only unreachable paths; it keeps all generations.",
            "Remove the snippet and rebuild. Already-deleted store paths are not restored.",
            "nix.gc = {\n  automatic = true;\n  dates = \"weekly\";\n"
            "  # Optional and NOT recommended until you are comfortable: also deletes old generations,\n"
            "  # which removes rollback targets.\n"
            "  # options = \"--delete-older-than 30d\";\n};",
            docs.TOPIC_FOR_CHECK["gc"]))

    if f.auto_optimise_store is False:
        recs.append(Recommendation(
            "auto-optimise", "Deduplicate store files automatically", "low",
            "Hard-links identical files in the Nix store, commonly saving several percent to tens of percent of space.",
            "nix.settings.auto-optimise-store is currently off.",
            "Each newly built path is deduplicated as it is added. Costs a little extra time per build.",
            "Set it back to false; existing hard links remain harmless.",
            "nix.settings.auto-optimise-store = true;",
            docs.TOPIC_FOR_CHECK["gc"]))

    boot_full = f.boot_used_percent is not None and f.boot_used_percent >= 80
    if f.system_generations > 20 or boot_full:
        why = []
        if f.system_generations > 20:
            why.append(f"{f.system_generations} system generations are kept")
        if boot_full:
            why.append(f"/boot is {f.boot_used_percent:.0f}% full")
        recs.append(Recommendation(
            "boot-limit", "Limit the number of boot menu entries", "review",
            "Each generation adds a kernel and initrd to /boot. A full /boot makes rebuilds fail.",
            "; ".join(why) + ".",
            "Only the newest N generations appear in the boot menu and keep files in /boot. "
            "Older generations stay in the store until you garbage-collect them yourself.",
            "Remove the line and rebuild to list every generation again.",
            "# systemd-boot:\nboot.loader.systemd-boot.configurationLimit = 20;\n"
            "# GRUB instead:\n# boot.loader.grub.configurationLimit = 20;",
            docs.TOPIC_FOR_CHECK["config"]))

    if f.swap_total == 0 and 0 < f.mem_total <= 8 * GIB and not f.has_zram:
        recs.append(Recommendation(
            "zram", "Enable compressed RAM swap (zram)", "low",
            "Gives low-memory machines a safety net against out-of-memory kills, with no disk wear.",
            f"{sysinfo.format_bytes(f.mem_total)} RAM and no swap configured.",
            "Creates a compressed swap device in RAM. Uses little memory until pressure appears.",
            "Remove the line and rebuild.",
            "zramSwap.enable = true;",
            docs.TOPIC_FOR_CHECK["options"]))

    if f.has_ssd and f.fstrim_enabled is False:
        recs.append(Recommendation(
            "fstrim", "Trim SSD free space weekly", "low",
            "Periodic TRIM helps SSDs keep their write performance and lifespan.",
            "An SSD/NVMe device was detected and fstrim.timer is not enabled.",
            "Runs `fstrim` weekly on mounted filesystems that support it.",
            "Remove the line and rebuild.",
            "services.fstrim.enable = true;",
            docs.TOPIC_FOR_CHECK["options"]))

    if f.journal_bytes is not None and f.journal_bytes > GIB:
        recs.append(Recommendation(
            "journal-cap", "Cap the size of the system journal", "low",
            "A large journal wastes disk space and slows log searches.",
            f"The journal currently uses {sysinfo.format_bytes(f.journal_bytes)}.",
            "journald discards the oldest log entries beyond the limit.",
            "Remove the line and rebuild. Discarded logs cannot be recovered.",
            "services.journald.extraConfig = ''\n  SystemMaxUse=500M\n'';\n"
            "# Option names can change between releases: check search.nixos.org/options.",
            docs.TOPIC_FOR_CHECK["options"]))

    worst = max([p for p in (f.root_used_percent, f.store_used_percent) if p is not None], default=None)
    if worst is not None and worst >= 85:
        recs.append(Recommendation(
            "min-free", "Let Nix free space itself when the disk runs low", "review",
            "Prevents builds from failing half way because the disk filled up.",
            f"A filesystem holding the Nix store is {worst:.0f}% full.",
            "When free space drops below min-free during a build, Nix garbage-collects until max-free is available. "
            "That can delete unreferenced paths in the middle of your work.",
            "Remove the settings and rebuild.",
            "nix.settings = {\n  min-free = 1073741824;   # 1 GiB\n  max-free = 5368709120;   # 5 GiB\n};",
            docs.TOPIC_FOR_CHECK["gc"]))

    if f.failed_units:
        shown = ", ".join(f.failed_units[:5]) + ("..." if len(f.failed_units) > 5 else "")
        recs.append(Recommendation(
            "failed-units", "Investigate failed services", "info",
            "Failed services waste resources and may hide real problems.",
            f"{len(f.failed_units)} failed unit(s): {shown}.",
            "Nothing is changed. Read the logs first: `journalctl -u <unit> -b`.",
            "Nothing to revert.",
            doc_url=docs.TOPIC_FOR_CHECK["services"]))

    if f.reboot_needed:
        recs.append(Recommendation(
            "reboot", "Reboot to use the updated kernel", "info",
            "The running kernel/initrd differs from the one in your current system generation.",
            "/run/booted-system differs from /run/current-system.",
            "Nothing is changed until you reboot.", "Nothing to revert.",
            doc_url=docs.TOPIC_FOR_CHECK["admin"]))

    if f.flakes_enabled is False:
        recs.append(Recommendation(
            "flakes", "Enable the modern nix command and flakes (optional)", "info",
            "Needed for `nix run`, `nix shell`, `nix develop` and flake-based system configurations.",
            "The experimental features nix-command / flakes are not enabled.",
            "Enables features that are widely used though still labelled experimental.",
            "Remove the line and rebuild.",
            'nix.settings.experimental-features = [ "nix-command" "flakes" ];',
            docs.TOPIC_FOR_CHECK["config"]))

    if not recs:
        recs.append(Recommendation(
            "all-good", "No optimisation recommendations right now", "info",
            "Nothing worth changing was detected.", "All checks were within normal ranges.",
            "Nothing changes.", "Nothing to revert."))
    return recs
