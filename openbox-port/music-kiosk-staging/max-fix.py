#!/usr/bin/env python3
"""Fix Max 9 (Wine/JUCE) window behavior in the kiosk session.

JUCE does three things that break window management:
1. When a max.exe window is resized to exactly match the monitor
   (1920x1080), JUCE auto-sets _NET_WM_STATE_FULLSCREEN, which raises
   it above Plank's `above` layer.
2. When Openbox sets _NET_WM_STATE_MAXIMIZED (titlebar maximize button,
   Alt-F10, etc.), JUCE immediately sends a ClientMessage to strip it,
   so the maximize never sticks — the window just flashes.
3. JUCE sets WM_NORMAL_HINTS with min=max (fixed size) to prevent
   resizing, and resets these hints after any configure request.

This script uses Xlib events to catch _NET_WM_STATE changes on max.exe
windows.  When it sees any change, it:
  - Strips _NET_WM_STATE (removes fullscreen/maximized)
  - Resets WM_NORMAL_HINTS to allow the target size (min=1, max=large)
  - Configures the window to 1918x1060 at 2446,360 (2px shy of the
    monitor, offset by 18px for the title bar frame)

The window fills the screen visually with a visible title bar, but
stays in Normal layer where Plank can reveal over it.
"""
from __future__ import annotations

import time
from Xlib import X, display, error
import Xlib.Xatom as Xatom

MAX_CLASS = "max.exe"
TARGET_W = 1918
TARGET_H = 1060
TARGET_X = 2446
TARGET_Y = 360
MIN_SIZE = 100  # skip 1x1 IME/placeholder windows

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


def main():
    d = display.Display()
    root = d.screen().root
    atom_state = d.intern_atom("_NET_WM_STATE")
    atom_client_list = d.intern_atom("_NET_CLIENT_LIST")
    atom_normal_hints = d.intern_atom("WM_NORMAL_HINTS")
    atom_cardinal = d.intern_atom("CARDINAL")

    watched = {}
    cooldown = {}  # wid -> monotonic timestamp until which we skip fixes

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
                    if MAX_CLASS not in class_tokens(win):
                        continue
                    win.change_attributes(event_mask=X.PropertyChangeMask)
                    watched[wid] = win
                except (error.BadWindow, error.BadDrawable):
                    continue
        for wid in list(watched):
            if wid not in live:
                del watched[wid]
                cooldown.pop(wid, None)

    def fix_window(wid):
        now = time.monotonic()
        if wid in cooldown and now < cooldown[wid]:
            return
        # Set cooldown to prevent re-entrancy from our own property changes
        cooldown[wid] = now + 0.3
        try:
            win = d.create_resource_object("window", wid)
            g = win.get_geometry()
            if g.width < MIN_SIZE or g.height < MIN_SIZE:
                return
            # Wait briefly for JUCE to settle its own hint/state fighting
            time.sleep(0.05)
            # Strip _NET_WM_STATE
            win.change_property(atom_state, Xatom.ATOM, 32, [])
            # Reset WM_NORMAL_HINTS to allow target size
            # flags=PPosition|PSize|PMinSize|PMaxSize|PWinGravity
            flags = PPosition | PSize | PMinSize | PMaxSize | PWinGravity
            hints = [
                flags, 0, 0,                         # flags, pad, pad
                TARGET_X, TARGET_Y,                   # x, y
                TARGET_W, TARGET_H,                   # width, height
                1, 1,                                 # min_width, min_height
                TARGET_W, TARGET_H,                   # max_width, max_height
                0, 0,                                 # width_inc, height_inc
                0, 0, 0, 0,                           # min/max aspect
                0, 0,                                 # base_width, base_height
                10,                                   # win_gravity (Static=10)
            ]
            win.change_property(atom_normal_hints, atom_cardinal, 32, hints)
            # Configure window
            win.configure(
                x=TARGET_X, y=TARGET_Y,
                width=TARGET_W, height=TARGET_H)
            d.sync()
        except (error.BadWindow, error.BadDrawable):
            pass

    root.change_attributes(event_mask=X.PropertyChangeMask)
    scan_clients()

    last_scan = time.monotonic()

    while True:
        if d.pending_events():
            ev = d.next_event()
            if getattr(ev, "type", None) == X.PropertyNotify:
                ev_win = getattr(ev, "window", None)
                ev_wid = ev_win.id if hasattr(ev_win, "id") else ev_win
                ev_atom = getattr(ev, "atom", None)
                if ev_wid == root.id and ev_atom == atom_client_list:
                    scan_clients()
                    last_scan = time.monotonic()
                elif ev_wid in watched and ev_atom in (atom_state, atom_normal_hints):
                    fix_window(ev_wid)
            continue

        now = time.monotonic()
        if now - last_scan >= 0.1:
            scan_clients()
            last_scan = now

        time.sleep(0.01)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
