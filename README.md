# GRASS GIS tools for RustGIS

A [RustGIS](https://github.com/opengeos/RustGIS) **process plugin** that runs GRASS GIS modules:
vector modules as geoprocessing tools, raster modules as commands with a panel. It is a working
prototype for
[opengeos/RustGIS#1249](https://github.com/opengeos/RustGIS/issues/1249), which proposes the same
bridge as a crate in the RustGIS tree.
[GRASS_INTERFACE.md](GRASS_INTERFACE.md) is the survey of RustGIS's extension points this was
designed from, written before the prototype and partly superseded by it.

![RustGIS with the plugin's own GRASS ribbon tab open, showing the GRASS, Data, Region, Terrain,
Imagery and Vector groups above the World Atlas sample map](plugin_grassgis.png)

Above is the plugin's own **GRASS** ribbon tab: **GRASS** opens the panel, **Data** reaches the
GRASS database and adds a map or an imagery group from it, **Region** sets the computational
region from the view, the layer or a box drawn on the map, **Terrain** runs slope, aspect and
viewshed or the common raster modules in menus by theme, **Imagery** does the same for the
imagery modules, and **Vector** holds the 64 generated tools in nine themed menus. **Modules**,
holding **Run Module** and the **Catalogue** filters, is past the right edge at this window
width, behind the **›** overflow.

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
| **Commands** on the ribbon | Slope, Aspect, Viewshed, **18 common raster modules** and **7 imagery modules** in menus by theme, the region and the database | a manifest holds up to **256 commands**, and a command opens no dialog, so each needs the panel to be told anything |
| **Run Module**, from the panel's tree | **all 1,195** are reached and show their parameters; **252** can be run: the **88** that read one raster and write one, **145** temporal, database and general ones whose form is all they need (imports such as `t.in.era5`, changes to a map of the chosen mapset in place such as `r.colors` and `v.db.update`, and the modules that work on a space-time dataset of that mapset such as `t.rast.list` and `t.rast.colors`), and **19** display modules that render a picture | a command has no form of its own, so the panel's **Module parameters** form sends the values it holds; the rest still need a name for what they write, or several rasters at once |

The tree is searchable and has three branches: **Runs from here** (the 252), **All modules**
(all 1,195, each with its reason for not running here) and **Recently run**. A **Catalogue**
dropdown above it keeps all modules, only the imagery (`i.*`) ones, or only the temporal
(`t.*`) ones; the ribbon's **Modules › Catalogue** menu sets the same filter and brings the
panel to its module step.
Not every module reads one raster and writes another, so **Run Module** has three paths:

- A **temporal, database or general** module imports a dataset or changes the project it runs
  in. It runs from the form, writing into the project and mapset chosen under **Projects and
  mapsets**, so `t.in.era5` downloads a variable straight into a mapset and `r.colors` changes a
  map there in place. A parameter that names a **space-time dataset** becomes a dropdown of that
  mapset's own datasets, the way a map parameter becomes a dropdown of its maps, so
  `t.rast.list`, `t.rast.colors`, `t.rast.univar` and 24 others run from the form. One that must
  **name what it writes** keeps its reason: `age="new"` means a new map in the user's own
  mapset, and the bridge will not invent a name it cannot promise is free.
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
forms are generated from the installation. It is false for *running* them from the panel: 252
can be run, and the rest still need a name for what they write, or several rasters at once. The 64-tool form
budget is the ABI's; the panel's form has no such budget.

### The panel: four steps, not one column

RustGIS draws a panel as one flat column of widgets: there is no section, tab or accordion, and
each tree gets up to 320 px of its own. Everything GRASS needs came to **24 widgets in one
column, four of them trees** — several screens of scrolling, with the GRASS database, the layer
and region, the terrain controls and the module catalogue interleaved.

It is four steps now, in the order the work is actually done. A **Step** dropdown at the top
sets which one is drawn, and every answer sets each widget's `visible` from it, so **at most
twelve of its 27 widgets are drawn at once**:

| Step | Holds |
|---|---|
| **1. Project & data** | the GRASS database, Projects and mapsets, Add Map, GRASS Database |
| **2. Layer & region** | the raster layer, the band sent to GRASS, the computational region, Region = Map View / Whole Layer / **from a Box**, the cell size |
| **3. Terrain** | the slope, aspect and viewshed runs, the four parameters only they take, and **Viewpoint on the Map** |
| **4. Modules** | the Catalogue filter, the module tree, Chosen module, Module parameters, Run Module |

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
database of 60 projects, over the plugin's own protocol:

| Answer | Before | After |
|---|---|---|
| Opening the panel (step 1) | 277 KB | **18 KB** |
| Opening it on the layer or terrain step | 277 KB | **1.5 KB** |
| Choosing a raster layer | 277 KB | **0.4 KB** |
| Choosing a module | 277 KB | **2.1 KB** |
| Opening the module step | 277 KB | 277 KB — the catalogue is what that step is for |

The **Catalogue** filter was a three-node tree inside a 320 px scroll area; it is a dropdown.

### Its own tab

The plugin has a **GRASS** tab rather than a group on **Plugins**, which had grown to 15 buttons
against a documented limit of 16. Seven groups, in the order the work is done, each entry with
an icon of its own:

| Group | Holds |
|---|---|
| GRASS | the panel |
| Data | GRASS Database, Add Map, Browse Mapset |
| Region | Region = Map View, Region = Whole Layer, Region = Box, Refresh Rasters |
| Terrain | Slope, Aspect, Viewshed, and menus of raster modules: Terrain, Hydrology, Filters, Surfaces, Sun |
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
| `commands` (up to 256) | the shaped slope/aspect/viewshed runs, 18 common raster modules, 7 imagery modules, the region, the database, the catalogue filters, and the three that drive the panel itself |
| `commands[].timeout` | a day for all 30 commands that run GRASS, so neither a download (`t.in.era5`) nor `r.watershed` on a large DEM is cut off at two minutes — on the command line, in Python and in scripts; the desktop app still stops a command at 120 seconds whatever the manifest says |
| a `tab` of its own, with compact columns and nested menus | the GRASS tab: GRASS, Data, Region, Terrain and Imagery (with menus by theme), Vector (nine themed menus), Modules — every entry with an icon of its own |
| a `panel`, with `tree` widgets that search and a `form` | the GRASS database, the map's rasters, the band, the module tree with its three branches, the chosen module's details, and its parameters as a form Run Module sends |
| a panel item's `visible` and `enabled` | the four steps, which draw at most twelve widgets of the 27 at a time, and Run Module disabled for a module the panel cannot drive |
| `choice` panel items | the Step dropdown and the Catalogue filter, which was a three-node tree |
| `pick` panel items | Viewpoint on the Map, where `r.viewshed` looks from, and Region from a Box, which draws the computational region |
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
  --cmd 'plugin:grass-vector/raster-slope={}'
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
| Open the panel | The **workspaces** are listed first (below), then projects and mapsets are read from the file system — a project is a folder with a PERMANENT mapset, a mapset one with a `WIND` file. 51 projects, 35,241 maps, in 0.03 s |
| Choose a mapset | Its imagery groups are listed first, then its maps: `cellhd` entries are rasters, `vector` folders are vectors. They load only then, because 35,000 maps do not fit a tree that takes 5,000 nodes |
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
never listed, because that is where a database's 35,000 maps are. Walking into them took **6.5 s**;
pruning them takes **0.27 s** for the same 26 workspaces, so the scan runs on each panel open
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
- **It does not replace the project.** `project.new` carries RustGIS's `Replaces` effect, which
  is reserved: a plugin may not replace someone's project, by design. What the plugin may do is
  clear the layers, which is what it does, and the messages say the project's own name and file
  are untouched rather than implying a new one. A project with **unsaved changes stops the load**
  entirely, unless `{"discard": true}` says otherwise.

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
