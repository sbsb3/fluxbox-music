#!/usr/bin/env python3
"""Hide tint2 (and Plank) while a fullscreen window covers their head.

apps pins tint2 to Layer 4 and Plank to Layer 2 ("AboveDock (always on top)"
per startup's comment) specifically so maximized DAWs can never bury them --
see [app] (class=Tint2) / (class=Plank) in apps. Fluxbox does not promote a
window's layer when it goes fullscreen, though, so a fullscreen window still
sits in Normal (8) and both docks keep compositing over it: tint2's strip at
the top, Plank's at the bottom.

Worse, the fullscreen hint itself can't be trusted here. This session
launches Steam flatpak games (GoldSrc mods such as The Specialists), and
those legacy engines typically never set _NET_WM_STATE_FULLSCREEN -- they
just resize a normal top-level window to the output's full resolution. So
detect fullscreen two ways: the EWMH state when an app bothers to set it, or
a mapped top-level window whose screen rect exactly matches the primary
output. Either one means a window wants the whole head to itself, and both
docks should get out of the way for as long as that is true.

Unmap/map rather than touching layer or stacking: it cannot be out-raced by
Fluxbox's own restack-on-map, and it stops the docks from eating clicks meant
for the game as a bonus.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from shutil import which

from Xlib import X, display, error

DEBOUNCE = 0.15          # coalesce bursts of Configure/PropertyNotify
CHECK = 1.0              # fallback poll, in case an event is missed
HEAD_REFRESH = 5.0       # re-query the primary output this often (hotplug)
PANEL_REFRESH = 5.0      # re-locate tint2 / plank this often (can restart)
GEOM_TOLERANCE = 2       # px slack when comparing a window rect to the head

PANEL_CLASSES = ("tint2", "plank")

# task-menu.py's maybe_usr1() self-heal watches for tint2 task buttons whose
# icon geometry looks "missing" and sends tint2 SIGUSR1 (full destroy+reinit)
# to recover -- see its own docstring for the restart-storm that caused
# before it got a cooldown/strike limit. Unmapping tint2 here makes every
# task look missing at once, which used to retrigger that self-heal
# repeatedly until tint2 crashed. Touch this flag while tint2 is ours to hide
# so task-menu.py knows to stand down instead of "fixing" it.
FULLSCREEN_HIDDEN_FLAG = os.path.expanduser("~/.openbox-music/panel-hidden")

LOG = os.environ.get("FULLSCREEN_PANEL_LOG")


def log(msg):
    if not LOG:
        return
    try:
        with open(LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    except OSError:
        pass


def have(cmd):
    return which(cmd) is not None


def primary_geometry():
    """(x, y, w, h) of the primary output, or None."""
    try:
        out = subprocess.run(
            ["xrandr", "--query"], capture_output=True, text=True, timeout=2
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        if " primary " not in f" {line} ":
            continue
        for tok in line.split():
            if "x" in tok and "+" in tok:
                try:
                    dims, x, y = tok.split("+")
                    w, h = dims.split("x")
                    return int(x), int(y), int(w), int(h)
                except ValueError:
                    continue
    return None


def intersects(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def close(a, b, tol=GEOM_TOLERANCE):
    return abs(a - b) <= tol


class Watcher:
    def __init__(self):
        self.d = display.Display()
        self.root = self.d.screen().root
        self.a = {
            "list": self.d.intern_atom("_NET_CLIENT_LIST"),
            "state": self.d.intern_atom("_NET_WM_STATE"),
            "fullscreen": self.d.intern_atom("_NET_WM_STATE_FULLSCREEN"),
            "type": self.d.intern_atom("_NET_WM_WINDOW_TYPE"),
            "type_desktop": self.d.intern_atom("_NET_WM_WINDOW_TYPE_DESKTOP"),
            "type_dock": self.d.intern_atom("_NET_WM_WINDOW_TYPE_DOCK"),
        }
        self.watched = set()
        self.panels = {}         # class token -> (win, x, y, w, h)
        self.panels_checked = 0.0
        self.head = None         # (x, y, w, h)
        self.head_checked = 0.0
        self.hidden = set()      # class tokens we have unmapped ourselves
        # A stale flag from a killed/crashed previous run would otherwise
        # leave task-menu.py's self-heal permanently stood down.
        try:
            os.remove(FULLSCREEN_HIDDEN_FLAG)
        except OSError:
            pass
        self.root.change_attributes(event_mask=X.PropertyChangeMask)
        self.d.sync()

    # --- lookups -----------------------------------------------------

    def clients(self):
        try:
            p = self.root.get_full_property(self.a["list"], X.AnyPropertyType)
        except error.BadWindow:
            return []
        return [int(w) for w in p.value] if p else []

    def class_tokens(self, win):
        try:
            hint = win.get_wm_class()
        except (error.BadWindow, error.BadDrawable):
            return []
        return [c.lower() for c in hint if c] if hint else []

    def rect(self, win):
        try:
            g = win.get_geometry()
            t = self.root.translate_coords(win, 0, 0)
        except (error.BadWindow, error.BadDrawable):
            return None
        return int(t.x), int(t.y), int(g.width), int(g.height)

    def find_head(self, now):
        if self.head is not None and now - self.head_checked < HEAD_REFRESH:
            return self.head
        self.head_checked = now
        self.head = primary_geometry()
        return self.head

    def tree_windows(self, top, maxdepth=4):
        """BFS over top's descendants, depth-limited."""
        level = [top]
        for _ in range(maxdepth):
            nxt = []
            for win in level:
                try:
                    nxt.extend(win.query_tree().children)
                except (error.BadWindow, error.BadDrawable):
                    continue
            if not nxt:
                break
            yield from nxt
            level = nxt

    def find_panels(self, now):
        # Fluxbox leaves both out of _NET_CLIENT_LIST (tint2 sets
        # _NET_WM_STATE_SKIP_TASKBAR; whatever Plank's reason is, checked live
        # and it is excluded too) -- unlike every other lookup here, this one
        # has to walk the raw window tree. Usually undecorated (apps:
        # [Deco] {NONE}) means Fluxbox leaves them as plain children of root,
        # but a relaunch can still land one inside a frame (observed live
        # after restarting tint2), so walk a few levels down rather than
        # assume depth 1.
        if self.panels and now - self.panels_checked < PANEL_REFRESH:
            return self.panels
        self.panels_checked = now
        found = {}
        for win in self.tree_windows(self.root):
            for cls in self.class_tokens(win):
                if cls not in PANEL_CLASSES:
                    continue
                r = self.rect(win)
                if not r or r[2] <= 1 or r[3] <= 1:
                    continue  # tooltip / placeholder windows of the same class
                prev = found.get(cls)
                if prev is None or r[2] * r[3] > prev[3] * prev[4]:
                    found[cls] = (win,) + r
        self.panels = found
        return found

    def watch_clients(self):
        live = set()
        for wid in self.clients():
            live.add(wid)
            if wid in self.watched:
                continue
            try:
                self.d.create_resource_object("window", wid).change_attributes(
                    event_mask=X.PropertyChangeMask | X.StructureNotifyMask)
            except (error.BadWindow, error.BadDrawable):
                continue
            self.watched.add(wid)
        self.watched &= live

    def is_fullscreen(self, win):
        try:
            p = win.get_full_property(self.a["state"], X.AnyPropertyType)
        except (error.BadWindow, error.BadDrawable):
            return False
        return bool(p) and self.a["fullscreen"] in list(p.value)

    def is_desktop_or_dock(self, win):
        # pcmanfm's per-head desktop windows are sized to exactly match their
        # output -- indistinguishable from a borderless fullscreen game by
        # geometry alone, so window type is the only way to tell them apart.
        try:
            p = win.get_full_property(self.a["type"], X.AnyPropertyType)
        except (error.BadWindow, error.BadDrawable):
            return False
        if not p:
            return False
        types = set(int(v) for v in p.value)
        return bool(types & {self.a["type_desktop"], self.a["type_dock"]})

    def is_viewable(self, win):
        try:
            return win.get_attributes().map_state == X.IsViewable
        except (error.BadWindow, error.BadDrawable):
            return False

    # --- decision ------------------------------------------------------

    def fullscreen_present(self, now):
        head = self.find_head(now)
        panels = self.find_panels(now)
        panel_wids = {p[0].id for p in panels.values()}
        for wid in self.clients():
            if wid in panel_wids:
                continue
            win = self.d.create_resource_object("window", wid)
            if not self.is_viewable(win) or self.is_desktop_or_dock(win):
                continue
            r = self.rect(win)
            if r is None:
                continue
            x, y, w, h = r
            if self.is_fullscreen(win):
                if head is None or any(
                    intersects(x, y, w, h, *p[1:]) for p in panels.values()
                ):
                    return True
                continue
            if head and (
                close(x, head[0]) and close(y, head[1])
                and close(w, head[2]) and close(h, head[3])
            ):
                return True
        return False

    # --- apply -----------------------------------------------------------

    def apply(self, now, hide):
        panels = self.find_panels(now)
        # Set the flag before tint2 actually disappears, and clear it only
        # after tint2 is mapped again: task-menu.py's poll must never see
        # "tint2 gone, flag absent" in between, or it reads that as the
        # exact fault it exists to self-heal.
        if hide and "tint2" in panels and "tint2" not in self.hidden:
            try:
                with open(FULLSCREEN_HIDDEN_FLAG, "w"):
                    pass
            except OSError:
                pass
        for cls, (win, *_r) in panels.items():
            if hide and cls not in self.hidden:
                try:
                    win.unmap()
                    self.hidden.add(cls)
                    log(f"hiding {cls}")
                except (error.BadWindow, error.BadDrawable):
                    pass
            elif not hide and cls in self.hidden:
                try:
                    win.map()
                except (error.BadWindow, error.BadDrawable):
                    pass
                self.hidden.discard(cls)
                log(f"restoring {cls}")
        self.d.sync()
        if not hide and "tint2" not in self.hidden:
            try:
                os.remove(FULLSCREEN_HIDDEN_FLAG)
            except OSError:
                pass

    # --- main loop ---------------------------------------------------

    def run(self):
        self.watch_clients()
        pending = False
        quiet_until = 0.0
        next_check = 0.0

        while True:
            now = time.monotonic()
            if self.d.pending_events():
                ev = self.d.next_event()
                etype = getattr(ev, "type", None)
                if etype == X.PropertyNotify and ev.window.id == self.root.id:
                    if ev.atom == self.a["list"]:
                        self.watch_clients()
                        self.panels_checked = 0.0
                    pending = True
                    quiet_until = now + DEBOUNCE
                elif etype in (X.PropertyNotify, X.ConfigureNotify):
                    pending = True
                    quiet_until = now + DEBOUNCE
                continue

            if pending and now >= quiet_until:
                pending = False
                next_check = 0.0  # force an immediate recheck below

            if now >= next_check:
                next_check = now + CHECK
                self.apply(now, self.fullscreen_present(now))

            time.sleep(0.05)


def main():
    if not have("xrandr"):
        # No way to learn the primary output size; nothing useful to do.
        sys.exit(0)
    Watcher().run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            os.remove(FULLSCREEN_HIDDEN_FLAG)
        except OSError:
            pass
