---
name: grass
description: Use when the user asks for GRASS GIS work in RustGIS - running a GRASS module (v.*, r.*) on a layer, picking the right GRASS tool or raster command of the GRASS GIS Tools plugin, setting the computational region, or bringing a map out of their GRASS database. Says which requests GRASS is needed for at all and which RustGIS already does itself.
---

# GRASS GIS in RustGIS

The **GRASS GIS Tools** plugin (`grass-vector`) runs the user's own GRASS installation
as a process plugin. Nothing of GRASS ships with it, so every answer depends on what
is installed: the panel's **Last run** text says the version it found, and
`modules.json` beside the plugin lists the modules this manifest was built from.

## The panel is four steps, in the order the work is done

The **GRASS GIS** panel shows one step at a time, chosen by the **Step** dropdown at
its top, because GRASS needs them in this order:

| Step | What it holds |
|---|---|
| `data` | the GRASS database tree, **Add Map**, **GRASS Database** |
| `layer` | the raster layer, its band, the computational region and the cell size |
| `terrain` | the slope, aspect and viewshed runs and their own parameters |
| `modules` | the **Catalogue** filter, the module tree, **Chosen module**, the form, **Run Module** |

The chosen layer, the region and **Last run** stay visible in the steps that act on
them, so a run never hides what it is about to use. A command sets the step only when
its whole result lives in another one (`data-browse`, and the three catalogue
filters); everything else reports through **Last run** where the user already is.

A script sets the step like any other panel value. It **has to** before naming a
module: a tree keeps a value only when that value was among the nodes last sent, and
the module tree is sent only by the module step. Without it RustGIS answers *1
value(s) not taken … modules*.

```
plugin:grass-vector/panel-step={"panel": {"step": "modules"}}
plugin:grass-vector/module-pick={"panel": {"modules": "runs/r.slope.aspect"}}
```

Every command still works with the panel closed.

## Reach for GRASS only when RustGIS has no answer

RustGIS does buffers, clips, overlays, dissolves, spatial joins, zonal statistics,
interpolation (IDW, kriging), viewsheds, lines of sight, slope, aspect and hillshade
itself, as built-in tools and commands. Those are faster, run in the browser too, and
need nothing installed. Use GRASS for work RustGIS has no equivalent for: topological
cleaning (`v.clean`), Voronoi and Delaunay (`v.voronoi`, `v.delaunay`), network
analysis (`v.net.*`), linear referencing (`v.lrs.*`), LiDAR filtering (`v.lidar.*`,
`v.decimate`), regularised spline surfaces (`v.surf.rst`), watershed and stream
extraction (`r.watershed`, `r.stream.extract`), geomorphons, solar radiation
(`r.sun`), and whatever else the user names by module.

## Vector modules are geoprocessing tools

Run one through `gp.run`:

```
gp.run {"tool": "plugin:grass-vector/v-clean", "params": {"input": "Parcels", "tool": "break,rmdupl"}}
```

- The tool id is the module name with dots as hyphens (`v.net.path` -> `v-net-path`).
  Only modules that read a vector **and** write one are tools, and a manifest holds 64
  of them; `modules.json`'s `toolsLeftOut` names the ones that missed the budget.
- `input` is a vector layer **on the map**; its features (or just the selected ones)
  are what the module sees.
- Every other parameter is GRASS's own, by its own name, and a flag is `flag_<letter>`
  (`-c` is `{"flag_c": true}`).
- A parameter the bridge could not offer is listed in `modules.json`'s `skipped` for
  that tool: a raster input, a 3D raster, a database table, an output name, or more
  parameters than the 32 a tool may declare. If the user needs one of those, say so
  rather than guessing at a workaround.
