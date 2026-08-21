#!/bin/sh
# tint2 workspace switcher
#   show <index>  pango label for workspace index (0-based)
#   goto <index>  switch to that workspace
#   delta <n>     move n workspaces, wrapping

set -eu

desktops() {
  wmctrl -d 2>/dev/null
}

pango_escape() {
  printf '%s' "$1" | sed 's/&/\&amp;/g; s/</\&lt;/g; s/>/\&gt;/g'
}

cmd=${1:-}
idx=${2:-0}

case "$cmd" in
  show)
    line=$(desktops | awk -v idx="$idx" '$1 == idx { print; exit }')
    if [ -z "$line" ]; then
      exit 0
    fi
    current=$(printf '%s\n' "$line" | awk '{ print $2 }')
    name=$(printf '%s\n' "$line" | awk -v idx="$idx" '{
      if (match($0, /WA: [^ ]+ [0-9]+x[0-9]+[ \t]+/))
        print substr($0, RSTART + RLENGTH)
      else
        print idx + 1
    }')
    name=$(pango_escape "$name")
    if [ "$current" = "*" ]; then
      printf '<span foreground="#eeeeee" font_weight="bold">%s</span>\n' "$name"
    else
      printf '<span foreground="#888888">%s</span>\n' "$name"
    fi
    ;;
  goto)
    wmctrl -s "$idx"
    ;;
  delta)
    cur=$(desktops | awk '$2 == "*" { print $1; exit }')
    n=$(desktops | awk 'END { print NR }')
    cur=${cur:-0}
    n=${n:-1}
    [ "$n" -gt 0 ] || n=1
    wmctrl -s $(( (cur + idx % n + n) % n ))
    ;;
  *)
    echo "usage: $0 show|goto|delta <index>" >&2
    exit 2
    ;;
esac
