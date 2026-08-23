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

# Layout: DP-4 primary landscape at 0x0, DP-2 portrait to its left, HDMI-0 off.
# A fresh X server forgets your XFCE layout, so rotation and positions must be
# set explicitly here. Add e.g. --rate 144 to DP-4 if you want high refresh.
xrandr --output DP-4 --mode 1920x1080 --primary --pos 0x0 \
       --output DP-2 --mode 1920x1080 --rotate right --pos -1080x0 \
       --output HDMI-0 --off

openbox --config-file "$HOME/.config/openbox-renoise/rc.xml" &

exec renoise
