#!/usr/bin/env python3
"""Keep Audacious Winamp-skin windows stacked after Fluxbox remap.

The skins UI is three windows (main, equalizer, playlist). Equalizer and
playlist are transients of main and advertise PPosition 0,0. After a Fluxbox
restart or a suspend/resume remap, Fluxbox places those transients on top of
the player so the three windows coincide. If they overlap, put the equalizer
directly under the main window and the playlist under the equalizer.
"""
from __future__ import annotations

import sys
import time

from Xlib import X, Xatom, display, error
from Xlib.ext import randr

ROLES = ("mainwindow", "equalizer", "playlist")
OVERLAP_PX = 40
DEBOUNCE = 0.2
POLL = 2.0


def intern(d, name):
    return d.intern_atom(name)


def iter_clients(d):
    root = d.screen().root
    try:
        frames = root.query_tree().children
    except error.BadWindow:
        return
    for frame in frames:
        yield frame
        try:
            for child in frame.query_tree().children:
                yield child
        except (error.BadWindow, error.BadDrawable):
            continue


def wm_class(win):
    try:
        cls = win.get_wm_class()
    except (error.BadWindow, error.BadDrawable):
        return []
    return [c.lower() for c in cls] if cls else []


def wm_role(d, win, atom_role):
    try:
        prop = win.get_full_property(atom_role, Xatom.STRING)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return ""
    if not prop or not prop.value:
        return ""
    val = prop.value
    if isinstance(val, bytes):
        return val.decode("utf-8", "replace")
    return str(val)


def toplevel(d, win):
    """Fluxbox frame if the client is reparented, else the window itself."""
    root_id = d.screen().root.id
    cur = win
    top = win
    try:
        parent = win.query_tree().parent
        while parent is not None and parent.id != root_id:
            top = parent
            cur = parent
            parent = cur.query_tree().parent
    except (error.BadWindow, error.BadDrawable):
        return win
    return top


def abs_geom(d, win):
    g = win.get_geometry()
    try:
        mapped = win.get_attributes().map_state == X.IsViewable
    except (error.BadWindow, error.BadDrawable):
        mapped = False
    try:
        t = d.screen().root.translate_coords(win, 0, 0)
        x, y = int(t.x), int(t.y)
    except (error.BadWindow, error.BadDrawable):
        x, y = int(g.x), int(g.y)
    return {
        "id": win.id,
        "win": win,
        "x": x,
        "y": y,
        "w": int(g.width),
        "h": int(g.height),
        "mapped": mapped,
    }


def overlap_area(a, b):
    dx = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
    dy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
    if dx <= 0 or dy <= 0:
        return 0
    return dx * dy


def find_skin_windows(d, atom_role):
    found = {}
    seen = set()
    for win in iter_clients(d):
        if win.id in seen:
            continue
        seen.add(win.id)
        if "audacious" not in wm_class(win):
            continue
        role = wm_role(d, win, atom_role)
        if role not in ROLES or role in found:
            continue
        found[role] = abs_geom(d, toplevel(d, win))
    return found


def monitors(d):
    root = d.screen().root
    try:
        info = randr.get_monitors(root, True)
    except Exception:
        g = root.get_geometry()
        return [{"x": 0, "y": 0, "w": int(g.width), "h": int(g.height)}]
    out = []
    for m in info.monitors:
        out.append(
            {
                "x": int(m.x),
                "y": int(m.y),
                "w": int(m.width_in_pixels),
                "h": int(m.height_in_pixels),
            }
        )
    return out or [{"x": 0, "y": 0, "w": 1920, "h": 1080}]


def clamp_to_monitor(x, y, w, h, mon):
    max_x = mon["x"] + mon["w"] - w
    max_y = mon["y"] + mon["h"] - h
    x = min(max(x, mon["x"]), max(mon["x"], max_x))
    y = min(max(y, mon["y"]), max(mon["y"], max_y))
    return x, y


def monitor_for(x, y, mons):
    for m in mons:
        if m["x"] <= x < m["x"] + m["w"] and m["y"] <= y < m["y"] + m["h"]:
            return m
    return mons[0]


def needs_stack(wins):
    vis = [wins[r] for r in ROLES if r in wins]
    if len(vis) < 2:
        return False
    for i, a in enumerate(vis):
        for b in vis[i + 1 :]:
            if overlap_area(a, b) >= OVERLAP_PX:
                return True
    return False


def move(d, geom, x, y):
    if geom["x"] == x and geom["y"] == y:
        return
    try:
        geom["win"].configure(x=int(x), y=int(y))
    except (error.BadWindow, error.BadDrawable):
        return


def stack(d, atom_role):
    wins = find_skin_windows(d, atom_role)
    main = wins.get("mainwindow")
    if not main:
        return False
    if not needs_stack(wins):
        return False

    mons = monitors(d)
    mon = monitor_for(main["x"], main["y"], mons)
    x = main["x"]
    y = main["y"] + main["h"]

    eq = wins.get("equalizer")
    if eq:
        ex, ey = clamp_to_monitor(x, y, eq["w"], eq["h"], mon)
        move(d, eq, ex, ey)
        y = ey + eq["h"]

    pl = wins.get("playlist")
    if pl:
        px, py = clamp_to_monitor(x, y, pl["w"], pl["h"], mon)
        move(d, pl, px, py)

    d.sync()
    return True


def main(argv):
    once = "--once" in argv
    d = display.Display()
    atom_role = intern(d, "WM_WINDOW_ROLE")
    stack(d, atom_role)
    if once:
        return

    root = d.screen().root
    root.change_attributes(
        event_mask=X.SubstructureNotifyMask | X.PropertyChangeMask
    )
    if d.has_extension("RANDR"):
        randr.select_input(root, randr.RRScreenChangeNotifyMask)

    pending = False
    due = 0.0
    next_poll = time.monotonic() + POLL

    while True:
        now = time.monotonic()
        if d.pending_events():
            ev = d.next_event()
            et = getattr(ev, "type", None)
            if et in (X.MapNotify, X.ConfigureNotify, X.UnmapNotify) or et not in (
                X.PropertyNotify,
                X.ClientMessage,
            ):
                pending = True
                due = now + DEBOUNCE
        else:
            time.sleep(0.05)

        now = time.monotonic()
        if pending and now >= due:
            pending = False
            stack(d, atom_role)
            next_poll = now + POLL
        elif now >= next_poll:
            stack(d, atom_role)
            next_poll = now + POLL


if __name__ == "__main__":
    main(sys.argv)
