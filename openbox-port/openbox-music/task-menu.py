#!/usr/bin/env python3
"""Send To on tint2 task buttons, including titlebar-less DAWs (Renoise).

tint2 has no per-task context menu. Fluxbox's WindowMenu (with [sendto]) only
opens from the titlebar, which Renoise / Bitwig / Max often do not have.

Grab Button3 on the panel. When the click hits a task, show Send To plus
min/max/close. Clicks that miss a task are replayed (launchers / clock / tray).

Plank overwrites _NET_WM_ICON_GEOMETRY with a 0x0 dock slot for pinned apps.
Cache the last geometry that sat on the tint2 panel so those tasks still hit.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from Xlib import X, display, error

POLL_TINT2 = 2.0
ALL_DESKTOPS = 0xFFFFFFFF
USR1_COOLDOWN = 15.0
USR1_MAX_STRIKES = 2
MIN_TASK_H = 32
# fullscreen-panel.py touches this while it has tint2 unmapped for a
# fullscreen window -- every task's icon geometry looks "missing" then, which
# would otherwise read as exactly the fault this self-heal exists to catch.
FULLSCREEN_HIDDEN_FLAG = os.path.expanduser("~/.openbox-music/panel-hidden")


def intern(d, name):
    return d.intern_atom(name)


def wmctrl(*args):
    subprocess.run(
        ["wmctrl", *args],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def class_tokens(win):
    try:
        hint = win.get_wm_class()
    except (error.BadWindow, error.BadDrawable):
        return []
    if not hint:
        return []
    return [c.lower() for c in hint if c]


def iter_clients(d, atom_list):
    root = d.screen().root
    try:
        prop = root.get_full_property(atom_list, X.AnyPropertyType)
    except (error.BadWindow, error.BadAtom):
        return
    if not prop:
        return
    for wid in prop.value:
        yield d.create_resource_object("window", int(wid))


def abs_geom(d, win):
    try:
        g = win.get_geometry()
        t = d.screen().root.translate_coords(win, 0, 0)
    except (error.BadWindow, error.BadDrawable):
        return None
    return int(t.x), int(t.y), int(g.width), int(g.height)


def intersects(ax, ay, aw, ah, bx, by, bw, bh):
    return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by


def read_icon_geom(win, atom_geom):
    try:
        prop = win.get_full_property(atom_geom, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return None
    if not prop or not prop.value or len(prop.value) < 4:
        return None
    return tuple(int(v) for v in prop.value[:4])


def desktop_names(d, atom_names):
    try:
        prop = d.screen().root.get_full_property(atom_names, X.AnyPropertyType)
    except (error.BadWindow, error.BadAtom):
        prop = None
    names = []
    if prop and prop.value:
        raw = prop.value
        if isinstance(raw, bytes):
            parts = raw.split(b"\x00")
        else:
            parts = [raw]
        for part in parts:
            if isinstance(part, bytes):
                part = part.decode("utf-8", "replace")
            part = str(part).strip()
            if part:
                names.append(part)
    return names or ["Internet", "Audio"]


def window_desktop(win, atom_desk):
    try:
        prop = win.get_full_property(atom_desk, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return None
    if not prop or not prop.value:
        return None
    return int(prop.value[0])


def find_tint2(d, atom_list):
    for win in iter_clients(d, atom_list):
        if "tint2" in class_tokens(win):
            return win
    return None


def atom_list_has(win, atom, wanted):
    try:
        prop = win.get_full_property(atom, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return False
    return bool(prop) and wanted in prop.value


def current_desktop(d, atom_cur):
    try:
        prop = d.screen().root.get_full_property(atom_cur, X.AnyPropertyType)
    except (error.BadWindow, error.BadAtom):
        return 0
    if not prop or not prop.value:
        return 0
    return int(prop.value[0])


def tint2_pid(win, atom_pid):
    try:
        prop = win.get_full_property(atom_pid, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return None
    if not prop or not prop.value:
        return None
    return int(prop.value[0])


def send_to_desktop(win, desk):
    wmctrl("-i", "-r", hex(win.id), "-t", str(int(desk)))


def close_window(win):
    wmctrl("-i", "-c", hex(win.id))


def minimize_window(win):
    wmctrl("-i", "-r", hex(win.id), "-b", "add,hidden")


def maximize_window(win):
    wmctrl("-i", "-r", hex(win.id), "-b", "toggle,maximized_vert,maximized_horz")


class Grabber:
    def __init__(self, d):
        self.d = d
        self.atoms = {
            "list": intern(d, "_NET_CLIENT_LIST"),
            "geom": intern(d, "_NET_WM_ICON_GEOMETRY"),
            "names": intern(d, "_NET_DESKTOP_NAMES"),
            "desk": intern(d, "_NET_WM_DESKTOP"),
            "cur": intern(d, "_NET_CURRENT_DESKTOP"),
            "pid": intern(d, "_NET_WM_PID"),
            "type": intern(d, "_NET_WM_WINDOW_TYPE"),
            "state": intern(d, "_NET_WM_STATE"),
            "dock": intern(d, "_NET_WM_WINDOW_TYPE_DOCK"),
            "desktop": intern(d, "_NET_WM_WINDOW_TYPE_DESKTOP"),
            "skip": intern(d, "_NET_WM_STATE_SKIP_TASKBAR"),
        }
        self.panel = None
        self.grabbed_ids = set()
        self.task_geom = {}
        self.watching = set()
        self.last_usr1 = 0.0
        self.usr1_misses = {}
        self.chronic_missing = set()
        self.chronic_classes = set()
        self.started = GLib.get_monotonic_time() / 1e6
        self.menu = None

    def _ungrab(self):
        for wid in list(self.grabbed_ids):
            try:
                w = self.d.create_resource_object("window", wid)
                w.ungrab_button(X.Button3, X.AnyModifier)
            except (error.BadWindow, error.BadDrawable, error.BadAccess):
                pass
        self.grabbed_ids.clear()

    def _grab_win(self, win):
        try:
            win.grab_button(
                X.Button3,
                X.AnyModifier,
                False,
                X.ButtonPressMask,
                X.GrabModeSync,
                X.GrabModeAsync,
                X.NONE,
                X.NONE,
            )
            self.grabbed_ids.add(win.id)
            return True
        except (error.BadWindow, error.BadDrawable, error.BadAccess):
            return False

    def grab_panel(self):
        panel = find_tint2(self.d, self.atoms["list"])
        if panel is None:
            self._ungrab()
            self.panel = None
            return
        if panel.id not in self.grabbed_ids:
            self._ungrab()
            self._grab_win(panel)
            self.d.sync()
        self.panel = panel

    def watch_clients(self):
        live = set()
        for win in iter_clients(self.d, self.atoms["list"]):
            live.add(win.id)
            if win.id in self.watching:
                self.note_geom(win)
                continue
            try:
                win.change_attributes(event_mask=X.PropertyChangeMask)
                self.watching.add(win.id)
            except (error.BadWindow, error.BadDrawable, error.BadAccess):
                continue
            self.note_geom(win)
        for wid in list(self.task_geom):
            if wid not in live:
                self.task_geom.pop(wid, None)
        self.watching &= live

    def note_geom(self, win):
        g = read_icon_geom(win, self.atoms["geom"])
        if not g:
            return
        x, y, w, h = g
        if w < 8 or h < MIN_TASK_H:
            return
        panel = abs_geom(self.d, self.panel) if self.panel is not None else None
        if panel is None:
            return
        if intersects(x, y, w, h, *panel):
            self.task_geom[win.id] = (x, y, w, h)

    def is_panel_task(self, win):
        tokens = class_tokens(win)
        if "tint2" in tokens or "plank" in tokens:
            return False
        if atom_list_has(win, self.atoms["type"], self.atoms["dock"]):
            return False
        if atom_list_has(win, self.atoms["type"], self.atoms["desktop"]):
            return False
        if atom_list_has(win, self.atoms["state"], self.atoms["skip"]):
            return False
        desk = window_desktop(win, self.atoms["desk"])
        cur = current_desktop(self.d, self.atoms["cur"])
        if desk is not None and desk != cur and desk != ALL_DESKTOPS:
            return False
        return True

    def maybe_usr1(self):
        if self.panel is None:
            return
        if os.path.exists(FULLSCREEN_HIDDEN_FLAG):
            return
        now = GLib.get_monotonic_time() / 1e6
        if now - self.started < 1.0:
            return
        if now - self.last_usr1 < USR1_COOLDOWN:
            return
        panel = abs_geom(self.d, self.panel)
        if panel is None:
            return
        live_ids = set()
        missing_ids = set()
        missing_classes = {}
        for win in iter_clients(self.d, self.atoms["list"]):
            live_ids.add(win.id)
            if not self.is_panel_task(win):
                continue
            if win.id in self.task_geom or win.id in self.chronic_missing:
                continue
            tokens = class_tokens(win)
            if self.chronic_classes & set(tokens):
                # A previous window of this same app was already confirmed
                # unresolvable -- a relaunch (new window id, new PID) gets
                # no free strikes; restarting tint2 was never going to fix
                # a property Plank keeps overwriting regardless of tint2's
                # state.
                self.chronic_missing.add(win.id)
                continue
            g = read_icon_geom(win, self.atoms["geom"])
            ok = g is not None and g[3] >= MIN_TASK_H and intersects(*g, *panel)
            if not ok:
                missing_ids.add(win.id)
                missing_classes[win.id] = tokens
        # Drop bookkeeping for windows that closed, or that got resolved
        # (cached, or restored) without needing another kick.
        for wid in list(self.usr1_misses):
            if wid not in missing_ids:
                del self.usr1_misses[wid]
        self.chronic_missing &= live_ids
        if not missing_ids:
            return
        # Plank permanently overwrites _NET_WM_ICON_GEOMETRY with its own
        # dock slot for apps pinned there, so a window that is both a tint2
        # task and Plank-pinned can never get a panel-intersecting geometry
        # cached -- restarting tint2 does not fix that. Once a window has
        # cost a couple of restarts without resolving, stop kicking tint2 on
        # its account (and any future window of the same app -- see above)
        # so a permanently-unresolvable app can't force a panel restart (and
        # the taskbar-desktop-index race that comes with it) every
        # USR1_COOLDOWN seconds forever.
        for wid in missing_ids:
            strikes = self.usr1_misses.get(wid, 0) + 1
            self.usr1_misses[wid] = strikes
            if strikes > USR1_MAX_STRIKES:
                self.chronic_missing.add(wid)
                self.chronic_classes.update(missing_classes.get(wid, ()))
        if missing_ids <= self.chronic_missing:
            return
        pid = tint2_pid(self.panel, self.atoms["pid"])
        if not pid:
            return
        try:
            os.kill(pid, signal.SIGUSR1)
            self.last_usr1 = now
            GLib.timeout_add(120, self._regrab_soon)
            GLib.timeout_add(400, self._regrab_soon)
        except OSError:
            pass

    def _regrab_soon(self):
        self.grab_panel()
        self.watch_clients()
        return False

    def task_at_pointer(self, px, py):
        hits = []
        for wid, (x, y, w, h) in self.task_geom.items():
            if x <= px < x + w and y <= py < y + h:
                hits.append((w * h, wid))
        if self.panel is not None:
            panel = abs_geom(self.d, self.panel)
            if panel:
                for win in iter_clients(self.d, self.atoms["list"]):
                    if win.id == self.panel.id or win.id in self.task_geom:
                        continue
                    g = read_icon_geom(win, self.atoms["geom"])
                    if not g:
                        continue
                    x, y, w, h = g
                    if h < MIN_TASK_H:
                        continue
                    if not intersects(x, y, w, h, *panel):
                        continue
                    if x <= px < x + w and y <= py < y + h:
                        hits.append((w * h, win.id))
        if not hits:
            return None
        hits.sort(key=lambda t: t[0])
        return self.d.create_resource_object("window", hits[0][1])

    def popup(self, win, event_time):
        names = desktop_names(self.d, self.atoms["names"])
        cur = window_desktop(win, self.atoms["desk"])
        menu = Gtk.Menu()

        send = Gtk.MenuItem(label="Send To")
        sub = Gtk.Menu()
        for i, name in enumerate(names):
            on_this = cur is not None and cur != ALL_DESKTOPS and i == cur
            label = f"{name}  (current)" if on_this else name
            item = Gtk.MenuItem(label=label)
            item.set_sensitive(not on_this)
            item.connect(
                "activate", lambda _w, desk=i, w=win: send_to_desktop(w, desk)
            )
            sub.append(item)
        send.set_submenu(sub)
        menu.append(send)
        menu.append(Gtk.SeparatorMenuItem())

        mn = Gtk.MenuItem(label="Iconify")
        mn.connect("activate", lambda *_: minimize_window(win))
        menu.append(mn)

        mx = Gtk.MenuItem(label="Maximize")
        mx.connect("activate", lambda *_: maximize_window(win))
        menu.append(mx)

        cl = Gtk.MenuItem(label="Close")
        cl.connect("activate", lambda *_: close_window(win))
        menu.append(cl)

        def forget(_m):
            if self.menu is menu:
                self.menu = None

        menu.connect("deactivate", forget)
        menu.show_all()
        self.menu = menu
        t = int(event_time) if event_time else Gtk.get_current_event_time()
        menu.popup(None, None, None, None, 3, t)

    def allow(self, mode):
        try:
            self.d.allow_events(mode, X.CurrentTime)
            self.d.flush()
        except error.Error:
            pass

    def on_event(self, ev):
        if ev.type == X.PropertyNotify:
            atom = getattr(ev, "atom", None)
            if atom == self.atoms["cur"]:
                self.task_geom.clear()
                return
            if atom == self.atoms["geom"]:
                try:
                    self.note_geom(ev.window)
                except (error.BadWindow, error.BadDrawable):
                    pass
            return
        # GrabModeSync freezes *all* pointer delivery until AllowEvents.
        # Always release the sync grab, even if hit-testing throws.
        if ev.type != X.ButtonPress or getattr(ev, "detail", None) != X.Button3:
            return
        mode = X.ReplayPointer
        win = None
        try:
            if ev.window.id not in self.grabbed_ids:
                return
            px = int(getattr(ev, "root_x", 0))
            py = int(getattr(ev, "root_y", 0))
            win = self.task_at_pointer(px, py)
            if win is not None:
                mode = X.AsyncPointer
        except (error.BadWindow, error.BadDrawable, error.BadAccess):
            mode = X.ReplayPointer
            win = None
        finally:
            self.allow(mode)
        if win is not None:
            try:
                self.popup(win, getattr(ev, "time", 0))
            except Exception:
                pass


def main(argv):
    d = display.Display()
    d.set_error_handler(lambda *_a, **_k: None)
    g = Grabber(d)
    try:
        d.screen().root.change_attributes(event_mask=X.PropertyChangeMask)
    except error.Error:
        pass

    def drain(_fd=None, _cond=None):
        try:
            while d.pending_events():
                g.on_event(d.next_event())
        except (error.ConnectionClosedError, OSError):
            Gtk.main_quit()
            return False
        return True

    def refresh():
        # Drain first: a pending sync-grab ButtonPress freezes the pointer
        # for every client until AllowEvents runs.
        drain()
        g.grab_panel()
        g.watch_clients()
        g.maybe_usr1()
        drain()
        return True

    def release_sync_grab():
        # Safety valve if a ButtonPress was dropped without AllowEvents.
        g.allow(X.AsyncPointer)
        return True

    refresh()
    try:
        fd = d.display.socket.fileno()
    except Exception:
        fd = None
    if fd is not None:
        GLib.io_add_watch(fd, GLib.IO_IN, drain)
    GLib.timeout_add(50, drain)
    GLib.timeout_add(500, release_sync_grab)
    GLib.timeout_add(int(POLL_TINT2 * 1000), refresh)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
