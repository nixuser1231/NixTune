"""System diagnostics: detect common NixOS problems. Strictly read-only."""

from __future__ import annotations

import logging
import os
import re
import traceback
from dataclasses import dataclass
from typing import Callable, Optional

from . import deps as depmod
from . import docs, generations, nixenv, privileged, runner, sysinfo

log = logging.getLogger("nixtune.diagnostics")

SEVERITIES = ("error", "warning", "info", "ok")
_ORDER = {s: i for i, s in enumerate(SEVERITIES)}


@dataclass
class Finding:
    id: str
    category: str
    title: str
    severity: str          # error | warning | info | ok
    detail: str = ""
    remedy: str = ""
    doc_url: str = ""


def counts(findings: list[Finding]) -> dict[str, int]:
    out = {s: 0 for s in SEVERITIES}
    for f in findings:
        out[f.severity] = out.get(f.severity, 0) + 1
    return out


# ------------------------------------------------------------------- checks
def check_nixos() -> list[Finding]:
    if nixenv.is_nixos():
        ver = nixenv.nixos_version() or "unknown version"
        return [Finding("nixos", "System", "Running NixOS", "ok", f"Detected NixOS ({ver}).")]
    return [Finding("nixos", "System", "This is not NixOS", "info",
                    f"Detected: {nixenv.pretty_os_name()}. NIXTUNE targets NixOS; Nix-store tools still "
                    "work if Nix is installed, but system-generation and NixOS-config checks are skipped.")]


def check_nix_cli() -> list[Finding]:
    ver = nixenv.nix_version()
    if ver:
        return [Finding("nix-cli", "Nix", "Nix command-line tools available", "ok", ver)]
    return [Finding("nix-cli", "Nix", "The `nix` command was not found", "error",
                    "NIXTUNE could not run `nix --version`.",
                    "Make sure Nix is installed and on PATH. On NixOS it is always part of the system; if you started "
                    "NIXTUNE from an unusual environment, launch it from the application menu or a normal shell.")]


def check_store_access() -> list[Finding]:
    for argv in (["nix", "--extra-experimental-features", "nix-command", "store", "info"],
                 ["nix", "--extra-experimental-features", "nix-command", "store", "ping"]):
        res = runner.run(argv, timeout=20)
        if res.missing:
            return []
        if res.ok:
            return [Finding("store-access", "Nix", "Nix store is reachable", "ok",
                            res.text.splitlines()[0] if res.text else "")]
    return [Finding("store-access", "Nix", "Could not reach the Nix store/daemon", "warning",
                    res.error_summary(),
                    "Check the daemon: `systemctl status nix-daemon`. Make sure your user can talk to it "
                    "(`nix.settings.allowed-users`).", docs.TOPIC_FOR_CHECK["services"])]


def check_flakes() -> list[Finding]:
    cfg = nixenv.nix_config()
    if not cfg:
        return [Finding("flakes", "Nix", "Could not read the Nix configuration", "info",
                        "`nix config show` failed, so flake/feature checks were skipped.")]
    enabled = nixenv.flakes_enabled(cfg)
    uses_flake = os.path.exists("/etc/nixos/flake.nix")
    if enabled:
        return [Finding("flakes", "Nix", "nix-command and flakes are enabled", "ok",
                        cfg.get("experimental-features", ""))]
    if uses_flake:
        return [Finding("flakes", "Nix", "Your system uses a flake but flakes are not enabled", "error",
                        "/etc/nixos/flake.nix exists, yet the experimental features nix-command/flakes are off.",
                        'Add to configuration.nix:\n  nix.settings.experimental-features = [ "nix-command" "flakes" ];\n'
                        "then `sudo nixos-rebuild switch`.", docs.TOPIC_FOR_CHECK["config"])]
    return [Finding("flakes", "Nix", "Flakes are not enabled", "info",
                    "Not a problem for classic configuration.nix setups. Needed only for `nix run`, "
                    "`nix shell`, or flake-based configs.",
                    'Optional: nix.settings.experimental-features = [ "nix-command" "flakes" ];')]


