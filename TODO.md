# TODO — RustGIS GRASS Plugin

Detailed development checklist, in the order the work was done. Every completed
step is written as a DONE paragraph; remaining work follows at the end.

## 1. Survey the plugin and the host

### DONE — Locate the plugin and its generated artefacts

The plugin lives in `~/dev/rustgis-grass-plugin`, with `main.py` as the
protocol loop, `generate_manifest.py` as the manifest builder, and
`grass_bridge/` holding the GRASS-facing modules. `plugin.json` and
`modules.json` are generated, not committed, because they carry GRASS's own
parameter labels. The installed GRASS is `/usr/local/bin/grass` (`GRASS
8.6.0dev`).

### DONE — Read the RustGIS plugin contract

The RustGIS source is `~/dev/RustGIS`. Its plugin docs (`docs/plugins.md`) and
manifest schema (`crates/plugins/src/manifest.rs`) define the limits that
shaped the design: 64 tools, 32 parameters per tool, 256 commands, 8 tab
groups, 32 panel items, 5,000 tree nodes, depth 8, 200-character node ids,
4,000-character runtime text, 32 menu items, and menu depth 4. The panel state
model is in `crates/plugins/src/panel.rs`; the panel UI and search are in
`crates/ui-egui/src/pluginpanel.rs` and `crates/ui-egui/src/chrome.rs`.

### DONE — Establish the tool/command split

Vector modules are geoprocessing tools: they receive GeoJSON and return
GeoJSON, make no host requests, and only 64 fit the manifest. Raster modules
are commands: they ask RustGIS to export a GeoTIFF (`share.exportRaster`), run
GRASS, and add the result back (`layer.addData`), which needs the `files` and
`edit` permissions. A command has no form, so the bridge can name only its
input and output and must leave every other parameter at GRASS's default.

### DONE — Cache the GRASS module descriptions

All module forms were read with `<module> --interface-description` and cached
at `/tmp/opencode/iface.json` (1,174 readable modules, 5 failures). This made
the runnability analysis repeatable without spawning GRASS for every question.

## 2. Analyse the catalogue

### DONE — Count and classify the modules

The installation exposes 1,174 readable modules across all of GRASS's
families (Raster, Vector, Imagery, Temporal, Planetary, Display, 3D Raster,
Database, General, Miscellaneous, Tests and PostScript), addons included. Only
64 vector modules fit the 64-tool budget.

### DONE — Work out what Run Module can honestly drive

The catalogue was filtered through progressively stricter rules. A loose
"reads a raster or writes one" gave 358 modules, but many of those need a
second raster, an imagery group, coordinates, a config file or a display. The
final rule requires one required raster input, at least one raster output, at
most one required raster output, an output that is not a basename, an input
that is not `multiple=yes` or a base-name band reader, no required flags, and
a default for every other required parameter. That gives 88 runnable modules:
Raster 70, Imagery 9, Planetary 9.

### DONE — Define the reason vocabulary

Every non-runnable module gets a short reason: `takes no raster`,
`writes no raster`, `needs an input chosen for it`, `needs N raster inputs`,
`writes N rasters`, `writes several rasters`, `needs several bands`,
`needs a display`, `needs flag -X`, `needs <names>`, `needs an imagery group`,
`needs a config file`, or `needs coordinates`. The full list is stored in the
catalogue so the panel never has to guess.

### DONE — Catch the non-obvious traps

Three cases were easy to mislabel. `r.watershed` lists five optional raster
inputs before its required elevation, so choosing the first port was wrong.
`r.slope.aspect` and friends have several optional raster outputs, so keeping
only the first output was wrong. `r3.cross.rast` has a required 3D raster
named `input`, which the old "plumbing" rule silently skipped and wrongly
offered as runnable. `i.landsat.toar` and `i.landsat.acca` take a base name and
read bands beside it, so they need several bands, and Display modules need a
display.

## 3. Implement runnability — `grass_bridge/interface.py`

### DONE — Add temporal detection

`TEMPORAL_ELEMENTS` recognises `stds`, `strds`, `stvds`, `str3ds` and `stdsp`,
so a module reading a space-time dataset can be described as temporal even
though it may also declare a raster port.

### DONE — Add the prompt and needs helpers

`_prompt()` reads a `gisprompt` element whichever attribute names it.
`_needs_text()` turns required parameter names into readable phrases such as
"needs an imagery group", "needs a config file" and "needs coordinates".

### DONE — Add `_runnability(task)`

