#!/bin/sh
# Make Audacious follow the current workspace.
#   audacious-follow.sh on|off|toggle|show
#
# The flag lives in /dev/shm so it dies on reboot and stays out of the config
# dir. audacious-stack.py does the move on _NET_CURRENT_DESKTOP (every switch
# path). Flag filenames keep their historical "fluxbox-" prefix -- it is just
# an IPC contract string shared with audacious-stack.py, not a WM dependency.

set -eu

FLAG="/dev/shm/fluxbox-audacious-follow-$(id -u)"
LEGACY="/dev/shm/fluxbox-audacious-park-$(id -u)"
STACK="${HOME}/.openbox-music/audacious-stack.py"

apply() {
  if [ -x "$STACK" ]; then
    python3 "$STACK" --apply-follow || true
  fi
}

on() {
  rm -f "$LEGACY"
  touch "$FLAG"
  apply
}

off() {
  rm -f "$FLAG" "$LEGACY"
}

is_on() {
  [ -f "$FLAG" ] || [ -f "$LEGACY" ]
}

cmd=${1:-show}
case "$cmd" in
  show)
    if is_on; then
      echo on
    else
      echo off
    fi
    ;;
  on)
    on
    ;;
  off)
    off
    ;;
  toggle)
    if is_on; then
      off
    else
      on
    fi
    ;;
  *)
    echo "usage: $0 on|off|toggle|show" >&2
    exit 2
    ;;
esac
