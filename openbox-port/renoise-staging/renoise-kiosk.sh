#!/bin/sh
# /usr/local/bin/renoise-kiosk
# Renoise kiosk: fullscreen on primary (DP-4), portrait monitor (DP-2) alive for plugin windows.

log=/tmp/renoise-kiosk.log
exec >>"$log" 2>&1
set -x

xset s off
xset -dpms
xsetroot -solid black   # requires xorg-xsetroot

pkill -x tint2 || true

# Belt-and-suspenders: if ~/.config/openbox/autostart ever does run under
# this session (it shouldn't for a plain `openbox --config-file` process --
# verified directly, this is not firing today), this tells it to stand down
# rather than fight the layout/tint2 below. See that file's own guard.
export OPENBOX_RENOISE_KIOSK=1

# The actual culprit for Renoise landing on the wrong monitor: a system udev
# rule (/usr/lib/udev/rules.d/40-monitor-hotplug.rules) restarts
# autorandr.service on every DRM "change" event, and the xrandr call below
# is exactly such an event. Left alone, autorandr.service reapplies the
# saved 3-monitor "default" profile (HDMI-0 back on, DP-4/DP-2 moved) a
# moment later -- while Renoise is still loading its scripting tools, well
# before it reaches window placement -- undoing this layout out from under
# it. Mask it for the duration; restored after Renoise exits below. Needs
# the sudoers rule in renoise-kiosk.sudoers (see deploy.sh) so this doesn't
# block on a password with no terminal around to answer one.
sudo systemctl mask --now autorandr.service 2>/dev/null || true

# Layout: DP-4 primary landscape at 0x0, DP-2 portrait to its left, HDMI-0 off.
# A fresh X server forgets your XFCE layout, so rotation and positions must be
# set explicitly here. Add e.g. --rate 144 to DP-4 if you want high refresh.
# The -342 y-offset on DP-2 matches its vertical alignment against DP-4 in
# the saved XFCE/autorandr "default" layout (DP-2 pos 1366x0, DP-4 pos
# 2446x342 there -- same -1080x-342 delta), so the mouse crosses the
# DP-2/DP-4 border in a straight line instead of jumping vertically.
xrandr --output DP-4 --mode 1920x1080 --primary --pos 0x0 \
       --output DP-2 --mode 1920x1080 --rotate right --pos -1080x-342 \
       --output HDMI-0 --off

openbox --config-file "$HOME/.config/openbox-renoise/rc.xml" &

# Not exec'd: Renoise needs to actually return here so autorandr.service can
# be restored below for normal (XFCE) use afterward.
renoise

sudo systemctl unmask autorandr.service 2>/dev/null || true
sudo systemctl start --no-block autorandr.service 2>/dev/null || true