The helper collects raster inputs, raster outputs, required parameters and
required flags, then applies the final rule and returns `runnable`, `reason`,
`needs`, `raster_input`, `raster_output`, `bands` and `temporal`.
`describe()` merges those fields into each catalogue entry.

### DONE — Fix the plumbing and base-name mistakes

Required parameters are no longer skipped merely because their name is
`input`, `output` or `layer`; only the chosen input and output are exempt.
Base-name inputs and Display modules are refused with explicit reasons.

## 4. Extend the catalogue — `generate_manifest.py`

### DONE — Store every raster port and the chosen run ports

Each catalogue entry now carries all `raster_in` and `raster_out` names plus
`raster_input`, `raster_output`, `runnable`, `reason`, `needs`, `bands` and
`temporal`. The chosen input/output are what Run Module names; the full port
lists keep the catalogue honest about what the module reads and writes.

### DONE — Generate commands only for runnable modules

Curated raster commands are produced only when `entry["runnable"]` is true.
The curated list shrank from 27 commands to 18 while keeping the same five
ribbon menus (Terrain, Hydrology, Filters, Surfaces, Sun).

### DONE — Relabel and explain the module tree

The panel tree is now "GRASS modules (runs here first)" and its help explains
the three branches and the search. A new "Chosen module" text item sits under
the tree, and the tree's command is `raster-state` so selecting a module
refreshes that text immediately. French translations were added for the new
strings.

### DONE — Reorganise the ribbon

The panel moved out of the Database group. A new **Modules** group now holds
`panel` and `run-module`, and `run-module` was removed from the Raster group.

### DONE — Bump the manifest version

`plugin.json` is generated as version `0.5.0`.

## 5. Rebuild the tree — `grass_bridge/raster.py`

### DONE — Replace the flat tree with three branches

`catalogue_tree()` returns `branch/runs`, `branch/all` and `branch/recent`.
"Runs from here" lists only runnable modules; "All modules" lists every
module with its reason where needed; "Recently run" lists the last twelve.
Family branches are built by `_family_nodes()`.

### DONE — Make node ids branch-aware

`NODE_PREFIXES` and `module_of()` strip `runs/`, `all/` or `recent/` before a
module is looked up. `entry_for()` accepts prefixed ids and refuses a family
or branch with a request to choose a module. `_clip()` keeps labels within
RustGIS's 200-character limit.

### DONE — Make labels searchable and informative

`_module_label()` puts the runnable triangle, module name, GRASS summary,
keywords and, for blocked modules, the reason into each leaf. That lets the
panel's search find a module by what it does, not only by its name.

### DONE — Describe the chosen module

`module_details()` says what the module reads and writes, whether it runs
here, its family, its needs, its temporal nature and its keywords. A module
that cannot run explains itself before Run Module is pressed.

### DONE — Remember recent modules

`recent_path()`, `read_recents()` and `remember()` keep the last twelve
modules in `~/.cache/rustgis-grass-plugin/recent.json`, newest first, without
duplicates. Writes are atomic and a cache that cannot be written never fails
a run.

### DONE — Name the correct input and output

`free_module_args()` uses the chosen `raster_input` and `raster_output`, not
the first listed ports, and raises with the catalogue reason when the module
is not runnable.

## 6. Wire the commands — `main.py`

### DONE — Update `run-module`

The command resolves the prefixed node, runs the module, remembers it,
rebuilds the tree with recents, and fills the details text.

### DONE — Update curated raster commands

Every successful curated raster run calls `raster.remember()` so the module
appears under "Recently run" next time the panel opens.

### DONE — Update `panel_state`

Opening the panel now reports how many modules run from here, resolves the
chosen module, builds the three-branch tree with recents, and fills the
details item.

## 7. Test the work

### DONE — Add interface tests

`tests/interface_test.py` now covers the runnable happy path, optional raster
ports, imagery-group needs, several-band inputs, required flags and
parameters, temporal detection, the 3D-raster-named-input regression,
base-name band readers and Display modules.

### DONE — Add tree and catalogue tests

`tests/raster_test.py` covers the three branches, prefixed node ids, family
and branch refusals, choosing the required ports, refusing non-runnable
modules with their reason, details text, newest-first recents, the cap and a
broken recents file, and an unwritable cache.

### DONE — Run the suite

`python3 -m pytest -q tests` passes 89 tests. `make check` passes under the
Debian build as well.

## 8. Document the change

### DONE — Update the README

