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
# `plank -n kiosk` we start below.
pkill -f '/home/sb/.config/openbox/autostart' 2>/dev/null || true
pkill -f '/home/sb/.fluxbox/startup' 2>/dev/null || true
pkill -f 'desktop-heads\.py' 2>/dev/null || true
pkill -x tint2 2>/dev/null || true
pkill -x picom 2>/dev/null || true
pkill -x plank 2>/dev/null || true

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

openbox --config-file "$HOME/.config/openbox-music-kiosk/rc.xml" --sm-disable &
obpid=$!

# Named dock "kiosk": only Renoise, Bitwig, SunVox, Max 9 (see
# plank-kiosk/launchers/*.dockitem, deployed to ~/.config/plank/kiosk/).
# Sleep 1 so Openbox is up first and Plank registers against it; also
# gives the pkill above a moment to settle.
plankpid=
if command -v plank >/dev/null 2>&1; then
    ( sleep 1; exec plank -n kiosk ) &
    plankpid=$!
fi

# One-shot delayed snapshot at +5s: catches anything the LightDM/Xsession
# chain starts a few seconds in (after our initial pkill already ran) and
# logs a process tree so it's traceable if tint2/a stray plank reappears.
(
    sleep 5
    pkill -x tint2 2>/dev/null || true
    echo "=== ps snapshot at +5s ===" >>"$log"
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
