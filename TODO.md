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

### DONE — The panel is four steps, and the tab is decluttered (0.11.0)

*Superseded in part by the three-tab entry below: there are three steps now,
drawn as tabs.*

RustGIS draws a panel as one flat column with no section, tab or accordion, so
24 widgets with four trees in them was several screens of scrolling. A `step`
dropdown and `grass_bridge/panel.py` make it four steps -- project and data,
layer and region, terrain, modules -- with every answer setting each widget's
`visible` from the step, so at most eleven of 25 are drawn. The ribbon went
from 141 entries to 122 in seven groups, the 27 keyword-made vector menus (20
of them holding one tool) to nine themed ones, and every command and menu
carries an icon of its own. `minRustgisVersion` is 0.6.0, because the panel's
`form` and `choice` items came after 0.5.0 and an unknown panel item kind is a
hard manifest error. `UX_REFACTOR.md` is the survey this came from.

### DONE — Save Workspace, and the stack the right way up (0.11.0)

A workspace was read and never written. **Save Workspace** (`data-save`,
`main.save_workspace`, `database.write_workspace`) puts the project's GRASS
layers back: which maps are in it, in which order, ticked or not, at what
opacity, and the view as the display's extent.

**It writes a sibling, `<name>_rustgis.gxw`, not the file it read** (`{"to":
"<path>.gxw"}` for another target). The `.gxw` is GRASS's own file, and a
GRASS GUI session holding it open rewrites it on exit, so an overwrite could
be silently undone by the application already using it. The user chose this
over overwriting with a backup.

**The original tree is edited, not regenerated.** A `.gxw` carries the GUI's
`<layout>` panes and notebook, each layer's `<task>` with its `d.vect`
colours, icons and sizes, and `<nviz>` 3D state -- none of which this plugin
models, and all of which a generated file would drop. So it is parsed, the
first display's layer list rebuilt, and the rest left as it stands; a
surviving layer keeps its own task, a new one gets `d.rast`/`d.vect` with
`map=`. ElementTree discards the doctype, so
`<!DOCTYPE gxw SYSTEM "grass-gxw.dtd">` is written back by hand.

