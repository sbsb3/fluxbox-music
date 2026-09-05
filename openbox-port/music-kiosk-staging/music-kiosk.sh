#!/bin/sh
# /usr/local/bin/music-kiosk
# Music kiosk: Openbox + `plank -n kiosk` with Renoise, Bitwig Studio,
# SunVox and Max 9 as the only dock entries. Gajim, Audacious, Renoise,
# Bitwig Studio and SunVox are auto-started below (backgrounded, so this
# script returns immediately and Openbox can come up). The session has no
# single foreground app to tie its lifetime to the way renoise-kiosk
# ties it to Renoise; instead Openbox runs in the background and this
# script blocks on `wait $obpid`; the session ends when Openbox exits --
# via the C-A-End keybinding in rc.xml (Exit action) or by killing
# Openbox. See rc.xml.

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
xsetroot -solid black   # quick first paint; feh reasserts a pixmap below

# Black root pixmap: xsetroot -solid sets only the root window's
# background PIXEL, which on rotated RandR outputs (DP-2 portrait) the
# X server does not reliably apply to the entire rotated framebuffer,
# leaving the X server's default white visible in strips at the top and
# bottom of the portrait monitor.  feh --bg-fill creates a full-root-
# window-size PIXMAP (not a pixel) from a 1x1 black image and sets it
# as the root window background, covering every pixel regardless of
# output rotation.  Created once here, reused by the reaper loop below.
blackimg=/tmp/kiosk-black.png
convert -size 1x1 xc:black "$blackimg" 2>/dev/null || true
feh --no-fehbg --bg-fill "$blackimg" 2>/dev/null || xsetroot -solid black

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
# SunVox: a sunvox process orphaned by an earlier session logout
# (PPID 1) survives into the new X server and ends up registering a
# Plank "running" icon at the same time as the auto-launched sunvox
# below -- two icons for the same app, no StartupWMClass match
# because /usr/share/applications/sunvox.desktop lacks it.  The
# ~/.local/share/applications/sunvox.desktop override added by
# deploy.sh fixes FUTURE mappings; kill the orphan here so we don't
# also have a duplicate from the prior session.  Same for the
# sunvox-fix.py watcher (would reposition the wrong window if its
# target died while a duplicate spawned).
pkill -x sunvox 2>/dev/null || true
pkill -f 'sunvox-fix\.py' 2>/dev/null || true

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
#
# hide-mode='auto' + pressure-reveal=true: Plank defaults to
# hide-mode='intelligent', which auto-hides the dock when a
# fullscreen/maximized window overlaps it AND refuses to reveal on
# mouse-hover while that window has focus.  'auto' hides the dock the
# same way but always reveals on mouse-to-edge regardless of what
# window is focused.  pressure-reveal=true + unhide-delay=60 match the
# working dock1 config: the user pushes the mouse against the bottom
# edge and the dock appears after ~60ms of pressure.
#
# dock-items: re-asserted here so the SunVox icon sits next to BitWig
# regardless of what order a previous session left it in.  Plank's drag-
# to-reorder UI is not usable from the kiosk (no mouse interaction
# during a Renoise fullscreen session), and `pinned-only` plus the
# install of plank-kiosk/launchers/*.dockitem makes the file order the
# fallback source for new items -- which is alphabetical, so SunVox
# ('s') ends up at the far right.  Overriding dock-items explicitly
# here puts the DAWs together: Renoise, Bitwig, SunVox, Max 9.
#
# pinned-only=true: see the matching block in openbox-nopanel.sh for
# the full rationale.  Without it, a running app that Plank can't
# match to a pinned dockitem (typically because BAMF is still
# warming up when the auto-launched SunVox maps) is auto-added to
# the dock as a second icon -- "two SunVox icons".  pinned-only=true
# stops that and matches the kiosk's intended behavior: every app
# the user can launch is already pinned.
if command -v dconf >/dev/null 2>&1; then
    dconf write /net/launchpad/plank/docks/kiosk/hide-mode "'auto'" 2>/dev/null || true
    dconf write /net/launchpad/plank/docks/kiosk/pressure-reveal true 2>/dev/null || true
    dconf write /net/launchpad/plank/docks/kiosk/unhide-delay 60 2>/dev/null || true
    dconf write /net/launchpad/plank/docks/kiosk/pinned-only true 2>/dev/null || true
    dconf write /net/launchpad/plank/docks/kiosk/dock-items "['audacious.dockitem', 'org.gajim.Gajim.dockitem', 'org.pulseaudio.pavucontrol.dockitem', 'renoise.dockitem', 'com.bitwig.BitwigStudio.dockitem', 'sunvox.dockitem', 'max9.dockitem', 'plugdata.dockitem', 'org.hydrogenmusic.Hydrogen.dockitem', 'carla.dockitem', 'org.rncbc.qpwgraph.dockitem', 'audacity.dockitem', 'music-kiosk-logout.dockitem', 'org.wezfurlong.wezterm.dockitem']" 2>/dev/null || true
