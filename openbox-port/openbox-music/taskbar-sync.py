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

That burst is open loop: it never checked whether tint2 came back to the
right desktop, so any miss stayed on screen until the next settle. Watch what
tint2 actually renders and repair until it agrees. tint2 rewrites
_NET_WM_ICON_GEOMETRY on a client window every time it lays that window's
task button out on the panel, so the newest burst of those writes names
exactly which desktop's taskbar is on screen. (Plank writes the same property
for the apps pinned in its dock, so only count rects that land on the tint2
panel.) When that disagrees with _NET_CURRENT_DESKTOP for longer than a
render can explain, escalate: poke again, and then rewrite
_NET_CURRENT_DESKTOP so the value is unambiguously there to be read.
"""
from __future__ import annotations

import os
import sys
import time

from Xlib import X, Xatom, display, error
from Xlib.protocol import event

DEBOUNCE = 0.12
# Offsets (seconds after settling) for the confirmation-poke burst. More than
# one guards against the poke's own re-read racing the same way the original
# read did; the spacing gives tint2 time to actually process each one.
POKE_OFFSETS = (0.0, 0.15, 0.4)

CHECK = 0.5             # how often to re-derive the rendered desktop
BURST = 0.35            # icon-geometry writes this close together are one pass
PANEL_REFRESH = 5.0     # re-locate the panel this often (it can be restarted)
# tint2 only rewrites icon geometry when a task button actually moves or
# resizes, so a taskbar that comes back to a layout it already had writes
# nothing at all. Past that age the newest burst says nothing about what is on
# the panel right now -- treat it as no evidence rather than as disagreement,
# or every quiet stretch looks like a fault.
EVIDENCE_MAX = 5.0
# Repair ladder, in seconds of continuous disagreement. Deliberately stops at
# a property rewrite: SIGUSR1 restarts the panel from scratch, and a restart
# re-derives which desktop to draw, which is its own way of landing on the
# wrong one (see the git history for the restart loop that caused).
STAGE_POKE = 1.2
STAGE_POKE2 = 2.5
STAGE_REWRITE = 4.5
REWRITE_COOLDOWN = 30.0
# Set TASKBAR_SYNC_LOG=/path to record every disagreement and repair.
LOG = os.environ.get("TASKBAR_SYNC_LOG")


def log(msg):
    if not LOG:
        return
    try:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def intern(d, name):
    return d.intern_atom(name)


def prop(win, atom):
    try:
        p = win.get_full_property(atom, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return None
    return p.value if p else None


def class_tokens(win):
    try:
        hint = win.get_wm_class()
    except (error.BadWindow, error.BadDrawable):
        return []
    return [c.lower() for c in hint if c] if hint else []


def intersects(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


class Sync:
    def __init__(self):
        self.d = display.Display()
        self.root = self.d.screen().root
        self.a = {
            "cur": intern(self.d, "_NET_CURRENT_DESKTOP"),
            "n": intern(self.d, "_NET_NUMBER_OF_DESKTOPS"),
            "geom": intern(self.d, "_NET_DESKTOP_GEOMETRY"),
            "vp": intern(self.d, "_NET_DESKTOP_VIEWPORT"),
            "wa": intern(self.d, "_NET_WORKAREA"),
            "names": intern(self.d, "_NET_DESKTOP_NAMES"),
            "list": intern(self.d, "_NET_CLIENT_LIST"),
            "icon": intern(self.d, "_NET_WM_ICON_GEOMETRY"),
            "desk": intern(self.d, "_NET_WM_DESKTOP"),
        }
        self.watch = {self.a[k] for k in
                      ("cur", "n", "geom", "vp", "wa", "names")}
        self.rendered = {}      # client window id -> (monotonic, desktop)
        self.watched = set()
        self.panel = None       # (win, x, y, w, h)
        self.panel_checked = 0.0
        self.bad_since = None
        self.stage = 0
        self.last_rewrite = 0.0
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.d.sync()

    # --- state reads -----------------------------------------------------

    def current_desktop(self):
        v = prop(self.root, self.a["cur"])
        return int(v[0]) if v else None

    def window_desktop(self, win):
        v = prop(win, self.a["desk"])
        if not v:
            return None
        n = int(v[0])
        return None if n == 0xFFFFFFFF else n

    def clients(self):
        v = prop(self.root, self.a["list"])
        return [int(w) for w in v] if v else []

    def find_panel(self, now):
        """Locate the tint2 panel and cache its screen rect."""
        if self.panel and now - self.panel_checked < PANEL_REFRESH:
            return self.panel
        self.panel_checked = now
        for wid in self.clients():
            win = self.d.create_resource_object("window", wid)
            if "tint2" not in class_tokens(win):
                continue
            try:
                g = win.get_geometry()
                t = self.root.translate_coords(win, 0, 0)
            except (error.BadWindow, error.BadDrawable):
                continue
            self.panel = (win, int(t.x), int(t.y), int(g.width), int(g.height))
            return self.panel
        self.panel = None
        return None

    def watch_clients(self):
        live = set()
        for wid in self.clients():
            live.add(wid)
            if wid in self.watched:
                continue
            try:
                self.d.create_resource_object("window", wid).change_attributes(
                    event_mask=X.PropertyChangeMask)
            except (error.BadWindow, error.BadDrawable):
                continue
            self.watched.add(wid)
        for wid in self.watched - live:
            self.rendered.pop(wid, None)
        self.watched &= live

    def note_render(self, win, now):
        """Record an icon-geometry write, if tint2 (not Plank) made it."""
        panel = self.find_panel(now)
        if panel is None:
            return
        v = prop(win, self.a["icon"])
        if not v or len(v) < 4:
            self.rendered.pop(win.id, None)
            return
        x, y, w, h = (int(n) for n in v[:4])
        if w <= 0 or h <= 0 or not intersects(x, y, w, h, *panel[1:]):
            # Plank's dock slot for a pinned app, or a cleared rect.
            self.rendered.pop(win.id, None)
            return
        desk = self.window_desktop(win)
        if desk is None:
            return
        self.rendered[win.id] = (now, desk)

    def rendered_desktops(self):
        """Desktops whose task buttons tint2 laid out in the newest pass."""
        if not self.rendered:
            return set()
        newest = max(t for t, _ in self.rendered.values())
        if time.monotonic() - newest > EVIDENCE_MAX:
            return set()
        return {dsk for t, dsk in self.rendered.values() if newest - t <= BURST}

    # --- repairs ---------------------------------------------------------

    def poke(self):
        # Poke tint2 with a synthetic notify only (no property write), so we
        # do not generate another real PropertyNotify and loop.
        ev = event.PropertyNotify(
            window=self.root,
            atom=self.a["cur"],
            time=X.CurrentTime,
            state=X.PropertyNewValue,
        )
        self.d.send_event(self.root, ev, event_mask=X.PropertyChangeMask)
        self.d.sync()

    def rewrite_current_desktop(self, desk):
        # Same value, written again. Harmless to Fluxbox (it does not read
        # back its own property) but it puts the number unambiguously on the
        # root window and raises a real PropertyNotify, so tint2's re-read has
        # something to find even if the earlier one came back empty.
        try:
            self.root.change_property(self.a["cur"], Xatom.CARDINAL, 32,
                                      [int(desk)])
            self.d.sync()
        except (error.BadWindow, error.BadAtom, error.BadValue):
            pass

    def repair(self, now, cur):
        elapsed = now - self.bad_since
        if self.stage < 1 and elapsed >= STAGE_POKE:
            self.stage = 1
            log(f"desktop {cur}, tint2 rendering "
                f"{sorted(self.rendered_desktops())} -- poking")
            self.poke()
        elif self.stage < 2 and elapsed >= STAGE_POKE2:
            self.stage = 2
            log(f"still wrong after {elapsed:.1f}s -- poking again")
            self.poke()
        elif self.stage < 3 and elapsed >= STAGE_REWRITE:
            self.stage = 3
            if now - self.last_rewrite < REWRITE_COOLDOWN:
                return
            self.last_rewrite = now
            log(f"still wrong after {elapsed:.1f}s -- rewriting "
                f"_NET_CURRENT_DESKTOP={cur}")
            self.rewrite_current_desktop(cur)
        elif self.stage >= 3 and elapsed >= STAGE_REWRITE + STAGE_POKE:
            # Still wrong after the whole ladder: start it over rather than
            # give up. The rewrite stays rate limited by REWRITE_COOLDOWN.
            self.bad_since = now
            self.stage = 0

    # --- main loop -------------------------------------------------------

    def run(self):
        pending = False
        quiet_until = 0.0
        poke_due = []       # remaining monotonic times for the poke burst
        next_check = 0.0
        self.watch_clients()

        while True:
            now = time.monotonic()
            if self.d.pending_events():
                ev = self.d.next_event()
                if getattr(ev, "type", None) != X.PropertyNotify:
                    continue
                # Ignore our own synthetic notify to avoid a loop.
                if getattr(ev, "send_event", False):
                    continue
                if ev.window.id != self.root.id:
                    if ev.atom == self.a["icon"]:
                        self.note_render(ev.window, now)
                    continue
                if ev.atom == self.a["list"]:
                    self.watch_clients()
                    continue
                if ev.atom not in self.watch:
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
                while self.d.pending_events():
                    ev = self.d.next_event()
                    if (
                        getattr(ev, "type", None) == X.PropertyNotify
                        and not getattr(ev, "send_event", False)
                        and ev.window.id == self.root.id
                        and ev.atom in self.watch
                    ):
                        pending = True
                        quiet_until = time.monotonic() + DEBOUNCE
                if pending:
                    time.sleep(0.02)
                    continue

                poke_due = [now + off for off in POKE_OFFSETS]

            if poke_due and now >= poke_due[0]:
                poke_due.pop(0)
                self.poke()
                continue

            if now >= next_check:
                next_check = now + CHECK
                self.watch_clients()
                cur = self.current_desktop()
                shown = self.rendered_desktops()
                if cur is not None and shown and cur not in shown:
                    if self.bad_since is None:
                        self.bad_since = now
                        self.stage = 0
                    else:
                        self.repair(now, cur)
                else:
                    if self.stage:
                        log(f"agreed again after {now - self.bad_since:.1f}s "
                            f"(desktop {cur}, stage {self.stage})")
                    self.bad_since = None
                    self.stage = 0

            time.sleep(0.02 if poke_due else 0.05)


def main():
    Sync().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
