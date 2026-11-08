# GRASS GIS tools for RustGIS

A [RustGIS](https://github.com/opengeos/RustGIS) **process plugin** that runs GRASS GIS modules:
vector modules as geoprocessing tools, raster modules as commands with a panel. It is a working
prototype for
[opengeos/RustGIS#1249](https://github.com/opengeos/RustGIS/issues/1249), which proposes the same
bridge as a crate in the RustGIS tree.
[GRASS_INTERFACE.md](GRASS_INTERFACE.md) is the survey of RustGIS's extension points this was
designed from, written before the prototype and partly superseded by it.

![RustGIS with the plugin's own GRASS ribbon tab open, showing the Database, Region, Raster and
Vector groups, above the World Atlas sample map](plugin_grassgis_030.png)

Above is the plugin's own **GRASS** ribbon tab: **Database** opens the GRASS database panel and
adds a map from it, **Region** sets the computational region from the map view or a layer,
**Raster** runs slope, aspect and viewshed or the common raster modules in menus, **Imagery**
does the same for the imagery modules, **Vector** holds the generated tools, grouped by what
they do, **Temporal** opens the temporal module catalogue, and **Modules** opens the panel and
its **Run Module**.

GRASS is not bundled, linked or copied here. Each run spawns the `grass` launcher already
installed on the machine, and every tool's form is read from that installation at build time with
`<module> --interface-description`. Nothing of GRASS — code, help text or module descriptions —
lives in this repository, which is why a GPL-2.0-or-later program can be driven from an
Apache-2.0 GIS this way.

## What it offers

Everything the installation has. On this machine that is **1,182 modules**, addons included, of
which **1,177** could describe themselves:

| Family | Modules | Family | Modules |
|---|---|---|---|
| Raster (`r.*`) | 455 | General (`g.*`) | 55 |
| Vector (`v.*`) | 223 | Display (`d.*`) | 49 |
| Imagery (`i.*`) | 177 | 3D Raster (`r3.*`) | 35 |
| Temporal (`t.*`) | 74 | Database (`db.*`) | 22 |
| Planetary (`p.*`) | 67 | Miscellaneous (`m.*`) | 14 |
| Tests (`test.*`) | 4 | PostScript (`ps.*`) | 1 |

They are reached three ways, because the ABI gives three and each has a ceiling:

| Route | Covers | Ceiling |
|---|---|---|
| **Tools**, with a generated form in the Tools pane | 64 vector modules | a manifest holds **64 tools**, and a tool takes no raster, so only vector modules qualify: 128 do, half of them fit |
| **Commands** on the ribbon | Slope, Aspect, Viewshed, **18 common raster modules** and **7 imagery modules** in menus by theme, the region and the database | a manifest holds up to **256 commands**, and a command opens no dialog, so each needs the panel to be told anything |
| **Run Module**, from the panel's tree | **all 1,177** are reached and show their parameters; the **88** that read one raster and write one, **91** temporal, database and general modules whose form is all they need, **25** that change a map of the chosen mapset in place (`r.colors`, `v.db.update`), and **19** display modules that render a picture, can be run | a command has no form of its own, so the panel's **Module parameters** form sends the values it holds; the rest still need a raster, vector or dataset the form cannot name |

The tree is searchable and has three branches: **Runs from here** (the 223), **All modules**
(every module, with its reason for not running here) and **Recently run**. A **Catalogue**
tree above it keeps all modules, only the imagery (`i.*`) ones, or only the temporal (`t.*`)
ones; the **Imagery Modules** and **Temporal Modules** ribbon buttons turn those filters on.
A temporal, database or general module does not read one raster and write another: it
imports a dataset or changes the project it runs in. Those run from the form, writing into
the project and mapset chosen under **Projects and mapsets** (so `t.in.era5` can download a
variable straight into a mapset); one whose required parameter names a space-time dataset
or a raster the form cannot set keeps its reason. A display module (`d.*`) does not write a
map either: it draws a picture of maps from the GRASS mapset chosen under **Projects and
mapsets**, and the 19 that can draw without a monitor return it as an RGB raster layer,
optionally kept as a PNG preview as well. Every input of one render comes from that same
mapset, and the fields stay visible when it holds no map of a kind. The rest need a live display, ask
for a map to edit, or cannot run in this GRASS build, and keep their reason. A module Run Module can drive is marked
with **▸**; the others carry their reason, such as *needs several bands* or *needs an
imagery group*, and choosing one says what it reads and writes in the **Chosen module**
text before Run Module is pressed. The 64 modules that could have been tools but did not fit are listed in
`modules.json` under `toolsLeftOut`, as are the five that could not be read at all.

Choosing a module also fills the **Module parameters** form with that module's own parameters,
read from its GRASS interface description: text boxes, whole and fractional numbers, checkboxes
for flags, selection lists for choices, and multi-selection lists for parameters that take
several values (a climate variable set, pressure levels). A required field is marked `*`. A
parameter with a range, such as `i.pca`'s `rescale=0,255`, stays a text field, because one
number field cannot hold it. Fields start at the module's defaults; clearing a text field or a
selection leaves the parameter out, so GRASS uses its own default. Changing the chosen module
keeps the values of fields with the same name and starts the new ones at their defaults.

So "every GRASS module" is true for *reaching* them and for *showing their parameters*: 1,177
forms are generated from the installation. It is false for *running* them from the panel: the
88 raster ones run on the chosen layer, 91 temporal, database and general ones run with their
form in a chosen mapset, 25 change a map of that mapset in place, 19 display ones render to a layer, and the rest still need inputs or
outputs a command cannot supply.
The 64-tool form budget is the ABI's; the panel's form has no such budget.

### Its own tab

The plugin has a **GRASS** tab rather than a group on **Plugins**, which had grown to 15 buttons
against a documented limit of 16:

| Group | Holds |
|---|---|
| Database | the panel, GRASS Database, Add Map, Browse Mapset |
| Region | Region = Map View, Region = Whole Layer, Refresh Rasters |
| Raster | Slope, Aspect, Viewshed, and menus of raster modules: Terrain, Hydrology, Filters, Surfaces, Sun |
| Imagery | the panel, Imagery Modules, and menus of imagery modules: Enhance, Preprocess, Detect, Geometry |
| Vector | the 64 tools, in menus by GRASS keyword (Proximity, Geometry, Network, LIDAR…) |
| Temporal | the panel and Temporal Modules, which filters the catalogue to the temporal (`t.*`) modules |
| Modules | the panel, All Modules, and Run Module |

### What of RustGIS it uses

Everything the plugin ABI offers that a GRASS bridge can make use of, as of RustGIS 0.5.0:

| RustGIS gives | The plugin uses it for |
|---|---|
| `tools` with a generated form | 64 vector modules, with their GRASS parameters, flags and choices |
| `file` tool parameters | the rules, node and control-point files of `v.segment`, `v.net`, `v.extract`, `v.rectify`, `v.lrs.segment` |
| `tables` beside `layers` in a tool's result | rows a module writes without geometry |
| `commands` (up to 256) | the shaped slope/aspect/viewshed runs, 18 common raster modules, 7 imagery modules, the region, the database and the catalogue-mode buttons |
| a `tab` of its own, with compact columns and nested menus | the GRASS tab: Database, Region, Raster and Imagery (with menus by theme), Vector (menus by GRASS keyword), Temporal, Modules |
| a `panel`, with `tree` widgets that search and a `form` | the GRASS database, the map's rasters, the band, the catalogue mode, the module tree with its three branches, the chosen module's details, and its parameters as a form Run Module sends |
| `raster.info` | refusing a raster with no coordinate system, describing the source, and sizing the band slider |
| `share.exportRaster`'s answer | saying when a run was made on a downsampled overview |
| `gp.env` | the computational region |
| `progress` messages | what a run is doing now, in the Tools pane |
| `skills` | a skill telling the AI Assistant when GRASS is needed and how these tools are addressed |
| `i18n` | the plugin's own interface text in French (GRASS's own text comes from the installation) |
| `minRustgisVersion` | 0.5.0, so an older RustGIS says why rather than loading half of it |

What it still cannot use: a raster or 3D raster as a **tool** parameter (there is none), several
input layers at once, a module's output file, a database table, and more than 64 tools or 32
parameters per tool.

## Install

From the package, on Debian or Ubuntu:

```sh
sudo apt install ./dist/rustgis-grass-plugin_0.10.0_all.deb
rustgis-grass-setup          # once per user; again after upgrading GRASS
```

`rustgis-grass-setup` generates the manifest from the GRASS installed here and registers the
plugin with RustGIS. The package carries no manifest, because a module's parameter labels are
part of GRASS's own GPL documentation; `rustgis-grass-setup --remove` undoes both steps.

### From the source tree

Needs GRASS GIS 8 and Python 3 on the machine. `RUSTGIS_GRASS` names the launcher if it is not
on the `PATH`.

```sh
python3 generate_manifest.py                      # read the forms from your GRASS
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

### The GRASS database

The panel's **Projects and mapsets** tree is the database GRASS itself uses, found the way GRASS
finds it: `GISDBASE` when set, otherwise the `GISDBASE:` line of `~/.grass8/rc`, otherwise
`~/grassdata`. Nothing here writes down a path.

| Step | What happens |
|---|---|
| Open the panel | Projects and mapsets are read from the file system — a project is a folder with a PERMANENT mapset, a mapset one with a `WIND` file. 51 projects, 35,241 maps, in 0.03 s |
| Choose a mapset | Its maps are listed: `cellhd` entries are rasters, `vector` folders are vectors. They load only then, because 35,000 maps do not fit a tree that takes 5,000 nodes |
| Choose a map, then **Add Map** | It is exported and added to the project: a raster as a GeoTIFF, a vector as a GeoPackage, both of which carry the coordinate system |
| Choose a mapset, then **Run Module** | A temporal, database or general module runs in that mapset, so what it writes outlives the run: `t.in.era5` imports its space-time dataset there |
| **GRASS Database** | Puts the database folder in the browser's **Folders** (`project.addFolder`) |

The status bar reports each one — *GRASS GIS Tools: forest_ndvi@PERMANENT added from IGN.*

Exporting runs in a **throwaway mapset of that project** (`grass --tmp-mapset`), reading the map
across mapsets as `name@mapset`. Nothing of the user's is written to, their own mapsets are never
locked, and a GRASS session they have open elsewhere is undisturbed. A **Run Module** for a
temporal, database or general module is the exception: it runs in the chosen mapset, because
the dataset it makes is meant to stay there.

Two things the host decides, not the plugin:

- **A plugin cannot add an entry to the Add Data menu or to Data Sources.** Those are RustGIS's
  own, and a plugin declares commands, tools, a tab and a panel — nothing else. `project.addFolder`
  puts the database in the browser, but a mapset's own files are GRASS's formats, which RustGIS
  has no reader for, so the folder is a signpost and **Add Map** is the way in. A data provider
  reading mapsets directly would have to live in the RustGIS tree.
- A GeoPackage written by GRASS from a project with a custom coordinate system comes back with
  `srs_id 100000` and no EPSG code, and RustGIS says so when it reads it as longitude/latitude.
  That notice is RustGIS's, and it is right to make it.

### The computational region

A GRASS raster module takes its extent and resolution from `g.region`, not from its inputs, so
that is what RustGIS's own **Analysis Environment** sets. Every run reads `gp.env` and applies it:

| In RustGIS | In GRASS |
|---|---|
| **Environments › Extent** (`view`, `full`, a layer, or four numbers) | `g.region n= s= e= w= align=src`, clipped to the raster and snapped to its grid |
| **Environments › Cell Size** (degrees) | `g.region nsres= ewres= -a`, converted to the raster's units at the region's latitude |
| The panel's **Cell size** slider (the raster's own units, 0 = off) | `g.region res= -a`, overriding the environment |

The panel's **Region = Map View** and **Region = Whole Layer** buttons set the environment's
extent to the view or clear it, so the region can be driven without leaving the panel, and the
panel shows the region in force. A degree of longitude shortens away from the equator, so a cell
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

### The two-minute cap

RustGIS stops a plugin command after two minutes. The run therefore carries its own deadline and
gives up with a readable reason instead of being killed with a half-written file behind it.
Measured here, `r.slope.aspect` end to end, project creation, export and import included:

| Raster | Wall time |
|---|---|
| 500 × 500 (250,000 cells) | 3.1 s |
| 4,000 × 4,000 (16,000,000 cells) | 9.5 s |

So the cap is generous for a per-cell module and useless for `r.watershed` on a national DEM.
That ceiling, not the ABI, is now the reason raster work belongs in a crate rather than a plugin.
`generate_manifest.py` prints what it had to leave out of each **tool**, and the mapper refuses
what RustGIS would not take rather than offering something that cannot work: a raster parameter,
a name with a digit in it (`v.gsflow.segments` has `width1`), a name the module declares twice
(the same module declares four of them twice over), and a file the module writes although it
declares it as one it reads (`v.rectify`'s `rmsfile`), since a file picker cannot name a file
that does not exist yet. Reading all 1,182 forms takes about three and
a half minutes, 24 at a time.

## Watch out

- **The region is not optional.** A freshly created GRASS project has a region of one cell at the
  origin. Run `v.voronoi` without setting it and GRASS says `Found 0 points/centroids`; a raster
  module would quietly write a single cell. Step 3 above exists because of that.
- A run costs about ten seconds of project creation, import and export even for a dozen points,
  because each module call builds its own database. A session-scoped mapset would amortise it.
- Several input maps, 3D (`r3.*`) data, imagery groups and the modules that take a base name and
  read the bands beside it are not run by Run Module; a raster reaches a command, never a tool.
  Their parameters still appear in the form, but a run would need a different bridge.
- A raster that RustGIS holds as an overview is exported as that overview, and a raster that is
  not a colour one is exported one band at a time. Both are reported in the run's messages, so
  read them before taking a result for the whole file at full resolution.
- A tree widget only keeps a value that was among the nodes the plugin last sent, so a script
  passing `{"panel": {"raster": "3"}}` must run `raster-state` first, as the panel does when it
  opens. The module tree's ids carry a branch prefix (`runs/`, `all/`, `recent/`), which
  `run-module` strips; a family or branch node is refused with a request to choose a module.
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
