# Impact of the RustGIS pull, and a UX refactor of the panel and the tab

Written against RustGIS `03b0ddcd` (2026-11-10, `version = "0.6.0"`, unreleased; last tag
`v0.5.0`, 2026-10-31) and plugin 0.10.0.

## 1. What the pull changed

Everything below landed **after** `v0.5.0`, and all but one after this plugin's last commit
(2026-11-08 04:42).

| RustGIS commit | Date | What it gives |
|---|---|---|
| `813c7cb2` panel forms and a per-command timeout | 07-11 | `form` panel item; `commands[].timeout`, 1 to 86,400 s |
| `ae098d42` session process plugins | 08-11 | `"session": true`: one program stays running, hears `view`/`layers`/`selection`/`project` events |
| `4b510fb0` dropdowns, date pickers, range sliders | 09-11 | `choice`, `date`, `range` panel items |
| `c4ccb515` richer `host.layers` | 09-11 | each layer's `extent`, `transparency` and `group`; `info.project` layout page sizes |
| `40120268`, `104cdd0d`, `d7f14d2f`, `4a266a2d` | 09-11 | lossy panel updates reported; panel value checks; panel clicks wait for refused changes |
| `17d6cfb6`, `67fa9811` | 09-11 | desktop still caps a command at 120 s whatever its `timeout`; no host request past the deadline |
| `46e50434` panel picks | 10-11 | `pick` panel item: a point or a box asked for on the map |
| `7cc9bb68` `layer.addUrl` with `bbox` | 10-11 | a COG window added off the frame |

### 1.1 The plugin is currently unloadable on the version it claims to need

`plugin.json` says `"minRustgisVersion": "0.5.0"` and the panel declares a `form` item. At
`v0.5.0`, `crates/plugins/src/panel.rs` has

```rust
pub const KINDS: &[&str] = &["text", "checkbox", "slider", "button", "tree"];
```

and an unknown kind is a **hard manifest error**, not a warning:

> `plugin.json: panel item kind 'form' isn't text, checkbox, slider, button, tree, form, choice, date, range or pick`

So on a released RustGIS 0.5.0 the whole plugin is refused, not degraded. It works only against
`main`. **Fix: `minRustgisVersion` must be `0.6.0`** (and stay there once any of `choice`,
`date`, `range`, `pick`, `session` or `timeout` is used).

### 1.2 Capabilities that answer open TODO items

- **`session: true`** answers *"a session-scoped mapset would amortise it"* in the README's
  *Watch out*. One long-lived program can hold the parsed catalogue (3.17 MB of `modules.json`,
  27 ms a call today), one throwaway GISDBASE reused across runs instead of ~10 s of project
  creation per run, and the GRASS version probe. It also hears `{"event": "layers"}`, so the
  raster list can be recomputed before the user asks for it.
  **Limit, verified:** a session plugin **cannot refresh its own panel**. `plugin.panel` is
  `Effect::Reserved` and `crates/engine/src/cmd/plugins.rs:393` `user_only()` refuses every
  `plugin.*` id to a plugin. Panel state still only changes as the answer to a command, so an
  event can warm a cache but not redraw the pane.
- **`commands[].timeout`** is already used on `run-module` (86,400 s). It is still worth setting
  on the curated raster commands for the `rustgis-cli`/Python/script path; the desktop app is
  capped at 120 s regardless, so the README's *two-minute cap* section stays true for the app.
- **`pick`** removes two guesses the plugin makes today: `r.viewshed` currently shoots from *the
  centre of the map*, and the region can only be the whole layer or the view.
- **`host.layers`** now carries `extent` and `group`, so the raster tree can be grouped like the
  Contents pane and a layer with no extent can be greyed out, without a `raster.info` call.

## 2. What is wrong with the interface today

Measured on the generated 0.10.0 manifest.

### 2.1 The panel: 24 widgets, one flat column

`crates/ui-egui/src/pluginpanel.rs:155` draws the items as one flat vertical list; there is no
section, accordion or sub-tab. A tree gets up to 320 px
(`pluginpanel.rs:866`). Today's panel stacks, in order: a text, **a tree**, 2 buttons, **a
tree**, a text, a slider, a text, 2 buttons, a slider, a checkbox, 2 sliders, a checkbox, 3
buttons, **a tree**, **a tree**, a text, **a form**, a button, a text.

