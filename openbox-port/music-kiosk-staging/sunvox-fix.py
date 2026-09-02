#!/usr/bin/env python3
"""Force SunVox window to a stable on-screen position on launch.

SunVox's SunDog engine writes `user specified location: <off-screen>`
into WM_NORMAL_HINTS at startup, then XMoveWindow's itself there
shortly after mapping.  Openbox's <position force="yes"> in rc.xml
only applies on initial placement, so SunVox wins the fight and the
window ends up off DP-4 (e.g. 4174,694 -- well past the right edge).

This daemon catches MapNotify on sunvox windows and force-positions
them at DP-4 top-left + 10px margin (2456, 352) at the user's saved
1920x1062 size, resets WM_NORMAL_HINTS so SunVox's stale preferred
position is gone, and strips MAXIMIZED so the window stays windowed
(matching the rc.xml intent of a decorated, draggable window on
DP-4).  Fixes only run for the first few seconds after map; after
that the user can move/resize freely.

Pattern mirrors the existing max-fix.py for Max 9.
"""
from __future__ import annotations

import sys
import time
from Xlib import X, display, error
import Xlib.Xatom as Xatom

SUNVOX_CLASS = "sunvox"
TARGET_X = 2456
TARGET_Y = 352
TARGET_W = 1920
TARGET_H = 1062
TARGET_TOLERANCE = 2
COOLDOWN_S = 0.2
FIX_WINDOW_AFTER_MAP_S = 3.0

# WM_SIZE_HINTS flags
PPosition = 4
PSize = 8
PMinSize = 16
PMaxSize = 32
PWinGravity = 512


def class_tokens(win):
    try:
        hint = win.get_wm_class()
    except (error.BadWindow, error.BadDrawable):
        return []
    return [c.lower() for c in hint] if hint else []


def is_at_target(g):
    return (abs(g.x - TARGET_X) <= TARGET_TOLERANCE and
            abs(g.y - TARGET_Y) <= TARGET_TOLERANCE and
            abs(g.width - TARGET_W) <= TARGET_TOLERANCE and
            abs(g.height - TARGET_H) <= TARGET_TOLERANCE)


def main():
    d = display.Display()
    root = d.screen().root
    atom_state = d.intern_atom("_NET_WM_STATE")
    atom_max_v = d.intern_atom("_NET_WM_STATE_MAXIMIZED_VERT")
    atom_max_h = d.intern_atom("_NET_WM_STATE_MAXIMIZED_HORZ")
    atom_client_list = d.intern_atom("_NET_CLIENT_LIST")
    atom_normal_hints = d.intern_atom("WM_NORMAL_HINTS")
    atom_cardinal = d.intern_atom("CARDINAL")

    watched = {}        # wid -> window resource
    cooldown = {}       # wid -> monotonic timestamp
    fix_deadline = {}   # wid -> monotonic deadline

    def scan_clients():
        try:
            p = root.get_full_property(atom_client_list, X.AnyPropertyType)
        except error.BadWindow:
            return
        live = set()
        if p:
            for wid in p.value:
                wid = int(wid)
                live.add(wid)
                if wid in watched:
                    continue
                try:
                    win = d.create_resource_object("window", wid)
                    if SUNVOX_CLASS not in class_tokens(win):
                        continue
                    win.change_attributes(
                        event_mask=X.PropertyChangeMask | X.StructureNotifyMask)
                    watched[wid] = win
                    # Fix immediately on first sighting: the watcher may
                    # have been started after the window was already mapped,
                    # in which case no MapNotify event will arrive.
                    fix_deadline[wid] = time.monotonic() + FIX_WINDOW_AFTER_MAP_S
                    fix_window(wid, "scan")
                except (error.BadWindow, error.BadDrawable):
                    continue
        for wid in list(watched):
            if wid not in live:
                del watched[wid]
                cooldown.pop(wid, None)
                fix_deadline.pop(wid, None)

    def fix_window(wid, reason=""):
        # Honor the per-window deadline so we don't fight the user.
        if wid in fix_deadline and time.monotonic() > fix_deadline[wid]:
            return
        now = time.monotonic()
        if wid in cooldown and now < cooldown[wid]:
            return
        try:
            win = d.create_resource_object("window", wid)
            g = win.get_geometry()
            # Skip 1x1 placeholder / pre-real-size windows
            if g.width < 100 or g.height < 100:
                return
            if is_at_target(g):
                return
            cooldown[wid] = now + COOLDOWN_S
            # Strip MAXIMIZED so the window stays windowed (rc.xml intent)
            try:
                sp = win.get_full_property(atom_state, X.AnyPropertyType)
                if sp:
                    states = [s for s in sp.value
                              if s != atom_max_v and s != atom_max_h]
                    win.change_property(atom_state, Xatom.ATOM, 32, states)
            except (error.BadWindow, error.BadDrawable):
                pass
            # Reset WM_NORMAL_HINTS so SunVox's stale preferred position is
            # overwritten with our target (the window manager will honor
            # PPosition | user-specified location from these hints).
            flags = PPosition | PSize | PMinSize | PMaxSize | PWinGravity
            hints = [
                flags, 0, 0,
                TARGET_X, TARGET_Y,
                TARGET_W, TARGET_H,
                1, 1,
                TARGET_W, TARGET_H,
                0, 0,
                0, 0, 0, 0,
                0, 0,
                10,
            ]
            win.change_property(atom_normal_hints, atom_cardinal, 32, hints)
            # Reconfigure window geometry
            win.configure(
                x=TARGET_X, y=TARGET_Y,
                width=TARGET_W, height=TARGET_H)
            d.sync()
            print(f"sunvox-fix: wid={wid:#x} {reason} "
                  f"-> {TARGET_W}x{TARGET_H}+{TARGET_X}+{TARGET_Y}",
                  file=sys.stderr, flush=True)
        except (error.BadWindow, error.BadDrawable):
            pass

    def handle_map(wid):
        fix_deadline[wid] = time.monotonic() + FIX_WINDOW_AFTER_MAP_S
        fix_window(wid, "map")

    root.change_attributes(event_mask=X.PropertyChangeMask)
    scan_clients()

    last_scan = time.monotonic()

    while True:
        if d.pending_events():
            ev = d.next_event()
            ev_type = getattr(ev, "type", None)

            if ev_type == X.PropertyNotify:
                ev_win = getattr(ev, "window", None)
                ev_wid = ev_win.id if hasattr(ev_win, "id") else ev_win
                ev_atom = getattr(ev, "atom", None)
                if ev_wid == root.id and ev_atom == atom_client_list:
                    scan_clients()
                    last_scan = time.monotonic()
                elif ev_wid in watched and ev_atom == atom_normal_hints:
                    # SunVox reset its preferred position -- re-fix.
                    fix_window(ev_wid, "hints")
            elif ev_type == X.ConfigureNotify:
                ev_win = getattr(ev, "window", None)
                ev_wid = ev_win.id if hasattr(ev_win, "id") else ev_win
                if ev_wid in watched:
                    fix_window(ev_wid, "configure")
            elif ev_type == X.MapNotify:
                ev_win = getattr(ev, "window", None)
                ev_wid = ev_win.id if hasattr(ev_win, "id") else ev_win
                if ev_wid in watched:
                    handle_map(ev_wid)
            continue

        now = time.monotonic()
        if now - last_scan >= 0.5:
            scan_clients()
            last_scan = now

        time.sleep(0.05)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass