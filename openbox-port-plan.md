# Plan: port `~/.fluxbox` music-production session to Openbox

## Context (read this before touching anything)

Source config lives in `~/.fluxbox` (this repo). It is a Fluxbox session used
for music production: Fluxbox itself only manages windows — the panel
(tint2), dock (Plank), desktop icons (pcmanfm), compositor (picom), and
notifications (dunst) are all separate processes launched from
`~/.fluxbox/startup`. A set of Python daemons (Xlib/xdotool against raw
EWMH properties) glue these together and paper over a few Fluxbox-specific
quirks.

Goal: produce a working Openbox session, `~/.config/openbox/`, that is
behaviorally equivalent for daily use, launched the same way Fluxbox is now
(LightDM session script — check how `~/.fluxbox/startup` is currently
invoked, e.g. `/usr/bin/startfluxbox` or a custom `.xsession`, before
assuming the entry point).

**Do not delete or edit anything under `~/.fluxbox` while working.** It must
keep working as a fallback session until the Openbox port is verified. Build
the new config in `~/.config/openbox/` and a parallel `~/.openbox-music/`
helper-scripts directory (mirroring `~/.fluxbox`'s non-Fluxbox-specific
scripts), and only touch the display manager's session list at the very end.

Work in a git branch off `main` in this repo for anything that lives here
(e.g. copies of scripts you adapt before moving them out), so the port is
reviewable as a diff. Files that end up living outside this repo
(`~/.config/openbox/*`) won't be tracked by this repo's git — that's fine,
just say so when reporting progress.

### Known WM-to-WM gaps (design decisions already made — don't re-litigate)

1. **Layers collapse 5→3.** Fluxbox `apps` uses named layers: Plank =
   AboveDock(2), tint2 = Dock(4), Audacious = Top(6), Renoise/plugin server =
   Normal(8), pcmanfm-desktop = Desktop(12). Openbox only has
   `above`/`normal`/`below` per `<application>` rule. Map: Plank, tint2,
   Audacious → `above`; Renoise + "Renoise Plugin Server" → default
   (`normal`, no override needed); pcmanfm desktop window → no `<layer>`
   needed at all, its `_NET_WM_WINDOW_TYPE_DESKTOP` hint already sinks it.
2. **No window tabbing/grouping in Openbox.** Drop `tabs.*` settings and the
   `StartTabbing` mouse bind entirely. Not a bug, not something to work
   around — just omit.
3. **No `fbrun`.** Replace with `rofi -show run` (preferred if installed) or
   `gmrun`/`dmenu_run` as fallback. Bind to `Mod4 d` (formerly
   `Exec fbrun`). Positioning/geometry is the launcher's own config, not a
   WM apps rule — do not try to replicate the Fluxbox `[Position]{WINCENTER}`
   apps-file entry for it.
4. **`windowmenu` (client menu) loses features.** Openbox's `client-menu` in
   `menu.xml` has no built-in alpha/opacity slider and no `extramenus`
   equivalent. Port the rest (iconify/maximize/close/layer/send-to-desktop);
   explicitly note the opacity slider as dropped, don't try to fake it.
5. **Edge-triggered workspace warping is not a stock Openbox feature.**
   Fluxbox's `workspacewarping*` settings (push mouse to screen edge →
   switch workspace) have no direct `rc.xml` equivalent. Treat as
   out-of-scope for v1; note it as a known regression rather than silently
   dropping it without mention.
6. **`fluxbox-remote`-based scripts need rewriting, not translating.**
   `apply-workspaces.sh` and `panel-size.sh` call `fluxbox-remote` for
   things Openbox does statically (desktop count/names in `rc.xml`) or via
   a different CLI (`openbox --reconfigure` instead of
   `fluxbox-remote Reconfigure`). See Phase 3.
7. **`plank-input-shape.py` may be unnecessary.** Its docstring says it
   exists because Fluxbox reparents Plank and copies only the bounding
   shape (not the input shape) onto the frame, so the frame swallows clicks
   over the DAW device-slider area. This may be Fluxbox-specific
   framing behavior. Test Plank click-through under bare Openbox before
   porting this script; only carry it over if the bug reproduces.