fi
plankpid=
if command -v plank >/dev/null 2>&1; then
    ( sleep 1; exec plank -n kiosk ) &
    plankpid=$!
fi

# Auto-start the user-requested apps: Gajim (chat), Audacious (player),
# plus the three DAWs on the dock (Renoise, Bitwig Studio, SunVox). Each
# is backgrounded so this script keeps going and Openbox keeps starting.
# Max 9 is intentionally NOT auto-started -- it stays on-demand from
# Plank like before, since it's the heaviest app and max-fix.py only
# engages when its window actually appears. sunvox-fix.py (started
# below) is window-driven, so it picks up an auto-launched SunVox too.
#
# ONE sequential launcher subshell, not five parallel sleep-races:
# 1. It first waits for Plank's dock window (and lets BAMF settle 2s
#    more) before launching anything. The old fixed +2..5s delays raced
#    Plank's own startup: a window that maps while Plank is still
#    loading dock items / activating BAMF fails the running-window ->
#    pinned-.dockitem association, and Plank then shows TWO icons (the
#    pinned SunVox/Renoise plus a second running one) for the whole
#    session. Renoise additionally needs StartupWMClass=Renoise in
#    ~/.local/share/applications/renoise.desktop (its WM_CLASS instance
#    is "renoise-3.5.4", which no desktop id matches; click-launch used
#    to hide this because Plank associates the PID it spawned itself).
# 2. Audacious is retried: on a cold boot the first attempt can die
#    with an error while the disk is still saturated -- it starts fine
#    when relaunched a few seconds later. Up to 3 attempts, 3s apart;
#    its output goes to the log (not /dev/null) so the actual error is
#    visible if it ever keeps failing.
# 3. The apps stay staggered so they don't all claim the JACK/Pulse
#    audio device at the same instant.
(
    if [ -n "$plankpid" ]; then
        # 15s max (60 x 0.25s); fall through if plank never maps so the
        # apps still start. Search by PID so a stale plank dying from the
        # pkill above can never satisfy the wait. Without xdotool, fall
        # back to a fixed wait.
        if command -v xdotool >/dev/null 2>&1; then
            i=0
            while [ "$i" -lt 60 ]; do
                kill -0 "$plankpid" 2>/dev/null || break
                xdotool search --pid "$plankpid" >/dev/null 2>&1 && break
                sleep 0.25
                i=$((i + 1))
            done
            sleep 2
        else
            sleep 10
        fi
    else
        sleep 5
    fi

    if command -v gajim >/dev/null 2>&1; then
        gajim >/dev/null 2>&1 &
    fi
    sleep 2

    if command -v audacious >/dev/null 2>&1; then
        tries=0
        while :; do
            audacious >>"$log" 2>&1 &
            sleep 3
            pgrep -x audacious >/dev/null 2>&1 && break
            tries=$((tries + 1))
            echo "music-kiosk: audacious died on attempt $tries" >>"$log"
            [ "$tries" -ge 3 ] && break
        done
    fi

    if command -v renoise >/dev/null 2>&1; then
        renoise >/dev/null 2>&1 &
        sleep 2
    fi
    if command -v bitwig-studio >/dev/null 2>&1; then
        bitwig-studio >/dev/null 2>&1 &
        sleep 2
    fi
    if command -v sunvox >/dev/null 2>&1; then
        sunvox >/dev/null 2>&1 &
    fi
) &

