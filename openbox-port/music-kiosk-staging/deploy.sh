#!/bin/sh
# deploy.sh - install Music Kiosk files from staging to system locations.
#
#   music-kiosk.sh        -> /usr/local/bin/music-kiosk                    (sudo)
#   rc.xml                -> ~/.config/openbox-music-kiosk/rc.xml           (user)
#   music-kiosk.desktop   -> /usr/share/xsessions/music-kiosk.desktop      (sudo)
#   music-kiosk.sudoers   -> /etc/sudoers.d/music-kiosk                    (sudo)
#   plank-kiosk/launchers -> ~/.config/plank/kiosk/launchers               (user)
#
# System paths are written via sudo (or directly if already root).

set -e

here=$(cd "$(dirname "$0")" && pwd)

src_sh="$here/music-kiosk.sh"
src_rc="$here/rc.xml"
src_desktop="$here/music-kiosk.desktop"
src_sudoers="$here/music-kiosk.sudoers"
src_plank="$here/plank-kiosk/launchers"

dst_sh=/usr/local/bin/music-kiosk
dst_rc="$HOME/.config/openbox-music-kiosk/rc.xml"
dst_desktop=/usr/share/xsessions/music-kiosk.desktop
dst_sudoers=/etc/sudoers.d/music-kiosk
dst_plank="$HOME/.config/plank/kiosk/launchers"

for f in "$src_sh" "$src_rc" "$src_desktop" "$src_sudoers"; do
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

mkdir -p "$(dirname "$dst_rc")" "$dst_plank"

do_install 755 "$src_sh"       "$dst_sh"
do_install 644 "$src_rc"       "$dst_rc"
do_install 644 "$src_desktop"  "$dst_desktop"
do_install 440 "$src_sudoers"  "$dst_sudoers"

# Plank dockitems go in as user files (no sudo). --target-directory keeps
# this plain-POSIX (no cp -t flag, which some platforms lack).
for item in "$src_plank"/*.dockitem; do
    [ -f "$item" ] || continue
    install -m 644 "$item" "$dst_plank/"
done

printf 'installed:\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s/*.dockitem -> %s\n' \
    "$src_sh"       "$dst_sh" \
    "$src_rc"       "$dst_rc" \
    "$src_desktop"  "$dst_desktop" \
    "$src_sudoers"  "$dst_sudoers" \
    "$src_plank"    "$dst_plank"