8. **Strut handling may be simpler under Openbox.** `panel-size.sh` writes
   `session.screen0.struts.1` directly into the Fluxbox `init` file to force
   a specific Xinerama head's reserved space. Test whether Openbox already
   honors tint2's own `_NET_WM_STRUT_PARTIAL` correctly per-head without a
   parallel WM-side strut override before porting that logic.

Flag any place where testing contradicts the assumptions above — these are
best-effort predictions from reading the Fluxbox config, not verified
Openbox behavior.

---

## Phase 0 — inventory and prerequisites

1. Confirm Openbox is installed (`openbox --version`); install if not.
2. Confirm a run-launcher is available for the `fbrun` replacement (`rofi`,
   else `gmrun`, else `dmenu`); install one if none present.
3. Read every file in `~/.fluxbox` before starting the port, specifically:
   `keys`, `menu`, `apps`, `windowmenu`, `init`, `startup`, `overlay`,
   `Xresources`, `apply-workspaces.sh`, `panel-size.sh`,
   `workspace-switch.sh`, `audacious-follow.sh`, and the docstring/header
   comment of every `*.py` script. Do not skip the `.py` docstrings — each
   one explains *why* it exists, which is load-bearing for deciding whether
   it needs to change for Openbox.
4. Check how the session is currently launched (LightDM `.desktop` entry or
   `~/.xsession` — `grep -r fluxbox /usr/share/xsessions/ ~/.xsession* 2>/dev/null`)
   so Phase 5's new session entry mirrors it correctly.

## Phase 1 — static config translation

Create `~/.config/openbox/rc.xml`:

- `<keyboard>`: port every bind in `~/.fluxbox/keys` that isn't a Fluxbox-only
  action. `Mod4`→`W` in Openbox modifier syntax. Keep the existing intent
  comments (e.g. "Super is the session modifier so Ctrl/Alt stay available
  to DAWs", "F-key workspace binds removed on purpose"). Replace
  `Exec fbrun` per gap #3. Replace `Mod4 Shift r :Reconfigure` with
  `openbox --reconfigure` (`Execute` action). Drop `StartTabbing` bind per
  gap #2.
- `<mouse>`: port `OnDesktop`, `OnToolbar`, `OnTitlebar`, `OnWindow`,
  `OnWindowBorder`, `OnLeftGrip`/`OnRightGrip` binds from `keys`. Openbox
  context names differ slightly from Fluxbox's (`OnWindow`→`Frame`,
  `OnTitlebar`→`Titlebar`, etc.) — check `man openbox` / the rc.xml schema
  for exact context names rather than guessing.