# Background reaper: openbox-autostart (/usr/lib/openbox/openbox-autostart)
# runs UNCONDITIONALLY before the user autostart guard: it sets the root
# window to #303030 (overriding our black) and openbox-xdg-autostart may
# launch tray applets from /etc/xdg/autostart.  The user autostart guard
# (OPENBOX_MUSIC_KIOSK=1) prevents pcmanfm/tint2/plank -n music from
# launching, but orphaned processes from the previous session (PPID 1)
# may still be drawing to the new X server.  This loop runs for ~6s after
# Openbox starts, killing leftovers and reasserting the black root pixmap
# (via feh, which covers rotated outputs — see the comment above where
# $blackimg is created), so any flash of icons or gray background lasts
# well under a second.
(
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12; do
        pkill -x tint2 2>/dev/null || true
        pkill -f 'pcmanfm --desktop' 2>/dev/null || true
        pkill -f 'plank -n music' 2>/dev/null || true
        pkill -f 'desktop-heads\.py' 2>/dev/null || true
        feh --no-fehbg --bg-fill "$blackimg" 2>/dev/null || xsetroot -solid black 2>/dev/null || true
        sleep 0.5
    done
    echo "=== ps snapshot at +6s ===" >>"$log"
    ps -eo pid,ppid,cmd --sort=pid >>"$log" 2>&1
) &
snap_pid=$!

# Max 9 (Wine/JUCE) auto-sets _NET_WM_STATE_FULLSCREEN when its window
# is resized to exactly match the monitor (1920x1080), which raises it
# above Plank's `above` layer.  JUCE also fights WM-level maximize by
# immediately stripping _NET_WM_STATE_MAXIMIZED via a ClientMessage.
# max-fix.py uses Xlib events to catch either state change and resize
# to 1920x1060 at (2446, 360) — width matches the monitor (frame right
# edge flush with DP-4), height is 20px shy (18px title bar + 2px shy so
# the frame doesn't exactly match monitor height and re-trigger JUCE
# fullscreen).  The window fills the screen horizontally with a visible
# title bar but stays in Normal layer where Plank can reveal over it.
maxfix_pid=
if python3 -c "import Xlib" >/dev/null 2>&1 && [ -x "${HOME}/.config/openbox-music-kiosk/max-fix.py" ]; then
    "${HOME}/.config/openbox-music-kiosk/max-fix.py" &
    maxfix_pid=$!
fi

# SunVox (SunDog engine via SDL2) writes an off-screen
# `user specified location` into WM_NORMAL_HINTS at startup and
# XMoveWindow's itself there shortly after mapping, so the rc.xml
# <position force="yes"> rule (which only fires on initial placement)
# can't keep it on DP-4.  sunvox-fix.py watches MapNotify /
# ConfigureNotify / WM_NORMAL_HINTS on sunvox class windows for the first
# few seconds after launch and force-positions them at DP-4 top-left
# + 10px margin (2456, 352) at the user's saved 1920x1062 size, and
# strips MAXIMIZED so the window stays windowed.  After the per-window
# deadline elapses the user can move/resize freely.
sunvoxfix_pid=
if python3 -c "import Xlib" >/dev/null 2>&1 && [ -x "${HOME}/.config/openbox-music-kiosk/sunvox-fix.py" ]; then
    "${HOME}/.config/openbox-music-kiosk/sunvox-fix.py" &
    sunvoxfix_pid=$!
fi

cleanup() {
    kill "$snap_pid" 2>/dev/null || true
    kill "$maxfix_pid" 2>/dev/null || true
    kill "$sunvoxfix_pid" 2>/dev/null || true
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