What cannot be saved is named, not guessed: a layer that is not a map of that
GRASS project (a file from disk, a basemap, a web layer), a view that will not
project (the display's own extent is kept), and a workspace with no
`<display>` (refused).

**The stacking bug this turned up.** The first `<layer>` of a display is the
**top** of the stack: GRASS writes its layer tree top first
(`core/workspace.py` walks it from its first child) and draws it bottom first
(`lmgr/layertree.py`'s `GetVisibleLayers` reverses the tree before rendering),
so the first element is drawn last. RustGIS lists its layers top first too
(`crates/map/src/lib.rs`: "in drawing order, top first") and `layer.addData`
inserts at 0. Load Workspace added them in document order, so **every
workspace came in upside down**; it loads from the bottom up now. Read out of
GRASS's and RustGIS's own sources, not inferred.

### DONE — A ribbon press with nothing chosen opens the tree (0.11.0)

**Add Map**, **Load Workspace** and **Browse Mapset** read the node chosen in
the panel's GRASS Data tree, and all three are on the ribbon as well as in the
panel. A ribbon button cannot be greyed out -- a command carries no runtime
state -- and the tree is drawn by the Project & data step alone, so a press
from the ribbon with another tab showing, or with nothing chosen, answered a
red error naming a tree the user could not see:

```
Load Workspace: choose a GRASS workspace under Workspaces, not a project or a map
Add Map: choose a map or an imagery group in the GRASS Data tree, not a project or a mapset
```

**They are off the ribbon now**, by the user's call: a press from there could
only ever be blind, and the panel's own buttons sit beside the tree whose
choice they act on. The Data group keeps **GRASS Database**, which needs
nothing chosen. **Run Module** stays, being the point of the tab, and answers
a press with no module chosen by showing the catalogue on the Modules tab
(`main.ask_for_module`), where it used to say `'None' is not a module of this
GRASS installation`. All four are still commands, so a script reaches them
with `map`, `workspace`, `mapset` or `module` in the parameters.

For a press made while the panel is open, the press is also taken as what it
means (`main.ask_in_tree`): the panel is put
on the step that draws the tree, with the tree in it, and the line says what
to choose and which button to press after. Where something wrong was chosen it
is named (`Normandie/PERMANENT is not a workspace under Workspaces`). The
chosen node is only sent back when there is one, because RustGIS keeps a
tree's value only while it was among the nodes last sent and `""` is no node.

**A plugin cannot open its own panel.** `ui.pane.plugin` is the host's own
command, the `ui.*` family is not reachable from a plugin (RustGIS refuses it
to scripts by the same rule), and a command's `panel` answer updates the
stored state without showing the pane. So the line goes to the message log
through `host.notify` as well, which is all a press can do when the panel is
closed. Removing the three from the ribbon would be the alternative; they are
genuine shortcuts once the panel is open, so they stay.

Verified through `rustgis-cli` on the real database: each of the three presses
answers the line and leaves the panel on `data`, and `data-workspace` with a
workspace named in its parameters still loads it (`Basemap`, 25 layers).

### DONE — Three tabs, and the curated terrain runs removed (0.11.0)

The fourth step held **Slope**, **Aspect** and **Viewshed**: three curated runs
with hand-written parameter widgets (degrees or percent, observer height, max
distance, earth curvature) and a **Viewpoint on the Map** pick. Once the
**Module parameters** form was built from each module's own
`--interface-description`, those three were a second, narrower path to
*r.slope.aspect* and *r.viewshed* -- fewer parameters than GRASS declares, and
code to maintain beside the general path. They are gone, with the step, the
widgets, the pick, their three ribbon buttons, `OPERATIONS`, `module_args`,
`RasterRun.raster_tool`, `run_raster_command`, `picked_point` and nine tests
that pinned them. The ribbon's **Terrain** menu still reaches the modules.

The three remaining steps are drawn as a **row of tabs**, not a dropdown. That
needed a new panel item kind in RustGIS: `choice` is an egui `ComboBox`, so
reading three labels cost a click and a menu. `tabs` holds `options` and a
value exactly as a `choice` does -- the two share a new
`panel::picks_an_option(kind)` -- and `pluginpanel.rs` draws it as a
`horizontal_wrapped` row of `selectable_label`s. Changed in RustGIS:
`crates/plugins/src/panel.rs`, `crates/plugins/src/tests.rs` (the pinned kinds
message, plus two tests for the new kind), `crates/ui-egui/src/pluginpanel.rs`.
`cargo test -p rustgis-plugins` is 70 passing; `rustgis-cli plugins install`
accepts the manifest and each tab draws its own widgets (data 7, layer 10,
modules 9 of 20). The plugin suite is 200 passing. **This package needs a
RustGIS build that has the `tabs` kind**: an unknown panel item kind is a hard
manifest error, so an older build refuses the whole plugin.

## Remaining work

### SUPERSEDED — Run temporal modules from a space-time dataset

This entry asked how to build an STRDS from a RustGIS layer: export the chosen layer into a
throwaway project, create and register a one-map STRDS, run the module, export the result. It
was never needed. The temporal modules were made runnable the other way round, in the mapset
path: they read the **real** datasets of the project and mapset chosen under Projects and
mapsets, which is where a user's space-time data actually is, and write their results there.
A one-map STRDS made from a single layer would have been a toy by comparison -- most
`t.rast.*` operations over one map are meaningless.

What is genuinely not possible stands: the plugin ABI has no space-time dataset kind, so a
`t.*` **command** on the ribbon, or a dataset as a tool parameter, is still out. The panel is
the place for them, and that is where they now are. See the form entry below.

### DONE — A lightweight command for each panel choice

Choosing a module re-ran `raster-state`, which rebuilt and sent all 1,424
catalogue nodes, 270 KB of JSON, for a choice that cannot change them;
choosing a layer did the same. `module-pick` answers the details, the form,
the status and whether Run Module is worth pressing, and makes no host request
at all; `layer-pick` answers the layer's source, bands, region and status.
A tree's nodes are now sent only by the step that draws it
(`grass_bridge/panel.py`), the raster tree excepted: it is one node per raster
layer and a tree keeps a chosen value only while its nodes were last sent.

### DONE — A panel pick for the region

RustGIS 0.6.0's `pick` panel item asks for a point or a box on the map.
**Viewpoint on the Map** (point, terrain step) was where `r.viewshed` looked
from; it went with the curated terrain runs, above.
**Region from a Box** (box, layer step) runs the new `region-box` command,
which sets the Analysis Environment's extent from the box's degrees; a box
across the antimeridian or with no height is refused, since the extent is four
increasing degrees. Verified on a 200x200 UTM 30N test DEM through
`rustgis-cli`: two picked points gave 28,000 and 4,003 visible cells of 40,000.

### NOT WORTH DOING — A session plugin

`"session": true` keeps one program running between commands, which would hold
the parsed catalogue and one throwaway GISDBASE instead of creating a project
per run, and would hear `layers` and `project` events.

**The saving was measured on 2026-11-16 and it is not there.** The claim this
entry used to make -- about ten seconds of project creation per run -- was
wrong. Best of three, on the small test DEM:

| Stage of one raster run | Time |
|---|---|
| `grass -c` (project creation) | 0.05 s |
| `r.in.gdal` | 0.22 s |
| `g.region raster=` | 0.19 s |
| the module itself (`r.slope.aspect`) | 0.21 s |
| `r.out.gdal` | 0.22 s |
| python start + parsing the 3.3 MB `modules.json` | 0.04 s |

A session would save project creation and the interpreter start: about 0.1 s
of a roughly 3 s run, 3 %. Everything else is the export, the import and the
module, which a session does not touch. Against that it would carry the whole
of the risk -- a GISDBASE living across runs, stale state between them, and a
`.gislock` left behind if its input closes without cleanup -- and it still
could not refresh its own panel (`plugin.panel` is `Effect::Reserved`, and
`user_only()` refuses every `plugin.*` id to a plugin, so an event can warm a
cache but not redraw the pane).

Revisit only if a measurement changes: a GRASS installation whose start-up is
far slower, or a reason to need the `layers`/`project` events for something
other than speed. See `UX_REFACTOR.md` 3.5.

### DONE — The two-minute cap, as far as the host allows

Every raster command now declares `"timeout": 86400` in `plugin.json`, so the
command line, Python and scripts no longer cut off `r.watershed` on a large
DEM or a `t.in.era5` download.

The desktop app is the part that cannot be fixed from here: it runs commands
on its window's own thread and stops them at 120 seconds whatever the manifest
says. Neither the request nor `host.info` tells the plugin which host it is in,
so raising the run's own deadline would mean being killed mid-write on the
desktop — the thing the deadline exists to prevent. The run therefore keeps to
120 seconds unless the caller, who does know, passes `timeout` in the command's
own parameters (`session.budget_asked`, 1 to 86,400 seconds, refused rather
than ignored when it is neither). When a run does run out, the message says how
long it was given and how to ask for more.

A host flag in `host.info` would let the plugin choose for itself; that belongs
upstream in RustGIS, not here.

### DONE — Let the form make more modules runnable

**276 modules run** from the panel's form, each in the project/mapset chosen under Projects and
mapsets: 88 on the raster path, 169 in a mapset, 19 display modules. `run-module` checks the
required fields first.

A word on the wording this entry used to carry. It said a required dataset or output "the form
cannot name" blocked a module, which is what the code itself said in `interface._cannot_name`.
That was wrong, and it hid how small the work was. GRASS declares these parameters
`type="string"` and `--help` shows nothing unusual about them: `t.rast.series` has a plain
`input=name` and `output=name`. What the bridge reacts to is the `<gisprompt>` that `--help`
never prints:

```
input  | required yes | type string | gisprompt: age=old, element=strds
output | required yes | type string | gisprompt: age=new, element=cell
```

A text box would hold either name perfectly well. So refusing them was a **policy, not an
inability**, and both halves are now done:

- **Inputs** (`age="old"`): a dataset parameter is a dropdown of the chosen mapset's own
  datasets, listed with `t.list type=<kind> mapset=<name> format=line` in a throwaway mapset so
  the user's is never locked. 27 modules carry one. 3D rasters come from `grid3` (a folder, so
  free), which also fixed a misreport: the 3D branch ran before the age check, so
  `t.rast.to.rast3` was told it "needs a 3D raster" when what it needs is a **name** for the one
  it writes.
- **Outputs** (`age="new"`): a new map or dataset is a text field, and the name is checked
  before GRASS starts -- its shape (`G_legal_filename`'s rules) and whether the mapset already
  holds one by that name. A taken name is refused by name; `--overwrite` is never passed. A
  `multiple` output takes a comma list, a single one refuses one. 30 modules name what they
  write, `t.rast.series`, `t.rast.aggregate`, `t.rast.mapcalc`, `t.rast.extract`,
  `t.rast.patch` and `t.rename` among them.

229 -> 252 -> **276 runnable**. Verified on `~/grassdata/BusogaForestryCom` (13 real datasets):
`t.rast.list` and `t.rast.univar` on `s2_B04@PERMANENT`, and `t.rast.series` wrote
`zzz_claude_b04_mean` (min 1191, max 4317.6) from its 20 Sentinel-2 maps, which was then
removed again; `output=basemap.r` was refused as taken, `output=my result@PERMANENT` as
malformed.

Still open, and each for a stated reason rather than for want of a field:

- **A file path to write** -- 10 modules (`t.rast.export`, `g.ppmtopng`, `m.csv.clean`,
  `m.printws`). The promise this plugin keeps is about maps in a mapset, which it can list.
  Nothing here can promise anything about an arbitrary path on disk, so a file output is not
  offered rather than offered unsafely. If it is ever wanted, the honest shape is the plugin's
  own output folder with a generated name, not a free path.
- **A new database table** -- 8 modules (`db.copy`, `db.dropcolumn` and the `db.*` family, which
  also need an existing table). Both halves need `db.tables`/`db.columns` run against the
  mapset's connection, which is a GRASS run per form build; worth doing only if the `db.*`
  family is actually wanted from the panel.
- **Raster modules that need several rasters or bands** -- 113 (88 need 2 to 5 rasters, 25
  several bands): `i.albedo`, `i.biomass`, the `i.eb.*` family, `i.cva`. Structural, not a
  policy: the raster path exports the one layer chosen in the panel's tree and imports one
  result, and there is one tree and one band slider. It is the same ceiling that makes the
  desktop's two-minute cap bite, and the reason this repo's own conclusion is that heavy raster
  work belongs in a crate in the RustGIS tree rather than behind the plugin ABI.
- ~~A script still cannot reach these modules in one call.~~ **Done**: `run-module` now takes
  `mapset` (`"<project>/<mapset>"`, or a full node id) and `values` (the module's parameters by
  their form field ids) beside `module`, laid over the panel so a parameter wins where both say
  something. Five calls became one. They go through the same code, so nothing is bypassed: a
  mapset that is not there, a dataset the mapset does not hold and a taken output name are each
  refused as they are from the panel. The raster path needs no equivalent -- it needs a layer
  RustGIS holds, which `raster` already names.

### DONE — The raster path counts the form it was given in 0.8.0

Found from a screenshot on 2026-11-16: `r.buffer` showed **Distance zone(s) 100** in the form
and, right under it, *"Not runnable from this panel: needs distances"* with Run Module greyed
out. The user's words were "r.buffer does not have input and output" -- true, and by design on
this path (the input is the chosen layer, the output the imported result); what was wrong was
refusing the module for a parameter the form was already showing.

`_runnability` asked only whether GRASS gave the parameter a default. It was written before the
form existed (0.8.0) and never learned about it, exactly as `_cannot_name` had not: the same
mistake in the one path still untouched. `_mapset_runnability` had been taught, which is why
temporal modules ran and raster ones did not.

**88 -> 160 raster modules, 276 -> 348 runnable overall.** `r.buffer`, `r.lake`, `r.carve`,
`r.catchment`, `r.extract`, `i.topo.corr`, `i.modis.qc`, the whole `r.li.*` landscape-index
family. The manifest gained 5 curated commands, `r.buffer` among them, since a command is only
generated for a runnable module.

Two things keep it honest:

- Only a **plain value** counts. The raster path runs in a throwaway project holding just the
  exported layer, so a typed imagery group, vector, dataset or table name would name nothing
  there; `MAPSET_ELEMENTS` keeps those refused. The group test that failed when this was first
  written was right, and is now the test for that rule.
- A required field left empty is caught **before** the export and the GRASS run, as the mapset
  path already did.

Two more bugs the same screenshot exposed, both fixed:

- **A parameter taking several numbers was a single number box.** `r.buffer` takes
  `distances=100,200,500`; one box holds one zone, so the module's own point was unreachable
  even once it ran. A `multiple` numeric parameter is now a text field, as a range already was.
- **The run message claimed "with GRASS's own defaults"** whatever the form had sent. It now
  names them: `with distances, units from the form and GRASS's own defaults for the rest`, and
  the follow-up line says what the bridge set as against what the form set.

### DONE — A workspace found in a backup opens from where it actually is

Reported from the app on 2026-11-16:
`/home/yann/SSD256Gb/20221128_MBP_backup/grassdata/Normandie/Nounours.gxw names GRASS project
<Normandie> in /home/yann/grassdata, which is not there`.

The message was accurate and the behaviour was wrong. The file is from 2021 and records
`/home/yann/grassdata`, which exists today and has no `Normandie` in it: the project went to a
backup drive and the `.gxw` went with it, one folder away from where it was looked for. Since a
`.gxw` lives in `<database>/<project>/`, the file's own location is better evidence than the path
it records. `database.workspace_place` now tries the recorded database, then the folder the file
is in (taking that folder's name as the project, so a renamed copy works), then this machine's
database, accepting a place only when the mapset's `WIND` is there.

Measured over the user's own 26 workspaces: 7 failed, **4 now open** (Normandie among them --
19 layers, EPSG:2154, framed on its own extent), and the remaining 3 are `.gxw` files kept in
folders of scripts whose project was never copied along. Those are still listed, with
`- project not found` in the label and Load Workspace **disabled**, and pressing it anyway names
every database tried rather than only the first.

### PARTLY DONE — Refresh the screenshot

The standard reference image is **`plugin_grassgis.png`**, the one `README.md`
embeds (the older `plugin_grassgis_030.png` is gone). It was refreshed on
2026-11-16 and now shows the 0.11.0 ribbon: GRASS, Data, Region (with
**Region = Box**), Terrain, Imagery and Vector, with Modules behind the **›**
overflow at that window width. The README's caption was rewritten to match it
and no longer says the picture predates the refactor.

Two things would still improve it, whenever the app is next open:

- **The panel is not in it.** The shot shows the layer list, so the four steps,
  the picks and the module tree -- the whole point of the 0.11.0 refactor --
  are not visible anywhere in the README. A second image of the panel, or one
  shot with the panel open, would show them.
- **It has a bug frozen in its status bar**: `.: ./plugin.json: No such file or
  directory (os error 2)`, bottom right. That was the stray relative `.` entry
  in RustGIS's plugin folder list, removed on 2026-11-16 (see the entry below),
  so a new shot will not show it.

### DONE — Harmonise the CRS when a GRASS map is loaded into the view

Asked for on 2026-11-16. Measured first, because the diagnosis mattered:
RustGIS 0.6.0 **does** read a georeferenced raster's coordinate system and
reproject it for display. A UTM 30N GeoTIFF added beside its EPSG:4326 twin
comes back with degree extents matching it to five decimals, so a GRASS map
was never in the wrong *place*, and a file with no coordinate system is
refused outright ("the file's coordinate system isn't recognised"), not
misplaced.

What was missing is the view's own projection: a map from a projected GRASS
project was drawn in whatever world projection the view happened to be in, not
in the system the user's GRASS work is in. `Add Map` now puts the view in the
GRASS project's own system (`database.Export.crs` reads `srid=` from
`g.proj -g`; `main.harmonise_projection` calls `map.projection`), the same
step the QGIS import makes (`crates/engine/src/cmd/qgis.rs`).

It only changes the view when that cannot move someone else's data: either the
view is still in a world projection, or the map is the only thing in it. A
view already in another EPSG system is left alone and says so. Verified
through `rustgis-cli`:

| View before | Other layers | Result |
|---|---|---|
| `globe`/`mercator`/`robinson` | --- | becomes `EPSG:32630` |
| `EPSG:32630` (the same) | --- | left; "already in" |
| `EPSG:32631` | yes | left; "the map is reprojected for display" |
| `EPSG:32631` | no | becomes `EPSG:32630` |
| any | --- | XY project refused, naming the project |

A projection RustGIS refuses does not fail the load: the layer is there and
reprojected for display, so the message says what was not done. `Add Map` also
takes `{"map": "raster/<project>/<mapset>/<name>"}` in its own parameters now,
because a tree's value cannot be set by a script that has not browsed the tree
(the same escape hatch `run-module` has).

Still open, if it ever matters: the vector path writes a GeoPackage, which
carries its own system, and was not re-measured here; and the display (`d.*`)
path imports its picture with a `.pgw` world file into the GRASS project, so
it inherits that project's system by construction.

### DONE — Offer imagery groups through `d.rgb`/`d.his`, not as separate bands

Asked for on 2026-11-16. A mapset's `i.group` groups are now listed above its
loose rasters (`database.groups` reads `group/<name>/REF`, so no GRASS run is
needed to list them), and `Add Map` composes one into a single RGB layer
through the existing display path (`session.DisplayRun.render_mapset`).

`raster.group_display` chooses the module from the band count: `d.rgb` for
three or more (the first three; the rest are named as left out), `d.his` for
two (hue, intensity). The **group's own band order** decides the channels,
because that is the order given to `i.group`. A group of one band is refused
with the advice to add the band itself, and the tree labels it
`(group of 1, not a composite)` so the refusal is predictable rather than a
surprise. A `REF` line that is not a `<map> <mapset>` pair is skipped: a wrong
map in a composite is worse than a missing one.

Every message says the layer is a picture of the bands, not their values, as
the `d.*` path already does.

Verified through `rustgis-cli` on groups of 1, 2, 3 and 4 bands.

### DONE — Find and offer the `.gxw` workspaces as projects

Asked for on 2026-11-16. The workspaces found in the GRASS database and under
the home folder are listed above the projects in the Data tree, labelled by
the project and mapset they open and their layer count (the file name is
almost always `default.gxw`). **Load Workspace** opens one: every raster and
vector of its first map display, in order, with a layer the workspace had
unticked loaded but not drawn; then the view's coordinate system and the
display's own extent, projected with `m.proj`.

Three things the notes above worried about, as they turned out:

- **The scan is cheap once it prunes the right thing.** Not depth: the GRASS
  mapsets. Walking them took **6.5 s** (this database holds 35,000 maps);
  skipping any folder with a `WIND` file takes **0.27 s** for the same 26
  workspaces, so there is no cache to go stale. The database is listed rather
  than walked, since GRASS writes a project's workspace beside it.
- **"Clean from any previous project" cannot be done as asked.** `project.new`
  carries `Effect::Replaces`, which RustGIS reserves to the user: a plugin is
  refused it outright ("plugins can't run another plugin's code, automation or
  reserved actions"). Clearing the layers is what a plugin may do, and that is
  what it does; the messages say the project's own name and file are unchanged
  rather than implying a new project. A project with unsaved changes stops the
  load unless `{"discard": true}` is passed.
- **Loading is a button, not a click on the name.** The request was to load on
  clicking the workspace, but a click in a tree is easy to make by accident
  and this one clears the project's layers. Clicking selects it and the status
  says what will happen; **Load Workspace** does it.

Verified on this machine's own workspaces: Maldives (2 layers, framed on
73.33, 3.89 to 73.59, 4.34) and IGN (6 layers, of which only the one ticked in
GRASS is drawn). A geographic project (EPSG:4326) is reported as it is -
RustGIS refuses a degrees system as the view's projection - without failing
the load.

### DONE — The `.` in RustGIS's plugin folder list

On 2026-11-16 RustGIS 0.6.0 failed at start-up with

```
.: ./plugin.json: No such file or directory (os error 2)
```

`rustgis-cli plugins install .` records the path **as given**, so a relative
one goes into `~/.local/share/rustgis/plugins/state.json` verbatim and is then
resolved against whatever working directory RustGIS is launched from -- which
is never the plugin's folder. The entry was removed (a backup of `state.json`
is beside it) and the start-up error is gone.

Two things to keep in mind:

- Always register with an absolute path: `rustgis-cli plugins install
  "$PWD"`, never `.`. Canonicalising the path belongs upstream in RustGIS;
  `plugins uninstall` takes an id, not a folder, so a bad entry cannot be
  removed through the CLI when another folder declares the same id.
- `state.json` still lists **two** folders that both declare `grass-vector`:
  the development tree `~/dev/rustgis-grass-plugin` and the installed copy
  `~/.local/share/rustgis-grass-plugin`. Only one of them can win, and which
  is not stated anywhere. Keep the installed copy for using the plugin and the
  development tree only while working on it.
