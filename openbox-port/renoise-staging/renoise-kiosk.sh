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

# Tell ~/.config/openbox/autostart to stand down: it runs unconditionally
# whenever plain `openbox` starts (see that file's own comment), and left
# unguarded it re-runs `autorandr --change --default` a moment after the
# xrandr call below, replacing this 2-monitor layout with the saved 3-monitor
# one (HDMI-0 back on, DP-4/DP-2 moved) -- which is what was dragging Renoise
# back onto the portrait screen -- and relaunches tint2 right after the
# pkill above.
export OPENBOX_RENOISE_KIOSK=1

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

exec renoise
