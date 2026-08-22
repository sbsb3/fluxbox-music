# Fluxbox -> Openbox music-session port notes

Companion to `openbox-port-plan.md`. Records what actually happened during
the port: what tested clean, what got corrected from the plan's predictions,
and what still needs verification on the real 3-monitor hardware (this was
built and tested in nested Xephyr sessions, never against the live displays,
per the plan's instruction not to touch the live Fluxbox session while
working).

Final locations (outside this repo, so not tracked by its git):
- `~/.config/openbox/rc.xml`, `~/.config/openbox/menu.xml`
- `~/.openbox-music/*` (startup + all the daemons/scripts)
- `~/.config/tint2/openbox-music.tint2rc`, `openbox-music-compact.tint2rc`
- `~/.openbox-music/launchers/music-menu.desktop`

Staged copies of all of the above also live in this repo under
`openbox-port/` for review as a diff (branch `openbox-port`).

## Phase 3 test-first items: what came back needed vs. unnecessary

1. **xfsettingsd fight (apply-workspaces.sh) - NEEDED, confirmed live.**
   Tested in a throwaway Xephyr + Openbox session with rc.xml's static
   2-desktop Internet/Audio config already loaded and no xfsettingsd
   running yet. Started `xfsettingsd --replace`; within ~2s
   `_NET_DESKTOP_NAMES` was rewritten to `"Internet", "Dev", ""` and
   `wmctrl -d` showed the live taskbar name change from Audio to Dev. This
   is a root-window property write, not something routed through the WM,
   so it reproduces identically regardless of which WM owns the desktop --
   not Fluxbox-specific as the plan speculated it might be safe to drop.
   Kept, shrunk to just this fight (the old fluxbox-remote add/remove/
   rename-workspace logic is genuinely dead now that desktop count/names
   are static in rc.xml).

   Second finding while building the fix: **Openbox does not self-heal a
   corrupted `_NET_DESKTOP_NAMES` from its own rc.xml, ever** -- neither
   `openbox --reconfigure` nor a full kill+restart of Openbox restores the
   names once something else has written over them (verified live, both
   ways, in the same Xephyr session: the corrupted "Dev" name survived
   both). Openbox treats existing root-window desktop state as
   authoritative over rc.xml on every (re)start, not just at first login.
   Also neither `wmctrl` nor `xdotool` has a verb to rewrite
   `_NET_DESKTOP_NAMES` directly. So `apply-workspaces.sh`'s repair step
   writes the property directly via a small inline Xlib call (same
   dependency every other script here already has) -- tested, confirmed it
   sticks once xfsettingsd is dead and nothing else contests it.

2. **plank-input-shape.py - NOT NEEDED, confirmed live.** The Fluxbox
   daemon exists because Fluxbox reparents Plank into a frame and copies
   only the bounding shape (never the input shape) onto that frame, so the
   frame swallows clicks meant for whatever is underneath. Checked
   `xwininfo -root -tree` under Openbox with Plank running: Plank's dock
   and tooltip windows are direct children of root, with no such wrapping
   frame window at all. There's nothing for the bug to attach to under
   Openbox, so the daemon and its startup block are dropped, not ported.
   If click-through problems over the dock area turn up in real use with
   real DAW windows, that would contradict this finding and the daemon
   should be revisited -- flagged as a checklist item in Phase 4.

