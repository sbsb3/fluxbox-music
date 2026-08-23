#!/bin/sh
# /usr/local/bin/renoise-kiosk
# Renoise kiosk: fullscreen on primary (DP-4), portrait monitor (DP-2) alive for plugin windows.

log=/tmp/renoise-kiosk.log
exec >>"$log" 2>&1
set -x

# --- Environment: match the music sessions so Renoise and plugin UIs
# render at the right size and find their VST/LV2 paths.  LightDM's
# /etc/lightdm/Xsession wrapper loads ~/.Xresources for every session,
# but that file has no Xft.dpi -- only the fluxbox/openbox-music startup
# scripts merge Xft.dpi:96 from their own Xresources.  Without it here,
# X computes DPI from the multi-monitor virtual screen's physical size
# and everything comes out way too large.
export XDG_CURRENT_DESKTOP=Openbox
export GDK_BACKEND=x11
export QT_QPA_PLATFORM=xcb
export GTK_THEME=Adwaita-dark
export XCURSOR_THEME=Adwaita
export XCURSOR_SIZE=24
export GDK_SCALE=1
export QT_AUTO_SCREEN_SCALE_FACTOR=0
export JACK_NO_START_SERVER=1
export VST3_PATH="${HOME}/.vst3:${HOME}/vst3:/usr/lib/vst3${VST3_PATH:+:$VST3_PATH}"
export VST_PATH="${HOME}/.vst:/usr/lib/vst${VST_PATH:+:$VST_PATH}"
export CLAP_PATH="${HOME}/.clap:/usr/lib/clap${CLAP_PATH:+:$CLAP_PATH}"
export LV2_PATH="${HOME}/.lv2:/usr/lib/lv2${LV2_PATH:+:$LV2_PATH}"

# Xft.dpi: 96 — the single most important line for correct rendering.
xrdb -merge <<'EOF'
Xft.dpi: 96
Xft.antialias: true
Xft.hinting: true
Xft.hintstyle: hintslight
Xft.rgba: rgb
Xcursor.theme: Adwaita
Xcursor.size: 24
EOF

xset s off
xset s noblank
xset -dpms
xsetroot -solid black   # requires xorg-xsetroot

# Kill orphaned processes from previous Fluxbox/Openbox music sessions.
# Their autostart/startup scripts background watchdog loops (tint2
# restart, desktop-heads, fullscreen-panel, etc.) that survive session
# logout as orphans (PPID 1).  The tint2 watchdog is the one that kept
# bringing the panel back: the ps snapshot in /tmp/renoise-kiosk.log
# showed multiple `sh /home/sb/.config/openbox/autostart` processes
# still alive from a prior session, each looping
#   while pgrep tint2; sleep 1; done; panel-size.sh ...
# Kill the watchdogs first (so they can't restart tint2), then tint2.
pkill -f '/home/sb/.config/openbox/autostart' 2>/dev/null || true
pkill -f '/home/sb/.fluxbox/startup' 2>/dev/null || true
pkill -f 'desktop-heads\.py' 2>/dev/null || true
pkill -x tint2 2>/dev/null || true
pkill -x picom 2>/dev/null || true
pkill -x plank 2>/dev/null || true

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

openbox --config-file "$HOME/.config/openbox-renoise/rc.xml" --sm-disable &
obpid=$!

# One-shot delayed kill: if something in the LightDM/Xsession chain
# starts tint2 a few seconds after the session begins (after our initial
# pkill already ran), this catches it.  Not a loop -- runs once, 5s after
# openbox starts, then exits.  Also logs a process snapshot so if tint2
# still shows up we can trace what launched it.
(
    sleep 5
    pkill -x tint2 2>/dev/null || true
    echo "=== ps snapshot at +5s ===" >>"$log"
    ps -eo pid,ppid,cmd --sort=pid >>"$log" 2>&1
) &
snap_pid=$!

cleanup() {
    kill "$snap_pid" 2>/dev/null || true
    kill "$obpid" 2>/dev/null || true
    sudo systemctl unmask autorandr.service 2>/dev/null || true
    sudo systemctl start --no-block autorandr.service 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Not exec'd: Renoise needs to actually return here so the trap fires.
renoise
