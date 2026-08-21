#!/usr/bin/env python3
"""Keep pcmanfm desktops and GTK per-monitor workareas in sync with RandR.

pcmanfm creates one desktop window per monitor only at startup, and never
adds a window if a head appears later. GTK's primary workarea is
_NET_WORKAREA intersected with that head. On this L-shaped layout the
panel sits at the top of the primary (y=342), while Fluxbox publishes a
56px top inset from the virtual origin (y=0), so:

  * the portrait head can end up with no desktop (no icons, no menu)
  * icons on the primary start under tint2

Advertise _GTK_WORKAREAS (the per-monitor list GTK actually uses) and
rebuild the pcmanfm desktop whenever the head count or the published
rects change -- pcmanfm samples its working area once per desktop window
and afterwards only listens for _NET_WORKAREA, which never moves here.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import traceback

from Xlib import X, Xatom, display, error
from Xlib.ext import randr

PROFILE = "fluxbox-music"
# Fallback top inset for the primary when tint2 is not up yet (startup runs
# us once before the panel exists). Keyed by panel-size.sh's profile file so
# the desktop pcmanfm builds at startup matches the panel about to appear.
PANEL_TOP = {"compact": 30, "normal": 56}
DEFAULT_PRIMARY_TOP = PANEL_TOP["normal"]
PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "panel-profile")
RESTART_COOLDOWN = 5.0


def intern(d, name):
    return d.intern_atom(name)


def default_primary_top():
    try:
        with open(PROFILE_FILE) as f:
            return PANEL_TOP[f.readline().strip()]
    except (OSError, KeyError):
        return DEFAULT_PRIMARY_TOP


def monitors(d):
    root = d.screen().root
    try:
        info = randr.get_monitors(root, True)
    except (error.Error, AttributeError, Exception):
        return []
    out = []
    for m in info.monitors:
        out.append(
            {
                "x": int(m.x),
                "y": int(m.y),
                "w": int(m.width_in_pixels),
                "h": int(m.height_in_pixels),
                "primary": bool(m.primary),
            }
        )
    return out


def abs_geom(d, win):
    g = win.get_geometry()
    try:
        t = d.screen().root.translate_coords(win, 0, 0)
        return int(t.x), int(t.y), int(g.width), int(g.height)
    except (error.BadWindow, error.BadDrawable):
        return int(g.x), int(g.y), int(g.width), int(g.height)


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


def window_class(win):
    try:
        cls = win.get_wm_class()
    except (error.BadWindow, error.BadDrawable):
        return []
    return [c.lower() for c in cls] if cls else []


def is_type(win, atom_type, atom):
    try:
        prop = win.get_full_property(atom_type, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return False
    return bool(prop) and atom in prop.value


def tint2_top_inset(d, atom_type, atom_dock, mon):
    """Pixels to skip at the top of *mon* if tint2 sits on that edge."""
    for win in iter_clients(d):
        if "tint2" not in window_class(win):
            continue
        if not is_type(win, atom_type, atom_dock):
            continue
        x, y, w, h = abs_geom(d, win)
        if h <= 0 or h > 200:
            continue
        # Same head, hugging the top edge.
        if y > mon["y"] + 8:
            continue
        if x + w <= mon["x"] or x >= mon["x"] + mon["w"]:
            continue
        return max(0, (y + h) - mon["y"])
    return 0


def workareas(d, atom_type, atom_dock, heads):
    rects = []
    for mon in heads:
        x, y, w, h = mon["x"], mon["y"], mon["w"], mon["h"]
        top = tint2_top_inset(d, atom_type, atom_dock, mon)
        if top == 0 and mon["primary"]:
            top = default_primary_top()
        y += top
        h = max(1, h - top)
        rects.extend([x, y, w, h])
    return rects


def n_desktops(d, atom_nd):
    try:
        prop = d.screen().root.get_full_property(atom_nd, X.AnyPropertyType)
        if prop and prop.value:
            return max(1, int(prop.value[0]))
    except (error.BadWindow, error.BadAtom):
        pass
    return 4


def count_desktop_windows(d, atom_type, atom_desktop):
    n = 0
    seen = set()
    for win in iter_clients(d):
        if win.id in seen:
            continue
        seen.add(win.id)
        if is_type(win, atom_type, atom_desktop):
            n += 1
    return n


def ensure_gtk_workareas_hint(d, atom_supported, atom_gtk):
    root = d.screen().root
    try:
        prop = root.get_full_property(atom_supported, Xatom.ATOM)
    except (error.BadWindow, error.BadAtom):
        return
    values = list(prop.value) if prop else []
    if atom_gtk in values:
        return
    root.change_property(atom_supported, Xatom.ATOM, 32, values + [atom_gtk])


def publish_workareas(d, atom_type, atom_dock, atom_nd, atom_supported, atom_gtk):
    heads = monitors(d)
    if not heads:
        return heads, []
    ensure_gtk_workareas_hint(d, atom_supported, atom_gtk)
    rects = workareas(d, atom_type, atom_dock, heads)
    nd = n_desktops(d, atom_nd)
    root = d.screen().root
    for i in range(nd):
        atom = intern(d, f"_GTK_WORKAREAS_D{i}")
        root.change_property(atom, Xatom.CARDINAL, 32, rects)
    d.sync()
    return heads, rects


def restart_pcmanfm_desktop():
    env = os.environ.copy()
    # --profile matters: pcmanfm's single-instance socket is per profile, so a
    # bare --desktop-off talks to (and spawns) a default-profile daemon and
    # leaves this session's desktop running. Time it out too -- when no daemon
    # answers, pcmanfm can sit there being one.
    try:
        subprocess.run(
            ["pcmanfm", "--desktop-off", "--profile", PROFILE],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    time.sleep(0.4)
    subprocess.Popen(
        ["pcmanfm", "--desktop", "--profile", PROFILE],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def apply(d, atoms, last_restart, force_restart=False):
    heads, rects = publish_workareas(
        d,
        atoms["type"],
        atoms["dock"],
        atoms["nd"],
        atoms["supported"],
        atoms["gtk"],
    )
    n_heads = len(heads)
    n_desk = count_desktop_windows(d, atoms["type"], atoms["desktop"])
    now = time.monotonic()
    need = force_restart or (n_heads > 0 and n_desk != n_heads)
    if need and (now - last_restart) >= RESTART_COOLDOWN:
        restart_pcmanfm_desktop()
        last_restart = now
    return heads, rects, n_desk, last_restart


def wait_heads_stable(d, timeout=5.0):
    deadline = time.monotonic() + timeout
    last = None
    stable_since = time.monotonic()
    while time.monotonic() < deadline:
        cur = [(m["x"], m["y"], m["w"], m["h"], m["primary"]) for m in monitors(d)]
        if cur and cur == last and time.monotonic() - stable_since >= 0.4:
            return cur
        if cur != last:
            last = cur
            stable_since = time.monotonic()
        time.sleep(0.15)
    return last or []


def heads_sig(heads, rects):
    return (
        tuple((h["x"], h["y"], h["w"], h["h"], h["primary"]) for h in heads),
        tuple(rects),
    )


def main(argv):
    once = "--once" in argv
    # --resync also rebuilds the desktop, for callers that changed the panel
    # height and cannot wait for (or do not have) the watcher.
    resync = "--resync" in argv
    d = display.Display()
    if not d.has_extension("RANDR"):
        sys.exit("X server has no RANDR extension")

    atoms = {
        "type": intern(d, "_NET_WM_WINDOW_TYPE"),
        "dock": intern(d, "_NET_WM_WINDOW_TYPE_DOCK"),
        "desktop": intern(d, "_NET_WM_WINDOW_TYPE_DESKTOP"),
        "nd": intern(d, "_NET_NUMBER_OF_DESKTOPS"),
        "supported": intern(d, "_NET_SUPPORTED"),
        "gtk": intern(d, "_GTK_WORKAREAS"),
    }

    wait_heads_stable(d)

    if once or resync:
        publish_workareas(
            d,
            atoms["type"],
            atoms["dock"],
            atoms["nd"],
            atoms["supported"],
            atoms["gtk"],
        )
        if resync:
            restart_pcmanfm_desktop()
        return

    last_restart = 0.0
    heads, rects, n_desk, last_restart = apply(d, atoms, last_restart)
    signature = heads_sig(heads, rects)

    root = d.screen().root
    root.change_attributes(event_mask=X.PropertyChangeMask | X.StructureNotifyMask)
    randr.select_input(root, randr.RRScreenChangeNotifyMask)
    next_poll = time.monotonic() + 2.0

    while True:
        try:
            dirty = False
            if d.pending_events():
                ev = d.next_event()
                if ev.type == X.PropertyNotify:
                    dirty = ev.atom in (atoms["supported"], atoms["nd"])
                else:
                    dirty = True
            else:
                time.sleep(0.2)

            now = time.monotonic()
            if now >= next_poll:
                dirty = True
                next_poll = now + 2.0

            if not dirty:
                continue

            time.sleep(0.15)
            while d.pending_events():
                d.next_event()

            heads, rects, n_desk, last_restart = apply(d, atoms, last_restart)
            new_sig = heads_sig(heads, rects)
            if new_sig != signature:
                old_rects = signature[1]
                signature = new_sig
                # pcmanfm reads its working area once, when it builds a desktop
                # window, and afterwards only reacts to _NET_WORKAREA -- which
                # never moves here, because the panel is not at the top of the
                # virtual screen. So a changed rect (panel-size.sh toggling
                # 56<->30, or the panel finally appearing after our startup
                # --once ran) needs the desktop rebuilt, not just republished,
                # or the top icon row stays under tint2.
                if n_desk != len(heads) or tuple(rects) != tuple(old_rects):
                    heads, rects, n_desk, last_restart = apply(
                        d, atoms, last_restart, force_restart=True
                    )
                    signature = heads_sig(heads, rects)
        except Exception:
            # A transient BadWindow while probing a dying client used to end
            # the watcher silently, and nothing restarted it: workareas then
            # stayed frozen for the rest of the session.
            traceback.print_exc()
            time.sleep(1.0)


if __name__ == "__main__":
    main(sys.argv)