Four trees and a form in one column is several screens of scrolling, and the order mixes three
unrelated jobs: reaching the GRASS database, choosing a layer and a region, and finding and
running a module. The three terrain controls (`percent`, `height`, `maxdist`, `curvature`) sit
in the middle and apply to three buttons only.

### 2.2 Every panel interaction re-sends the whole catalogue

`panel_state` answers `modules.nodes` on every call, and the module tree, the mode tree and the
raster tree all call `raster-state`. Measured here: **1,424 nodes, 270 KB of JSON**, rebuilt and
written down the pipe for every click — including clicks that cannot change it (choosing a
raster layer, moving the band slider). The docs are explicit that *"what an answer leaves out
stays as it was"*, so this is pure waste.

### 2.3 The ribbon tab: 141 entries, 27 of them one-item menus

7 groups, 141 entries. The **Vector** group alone holds **27 menus**, generated straight from
GRASS keywords:

- 20 of the 27 hold **a single tool** (*Attribute table* › `v.db.droprow`, *Clip* › `v.clip`,
  *Dissolve* › `v.dissolve`, *Kernel density* › `v.kernel`, *Plot* › `v.boxplot`, …): a menu
  that opens to one row is a button with an extra click.
- the keywords are not normalised: **`LIDAR` and `Lidar` are two separate menus**, and
  *Geometry* (19 tools) sits beside *Lines central* (1) and *Point cloud* (1).
- `panel` appears **three times** (in Imagery, Temporal and Modules).
- **32 of 38 commands use the icon `stats`**, the 64 tools declare **no icon**, and the 27 menus
  declare none either. RustGIS ships 151 icons, among them `relief`, `raster_layer`, `bands`,
  `catalog`, `environments`, `run`, `toolbox`, `time_slider`, `planet`, `add_data`,
  `add_folder`, `resample`, `clip`, `dissolve`, `near`, `simplify`, `split`, `hull`, `union`,
  `intersect`, `measure`, `rgb`, `stretch`. A small-layout group of identical bar-chart glyphs
  is unreadable at a glance.
- the three **`*-state` buttons** (Imagery Modules, Temporal Modules, All Modules) are not
  actions: they are a filter on a tree inside the panel, promoted to the ribbon.

## 3. The refactor

The user's own order — **project first, then layers, then tools** — becomes the panel's
structure instead of being left implicit in a scroll.

### 3.1 The panel becomes a four-step workflow

One `choice` dropdown at the top drives `visible` on everything below it.
`pluginpanel.rs:155` already filters on `visible`, and a `choice` runs its command the moment an
option is chosen, so the step's answer sets the next step's widget set. The panel's declared
budget is **32 items**; the plan below uses **30**, with at most **8 visible at once**.

```
GRASS GIS
Step  [ 1 · Project & data | 2 · Layer & region | 3 · Terrain | 4 · Modules ]   (choice)
...the chosen step's widgets...
Last run                                                           (text, always visible)
```

| Step | Items (visible) | Was |
|---|---|---|
| **1 · Project & data** | `gisdbase` text, `database` tree, buttons *Add Map*, *Browse Mapset*, *GRASS Database* | top of the column |
| **2 · Layer & region** | `raster` tree, `source` text, `band` slider, `region` text, `region-box` **pick (box)**, buttons *Region = Map View*, *Region = Whole Layer*, `res` slider | items 5-11 |
| **3 · Terrain** | `percent`, `height`, `maxdist`, `curvature`, `viewpoint` **pick (point)**, buttons *Slope*, *Aspect*, *Viewshed* | items 12-18 |
| **4 · Modules** | `family` **choice** (replaces the `mode` tree), `modules` tree, `details` text, `form`, button *Run Module* | items 19-24 |

Why each change:

- **A `choice` for the step** rather than a tree or a row of buttons: it is one line high, its
  value is kept by RustGIS between calls, and `rustgis-cli ... '{"panel": {"step": "modules"}}'`
  drives it from a script.
- **The `mode` tree becomes a `choice`.** A three-node tree inside a 320 px scroll area to pick
  *All / Imagery only / Temporal only* is a dropdown wearing a tree's clothes. This also frees a
  panel item and removes one of the four trees.
