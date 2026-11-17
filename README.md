# GRASS GIS tools for RustGIS

A [RustGIS](https://github.com/opengeos/RustGIS) **process plugin** that runs GRASS GIS modules:
vector modules as geoprocessing tools, raster modules as commands with a panel. It is a working
prototype for
[opengeos/RustGIS#1249](https://github.com/opengeos/RustGIS/issues/1249), which proposes the same
bridge as a crate in the RustGIS tree.
[GRASS_INTERFACE.md](GRASS_INTERFACE.md) is the survey of RustGIS's extension points this was
designed from, written before the prototype and partly superseded by it.

![RustGIS with the plugin's GRASS ribbon tab and its panel open, the panel on its Modules tab
showing the chosen layer, the computational region and the module catalogue, and the map showing
the layers of a GRASS workspace that was loaded](plugin_grassgis.png)

Above is the plugin's own **GRASS** ribbon tab: **GRASS** opens the panel, **Data** puts the
GRASS database in RustGIS's browser, **Region** sets the computational region from the view, the
layer or a box drawn on the map, **Terrain** runs the common raster modules in menus by theme,
**Imagery** does the same for the imagery modules, **Vector** holds the 64 generated tools in
nine themed menus, and **Modules** holds **Run Module** and the **Catalogue** filters.

The panel is at the right, on the last of its three tabs, **Modules**, which carries the
catalogue: **Runs from here (348)**, the modules this panel can drive, **All modules (1195)**,
every one installed with its reason for not running here, and **Recently run**. Above them it
keeps the chosen layer and the computational region in sight, because a run is about to use
them.

The map is a **GRASS workspace** opened by the plugin -- `Basemap/default.gxw` -- and its layer
list is worth a look: `mrds_trim`, `reefs`, `powerplantMW`, `mines` from the top down, two of
them unticked, which is the workspace's own stack and its own `checked` flags.

GRASS is not bundled, linked or copied here. Each run spawns the `grass` launcher already
installed on the machine, and every tool's form is read from that installation at build time with
`<module> --interface-description`. Nothing of GRASS — code, help text or module descriptions —
lives in this repository, which is why a GPL-2.0-or-later program can be driven from an
Apache-2.0 GIS this way.

## What it offers

Everything the installation has. On this machine that is **1,205 modules**, addons included, of
which **1,195** could describe themselves:

| Family | Modules | Family | Modules |
|---|---|---|---|
| Raster (`r.*`) | 456 | General (`g.*`) | 55 |
| Vector (`v.*`) | 225 | Display (`d.*`) | 49 |
| Imagery (`i.*`) | 186 | 3D Raster (`r3.*`) | 35 |
| Temporal (`t.*`) | 80 | Database (`db.*`) | 22 |
| Planetary (`p.*`) | 67 | Miscellaneous (`m.*`) | 14 |
| Tests (`test.*`) | 4 | PostScript (`ps.*`) | 1 |

They are reached three ways, because the ABI gives three and each has a ceiling:

| Route | Covers | Ceiling |
|---|---|---|
| **Tools**, with a generated form in the Tools pane | 64 vector modules | a manifest holds **64 tools**, and a tool takes no raster, so only vector modules qualify: 128 do, half of them fit |
| **Commands** on the ribbon | **18 common raster modules** and **7 imagery modules** in menus by theme, the region and the database | a manifest holds up to **256 commands**, and a command opens no dialog, so each needs the panel to be told anything |
| **Run Module**, from the panel's tree | **all 1,195** are reached and show their parameters; **348** can be run: the **160** that read one raster and write one, **169** temporal, database and general ones whose form is all they need (imports such as `t.in.era5`, changes to a map of the chosen mapset in place such as `r.colors` and `v.db.update`, and the modules that read a space-time dataset of that mapset and write a new map or dataset into it, such as `t.rast.list` and `t.rast.series`), and **19** display modules that render a picture | a command has no form of its own, so the panel's **Module parameters** form sends the values it holds; the rest need several rasters at once, a file path, or a database table |

The tree is searchable and has three branches: **Runs from here** (the 348), **All modules**
(all 1,195, each with its reason for not running here) and **Recently run**. A **Catalogue**
dropdown above it keeps all modules, only the imagery (`i.*`) ones, or only the temporal
(`t.*`) ones; the ribbon's **Modules › Catalogue** menu sets the same filter and brings the
panel to its module step.
Not every module reads one raster and writes another, so **Run Module** has three paths:

- A **temporal, database or general** module imports a dataset or changes the project it runs
  in. It runs from the form, writing into the project and mapset chosen under **Projects and
  mapsets**, so `t.in.era5` downloads a variable straight into a mapset and `r.colors` changes a
  map there in place. A parameter that names a **space-time dataset** becomes a dropdown of that
  mapset's own datasets, the way a map parameter becomes a dropdown of its maps, and one that
  names a **new map or dataset** becomes a text box whose name is checked against that mapset
  before the run. So `t.rast.list`, `t.rast.colors`, `t.rast.series`, `t.rast.aggregate`,
  `t.rast.mapcalc` and the rest run from the form. What stays refused is a **file path** to
  write (10 modules) and a **new database table** (8): nothing here can promise not to
  overwrite a path of the user's choosing, so it is not offered rather than offered unsafely.
- A **display** module (`d.*`) draws a picture of maps from that same mapset rather than writing
  one. The 19 that can draw without a monitor return it as an RGB raster layer, optionally with
  a PNG preview. Every input of a render comes from that mapset, and the fields stay visible when
  it holds no map of a kind.
- The **rest** need a live display, ask for a map to edit, or cannot run in this GRASS build.

A module Run Module can drive is marked **▸**; the others carry their reason — *needs several
bands*, *needs an imagery group* — and choosing one says what it reads and writes in **Chosen
module** before Run Module is pressed. The 65 modules that could have been tools but did not fit
are listed in `modules.json` under `toolsLeftOut`, as are the 10 that could not be read at all.

Choosing a module also fills the **Module parameters** form with that module's own parameters,
read from its GRASS interface description: text boxes, whole and fractional numbers, checkboxes
for flags, selection lists for choices, and multi-selection lists for parameters that take
several values (a climate variable set, pressure levels). A required field is marked `*`. A
parameter with a range, such as `i.pca`'s `rescale=0,255`, stays a text field, because one
number field cannot hold it. Fields start at the module's defaults; clearing a text field or a
selection leaves the parameter out, so GRASS uses its own default. Changing the chosen module
keeps the values of fields with the same name and starts the new ones at their defaults.

So "every GRASS module" is true for *reaching* them and for *showing their parameters*: 1,195
forms are generated from the installation. It is false for *running* them from the panel: 348
can be run, and the rest need several rasters at once, a name from a mapset the run never sees,
a file path or a database table. The 64-tool form
budget is the ABI's; the panel's form has no such budget.

### The panel: three tabs, not one column

RustGIS draws a panel as one flat column of widgets: there is no section or accordion, and each
tree gets up to 320 px of its own. Everything GRASS needs came to **24 widgets in one column,
four of them trees** — several screens of scrolling, with the GRASS database, the layer and
region, three curated terrain runs and the module catalogue interleaved.

It is three steps now, in the order the work is actually done, drawn as a **row of tabs** across
the top of the panel. Every answer sets each widget's `visible` from the chosen tab, so **at most
ten of its 20 widgets are drawn at once**:

| Tab | Holds |
|---|---|
| **Project & data** | the GRASS database tree (projects, mapsets, maps and workspaces), **Add Map**, **Load Workspace**, **Browse Mapset**, **GRASS Database** |
| **Layer & region** | the raster layer, the band sent to GRASS, the computational region, Region = Map View / Whole Layer / **from a Box**, the cell size |
| **Modules** | the Catalogue filter, the module tree, Chosen module, Module parameters, Run Module |

The tab row is a panel item kind of its own, `tabs`, which RustGIS did not have: a `choice` is
drawn as a dropdown, so the step chooser cost a click and a menu to read three labels. `tabs`
holds `options` and a value exactly as a `choice` does and draws them as a row of labels.

A fourth step used to hold **Slope**, **Aspect** and **Viewshed** — three curated runs with
hand-written parameter widgets and a **Viewpoint on the Map** pick. The form built from
`--interface-description` now drives *r.slope.aspect*, *r.viewshed* and every other module from
their own declared parameters, so the curated three were a second, narrower path to the same
modules. They are gone, with their widgets, their pick and their three ribbon buttons; the
ribbon's **Terrain** menu still reaches the modules themselves.

The chosen layer, the region and **Last run** stay visible in every step that acts on them, so a
run never hides what it is about to use. A command moves the panel to another step only when its
whole result lives there (**Browse Mapset**, and the three Catalogue filters); every other
command reports through **Last run**, where the user already is. **Run Module** is disabled for
a module the panel cannot drive, with the reason in **Chosen module**, instead of failing after
the click.

The step also decides what an answer *carries*. The module tree is **1,424 nodes and about
270 KB of JSON**, and a mapset's tree can be thousands of maps; RustGIS keeps what an answer
leaves out, so each tree is sent only by the step that draws it. Choosing a layer used to rebuild
and send the whole catalogue for a choice that cannot change it; it now runs `layer-pick`, and
choosing a module runs `module-pick`, which makes no host request at all. Measured here, on a
database of 62 projects, over the plugin's own protocol:

| Answer | Before | After |
|---|---|---|
| Opening the panel (first tab) | 277 KB | **18 KB** |
| Opening it on the layer tab | 277 KB | **1.5 KB** |
| Choosing a raster layer | 277 KB | **0.4 KB** |
| Choosing a module | 277 KB | **2.1 KB** |
| Opening the Modules tab | 277 KB | 277 KB — the catalogue is what that tab is for |

The **Catalogue** filter was a three-node tree inside a 320 px scroll area; it is a dropdown.

**Three buttons left the ribbon.** *Add Map*, *Load Workspace* and *Browse Mapset* each read the
node chosen in the panel's **GRASS Data** tree. A ribbon button cannot be greyed out for want of
one -- a command carries no runtime state -- and the tree they read is in the panel, which a
plugin cannot open (`ui.pane.plugin` is the host's own command and the `ui.*` family is not
reachable from a plugin). On the ribbon they could only be pressed blind, so they are buttons of
the panel alone now, beside the tree whose choice they act on. **GRASS Database** stays, because
it needs nothing chosen. **Run Module** stays as well, being the point of the tab: pressed with
no module chosen it answers the catalogue on the Modules tab and says to choose one, where it
used to answer `'None' is not a module of this GRASS installation`.

### Its own tab

The plugin has a **GRASS** tab rather than a group on **Plugins**, which had grown to 15 buttons
against a documented limit of 16. Seven groups, in the order the work is done, each entry with
an icon of its own:

| Group | Holds |
|---|---|
| GRASS | the panel |
| Data | GRASS Database |
| Region | Region = Map View, Region = Whole Layer, Region = Box, Refresh Rasters |
| Terrain | menus of raster modules: Terrain, Hydrology, Filters, Surfaces, Sun |
| Imagery | menus of imagery modules: Enhance, Preprocess, Detect, Geometry |
| Vector | the 64 tools in nine themed menus: Overlay & clip, Geometry, Points & lines, Proximity & sampling, Network, Point clouds & LIDAR, Generalize & clean, Transform & project, Tables & import |
| Modules | Run Module, and a Catalogue menu holding All, Imagery and Temporal |

What that fixed: GRASS's own keywords had put the 64 vector tools into **27 menus, 20 of them
holding a single tool** and two of them (`LIDAR` and `Lidar`) differing only in case — a column
of menus that each opened to one row. The keyword is still each tool's toolbox, which is what the
Tools pane and its search show, so nothing is lost. The panel was declared in three groups and is
now declared once; the three catalogue filters moved off the top level into a menu, because they
set what the panel's tree lists rather than running anything; and **32 of 38 commands carried the
same `stats` icon** while the 64 tools and 27 menus carried none, out of the 151 icons RustGIS
ships.

### What of RustGIS it uses

Everything the plugin ABI offers that a GRASS bridge can make use of, as of RustGIS 0.6.0:

| RustGIS gives | The plugin uses it for |
|---|---|
| `tools` with a generated form | 64 vector modules, with their GRASS parameters, flags and choices |
| `file` tool parameters | the rules, node and control-point files of `v.segment`, `v.net`, `v.extract`, `v.rectify`, `v.lrs.segment` |
| `tables` beside `layers` in a tool's result | rows a module writes without geometry |
| `commands` (up to 256) | 18 common raster modules, 7 imagery modules, the region, the database, the catalogue filters, and the three that drive the panel itself |
| `commands[].timeout` | a day for all 30 commands that run GRASS, so neither a download (`t.in.era5`) nor `r.watershed` on a large DEM is cut off at two minutes — on the command line, in Python and in scripts; the desktop app still stops a command at 120 seconds whatever the manifest says |
| a `tab` of its own, with compact columns and nested menus | the GRASS tab: GRASS, Data, Region, Terrain and Imagery (with menus by theme), Vector (nine themed menus), Modules — every entry with an icon of its own |
| a `panel`, with `tree` widgets that search and a `form` | the GRASS database, the map's rasters, the band, the module tree with its three branches, the chosen module's details, and its parameters as a form Run Module sends |
| a panel item's `visible` and `enabled` | the three tabs, which draw at most ten widgets of the 20 at a time, and Run Module disabled for a module the panel cannot drive |
| `choice` panel items | the Step dropdown and the Catalogue filter, which was a three-node tree |
| `pick` panel items | Region from a Box, which draws the computational region on the map |
| `raster.info` | refusing a raster with no coordinate system, describing the source, and sizing the band slider |
| `share.exportRaster`'s answer | saying when a run was made on a downsampled overview |
| `gp.env` | the computational region |
| `progress` messages | what a run is doing now, in the Tools pane |
| `skills` | a skill telling the AI Assistant when GRASS is needed and how these tools are addressed |
| `i18n` | the plugin's own interface text in French (GRASS's own text comes from the installation) |
| `minRustgisVersion` | 0.6.0, so an older RustGIS says why rather than loading half of it. It has to be 0.6.0: the panel's `form` and `choice` items came after 0.5.0, and a panel item kind an older RustGIS does not know is a hard manifest error — a 0.5.0 floor had the whole plugin refused |

What it still cannot use: a raster or 3D raster as a **tool** parameter (there is none), several
input layers at once, a module's output file, a database table, and more than 64 tools or 32
parameters per tool.

## Install

From the package, on Debian or Ubuntu:

```sh
sudo apt install ./dist/rustgis-grass-plugin_0.11.0_all.deb
rustgis-grass-setup          # once per user; again after upgrading GRASS
```

`rustgis-grass-setup` generates the manifest from the GRASS installed here and registers the
plugin with RustGIS. The package carries no manifest, because a module's parameter labels are
part of GRASS's own GPL documentation; `rustgis-grass-setup --remove` undoes both steps.

> **The first run takes a couple of minutes.** The manifest is read from GRASS itself, with one
> `<module> --interface-description` run per module — 1,204 of them here, 24 at a time, measured
> at **129 s** end to end on this machine; allow longer on a slower one, or the first time, when
> nothing is cached. Nothing is wrong: the step counts the forms as it reads them (`847/1204
> forms read (70%)`) and reports into
> [MetaMonitor](https://github.com/YannChemin/MetaMonitor)'s spool as **GRASS manifest**. It runs
> **once**, and again only after a GRASS upgrade or a new version of this package. RustGIS itself
> starts instantly afterwards: the plugin reads the generated `modules.json`, never GRASS's
> forms.

### From the source tree

Needs GRASS GIS 8 and Python 3 on the machine. `RUSTGIS_GRASS` names the launcher if it is not
on the `PATH`.

```sh
python3 generate_manifest.py                      # about 2 min: one GRASS run per module
rustgis-cli plugins install ./rustgis-grass-plugin
rustgis-cli run --sample \
  --cmd 'gp.run={"tool":"plugin:grass-vector/v-voronoi","params":{"input":"Cities"}}'
rustgis-cli run --cmd 'layer.addData={"path":"dem.tif"}' \
  --cmd 'plugin:grass-vector/r-slope-aspect={}'
```

The raster commands need the `edit` and `files` permissions, which the generated manifest asks
for: they are what lets the plugin have RustGIS write and read the GeoTIFFs it works on. The
vector tools need neither.

In the desktop app: **Plugin Manager › Settings › Add Plugin Folder…**. The tools then appear in
the Tools pane under **Plugins ›** and as a group on the **Plugins** ribbon tab; the plugin's own
**GRASS** tab carries the panel and the raster commands. A process plugin is **not sandboxed**:
it runs programs as you do, which is how it can reach GRASS at all.

`plugin.json` and `modules.json` are **not committed**: they carry GRASS's own parameter labels,
which are part of its GPL documentation. They are generated from your installation by
`generate_manifest.py`, which is also why that step comes before installing the plugin.

## How a vector run works

1. A throwaway GISDBASE is made in a temporary folder, with a UTM project for the data's own area
   and an EPSG:4326 project to export through. The whole folder is deleted afterwards, so no
   `.gislock` outlives a run.
2. The input layer's GeoJSON is imported with `v.import`, which reprojects it into UTM, so the
   module's distances and areas are in metres rather than degrees.
3. **The computational region is set from the input layer** (`g.region vector=…`).
4. The module runs, then `v.proj` and `v.out.ogr` bring the result back as longitude/latitude
   GeoJSON.
5. Every run reports the projection it used, the region it set, and each distinct GRASS warning
   with how often it was raised.

A parameter that takes a file is a RustGIS `file` parameter: the user picks the file in the
Tools pane, RustGIS reads it and sends its contents, and the bridge writes them into the run's
own folder for GRASS to read. That is how `v.segment`'s and `v.lrs.segment`'s rules,
`v.extract`'s category list, `v.net`'s node file and `v.rectify`'s control points are reachable;
the run says which file it read and how big it was. A file a module *writes* but declares as an
input (`v.rectify`'s `rmsfile`) is left out and reported instead, because a file picker cannot
name a file that does not exist yet.

Rows a module writes with no geometry — `v.distance`'s upload table, say — come back as a
standalone **table** rather than a layer with nothing to draw, and the messages count both
halves, so neither is dropped in silence.

`generate_manifest.py` prints what it had to leave out of each tool, and the mapper refuses what
RustGIS would not take rather than offering something that cannot work: a raster parameter, a
name with a digit in it (`v.gsflow.segments` has `width1`), a name the module declares twice (the
same module declares four of them twice over), and a file the module writes although it declares
it as one it reads (`v.rectify`'s `rmsfile`), since a file picker cannot name a file that does
not exist yet.

## How a raster run works

A tool cannot do this. RustGIS's plugin ABI gives a tool `layer`, `vectorLayer`, `polygonLayer`,
`pointLayer`, `field`, `numericField`, `number`, `text`, `choice`, `bool` and `file` parameters,
and lets it return GeoJSON layers, tables, a selection and messages: **no raster either way**,
and a tool "can log, but makes no host requests". A plugin *command* may call any RustGIS
command its permissions allow, which is enough to carry a raster in and out:

1. `host.layers` lists the map's layers; the panel's tree chooses one of the rasters (without a
   choice, the active one, or the only one), and the module tree chooses the module (without a
   choice, `run-module` says which modules it can drive).
2. `raster.info` describes it before it leaves: its coordinate system, size, cell size, value
   type and bands. A layer RustGIS read **without a coordinate system is refused** here, because
   `grass -c` on such a file makes a project with no projection and every distance the module
   reports is then in cells.
3. `share.exportRaster` writes it as a GeoTIFF (`files`). It writes **one band** of a raster that
   is not a colour one, so the panel's band slider says which; the slider's ends and the band
   names come from `raster.info`, so a hyperspectral cube's bands are all reachable, and the run
   says which band GRASS saw. If RustGIS holds the layer only as a **downsampled overview**, the
   export says so (`overviewOf`) and the run reports that its result is coarser than the file on
   disk.
4. A throwaway GISDBASE is made, with a project taking **the raster's own coordinate system**, so
   nothing is reprojected on the way in or out. `r.in.gdal` imports it and `g.region raster=…`
   sets the region from it, which **Analyze › Geoprocessing › Environments** then narrows (see
   below).
5. The module runs, and `r.out.gdal` writes the result.
6. `layer.addData` adds that file as a raster layer (`files` and `edit`), and the run reports the
   projection, the region's cells and extent, what the numbers mean, and each distinct GRASS
   warning with its count.

The result stays in `~/.cache/rustgis-grass-plugin/`, because RustGIS reads the file when the
layer is added and keeps the path; each message says where it is.

## The GRASS database

The panel's **Projects and mapsets** tree is the database GRASS itself uses, found the way GRASS
finds it: `GISDBASE` when set, otherwise the `GISDBASE:` line of `~/.grass8/rc`, otherwise
`~/grassdata`. Nothing here writes down a path.

| Step | What happens |
|---|---|
| Open the panel | The **workspaces** are listed first (below), then projects and mapsets are read from the file system — a project is a folder with a PERMANENT mapset, a mapset one with a `WIND` file. **62 projects, 58,773 maps**: the projects and mapsets in **0.001 s**, the whole tree in **0.36 s**, nearly all of it the workspace scan below |
| Choose a mapset | Its imagery groups are listed first, then its maps: `cellhd` entries are rasters, `vector` folders are vectors. They load only then, because 58,000 maps do not fit a tree that takes 5,000 nodes |
| Choose a map, then **Add Map** | It is exported and added to the project: a raster as a GeoTIFF, a vector as a GeoPackage, both of which carry the coordinate system. The view is then put in that GRASS project's own system (below) |
| Choose a **group**, then **Add Map** | Its bands are composed into one picture by the display module that fits, and added as a single RGB layer (below) |
| Choose a mapset, then **Run Module** | A temporal, database or general module runs in that mapset, so what it writes outlives the run: `t.in.era5` imports its space-time dataset there |
| Choose a **workspace**, then **Load Workspace** | Its GRASS project's layers are loaded, in the state the workspace left them |
| **GRASS Database** | Puts the database folder in the browser's **Folders** (`project.addFolder`) |

The status bar reports each one — *GRASS GIS Tools: forest_ndvi@PERMANENT added from IGN.*

Exporting runs in a **throwaway mapset of that project** (`grass --tmp-mapset`), reading the map
across mapsets as `name@mapset`. Nothing of the user's is written to, their own mapsets are never
locked, and a GRASS session they have open elsewhere is undisturbed. A **Run Module** for a
temporal, database or general module is the exception: it runs in the chosen mapset, because
the dataset it makes is meant to stay there.

### Workspaces: a project someone already set up

A GRASS workspace (`.gxw`) is the GRASS GUI's own file: XML naming a database, a project and a
mapset, with the layers that were displayed and whether each was ticked. They are listed **above**
the raw projects and mapsets, because a workspace is a project already arranged — labelled by
what it opens, not by its file name, which is almost always `default.gxw`:

```
Workspaces (26)
  Maldives/PERMANENT (2 layers) - Maldives/default.gxw
  IGN/PERMANENT (6 layers) - IGN/default.gxw
```

They are looked for in the GRASS database and under the home folder. **Where it does not look
matters more than how deep it goes:** a GRASS mapset — any folder holding a `WIND` file — is
never listed, because that is where a database's 58,000 maps are. Walking into them took **6.5 s**;
pruning them takes **0.32 s** for the same 26 workspaces, so the scan runs on each panel open
rather than being cached into something that can go stale. The database itself is not walked at
all: GRASS writes a project's workspace beside it, so one listing of the project folders finds it.
Hidden folders, `node_modules`, `venv`, `target` and the like are skipped, and the walk stops four
levels down.

**A `.gxw` outlives the machine it was written on, so the recorded path is a hint, not an
address.** One of these files from 2021 records `<database>/home/yann/grassdata</database>` and
the project `Normandie`. That database still exists; its `Normandie` does not — the project went
to a backup drive, and the workspace file travelled with it. So three places are tried, in order
of how much each is worth trusting:

1. the database the file records, while it still holds the project and mapset;
2. **the folder the file is in**, when that folder *is* the project — a `.gxw` lives in
   `<database>/<project>/`, so the file's own place says where its project is now. The folder's
   name is taken as the project, not the recorded one, so a copy renamed on the way to the backup
   still opens;
3. this machine's database, for a file kept away from its project.

A place counts only when the mapset's `WIND` is there, since that is what makes a folder a mapset
rather than a folder of the same name. Of 26 workspaces found on this machine, 7 could not be
opened from their recorded path and **4 of those open from the folder they are kept in**. The
other 3 are `.gxw` files in folders of scripts whose project was never copied along: they are
still **listed, with `- project not found` in the label** and **Load Workspace disabled**, the
way the module tree lists a module it cannot run. A file that was found and cannot be opened is
worth seeing with its reason; leaving it out would only raise the question of whether the scan
missed it.

**Start from an empty RustGIS project.** Loading a workspace **clears the layers of the project
it is loaded into**, because a workspace *is* a set of layers and merging two sets would give
neither. RustGIS opens on the **World Atlas** sample -- countries, cities, rivers and lakes --
so the first thing to do is make an empty project and load the workspace into that: the
**Project** button at the left of the ribbon opens the start screen, where **New Project > Map**
gives a blank map. Loading into a project with unsaved changes is refused outright; loading into
the sample removes its layers and reports how many went. The plugin cannot do this step for you,
because `project.new` carries RustGIS's `Replaces` effect, which is reserved to the user.

**Load Workspace** then opens one:

| | |
|---|---|
| Layers | Every raster and vector of its **first** map display is exported and added, in its order. A layer the workspace had unticked is loaded but **not drawn**, so the project matches what GRASS was showing. If the workspace has several displays, the first one's layers are loaded and the rest are reported, because RustGIS has one map |
| Coordinate system | The view is put in the GRASS project's own system, as **Add Map** does |
| Extent | The view is framed on the display's own extent, projected out of the project's system with `m.proj` |
| One bad layer | Reported and skipped, not fatal — a workspace that names a map since deleted still opens |

Two things it deliberately does **not** do:

- **It is not loaded by clicking the name.** Clicking selects it and says what will happen; the
  button does it. Loading clears the project's layers, and losing work to a mis-click in a tree
  is not something to do quietly.
- **It does not replace the project**, so it cannot make the empty one for you. `project.new`
  carries RustGIS's `Replaces` effect, which is reserved: a plugin may not replace someone's
  project, by design. What the plugin may do is clear the layers, which is what it does, and the
  messages say the project's own name and file are untouched rather than implying a new one. A
  project with **unsaved changes stops the load** entirely, unless `{"discard": true}` says
  otherwise.
- **It does not write back to the `.gxw` it read.** **Save Workspace** writes a sibling, below.

### Save Workspace writes a sibling, never the file GRASS owns

**Save Workspace** puts the project's GRASS layers back into a workspace: which maps are in it,
**in which order**, ticked or not, at what opacity, and the view as the display's extent. It
writes `<name>_rustgis.gxw` beside the workspace that was loaded, and the GRASS GUI opens it like
any other -- same project, same mapset.

A script names the workspace by its path -- `{"workspace": "<path>.gxw"}`, for **Load Workspace**
too, since a script cannot choose in a tree -- and `{"to": "<path>.gxw"}` chooses the target.
Otherwise the workspace saved is the one loaded last, remembered between runs.

It does **not** write the `.gxw` it read, and `to` is the only way to write anywhere else. Two reasons: the file is GRASS's own, and a GRASS GUI session holding it open
**rewrites it on exit**, so an overwrite could be silently undone by the application that was
already using it.

**The original file's tree is edited, not regenerated.** A `.gxw` carries much more than this
plugin models -- the GUI's `<layout>` panes and notebook, each layer's `<task>` with its `d.vect`
colours, icons and sizes, `<nviz>` 3D state -- and building a file out of what the plugin
understands would quietly drop all of it. So the file is parsed, the first display's layer list
rebuilt, and everything else left as it stands: a layer still in the project keeps its own
`<task>`, a layer new to the workspace gets the minimal one that draws it (`d.rast` or `d.vect`
with `map=`), and a layer no longer there is dropped. ElementTree discards the doctype, so
`<!DOCTYPE gxw SYSTEM "grass-gxw.dtd">` is written back by hand -- GRASS's own reader expects it.

What cannot be saved is said rather than guessed at:

| | |
|---|---|
| A layer that is not a map of that GRASS project | A file from disk, a basemap, a web layer: a `.gxw` names GRASS maps, so these are left out and listed by name |
| RustGIS styling | A new layer gets `map=` and nothing invented; an existing one keeps the task GRASS wrote. Colours set in RustGIS have no general `.gxw` equivalent |
| A view that will not project | The display's own extent is kept and a line says so, rather than failing a save whose layers are the point |
| A workspace with no `<display>` | Refused: there is nothing to save layers into |

**The stack is right way up.** The first `<layer>` of a display is the **top** of the stack:
GRASS writes its layer tree top first (`core/workspace.py` walks it from its first child) and
draws it bottom first (`lmgr/layertree.py`'s `GetVisibleLayers` reverses the tree before
rendering), so the first element is drawn last. RustGIS also lists its layers top first, and
`layer.addData` puts each new one on top -- so **Load Workspace** reads the layers from the
bottom up, and **Save Workspace** writes them from the top down. Loading used to add them in
document order, which turned the stack upside down.

### Imagery groups arrive composed, not as a stack of grey bands

A GRASS imagery group (`i.group`) is a named, **ordered** set of bands meant to be seen together.
Listing its members one by one means loading three grey layers and composing them by hand, so a
group is offered as one entry, above the loose rasters, and **Add Map** composes it:

| Bands in the group | Composed by | Channels, in the group's band order |
|---|---|---|
| 3 or more | `d.rgb` | red, green, blue — a fourth band and beyond are left out, and said to be |
| 2 | `d.his` | hue, intensity |
| 1 | — | refused: *"add that band on its own, as a raster"*, and the tree labels it `(group of 1, not a composite)` |

The group's own band order decides which band is which channel, because that is the order the
user gave `i.group`. The group is read from the mapset's `group/<name>/REF` file — `<map> <mapset>`
per line — like everything else in the tree, so no GRASS run is needed to list groups. A `REF`
line that is not a `<map> <mapset>` pair is skipped rather than guessed at: a wrong map in a
composite is worse than a missing one.

The render goes through the same path as the `d.*` modules (a cairo monitor, a `.pgw` world file,
`r.in.gdal`), so the result is a three-band GeoTIFF on the maps' own grid. Every message says what
it is: **a picture of the bands, not their values — for looking at, not for running analysis on.**

### The view's coordinate system

RustGIS reads a layer's coordinate system from the file and reprojects it for display, so a GRASS
map always lands in the right **place**: a UTM 30N GeoTIFF added beside its EPSG:4326 twin comes
back with degree extents matching it to five decimals, and a file carrying no system at all is
refused rather than misplaced. What RustGIS does not do is adopt that system as the **view's own**,
so a map from a projected GRASS project was drawn in whatever world projection the view happened to
be in -- not the system the GRASS work is in.

**Add Map** now harmonises it, the same step the QGIS import makes: it reads `srid=` from
`g.proj -g` and calls `map.projection`. It only changes the view when that cannot move someone
else's data under them:

| View before | Other layers in it | What happens |
|---|---|---|
| `globe`, `mercator`, `robinson` … | — | becomes the GRASS project's system |
| already that system | — | left alone, said to be |
| another `EPSG:` system | yes | **left alone** — the map is reprojected for display, so it is still in the right place |
| another `EPSG:` system | no | becomes the GRASS project's system |

A system RustGIS refuses does not fail the load: the layer is there, and the message says what was
not done. A map from an **XY project** is refused with its reason named — that project has no
system to write, so the export carries none and there is nothing to place it by.

Two things the host decides, not the plugin:

- **A plugin cannot add an entry to the Add Data menu or to Data Sources.** Those are RustGIS's
  own, and a plugin declares commands, tools, a tab and a panel — nothing else. `project.addFolder`
  puts the database in the browser, but a mapset's own files are GRASS's formats, which RustGIS
  has no reader for, so the folder is a signpost and **Add Map** is the way in. A data provider
  reading mapsets directly would have to live in the RustGIS tree.
- A GeoPackage written by GRASS from a project with a custom coordinate system comes back with
  `srs_id 100000` and no EPSG code, and RustGIS says so when it reads it as longitude/latitude.
  That notice is RustGIS's, and it is right to make it.

## The computational region

A GRASS raster module takes its extent and resolution from `g.region`, not from its inputs, so
that is what RustGIS's own **Analysis Environment** sets. Every run reads `gp.env` and applies it:

| In RustGIS | In GRASS |
|---|---|
| **Environments › Extent** (`view`, `full`, a layer, or four numbers) | `g.region n= s= e= w= align=src`, clipped to the raster and snapped to its grid |
| **Environments › Cell Size** (degrees) | `g.region nsres= ewres= -a`, converted to the raster's units at the region's latitude |
| The panel's **Cell size** slider (the raster's own units, 0 = off) | `g.region res= -a`, overriding the environment |

**Region = Map View** and **Region = Whole Layer** set the environment's extent to the view or
clear it, and **Region = Box** on the ribbon — the **Region from a Box** pick in the panel — asks
for a box on the map and sets the extent to it: the third way GRASS users expect to set a region,
beside the view and the whole layer. So the region can be driven without leaving the panel, and the panel shows the region in
force. A box drawn across the antimeridian is refused with its own message, because the
environment's extent is four increasing degrees and such a box would silently mean the rest of
the world. A degree of longitude shortens away from the equator, so a cell
size of 0.001° over a UTM raster at 43.31° N becomes 110.5 m north-south by 81.0 m east-west, and
the run says so.

Two consequences worth knowing:

- `r.slope.aspect` puts the region back on the elevation map's own grid unless it is given `-a`.
  The bridge passes `-a` whenever the region was narrowed, or the cell size asked for would be
  silently ignored.
- An extent that does not meet the raster is an error naming where to change it, not an empty
  result.

The vector tools get the extent for free and never see the cell size: RustGIS filters a tool's
features by the environment's extent before the tool runs (471 features of the sample `Cities`
layer become 80 under a European extent), and the region is then set from what arrives.

## Space-time datasets are read, not guessed

A map is a folder, so the plugin lists a mapset's maps from the file system and it costs
nothing — rasters from `cellhd`, vectors from `vector`, **3D rasters from `grid3`**, which is
why a `raster_3d=` parameter such as `g.region`'s is a dropdown of the mapset's voxel maps.
`g.list type=raster3d` would give the same answer and cost a GRASS run. A space-time dataset is
not a folder: it is a row in that mapset's own temporal database,
`<mapset>/tgis/sqlite.db`. The plugin does not read that database directly — its schema is
GRASS's business, not a thing to depend on — and asks GRASS instead:

```
t.list type=strds mapset=PERMANENT format=line
```

run in a `--tmp-mapset` that names the user's mapset with `mapset=`, so **the mapset the
datasets live in is never locked** and the user's own session is left alone. `strds`, `stvds`
and `str3ds` are each listed on demand, and only when the chosen module actually names one of
them, which 27 of 1,195 modules do. A project with no temporal database simply has no dataset
to offer: the field stays visible and says so, rather than the panel failing to open.

Nothing about such a parameter is visible in `--help`: GRASS declares it `type="string"` like
any other name. What marks it is the `<gisprompt>` in the module's interface description —
`age="old" element="strds"` for a dataset it reads, `age="new"` for a map it writes — and that
is what the bridge reads to decide which fields it can fill.

## Nothing a GRASS module needs is unclear; the limits are this plugin's

Every GRASS module describes itself exactly. `--interface-description` gives, for each
parameter: its name, its type, whether it is required, whether it takes several values, its
default, the values it permits, its description, and a `<gisprompt>` saying whether it names
something that already exists (`age="old"`) or something the module creates (`age="new"`), and
of what kind — `cell`, `vector`, `grid3`, `strds`, `dbtable`, `file`. The bridge reads all of
it; that is where every form in this panel comes from.

So **no module is ever refused here for being unclear**, and the reasons say so. Each names one
of exactly three limits, all of them on this side:

| The limit | What it looks like | Examples |
|---|---|---|
| **Where the run happens.** The raster path runs the module in a throwaway project holding only the exported layer, so a map, dataset or table of the user's own mapset is perfectly well described and simply not in the project the module opens | *another raster of the mapset, which this run does not open*; *needs an imagery group* | `i.topo.corr`'s second raster, `i.example`'s group |
| **What the panel hands over.** One layer tree, one band slider | *needs 2 raster inputs*, *needs several bands* | `i.albedo`, the `i.eb.*` family |
| **A promise this plugin keeps.** It never overwrites, and does not write to a path of the user's choosing | *a file path to write to, which this panel does not ask for*; *a new database table, which this panel does not ask for* | `t.rast.export`, `db.copy` |

The wording used to be *"which the form cannot name"*, which read as though GRASS had left
something out. It had not: the plugin had decided something, and the decision was sometimes
wrong — twice it outlived the thing that justified it (see **A required parameter the form
offers**, below, and the space-time datasets above). A reason that blames the data hides a
decision that can be revisited.

The panel also shows the reason that **bears on the module**, not whichever path happened to
answer first. Each path reports its own, so `t.rast.export` used to say *"takes no raster"* —
true, and nothing to do with what stops it, which is the file path. A vector module says it
works on features rather than on a raster, and points at the Tools pane where the 64 that fit
the tool budget are.

And whatever the reason, the module is still fully described and still runnable: the panel's
form shows every parameter GRASS declares, and the text names the command line that runs it —
`grass <mapset> --exec t.rast.export …`.

## A required parameter the form offers is not a reason to refuse

Until 0.11.0 the raster path asked only one question of a required parameter: does GRASS give it
a default? If not, the module was refused. That rule was written before the panel had a form and
never learned that it does, so `r.buffer` was listed as **"Not runnable from this panel: needs
distances"** with its own **Distance zone(s)** field filled in right above the greyed-out button.
It now counts the form, and **72 more raster modules run**: `r.buffer`, `r.lake`, `r.carve`,
`r.catchment`, `i.topo.corr`, `i.modis.qc`, the `r.li.*` landscape-index family and the rest.

Two conditions keep it honest:

- **Only a plain value counts.** This path runs the module in a throwaway project built around
  the one exported layer, where nothing of the user's mapset exists, so a typed imagery group,
  vector, dataset or table name would name nothing. Those keep their reason — `i.example` still
  says *needs an imagery group*, and `needs 2 raster inputs` is untouched.
- **A required field left empty is caught before the export and the GRASS run**, as the mapset
  path already did: `r.buffer needs distances before it can run`, not a GRASS error after the
  wait.

A parameter that takes **several** numbers is a text field, not a number box. `r.buffer` takes
`distances=100,200,500`, and one number box can hold one zone — which made the module's own
point unreachable even once it was runnable. The same already applied to a range such as
`i.pca`'s `rescale=0,255`.

The run message says what was actually sent: `r.buffer ran in …, with distances, units from the
form and GRASS's own defaults for the rest.` It used to say *"with GRASS's own defaults"* whatever
the form had supplied, which is the same untruth as the greyed-out button.

## Reaching a module from a script, in one call

The panel is a good way to run a module and a poor way to be scripted. RustGIS keeps a tree's
value only while that value was among the nodes the plugin last sent, and a form takes values
only for the fields it currently holds, so naming a module, a mapset and some parameters from
outside the panel used to take four calls to walk the panel there and a fifth to run. `run-module`
takes all three in the command's own parameters instead:

```
plugin:grass-vector/run-module={"module": "t.rast.series",
                                "mapset": "Busoga/PERMANENT",
                                "values": {"input": "s2_B04@PERMANENT",
                                           "method": "average",
                                           "output": "b04_mean"}}
```

`mapset` is `"<project>/<mapset>"`, or a full `mapset/<project>/<mapset>` node id. `values` are
the module's parameters by the form's own field ids. Both are laid **over** the panel, so a
parameter wins where both say something and the rest of the panel is untouched.

They are **not a way around a check**. The same code runs either way, so a mapset that is not
there, a dataset that mapset does not hold, and an output name already taken are each refused
exactly as they are from the panel:

```
t.rast.list runs in a GRASS mapset, and Nowhere/PERMANENT is not one of /home/yann/grassdata
t.rast.list: nope@PERMANENT is not a space-time raster dataset of the PERMANENT mapset
t.rast.series: the PERMANENT mapset already holds a raster map called basemap.r, and this
plugin never overwrites: choose another name for output, or remove that one in GRASS first
```

The raster path still needs a layer RustGIS holds, which is what `raster` names, so there is
nothing to add there: a script that has no layer loaded has nothing to run a raster module on.

## A name for what a module writes, and the promise around it

A module such as `t.rast.series` or `t.rast.aggregate` must be told what to call the map it
writes. The bridge **does not invent that name**, and the reason is not shyness: these modules
run in the user's own mapset, so a guessed name either collides with something real or scatters
`output_1` maps through their data. The name is typed into a text field, and what the bridge
adds is the check:

| | |
|---|---|
| Shape | Refused if GRASS would refuse it: no spaces, quotes, `@`, comma, `=`, `*`, `~` or `/`, and not starting with a dot or a dash |
| Already there | Refused by name — `the PERMANENT mapset already holds a raster map called basemap.r, and this plugin never overwrites: choose another name for output, or remove that one in GRASS first` |
| A dataset | Compared bare: a mapset lists one as `name@mapset` and a new one is named without it, so the collision would otherwise be missed |
| Several results | A `multiple` output takes a comma-separated list (`t.rast.series method=average,maximum`); a single one refuses a list rather than letting GRASS take the first |

All of it happens **before GRASS is started**, and `--overwrite` is never passed. That is the
whole promise: a name typed in haste costs an error message, not a map.

Three kinds of output stay refused, and the reason now names which: a **file path** (`t.rast.export`,
`g.ppmtopng` — the plugin cannot promise anything about a path of the user's choosing), a **new
database table** (`db.copy`), and a mapset name (`g.mapset`). The message says `needs a file path
to write, which the form does not offer` rather than the old catch-all about an output name.

## The two-minute cap

RustGIS stops a plugin command after two minutes. The run therefore carries its own deadline and
gives up with a readable reason instead of being killed with a half-written file behind it.
Measured here, `r.slope.aspect` end to end, project creation, export and import included:

| Raster | Wall time |
|---|---|
| 500 × 500 (250,000 cells) | 3.1 s |
| 4,000 × 4,000 (16,000,000 cells) | 9.5 s |

So the cap is generous for a per-cell module and useless for `r.watershed` on a national DEM.

RustGIS 0.6.0 lets a command declare its own `timeout`, and every raster command here declares a
day. **That only holds away from the desktop app**: the desktop runs commands on its window's own
thread and stops them at 120 seconds whatever the manifest says. Nothing in the request or in
`host.info` tells the plugin which host it is in, so it cannot raise its own deadline safely —
doing so on the desktop would mean being killed mid-write, which is what the deadline exists to
prevent. The run therefore still keeps to 120 seconds unless the caller, who does know, asks for
longer:

```sh
rustgis-cli run --cmd 'plugin:grass-vector/r-watershed={"timeout": 3600, "panel": {"raster": "3"}}'
```

A `timeout` outside 1 to 86,400 seconds, or one that is not a number, is refused rather than
quietly ignored, and when a run does run out the message says how long it was given.

That desktop ceiling, not the ABI, is now the reason raster work belongs in a crate rather than a
plugin.

## Watch out

- **The region is not optional.** A freshly created GRASS project has a region of one cell at the
  origin. Run `v.voronoi` without setting it and GRASS says `Found 0 points/centroids`; a raster
  module would quietly write a single cell. Step 3 above exists because of that.
- **A run pays for the trip, not for the project.** Each module call builds its own throwaway
  database, which sounds expensive and is not: measured here, project creation is **0.05 s** of a
  roughly 3 s `r.slope.aspect` run. The rest is the export out of RustGIS, `r.in.gdal`, the
  module and `r.out.gdal`, at about 0.2 s each. A session-scoped mapset would save the project
  creation and the interpreter start — about 3 % — so it is not worth the state it would keep
  (see `TODO.md`).
- Several input maps, 3D (`r3.*`) data, imagery groups and the modules that take a base name and
  read the bands beside it are not run by Run Module; a raster reaches a command, never a tool.
  Their parameters still appear in the form, but a run would need a different bridge.
- A raster that RustGIS holds as an overview is exported as that overview, and a raster that is
  not a colour one is exported one band at a time. Both are reported in the run's messages, so
  read them before taking a result for the whole file at full resolution.
- A tree widget only keeps a value that was among the nodes the plugin last sent, so a script
  passing `{"panel": {"raster": "3"}}` must run `raster-state` first, as the panel does when it
  opens. Since 0.11.0 the module tree is sent only by the module step, so a script naming a
  module must bring the panel there first, which the ribbon's **Run Module** and **Catalogue**
  buttons also do:

  ```sh
  rustgis-cli run --sample \
    --cmd 'plugin:grass-vector/panel-step={"panel": {"step": "modules"}}' \
    --cmd 'plugin:grass-vector/module-pick={"panel": {"modules": "runs/r.slope.aspect"}}'
  ```

  Without it RustGIS says *1 value(s) not taken … modules* and the plugin answers "Choose a
  module in the tree." **`run-module` needs none of that**: it takes `module` in the command's
  own parameters, which is the way to run one from a script —
  `plugin:grass-vector/run-module={"module": "r.slope.aspect", "panel": {"raster": "3"}}`. The
  module tree's ids carry a branch prefix (`runs/`, `all/`, `recent/`), which `run-module`
  strips; a family or branch node is refused with a request to choose a module.
- `v.generalize` has one parameter too many for a plugin tool's limit of 32; the generator keeps
  the required ones and says which it dropped.

## Tests

```sh
python3 -m pytest -q tests
```

The mapping tests use XML written for the tests and the raster tests cover the decisions made
around a module run, so neither needs GRASS. Two integration tests run real modules and skip
themselves when GRASS is not installed.

## Licence

Released into the public domain (The Unlicense). GRASS GIS itself is GPL-2.0-or-later and is
neither included nor modified here.