3. **Strut handling (panel-size.sh's set_fluxbox_strut) - PARTIALLY
   RESOLVED, real-hardware verification still needed.** This needed more
   digging than the plan anticipated. The actual problem `struts.1` solved
   was never "does the WM honor STRUTs" (both WMs do) -- it's that on this
   session's L-shaped 3-head layout, tint2's own `strut_policy=follow_size`
   reserves space relative to the *virtual screen* edge, which doesn't line
   up with "top of the primary monitor" specifically (per tint2's own man
   page: "on multi-monitor setups the panel generally must be placed at the
   edge, not the middle, of the virtual screen for this to work
   correctly"). Fluxbox's fix was a static per-Xinerama-head override
   (`session.screen0.struts.1`) that tint2 itself has no way to express.

   Checked Openbox's rc.xml schema for an equivalent: there isn't one.
   `<margins>` is a single value applied to the whole desktop, not
   per-monitor -- so even wanting to keep the old mechanism, there's no
   file to put it in. `set_fluxbox_strut()` is dropped outright, not just
   simplified, and `openbox --reconfigure` (which its only other job,
   forcing a reload, needed) turned out to have nothing left to call for
   either, since nothing else in this script touches WM config anymore.

   The only remaining lever is tint2's own strut mechanism. Flipped
   `strut_policy` from `none` to `follow_size` in the new
   `openbox-music*.tint2rc` files (tint2 already has `panel_monitor =
   primary` set, which should give `follow_size` a correct
   `_NET_WM_STRUT_PARTIAL` start/end range for that head). Single-monitor
   Xephyr test confirms the mechanism works in principle: `_NET_WORKAREA`
   correctly shrank to `0,56,1280,744` (56px top inset) once tint2 came up,
   and a full `~/.openbox-music/startup` smoke test showed the same thing
   live with the real desktop icons and panel. **Not yet verified on the
   real 3-monitor L-shaped layout** -- that's the one thing this port
   could not test without touching the live displays. If maximized windows
   still tuck under the panel wrong there, try tint2's
   `panel_pivot_struts = 1` next; if neither works, the documented fallback
   is `strut_policy = none` and accepting the panel visually overlapping
   maximized windows on the primary head as a known regression (harmless
   since tint2 stays `layer=above` regardless).

## Correction to the plan: gap #4 (client-menu) is not what it looked like

The plan assumed `<menu id="client-menu">` in menu.xml is a normal,
data-driven menu block like `root-menu`, missing only the alpha slider and
extramenus. Live testing found otherwise: in this Openbox (3.6.1),
`client-menu` is fully hardcoded in the binary (confirmed via `strings` --
literal strings `_Send to desktop`, `_Roll up/down`, etc. live inside
`/usr/bin/openbox`). Defining `<menu id="client-menu">` with a completely
different item list in menu.xml was silently ignored; Alt+Space and
right-click-titlebar both still popped Openbox's own built-in menu (Send to
desktop / Layer / Restore / Move / Resize / Iconify / Maximize / Roll
up-down / Un-Decorate / Close), verified with a screenshot.

Net effect is actually *better* coverage than the plan expected for the
parts windowmenu already had (shade, maximize, iconify, close, sendto,
layer are all present automatically, zero menu.xml needed), but the file's
custom block was dead weight and has been replaced with a comment
explaining this. Confirmed newly-dropped, with no built-in substitute:
- `[stick]` (sticky/omnipresent toggle) -- not in the built-in list at all.
  Still reachable as a raw action (`ToggleOmnipresent`, already bound to
  the `AllDesktops` mouse context in rc.xml) but not from this menu.
- `[alpha]` (opacity slider) and `[extramenus]` -- gap #4 as originally
  documented, no change here.

## Other things caught along the way

- **XML comments**: Openbox's XML parser rejects `--` anywhere inside a
  comment (standard XML rule, easy to trip on when comments use em-dash
  style `--`). Both rc.xml and menu.xml hit this repeatedly during testing
  and got the double-hyphens turned into single hyphens.
- **`<menu><file>` in rc.xml resolves relative to the Openbox config search
  path (`~/.config/openbox/`, falling back to `/etc/xdg/openbox/`), not
  relative to whatever `--config-file` path you passed.** Building rc.xml
  and menu.xml in a repo staging directory and pointing `--config-file` at
  that staged rc.xml silently loaded the *system's* stock menu.xml instead
  of the ported one (parse errors in the staged menu.xml were also
  silently falling back the same way, which is how this got caught).
  Fixed by testing against the real `~/.config/openbox/` location once the
  content was ready, which is also where these files need to live anyway
  per Phase 1.
- **`fbrun` replacement extends past what the plan's gap #3 named**: the
  `keys` file has a second fbrun bind the plan didn't call out
  (`Mod1 F2 :Exec fbrun`, in addition to `Mod4 d`). Both are now
  `rofi -show run`.
- **`launchers/music-menu.desktop`** (a `.desktop` launcher outside `keys`/
  `menu`/`apps`, found via `grep -rl fluxbox-remote`) calls
  `fluxbox-remote RootMenu`. Openbox has no remote-menu-popup verb at all;
  ported as `xdotool key super+space`, replaying the same keypress rc.xml
  already binds to the root menu. Verified live: this pops the real ported
  root menu (screenshot taken), not just the default one.
- **`slitlist`** (Fluxbox's slit dockapp list) is empty and unused in this
  session already (tint2/Plank replaced the slit long ago) -- not ported,
  nothing to port.
- **`debug/tb-watch.py`** (untracked, ad-hoc taskbar-sync debugging tool,
  not referenced by `startup`) is out of scope for this port and untouched.
- Fixed one latent bug in a copied script while relocating it: the
  `panel-hidden` IPC flag path shared between `fullscreen-panel.py` and
  `task-menu.py` had to move to `~/.openbox-music/panel-hidden` in *both*
  files identically, or the two daemons would silently stop agreeing with
  each other after the move.
- picom's and dunst's config files (`~/.config/picom/fluxbox-music.conf`,
  `~/.config/dunst/fluxbox-music.conf`) are intentionally left with their
  existing names and referenced unchanged from the new startup script --
  their content is WM-agnostic (compositor/notification-daemon settings),
  so renaming them would just be churn with no behavior difference. Same
  reasoning for pcmanfm's `--profile fluxbox-music` argument (a pcmanfm
  config-profile name, unrelated to which WM is running) -- left as is
  rather than renamed and requiring a new `~/.config/pcmanfm/` profile
  directory.
- **Unrelated live-session finding, fixed in passing**: `/tmp/desktop-heads.log`
  (the live Fluxbox session's supervised-restart log for `desktop-heads.py`)
  had grown to 1.6 GB and filled the entire 2 GB `/tmp` tmpfs, which was
  causing unrelated tool flakiness while this port was being tested. Not a
  port issue -- pre-existing in the live session -- but worth a separate
  look at some point: either `desktop-heads.py` was crash-looping and
  re-logging heavily at some point, or the log has simply never been
  rotated. Truncated the file (safe -- the running process keeps its open
  handle and just keeps appending) rather than touching the live process.

## Settings from `init` with no Openbox equivalent (dropped, not silently)

Beyond `workspacewarping*` (gap #5) and `tabs.*`/`tab.*` (gap #2), already
called out in the plan:

- `maxIgnoreIncrement`, `ignoreBorder`, `showwindowposition`,
  `noFocusWhileTypingDelay` (was already 0, a no-op), `colorsPerChannel`,
  `cacheMax`/`cacheLife`, `configVersion`, `forcePseudoTransparency` (moot
  -- picom does real transparency), `allowRemoteActions` (moot -- CLI
  control is just always available) -- all Fluxbox-internal knobs with
  nothing analogous in Openbox.
- `toolbar.*`, `slit.*`, `iconbar.*` -- Fluxbox's own toolbar/slit are
  unused in this session already (tint2/Plank replaced them); N/A, not a
  port loss.
- `window.focus.alpha`/`unfocus.alpha` -- both were 255 (fully opaque)
  anyway, i.e. already a no-op.
- `autoRaise`/`autoRaiseDelay` -- Fluxbox had autoRaise off and relied on
  click-to-raise instead; that's just the default Frame-click behavior in
  rc.xml's `<mouse>` section already, nothing to configure.
- `fullMaximization: false` -- matches Openbox's default behavior already
  (maximize respects the workarea/struts; a separate `MaximizeFull` action
  exists if true fullscreen-maximize is ever wanted).
- `rowPlacementDirection`/`colPlacementDirection` -- no Openbox knob at
  this granularity for Smart placement; approximated with `<center>no</center>`.
- `strftimeFormat` (Fluxbox toolbar's clock format) -- moot, tint2 owns the
  clock and has its own format config, untouched by this port.

Settings that DID have a direct equivalent (translated, not dropped):
`edgeSnapThreshold` -> `<resistance>`, `focusModel ClickFocus` ->
`<followMouse>no</followMouse>`, `focusNewWindows` -> `<focusNew>`,
`opaqueResize: false` -> `<drawContents>no</drawContents>` (Fluxbox showed
an outline while resizing, not live content -- this is the literal
equivalent, not opaqueMove which has no Openbox toggle since Openbox always
moves windows opaquely), `doubleClickInterval` -> `<doubleClickTime>`,
`menuDelay` -> `<submenuShowDelay>`, `workspaces`/`workspaceNames` ->
`<desktops>`.

## Verified live (Xephyr), not just read from docs

- rc.xml and menu.xml parse and load cleanly from `~/.config/openbox/`.
- 2 desktops named Internet/Audio at a clean start, no fluxbox-remote-style
  dance needed.
- `openbox --reconfigure` works without dropping the session.
- Root menu (Mod4+space, and via `xdotool key super+space` standing in for
  the old `fluxbox-remote RootMenu`) opens the ported menu with correct
  structure, icons, and submenus.
- Client menu (Alt+Space) opens Openbox's built-in menu with Send to
  desktop / Layer / Close all working (see gap #4 correction above).
- `workspace-switch.sh show/goto/delta` all work unmodified against Openbox
  (wmctrl-based, confirmed WM-agnostic as predicted).
- `desktop-heads.py --once`, `taskbar-sync.py`, `task-menu.py`,
  `fullscreen-panel.py`, `audacious-stack.py`, `window-icons.py` all start
  and run cleanly against a live Openbox session with no tracebacks
  (smoke-tested per Phase 3's instruction, not edited blind).
- Full `~/.openbox-music/startup` end-to-end: Openbox, tint2 (with the real
  panel showing live Internet/Audio workspace labels), Plank, pcmanfm
  desktop (rendering the real desktop icons), and the daemons all come up
  together without crashing. (dunst and the polkit agent could not
  actually acquire their D-Bus names in this test because the nested
  session shares a D-Bus session bus with the already-running live
  session -- that's a test-environment limitation, not a port bug, and
  will not occur in a real separate login.)
- Plank exited partway through that same end-to-end test after ~20s
  (caught SIGTERM) -- traced to Plank's own single-instance-per-dock-name
  handling colliding with the live session's already-running `plank -n
  music`, since the test reused the same profile name. Also a
  test-environment artifact, not a port bug; a real separate login has no
  competing instance.

## Not tested (needs the real hardware / a real login)

- The strut/`panel_pivot_struts` question on the actual 3-monitor L-shaped
  layout (see item 3 above).
- Renoise/plugin-server layer behavior under a real maximized DAW window,
  and Plank/tint2 hide behavior under a real Steam fullscreen game
  (`fullscreen-panel.py`'s detection logic was smoke-tested for crashes
  only, not for correct fullscreen detection against a real game window).
- Audacious's real three-window stacking behavior after a restart/resume,
  since that needs Audacious actually running with the Winamp skin.
- `panel-size.sh normal|compact|toggle` end-to-end against the real
  monitors (logic reviewed and syntax-checked; the strut-writing half was
  removed per item 3, so this needs a real test that the remaining
  restart-tint2-and-resync-desktop behavior still reflows correctly).