def check_config_files() -> list[Finding]:
    if not nixenv.is_nixos():
        return []
    base = "/etc/nixos"
    cfg, flake, hw = (os.path.join(base, n) for n in ("configuration.nix", "flake.nix", "hardware-configuration.nix"))
    out: list[Finding] = []
    if not (os.path.exists(cfg) or os.path.exists(flake)):
        return [Finding("config-present", "Configuration", "No configuration found in /etc/nixos", "warning",
                        "Neither configuration.nix nor flake.nix exists there.",
                        "If your configuration lives elsewhere (e.g. a git repository referenced by "
                        "`nixos-rebuild --flake`), this is fine.", docs.TOPIC_FOR_CHECK["config"])]
    out.append(Finding("config-present", "Configuration", "System configuration found", "ok",
                       flake if os.path.exists(flake) else cfg))
    if not os.path.exists(hw):
        out.append(Finding("hardware-config", "Configuration", "hardware-configuration.nix is missing", "warning",
                           "NixOS normally keeps filesystem/boot hardware settings in this file.",
                           "Generate it with `sudo nixos-generate-config` (review before replacing anything).",
                           docs.TOPIC_FOR_CHECK["config"]))
    # stateVersion: search the top-level .nix files (read-only, size-capped)
    found = False
    try:
        for name in sorted(os.listdir(base))[:40]:
            if not name.endswith(".nix"):
                continue
            try:
                with open(os.path.join(base, name), "r", encoding="utf-8", errors="replace") as fh:
                    if re.search(r"system\.stateVersion\s*=", fh.read(400_000)):
                        found = True
                        break
            except OSError:
                continue
    except OSError:
        pass
    if found:
        out.append(Finding("state-version", "Configuration", "system.stateVersion is set", "ok"))
    else:
        out.append(Finding("state-version", "Configuration", "system.stateVersion was not found in /etc/nixos/*.nix",
                           "info", "It may live in another file or be unreadable. NixOS requires it to be set.",
                           "Set it to the release you first installed, e.g. `system.stateVersion = \"25.05\";`. "
                           "Never change it just to 'upgrade'.", docs.TOPIC_FOR_CHECK["config"]))
    return out


def _disk_finding(fid: str, label: str, path: str, warn: float, crit: float, remedy: str) -> list[Finding]:
    du = sysinfo.disk_usage(path)
    if du is None or du.total == 0:
        return []
    detail = (f"{sysinfo.format_bytes(du.used)} used of {sysinfo.format_bytes(du.total)} "
              f"({du.percent:.0f}%), {sysinfo.format_bytes(du.free)} free")
    if du.percent >= crit:
        return [Finding(fid, "Storage", f"{label} is almost full", "error", detail, remedy, docs.TOPIC_FOR_CHECK["gc"])]
    if du.percent >= warn:
        return [Finding(fid, "Storage", f"{label} is getting full", "warning", detail, remedy, docs.TOPIC_FOR_CHECK["gc"])]
    return [Finding(fid, "Storage", f"{label} has enough free space", "ok", detail)]


def check_disks() -> list[Finding]:
    out: list[Finding] = []
    store_remedy = "Use the Nix Cleaner page to preview and run garbage collection, then review old generations."
    out += _disk_finding("disk-root", "Root filesystem (/)", "/", 85, 95, store_remedy)
    try:
        same = os.stat("/nix").st_dev != os.stat("/").st_dev
    except OSError:
        same = False
    if same:
        out += _disk_finding("disk-nix", "Nix store filesystem (/nix)", "/nix", 85, 95, store_remedy)
    if os.path.ismount("/boot"):
        out += _disk_finding("disk-boot", "Boot partition (/boot)", "/boot", 80, 92,
                             "Each generation stores a kernel+initrd in /boot. Limit them with "
                             "`boot.loader.systemd-boot.configurationLimit` (see the Optimizer page).")
    return out


def check_failed_units() -> list[Finding]:
    res = runner.run(["systemctl", "--failed", "--no-pager", "--plain", "--no-legend"], timeout=20)
    if res.missing:
        return []
    names = [ln.split()[0] for ln in res.stdout.splitlines() if ln.strip()]
    if not res.ok and not names:
        return [Finding("failed-units", "Services", "Could not query systemd", "info", res.error_summary())]
    if names:
        return [Finding("failed-units", "Services", f"{len(names)} failed systemd unit(s)", "warning",
                        "\n".join(names[:20]),
                        "Inspect one with `systemctl status <unit>` and `journalctl -u <unit> -b`. "
                        "Use the Services page for details.", docs.TOPIC_FOR_CHECK["services"])]
    return [Finding("failed-units", "Services", "No failed systemd units", "ok")]