- **Gate the steps with `enabled`.** *Add Map* stays disabled until a map is chosen; step 2's
  region buttons until a raster layer is chosen; *Run Module* until the chosen module is
  runnable and its required fields are filled (`run_module` already checks this — report it in
  the button's state rather than only in an error after the click).
- **`status` is the one widget never hidden**, so the result of a run is readable from any step.
- **The step a command implies is the step it leaves you on.** The ribbon's *Add Map* answers
  with `step = "data"`, *Region = Map View* with `step = "layer"`, *Imagery Modules* with
  `step = "modules"` and `family = "imagery"`. A ribbon button then both acts and puts the panel
  where the next action is.

### 3.2 Two picks, two guesses removed

```json
{ "kind": "pick", "id": "viewpoint", "label": "Viewpoint on the map", "command": "raster-viewshed" },
{ "kind": "pick", "id": "region-box", "shape": "box", "label": "Region from a box", "command": "region-box" }
```

- `viewpoint` gives `{lon, lat, x, y, crs}`. `run_raster_command` passes `coordinates=x,y` to
  `r.viewshed` after converting from the pick's `crs` to the raster's, instead of the map
  centre. The point stays marked on the map while the panel is open, so the viewshed's origin is
  visible rather than assumed.
- `region-box` gives `bbox` in degrees and `extent` in the map's CRS. A new `region-box` command
  sets `gp.env`'s extent from it, which is the third way to set a region GRASS users expect
  (*draw it*) and which `g.region n= s= e= w=` already implements in `set_region`.

Both need `minRustgisVersion` `0.6.0`; both are refused outright by older versions, which is
another reason the floor has to move.

**Done (2026-11-16, 0.11.0).** `viewpoint` declares no command of its own, so picking marks the
place and the next **Viewshed** uses it; without a pick the run still falls back to the centre of
the map and says so, which keeps the ribbon button working with the panel closed. `region-box`
runs a new `region-box` command, also on the ribbon. Verified on a 200 x 200 UTM 30N test DEM
through `rustgis-cli`: two picked points gave 28,000 and 4,003 visible cells of 40,000.

### 3.3 Stop re-sending the catalogue

Three cheap changes, in order of payoff:

1. **Answer `modules.nodes` only when the module tree is visible** — that is, only from step 4.
   Steps 1-3 drop ~270 KB per click.
2. **Give the module tree its own command**, `module-pick` (the TODO's *lightweight
   `module-details` command*). It answers `details`, `form` and `status` and **no `nodes`**;
   choosing a module in a 1,424-node tree then costs a few KB instead of 270.
3. **Give the raster tree its own command**, `layer-pick`, answering `source`, `band` and
   `region` only. A layer choice today rebuilds the whole catalogue tree for nothing.

`raster-state` stays the panel's `state` command and the only one that sends everything.

### 3.4 The ribbon tab: 7 groups, no one-item menus, an icon per entry

| Group | Layout | Holds |
|---|---|---|
| **GRASS** | large | `panel` (the only `panel` entry, icon `pane_right`) |
| **Data** | small | *GRASS Database* (`add_folder`), *Add Map* (`add_data`), *Browse Mapset* (`catalog`) |
| **Region** | small | *Map View* (`zoom_box`), *Whole Layer* (`zoom_full`), *From a Box* (`measure_area`) |
| **Terrain** | small | *Slope* (`relief`), *Aspect* (`directions`), *Viewshed* (`explore`), menu *Raster* (`raster_layer`) with the 5 themed submenus as now |
| **Imagery** | small | menu *Imagery* (`bands`) with the 4 themed submenus |
| **Vector** | small | **8 menus**, not 27 (below) |
| **Modules** | small | *Run Module* (`run`), *Catalogue* menu (`catalog`) holding *All*, *Imagery only*, *Temporal only* |

Vector, from 27 keyword menus to 8 curated ones, each with an icon; the GRASS keyword stays in
each tool's `help`, so nothing is lost and the search in the Tools pane still finds it:

| Menu | Icon | From today's keyword menus |
|---|---|---|
| Overlay & clip | `clip` | Clip, Dissolve, Extract, Select, Overlay, Patch |
| Geometry | `hull` | Geometry (minus the above), Centroid, Lines central, Graphics, Surface |
| Proximity & sampling | `near` | Distance, Sampling, Kernel density, Statistics |
| Network | `directions` | Network, Linear reference system, Stream network |
| Point clouds & LIDAR | `point_layer` | **LIDAR + Lidar merged**, Point cloud |
| Generalize & clean | `simplify` | Generalization, Topology |
| Transform & project | `identity` | Transformation, Projection, Rectify |
| Tables & import | `table` | Attribute table, Category, Import, Plot |

Rules this follows: no menu with fewer than two entries; no two menus whose labels differ only
in case; `panel` declared once; an icon on every command, tool and menu. The three `*-state`
buttons move off the ribbon's top level into the *Catalogue* menu, because they set a filter,
not run anything.

### 3.5 Session plugin (separate, larger step)

`"session": true` with the same `main.py` loop restructured as a read-dispatch-write loop:

- parse `modules.json` once; keep the catalogue, the tree and the GRASS version in memory;
- keep **one** throwaway GISDBASE for the whole session, with a mapset per run, and delete it on
  input close — the `.gislock` rule in the user's conventions makes that cleanup mandatory, and
  it is the only part of this change that can leave state behind;
- on `{"event": "layers"}` and `{"event": "project"}`, drop the cached layer list and raster
  info so the next command is correct; the panel cannot be redrawn from an event (§1.2), so this
  is a warm cache, not a live pane;
- on input close, exit and remove the GISDBASE.

This is where the README's *"a run costs about ten seconds of project creation"* goes away. It
should be done **after** the panel and tab work, because it changes the process model and the
tests' entry point, while §3.1-3.4 are manifest and `panel_state` changes.

### 3.6 What steps 1-4 measured after the work (2026-11-16, plugin 0.11.0)

Implemented. Measured over the plugin's own protocol, against the 60-project
database on this machine:

| | Before | After |
|---|---|---|
| Panel widgets declared | 24 | 27 |
| Widgets drawn at once | 24 | at most 12 |
| Panel opened (step 1) | 277 KB | 18 KB |
| Panel opened (step 2 or 3) | 277 KB | 1.5 KB |
| Choosing a raster layer | 277 KB | 0.4 KB |
| Choosing a module | 277 KB | 2.1 KB |
| Ribbon entries | 141 | 122 |
| Vector menus | 27 (20 with one tool) | 9 (none with one tool) |
| Commands without an icon of their own | 32 of 38 | 0 of 42 |
| `panel` declared in the tab | 3 times | once |

Step 5 (the picks) is done too, and measured in 3.2. Step 6 (timeouts) is done, with the
limit noted below. Step 7 (a session plugin) is not.

### 3.7 Step 6 as built, and what the host does not allow

Every raster command declares `"timeout": 86400`. That fixes `rustgis-cli`, Python and
scripts. It cannot fix the desktop app, which keeps any command to 120 seconds whatever
the manifest says (`17d6cfb6`), and **nothing tells the plugin which host it is in**:
`host.info` answers `{rustgis, abi, plugin, permissions}` only
(`crates/engine/src/cmd/plugins.rs:587`), the command request carries no host field, and
no environment variable is set for a process plugin. Raising the run's own deadline
unconditionally would therefore mean being killed mid-write on the desktop, which is the
thing that deadline exists to prevent.

So the run keeps to 120 seconds unless the caller — who does know where it is running —
passes `timeout` in the command's own parameters. A host flag in `host.info` would let
the plugin decide for itself, and belongs upstream in RustGIS rather than here.

## 4. Order of work

1. `minRustgisVersion` → `0.6.0`; note in README why (§1.1). *One line, unblocks everything.*
2. Icons on all 38 commands, 64 tools and every menu; `panel` declared once; the 27 vector menus
   curated to 8 (§3.4). *Manifest only, in `generate_manifest.py`.*
3. The step `choice` and `visible` stepping; the `mode` tree → `family` choice (§3.1).
   *`PANEL` and `panel_state`.*
4. `layer-pick` and `module-pick`, and `nodes` only from step 4 (§3.3). *Two commands, visible
   responsiveness win.*
5. The two picks and the `region-box` command (§3.2). *New capability.*
6. `timeout` on the curated raster commands (§1.2).
7. `session: true` (§3.5).

Steps 1-4 are the ones that fix "cluttered and not intuitive"; 5-7 are what the pull newly makes
possible.

Each of 2-5 needs its new labels in `FRENCH` in `generate_manifest.py`, or `check_i18n` reports
the dead entries; and `tests/display_test.py` and `tests/raster_test.py` cover `panel_state`, so
the step gating belongs in a test there.
