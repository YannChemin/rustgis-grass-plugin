# RustGIS GRASS Plugin — Development History

## Objective

Upgrade the RustGIS GRASS plugin in `~/dev/rustgis-grass-plugin` so its large
GRASS module catalogue (~1,174 modules) is exposed honestly and discoverably:
add imagery and (later) temporal menus, and make the panel show what can
actually be run and why the rest cannot.

Approved direction: **Arrangement B + C, Phase 0 first** — a curated task
ribbon (Database, Region, Raster, Imagery, Vector, Temporal, Modules) plus one
**mode-driven catalogue panel** with a "Runs from here" tree, an "All modules"
tree, chosen-module details, and recent modules. This session delivered Phase 0
(Database, Region, Raster, Vector, Modules) and Phase 1's Imagery group and
catalogue mode; the Temporal group remains in "Possible next steps".

## Starting point

- Plugin repo: `~/dev/rustgis-grass-plugin`, branch `main`, HEAD `ebacd30`.
- Plugin version: `0.4.0`.
- GRASS installed at `/usr/local/bin/grass` (`GRASS 8.6.0dev`).
- RustGIS source at `~/dev/RustGIS`.
- The catalogue had 1,174 readable modules, 64 vector tools, and 27 curated
  raster commands.
- The panel had a single flat "Every GRASS module installed" tree and no way
  to tell which modules Run Module could actually drive.

## Investigation

- Read RustGIS plugin docs (`docs/plugins.md`) and the manifest schema
  (`crates/plugins/src/manifest.rs`).
- Recorded the manifest limits that shaped the design: 64 tools, 32 params per
  tool, 256 commands, 8 tab groups, 32 panel items, 5,000 tree nodes, tree
  depth 8, 200-character tree node ids, 4,000-character runtime text, 32 menu
  items, menu depth 4.
- Read the panel renderer (`crates/ui-egui/src/pluginpanel.rs`), panel state
  model (`crates/plugins/src/panel.rs`), and command palette search
  (`crates/ui-egui/src/chrome.rs`).
- Cached every module's `--interface-description` XML at
  `/tmp/opencode/iface.json` for offline analysis.
- Established the key architectural fact: vector modules are *tools* (GeoJSON
  in/out, no host requests, only 64 fit); raster modules are *commands* that
  export a GeoTIFF (`share.exportRaster`), run GRASS, and add the result back
  (`layer.addData`). A command has no form, so only its input and output can
  be named.

### Runnability rule iterations

The central question was: which modules can Run Module drive on one raster
with GRASS's own defaults?

| Rule | Count |
|---|---|
| Loose "reads a raster or writes one" | 358 |
| Allow optional raster inputs/outputs, required params defaulted | ~117–141 |
| Exactly one raster in, one raster out | 78 |
| Restricted single required input/output | 69 |
| Allow extra optional raster ports, choose required input/output | ~100 |
| Implemented conservative rule (incl. groups, bands, flags, defaults) | 97 |
| Exclude 3D raster required input named `input` | 91 |
| Exclude base-name band readers and Display modules | **88** |

Final rule: one required raster input, at least one raster output, at most one
required raster output, chosen output not a basename, chosen input not
`multiple=yes` or a base-name band reader, no required flags, and every other
required parameter has a default. Display modules are refused because Run
Module has no display.

Final breakdown: **Raster 70, Imagery 9, Planetary 9**.

Reason strings produced by `_runnability`:
`takes no raster`, `writes no raster`, `needs an input chosen for it`,
`needs N raster inputs`, `writes N rasters`, `writes several rasters`,
`needs several bands`, `needs a display`, `needs flag -X`, `needs <names>`,
`needs an imagery group`, `needs a config file`, `needs coordinates`.

## Work done

### 1. Runnability analysis — `grass_bridge/interface.py`

- Added `TEMPORAL_ELEMENTS = frozenset({"stds","strds","stvds","str3ds","stdsp"})`.
- Added `_prompt(gisprompt)` to read a prompt's element whichever attribute
  names it.
- Added `_needs_text(names)`:
  - `group` / `input_group` / `input_group_to_decompose` → "needs an imagery group"
  - `config` / `parameters` / `rules` → "needs a config file"
  - `coordinates` / `coordinate` → "needs coordinates"
  - otherwise "needs <name>"
- Added `_runnability(task)` with the final conservative rule above.
- `describe()` now merges the runnability fields into every catalogue entry.
- Fixed a subtle bug: a required 3D raster named `input` (`r3.cross.rast`) was
  skipped as "plumbing" and wrongly offered as runnable. Required parameters
  are no longer skipped by name unless they are the chosen input/output.