def check_reboot_needed() -> list[Finding]:
    if not (os.path.exists("/run/booted-system") and os.path.exists("/run/current-system")):
        return []
    diffs = []
    for part in ("kernel", "initrd", "kernel-modules"):
        a = os.path.realpath(os.path.join("/run/booted-system", part))
        b = os.path.realpath(os.path.join("/run/current-system", part))
        if a != b:
            diffs.append(part)
    if diffs:
        return [Finding("reboot", "System", "A reboot is needed to use the newest kernel/initrd", "info",
                        "Changed since boot: " + ", ".join(diffs) + ".",
                        "Reboot when convenient. Until then you run the older kernel.", docs.TOPIC_FOR_CHECK["admin"])]
    return [Finding("reboot", "System", "Running the current kernel", "ok")]


def check_generation_count() -> list[Finding]:
    ref = generations.ProfileRef("NixOS system", generations.SYSTEM_PROFILE_DIR, "system", True)
    gens = generations.list_generations(ref)
    if not gens:
        return []
    n = len(gens)
    if n > 40:
        return [Finding("gen-count", "Storage", f"{n} system generations are kept", "warning",
                        "Every generation keeps its closure in the store and a boot entry in /boot.",
                        "Review the Generations page. NIXTUNE never deletes them; it can show you the command.",
                        docs.TOPIC_FOR_CHECK["gc"])]
    if n > 20:
        return [Finding("gen-count", "Storage", f"{n} system generations are kept", "info",
                        "That is fine, but old ones occupy disk space.", "", docs.TOPIC_FOR_CHECK["gc"])]
    return [Finding("gen-count", "Storage", f"{n} system generation(s) kept", "ok")]


def check_memory() -> list[Finding]:
    mem = sysinfo.memory()
    if not mem.total:
        return []
    out: list[Finding] = []
    avail_pct = 100.0 * mem.available / mem.total
    if avail_pct < 10:
        out.append(Finding("mem-low", "Memory", "Very little memory is available", "warning",
                           f"{sysinfo.format_bytes(mem.available)} available of {sysinfo.format_bytes(mem.total)}.",
                           "Close heavy applications, or consider `zramSwap.enable = true;` (see Optimizer)."))
    else:
        out.append(Finding("mem-ok", "Memory", "Memory pressure is low", "ok",
                           f"{sysinfo.format_bytes(mem.available)} available of {sysinfo.format_bytes(mem.total)}."))
    if mem.swap_total == 0 and mem.total <= 8 * 1024 ** 3:
        out.append(Finding("no-swap", "Memory", "No swap is configured", "info",
                           "With 8 GiB RAM or less, builds and browsers can hit out-of-memory conditions.",
                           "See the Optimizer page for a zram swap recommendation."))
    return out


def check_journal_errors() -> list[Finding]:
    res = runner.run(["journalctl", "-b", "-p", "err", "--no-pager", "-q", "-n", "15"], timeout=20)
    if res.missing:
        return []
    text = res.text
    if "insufficient permissions" in text.lower() or "not seeing messages" in text.lower():
        return [Finding("journal", "Services", "Journal not readable by your user", "info",
                        "Add yourself to the `systemd-journal` group (users.users.<name>.extraGroups) to let "
                        "NIXTUNE count boot errors.")]
    lines = [ln for ln in res.stdout.splitlines() if ln.strip() and not ln.startswith("-- ")]
    if lines:
        return [Finding("journal", "Services", f"Error-level messages this boot (showing {len(lines)})", "info",
                        "\n".join(lines[-15:]),
                        "Often harmless, but recurring entries point at real problems. `journalctl -b -p err` shows all.",
                        docs.TOPIC_FOR_CHECK["troubleshooting"])]
    return [Finding("journal", "Services", "No error-level journal messages this boot", "ok")]


