#!/usr/bin/env python3
"""Stamp desktop-launcher icons onto windows that never publish one.

tint2 tasks use _NET_WM_ICON / WMHints. SunVox and Bitwig leave those empty,
so the panel falls back to its generic document placeholder. Desktop and
Plank already resolve Icon= from the .desktop file. Copy that PNG onto the
client window so the task button matches the launcher.

Bitwig's WM_CLASS is a single string (not instance+class), so XGetClassHint
returns None; the raw property is what we match.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from shutil import which

from Xlib import X, Xatom, display, error

POLL = 2.0
DEBOUNCE = 0.25
PIX = Path.home() / ".fluxbox" / "pixmaps"

# WM_CLASS token (lowercase) -> pixmap candidates (PIX-relative or absolute)
ICONS = {
    "sunvox": (
        "sunvox.png",
        "/usr/share/icons/hicolor/64x64/apps/sunvox.png",
        "/usr/share/icons/hicolor/32x32/apps/sunvox.png",
    ),
    "com.bitwig.bitwigstudio": (
        "bitwig.png",
        "/usr/share/icons/hicolor/48x48/apps/com.bitwig.BitwigStudio.png",
    ),
}


def intern(d, name):
    return d.intern_atom(name)


def resolve_icon(candidates):
    for name in candidates:
        path = Path(name)
        if not path.is_absolute():
            path = PIX / name
        if path.is_file():
            return path
    return None


def class_tokens(d, win, atom_class):
    tokens = []
    try:
        hint = win.get_wm_class()
    except (error.BadWindow, error.BadDrawable):
        return []
    if hint:
        tokens.extend(hint)
    try:
        prop = win.get_full_property(atom_class, Xatom.STRING)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        prop = None
    if prop and prop.value:
        raw = prop.value
        if isinstance(raw, bytes):
            parts = raw.split(b"\x00")
        else:
            parts = [raw]
        for part in parts:
            if isinstance(part, bytes):
                part = part.decode("utf-8", "replace")
            if part:
                tokens.append(str(part))
    out = []
    seen = set()
    for t in tokens:
        key = t.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def icon_for(tokens):
    for t in tokens:
        if t in ICONS:
            path = resolve_icon(ICONS[t])
            if path:
                return t, path
    return None, None


def has_net_icon(win, atom_icon):
    try:
        prop = win.get_full_property(atom_icon, X.AnyPropertyType)
    except (error.BadWindow, error.BadDrawable, error.BadAtom):
        return False
    return bool(prop) and len(prop.value) >= 4


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


def png_to_icon_data(path):
    from PIL import Image

    src = Image.open(path).convert("RGBA")
    sizes = []
    w0, h0 = src.size
    for size in (w0, 48, 32):
        if size < 16:
            continue
        if size not in sizes:
            sizes.append(size)
    data = []
    for size in sizes:
        im = src if src.size == (size, size) else src.resize(
            (size, size), Image.Resampling.LANCZOS
        )
        w, h = im.size
        data.extend([w, h])
        raw = im.tobytes("raw", "RGBA")
        for i in range(0, len(raw), 4):
            r, g, b, a = raw[i : i + 4]
            data.append((a << 24) | (r << 16) | (g << 8) | b)
    return data


def set_icon_property(d, win, atom_icon, path):
    try:
        data = png_to_icon_data(path)
        win.change_property(atom_icon, Xatom.CARDINAL, 32, data)
        d.flush()
        return True
    except Exception:
        return False


def set_icon_xseticon(win, path):
    exe = which("xseticon")
    if not exe:
        return False
    try:
        r = subprocess.run(
            [exe, "-id", hex(win.id), str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return r.returncode == 0
    except OSError:
        return False


def apply_window(d, win, atom_class, atom_icon, applied):
    tokens = class_tokens(d, win, atom_class)
    key, path = icon_for(tokens)
    if not key:
        return
    wid = win.id
    stamp = (key, str(path), path.stat().st_mtime)
    if has_net_icon(win, atom_icon):
        applied[wid] = stamp
        return
    ok = set_icon_property(d, win, atom_icon, path)
    if not ok:
        ok = set_icon_xseticon(win, path)
    if ok:
        applied[wid] = stamp


def apply_all(d, atom_list, atom_class, atom_icon, applied):
    live = set()
    for win in iter_clients(d, atom_list):
        live.add(win.id)
        try:
            apply_window(d, win, atom_class, atom_icon, applied)
        except (error.BadWindow, error.BadDrawable, error.BadAtom):
            continue
    for wid in list(applied):
        if wid not in live:
            del applied[wid]


def main(argv):
    once = "--once" in argv
    d = display.Display()
    atom_list = intern(d, "_NET_CLIENT_LIST")
    atom_class = intern(d, "WM_CLASS")
    atom_icon = intern(d, "_NET_WM_ICON")
    applied = {}

    apply_all(d, atom_list, atom_class, atom_icon, applied)
    if once:
        return

    root = d.screen().root
    root.change_attributes(event_mask=X.PropertyChangeMask | X.SubstructureNotifyMask)
    pending = False
    due = 0.0
    next_poll = time.monotonic() + POLL

    while True:
        now = time.monotonic()
        if d.pending_events():
            ev = d.next_event()
            et = getattr(ev, "type", None)
            if et == X.PropertyNotify:
                if getattr(ev, "atom", None) == atom_list:
                    pending = True
                    due = now + DEBOUNCE
            elif et in (X.MapNotify, X.CreateNotify, X.ReparentNotify):
                pending = True
                due = now + DEBOUNCE
        else:
            time.sleep(0.05)

        now = time.monotonic()
        if pending and now >= due:
            pending = False
            apply_all(d, atom_list, atom_class, atom_icon, applied)
            next_poll = now + POLL
        elif now >= next_poll:
            apply_all(d, atom_list, atom_class, atom_icon, applied)
            next_poll = now + POLL


if __name__ == "__main__":
    main(sys.argv)