- Added base-name detection so `i.landsat.toar` and `i.landsat.acca` are
  marked "needs several bands" rather than being run on one band and failing.
- Display modules are marked "needs a display" instead of offering a GUI
  module that would wait forever.

### 2. Catalogue and manifest — `generate_manifest.py`

- Catalogue entries now carry:
  - all `raster_in` / `raster_out` ports;
  - the chosen `raster_input` / `raster_output`;
  - `runnable`, `reason`, `needs`, `bands`, `temporal`.
- Module commands are generated only for entries with `runnable` true
  (previously `raster` true), reducing curated commands from 27 to 18.
- The generator's summary prints the runnable count.
- Version bumped `0.4.0` → `0.5.0`.
- Panel changes:
  - modules tree relabelled "GRASS modules (runs here first)";
  - new help text describing the three branches and search;
  - new `details` text item "Chosen module";
  - modules tree now has `command: "raster-state"`, so selecting a module
    refreshes the details immediately.
- i18n additions: `Modules`, `GRASS modules (runs here first)`, `Chosen module`.
- Tab changes: removed `panel` from the Database group; added a **Modules**
  group containing `["panel", "run-module"]`; removed `run-module` from the
  Raster group.

### 3. Tree API — `grass_bridge/raster.py`

- Added `import json`.
- Replaced the old `catalogue_tree` / `entry_for` pair with:
  - `NODE_PREFIXES = ("runs/", "all/", "recent/")`
  - `MAX_RECENT = 12`
  - `RECENT_FILE = "recent.json"`
  - `module_of(node)` — strip a branch prefix
  - `_clip(text, limit=200)` — respect RustGIS's node-id/label limit
  - `_module_label(entry)` — runnable mark, module, summary, keywords, reason
  - `_family_nodes(catalogue, prefix)` — family branches
  - `catalogue_tree(catalogue, chosen=None, recent=())` → three branches:
    `branch/runs`, `branch/all`, `branch/recent`
  - `entry_for(catalogue, module, quietly=False)` — accepts prefixed node ids,
    gives a friendly error for branches/families
  - `module_details(entry)` — reads/writes, runnability, needs, temporal note
  - `recent_path()`, `read_recents(limit)`, `remember(module, limit)`
    (atomic write via temp file + `os.replace`, never fails a run)
- `free_module_args(entry)` now uses `raster_input` / `raster_output` rather
  than the first listed ports, so `r.watershed` gets `elevation=src` instead
  of its first optional input. It raises with the catalogue reason when a
  module is not runnable.
- Recents are written beside the result GeoTIFFs in
  `~/.cache/rustgis-grass-plugin/recent.json`.
- Cache-write failures are swallowed: the run has already succeeded by then.

### 4. Wiring — `main.py`

- `run-module`:
  - resolves the prefixed tree node via `raster.entry_for`;
  - after a successful run, calls `raster.remember(entry["module"])`;
  - rebuilds the tree with recents;
  - fills the new `details` text via `raster.module_details(entry)`.
- Curated raster commands call `raster.remember(operation["module"])`.
- `panel_state`:
  - counts runnable modules and adds the count to the status line;
  - resolves the chosen module from the panel values;
  - builds the three-branch module tree with recents;
  - fills the `details` item.

### 5. Tests

Added to `tests/interface_test.py`:
- a module reading and writing one raster runs;
- optional raster inputs/outputs do not stop a run;
- a group requirement is stated, not offered;
- `multiple=yes` means several bands;
- required flag or parameter is a reason;
- temporal modules are recognised;
- a required 3D raster named `input` is not plumbing;
- base-name band readers are marked;
- Display modules are refused.

Added to `tests/raster_test.py`:
- the tree branches into runs/all/recent;
- the tree notes a chosen module that cannot run;
- node prefixes resolve to the right module;
- family/branch nodes are refused with a friendly message;
- Run Module names the required input/output;
- Run Module refuses with the catalogue reason;
- details text states reads/writes/needs/temporal;
- recents are newest-first and deduplicated;
- recents are capped and a broken file is ignored;
- an unwritable cache never fails a run.

Result: **89 tests pass**. `make check` passes under the Debian build as well.

### 6. Documentation and packaging

