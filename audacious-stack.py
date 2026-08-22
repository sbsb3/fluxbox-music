#!/usr/bin/env python3
"""Keep Audacious Winamp-skin windows stacked after Fluxbox remap.

The skins UI is three windows (main, equalizer, playlist). Equalizer and
playlist are transients of main and advertise PPosition 0,0. After a Fluxbox
restart or a suspend/resume remap, Fluxbox places those transients on top of
the player so the three windows coincide. If they overlap, put the equalizer
directly under the main window and the playlist under the equalizer.

When /dev/shm/fluxbox-audacious-follow-<uid> exists, every Audacious client
(Winamp skin and dockable plugin windows such as Waveform Seekbar) is made
sticky so it stays mapped on every workspace. Sending _NET_WM_DESKTOP instead
iconifies a maximized plugin window on a secondary head: Fluxbox unmaps it
for the desktop change and never remaps it. After a switch we also deiconify
leftovers and restore maximize if the frame still fills a monitor.
"""
from __future__ import annotations

import os
import sys
import time

from Xlib import X, Xatom, display, error
from Xlib.ext import randr
from Xlib.protocol import event

ROLES = ("mainwindow", "equalizer", "playlist")
OVERLAP_PX = 40
DEBOUNCE = 0.2
FOLLOW_DEBOUNCE = 0.05
FOLLOW_RESTORE = 0.12
POLL = 2.0
ALL_DESKTOPS = 0xFFFFFFFF
NET_WM_STATE_REMOVE = 0
NET_WM_STATE_ADD = 1
NormalState = 1
IconicState = 3
FOLLOW_FLAG = "/dev/shm/fluxbox-audacious-follow-" + str(os.getuid())
# Previous toggle wrote this; still honor it so an already-on flag keeps working.
LEGACY_PARK_FLAG = "/dev/shm/fluxbox-audacious-park-" + str(os.getuid())


def intern(d, name):
    return d.intern_atom(name)


def desktop_atoms(d):
    return {
        "cur": intern(d, "_NET_CURRENT_DESKTOP"),
        "n": intern(d, "_NET_NUMBER_OF_DESKTOPS"),
        "desk": intern(d, "_NET_WM_DESKTOP"),
        "list": intern(d, "_NET_CLIENT_LIST"),
        "state": intern(d, "_NET_WM_STATE"),
        "hidden": intern(d, "_NET_WM_STATE_HIDDEN"),
        "sticky": intern(d, "_NET_WM_STATE_STICKY"),
        "maxv": intern(d, "_NET_WM_STATE_MAXIMIZED_VERT"),
        "maxh": intern(d, "_NET_WM_STATE_MAXIMIZED_HORZ"),
        "wm_state": intern(d, "WM_STATE"),
        "wm_change": intern(d, "WM_CHANGE_STATE"),
    }


def follow_on():
    try:
        return os.path.exists(FOLLOW_FLAG) or os.path.exists(LEGACY_PARK_FLAG)
    except OSError:
        return False


