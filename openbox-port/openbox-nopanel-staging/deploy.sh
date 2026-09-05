#!/bin/sh
# deploy.sh - install Openbox No Panel files from staging to system locations.
#
#   openbox-nopanel.sh          -> /usr/local/bin/openbox-nopanel          (sudo)
#   rc.xml                      -> ~/.config/openbox-nopanel/rc.xml         (user)
#   menu.xml                    -> ~/.config/openbox-nopanel/menu.xml       (user)
#   openbox-nopanel.desktop     -> /usr/share/xsessions/openbox-nopanel.desktop (sudo)
#   openbox-nopanel.sudoers     -> /etc/sudoers.d/openbox-nopanel           (sudo)
#   max-fix.py                  -> ~/.config/openbox-nopanel/max-fix.py     (user)
#   sunvox-fix.py               -> ~/.config/openbox-nopanel/sunvox-fix.py  (user)
#   plank-kiosk/launchers/*.dockitem -> ~/.config/plank/nopanel/launchers/  (user)
#
# max-fix.py and sunvox-fix.py are NOT edited here; they are copied
# verbatim from music-kiosk-staging/ (the Max 9 / SunVox behavior is
# the same in this session).  If those scripts diverge later, edit
# the copy in music-kiosk-staging first and re-run its deploy.sh, then
# re-run this deploy.sh.
#
# Plank dockitems are also copied verbatim from music-kiosk-staging/,
# but installed under ~/.config/plank/nopanel/launchers/ rather than
# the kiosk directory.  Plank looks up `--launcher-folder $dir/launchers`
# (or the dockname-derived default ~/.config/plank/$dockname/launchers)
# for the icons; same files, different directory per session so a
# `plank -n nopanel` in this session never reads the kiosk dockitems
# the music-kiosk session owns.
#
# System paths are written via sudo (or directly if already root).

set -e

here=$(cd "$(dirname "$0")" && pwd)
kiosk_here="$here/../music-kiosk-staging"

src_sh="$here/openbox-nopanel.sh"
src_rc="$here/rc.xml"
src_menu="$here/menu.xml"
src_desktop="$here/openbox-nopanel.desktop"
src_sudoers="$here/openbox-nopanel.sudoers"
src_maxfix="$kiosk_here/max-fix.py"
src_sunvoxfix="$kiosk_here/sunvox-fix.py"
src_plank="$kiosk_here/plank-kiosk/launchers"

dst_sh=/usr/local/bin/openbox-nopanel
dst_rc="$HOME/.config/openbox-nopanel/rc.xml"
dst_menu="$HOME/.config/openbox-nopanel/menu.xml"
dst_desktop=/usr/share/xsessions/openbox-nopanel.desktop
dst_sudoers=/etc/sudoers.d/openbox-nopanel
dst_plank="$HOME/.config/plank/nopanel/launchers"

for f in "$src_sh" "$src_rc" "$src_menu" "$src_desktop" "$src_sudoers"; do
    [ -f "$f" ] || { echo "missing source: $f" >&2; exit 1; }
done
for f in "$src_maxfix" "$src_sunvoxfix"; do
    [ -f "$f" ] || { echo "missing source: $f" >&2; exit 1; }
done
[ -d "$src_plank" ] || { echo "missing source dir: $src_plank" >&2; exit 1; }

# A broken sudoers file can wedge sudo system-wide, so validate before
# install rather than trust our own syntax.
if command -v visudo >/dev/null 2>&1; then
    visudo -cf "$src_sudoers" || { echo "openbox-nopanel.sudoers failed visudo -c, not installing" >&2; exit 1; }
fi

do_install() {
    if [ "$(id -u)" -eq 0 ]; then
        install -m "$1" "$2" "$3"
    else
        sudo install -m "$1" "$2" "$3"
    fi
}

mkdir -p "$(dirname "$dst_rc")" "$dst_plank"

do_install 755 "$src_sh"             "$dst_sh"
do_install 644 "$src_rc"             "$dst_rc"
do_install 644 "$src_menu"           "$dst_menu"
do_install 644 "$src_desktop"        "$dst_desktop"
do_install 440 "$src_sudoers"        "$dst_sudoers"
do_install 755 "$src_maxfix"         "$(dirname "$dst_rc")/max-fix.py"
do_install 755 "$src_sunvoxfix"      "$(dirname "$dst_rc")/sunvox-fix.py"

