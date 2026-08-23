#!/bin/sh
# deploy.sh - install Renoise kiosk files from staging to system locations.
#
#   renoise-kiosk.sh       -> /usr/local/bin/renoise-kiosk            (sudo)
#   rc.xml                 -> ~/.config/openbox-renoise/rc.xml         (user)
#   renoise-kiosk.desktop  -> /usr/share/xsessions/renoise-kiosk.desktop (sudo)
#   renoise-kiosk.sudoers  -> /etc/sudoers.d/renoise-kiosk             (sudo)
#
# System paths are written via sudo (or directly if already root).

set -e

here=$(cd "$(dirname "$0")" && pwd)

src_sh="$here/renoise-kiosk.sh"
src_rc="$here/rc.xml"
src_desktop="$here/renoise-kiosk.desktop"
src_sudoers="$here/renoise-kiosk.sudoers"

dst_sh=/usr/local/bin/renoise-kiosk
dst_rc="$HOME/.config/openbox-renoise/rc.xml"
dst_desktop=/usr/share/xsessions/renoise-kiosk.desktop
dst_sudoers=/etc/sudoers.d/renoise-kiosk

for f in "$src_sh" "$src_rc" "$src_desktop" "$src_sudoers"; do
    [ -f "$f" ] || { echo "missing source: $f" >&2; exit 1; }
done

# A broken sudoers file can wedge sudo system-wide, so validate before
# install rather than trust our own syntax.
if command -v visudo >/dev/null 2>&1; then
    visudo -cf "$src_sudoers" || { echo "renoise-kiosk.sudoers failed visudo -c, not installing" >&2; exit 1; }
fi

do_install() {
    if [ "$(id -u)" -eq 0 ]; then
        install -m "$1" "$2" "$3"
    else
        sudo install -m "$1" "$2" "$3"
    fi
}

mkdir -p "$(dirname "$dst_rc")"

do_install 755 "$src_sh"       "$dst_sh"
do_install 644 "$src_rc"       "$dst_rc"
do_install 644 "$src_desktop"  "$dst_desktop"
do_install 440 "$src_sudoers"  "$dst_sudoers"

printf 'installed:\n  %s -> %s\n  %s -> %s\n  %s -> %s\n  %s -> %s\n' \
    "$src_sh"      "$dst_sh" \
    "$src_rc"      "$dst_rc" \
    "$src_desktop" "$dst_desktop" \
    "$src_sudoers" "$dst_sudoers"
