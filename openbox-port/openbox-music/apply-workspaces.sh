#!/bin/sh
# This Openbox session uses two workspaces: Internet and Audio, set
# statically in ~/.config/openbox/rc.xml's <desktops>. XFCE xfconf (4 names)
# is restored afterwards so an XFCE login is unchanged.
#
# gap #6 / PORT-NOTES.md: the fluxbox-remote-driven add/remove/rename-
# workspace logic from the Fluxbox version of this script is gone -- desktop
# count/names are static in rc.xml now, nothing to apply at runtime for that
# part. What's left is the xfsettingsd fight, and it is NOT Fluxbox-specific:
# tested live against a fresh Openbox session (Xephyr, no xfsettingsd
# started yet) and confirmed xfsettingsd rewrites the root window's
# _NET_DESKTOP_NAMES to XFCE's own names ("Internet", "Dev", "") within
# ~2 seconds of starting, regardless of which WM owns the desktop count/
# names -- it's a property write, not something routed through the WM.
# wmctrl -d confirmed the second desktop's live name changed from "Audio"
# to "Dev". So this half of the script is still needed, unchanged in kind.

set -eu

have() { command -v "$1" >/dev/null 2>&1; }

# Stop xfsettingsd from renaming Internet/Audio back to XFCE's first two
# names (Internet, Dev) or shrinking xfconf workspace_count to 2.
if pgrep -x xfsettingsd >/dev/null 2>&1; then
  killall xfsettingsd 2>/dev/null || true
  sleep 0.2
fi

if have xfconf-query; then
  xfconf-query -c xfwm4 -p /general/workspace_count -s 4 -t int 2>/dev/null || true
  xfconf-query -c xfwm4 -p /general/workspace_names \
    -t string -s Internet -t string -s Dev -t string -s Audio -t string -s "Workspace 4" \
    2>/dev/null || true
fi

# Belt and suspenders: if xfsettingsd got a write in before this ran (this
# script races it at startup the same way the Fluxbox version did), the
# names may already be wrong on the root window. Tested and ruled out live
# in a throwaway Xephyr session before settling on this:
#   - neither wmctrl nor xdotool has a verb to rewrite _NET_DESKTOP_NAMES
#   - openbox --reconfigure does NOT re-publish rc.xml's <desktops><names>
#     over an existing root property -- confirmed it leaves a corrupted
#     name untouched
#   - a full kill + restart of Openbox does not either -- Openbox treats
#     existing _NET_DESKTOP_NAMES/_NET_NUMBER_OF_DESKTOPS on the root
#     window as authoritative over rc.xml on every start, not just reconfig
# So write the property directly (same Xlib dependency every other script
# here already uses) -- confirmed this sticks with nothing then fighting it,
# since xfsettingsd is already dead by this point.
if python3 -c "import Xlib" >/dev/null 2>&1; then
  python3 - <<'PY'
from Xlib import display
d = display.Display()
root = d.screen().root
names_atom = d.intern_atom("_NET_DESKTOP_NAMES")
utf8_atom = d.intern_atom("UTF8_STRING")
root.change_property(names_atom, utf8_atom, 8, b"Internet\x00Audio\x00")
d.flush()
PY
fi