The README now says 88 runnable modules instead of 358, 18 curated commands
instead of 27, explains the three tree branches, the reason labels, the
Modules group, base-name and imagery caveats, and installs version `0.5.0`.

### DONE — Update the AI skill

`skills/grass/SKILL.md` describes the three branches, the triangle mark, the
reason strings, branch-prefixed node ids and the Recently run list.

### DONE — Update packaging documentation

`debian/changelog` has a `0.5.0` entry, `man/rustgis-grass-setup.1` is bumped
to `0.5.0`, and `.gitignore` points its release exception at the new package.

## 9. Build and verify

### DONE — Build the package

`make deb` produced `dist/rustgis-grass-plugin_0.5.0_all.deb`, with the test
suite passing during the build.

### DONE — Validate the generated manifest

`rustgis-cli commands --plugin . --no-plugins` loaded `plugin.json` and
listed all 28 commands, which proves the manifest passes RustGIS's own
validation.

### DONE — Exercise the panel state

`rustgis-cli run --plugin . --no-plugins` with `raster-state` produced the
three-branch tree and the "Choose a module" details text. With a chosen
module, the details text listed its reads, writes, family and keywords.

### DONE — Run a module end to end

Using `crates/map/testdata/qgis/generated/data/dem.tif`, the sequence
`layer.addData`, `raster-state`, choose `runs/r.slope.aspect`, `run-module`
ran `r.slope.aspect`, wrote `DEM_r-slope-aspect.tif`, recorded
`["r.slope.aspect"]` in `recent.json`, and updated the status and details.

## 10. Imagery group and catalogue mode

### DONE — Always show the Recently run branch

`catalogue_tree()` now returns `branch/recent` even when nothing has run,
labelled `Recently run (0)` with no children, so the panel always has its
three branches.

### DONE — Add family filtering and mode nodes

`MODE_FAMILIES`, `mode_family()` and `mode_nodes()` were added to
`grass_bridge/raster.py`. `catalogue_tree(..., family=...)` keeps only that
family, labels the all branch `All imagery modules (176)`, and filters the
Recent branch too.

### DONE — Add the Catalogue mode tree

`PANEL` has a `mode` tree ("Catalogue") holding All modules and Imagery, with
counts. `panel_state(req, mode=None)` keeps or sets the mode, fills the mode
tree, filters the module tree and says "Showing imagery modules only." in the
status line.

### DONE — Add the Imagery ribbon group and commands

`IMAGERY_COMMANDS` gives the seven runnable i.* modules commands under
Enhance, Preprocess, Detect and Geometry. The new Imagery group holds the
panel, `imagery-state` and those menus. `all-state` in the Modules group
restores the whole catalogue. Both commands call `panel_state` with the
matching mode, which returns the value so the mode tree reflects it.

### DONE — Keep the filter after a run

`run_module` reads `values["mode"]` and rebuilds the module tree with the same
family filter after a run.

### DONE — Test and document

Tests cover family filtering, mode nodes and lookup, the empty Recent branch,
and panel-state mode wiring. `python3 -m pytest -q tests` passes 93 tests. The
README and SKILL describe the Imagery group, the Catalogue mode and the seven
imagery commands; the manifest now carries 37 commands, 6 ribbon groups, 23
panel items and 1,175 readable modules.

### DONE — Bump and package 0.6.0

`plugin.json` is generated as version `0.6.0`. `debian/changelog` has a `0.6.0`
entry, `man/rustgis-grass-setup.1` is bumped, the README installs the new
package, and `.gitignore` points its release exception at
`dist/rustgis-grass-plugin_0.6.0_all.deb`.

## 11. Temporal group and catalogue mode

### DONE — Add the temporal mode

`MODE_FAMILIES` in `grass_bridge/raster.py` gains `mode/temporal` → `Temporal`.
`mode_nodes()` now lists All modules, Imagery and Temporal with their counts,
so the panel's Catalogue tree can show the 74 `t.*` modules.

### DONE — Add the Temporal ribbon group and command

A new `temporal-state` command opens the panel in the temporal mode, as
`imagery-state` does for imagery. The new Temporal ribbon group (between Vector
and Modules) holds the panel and Temporal Modules. The panel and module-tree
help, and the French strings, name the temporal filter.

### DONE — Keep the temporal catalogue honest

No temporal module is offered as runnable, because a temporal module reads a
space-time dataset rather than one raster. The catalogue reports 66 as
**takes no raster** and 8 as **writes no raster**, and the details text already
explains that a temporal module reads a space-time dataset, not one raster.

