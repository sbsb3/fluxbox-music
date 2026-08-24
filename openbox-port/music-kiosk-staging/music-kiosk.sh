#!/bin/sh
# /usr/local/bin/music-kiosk
# Music kiosk: Openbox + `plank -n kiosk` with Renoise, Bitwig Studio,
# SunVox and Max 9 as the only dock entries. The DAWs are launched on
# demand from Plank (this script does NOT auto-start any of them), so the
# session has no single foreground app to tie its lifetime to the way
# renoise-kiosk ties it to Renoise. Instead Openbox runs in the background
# and this script blocks on `wait $obpid`; the session ends when Openbox
# exits -- via the C-A-End keybinding in rc.xml (Exit action) or by
# killing Openbox. See rc.xml.

log=/tmp/music-kiosk.log
exec >>"$log" 2>&1
set -x

# --- Environment: match the music/renoise-kiosk sessions so the DAWs and
# plugin UIs render at the right size and find their VST/LV2 paths.
# LightDM's /etc/lightdm/Xsession wrapper loads ~/.Xresources for every
# session, but that file has no Xft.dpi -- only the fluxbox/openbox-music
# startup scripts merge Xft.dpi:96 from their own Xresources.  Without it
# here, X computes DPI from the multi-monitor virtual screen's physical
# size and everything comes out way too large.
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
# logout as orphans (PPID 1).  Kill the watchdogs first (so they can't
# restart tint2), then tint2.  Plank is killed here too so a stale
# `plank -n music` / default dock1 from a prior session can't fight the
# `plank -n kiosk` we start below.  pcmanfm --desktop is killed so desktop
# icons from a prior Fluxbox/openbox-music session don't bleed through
# onto the non-fullscreen monitors (HDMI-0, DP-2) in the kiosk; only
# `pcmanfm --desktop` is targeted, not file-browser windows.
pkill -f '/home/sb/.config/openbox/autostart' 2>/dev/null || true
pkill -f '/home/sb/.fluxbox/startup' 2>/dev/null || true
pkill -f 'desktop-heads\.py' 2>/dev/null || true
pkill -x tint2 2>/dev/null || true
pkill -x picom 2>/dev/null || true
pkill -x plank 2>/dev/null || true
pkill -f 'pcmanfm --desktop' 2>/dev/null || true

# Belt-and-suspenders: ~/.config/openbox/autostart is sourced by
# /usr/lib/openbox/openbox-autostart unconditionally after Openbox starts
# (see that file's header), regardless of --config-file.  Its guard at
# line 23 stands down for OPENBOX_MUSIC_SESSION=1 / OPENBOX_RENOISE_KIOSK=1
# so it doesn't clobber this kiosk's xrandr layout / relaunch tint2.
# Reuse OPENBOX_MUSIC_SESSION=1 to trip the existing guard (no edit to the
# live autostart needed); OPENBOX_MUSIC_KIOSK=1 is this session's own tag
# for any future consumer.
export OPENBOX_MUSIC_SESSION=1
export OPENBOX_MUSIC_KIOSK=1

# A system udev rule (/usr/lib/udev/rules.d/40-monitor-hotplug.rules)
# restarts autorandr.service on every DRM "change" event, and the xrandr
# call below is exactly such an event.  The layout below now matches the
# saved XFCE/autorandr "default" profile exactly, so autorandr re-applying
# it would be a no-op -- but the re-apply event itself still causes a
# mid-session flicker, so mask for the duration and restore on exit.
# Needs the sudoers rule in music-kiosk.sudoers (see deploy.sh) so this
# doesn't block on a password with no terminal around to answer one.
sudo systemctl mask --now autorandr.service 2>/dev/null || true

