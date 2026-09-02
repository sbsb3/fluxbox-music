# fluxbox-music

A window-manager configuration repo for a **Linux music-production session**
built around DAWs (Renoise, Bitwig Studio, SunVox, Max 9, Hydrogen, Audacity,
PlugData), a JACK/PipeWire graph (Carla, qpwgraph, pavucontrol), and a fixed
3-monitor L-shaped layout.

The repo historically held only the **Fluxbox** session (`~/.fluxbox`). It now
also contains a behavioral **port of that session to Openbox**, developed on
the `openbox-port` branch and staged under [`openbox-port/`](openbox-port/).
**This README focuses on the Openbox port.** The original Fluxbox config is
documented briefly at the end and is left untouched as a fallback session.

- **Upstream:** https://github.com/sbsb3/fluxbox-music.git
- **Branches:** `main` (Fluxbox config) · `openbox-port` (the port, primary
  development branch)
- **WM-agnostic stack:** tint2 (panel) · Plank (dock) · pcmanfm `--desktop`
  (icons) · picom (compositor) · dunst (notifications) — all launched from a
  `startup` script, independent of which WM owns the windows.

---

## Table of contents

1. [Why a port?](#why-a-port)
2. [Quick start (Openbox session)](#quick-start-openbox-session)
3. [Repository layout](#repository-layout)
4. [The Openbox port](#the-openbox-port)
   - [Goals & design constraints](#goals--design-constraints)
   - [Branch model](#branch-model)
   - [Port deliverables & install locations](#port-deliverables--install-locations)
   - [The plan (Phases 0–5)](#the-plan-phases-05)
   - [Known WM-to-WM gaps (design decisions)](#known-wm-to-wm-gaps-design-decisions)
   - [Phase 3 test-first results](#phase-3-test-first-results)
   - [Settings translation inventory](#settings-translation-inventory)
   - [Kiosk sessions](#kiosk-sessions)
5. [Key bindings reference (Openbox)](#key-bindings-reference-openbox)
6. [Window rules / `<applications>`](#window-rules--applications)
7. [Scripts & daemons reference](#scripts--daemons-reference)
8. [Verification status](#verification-status)
9. [Known regressions vs. Fluxbox](#known-regressions-vs-fluxbox)
10. [The original Fluxbox session](#the-original-fluxbox-session)
11. [Development notes & gotchas](#development-notes--gotchas)

---

## Why a port?

Fluxbox only manages windows. Everything user-visible (panel, dock, icons,
compositor, notifications) is a separate process started from `startup`, and a
small fleet of Python daemons (Xlib/xdotool against raw EWMH properties) glue
those processes together and paper over Fluxbox-specific quirks. That means the
bulk of the session is **WM-agnostic** and ports cleanly. The work is in
translating the WM-specific config (`keys`, `apps`, `init`, `windowmenu`,
`menu`) into Openbox's `rc.xml`/`menu.xml`, and pruning the daemons/scripts
that only existed to fix Fluxbox framing behavior.

The port was specified up front in [`openbox-port-plan.md`](openbox-port-plan.md)
and recorded as-built in [`openbox-port/PORT-NOTES.md`](openbox-port/PORT-NOTES.md).
Read those alongside this README for the full reasoning.

---

## Quick start (Openbox session)

> The port was built and tested in nested **Xephyr** sessions per the plan's
> instruction not to disturb the live Fluxbox session. See
> [Verification status](#verification-status) for what is and isn't yet
> validated on real hardware.

1. Install prerequisites: `openbox`, `rofi` (replaces `fbrun`), plus the
   existing stack (`tint2`, `plank`, `pcmanfm`, `picom`, `dunst`, `feh`,
   `autorandr`, `xsettingsd`/`xfsettingsd`, Python 3 with `python-xlib`,
   `wmctrl`, `xdotool`).
2. Deploy the staged files to their real (out-of-repo) locations:
   - `openbox-port/openbox/rc.xml`        → `~/.config/openbox/rc.xml`
   - `openbox-port/openbox/menu.xml`      → `~/.config/openbox/menu.xml`
   - `openbox-port/openbox/autostart`     → `~/.config/openbox/autostart`
   - `openbox-port/openbox/themes/*`      → `~/.config/openbox/themes/`
   - `openbox-port/openbox-music/*`       → `~/.openbox-music/`
   - `openbox-port/openbox-music/tint2/*` → `~/.config/tint2/`
3. Add a LightDM `.desktop` entry (or `.xsession`) that execs
   `~/.openbox-music/startup`, mirroring how `/usr/bin/startfluxbox` execs
   `~/.fluxbox/startup`. **Do not remove the existing Fluxbox entry** — keep
   it as a fallback (Phase 5).
4. Log out, pick the new session, log in.

Reconfigure live after edits: `openbox --reconfigure` (replaces
`fluxbox-remote Reconfigure`).

---

## Repository layout

```
.                               # ~/.fluxbox — original Fluxbox session (main branch)
├── init                         # Fluxbox session config (focus, snapping, layers, struts, …)
├── keys                         # Fluxbox key + mouse bindings
├── apps                         # Fluxbox per-app rules (layers, decor, stick, …)
├── menu                         # Fluxbox root menu
├── windowmenu                   # Fluxbox client (window) menu
├── startup                      # LightDM entry point (exec'd by /usr/bin/startfluxbox)
├── overlay  Xresources  styles/ backgrounds/ pixmaps/  # theme/wallpaper/icon assets
├── apply-workspaces.sh  panel-size.sh  workspace-switch.sh  audacious-follow.sh
├── *.py                         # WM-agnostic Xlib/xdotool daemons (see Scripts reference)
├── openbox-port-plan.md         # the spec (Phases 0–5, 8 known gaps)
└── openbox-port/                # the port (openbox-port branch)  ← primary focus
    ├── PORT-NOTES.md            # as-built report (test-first results, corrections, gotchas)
    ├── openbox/                 # staged ~/.config/openbox
    │   ├── rc.xml  menu.xml  autostart
    │   └── themes/ClearlooksDarkMenu/openbox-3/themerc
    ├── openbox-music/           # staged ~/.openbox-music (startup + scripts + tint2 + launchers)
    ├── music-kiosk-staging/     # Openbox + Plank kiosk for DAWs-on-demand
    └── renoise-staging/         # fullscreen-Renoise kiosk
```

Files that end up living outside this repo (`~/.config/openbox/*`,
`~/.openbox-music/*`, `~/.config/tint2/*`) are **not tracked** by this repo's
git once deployed — the staged copies under `openbox-port/` exist so the port
is reviewable as a diff.

---

## The Openbox port

### Goals & design constraints

- **Behavioral equivalence for daily use**, launched the same way Fluxbox is
  now (LightDM session script execs a `startup` file).
- **Do not touch the live Fluxbox session while working.** Build the new
  config in `~/.config/openbox/` + `~/.openbox-music/`; keep `~/.fluxbox`
  working as a fallback until the port is verified on real hardware.
- **Super (Mod4) stays the session modifier** so Ctrl/Alt remain available to
  DAWs. **F-key workspace binds are omitted on purpose** (Renoise, Bitwig,
  SunVox, and Max all use F-keys).
- **Two workspaces, `Internet` / `Audio`**, static in `rc.xml` — no runtime
  `fluxbox-remote` dance to create/name them.
- **No silent omissions.** Anything that can't be translated is listed
  explicitly as dropped (see [Settings translation inventory](#settings-translation-inventory)).

### Branch model

- `main` — the original Fluxbox config. Untouched by the port.
- `openbox-port` — branched off `main`; all port work happens here. The staged
  files under `openbox-port/` are the reviewable diff.

### Port deliverables & install locations

| In-repo (staged, tracked)                              | Deployed (out-of-repo, untracked)        |
| ------------------------------------------------------ | ---------------------------------------- |
| `openbox-port/openbox/rc.xml`                          | `~/.config/openbox/rc.xml`               |
| `openbox-port/openbox/menu.xml`                        | `~/.config/openbox/menu.xml`             |
| `openbox-port/openbox/autostart`                       | `~/.config/openbox/autostart`            |
| `openbox-port/openbox/themes/ClearlooksDarkMenu/...`   | `~/.config/openbox/themes/...`           |
| `openbox-port/openbox-music/startup` + scripts + daemons | `~/.openbox-music/`                    |
| `openbox-port/openbox-music/tint2/*.tint2rc`           | `~/.config/tint2/`                       |
| `openbox-port/openbox-music/launchers/music-menu.desktop` | `~/.openbox-music/launchers/`        |
| `openbox-port/music-kiosk-staging/*`                   | `/usr/local/bin/music-kiosk`, Plank profile, LightDM entry, sudoers |
| `openbox-port/renoise-staging/*`                       | `/usr/local/bin/renoise-kiosk`, LightDM entry, sudoers               |

`autostart` is guarded by `$OPENBOX_MUSIC_SESSION`: a normal Openbox login
runs the music-session setup from `autostart`, while the dedicated
`~/.openbox-music/startup` session sets that env var and starts the same stack
itself — without the guard, both paths would spawn overlapping tint2 windows
and `task-menu.py` could grab only one of their input frames.

### The plan (Phases 0–5)

Defined in [`openbox-port-plan.md`](openbox-port-plan.md):

- **Phase 0 — inventory & prerequisites.** Confirm Openbox + a run-launcher
  are installed; read every `~/.fluxbox` file (especially the `.py`
  docstrings, which explain *why* each daemon exists — load-bearing for
  deciding whether it must change); locate the session entry mechanism.
- **Phase 1 — static config translation.** Author `rc.xml` (`<keyboard>`,
  `<mouse>`, `<applications>`, `<desktops>`, focus/placement/snap settings)
  and `menu.xml` (root menu + client-menu).
- **Phase 2 — startup script.** Adapt `~/.fluxbox/startup` into
  `~/.openbox-music/startup`: keep env/xset/autorandr/xsettingsd/xrdb/feh/
  dunst/tray blocks, swap the Fluxbox launch block for Openbox, keep the
  WM-agnostic daemons.
- **Phase 3 — script-by-script adjustment.** Not a blanket copy: each script
  is evaluated against the known gaps and tested before porting (see below).
- **Phase 4 — verification checklist.** Manual/Xephyr smoke tests before
  touching the display manager.
- **Phase 5 — cut over.** Add a new LightDM entry; do **not** remove the
  Fluxbox entry; leave it as a fallback for at least one full work session.

### Known WM-to-WM gaps (design decisions)

These were decided *before* coding and are not to be re-litigated mid-port.
(Quoted/paraphrased from `openbox-port-plan.md`; see that file for full text.)

1. **Layers collapse 5 → 3.** Fluxbox named layers (Plank=AboveDock/2,
   tint2=Dock/4, Audacious=Top/6, Renoise+plugin server=Normal/8,
   pcmanfm-desktop=Desktop/12) map to Openbox's `above`/`normal`/`below`.
   Plank, tint2, Audacious → `above`; Renoise + plugin server → default
   `normal`; pcmanfm desktop needs no `<layer>` (its
   `_NET_WM_WINDOW_TYPE_DESKTOP` hint already sinks it).
2. **No window tabbing/grouping in Openbox.** Drop `tabs.*`/`tab.*` settings
   and the `StartTabbing` mouse bind. Not a bug — just omit.
3. **No `fbrun`.** Replace with `rofi -show run` (fallback `gmrun`/
   `dmenu_run`). Bind to `Mod4 d` *and* `Mod1 F2` (the plan's gap #3 only
   named the first; the keys file has both — both are ported). Launcher
   geometry is the launcher's own config, not a WM apps rule.
4. **`windowmenu` (client menu) loses features.** Openbox's `client-menu`
   has no built-in alpha/opacity slider and no `extramenus` equivalent. Port
   the rest; note the opacity slider as dropped. **Correction from live
   testing:** in Openbox 3.6.1 `client-menu` is fully hardcoded in the binary
   — a `<menu id="client-menu">` block in `menu.xml` is silently ignored
   (Alt+Space / right-click-titlebar always pop Openbox's own built-in menu:
   Send to desktop / Layer / Restore / Move / Resize / Iconify / Maximize /
   Roll up-down / Un-Decorate / Close). Net coverage is actually *better* for
   the parts `windowmenu` already had; the custom block was replaced with a
   comment. Newly dropped with no built-in substitute: `[stick]` (sticky
   toggle — still reachable via the `ToggleOmnipresent` action bound to the
   `AllDesktops` mouse context, just not from this menu) and `[alpha]`/
   `[extramenus]`.
5. **Edge-triggered workspace warping is not stock Openbox.** Fluxbox's
   `workspacewarping*` (mouse at screen edge → switch workspace) has no
   `rc.xml` equivalent. Out of scope for v1; documented as a known regression.
6. **`fluxbox-remote`-based scripts need rewriting, not translating.**
   `apply-workspaces.sh` and `panel-size.sh` call `fluxbox-remote` for things
   Openbox does statically (`<desktops>`) or via `openbox --reconfigure`.
7. **`plank-input-shape.py` may be unnecessary.** Its docstring says it
   exists because Fluxbox reparents Plank and copies only the bounding shape
   (not the input shape) onto the frame. Test under bare Openbox before
   porting. (Result: **not needed** — see Phase 3 results.)
8. **Strut handling may be simpler.** `panel-size.sh` writes
   `session.screen0.struts.1` directly into the Fluxbox `init` to force a
   specific Xinerama head's reserved space. Test whether Openbox already
   honors tint2's own `_NET_WM_STRUT_PARTIAL` per-head without a WM-side
   override before porting that logic.

### Phase 3 test-first results

From [`openbox-port/PORT-NOTES.md`](openbox-port/PORT-NOTES.md) — these are
**live test results**, not plan predictions.

1. **`xfsettingsd` fight (`apply-workspaces.sh`) — NEEDED, confirmed live.**
   Started `xfsettingsd --replace` in an Xephyr+Openbox session with the
   static 2-desktop config already loaded; within ~2s `_NET_DESKTOP_NAMES`
   was rewritten to `"Internet", "Dev", ""` and `wmctrl -d` showed the live
   taskbar name change from `Audio` to `Dev`. This is a root-window property
   write, not routed through the WM, so it reproduces identically regardless
   of which WM owns the desktop — **not** Fluxbox-specific as the plan
   speculated. The script is kept but shrunk to just this fight; the old
   `fluxbox-remote` add/remove/rename-workspace logic is dead now that desktop
   count/names are static in `rc.xml`.

   Second finding: **Openbox does not self-heal a corrupted
   `_NET_DESKTOP_NAMES` from its own `rc.xml`, ever** — neither
   `openbox --reconfigure` nor a full kill+restart restores the names once
   something else has overwritten them (verified both ways in the same
   Xephyr session: the corrupted `Dev` survived both). Openbox treats existing
   root-window desktop state as authoritative over `rc.xml` on every
   (re)start. Neither `wmctrl` nor `xdotool` can rewrite
   `_NET_DESKTOP_NAMES` directly, so `apply-workspaces.sh`'s repair step
   writes the property via a small inline Xlib call (same dependency every
   other script here already has). Confirmed it sticks once `xfsettingsd` is
   dead.

2. **`plank-input-shape.py` — NOT NEEDED, confirmed live.** `xwininfo -root
   -tree` under Openbox with Plank running shows Plank's dock and tooltip
   windows are direct children of root with no wrapping frame window at all.
   There's nothing for the Fluxbox-reparenting bug to attach to. The daemon
   and its startup block are **dropped, not ported.** (If click-through
   problems over the dock area turn up in real use with real DAW windows,
   that would contradict this and the daemon should be revisited — flagged
   in the Phase 4 checklist.)

3. **Strut handling (`panel-size.sh`'s `set_fluxbox_strut`) — PARTIALLY
   RESOLVED; real-hardware verification still needed.** The actual problem
   `struts.1` solved was never "does the WM honor STRUTs" (both do) — it's
   that on this session's L-shaped 3-head layout, tint2's own
   `strut_policy=follow_size` reserves space relative to the *virtual screen*
   edge, which doesn't line up with "top of the primary monitor"
   specifically. Fluxbox's fix was a static per-Xinerama-head override that
   tint2 itself has no way to express.

   Openbox's `rc.xml` schema has no per-monitor equivalent (`<margins>` is a
   single value applied to the whole desktop), so `set_fluxbox_strut()` is
   **dropped outright**, and `openbox --reconfigure` (its only other job) has
   nothing left to call either. The only remaining lever is tint2's own strut
   mechanism: `strut_policy` flipped from `none` to `follow_size` in the new
   `openbox-music*.tint2rc` files (tint2 already has `panel_monitor =
   primary`). Single-monitor Xephyr test confirms the mechanism works in
   principle (`_NET_WORKAREA` shrank to `0,56,1280,744`). **Not yet verified
   on the real 3-monitor L-shaped layout.** If maximized windows still tuck
   under the panel there, try tint2's `panel_pivot_struts = 1` next; if
   neither works, the documented fallback is `strut_policy = none` and
   accepting the panel visually overlapping maximized windows on the primary
   head as a known regression (harmless since tint2 stays `layer=above`).

### Settings translation inventory

**Translated** (direct Openbox equivalent):

| Fluxbox `init`                     | Openbox `rc.xml`                         |
| ---------------------------------- | ---------------------------------------- |
| `edgeSnapThreshold: 8`             | `<resistance><strength>8</strength>...`  |
| `focusModel ClickFocus`            | `<followMouse>no</followMouse>`          |
| `focusNewWindows`                  | `<focusNew>`                             |
| `opaqueResize: false` (outline)    | `<drawContents>no</drawContents>`        |
| `doubleClickInterval`              | `<doubleClickTime>`                      |
| `menuDelay`                        | `<submenuShowDelay>`                     |
| `workspaces` / `workspaceNames`    | `<desktops>`                             |

Note: Fluxbox `opaqueMove` has no Openbox toggle — Openbox always moves windows
opaquely. `opaqueResize: false`'s literal equivalent is `<drawContents>no`
(show outline while resizing), not `opaqueMove`.

**Dropped** (no Openbox equivalent — listed, not silently omitted):

- Gaps already called out in the plan: `workspacewarping*` (#5),
  `tabs.*`/`tab.*` (#2).
- Fluxbox-internal knobs with no analogue: `maxIgnoreIncrement`,
  `ignoreBorder`, `showwindowposition`, `noFocusWhileTypingDelay` (was 0,
  a no-op), `colorsPerChannel`, `cacheMax`/`cacheLife`, `configVersion`,
  `forcePseudoTransparency` (moot — picom does real transparency),
  `allowRemoteActions` (moot — CLI control is always available).
- Unused in this session already (tint2/Plank replaced them):
  `toolbar.*`, `slit.*`, `iconbar.*`.
- `window.focus.alpha`/`unfocus.alpha` — both 255 (fully opaque), already a
  no-op.
- `autoRaise`/`autoRaiseDelay` — Fluxbox had autoRaise off and relied on
  click-to-raise; that's the default Frame-click behavior in `rc.xml`'s
  `<mouse>` section, nothing to configure.
- `fullMaximization: false` — matches Openbox's default (maximize respects
  workarea/struts; a separate `MaximizeFull` action exists if ever wanted).
- `rowPlacementDirection`/`colPlacementDirection` — no Openbox knob at this
  granularity for Smart placement; approximated with `<center>no</center>`.
- `strftimeFormat` (Fluxbox toolbar clock) — moot; tint2 owns the clock and
  has its own format config, untouched by this port.

### Kiosk sessions

Two extra Openbox sessions live under `openbox-port/` and are deployed to
system locations (LightDM entries, `/usr/local/bin/*`, sudoers rules).

**`music-kiosk-staging/` — Music kiosk.** Openbox + `plank -n kiosk`, with
DAWs (Renoise, Bitwig, SunVox, Max 9) plus support tools (Audacious, Audacity,
Carla, Hydrogen, pavucontrol, qpwgraph, PlugData, ZynAddSubFX, WezTerm, Gajim,
and a graphical logout launcher) as the only Plank dock entries. DAWs are
launched **on demand** from Plank — the script does not auto-start any of
them, so there's no single foreground app to tie the session lifetime to.
Instead Openbox runs in the background and the script blocks on
`wait $obpid`; the session ends when Openbox exits — via the
`Ctrl-Alt-End` keybinding in `rc.xml` (`Exit` action) or by killing Openbox.

Kiosk specifics refined through many commits:
- 3-monitor XFCE-exact layout; portrait `DP-2` placed on the left; `HDMI-0`
  gamma tint.
- Plank `hide-mode=auto` with `pressure-reveal=true` + unhide-delay, so the
  dock hides but reveals on mouse-edge even over maximized DAWs (earlier
  attempts used `hide-mode=none` then `auto`; landed on `auto` after finding
  `none` kept the dock visible over fullscreen Renoise but `auto` with
  pressure reveal gives the best of both).
- DAWs run **maximized** (not fullscreen) so Plank can reveal over them.
- `feh` root pixmap for a black background (fixes white strips on the rotated
  `DP-2`); desktop context menu removed.
- `picom` started for Plank animations.
- **`max-fix.py`** — a pure-Xlib event-driven daemon that catches Max 9's
  JUCE toolkit fighting the WM: JUCE strips fullscreen/maximized state and
  auto-sets fullscreen over Plank on patcher windows. The daemon resizes
  offending windows to `1918x1078` (2px shy) to avoid JUCE auto-fullscreen,
  watches `WM_NORMAL_HINTS`, offsets for the 18px frame so the title bar
  stays visible, and only acts on fullscreened/maximized windows (leaving
  helper patches alone). Alt-Tab is also bound in the kiosk `rc.xml`.
- **`sunvox-fix.py`** — Xlib daemon that pins SunVox at DP-4 top-left
  (`2456,352` at `1920x1062`) on launch. SunVox's SunDog engine writes
  an off-screen `user specified location` into `WM_NORMAL_HINTS` at
  startup and `XMoveWindow`s itself there shortly after mapping, so the
  `<position force="yes">` rule (which only applies once, on initial
  placement) loses. The watcher catches `MapNotify`/`ConfigureNotify`/
  `WM_NORMAL_HINTS` on sunvox class windows for the first ~3 seconds
  after launch and force-positions them; after the per-window deadline
  elapses the user can move/resize freely. Strips `MAXIMIZED` so the
  window stays windowed (matching the `rc.xml` intent).
- A `.sudoers` file lets the logout launcher terminate the session without a
  password.

**`renoise-staging/` — Renoise kiosk.** Fullscreen Renoise on the primary
`DP-4`, with the portrait `DP-2` kept alive for plugin windows. Unlike the
music kiosk, this one ties the session lifetime to Renoise. Includes a
`deploy.sh`, `renoise-kiosk.desktop`, and sudoers rule. Tuned across commits:
fix DPI, kill orphaned `tint2` watchdogs, neutralize `autorandr.service`,
drop the respawn loop, force the window onto `DP-4`, stop the shared autostart
hook from undoing it, place the portrait `DP-2` on the left, fix an XML
comment.

---

## Key bindings reference (Openbox)

Ported from `~/.fluxbox/keys` into `openbox-port/openbox/rc.xml`. Modifier
syntax: Fluxbox `Mod4` → Openbox `W`. Super is the session modifier so
Ctrl/Alt stay available to DAWs; F-key workspace binds are omitted on purpose.

- **Root menu:** `W-space` (and right-click desktop) — opens the ported root
  menu.
- **Run launcher:** `W-d` and `Alt-F2` — both `rofi -show run` (replaces
  `fbrun`; the plan only named `W-d` but `keys` had both).
- **Reconfigure:** `W-Shift-r` — `openbox --reconfigure` (replaces
  `fluxbox-remote Reconfigure`).
- **Window menu / Send To:** right-click titlebar/border/grips, and `W-Right`
  on titlebar-less DAWs (Renoise, Bitwig, Max) — plain right-click stays with
  the app. Pops Openbox's built-in client-menu (see gap #4 correction).
- **Move/resize without stealing DAW Ctrl bindings:** `Alt-Left` on a window
  raises+focuses+starts move; `Alt-Right` raises+focuses+starts resize from
  nearest corner; `Alt-Middle` lowers.
- **Maximize:** double-click titlebar (not shade/roll-up).
- **Sticky/omnipresent:** `ToggleOmnipresent` bound to the `AllDesktops`
  mouse context (replaces the `windowmenu` `[stick]` entry that has no
  client-menu equivalent).
- **Desktop switch:** wheel on desktop = prev/next workspace; right-click
  desktop = workspace menu.
- **Dropped binds:** `StartTabbing` (gap #2, no tabbing in Openbox).

See `openbox-port/openbox/rc.xml` for the full `<keyboard>` and `<mouse>`
blocks, including the intent-preserving comments carried over from `keys`.

---

## Window rules / `<applications>`

Ported from `~/.fluxbox/apps` into `rc.xml`'s `<applications>` section. One
`<application>` block per `apps` entry:

- **`fbrun`** → dropped (gap #3; the replacement launcher isn't
  WM-positioned this way).
- **`Tint2`, `Plank`** → `<layer>above</layer>`, `<decor>no</decor>`,
  `<skip_taskbar>yes</skip_taskbar>`, `<skip_pager>yes</skip_pager>`, sticky.
- **pcmanfm desktop window** (`class=Pcmanfm`,
  `_NET_WM_WINDOW_TYPE=.*DESKTOP.*`) → decor off, skip taskbar/pager; **no
  `<layer>` needed** (its desktop hint already sinks it — gap #1).
- **`Renoise`, `Renoise Plugin Server`** → no layer override (default
  `normal`), with the explanatory comment carried over from `apps` about why
  they must stay Normal (the old AboveDock workaround was for Plank's
  oversized Fluxbox frame covering the bottom of maximized DAWs;
  `plank-input-shape.py` fixed that under Fluxbox, and under Openbox the
  frame doesn't exist at all — so Normal is correct in both ports now).
- **`Audacious`** (`role=mainwindow`/`equalizer`/`playlist`) →
  `<layer>above</layer>`, `<decor>no</decor>`, with the comment that
  positions are restored by `audacious-stack.py` (still relevant).

Layer mapping summary (gap #1): Fluxbox's 5 named layers → Openbox's 3.
Plank/tint2/Audacious → `above`; Renoise + plugin server → `normal`;
pcmanfm desktop → implicit (via window-type hint).

---

## Scripts & daemons reference

The session's glue layer. Most are **WM-agnostic** (talk to tint2 / EWMH /
raw Xlib, not to the WM) and ported unchanged; the rest are adjusted or
dropped per Phase 3. `grep -n fluxbox *.py` confirms no `fluxbox-remote` calls
in the `.py` files — only in the two `.sh` files below.

| File                       | Status under Openbox | Role                                                                 |
| -------------------------- | -------------------- | ------------------------------------------------------------------- |
| `startup`                  | adapted              | LightDM entry point; launches Openbox + the whole stack             |
| `apply-workspaces.sh`      | **shrunk**           | Now only the xfsettingsd fight + inline-Xlib `_NET_DESKTOP_NAMES` repair (desktop count/names are static in `rc.xml`) |
| `panel-size.sh`            | **simplified**       | `set_fluxbox_strut()` dropped (no per-monitor `rc.xml` equivalent); `openbox --reconfigure` call dropped (nothing left to reload); now just swaps the tint2 rc file + resyncs desktop icons |
| `workspace-switch.sh`      | unchanged            | wmctrl-based; `show`/`goto`/`delta` confirmed WM-agnostic            |
| `audacious-follow.sh`      | unchanged            | Talks to tint2 + EWMH; `on`/`off`/`toggle`                           |
| `audacious-stack.py`       | unchanged            | Restores Audacious's three Winamp-skin windows' positions after restart/resume |
| `desktop-heads.py`         | unchanged            | Supervised restart / head-aware desktop helper                      |
| `taskbar-sync.py`          | unchanged            | Keeps tint2's taskbar showing the current desktop's buttons         |
| `task-menu.py`             | adjusted (path)      | Right-click task button → send-to-workspace menu; `panel-hidden` IPC path relocated to `~/.openbox-music/panel-hidden` (must match `fullscreen-panel.py`) |
| `fullscreen-panel.py`      | adjusted (path)      | Hides tint2/Plank while a fullscreen window covers their head; same `panel-hidden` IPC path relocation |
| `window-icons.py`          | unchanged            | Fixes task icons clobbered by apps' own placeholders                |
| `plank-input-shape.py`     | **dropped**          | Fluxbox-only framing bug doesn't reproduce under Openbox (Plank is a direct child of root, no wrapping frame) |
| `launchers/music-menu.desktop` | adjusted          | `fluxbox-remote RootMenu` → `xdotool key super+space` (Openbox has no remote-menu-popup verb); verified live to pop the real ported root menu |
| `fbrun_history`            | dropped              | Irrelevant once `fbrun` is replaced (gap #3)                        |
| `slitlist`                 | not ported           | Fluxbox slit unused in this session already (tint2/Plank replaced it) |

The `panel-hidden` IPC flag path is shared between `fullscreen-panel.py` and
`task-menu.py`; it was relocated to `~/.openbox-music/panel-hidden` in **both**
files identically, or the two daemons would silently stop agreeing with each
other after the move (latent bug caught while relocating).

`picom`/`dunst` configs (`~/.config/picom/fluxbox-music.conf`,
`~/.config/dunst/fluxbox-music.conf`) are intentionally left with their
existing names and referenced unchanged — their content is WM-agnostic, so
renaming would be churn with no behavior difference. Same for pcmanfm's
`--profile fluxbox-music` (a pcmanfm config-profile name, unrelated to which
WM is running).

---

## Verification status

**Verified live in nested Xephyr sessions** (per the plan: don't touch the
live Fluxbox session while working):

- `rc.xml` and `menu.xml` parse and load cleanly from `~/.config/openbox/`.
- 2 desktops named `Internet`/`Audio` at a clean start, no
  `fluxbox-remote`-style dance needed.
- `openbox --reconfigure` works without dropping the session.
- Root menu (`W-space`, and via `xdotool key super+space` standing in for the
  old `fluxbox-remote RootMenu`) opens the ported menu with correct
  structure, icons, and submenus.
- Client menu (Alt+Space) opens Openbox's built-in menu; Send to desktop /
  Layer / Close all work.
- `workspace-switch.sh show/goto/delta` work unmodified (wmctrl-based,
  confirmed WM-agnostic).
- `desktop-heads.py --once`, `taskbar-sync.py`, `task-menu.py`,
  `fullscreen-panel.py`, `audacious-stack.py`, `window-icons.py` all start
  and run cleanly against a live Openbox session with no tracebacks
  (smoke-tested per Phase 3, not edited blind).
- Full `~/.openbox-music/startup` end-to-end: Openbox, tint2 (with the real
  panel showing live Internet/Audio labels), Plank, pcmanfm desktop (rendering
  the real icons), and the daemons all come up together without crashing.

**Test-environment caveats** (not port bugs): dunst and the polkit agent
couldn't acquire their D-Bus names in Xephyr because the nested session
shares a D-Bus session bus with the already-running live session — won't
happen in a real separate login. Plank exited after ~20s in the same test
because its single-instance-per-dock-name handling collided with the live
session's already-running `plank -n music` (reused profile name) — also won't
happen in a real separate login.

**Not yet tested (needs the real 3-monitor hardware / a real login):**

- The strut / `panel_pivot_struts` question on the actual L-shaped layout
  (see Phase 3 item 3).
- Renoise/plugin-server layer behavior under a real maximized DAW window,
  and Plank/tint2 hide behavior under a real Steam fullscreen game
  (`fullscreen-panel.py`'s detection logic was smoke-tested for crashes only).
- Audacious's real three-window stacking behavior after a restart/resume
  (needs Audacious actually running with the Winamp skin).
- `panel-size.sh normal|compact|toggle` end-to-end against the real monitors
  (logic reviewed and syntax-checked; the strut-writing half was removed, so
  the remaining restart-tint2-and-resync-desktop behavior needs a real test).

Phase 5 (cut over: add a LightDM entry, log out, do a real end-to-end test,
keep Fluxbox as fallback) is **not yet performed** — by design it waits until
the real-hardware items above pass.

---

## Known regressions vs. Fluxbox

- **Edge-triggered workspace warping** (`workspacewarping*`) — no Openbox
  equivalent (gap #5).
- **Window tabbing/grouping** (`tabs.*`, `StartTabbing`) — no Openbox
  equivalent (gap #2).
- **Opacity slider in the client menu** (`[alpha]`) and `extramenus` — no
  Openbox equivalent (gap #4). `[stick]` is also absent from Openbox's
  hardcoded client-menu (still reachable via the `ToggleOmnipresent` action).
- **Per-Xinerama-head strut override** (`session.screen0.struts.1`) — no
  `rc.xml` equivalent; replaced by tint2's own `strut_policy=follow_size`,
  which may not fully cover the L-shaped 3-head case (see Phase 3 item 3 /
  Verification status). Fallback: `strut_policy=none` and accept visual
  overlap on the primary head (harmless, tint2 stays `layer=above`).

Everything else is either translated 1:1, adjusted with equivalent behavior,
or was already unused under Fluxbox.

---

## The original Fluxbox session

The `main` branch holds the original, still-live Fluxbox config. It is the
**source of truth** the port was translated from and remains the fallback
session.

- **Entry point:** LightDM runs `/usr/bin/startfluxbox`, which execs
  `~/.fluxbox/startup`. XFCE autostart is intentionally **not** run.
- **Config files:** `init` (session/focus/snap/layers/struts),
  `keys` (key + mouse bindings), `apps` (per-app layer/decor/stick rules),
  `menu` (root menu), `windowmenu` (client menu, incl. alpha slider + Send
  To + extramenus), `overlay`/`Xresources`/`styles/`/`backgrounds/`/`pixmaps/`
  (theme/wallpaper/icons).
- **Workspaces:** `Internet`, `Audio` (kept in sync against xfsettingsd by
  `apply-workspaces.sh`'s `fluxbox-remote` calls — the logic the Openbox port
  shrinks).
- **Fluxbox-specific daemon:** `plank-input-shape.py` exists only because
  Fluxbox reparents Plank and copies only the bounding shape onto the frame;
  not needed under Openbox (Plank is a direct child of root there).

Everything else (tint2, Plank, pcmanfm, picom, dunst, and the WM-agnostic
daemons) is identical between the two sessions.

---

## Development notes & gotchas

- **XML comments can't contain `--`.** Openbox's XML parser rejects `--`
  inside a comment (standard XML rule). Both `rc.xml` and `menu.xml` hit this
  repeatedly during testing; em-dash-style `--` was turned into single
  hyphens.
- **`<menu><file>` in `rc.xml` resolves relative to Openbox's config search
  path** (`~/.config/openbox/`, falling back to `/etc/xdg/openbox/`), **not**
  relative to whatever `--config-file` path you passed. Building `rc.xml` +
  `menu.xml` in a repo staging dir and pointing `--config-file` at the staged
  `rc.xml` silently loaded the *system's* stock `menu.xml` instead of the
  ported one (parse errors in the staged `menu.xml` also fell back the same
  way — which is how this got caught). Test against the real
  `~/.config/openbox/` location once content is ready; that's where these
  files live anyway.
- **Openbox treats existing root-window desktop state as authoritative over
  `rc.xml` on every (re)start**, not just at first login. A corrupted
  `_NET_DESKTOP_NAMES` survives `--reconfigure` and a full kill+restart. The
  repair must write the root-window property directly (`apply-workspaces.sh`
  does this via inline Xlib).
- **No `fluxbox-remote` equivalent for menu popup.** Openbox has no
  remote-menu-popup verb; `launchers/music-menu.desktop` uses
  `xdotool key super+space` to replay the keypress `rc.xml` already binds to
  the root menu.
- **Unrelated live-session finding (fixed in passing):** `/tmp/desktop-heads.log`
  (the live Fluxbox session's supervised-restart log for `desktop-heads.py`)
  had grown to 1.6 GB and filled the 2 GB `/tmp` tmpfs, causing unrelated
  tool flakiness. Pre-existing, not a port issue. Truncated the file (safe —
  the running process keeps its open handle and keeps appending). Worth a
  separate look at log rotation / crash-looping.
- **Untracked `debug/`** holds ad-hoc debugging tools (e.g. `tb-watch.py`)
  not referenced by `startup`; out of scope for the port and untouched.

See [`openbox-port-plan.md`](openbox-port-plan.md) for the full spec and
[`openbox-port/PORT-NOTES.md`](openbox-port/PORT-NOTES.md) for the as-built
report (including every correction to the plan's predictions made during live
testing).
