#!/bin/sh
# Switch the top tint2 panel between normal (56px) and compact (30px).
#   panel-size.sh normal|compact|toggle|show
#
# gap #8 / PORT-NOTES.md: Fluxbox's set_fluxbox_strut() wrote
# session.screen0.struts.1 directly to force a specific Xinerama head's
# reserved space, because tint2's own strut_policy reserves space relative
# to the *virtual screen* edge, which does not line up with "top of the
# primary monitor" on this L-shaped 3-head layout. Openbox has no per-head
# equivalent to struts.N at all -- rc.xml's <margins> is a single value for
# the whole desktop, not per-monitor -- so that function has no target to
# port to and is dropped, not just simplified. See PORT-NOTES.md for what
# was tested and what still needs verifying on the real 3-monitor layout
# (tint2's own strut_policy / panel_pivot_struts).

set -eu

FLUX="${HOME}/.openbox-music"
PROFILE_FILE="${FLUX}/panel-profile"
TINT_DIR="${HOME}/.config/tint2"
NORMAL_RC="${TINT_DIR}/openbox-music.tint2rc"
COMPACT_RC="${TINT_DIR}/openbox-music-compact.tint2rc"
ACTIVE_RC="${TINT_DIR}/openbox-music-active.tint2rc"

have() { command -v "$1" >/dev/null 2>&1; }

current_profile() {
  if [ -f "$PROFILE_FILE" ]; then
    read -r p < "$PROFILE_FILE" || p=
    case "$p" in
      normal|compact) printf '%s\n' "$p"; return ;;
    esac
  fi
  # Infer from the config tint2 was started with.
  if pgrep -a tint2 2>/dev/null | grep -q 'openbox-music-compact'; then
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

resync_desktop() {
  # The panel just changed height, so the per-monitor workareas moved.
  # pcmanfm samples its working area once per desktop window and afterwards
  # only watches _NET_WORKAREA -- which never moves here, because the panel is
  # not at the top of the virtual screen -- so the desktop has to be rebuilt or
  # the top icon row ends up under tint2. desktop-heads.py does that on its own
  # within a poll when it is running; only step in when it is not.
  [ -x "${FLUX}/desktop-heads.py" ] || return 0
  if pgrep -f "${FLUX}/desktop-heads.py" >/dev/null 2>&1; then
    return 0
  fi
  "${FLUX}/desktop-heads.py" --resync >/dev/null 2>&1 || true
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
  # Use if/fi so `&` backgrounds only the applet. An `A && B && cmd &` list
  # runs in a subshell that waits on cmd, leaving orphan shells forever.
  if have pasystray && ! pgrep -x pasystray >/dev/null 2>&1; then
    pasystray >/dev/null 2>&1 &
  fi
  if have nm-applet && ! pgrep -x nm-applet >/dev/null 2>&1; then
    nm-applet >/dev/null 2>&1 &
  fi
}

apply_profile() {
  profile=$1
  rc=$(rc_for "$profile")

  if [ ! -f "$rc" ]; then
    echo "panel-size: missing config $rc" >&2
    exit 1
  fi

  printf '%s\n' "$profile" > "$PROFILE_FILE"
  # Stable path for tint2 -c so startup and this script agree.
  ln -sfn "$(basename "$rc")" "$ACTIVE_RC"

  if pgrep -x tint2 >/dev/null 2>&1; then
    killall -q tint2 2>/dev/null || true
    sleep 0.35
  fi
  if have tint2; then
    tint2 -c "$ACTIVE_RC" >/dev/null 2>&1 &
    place_tint2
    restart_tray
  fi
  resync_desktop
}

cmd=${1:-show}
case "$cmd" in
  show)
    current_profile
    ;;
  normal|compact|toggle)
    # Serialize profile changes; double-clicks from the menu used to race
    # two restarts and leave orphan tray-holder shells.
    lockdir="${FLUX}/panel-size.lock"
    if mkdir "$lockdir" 2>/dev/null; then
      trap 'rmdir "$lockdir" 2>/dev/null' EXIT
    else
      echo "panel-size: already running" >&2
      exit 0
    fi
    if [ "$cmd" = toggle ]; then
      cur=$(current_profile)
      if [ "$cur" = compact ]; then
        apply_profile normal
      else
        apply_profile compact
      fi
    else
      apply_profile "$cmd"
    fi
    ;;
  *)
    echo "usage: $0 normal|compact|toggle|show" >&2
    exit 2
    ;;
esac
