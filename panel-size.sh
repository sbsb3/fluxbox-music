#!/bin/sh
# Switch the top tint2 panel between normal (56px) and compact (30px).
#   panel-size.sh normal|compact|toggle|show
# Also keeps Fluxbox session.screen0.struts.1 in sync so maximized windows
# stop under the panel.

set -eu

FLUX="${HOME}/.fluxbox"
INIT="${FLUX}/init"
PROFILE_FILE="${FLUX}/panel-profile"
TINT_DIR="${HOME}/.config/tint2"
NORMAL_RC="${TINT_DIR}/fluxbox-music.tint2rc"
COMPACT_RC="${TINT_DIR}/fluxbox-music-compact.tint2rc"
ACTIVE_RC="${TINT_DIR}/fluxbox-music-active.tint2rc"

NORMAL_STRUT=56
COMPACT_STRUT=30

have() { command -v "$1" >/dev/null 2>&1; }

current_profile() {
  if [ -f "$PROFILE_FILE" ]; then
    read -r p < "$PROFILE_FILE" || p=
    case "$p" in
      normal|compact) printf '%s\n' "$p"; return ;;
    esac
  fi
  # Infer from the config tint2 was started with.
  if pgrep -a tint2 2>/dev/null | grep -q 'fluxbox-music-compact'; then
    echo compact
  else
    echo normal
  fi
}

rc_for() {
  case "$1" in
    compact) printf '%s\n' "$COMPACT_RC" ;;
    *)       printf '%s\n' "$NORMAL_RC" ;;
  esac
}

strut_for() {
  case "$1" in
    compact) printf '%s\n' "$COMPACT_STRUT" ;;
    *)       printf '%s\n' "$NORMAL_STRUT" ;;
  esac
}

set_fluxbox_strut() {
  height=$1
  [ -f "$INIT" ] || return 0
  # struts.1 = left,right,top,bottom on Xinerama head 1 (primary in this setup)
  tmp=$(mktemp)
  awk -v h="$height" '
    BEGIN { done = 0 }
    /^session\.screen0\.struts\.1:/ {
      print "session.screen0.struts.1:\t0, 0, " h ", 0"
      done = 1
      next
    }
    { print }
    END {
      if (!done)
        print "session.screen0.struts.1:\t0, 0, " h ", 0"
    }
  ' "$INIT" > "$tmp"
  mv "$tmp" "$INIT"
  if have fluxbox-remote; then
    fluxbox-remote Reconfigure 2>/dev/null || true
  fi
}

place_tint2() {
  have xdotool || return 0
  have xrandr || return 0
  i=0
  while [ "$i" -lt 20 ]; do
    wid=$(xdotool search --class Tint2 2>/dev/null | head -n 1) || wid=
    if [ -n "$wid" ]; then
      geom=$(xrandr --query | awk '/ primary / {
        for (i = 1; i <= NF; i++)
          if ($i ~ /^[0-9]+x[0-9]+\+[0-9]+\+[0-9]+$/) print $i
      }')
      [ -n "$geom" ] || return 0
      w=${geom%%x*}
      rest=${geom#*x}
      rest=${rest#*+}
      x=${rest%%+*}
      y=${rest#*+}
      ph=$(xdotool getwindowgeometry "$wid" 2>/dev/null | awk '/Geometry:/{split($2,a,"x"); print a[2]}')
      ph=${ph:-30}
      xdotool windowmove "$wid" "$x" "$y" 2>/dev/null || true
      xdotool windowsize "$wid" "$w" "$ph" 2>/dev/null || true
      return 0
    fi
    i=$((i + 1))
    sleep 0.1
  done
}

restart_tray() {
  # tint2 owns the tray; applets must be restarted after the panel returns.
  for p in pasystray nm-applet; do
    killall -q "$p" 2>/dev/null || true
  done
  i=0
  while [ "$i" -lt 15 ]; do
    pgrep -x pasystray >/dev/null 2>&1 || pgrep -x nm-applet >/dev/null 2>&1 || break
    sleep 0.1
    i=$((i + 1))
  done
  sleep 0.25
  have pasystray && ! pgrep -x pasystray >/dev/null 2>&1 && pasystray >/dev/null 2>&1 &
  have nm-applet && ! pgrep -x nm-applet >/dev/null 2>&1 && nm-applet >/dev/null 2>&1 &
}

apply_profile() {
  profile=$1
  rc=$(rc_for "$profile")
  strut=$(strut_for "$profile")

  if [ ! -f "$rc" ]; then
    echo "panel-size: missing config $rc" >&2
    exit 1
  fi

  printf '%s\n' "$profile" > "$PROFILE_FILE"
  # Stable path for tint2 -c so startup and this script agree.
  ln -sfn "$(basename "$rc")" "$ACTIVE_RC"

  set_fluxbox_strut "$strut"

  if pgrep -x tint2 >/dev/null 2>&1; then
    killall -q tint2 2>/dev/null || true
    sleep 0.35
  fi
  if have tint2; then
    tint2 -c "$ACTIVE_RC" >/dev/null 2>&1 &
    place_tint2
    restart_tray
  fi
}

cmd=${1:-show}
case "$cmd" in
  show)
    current_profile
    ;;
  normal|compact)
    apply_profile "$cmd"
    ;;
  toggle)
    cur=$(current_profile)
    if [ "$cur" = compact ]; then
      apply_profile normal
    else
      apply_profile compact
    fi
    ;;
  *)
    echo "usage: $0 normal|compact|toggle|show" >&2
    exit 2
    ;;
esac