- `<applications>`: one `<application>` block per `apps` file entry:
  - `fbrun` entry → drop (gap #3; the replacement launcher isn't
    WM-positioned this way).
  - `Tint2`, `Plank` → `<layer>above</layer>`, `<decor>no</decor>`,
    `<skip_taskbar>yes</skip_taskbar>`, `<skip_pager>yes</skip_pager>`. Do
    not set `<desktop>` sticky via a hidden/close-blocking trick if Openbox
    has a cleaner sticky flag — check `<application>` schema for the actual
    sticky-equivalent element name.
  - pcmanfm desktop window (`class=Pcmanfm`, desktop window type) → decor
    off, skip taskbar/pager; per gap #1, no explicit layer needed.
  - `Renoise`, `Renoise Plugin Server` → no layer override (default
    `normal`); port the explanatory comment about why they must stay
    Normal (from `apps`'s existing comment).
  - `Audacious` (`role=mainwindow`/`equalizer`/`playlist`) →
    `<layer>above</layer>`, `<decor>no</decor>`. Keep the comment about
    positions being restored by `audacious-stack.py` (still relevant).
- `<desktops>`: `<number>2</number>`, `<names><name>Internet</name>
  <name>Audio</name></names>`.
- Screen/behavior settings from `init` — translate what has a direct
  Openbox equivalent (focus model `ClickFocus`, `focusNewWindows`,
  placement policy closest to `RowSmartPlacement`, `opaqueMove`,
  `edgeSnapThreshold`). For settings with no Openbox equivalent
  (`workspacewarping*`, `tabs.*`, `maxIgnoreIncrement`), list them
  explicitly in the port notes as dropped rather than silently omitting.

Create `~/.config/openbox/menu.xml`:

- Translate `~/.fluxbox/menu`'s `[begin]`/`[submenu]`/`[exec]`/`[separator]`
  structure to `<openbox_menu>`/`<menu>`/`<item>`/`<separator>`, preserving
  submenu nesting and icon paths (`~/.fluxbox/pixmaps/*.png` — either
  reference in place or copy to a new icons dir, your call, but be
  consistent).
- Port `~/.fluxbox/windowmenu` to a `<menu id="client-menu">` block per gap
  #4, noting the dropped alpha slider / extramenus in a comment.

Copy `~/.fluxbox/Xresources` and `~/.fluxbox/overlay` forward unchanged if
still relevant (overlay's role — "styles must not fight feh/pcmanfm for the
wallpaper" — depends on the Openbox theme, check whether it needs a
different mechanism, e.g. an Openbox theme without a background directive).

## Phase 2 — startup script

Create `~/.openbox-music/startup` adapted from `~/.fluxbox/startup`:

- Keep unchanged: env exports, `xset` calls, `autorandr`, `xsettingsd`/
  `xfsettingsd` block, `xrdb`, `xmodmap`, wallpaper via `feh`, `wait_heads`,
  tray applet startup, dunst block (including the `xfce4-notifyd` mask/
  unmask dance — that's unrelated to which WM is running).
- Replace the Fluxbox launch block:
  ```sh
  fluxbox -log "${fluxdir}/log" &
  fbpid=$!
  ```
  with an Openbox equivalent (`openbox --config-file
  ~/.config/openbox/rc.xml &`, capture `$!` the same way, keep the same
  `trap ... EXIT` pattern).
- Keep `picom`, `desktop-heads.py`, `pcmanfm --desktop`, `audacious-stack.py`,
  `window-icons.py`, `tint2`, `place_tint2`, `task-menu.py`,
  `taskbar-sync.py`, `plank`, `fullscreen-panel.py` blocks — adjust only
  what Phase 3 determines needs adjusting (`plank-input-shape.py`,
  strut handling). Otherwise these are WM-agnostic; don't rewrite them
  speculatively.
- `apply-workspaces.sh` invocation: keep only if Phase 3 keeps a shrunk
  version of that script (see below); otherwise remove the call since
  `<desktops>` in `rc.xml` now does this statically.

## Phase 3 — script-by-script adjustment

For each script below, the action is specific — don't do a blanket
copy-and-hope:

- **`apply-workspaces.sh`**: the `fluxbox-remote`-driven
  add/remove/rename-workspace logic is now dead code (desktop count/names
  are static in `rc.xml`). Shrink the script to just the
  xfsettingsd-fights-back mitigation (stop xfsettingsd, restore xfconf's
  4-name/4-count XFCE state) — but first test whether that fight is even
  needed under Openbox (see gap #6 note: Openbox may not react live to
  external `_NET_DESKTOP_NAMES` rewrites the way Fluxbox does here). If
  testing shows no fight is needed, delete the script and its startup
  call entirely and say so.
- **`panel-size.sh`**: replace the `fluxbox-remote Reconfigure` call with
  `openbox --reconfigure`. Test whether `set_fluxbox_strut()`'s direct
  write into a WM init file has any Openbox equivalent need at all (gap
  #8) — if tint2's own `_NET_WM_STRUT_PARTIAL` is honored correctly on the
  right head without it, delete that function and simplify the script to
  just swapping the tint2 rc file.
- **`plank-input-shape.py`**: test Plank click-through on the DAW
  device-slider area under bare Openbox first (gap #7). Keep unchanged in
  the startup sequence only if the bug reproduces; otherwise drop the
  daemon and its startup block, and note the reason in the port notes.
- **`desktop-heads.py`, `taskbar-sync.py`, `task-menu.py`,
  `fullscreen-panel.py`, `window-icons.py`, `audacious-stack.py`**: read
  each one's docstring and confirm it doesn't shell out to anything
  Fluxbox-specific (`grep -n "fluxbox" *.py` across the repo is a fast
  check — Phase-0 groundwork already showed no `fluxbox-remote` calls in
  the `.py` files, only in the two `.sh` files above, but re-verify before
  assuming). Expect these to run unchanged; smoke-test each rather than
  editing blind.
- **`audacious-follow.sh`, `workspace-switch.sh`**: these talk to tint2 and
  to `_NET_CURRENT_DESKTOP`/EWMH directly — expect unchanged, but note that
  `workspace-switch.sh`'s "switch workspace" path must still work with
  Openbox's desktop-switching (`wmctrl -s`/`xdotool set_desktop`, whichever
  it currently uses) — confirm rather than assume.
- **`fbrun_history`**: irrelevant once `fbrun` is replaced (gap #3); don't
  port.

## Phase 4 — verification checklist

Run these manually (or via a throwaway nested X session /
`Xephyr`/`weston` if available, to avoid disrupting the live Fluxbox
session while testing) before touching the session entry in Phase 5:

- [ ] Openbox starts, tint2 + Plank + pcmanfm-desktop + picom + dunst all
      come up in the same order/timing as under Fluxbox.
- [ ] Two workspaces named Internet/Audio exist at start, no `fluxbox-remote`
      dance needed.
- [ ] Every `keys` bind ported in Phase 1 fires correctly, including the
      Alt-based move/resize/lower binds (these must not collide with DAW
      Ctrl/F-key bindings — this was a deliberate design constraint in the
      original `keys` file, re-verify it still holds).
- [ ] Root menu (`Mod4 space` / right-click desktop) matches the Fluxbox
      menu's structure and launches every entry.
- [ ] Renoise stays at Normal layer under maximized DAW windows; Plank/tint2
      stay above fullscreen music apps but hide correctly under
      Steam-style fullscreen games (`fullscreen-panel.py` behavior).
- [ ] Audacious's three windows (main/equalizer/playlist) stay stacked
      together and undecorated; `audacious-follow.sh on/off/toggle` still
      works.
- [ ] Plank click-through over the DAW device-slider band works (confirms
      Phase 3's `plank-input-shape.py` decision was correct either way).
- [ ] `panel-size.sh normal|compact|toggle` resizes tint2 and reflows
      maximized windows without stale struts.
- [ ] tint2 task buttons: left-click focuses, right-click gives the
      `task-menu.py` send-to-workspace menu, desktop-switch keeps the
      taskbar in sync (`taskbar-sync.py`).
- [ ] No zombie `fluxbox-remote` calls remain anywhere in the ported
      scripts (`grep -rn fluxbox-remote` over the new tree should be empty
      unless a deliberate exception was documented).

## Phase 5 — cut over

Only after Phase 4 passes:

1. Add a new session entry (LightDM `.desktop` file or `.xsession`
   variant, matching whatever mechanism Phase 0 found) that launches
   `~/.openbox-music/startup` instead of `~/.fluxbox/startup`. Do not
   remove or rename the existing Fluxbox entry.
2. Log out and select the new session to do a real end-to-end test.
3. Leave `~/.fluxbox` and its session entry in place as a fallback for at
   least one full work session before considering removing it — that's a
   user decision, not something to do automatically at the end of this
   plan.

## Deliverable / report-back format

When done (or when blocked), report:
- What was ported 1:1, what was adjusted, and why (tie back to the gap
  numbers above where relevant).
- Which Phase-3 "test first" items (plank-input-shape, strut handling,
  xfsettingsd fight) came back needed vs. unnecessary, with what you
  observed.
- Any `keys`/`apps`/`menu` entries that could not be translated and were
  dropped, listed explicitly — no silent omissions.
- Final file tree under `~/.config/openbox/` and `~/.openbox-music/`.