- `README.md`:
  - 88 runnable modules instead of the old 358;
  - 18 curated raster commands instead of 27;
  - three tree branches and the reason labels;
  - Modules ribbon group and revised tab table;
  - base-name/imagery caveats;
  - package version `0.5.0`.
- `skills/grass/SKILL.md`:
  - three-branch module tree, `▸` mark and reason strings;
  - branch-prefixed node ids;
  - Recently run branch in the cache section.
- `debian/changelog`: new `0.5.0` entry describing the runnability work.
- `man/rustgis-grass-setup.1`: version bumped to `0.5.0`.
- `.gitignore`: release exception moved from 0.3.0 to 0.5.0.
- Built `dist/rustgis-grass-plugin_0.5.0_all.deb` with `make deb`.

### 7. Imagery group and catalogue mode

- `grass_bridge/raster.py`:
  - `MODE_FAMILIES` maps `mode/all` and `mode/imagery` to the family each
    keeps;
  - `mode_family(mode)` resolves a mode tree node;
  - `mode_nodes(catalogue)` returns the mode tree with module counts;
  - `catalogue_tree(..., family=None)` filters runs/all/recent to one family
    and labels the branch `All imagery modules (176)` when filtered.
- `generate_manifest.py`:
  - `IMAGERY_COMMANDS` adds commands for the seven i.* modules the panel can
    drive from one raster, under Enhance, Preprocess, Detect and Geometry;
  - new commands `imagery-state` and `all-state` set the catalogue mode;
  - a `mode` tree item ("Catalogue") switches between all and imagery;
  - a new Imagery ribbon group holds the panel, Imagery Modules and the
    imagery menus; the Modules group gains All Modules.
- `main.py`:
  - `panel_state(req, mode=None)` keeps or sets the catalogue mode, returns the
    mode tree, filters the module tree, and says when a family is shown;
  - `imagery-state` and `all-state` call it with the matching mode;
  - `run_module` rebuilds the module tree with the same filter after a run.
- The Recently run branch is now always present, labelled `Recently run (0)`
  until something has run, so the panel always has its three branches.
- Tests: family filtering, mode nodes/family lookup, the empty recent branch,
  and panel-state mode wiring. **93 tests pass**.
- i18n: Imagery, the two ribbon buttons, the four imagery menus, Catalogue and
  the mode labels in French.
- Documentation updated for the Imagery group, the Catalogue mode, 25 curated
  modules and the current 1,175-module catalogue.
- Version bumped `0.5.0` → `0.6.0`, with a new `debian/changelog` entry, the
  man page date and version, and the `.gitignore` release exception.

### 8. Temporal group and catalogue mode

- `grass_bridge/raster.py`:
  - `MODE_FAMILIES` gains `mode/temporal` → `Temporal`, so
    `mode_family("mode/temporal")` resolves it;
  - `mode_nodes(catalogue)` now returns All modules, Imagery and Temporal with
    their counts.
- `generate_manifest.py`:
  - a new `temporal-state` command (ribbon label **Temporal Modules**) opens the
    panel in the temporal mode;
  - a new Temporal ribbon group holds the panel and Temporal Modules, between
    Vector and Modules;
  - the panel's Catalogue and module-tree help, plus the panel help, name the
    temporal filter; French strings for Temporal and Temporal Modules.
- `main.py`: `temporal-state` calls `panel_state(req, "mode/temporal")`, as
  `imagery-state` and `all-state` do for their modes.
- No temporal module is offered as runnable. All 74 report **takes no raster**
  (66) or **writes no raster** (8); the details text already says a temporal
  module reads a space-time dataset, not one raster.
- Tests: temporal family filtering, the temporal mode in `mode_nodes`, and the
  `temporal-state` dispatch. **95 tests pass**.
- Version bumped `0.6.0` → `0.7.0`, with a new `debian/changelog` entry, the man
  page date and version, the `.gitignore` release exception and the README
  install line.
- Catalogue refreshed while building: 1,181 installed, 1,176 readable (Imagery
  is now 177). The manifest carries 38 commands, 64 tools, 7 ribbon groups and
  23 panel items.

#### Space-time design note

Temporal modules act on a space-time raster dataset (STRDS), not on one map.
Running one would mean exporting the chosen layer into the throwaway GRASS
project, creating an STRDS there, registering the map, running the module and
exporting its raster result — and a one-map STRDS would make most `t.rast.*`
operations trivial. The plugin ABI has no space-time dataset kind and RustGIS
holds no temporal model, so this is left as a separate TODO rather than
pretended in the panel.

## Verification