# Layout: all 3 monitors on, positions copied verbatim from the XFCE
# displays.xml "default" profile (and autorandr ~/.config/autorandr/default):
#   HDMI-0  1366x768 @59.79  pos 0x273     (leftmost, landscape)
#   DP-2    1920x1080 @60     pos 1366x0   (portrait, rotated right)
#   DP-4    1920x1080 @60     pos 2446x342 (primary, landscape, rightmost)
# A fresh X server forgets the XFCE layout, so rotation/positions/rates
# must be set explicitly here.  HDMI-0 sits to the left of DP-2 which sits
# to the left of DP-4, matching the physical desk layout.
xrandr --output HDMI-0 --mode 1366x768 --rate 59.79 --pos 0x273 \
       --output DP-2   --mode 1920x1080 --rate 60 --rotate right --pos 1366x0 \
       --output DP-4   --mode 1920x1080 --rate 60 --primary --pos 2446x342

# HDMI-0 color profile: software gamma ramp (xrandr --brightness/--gamma
# rewrite the gamma LUT, not hardware).  Applied after the layout call
# because any xrandr reconfiguration of the output resets the ramp.
# 1.0:0.52:0.18 is a warm/red-heavy tint for that monitor.
xrandr --output HDMI-0 --brightness 1.0 --gamma 1.0:0.52:0.18

openbox --config-file "$HOME/.config/openbox-music-kiosk/rc.xml" --sm-disable &
obpid=$!

# Compositor: reuses the fluxbox-music picom config (xrender backend,
# unredir-if-possible=false).  Without a compositor Plank's zoom/hover
# animation paints solid black over the DAW below it (Plank is a depth-32
# ARGB dock that needs compositing live), and there are no window shadows
# or transparency.  Started after Openbox so it has a WM to talk to and
# before Plank so the dock animates from first map.  --daemon forks, so
# no PID to track; it exits with the X server / session, and the
# pkill -x picom in the orphan-cleanup above handles any stale instance
# from a prior session.
if command -v picom >/dev/null 2>&1; then
    picom --config "$HOME/.config/picom/fluxbox-music.conf" --daemon
fi

# Named dock "kiosk": only Renoise, Bitwig, SunVox, Max 9 (see
# plank-kiosk/launchers/*.dockitem, deployed to ~/.config/plank/kiosk/).
# Sleep 1 so Openbox is up first and Plank registers against it; also
# gives the pkill above a moment to settle.
plankpid=
if command -v plank >/dev/null 2>&1; then
    ( sleep 1; exec plank -n kiosk ) &
    plankpid=$!
fi

# Background reaper: openbox-autostart (/usr/lib/openbox/openbox-autostart)
# runs UNCONDITIONALLY before the user autostart guard: it sets the root
# window to #303030 and then openbox-xdg-autostart may launch tray applets
# (nm-applet, pasystray) from /etc/xdg/autostart and ~/.config/autostart.
# The user autostart guard (OPENBOX_MUSIC_KIOSK=1) prevents pcmanfm/tint2/
# plank -n music from launching, but orphaned processes from the previous
# session (PPID 1) may still be drawing to the new X server, and the
# #303030 background overrides our xsetroot -solid black.  This loop runs
# for ~6s after Openbox starts, killing leftovers and reasserting black,
# so any flash of icons or gray background lasts well under a second.
(
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
        pkill -x tint2 2>/dev/null || true
        pkill -f 'pcmanfm --desktop' 2>/dev/null || true
        pkill -f 'plank -n music' 2>/dev/null || true
        pkill -f 'desktop-heads\.py' 2>/dev/null || true
        xsetroot -solid black 2>/dev/null || true
        sleep 0.5
    done
    echo "=== ps snapshot at +6s ===" >>"$log"
    ps -eo pid,ppid,cmd --sort=pid >>"$log" 2>&1
) &
snap_pid=$!

cleanup() {
    kill "$snap_pid" 2>/dev/null || true
    [ -n "$plankpid" ] && kill "$plankpid" 2>/dev/null || true
    pkill -x plank 2>/dev/null || true
    kill "$obpid" 2>/dev/null || true
    sudo systemctl unmask autorandr.service 2>/dev/null || true
    sudo systemctl start --no-block autorandr.service 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Block until Openbox exits (C-A-End -> Exit in rc.xml, or killed).
# `wait` returns the exit status of $obpid; ignore it (the trap cleans up).
wait "$obpid" 2>/dev/null || true
