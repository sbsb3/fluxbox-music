#!/bin/sh
# deploy.sh - install Music Kiosk files from staging to system locations.
#
#   music-kiosk.sh        -> /usr/local/bin/music-kiosk                    (sudo)
#   rc.xml                -> ~/.config/openbox-music-kiosk/rc.xml           (user)
#   music-kiosk.desktop   -> /usr/share/xsessions/music-kiosk.desktop      (sudo)
#   music-kiosk.sudoers   -> /etc/sudoers.d/music-kiosk                    (sudo)
#   music-kiosk-logout.sh -> /usr/local/bin/music-kiosk-logout             (sudo)
#   music-kiosk-logout.desktop -> ~/.local/share/applications/             (user)
#   plank-kiosk/launchers -> ~/.config/plank/kiosk/launchers               (user)
#   max-fix.py            -> ~/.config/openbox-music-kiosk/max-fix.py       (user)
#   sunvox-fix.py         -> ~/.config/openbox-music-kiosk/sunvox-fix.py    (user)
#
# System paths are written via sudo (or directly if already root).

set -e

here=$(cd "$(dirname "$0")" && pwd)

src_sh="$here/music-kiosk.sh"
src_rc="$here/rc.xml"
src_desktop="$here/music-kiosk.desktop"
src_sudoers="$here/music-kiosk.sudoers"
src_logout_sh="$here/music-kiosk-logout.sh"
src_logout_desktop="$here/music-kiosk-logout.desktop"
src_plank="$here/plank-kiosk/launchers"
src_maxfix="$here/max-fix.py"
src_sunvoxfix="$here/sunvox-fix.py"

dst_sh=/usr/local/bin/music-kiosk
dst_rc="$HOME/.config/openbox-music-kiosk/rc.xml"
dst_desktop=/usr/share/xsessions/music-kiosk.desktop
dst_sudoers=/etc/sudoers.d/music-kiosk
dst_logout_sh=/usr/local/bin/music-kiosk-logout
dst_logout_desktop="$HOME/.local/share/applications/music-kiosk-logout.desktop"
dst_plank="$HOME/.config/plank/kiosk/launchers"

for f in "$src_sh" "$src_rc" "$src_desktop" "$src_sudoers" "$src_logout_sh" "$src_logout_desktop" "$src_maxfix" "$src_sunvoxfix"; do
    [ -f "$f" ] || { echo "missing source: $f" >&2; exit 1; }
done
[ -d "$src_plank" ] || { echo "missing source dir: $src_plank" >&2; exit 1; }

# A broken sudoers file can wedge sudo system-wide, so validate before
# install rather than trust our own syntax.
if command -v visudo >/dev/null 2>&1; then
    visudo -cf "$src_sudoers" || { echo "music-kiosk.sudoers failed visudo -c, not installing" >&2; exit 1; }
fi

do_install() {
    if [ "$(id -u)" -eq 0 ]; then
        install -m "$1" "$2" "$3"
    else
        sudo install -m "$1" "$2" "$3"
    fi
}

mkdir -p "$(dirname "$dst_rc")" "$dst_plank" "$(dirname "$dst_logout_desktop")"

do_install 755 "$src_sh"              "$dst_sh"
do_install 644 "$src_rc"              "$dst_rc"
do_install 644 "$src_desktop"         "$dst_desktop"
do_install 440 "$src_sudoers"         "$dst_sudoers"
do_install 755 "$src_logout_sh"       "$dst_logout_sh"
do_install 644 "$src_logout_desktop"  "$dst_logout_desktop"
do_install 755 "$src_maxfix"          "$(dirname "$dst_rc")/max-fix.py"
do_install 755 "$src_sunvoxfix"       "$(dirname "$dst_rc")/sunvox-fix.py"

# Plank dockitems go in as user files (no sudo). --target-directory keeps
# this plain-POSIX (no cp -t flag, which some platforms lack).
for item in "$src_plank"/*.dockitem; do
    [ -f "$item" ] || continue
    install -m 644 "$item" "$dst_plank/"
done

# SunVox desktop file patch: install a user-local copy of
# /usr/share/applications/sunvox.desktop with StartupWMClass=sunvox
# appended.  SunVox's WM_CLASS is "sunvox"/"sunvox" (verified live with
# xprop) but the system .desktop lacks StartupWMClass, so Plank can't
# associate the running window to the pinned SunVox dockitem -- it
# falls back to matching by `Exec=sunvox` against the running process
# list and ends up showing a SECOND "running" icon next to the pinned
# one.  XDG resolves ~/.local/share/applications before
# /usr/share/applications, so this override is what every launcher
# (Plank, xdg-open, rofi's drun mode) sees for SunVox from now on.
# Same problem affected Renoise until StartupWMClass=Renoise was
# added to its .desktop.
mkdir -p "$HOME/.local/share/applications"
sunvox_desktop="$HOME/.local/share/applications/sunvox.desktop"
if [ ! -f "$sunvox_desktop" ] || ! grep -q '^StartupWMClass=sunvox$' "$sunvox_desktop" 2>/dev/null; then
    if [ -f /usr/share/applications/sunvox.desktop ]; then
        awk '
            /^StartupNotify=/ { print; print "StartupWMClass=sunvox"; next }
            { print }
        ' /usr/share/applications/sunvox.desktop > "$sunvox_desktop.tmp"
        mv "$sunvox_desktop.tmp" "$sunvox_desktop"
        chmod 644 "$sunvox_desktop"
        printf 'installed:\n  %s -> %s (user .desktop override with StartupWMClass=sunvox)\n' \
            /usr/share/applications/sunvox.desktop "$sunvox_desktop"

        # bamfdaemon caches its desktop-file index in memory.  A
        # deploy that patches sunvox.desktop (or any other file with
        # a StartupWMClass line) won't be picked up until bamfdaemon
        # respawns.  Killing it here is safe -- it's a dbus
        # activated service that re-launches on demand (plank /
        # xdg-open / any client triggering it triggers the respawn).
        # No-op if bamfdaemon isn't running (e.g. running this
        # deploy from outside an X session).
        if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ] && pgrep -x bamfdaemon >/dev/null 2>&1; then
            pkill -x bamfdaemon 2>/dev/null || true
            printf 'restarted bamfdaemon (it was holding a stale desktop-file cache)\n'
        fi
    fi
fi

printf 'installed:\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s/*.dockitem -> %s\n' \
    "$src_sh"              "$dst_sh" \
    "$src_rc"              "$dst_rc" \
    "$src_desktop"         "$dst_desktop" \
    "$src_sudoers"         "$dst_sudoers" \
    "$src_logout_sh"       "$dst_logout_sh" \
    "$src_logout_desktop"  "$dst_logout_desktop" \
    "$src_plank"           "$dst_plank"