- A parameter that takes a file (`v.segment`'s rules, `v.extract`'s category list,
  `v.net`'s node file, `v.rectify`'s control points, `v.lrs.segment`'s rules) is a
  `file` parameter: the user picks the file in the Tools pane and RustGIS hands its
  contents over. It cannot be filled with a path in a script.
- Features arrive in longitude/latitude and are worked on in a metric projection of
  their own area (UTM, or Web Mercator for a layer spanning many degrees), then
  projected back, so distances and areas are in metres. The run messages say which
  projection was used.
- Rows the module writes without geometry (`v.distance`'s upload table, say) come back
  as a standalone **table**, not a layer, and the messages count them.

## Raster modules are commands, driven from the panel

A plugin tool is handed features, never a raster, and makes no host requests, so raster
work is done by commands instead: they ask RustGIS to export the layer, run the module
on the file and add the result back.

- The common modules have a command each: `plugin:grass-vector/r-slope-aspect`,
  `r-watershed`, `r-neighbors`, `r-sunmask`, `r-fillnulls`, and the rest of the GRASS
  tab's Raster menus. The Imagery group adds the imagery ones the panel can drive
  (`i-edge`, `i-zc`, `i-destripe`, `i-sar-speckle`, `i-water`, `i-emissivity`,
  `i-rotate`) under Enhance, Preprocess, Detect and Geometry. Three shaped commands
  take parameters from the panel instead of GRASS's defaults: `raster-slope` (degrees
  or percent), `raster-aspect` and `raster-viewshed` (height, range, earth curvature,
  and the viewpoint).
- **The viewshed looks from the place picked on the map**, the panel's **Viewpoint on
  the Map** pick, in the terrain step. Without one it falls back to the centre of the
  map, as it always did, and the run's messages say which was used and where it ended
  up in the raster's own projection. A script gives the degrees and RustGIS works out
  the rest:

```
plugin:grass-vector/raster-viewshed={"panel": {"viewpoint": {"lon": -1.55, "lat": 47.21}, "height": 30, "maxdist": 3}}
plugin:grass-vector/region-box={"panel": {"region-box": {"bbox": [-2.0, 47.0, -1.0, 48.0]}}}
```

  `region-box` sets the Analysis Environment's extent, and so the computational region,
  from a box drawn on the map. One drawn across the antimeridian is refused rather than
  turned into an extent meaning the rest of the world.
- Any other installed module is run by choosing it in the panel's module tree, filling
  or accepting its **Module parameters** form, and running `run-module`. The tree has
  three branches: **Runs from here** (the modules Run Module can drive), **All modules**
  (every installed module, with the reason the others cannot be driven) and **Recently
  run**. Any readable module shows its parameters in the form. The 88 that read one
  raster and write one run on the chosen layer; 91 temporal, database and general
  modules run with the form in the GRASS project/mapset chosen under **Projects and
  mapsets** (so `t.in.era5` imports its space-time dataset there); 25 change a map of
  that same mapset in place (`r.colors`, `v.db.update`); 19 display (`d.*`)
  modules render a picture of maps from that same chosen mapset, imported back
  as an RGB layer, with an optional PNG preview; and the rest carry the reason they cannot run. The panel's **Catalogue** dropdown keeps
  all modules (`all`), only the imagery ones (`imagery`) or only the temporal ones
  (`temporal`); `imagery-state`, `temporal-state` and `all-state` set it from the
  ribbon and move the panel to the module step. A temporal
  module whose required parameter names a space-time dataset or a raster cannot be
  given one by the form, so it keeps its reason.
  A leading triangle **▸** marks a module Run Module can
  drive; the others carry their reason, such as *needs several bands*, *needs an
  imagery group* or *needs a display*, so tell the user what the module needs instead
  of offering a run that would fail. A display module that does run writes a layer
  holding a picture, not a data map; say so rather than treating it as analysis.
- Choosing a module fills the panel's **Module parameters** form with that module's
  own parameters, read from its GRASS interface description. Text boxes, numbers,
  checkboxes for flags, selection lists for choices and multi-selection lists for
  parameters that take several values are there; a required field is marked `*`, and a
  range such as `rescale=0,255` stays a text field. Fields start at the module's
  defaults. `run-module` sends the values the form holds, and a field left empty is
  left out, so GRASS uses its own default for it. Tell the user which values were
  actually sent, rather than implying a default was chosen.
- Choosing a layer runs `layer-pick` and choosing a module runs `module-pick`: each
  answers only what it changed, so neither sends the catalogue back. **Run Module** is
  disabled for a module this panel cannot drive, and **Chosen module** says why.
- **A GRASS workspace (`.gxw`) opens as a ready-made project.** The panel's Data tree
  lists the workspaces found in the GRASS database and under the home folder *above*
  the projects, labelled by the project and mapset they open and their layer count.
  **Load Workspace** loads every raster and vector of the workspace's first map
  display, keeps a layer the workspace had unticked loaded but **not drawn**, puts the
  view in the GRASS project's coordinate system and frames the workspace's own extent.
  Tell the user two things when they ask for it: it **clears the project's layers**
  (and refuses outright if the project has unsaved changes, unless `discard` is
  passed), and it does **not** replace the project itself -- a plugin may not, so the
  project's name and file are unchanged. Reach it from a script with
  `{"workspace": "workspace/<percent-encoded path>", "discard"?: true}`; the path is
  percent-encoded because a node id is built with `/`.

- **An imagery group is offered as one composite, not as its bands.** A mapset's
  `i.group` groups are listed above its loose rasters, labelled with their band
  count. `Add Map` on a group composes it with `d.rgb` (3 bands or more, the first
  three) or `d.his` (2 bands: hue, intensity), in the **group's own band order**, and
  adds one RGB layer. A group of one band is refused, advising that the band be added
  on its own; the tree labels it `(group of 1, not a composite)`. A group of more than
  three says which bands were left out. Tell the user the result is **a picture of the
  bands, not their values** -- it is not something to run analysis on -- exactly as the
  display modules' output is. Reach it from a script with
  `{"map": "group/<project>/<mapset>/<name>"}`.

- **Add Map also sets the view's coordinate system.** RustGIS already reprojects a
  layer for display, so a GRASS map is never in the wrong place; what `Add Map` adds
  is putting the *view* in the GRASS project's own system, read from `g.proj -g`. It
  does this only when the view is still in a world projection (`globe`, `mercator`)
  or holds nothing else -- a view already in another `EPSG:` system with layers in it
  is left alone, and the message says so. Report which happened instead of implying
  the view was changed. A map from an **XY project** is refused, naming the project:
  it has no coordinate system, so nothing can place it. `Add Map` takes
  `{"map": "raster/<project>/<mapset>/<name>"}` in its own parameters, which is the
  only way to reach it from a script, since a tree's value cannot be set without
  having browsed the tree.

- **A raster run stops after two minutes unless it is told otherwise.** Every raster
  command declares a day in the manifest, but that only holds away from the desktop
  app, which stops any command at 120 seconds; the plugin cannot tell which host it is
  in, so it keeps to 120 unless the caller passes `timeout` in the command's own
  parameters. From `rustgis-cli`, a script or Python, pass it for anything heavy
  (`r.watershed` on a large DEM, `r.sun`); in the desktop app it cannot help, so narrow
  the region or the raster instead. A value outside 1 to 86,400 seconds is refused.

```
plugin:grass-vector/r-watershed={"timeout": 3600, "panel": {"raster": "3"}}
```
- The tree's node ids carry a branch prefix (`runs/`, `all/`, `recent/`);
  `run-module` strips it. A family or branch node is refused with a request to choose
  a module.
- The panel's values go with any run, so a script sets them. A tree-driven module
  takes its parameters under `form`, by the field ids the panel's form uses:

```
plugin:grass-vector/run-module={"module": "r.slope.aspect", "panel": {"raster": "3", "form": {"format": "percent", "flag_a": true}}}
plugin:grass-vector/r-watershed={"panel": {"raster": "3", "band": 1}}
```

  `run-module` takes `module` in the command's own parameters, which is the way to run
  one from a script: a tree keeps a value only when it was among the nodes last sent,
  so `{"panel": {"modules": "all/r.slope.aspect"}}` alone needs the panel to have been
  brought to its module step first.

  `raster` is the layer **id** as `host.layers` gives it, not its name. Without one,
  the active raster layer is used, or the only one if there is just one. `modules`
  carries the chosen module's id (`runs/`, `all/` or `recent/` prefix), and `form`
  holds only the fields the user changed: the rest stay at the module's defaults.
- RustGIS writes one band of a raster that is not a colour one, so the panel's **band**
  slider says which band GRASS sees. Its ends come from `raster.info`, so a cube's
  bands are all reachable; say which band a result came from.
- A raster RustGIS holds as a downsampled overview is exported as that overview, and
  the run messages say so: the result is coarser than the file on disk. Repeat that to
  the user instead of passing the result off as full resolution.
- A layer with no coordinate system is refused: GRASS would work in cells, not on the
  ground.
- A command is stopped after two minutes (RustGIS's limit for plugin commands), so a
  big raster may need the Analysis Environment's extent narrowed first. Tools have no
  such limit.

## The computational region decides everything

In GRASS the region, not the input, sets what a raster module reads and writes. The
bridge takes it from **Analyze > Geoprocessing > Environments**: `gp.env`'s extent
becomes the region's bounds (projected into the raster's own system and clipped to it,
aligned to its grid) and its cell size the resolution, with the panel's own cell size
winning over both. `region-view` sets the extent to what the map shows and
`region-full` clears it. With neither set, the whole raster is used at its own cell
size. The run messages always state the region that was used; quote it.

## Their own GRASS database

- `data-folder` puts the GISDBASE GRASS itself uses (`GISDBASE`, GRASS's settings file,
  or `~/grassdata`) into the Browser under Folders. RustGIS reads none of GRASS's own
  formats, so the folders are there to look at, not to open.
- `data-browse` lists a mapset's maps in the panel's tree; `data-add` exports the map
  chosen there (a raster as a GeoTIFF, a vector as a GeoPackage, both carrying their
  coordinate system) and adds it to the project.
- A temporal, database or general module run through the form writes into the mapset
  chosen under **Projects and mapsets**, not a throwaway one, so its dataset outlives
  the run. Choose the mapset first; without one the run says so and stops.
- Raster results are kept in `~/.cache/rustgis-grass-plugin/`, and the messages give the path.
  The last twelve modules run there are listed under the tree's **Recently run** branch.

## When something fails

The error is GRASS's own last `ERROR` line, prefixed with the module. Common ones: no
raster layer on the map, the Analysis Environment's extent not meeting the raster, the
module not being installed (an addon the manifest was built with may be gone), and the
two-minute limit. Say which it was and what to change; do not retry the same call.
