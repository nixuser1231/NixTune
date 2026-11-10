# NIXTUNE 1.0

Maintenance, diagnostics and tuning for **NixOS**, built with Python 3 + PySide6 and tuned for KDE Plasma
(dark blue/purple UI). Runs as a normal user; admin rights are requested per action through polkit.

| Page | What it does |
|---|---|
| Dashboard | Live CPU, RAM, disk, uptime (read from `/proc`, no extra packages) |
| Nix Cleaner | Previews garbage-collection candidates (`nix-store --gc --print-dead`) and reclaimable size; cleanup only after explicit confirmation |
| Generations | Lists system/user generations with dates; never deletes. Builds delete commands for **you** to review and run |
| Services | systemd units (system/user) with status, filter, failed-first |
| Diagnostics | Missing tools, Nix daemon, flakes, disk/memory, polkit, failed units, journal errors, desktop session |
| Optimizer | Explained, optional recommendations (each says why, risk and the exact config snippet) |
| Dependencies | Detects missing dependencies and explains the NixOS way to add them |
| Documentation | Curated links to https://nixos.org/manual/nixos/stable/ (opened in your browser; https + official hosts only) |
| Desktop Integration | Previews, then installs a per-user KDE application-menu launcher + icon |

Also: *Save error report* (redacted, written locally, never uploaded) and a global error dialog.

## Install

### Try it (no installation)
```
nix-shell            # uses shell.nix
python -m nixtune
```
or simply run `./nixtune-launch.sh` (the one-click launcher: uses PySide6 if present, otherwise `nix-shell`).

### With flakes
```
nix run .                         # run
nix profile install .             # install for your user
```

### Permanently, system-wide (recommended: enables the polkit-protected cleanup actions)
```nix
# flake.nix of your system
inputs.nixtune.url = "path:/path/to/nixtune-1.0";   # or your git URL
# in your configuration:
imports = [ inputs.nixtune.nixosModules.default ];
programs.nixtune.enable = true;
```
then `sudo nixos-rebuild switch`. The module installs the package, enables polkit, and links the
polkit policy and helper. NIXTUNE never edits your configuration itself.

### Menu entry
Either use the app (*Desktop Integration -> Install launcher*, shows exactly what will be written first),
or it is installed automatically by the package (`share/applications/nixtune.desktop`).

## Dependency checker
```
./nixtune-check-deps --explain     # works even without Qt
nixtune --diagnose --report report.txt
```

## Security model
* The GUI refuses to run as root.
* The only privileged code is `helper/nixtune-helper`, started via `pkexec`. It accepts exactly one
  argument from a fixed allow-list (`gc` -> `nix-store --gc`, `optimise` -> `nix-store --optimise`), takes no
  paths or flags, scrubs the environment and uses only root-owned tools.
* NIXTUNE only uses the helper if it is root-owned and not user-writable (true in the Nix store). From a plain
  source checkout the helper is *refused* and the UI shows the equivalent `sudo` command for you to run.
* System generations are never deleted by NIXTUNE; no action touches configuration files.
* Every destructive action shows a preview and needs confirmation.
* Nothing downloaded is ever executed; documentation links open in your own browser.

## Tests
```
python -m pytest tests                              # logic + stand-in-Qt smoke tests
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py # real Qt, writes screenshots to shots/
```

## Honest status
Verified in the build environment (Ubuntu, non-root user, Nix 2.34, **no PySide6 installable**): all
non-Qt logic, CLI, diagnostics, helper, desktop-entry install/uninstall, Nix syntax of `flake.nix`/`shell.nix`,
and construction of every GUI page against a stand-in Qt. **Not verified here:** rendering with real PySide6, a
real NixOS host, `nix build` of the flake, and the polkit prompt. Please run `tests/gui_smoke.py` and
`nix build` on your machine and report problems via *Save error report*.