def check_polkit() -> list[Finding]:
    out: list[Finding] = []
    helper = privileged.find_helper()
    pk = runner.pkexec_path()
    if pk and helper and helper.trusted:
        out.append(Finding("priv-helper", "Security", "Privileged helper is installed and trusted", "ok", helper.path))
    else:
        why = ("pkexec (setuid) not found" if not pk else
               "helper not found" if not helper else f"helper not trusted: {helper.reason}")
        out.append(Finding("priv-helper", "Security", "Privileged actions are unavailable", "info",
                           why + ". Cleanup actions will show the equivalent sudo command instead.",
                           "Install NIXTUNE via the flake / NixOS module (`programs.nixtune.enable = true;`) "
                           "so the helper lives in the read-only Nix store."))
    agent = False
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                with open(f"/proc/{pid}/comm", "r") as fh:
                    comm = fh.read().strip().lower()
            except OSError:
                continue
            if "polkit" in comm and ("agent" in comm or "auth" in comm):
                agent = True
                break
    except OSError:
        pass
    if agent:
        out.append(Finding("polkit-agent", "Security", "A polkit authentication agent is running", "ok"))
    else:
        out.append(Finding("polkit-agent", "Security", "No polkit authentication agent detected", "warning",
                           "Without one, password prompts for privileged actions cannot appear.",
                           "On KDE Plasma this is polkit-kde-authentication-agent-1 and starts with the session. "
                           "Outside a full desktop session, start an agent or use the sudo commands shown."))
    return out


def check_environment() -> list[Finding]:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "")
    session = os.environ.get("XDG_SESSION_TYPE", "unknown")
    if "KDE" in desktop.upper():
        return [Finding("desktop", "Desktop", "KDE Plasma session detected", "ok", f"{desktop} ({session})")]
    return [Finding("desktop", "Desktop", "Not running in a KDE Plasma session", "info",
                    f"Desktop: {desktop or 'unknown'} ({session}). NIXTUNE works anywhere, but the application-menu "
                    "integration is tuned for KDE.")]


def check_dependencies() -> list[Finding]:
    out: list[Finding] = []
    deps = depmod.check_all()
    miss_req = [d for d in deps if not d.found and d.required]
    miss_opt = [d for d in deps if not d.found and not d.required]
    if miss_req:
        out.append(Finding("deps-required", "Dependencies", f"{len(miss_req)} required dependency(ies) missing",
                           "error", ", ".join(d.name for d in miss_req),
                           "Open the Dependencies page for NixOS-specific instructions."))
    else:
        out.append(Finding("deps-required", "Dependencies", "All required dependencies are present", "ok"))
    if miss_opt:
        out.append(Finding("deps-optional", "Dependencies", f"{len(miss_opt)} optional dependency(ies) missing",
                           "info", ", ".join(d.name for d in miss_opt),
                           "Optional features degrade gracefully. See the Dependencies page."))
    return out


def check_store_optimisation() -> list[Finding]:
    cfg = nixenv.nix_config()
    val = nixenv.truthy(cfg.get("auto-optimise-store")) if cfg else None
    if val is None:
        return []
    if val:
        return [Finding("auto-optimise", "Nix", "auto-optimise-store is enabled", "ok")]
    return [Finding("auto-optimise", "Nix", "auto-optimise-store is off", "info",
                    "Identical files in the store are not deduplicated automatically.",
                    "See the Optimizer page for a safe recommendation.", docs.TOPIC_FOR_CHECK["gc"])]


CHECKS: tuple[Callable[[], list[Finding]], ...] = (
    check_nixos, check_nix_cli, check_store_access, check_flakes, check_config_files, check_disks,
    check_generation_count, check_failed_units, check_reboot_needed, check_memory, check_journal_errors,
    check_store_optimisation, check_polkit, check_environment, check_dependencies,
)


def run_all(progress: Optional[Callable[[str], None]] = None) -> list[Finding]:
    """Run every check; one failing check never stops the others."""
    findings: list[Finding] = []
    for check in CHECKS:
        name = check.__name__
        if progress:
            progress(f"Running {name.replace('check_', '').replace('_', ' ')}...")
        try:
            findings.extend(check())
        except Exception as exc:  # noqa: BLE001 - isolate every check
            log.exception("diagnostic %s crashed", name)
            findings.append(Finding(
                name, "Internal", f"Check '{name}' failed to run", "warning",
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc(limit=3)}",
                "This is a NIXTUNE bug or an unusual system state. Save the diagnostic report and file an issue.",
            ))
    findings.sort(key=lambda f: (_ORDER.get(f.severity, 9), f.category, f.title))
    return findings


def render_text(findings: list[Finding]) -> str:
    c = counts(findings)
    lines = [f"errors={c['error']} warnings={c['warning']} info={c['info']} ok={c['ok']}", ""]
    for f in findings:
        lines.append(f"[{f.severity.upper():7}] {f.category}: {f.title}")
        for part in (f.detail, f.remedy and f"Fix: {f.remedy}"):
            if part:
                lines += [f"            {ln}" for ln in part.splitlines()]
    return "\n".join(lines)
