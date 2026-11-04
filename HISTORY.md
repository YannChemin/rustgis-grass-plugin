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

## Verification

- `python3 -m pytest -q tests` → 89 passed.
- `rustgis-cli commands --plugin . --no-plugins` loaded the generated manifest
  successfully and listed all 28 commands.
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

- 1,174 modules read; 5 could not be read.
- 64 vector tools; 64 more could have fit.
- 18 curated raster commands (down from 27).
- 88 modules runnable via Run Module: Raster 70, Imagery 9, Planetary 9.
- 22 panel items (limit 32).
- 28 commands, 64 tools, 5 ribbon groups.
- Tree size about 1,300 nodes (limit 5,000).

## Files changed

- `grass_bridge/interface.py` — `TEMPORAL_ELEMENTS`, `_prompt`,
  `_needs_text`, `_runnability`, `describe`.
- `grass_bridge/raster.py` — `catalogue_tree`, `entry_for`, `module_details`,
  `remember` / `read_recents`, `free_module_args`.
- `generate_manifest.py` — catalogue fields, runnable-only commands, version,
  panel/tab groups, i18n.
- `main.py` — tree, details and recents wiring.
- `README.md`, `skills/grass/SKILL.md`, `debian/changelog`,
  `man/rustgis-grass-setup.1`.
- `tests/interface_test.py`, `tests/raster_test.py`.
- `.gitignore`, `dist/rustgis-grass-plugin_0.5.0_all.deb`.

## Possible next steps

- Add a dedicated Imagery ribbon group and imagery-specific catalogue mode.
- Add a Temporal group/mode once space-time dataset handling is designed.
- Consider a lighter `module-details` command so selecting a module does not
  re-send the full tree.
- Replace the two-minute command cap or amortise GRASS project creation for
  larger rasters.