### DONE — Test, document and package 0.7.0

Tests cover temporal family filtering, the temporal mode in `mode_nodes`, and
the `temporal-state` dispatch. `python3 -m pytest -q tests` passes 95 tests.
README, SKILL and HISTORY describe the Temporal group and mode. `plugin.json`
is version `0.7.0`; `debian/changelog`, the man page, the README install line
and the `.gitignore` exception point at the `0.7.0` package. The refreshed
catalogue has 1,181 installed / 1,176 readable modules, 38 commands, 64 tools,
7 ribbon groups and 23 panel items.

## 12. The chosen module's form

### DONE — Add a form kind to the RustGIS panel

`crates/plugins/src/panel.rs` now has `FormField` (id, kind, label, help,
choices, default, required, integer), `form` in `KINDS`, and the limits 64
fields, 64-character ids and 256 choices. `ItemState.fields` carries a module's
fields, `PanelState::form` and `form_value` read them, and `apply` normalizes a
form: a value is made to its field's kind, a field the new module does not have
is dropped, and a new field starts at its default. `set_values` merges an update
from the UI. Two panel tests cover it.

### DONE — Draw the form in the panel

`crates/ui-egui/src/pluginpanel.rs` renders a two-column grid: text, number
(red when the text is not a number), checkbox, select and multi-select. Text
and number fields send when they lose focus; the others send at once. A
required field is marked `*`, and `State.typing` keeps a half-typed number from
being overwritten by a state refresh. One UI test covers the number parsing.

### DONE — Read the fields from GRASS

`grass_bridge/interface.py` maps a module's parameters to form fields, leaves
out the input, output and layer the caller names and the rasters and tables the
panel cannot pass, and marks whole numbers, multiple choices and required
fields. A number with several key values, or a string default, stays text, so a
range such as `i.pca`'s `rescale=0,255` is not lost. Labels and help are clipped
to what RustGIS shows.

### DONE — Send the form with Run Module

`grass_bridge/raster.py` turns the form's values into GRASS arguments: flags,
choices, multi-values and numbers, leaving out empty and unknown values.
`main.py` appends them to `run-module`'s free arguments, and `panel_state` sends
the chosen module's fields with the details. `generate_manifest.py` adds the
`form` panel item and puts each module's fields in `modules.json`.

### DONE — Test, document and package 0.8.0

`make check` is 100 passing; the RustGIS panel tests and the UI number test
pass. The README, the skill, this history, the changelog and the man page name
the form, the 24 panel items and version `0.8.0`; the `.gitignore` exception and
the README install line point at the `0.8.0` package.

## Remaining work

### TODO — Run temporal modules from a space-time dataset

A temporal module needs an STRDS, not one raster. A real implementation would
export the chosen layer into the throwaway GRASS project, create and register
an STRDS, run the module and export its raster result; a one-map STRDS would
make most `t.rast.*` operations trivial, and the plugin ABI has no space-time
dataset kind. Design this before offering any `t.*` command.

### TODO — Consider a lightweight `module-details` command

Selecting a module currently re-runs `raster-state`, which re-sends the full
~1,300-node tree. A dedicated command could return only the details text and
keep selection cheap, at the cost of one more command.

### PARTLY DONE — The two-minute cap

A command may now declare `"timeout"` in `plugin.json`; `run-module` asks for a
day, so `t.in.era5` is not cut off. Raster runs still use the two-minute
default, because they copy the whole layer through a temporary project: narrow
the region first, or give the curated raster commands a longer timeout once
their progress is reported.

### PARTLY DONE — Let the form make more modules runnable

Done for temporal, database and general modules whose required parameters are
form fields or defaulted: 91 more run, each in the project/mapset chosen under
Projects and mapsets, and `run-module` now checks required fields first.
Still open:
- A required space-time dataset, raster or vector the form cannot name still
  blocks the module (t.rast.aggregate, t.rast.series). Offer the datasets from
  the chosen mapset in the form, or a second tree feed.
- A required output name is not invented; modules such as `v.in.ogr` cannot run
  until the form offers output names or the bridge names them.
- Raster modules that need several rasters or bands remain commands only.

### TODO — Refresh the screenshot

`plugin_grassgis_030.png` predates the Imagery and Temporal groups, the
three-branch tree, the catalogue modes and the details text. A new screenshot
would show the current ribbon and panel.
