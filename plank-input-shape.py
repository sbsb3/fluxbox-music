#!/usr/bin/env python3
"""Propagate Plank's ShapeInput region onto its Fluxbox frame window.

Fluxbox reparents Plank into a frame and copies only the *bounding* shape to
that frame, never the *input* shape.  Plank sets a correct input shape on its
own window (a 1px sliver while hidden), but the frame keeps accepting pointer
events across its whole rect -- the full width of the monitor by ~168px tall.
Clicks in the bottom band of the screen are swallowed and never reach the DAW
underneath, so e.g. Renoise device sliders there cannot be dragged.

Copy the client's input shape onto the frame whenever Plank changes it.
"""
import sys
import time

from Xlib import X, display, error
from Xlib.ext import shape

DOCK = "_NET_WM_WINDOW_TYPE_DOCK"


def is_plank_dock(d, win, atom_type, atom_dock):
    try:
        cls = win.get_wm_class()
        if not cls or "plank" not in [c.lower() for c in cls]:
            return False
        prop = win.get_full_property(atom_type, X.AnyPropertyType)
        return bool(prop) and atom_dock in prop.value
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return False


def find_dock(d, atom_type, atom_dock):
    """Plank's dock window sits one level under a Fluxbox frame."""
    root = d.screen().root
    try:
        children = root.query_tree().children
    except error.BadWindow:
        return None
    for frame in children:
        if is_plank_dock(d, frame, atom_type, atom_dock):
            return frame
        try:
            for child in frame.query_tree().children:
                if is_plank_dock(d, child, atom_type, atom_dock):
                    return child
        except (error.BadWindow, error.BadDrawable):
            continue
    return None


def sync(client, frame):
    """Set the frame's input shape from the client's.

    python-xlib's shape_combine() takes no source window, so read the client's
    input rectangles and apply them to the frame explicitly.  The client sits
    at +0+0 inside the frame, so the rectangles carry over unshifted.
    """
    rects = client.shape_get_rectangles(shape.SK.Input).rectangles
    frame.shape_rectangles(
        shape.SO.Set,
        shape.SK.Input,
        0,  # UnSorted
        0,
        0,
        [{"x": r.x, "y": r.y, "width": r.width, "height": r.height} for r in rects],
    )


def main():
    d = display.Display()
    if not d.has_extension("SHAPE"):
        sys.exit("X server has no SHAPE extension")

    atom_type = d.intern_atom("_NET_WM_WINDOW_TYPE")
    atom_dock = d.intern_atom(DOCK)
    shape_notify = d.extension_event.ShapeNotify

    client = None
    frame = None

    while True:
        if client is None:
            client = find_dock(d, atom_type, atom_dock)
            if client is None:
                time.sleep(2)
                continue
            try:
                frame = client.query_tree().parent
                client.shape_select_input(1)
                sync(client, frame)
                d.sync()
            except (error.BadWindow, error.BadDrawable):
                client = frame = None
                continue

        # Plank restarts, and Fluxbox rebuilds frames on reconfigure, so both
        # ids go stale; fall back to rediscovery rather than dying.
        try:
            parent = client.query_tree().parent
            if parent.id != frame.id:
                frame = parent
                sync(client, frame)
                d.sync()
        except (error.BadWindow, error.BadDrawable):
            client = frame = None
            continue

        if d.pending_events():
            ev = d.next_event()
            if ev.type == shape_notify:
                try:
                    sync(client, frame)
                    d.sync()
                except (error.BadWindow, error.BadDrawable):
                    client = frame = None
        else:
            time.sleep(0.1)


if __name__ == "__main__":
    main()