- `python3 -m pytest -q tests` → 95 passed.
- `rustgis-cli commands --plugin . --no-plugins` loaded the generated manifest
  successfully and listed all 38 commands.
- `rustgis-cli run --plugin . --no-plugins` with `raster-state` produced the
  three-branch tree and the "Choose a module" details text.
- Full end-to-end run on `crates/map/testdata/qgis/generated/data/dem.tif`:
  - `layer.addData` added the DEM;
  - `raster-state` populated the tree;
  - panel value `modules = runs/r.slope.aspect`;
  - `run-module` ran `r.slope.aspect`;
  - result written to `~/.cache/rustgis-grass-plugin/DEM_r-slope-aspect.tif`;
  - recents written as `["r.slope.aspect"]`;
  - panel status and details updated correctly.

## Key numbers

- 1,176 modules read; 5 could not be read.
- 64 vector tools; 64 more could have fit.
- 18 curated raster commands and 7 curated imagery commands (raster was 27
  before the runnability work).
- 88 modules runnable via Run Module: Raster 70, Imagery 9, Planetary 9.
- 23 panel items (limit 32).
- 38 commands, 64 tools, 7 ribbon groups.
- Tree size about 1,300 nodes (limit 5,000); the Imagery mode holds 177 and
  the Temporal mode 74.

## Files changed

- `grass_bridge/interface.py` — `TEMPORAL_ELEMENTS`, `_prompt`,
  `_needs_text`, `_runnability`, `describe`.
- `grass_bridge/raster.py` — `catalogue_tree`, `entry_for`, `module_details`,
  `remember` / `read_recents`, `free_module_args`, `mode_nodes` /
  `mode_family`.
- `generate_manifest.py` — catalogue fields, runnable-only commands, version,
  panel/tab groups, imagery and temporal commands and modes, i18n.
- `main.py` — tree, details and recents wiring, catalogue modes and their
  commands (`imagery-state`, `temporal-state`, `all-state`).
- `README.md`, `skills/grass/SKILL.md`, `debian/changelog`,
  `man/rustgis-grass-setup.1`.
- `tests/interface_test.py`, `tests/raster_test.py`.
- `.gitignore`, `debian/changelog`, `man/rustgis-grass-setup.1`,
  `dist/rustgis-grass-plugin_0.7.0_all.deb`.

## This session — display modules render a picture (0.10.0)

### Objective

Make the display (`d.*`) branch of the catalogue usable from the panel. It was
the one family refused wholesale with "needs a display", even though most of
its modules can draw to a file instead of a monitor.

### What changed

- `interface._render_runnability()` triages display modules: it exposes their
  input layers and marks a module `render_runnable` when a headless render can
  produce a picture. 19 modules qualify; interactive ones (`d.what.*`,
  `d.rast.edit`) and `d.polar` (its script uses a function missing from this
  GRASS build) keep an explicit reason.
- `session.DisplayRun.render_mapset()` renders maps of one mapset chosen under
  **Projects and mapsets**, in a throwaway mapset of the same project. It adds
  that mapset to the search path, renders with GRASS's direct cairo driver
  (`GRASS_RENDER_IMMEDIATE=cairo`), writes a world file, imports the PNG with
  `r.in.gdal -o`, resets the region to the picture grid and exports an RGB
  GeoTIFF to the plugin cache. It no longer starts a monitor: `d.mon start`
  does not survive between two `grass --exec` processes.
- `raster.render_form()`, `render_plan()` and `render_args()` add the display
  module's form, choices drawn from that one mapset's raster and vector maps,
  the "Keep the PNG preview" checkbox, and the small argument fixes `d.title`
  (`-d`) and `d.vect.thematic` (`algorithm=int`) need. Every input must name a
  map of the same mapset. `main.run_display_module()` renders, adds the RGB
  layer to the map and reports it; it no longer exports RustGIS layers first.
- The catalogue carries `render_runnable`, `render_reason` and
  `render_inputs`; the tree marks render modules with **▸** and
  `[renders a picture]`, and the details text says the result is a picture, not
  a dataset.
- Tests: `tests/display_test.py` runs three real GRASS renders (raster,
  `d.his`+`d.rgb`, vector framing) when GRASS and GDAL are present;
  `tests/interface_test.py` and `tests/raster_test.py` cover the triage, form,
  plan and arguments. `make check` is 128 passing and `ruff check` is clean.

### Verification

