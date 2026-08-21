#!/bin/sh
# This Fluxbox session uses two workspaces: Internet and Audio.
# XFCE xfconf (4 names) is restored afterwards so an XFCE login is unchanged.
# xfsettingsd copies XFCE names onto Fluxbox, so it is stopped after GTK setup.

set -eu

have() { command -v "$1" >/dev/null 2>&1; }
have wmctrl || exit 0
have fluxbox-remote || exit 0

fb() {
  fluxbox-remote "$1" || true
  sleep 0.2
}

desktop_count() {
  xprop -root -notype _NET_NUMBER_OF_DESKTOPS 2>/dev/null | awk '{ print $NF }'
}

n=$(desktop_count)
n=${n:-0}
[ "$n" -ge 1 ] || exit 0

while [ "$n" -gt 2 ]; do
  fb RemoveLastWorkspace
  n=$(desktop_count)
  n=${n:-2}
done
while [ "$n" -lt 2 ]; do
  fb AddWorkspace
  n=$(desktop_count)
  n=${n:-2}
done

cur=$(xprop -root -notype _NET_CURRENT_DESKTOP 2>/dev/null | awk '{ print $NF }')
cur=${cur:-0}

fb "Workspace 1"
fb "SetWorkspaceName Internet"
fb "Workspace 2"
fb "SetWorkspaceName Audio"

if [ "$cur" -ge 1 ]; then
  fb "Workspace 2"
else
  fb "Workspace 1"
fi

# Stop xfsettingsd from renaming these back to XFCE's first two names
# (Internet, Dev) or shrinking xfconf workspace_count to 2.
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
