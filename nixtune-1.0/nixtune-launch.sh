#!/usr/bin/env bash
# NIXTUNE one-click launcher (source checkout).
# Starts the app with whatever provides PySide6: the current Python, else
# nix-shell/nix develop using this project's own shell.nix / flake.nix.
# It never runs as root and never downloads or runs anything but nixpkgs'
# normal, hash-verified packages.
set -u
here="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"

fail() {
  msg="$1"
  echo "NIXTUNE: $msg" >&2
  if [ ! -t 2 ]; then
    if command -v kdialog >/dev/null 2>&1; then kdialog --error "$msg" --title NIXTUNE >/dev/null 2>&1
    elif command -v notify-send >/dev/null 2>&1; then notify-send -a NIXTUNE "NIXTUNE could not start" "$msg"
    fi
  fi
  exit 1
}

[ "$(id -u)" = 0 ] && fail "refusing to run as root. Start it as your normal user."

export PYTHONPATH="$here/src${PYTHONPATH:+:$PYTHONPATH}"

if python3 -c 'import PySide6' >/dev/null 2>&1; then
  exec python3 -m nixtune "$@"
fi

args=""
for a in "$@"; do args="$args $(printf '%q' "$a")"; done
cmd="exec python3 -m nixtune$args"

if command -v nix-shell >/dev/null 2>&1; then
  exec nix-shell "$here/shell.nix" --run "$cmd"
elif command -v nix >/dev/null 2>&1; then
  exec nix --extra-experimental-features 'nix-command flakes' develop "$here" --command bash -c "$cmd"
fi
fail "PySide6 is missing and Nix was not found. See README.md."
