#!/usr/bin/env python3
"""Windows+Shift+right-click Send To on tint2 task buttons (DAWs too).

tint2 has no per-task context menu. Openbox's own client-menu (with Send To)
only opens from a titlebar, which Renoise / Bitwig / Max often do not have.

Core-protocol XGrabButton is not usable here, on ANY button+modifier combo:
the window that actually receives clicks is not tint2's own window at all,
but an invisible frame Openbox creates in front of every top-level window it
manages (docks included) -- and Openbox itself permanently holds passive
grabs there: plain Button3/AnyModifier for click-to-focus, and Mod4+Button3
for the Frame context's own "W-Right -> client-menu" bind (rc.xml, the same
one that gives titlebar-less DAWs their Send To menu). X allows only one
owner per exact button+modifier combo per window, so neither is ours to
take.

XInput2 passive grabs (XIGrabButton) are a separate grab table from core
XGrabButton, so Mod4+Button3 there does NOT conflict with Openbox's core
grab of the same nominal combo at *registration* time -- confirmed live via
a raw protocol probe (ours succeeds where a core-protocol attempt gets
BadAccess). But the two tables still both match the SAME physical button
press at *delivery* time, and which one the server actually hands the event
to turned out not to be reliably ours: plain Mod4+Button3 only reached this
script roughly half the time live-testing it, the rest silently going to
Openbox's own Frame-context grab instead (its client-menu popping up for
whatever else was focused). Mod4+Shift+Button3 has no such competing
core-protocol registration anywhere in rc.xml to race against, and testing
it back-to-back many times over came back with zero misses. Use that
combo -- grab it via XI2 on the frame window in front of tint2,
GrabModeSync, and release every captured event with XIAllowEvents
(hand-rolled: python-xlib wraps the rest of XI2's passive-grab requests but
not this one) -- Async to consume a hit, Replay to let a miss fall through
as before.

When the click hits a task, show Send To plus min/max/close (deferred one
main-loop tick past the triggering event -- inline, GTK's own popup grab
sometimes couldn't take because this same click's button-release hadn't
finished settling at the server yet, and the menu would show and instantly
self-dismiss). Clicks that miss a task are replayed (launchers / clock /
tray).

Plank overwrites _NET_WM_ICON_GEOMETRY with a 0x0 dock slot for pinned apps.
Cache the last geometry that sat on the tint2 panel so those tasks still hit.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys

DEBUG = os.environ.get("TASK_MENU_DEBUG") == "1"


def debug(*args):
    if DEBUG:
        print(*args, file=sys.stderr, flush=True)

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from Xlib import X, display, error
from Xlib.ext import xinput
from Xlib.protocol import rq

POLL_TINT2 = 2.0
ALL_DESKTOPS = 0xFFFFFFFF
USR1_COOLDOWN = 15.0
USR1_MAX_STRIKES = 2
# Filters out Plank's clobbered 0x0 icon geometry for pinned apps (see
# below) without rejecting real task geometry from the compact tint2
# profile, whose 30px-tall panel (panel-size.sh) reports task icons
# shorter than the 56px normal profile ever would.
MIN_TASK_H = 16
# Windows+Shift, plus its Lock/NumLock variants -- X grabs are keyed on the
# exact modifier state, so "Super+Shift regardless of lock keys" needs one
# grab per combination rather than a single wildcard. Shift is load-bearing
# here, not decorative: see module docstring for why plain Mod4 isn't enough.
GRAB_MODS = (
    X.Mod4Mask | X.ShiftMask,
    X.Mod4Mask | X.ShiftMask | X.LockMask,
    X.Mod4Mask | X.ShiftMask | X.Mod2Mask,
    X.Mod4Mask | X.ShiftMask | X.LockMask | X.Mod2Mask,
)
# XI2 GenericEvent core type, and the XI_ButtonPress sub-type carried in its
# extension payload -- separate namespaces (X.ButtonPress is the core event).
GENERIC_EVENT = 35
# XIAllowEvents event_mode values (XI2 protocol; not core AllowEvents' modes).
XI_ASYNC_DEVICE = 0
XI_REPLAY_DEVICE = 2


class XIAllowEvents(rq.Request):
    """Hand-rolled: python-xlib's xinput module wraps XIPassiveGrabDevice
    and friends but not this one. Wire format per the XI2 protocol spec,
    request minor-opcode 53 (the gap between XIUngrabDevice=52 and
    XIPassiveGrabDevice=54 in Xlib/ext/xinput.py)."""

    _request = rq.Struct(
        rq.Card8("opcode"),
        rq.Opcode(53),
        rq.RequestLength(),
        rq.Card32("time"),
        rq.Card16("deviceid"),
        rq.Card8("event_mode"),
        rq.Pad(1),
    )


def xi_allow_events(d, xi_major, deviceid, event_mode):
    XIAllowEvents(
        display=d.display,
        opcode=xi_major,
        time=X.CurrentTime,
        deviceid=deviceid,
        event_mode=event_mode,
    )
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


def find_frame(d, panel):
    """The window that actually receives clicks over tint2: an invisible,
    class-less, same-geometry sibling Openbox creates in front of every
    top-level window it manages, docks included (see module docstring).
    It is a plain child of root, not of tint2 -- found by matching absolute
    geometry among root's other children, not by walking tint2's own tree.
    """
    if panel is None:
        return None
    root = d.screen().root
    try:
        g = panel.get_geometry()
        t = root.translate_coords(panel, 0, 0)
    except (error.BadWindow, error.BadDrawable):
        return None
    target = (t.x, t.y, g.width, g.height)
    try:
        children = root.query_tree().children
    except (error.BadWindow, error.BadDrawable):
        return None
    for c in children:
        if c.id == panel.id:
            continue
        try:
            cg = c.get_geometry()
            ct = root.translate_coords(c, 0, 0)
        except (error.BadWindow, error.BadDrawable):
            continue
        if (ct.x, ct.y, cg.width, cg.height) == target:
            return c
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
        self.xi_major = d.query_extension("XInputExtension").major_opcode
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
                # Free-function call, self passed explicitly: python-xlib's
                # xinput module defines this but never registers it as a
                # bound Window method (unlike e.g. xinput_grab_keycode).
                xinput.passive_ungrab_device(
                    w, xinput.AllMasterDevices, X.Button3, xinput.GrabtypeButton, list(GRAB_MODS)
                )
            except (error.BadWindow, error.BadDrawable, error.BadAccess):
                pass
        self.grabbed_ids.clear()

    def _grab_win(self, win):
        try:
            reply = xinput.passive_grab_device(
                win,
                xinput.AllMasterDevices,
                X.CurrentTime,
                X.Button3,
                xinput.GrabtypeButton,
                X.GrabModeSync,
                X.GrabModeAsync,
                False,
                xinput.ButtonPressMask,
                list(GRAB_MODS),
            )
        except (error.BadWindow, error.BadDrawable, error.BadAccess) as e:
            debug(f"_grab_win: XI2 grab on {win.id:#x} raised {e!r}")
            return False
        # The reply lists only the modifier combos that FAILED; empty means
        # every one of GRAB_MODS was granted.
        failed = list(reply.modifiers)
        ok_count = len(GRAB_MODS) - len(failed)
        debug(f"_grab_win: XI2 grab_button on {win.id:#x} succeeded for {ok_count}/{len(GRAB_MODS)} modifier combos"
              + (f", failed={[hex(m) for m in failed]}" if failed else ""))
        if ok_count:
            self.grabbed_ids.add(win.id)
            return True
        return False

    def grab_panel(self):
        panel = find_tint2(self.d, self.atoms["list"])
        if panel is None:
            self._ungrab()
            self.panel = None
            return
        self.panel = panel
        # Not panel itself: the window that actually receives clicks is an
        # invisible Openbox-created frame sitting in front of it (module
        # docstring). Re-resolve every call -- tint2 restarts get a new
        # frame too, and the old frame's grab dies with its window anyway.
        frame = find_frame(self.d, panel)
        if frame is None:
            self._ungrab()
            return
        if frame.id not in self.grabbed_ids:
            self._ungrab()
            self._grab_win(frame)

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
            debug("popup: deactivate fired")
            if self.menu is menu:
                self.menu = None
            # NOTE: used to force-ungrab the GDK seat here too, on the
            # theory that GTK's own popup grab lingering was why the very
            # next Windows+Shift+right-click sometimes went nowhere.
            # Suspect now it was the opposite problem: this ungrab call
            # firing (only ever reached once a menu has actually shown and
            # then closed) lines up with every popup attempt afterward
            # going silently blank -- exactly the failure mode this was
            # meant to prevent, just delayed by one popup. The
            # Mod4+Shift+Button3 combo already fixed the race this existed
            # for, from a different angle (no competing core-protocol
            # grab left to lose to), so this isn't pulling its weight
            # anymore and may be actively causing the regression. Removed;
            # see git history if it needs to come back.

        menu.connect("deactivate", forget)
        menu.show_all()
        self.menu = menu
        # popup_at_pointer(), the GTK-recommended replacement for the
        # classic call below, needs a GdkWindow to anchor its positioning
        # rect to -- normally the widget/window that triggered it. This
        # script has none (it's a headless daemon with no window of its
        # own), and asking it to figure one out from "no triggering event"
        # is a hard GTK-CRITICAL assertion failure, not a graceful
        # fallback. Back to the classic call, real event time included.
        t = int(event_time) if event_time else Gtk.get_current_event_time()
        debug(f"popup: calling menu.popup(), event_time={t}")
        menu.popup(None, None, None, None, 3, t)
        debug(f"popup: menu.popup() returned, visible={menu.get_visible()} mapped={menu.get_mapped()}")

        def check_later():
            debug(f"popup: 300ms later, visible={menu.get_visible()} mapped={menu.get_mapped()}")
            return False

        GLib.timeout_add(300, check_later)

    def allow(self, mode):
        # Core AllowEvents. Nothing holds a core grab anymore (see module
        # docstring), so this is now only the safety-valve's belt-and-braces
        # call in main() -- harmless no-op if the server has nothing of
        # ours to release.
        try:
            self.d.allow_events(mode, X.CurrentTime)
            self.d.flush()
        except error.Error:
            pass

    def xi_allow(self, deviceid, mode):
        try:
            xi_allow_events(self.d, self.xi_major, deviceid, mode)
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
        if ev.type in (X.CreateNotify, X.DestroyNotify, X.ReparentNotify, X.UnmapNotify, X.MapNotify):
            # Openbox destroys and recreates tint2's invisible frame (the
            # window our XI2 grab actually lives on -- see module
            # docstring) on its own schedule, not ours: e.g. every unmap/
            # remap cycle fullscreen-panel.py does to hide tint2 behind a
            # fullscreen window. Waiting out the up-to-2s POLL_TINT2 gap
            # left a real window where the old frame was already gone and
            # the new one wasn't grabbed yet -- re-resolve immediately
            # instead of waiting for the next poll to notice.
            self.grab_panel()
            return
        # evtype lives on the GenericEvent wrapper itself; the rest (deviceid,
        # detail, root_x/y, event, time, ...) is in its DictWrapper .data,
        # which -- unlike a plain dict -- has no .get(): index it directly.
        if ev.type != GENERIC_EVENT or getattr(ev, "extension", None) != self.xi_major:
            return
        if getattr(ev, "evtype", None) != xinput.ButtonPress:
            return
        data = ev.data
        # deviceid first and outside the narrower checks below: whichever
        # device this event came from is who XIAllowEvents must target, in
        # every exit path, even one we bail out of early. 2 is the virtual
        # core pointer XI2 reports on ordinary single-pointer setups --
        # a fallback only, in case the field itself is somehow unreadable.
        try:
            deviceid = data["deviceid"]
        except (KeyError, AttributeError):
            deviceid = 2
        mode = XI_REPLAY_DEVICE
        win = None
        try:
            if data["detail"] != X.Button3:
                return
            event_win = data["event"]
            # GrabModeSync freezes *this device's* events until
            # XIAllowEvents. Always release it, even if hit-testing throws
            # (the try/finally below covers everything past this point).
            if event_win is None or event_win.id not in self.grabbed_ids:
                seen = hex(event_win.id) if event_win is not None else None
                debug(f"on_event: xi event window {seen} not in grabbed_ids {[hex(w) for w in self.grabbed_ids]!r}")
                return
            px = int(data["root_x"])
            py = int(data["root_y"])
            win = self.task_at_pointer(px, py)
            hit = hex(win.id) if win else None
            debug(f"on_event: xi click at ({px},{py}) -> {hit} out of {len(self.task_geom)} cached tasks")
            if win is not None:
                mode = XI_ASYNC_DEVICE
        except (error.BadWindow, error.BadDrawable, error.BadAccess) as e:
            debug(f"on_event: exception {e!r}")
            mode = XI_REPLAY_DEVICE
            win = None
        finally:
            self.xi_allow(deviceid, mode)
            # xi_allow()'s flush() only sends our release; it doesn't wait
            # for the server to have actually processed it. GTK's popup
            # grab lives on GDK's own, separate X connection -- if that
            # grab attempt reaches the server first, on real hardware
            # timing (never reproduced with synthetic XTest clicks in
            # testing), it can find the device still marked frozen and
            # fail with no error we'd see, and the menu never appears.
            # A real round trip on our own connection closes that race.
            try:
                self.d.sync()
            except error.Error:
                pass
        if win is not None:
            event_time = data["time"]

            def show_popup(_win=win, _t=event_time):
                try:
                    self.popup(_win, _t)
                except Exception as e:
                    debug(f"on_event: popup() raised {e!r}")
                return False

            # Deferred a tick: calling this inline, in the same dispatch as
            # the raw XI2 event that triggered it, sometimes leaves GTK's
            # own pointer grab for the menu unable to take (the button
            # release for this same click may not have finished settling
            # at the X server yet) -- the menu then shows and immediately
            # self-dismisses. Letting one main-loop iteration pass first
            # reliably avoids the race.
            GLib.idle_add(show_popup)


def main(argv):
    d = display.Display()
    d.set_error_handler(lambda *_a, **_k: None)
    g = Grabber(d)
    try:
        d.screen().root.change_attributes(
            event_mask=X.PropertyChangeMask | X.SubstructureNotifyMask
        )
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
        # Core call is belt-and-braces (nothing holds a core grab, see
        # module docstring); deviceid 2 is the virtual core pointer XI2
        # reports on ordinary single-pointer setups, matching what the
        # real grab is established against (AllMasterDevices).
        g.allow(X.AsyncPointer)
        g.xi_allow(2, XI_ASYNC_DEVICE)
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