- Regenerated manifest: 64 tools, 38 commands, 7 ribbon groups, 24 panel
  items, 1,177 catalogue entries (88 raster, 91 mapset, 19 display runnable),
  version 0.10.0.
- Real renders from a chosen mapset produce a georeferenced, three-band RGB
  GeoTIFF; a vector-only render frames the layer at 1001×1001 instead of one
  pixel.
- With no mapset chosen, `d.rgb` keeps its red/green/blue fields visible and
  the panel says to choose a project and mapset, instead of hiding them and
  leaving only the flags.
- `d.mon start=cairo` was confirmed not to persist; the direct-render
  environment was confirmed to work across separate processes.

### Files changed

- `grass_bridge/interface.py`, `grass_bridge/session.py`,
  `grass_bridge/raster.py`, `main.py`, `generate_manifest.py`.
- `tests/interface_test.py`, `tests/raster_test.py`, `tests/display_test.py`.
- `README.md`, `HISTORY.md`, `debian/changelog`, `man/rustgis-grass-setup.1`.

## This session — form-driven mapset runs (0.9.0)

### Objective

Let a module the form can describe actually run when it does not read one raster
and write another. `t.in.era5` was the case that exposed it: the form showed its
variables, dates and prefix, but Run Module answered "takes no raster", so the
import could never start.

### What changed

- `interface._mapset_runnability()` marks a module whose family is Temporal,
  Database, General or Miscellaneous, and whose required parameters are all
  either form fields or defaulted, as runnable in a chosen mapset. A required
  raster, space-time dataset, vector, table or output name the form cannot name
  keeps its reason. Result: 91 more modules run from the form (179 in all).
- The catalogue carries `mapset_runnable` and `mapset_reason`; the tree marks
  these with **▸** and `[in a chosen mapset]`, and the details text says to pick
  a project/mapset under **Projects and mapsets**.
- `main.run_module_in_mapset()` validates the chosen mapset, checks required
  form fields (`raster.missing_form_values`), builds the arguments with
  `form_args`, and runs `session.Run.mapset_module()` in that mapset. Nothing is
  copied to a throwaway mapset, so an imported dataset stays.
- `database.chosen_mapset()` accepts a mapset or a map node and rejects `..`,
  separators and a folder without `WIND`.
- `main.run_module()` refuses a module that is neither runnable on the chosen
  raster nor mapset-runnable, stating the catalogue's reason, instead of trying
  it on the raster anyway.
- A form label is short (at most 48 characters) and the full GRASS description
  is its tooltip; the panel wraps a label in a narrow column. Earlier, a long
  description widened the whole column and pushed the value box out of the
  pane, which made `t.in.era5`'s fields unreachable.
- A display module (`d.*`) is refused with "needs a display" instead of the
  misleading "takes no raster".
- Created datasets are named by the module's own prefix parameter (t.in.era5's
  `output_prefix`); no required output name is invented.
- A module command may now declare `"timeout"` seconds (1 to 86400) in
  `plugin.json`; `run-module` declares 86400, because a download does not fit
  the two minutes a command normally gets. `process::call` uses it through
  `call_with_timeout`. The host docs and validation are updated.
- `i.pca`'s `keys`/range fix and the form are unchanged; the generator now
  prints the mapset count, and `plugin.json` is 64 tools, 38 commands, 7 groups,
  24 panel items, 1,176 catalogue entries, version 0.9.0.

### Verification

- `make check`: 112 tests pass (interface, raster, database, mapset run, form
  labels, validation and the refusal), and `ruff check` is clean.
- `cargo test -p rustgis-plugins`: 40 pass, 2 ignored, including
  `command_timeouts_are_bounded`.
- Generated manifest: 88 raster modules, 91 mapset modules, 1,176 forms.
- Real smoke test in a throwaway GRASS database: `g.region -p` runs in a chosen
  mapset, and `r.mapcalc` writes a raster there.

## This session — the chosen module's form (0.8.0)

### Objective

Close the gap the previous session measured: every readable module was reachable
from the panel, but only a tool or a curated command had a form, so a
tree-driven module could only run on GRASS's own defaults. Give the panel a
**Module parameters** form filled from the chosen module's
`--interface-description`, and pass those values to `run-module`.

### What RustGIS needed

The host's panel kinds were text, checkbox, slider, button and tree. A form is a
sixth kind, because a plugin cannot know a module's parameters at manifest-build
time and the panel state is the only channel that can carry them. The host
change is in `~/dev/RustGIS`:

- `crates/plugins/src/panel.rs`: new `FormField` (`id`, `kind`, `label`, `help`,
  `choices`, `default`, `required`, `integer`), `form` in `KINDS`, limits
  `MAX_FORM_FIELDS=64`, `MAX_FORM_FIELD_ID=64`, `MAX_FORM_CHOICES=256`,
  `ItemState.fields`, `PanelState::form` / `form_value`, and normalization in
  `apply`: values are made to the declared kind, a field the new module lacks is
  dropped, a new field starts at its default. `set_values` merges a form update.
- `crates/ui-egui/src/pluginpanel.rs`: `form()` renders a two-column grid of
  text boxes, number boxes (red stroke when the text is not a number),
  checkboxes, selection lists and multi-selection lists. Text and number fields
  send on losing focus, the others at once; a required field is marked `*`.
  `State.typing` keeps a half-typed number from being overwritten by a state
  refresh.
- Tests: two panel tests (a form takes its fields and starts at defaults; it
  ignores fields and values it cannot take) and one UI test (the number field
  reads whole and fractional text, and rejects `3.5` where a whole is needed).

The host still accepts the old manifests unchanged: a panel without a form
behaves as before.

### What the plugin did

- `grass_bridge/interface.py`: `parse` was split into `_specs` (which keeps
  `help`, `multiple`, `integer` and the number of `keydesc` items) and `parse`;
  new `form_fields` maps a parameter to text, number, checkbox, select or multi,
  clips a label to 200 and help to 2,000 characters, and leaves out what the
  panel's caller names (input, output, layer) or cannot pass (rasters, tables).
  A numeric parameter with more than one key value, or a string default, becomes
  text, so `i.pca`'s `rescale=0,255` survives.
- `grass_bridge/raster.py`: `form_of` exposes the cached fields, and `form_args`
  turns the form's values into GRASS arguments: a checked flag becomes `-n`, a
  multi-selection `name=a,b`, a select is checked against the module's choices,
  a whole number loses its `.0`, and an empty or unknown value is left out.
- `main.py`: `run_module` appends `raster.form_args(...)` to the free input and
  output arguments; `panel_state` sends `"form": {"fields": ...}` for the chosen
  module in both the tree refresh and the mode refresh.
- `generate_manifest.py`: a `form` panel item (the 24th) between the chosen
  module's details and Run Module, and a `form` list on each catalogue entry,
  so the panel can show parameters without another GRASS call.
- Tests: form mapping (choices, whole numbers, multi-values, label/help, and a
  range staying text), `form_args` (flags, choices, multi, numbers, empty text,
  unknown fields), and the panel state carrying the chosen module's fields.
  `make check` is 100 passing.

### Verification

- `cargo test -p rustgis-plugins` — 39 passed, 2 ignored; the panel tests
  include the two new form cases.
- `cargo test -p rustgis-ui-egui --lib pluginpanel::tests::a_form_field_reads` —
  passes; `cargo check -p rustgis-ui-egui` is clean.
- `make check` in the plugin — 100 passed.
- The regenerated manifest has 1,176 catalogue entries, each with its form;
  `r.slope.aspect` shows `format`, `precision`, `zscale`, `min_slope`, `nprocs`,
  `memory` and its flags; `i.pca` shows `rescale` as text with `0,255`;
  `t.in.era5` shows its 35 climate variables and pressure levels as multi
  fields.
- Panel items: 24 (limit 32). Version 0.8.0.

### Files changed

- `grass_bridge/interface.py` — `_specs`, `parse`, `form_fields`, `keys`.
- `grass_bridge/raster.py` — `form_of`, `form_args`, details wording.
- `main.py` — form arguments in `run_module`; form fields in `panel_state`.
- `generate_manifest.py` — form item, catalogue forms, version 0.8.0.
- `tests/interface_test.py`, `tests/raster_test.py` — form tests.
- `README.md`, `skills/grass/SKILL.md`, `HISTORY.md`, `TODO.md`,
  `debian/changelog`, `man/rustgis-grass-setup.1`, `.gitignore`.
- `~/dev/RustGIS/crates/plugins/src/panel.rs`,
  `~/dev/RustGIS/crates/ui-egui/src/pluginpanel.rs`,
  `~/dev/RustGIS/crates/plugins/src/lib.rs`.

## Possible next steps

- Run temporal modules once space-time dataset handling is designed.
- Consider a lighter `module-details` command so selecting a module does not
  re-send the full tree.
- Replace the two-minute command cap or amortise GRASS project creation for
  larger rasters.
