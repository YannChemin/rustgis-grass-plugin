# GRASS GIS vector tools for RustGIS

A [RustGIS](https://github.com/opengeos/RustGIS) **process plugin** that runs GRASS GIS vector
modules as geoprocessing tools. It is a working prototype for
[opengeos/RustGIS#1249](https://github.com/opengeos/RustGIS/issues/1249), which proposes the same
bridge as a crate in the RustGIS tree.

![The five GRASS tools as a group on the RustGIS Plugins ribbon tab](plugin_grassgis.png)

GRASS is not bundled, linked or copied here. Each run spawns the `grass` launcher already
installed on the machine, and every tool's form is read from that installation at build time with
`<module> --interface-description`. Nothing of GRASS — code, help text or module descriptions —
lives in this repository, which is why a GPL-2.0-or-later program can be driven from an
Apache-2.0 GIS this way.

## What it offers

Five vector modules RustGIS has no equivalent for, generated from GRASS's own metadata:

| Tool | Module |
|---|---|
| Voronoi Polygons | `v.voronoi` |
| Delaunay Triangulation | `v.delaunay` |
| Point Clusters | `v.cluster` |
| Generalize | `v.generalize` |
| Points Along Lines | `v.to.points` |

## Install

Needs GRASS GIS 8 and Python 3 on the machine. `RUSTGIS_GRASS` names the launcher if it is not
on the `PATH`.

```sh
python3 generate_manifest.py                      # read the forms from your GRASS
rustgis-cli plugins install ./rustgis-grass-plugin
rustgis-cli run --sample \
  --cmd 'gp.run={"tool":"plugin:grass-vector/v-voronoi","params":{"input":"Cities"}}'
```

In the desktop app: **Plugin Manager › Settings › Add Plugin Folder…**, then the tools appear in
the Tools pane under **Plugins ›**. A process plugin is **not sandboxed**: it runs programs as
you do, which is how it can reach GRASS at all.

`plugin.json` and `modules.json` are **not committed**: they carry GRASS's own parameter labels,
which are part of its GPL documentation. They are generated from your installation by
`generate_manifest.py`, which is also why that step comes before installing the plugin.

## How a run works

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

## Why vector only

RustGIS's plugin ABI gives a tool `layer`, `vectorLayer`, `polygonLayer`, `pointLayer`, `field`,
`numericField`, `number`, `text`, `choice`, `bool` and `file` parameters, and lets it return
GeoJSON layers, tables, a selection and messages. There is **no raster layer** either way, and a
tool "can log, but makes no host requests", so it cannot ask RustGIS to add a raster from a file.

That rules out `r.*`, `r3.*` and most of `i.*` — the larger half of GRASS's value. A plugin
*command* may call any RustGIS command, so a raster result could be added with `layer.addData`,
but commands are stopped after two minutes, which a real `r.watershed` will exceed. Raster
support is the main reason the bridge belongs in a crate, where `OutputLayer::Raster` exists.
`generate_manifest.py` prints what it had to leave out of each module, and the mapper refuses
every raster parameter rather than offering one that cannot work.

## Watch out

- **The region is not optional.** A freshly created GRASS project has a region of one cell at the
  origin. Run `v.voronoi` without setting it and GRASS says `Found 0 points/centroids`; a raster
  module would quietly write a single cell. Step 3 above exists because of that.
- A run costs about ten seconds of project creation, import and export even for a dozen points,
  because each module call builds its own database. A session-scoped mapset would amortise it.
- Several input maps, raster inputs and 3D data are not offered.
- `v.generalize` has one parameter too many for a plugin tool's limit of 32; the generator keeps
  the required ones and says which it dropped.

## Tests

```sh
python3 -m pytest -q tests
```

The mapping tests use XML written for the tests, so they need no GRASS. Two integration tests run
real modules and skip themselves when GRASS is not installed.

## Licence

Released into the public domain (The Unlicense). GRASS GIS itself is GPL-2.0-or-later and is
neither included nor modified here.
