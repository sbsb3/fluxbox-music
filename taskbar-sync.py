#!/usr/bin/env python3
"""Keep tint2's task list on the real current workspace.

tint2 treats _NET_WORKAREA / _NET_DESKTOP_GEOMETRY / _NET_DESKTOP_VIEWPORT
changes as "desktops changed" and re-reads _NET_CURRENT_DESKTOP via a plain
XGetWindowProperty. tint2's own get_property32() returns 0 whenever that read
comes back empty, with no way to tell "really desktop 0" from "the read
raced and failed" -- so a single unlucky read after the properties settle
is enough to stick the panel on desktop 0's (Internet's) tasks while Fluxbox
stays on Audio. Notifications and workspace switches both churn those
properties and both can trigger the race.

After the root properties settle, synthesize a PropertyNotify for
_NET_CURRENT_DESKTOP so tint2 re-reads the real value and fixes the taskbar.
One poke is one more XGetWindowProperty call, which can race and fail just
like the original read did -- so send a short burst of confirmation pokes
instead of just one, and cancel the burst the moment a real property change
shows up (that means a fresh, more current settle is already underway).
"""
from __future__ import annotations

import sys
import time

from Xlib import X, display
from Xlib.protocol import event

DEBOUNCE = 0.12
# Offsets (seconds after settling) for the confirmation-poke burst. More than
# one guards against the poke's own re-read racing the same way the original
# read did; the spacing gives tint2 time to actually process each one.
POKE_OFFSETS = (0.0, 0.15, 0.4)


def intern(d, name):
    return d.intern_atom(name)


def main():
    d = display.Display()
    root = d.screen().root
    atoms = {
        "cur": intern(d, "_NET_CURRENT_DESKTOP"),
        "n": intern(d, "_NET_NUMBER_OF_DESKTOPS"),
        "geom": intern(d, "_NET_DESKTOP_GEOMETRY"),
        "vp": intern(d, "_NET_DESKTOP_VIEWPORT"),
        "wa": intern(d, "_NET_WORKAREA"),
        "names": intern(d, "_NET_DESKTOP_NAMES"),
    }
    watch = set(atoms.values())

    root.change_attributes(event_mask=X.PropertyChangeMask)
    d.sync()

    pending = False
    quiet_until = 0.0
    poke_due = []  # remaining monotonic times for the confirmation-poke burst

    def poke():
        # Poke tint2 with a synthetic notify only (no property write), so we
        # do not generate another real PropertyNotify and loop.
        ev = event.PropertyNotify(
            window=root,
            atom=atoms["cur"],
            time=X.CurrentTime,
            state=X.PropertyNewValue,
        )
        d.send_event(root, ev, event_mask=X.PropertyChangeMask)
        d.sync()

    while True:
        now = time.monotonic()
        if d.pending_events():
            ev = d.next_event()
            if getattr(ev, "type", None) != X.PropertyNotify:
                continue
            # Ignore our own synthetic notify to avoid a loop.
            if getattr(ev, "send_event", False):
                continue
            if ev.atom not in watch:
                continue
            pending = True
            quiet_until = now + DEBOUNCE
            # A fresh real change means a newer, more current settle is
            # already underway -- the in-flight poke burst is stale.
            poke_due = []
            continue

        if pending and now >= quiet_until:
            pending = False
            # Drain any burst that arrived during the quiet window.
            while d.pending_events():
                ev = d.next_event()
                if (
                    getattr(ev, "type", None) == X.PropertyNotify
                    and not getattr(ev, "send_event", False)
                    and ev.atom in watch
                ):
                    pending = True
                    quiet_until = time.monotonic() + DEBOUNCE
            if pending:
                time.sleep(0.02)
                continue

            poke_due = [now + off for off in POKE_OFFSETS]

        if poke_due and now >= poke_due[0]:
            poke_due.pop(0)
            poke()
            continue

        time.sleep(0.02 if poke_due else 0.05)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