# Plank dockitems go in as user files (no sudo). --target-directory keeps
# this plain-POSIX (no cp -t flag, which some platforms lack).
for item in "$src_plank"/*.dockitem; do
    [ -f "$item" ] || continue
    install -m 644 "$item" "$dst_plank/"
done

# SunVox desktop file patch: install a user-local copy of
# /usr/share/applications/sunvox.desktop with three changes:
#
#   1. StartupNotify=true (was false).  Plank / xdg-open / gtk-launch
#      use the startup-notification protocol to map a freshly-launched
#      window to its desktop file BEFORE the window appears.  With
#      false, Plank falls back to asking BAMF after the window maps,
#      and that post-hoc match is race-prone (see #3 below).  True
#      makes the match synchronous and reliable for any launch path
#      (Plank dock click, xdg-open, rofi drun, gtk-launch).
#
#   2. StartupWMClass=sunvox appended.  SunVox's WM_CLASS is
#      "sunvox" / "sunvox" (verified live with xprop) but the system
#      .desktop lacks StartupWMClass.  Plank uses StartupWMClass as a
#      secondary match key when BAMF is unavailable or returns
#      nothing, so this is a belt-and-suspenders backstop for #1.
#      Same fix was applied to renoise.desktop earlier; see
#      music-kiosk.sh line 188 for that history.
#
#   3. XDG resolves ~/.local/share/applications BEFORE
#      /usr/share/applications, so this override is what every
#      launcher (Plank, xdg-open, rofi's drun mode, gtk-launch) sees
#      for SunVox from now on.  Without it, all of them read the
#      unpatched system file.
#
# Why this matters even though the launcher subshell already waits
# for BAMF before auto-launching SunVox: that wait covers the
# initial auto-launch only.  When the user clicks SunVox in Plank
# later (or runs `sunvox` from wezterm / rofi), no wait runs --
# the same race recurs, BAMF is queried late, and Plank auto-adds
# a duplicate "running-only" icon.  StartupNotify=true eliminates
# the race for every launch path.
mkdir -p "$HOME/.local/share/applications"
sunvox_desktop="$HOME/.local/share/applications/sunvox.desktop"
sunvox_needs_install=0
if [ ! -f "$sunvox_desktop" ]; then
    sunvox_needs_install=1
elif ! grep -q '^StartupWMClass=sunvox$' "$sunvox_desktop" 2>/dev/null \
   || grep -q '^StartupNotify=false' "$sunvox_desktop" 2>/dev/null; then
    sunvox_needs_install=1
fi
if [ "$sunvox_needs_install" = "1" ]; then
    if [ -f /usr/share/applications/sunvox.desktop ]; then
        awk '
            /^StartupNotify=false/ { print "StartupNotify=true"; print "StartupWMClass=sunvox"; next }
            /^StartupNotify=true/ { print; print "StartupWMClass=sunvox"; next }
            /^StartupNotify=/ { print; print "StartupWMClass=sunvox"; next }
            { print }
        ' /usr/share/applications/sunvox.desktop > "$sunvox_desktop.tmp"
        mv "$sunvox_desktop.tmp" "$sunvox_desktop"
        chmod 644 "$sunvox_desktop"
        printf 'installed:\n  %s -> %s (user .desktop override with StartupNotify=true, StartupWMClass=sunvox)\n' \
            /usr/share/applications/sunvox.desktop "$sunvox_desktop"

        # bamfdaemon caches its desktop-file index in memory.  A
        # deploy that patches sunvox.desktop (or any other file with
        # a StartupWMClass line) won't be picked up until bamfdaemon
        # respawns.  Killing it here is safe -- it's a dbus
        # activated service that re-launches on demand (plank /
        # xdg-open / any client triggering it triggers the respawn).
        # No-op if bamfdaemon isn't running (e.g. running this
        # deploy from outside an X session).  Skip under
        # `set -e`/non-interactive shells where the user's
        # environment may not have a dbus session.
        if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && pgrep -x bamfdaemon >/dev/null 2>&1; then
            pkill -x bamfdaemon 2>/dev/null || true
            printf 'restarted bamfdaemon (it was holding a stale desktop-file cache)\n'
        fi
    fi
fi

printf 'installed:\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s/*.dockitem -> %s\n' \
    "$src_sh"             "$dst_sh" \
    "$src_rc"             "$dst_rc" \
    "$src_menu"           "$dst_menu" \
    "$src_desktop"        "$dst_desktop" \
    "$src_sudoers"        "$dst_sudoers" \
    "$src_maxfix"         "$(dirname "$dst_rc")/max-fix.py" \
    "$src_sunvoxfix"      "$(dirname "$dst_rc")/sunvox-fix.py" \
    "$src_plank"          "$dst_plank"