def card32(win, atom):
    try:
        prop = win.get_full_property(atom, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return None
    if not prop or not prop.value:
        return None
    return int(prop.value[0])


def net_clients(d, atom_list):
    root = d.screen().root
    try:
        prop = root.get_full_property(atom_list, X.AnyPropertyType)
    except (error.BadWindow, error.BadAtom):
        return
    if not prop or not prop.value:
        return
    for wid in prop.value:
        yield d.create_resource_object("window", int(wid))


def audacious_clients(d, atom_list):
    found = []
    seen = set()
    for win in net_clients(d, atom_list):
        if win.id in seen:
            continue
        seen.add(win.id)
        if "audacious" in wm_class(win):
            found.append(win)
    return found


def send_client(d, win, atom, payload):
    data = list(payload) + [0] * (5 - len(payload))
    ev = event.ClientMessage(
        window=win,
        client_type=atom,
        data=(32, data),
    )
    mask = X.SubstructureNotifyMask | X.SubstructureRedirectMask
    try:
        d.send_event(d.screen().root, ev, event_mask=mask)
    except (error.BadWindow, error.BadDrawable):
        return


def send_to_desktop(d, win, desk, atom_desk):
    send_client(d, win, atom_desk, [int(desk), 2, 0, 0, 0])


def send_state(d, win, atoms, action, atom1, atom2=0):
    send_client(d, win, atoms["state"], [int(action), int(atom1), int(atom2), 2, 0])


def net_state(win, atom_state):
    try:
        prop = win.get_full_property(atom_state, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return set()
    if not prop or not prop.value:
        return set()
    return {int(v) for v in prop.value}


def is_sticky(win, atoms):
    if atoms["sticky"] in net_state(win, atoms["state"]):
        return True
    return card32(win, atoms["desk"]) == ALL_DESKTOPS


def is_iconic(win, atoms):
    if atoms["hidden"] in net_state(win, atoms["state"]):
        return True
    return card32(win, atoms["wm_state"]) == IconicState


def is_maxed(win, atoms):
    st = net_state(win, atoms["state"])
    return atoms["maxv"] in st and atoms["maxh"] in st


def fills_a_monitor(d, win):
    """True if the Fluxbox frame covers a whole RandR head (the seekbar on HDMI)."""
    try:
        g = abs_geom(d, toplevel(d, win))
    except (error.BadWindow, error.BadDrawable):
        return False
    for m in monitors(d):
        if abs(g["x"] - m["x"]) > 12 or abs(g["y"] - m["y"]) > 12:
            continue
        if abs(g["w"] - m["w"]) <= 24 and abs(g["h"] - m["h"]) <= 24:
            return True
    return False


def set_sticky(d, win, atoms, on):
    if on:
        if not is_sticky(win, atoms):
            send_state(d, win, atoms, NET_WM_STATE_ADD, atoms["sticky"])
    else:
        if is_sticky(win, atoms):
            send_state(d, win, atoms, NET_WM_STATE_REMOVE, atoms["sticky"])
            cur = card32(d.screen().root, atoms["cur"])
            if cur is not None:
                send_to_desktop(d, win, cur, atoms["desk"])


def deiconify(d, win, atoms):
    """Force Fluxbox to remap an iconic client.

    MapRequest is ignored for an iconic window that is also sticky and
    maximized (the Waveform Seekbar on HDMI-0). Dropping STICKY and
    sending it to the current desk is what actually maps it again.
    """
    if is_sticky(win, atoms):
        send_state(d, win, atoms, NET_WM_STATE_REMOVE, atoms["sticky"])
    cur = card32(d.screen().root, atoms["cur"])
    if cur is not None:
        send_to_desktop(d, win, cur, atoms["desk"])
    send_client(d, win, atoms["wm_change"], [NormalState, 0, 0, 0, 0])
    send_state(d, win, atoms, NET_WM_STATE_REMOVE, atoms["hidden"])
    try:
        win.map()
    except (error.BadWindow, error.BadDrawable):
        pass


def maximize(d, win, atoms):
    send_state(d, win, atoms, NET_WM_STATE_ADD, atoms["maxv"], atoms["maxh"])


# Window ids that should be re-maximized on the next restore pass (after map).
_maximize_after = set()


def apply_follow(d, atoms, restore=False):
    """Keep Audacious sticky while follow is on; restore map/maximize after a switch.

    restore=True after a workspace change or the menu toggle: deiconify first
    (without sticky), then on the next pass add sticky and restore maximize.
    Adding sticky while iconic is a no-op, which is why the seekbar used to
    stay minimized. The 2s poll only keeps sticky in sync so a user iconify
    is not fought every tick.
    Returns True if a second restore pass should run after Fluxbox settles.
    """
    on = follow_on()
    need_again = False
    live = set()
    for win in audacious_clients(d, atoms["list"]):
        live.add(win.id)
        if not on:
            set_sticky(d, win, atoms, False)
            _maximize_after.discard(win.id)
            continue
        if restore and is_iconic(win, atoms):
            if is_maxed(win, atoms) or fills_a_monitor(d, win):
                _maximize_after.add(win.id)
            deiconify(d, win, atoms)
            need_again = True
            continue
        set_sticky(d, win, atoms, True)
        if restore and win.id in _maximize_after:
            _maximize_after.discard(win.id)
            maximize(d, win, atoms)
    _maximize_after.intersection_update(live)
    d.flush()
    return need_again


def apply_follow_settled(d, atoms):
    """Two-pass restore so Fluxbox can remap before we re-maximize."""
    need = apply_follow(d, atoms, restore=True)
    if not need:
        return
    d.sync()
    time.sleep(FOLLOW_RESTORE)
    apply_follow(d, atoms, restore=True)


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
    apply_only = "--apply-follow" in argv or "--apply-park" in argv
    d = display.Display()
    atom_role = intern(d, "WM_WINDOW_ROLE")
    atoms = desktop_atoms(d)
    if apply_only:
        apply_follow_settled(d, atoms)
        return

    stack(d, atom_role)
    apply_follow_settled(d, atoms)
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
    pending_follow = False
    follow_due = 0.0
    follow_restore = False
    next_poll = time.monotonic() + POLL
    atom_cur = atoms["cur"]

    while True:
        now = time.monotonic()
        if d.pending_events():
            ev = d.next_event()
            et = getattr(ev, "type", None)
            if et == X.PropertyNotify and getattr(ev, "atom", None) == atom_cur:
                pending_follow = True
                follow_restore = True
                follow_due = now + FOLLOW_DEBOUNCE
            if et in (X.MapNotify, X.ConfigureNotify, X.UnmapNotify) or et not in (
                X.PropertyNotify,
                X.ClientMessage,
            ):
                pending = True
                due = now + DEBOUNCE
                if et == X.MapNotify:
                    pending_follow = True
                    follow_restore = True
                    follow_due = now + DEBOUNCE
        else:
            time.sleep(0.05)

        now = time.monotonic()
        if pending_follow and now >= follow_due:
            pending_follow = False
            restore = follow_restore
            follow_restore = False
            if apply_follow(d, atoms, restore=restore) and restore:
                pending_follow = True
                follow_restore = True
                follow_due = now + FOLLOW_RESTORE
        if pending and now >= due:
            pending = False
            stack(d, atom_role)
            next_poll = now + POLL
        elif now >= next_poll:
            stack(d, atom_role)
            apply_follow(d, atoms, restore=False)
            next_poll = now + POLL


if __name__ == "__main__":
    main(sys.argv)
