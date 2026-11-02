# RustGIS as a front end for GRASS GIS — what is available today

_Written 2026-10-31 against RustGIS v0.4.0 (`main`, 92ef1db). A survey of the existing
extension points and an assessment, not a plan or an accepted proposal._

_Partly superseded by what the prototype in this repository then measured: a plugin command
can carry a raster in and out (`share.exportRaster` and `layer.addData`), bounded by the
two-minute cap on commands rather than by the ABI, and the computational region turned out to
drop features silently rather than only misalign them. See the README and
[opengeos/RustGIS#1249](https://github.com/opengeos/RustGIS/issues/1249)._

_Re-checked 2026-11-02 against RustGIS v0.5.0. What changed under the points below: a process
plugin's tool **does** have a progress channel — it runs in the background with a Cancel button
and sends `{"progress": …}` lines, so point 5 of section 5 is answered for tools (a command
still has none, and still stops after two minutes); `raster.info` now answers the coordinate
system, cell size, bands and whether the layer is georeferenced at all, which is how point 3's
CRS-less-project gotcha is caught before a run; and the ABI has gained `file` tool parameters,
`tables` in a tool's result, panel trees, nested ribbon menus, plugin skills for the AI
Assistant and `minRustgisVersion` — all of which the prototype now uses (see the README's
"What of RustGIS it uses"). Points 1, 2, 4 and 6 stand: there is still no session-scoped
mapset, no region parameter of RustGIS's own, no voxel layer, and no answer to the volume of
modules beyond a curated subset plus the panel's tree._

**Short answer: yes, and the hole is already the right shape.** RustGIS has a public, documented
extension point for exactly this — an out-of-process tool suite whose tool forms are read from the
program itself at startup (`rustgis_analysis::register_external`). The GeoLibre/Whitebox bridge
(`crates/geolibre`, 1,485 lines) is a working instance of it. A `crates/grass` written the same way
would put GRASS's module library into RustGIS's tool list, its ribbon, its command line, its Python
package and its MCP server without touching a line of GPL code and without linking anything.

---

## 1. What RustGIS is, in the terms that matter here

| Fact | Where |
|---|---|
| ~345,000 lines of Rust across 474 files, 12 crates, 4 apps | `crates/`, `apps/` |
| 526 engine commands (`CommandSpec`), everything the UI does is one of them | `crates/engine/src/cmd/*.rs` |
| 37 built-in geoprocessing tools (`ToolSpec`), run through `gp.run` | `crates/analysis/src/tools.rs` |
| Desktop (egui), browser (wasm32), CLI, Python (PyO3/maturin) — one command set | `apps/` |
| MCP server (stdio and HTTP), file bridge, relay into the running desktop app | `docs/mcp.md` |
| Licence Apache-2.0; `unsafe_code = "forbid"`; no `unwrap`/`panic` in non-test code | `Cargo.toml`, `AGENTS.md` |
| Already runs other programs as subprocesses: `ogr2ogr`/`ogrinfo`, DuckDB, `geolibre` | `crates/data/src/source/external.rs`, `crates/geolibre/src/runner.rs` |

Data it can hand to GRASS and read back natively, with no GDAL needed: GeoJSON, CSV, Shapefile,
KML/KMZ, GPX, GML, MapInfo MIF, OSM PBF, TopoJSON, DXF, GeoPackage, GeoParquet, FlatGeobuf,
LAS/LAZ, GeoTIFF/COG (read **and** write), ASCII grid, Zarr 2/3, PostGIS and MySQL, plus EPSG
reprojection (`crates/data/src/raster/crs.rs`, WKT2 and Esri datum corpora included).

## 2. The extension point

`crates/analysis/src/lib.rs:216`:

```rust
pub fn register_external(key: &'static str, provider: ExternalProvider, runner: ExternalRunner);
pub type ExternalProvider = fn() -> Vec<ToolSpec>;              // the tool list, loaded lazily
pub type ExternalRunner   = fn(&ToolSpec, &dyn Inputs, &Value) -> Result<ToolResult, String>;
```

A suite registers once (`register()`), its tool list is built on first use and cached, and
`reload_external_of(key)` invalidates it when the user installs or relocates the program. Each
`ToolSpec` carries `id`, `name`, `toolbox` (a `"GRASS › Raster › Terrain"` string is enough to get
its own tree in the Geoprocessing pane), `summary` and typed `ParamSpec`s:
`RasterLayer`, `VectorLayer`, `PointLayer`, `PolygonLayer`, `Field`, `NumericField`, `Number`,
`Text`, `Choice(&[…])`, multi-raster lists. That typed form is what the UI builds the tool dialog
from, what the CLI validates, and what the MCP server advertises to an agent. Outputs come back as
`Output::Layer`, `Layers(Vec<OutputLayer>)` (several vectors and rasters from one run — GRASS modules
routinely produce more than one), `Table`, `Update`, `Selection` or `File`.

So the whole integration is: *produce `Vec<ToolSpec>` from GRASS's own metadata, and implement one
`run` function.*

## 3. The pattern to copy, step by step

`crates/geolibre` does this in 1,485 lines including tests. The GRASS equivalent maps one-to-one:

| GeoLibre bridge | GRASS equivalent |
|---|---|
| Find the `geolibre` program: `$RUSTGIS_GEOLIBRE`, then install dir, then `PATH` (`runner.rs`) | Find `grass`: `$RUSTGIS_GRASS`, then `PATH`, then `/usr/local/grass*/bin`, `/usr/lib/grass*` |
| `geolibre manifests` → JSON array of tool forms | `grass --tmp-project XY --exec <module> --interface-description` → the module's XML; or one pass over `$GISBASE/bin` + `$GISBASE/scripts` + `~/.grass8/addons/bin` |
| `specs()` maps each manifest to a `ToolSpec`, prefixing ids with `geolibre:` (`lib.rs:177`) | Same, prefix `grass:`; XML `<parameter>` → `ParamSpec`, `gisprompt` `raster`/`vector`/`cell` → `RasterLayer`/`VectorLayer`, `<flag>` → `Choice`/switch, `<values>` → `Choice`, `multiple="yes"` → the list kinds |
| `native::run`: fresh scratch dir, stage inputs, run, collect files that weren't inputs, delete the dir (`native.rs`) | Same, with `grass --tmp-project <georef-or-EPSG> --exec` wrapping the module — or a session-scoped mapset, see §5 |
| Vectors staged as GeoJSON in a metric CRS; rasters passed by path | Identical; GRASS imports them with `v.in.ogr`/`r.in.gdal` and exports with `v.out.ogr`/`r.out.gdal` |
| `output_within` with a timeout, both pipes drained on threads, child killed and reaped | Reusable verbatim; `external.rs::output_with_budget` even monitors scratch size |
| Browser: geolibre-rust's WASI runner, `external_start` → `Services::geolibre_run` → `gp.finish` | **Not available.** GRASS is native C with no official WebAssembly/WASI build; the bridge is desktop- and CLI-only, `#[cfg(not(target_arch = "wasm32"))]`, like the GDAL and database providers already are |
| `gp.geolibre`, `gp.installGeolibre`, `gp.setGeolibre` commands (`cmd/gp.rs`) | `gp.grass` (status: found?, version, GISBASE, module count), `gp.setGrass` (Locate…); **no** `gp.installGrass` — GRASS is a system install, not a 19 MB download |

What falls out for free once the specs exist: the tool dialogs, the Geoprocessing pane tree, command
search, the geoprocessing history and `Ran` records, `gp.run` from scripts, `rustgis-cli run --cmd
'gp.run={"tool":"grass:r.slope.aspect",…}'`, `rustgis.Session.run_tool("grass:r.watershed", …)` in
Python, and an MCP agent that can call GRASS modules by name with validated parameters. That last
one is the interesting part: it is a usable, non-hallucinating agent interface to GRASS, built out of
GRASS's own parser metadata.

## 4. Licence: the one hard constraint, and it is satisfiable

GRASS is GPL-2.0-or-later; RustGIS is Apache-2.0 and `AGENTS.md`/`CONTRIBUTING.md:70` forbid copying
or translating copyleft code into the tree. The out-of-process design is what keeps this clean, and
it is the same posture RustGIS already takes with GDAL ("Nothing links to GDAL",
`crates/data/src/source/gdal.rs:6`). Rules for a GRASS bridge:

- **Spawn `grass`, never link `libgrass_*`.** Linking is where the GPL argument bites.
- **Do not vendor GRASS's module descriptions, help text or `.md`/`.html` manuals** into the repo.
  Read `--interface-description` at runtime, from the user's own installation, and show its strings
  as data. A committed table of 500 module forms would be copying GPL documentation; a runtime query
  is not.
- No GRASS binary in RustGIS's installers or packaging. "Optional extra that adds tools, not a
  requirement" is already the stated project line (`ROADMAP.md` › Goals).
- `ATTRIBUTION.md` gets no asset row (no files copied), but the docs page should name GRASS, its
  licence and where to install it, as `docs/comparison/geolibre.md` does for its suite.

## 5. Where it gets genuinely harder than GeoLibre

These are design decisions, not blockers, but they are real and a GeoLibre-shaped bridge does not
answer them:

1. **GRASS is stateful; RustGIS's tool contract is not.** A `ToolSpec::run` is files in, files out.
   GRASS wants a GISDBASE, a project (CRS-bearing), a mapset, and a computational region. Options:
   - *Per-run throwaway*: `grass --tmp-project <first raster's georeferenced file> --exec`. Honest,
     stateless, matches the contract — and pays an import/export round trip on **every** module call.
     Fine for `r.slope.aspect` on one raster, terrible for a ten-module workflow.
   - *Session-scoped mapset*: one GISDBASE under the app's cache folder per RustGIS session, layers
     imported once and cached by content hash, modules chaining inside GRASS, results exported only
     when a tool declares an output. Much faster, and the only way `r.watershed` → `r.water.outlet`
     → `v.to.db` is bearable. Costs a cache-invalidation story and a visible "GRASS workspace" the
     user can clear.
   - Recommendation: build the per-run form first (it is the GeoLibre bridge with a different
     program), then add the session mapset behind the same tool ids.
2. **The computational region has no equivalent in RustGIS.** Every GRASS raster module's output
   extent and resolution come from `g.region`, not from the inputs. Silently defaulting it would
   break the project's **Never silent** rule: the bridge must either expose `region=` as a parameter
   on raster tools or emit a notice through `ToolResult::messages` stating the region it used
   ("region set from <Elevation>: 1201×1201 at 30 m"). This is the single most likely source of
   quietly wrong results.
3. **Project CRS.** A GRASS project is single-CRS. RustGIS layers are reprojected to WGS 84 for
   display but keep source coordinates. The bridge must pick the GRASS project's CRS (first raster
   input's, else a UTM zone from the data — the rule `crates/geolibre/src/lib.rs` already uses for
   metric staging) and *say so*. Note the gotcha already recorded in the user's own notes:
   `grass -c <file>` trusts GDAL's geotransform and will silently create a CRS-less, zero-region
   project for files georeferenced by lookup table (EMIT L2A NetCDF). Verify with `g.proj -p` /
   `g.region -p` after creation and fail loudly, per rule 7 of the GRASS addon conventions.
4. **No voxel model in RustGIS.** GRASS 3D rasters (`r3.*`) have no `OutputLayer` variant. A 3D
   result can only come back as 2D slices, or as a point table via `r3.what` — which is also the
   fast path (sub-second for ~1,000 points × 408 bands, versus ~51 min for an equivalent
   `r3.to.rast` extraction). Hyperspectral cube work therefore stays a partial fit until RustGIS
   grows a cube layer type; `crates/engine/src/cmd/cube.rs` is time-series, not voxels.
5. **Progress.** GRASS modules report `G_percent()`. `ToolSpec::run` is synchronous with no progress
   channel, so a long `r.sim.water` is a frozen dialog. The browser path already has an async
   shape (`external_start` → `gp.finish`); a native long-run equivalent would need proposing.
6. **Volume.** ~500 core modules plus ~400 addons, auto-generated into the tool tree, would dwarf the
   37 built-ins and the 1,000-tool GeoLibre suite put together. Expect to need a curated default
   subset plus "show all", and `toolbox` strings built from GRASS's own module prefixes
   (`r.` → Raster, `v.` → Vector, `i.` → Imagery, `r3.` → Volume, `t.` → Temporal, `db.`, `g.`, `m.`).

## 6. Things deliberately *not* worth doing

- **A plugin instead of a crate.** `.rgplugin` WebAssembly modules are sandboxed (`wasmi`, no files,
  no network, no subprocesses), so they cannot reach GRASS. A *process* plugin
  (`"runtime": "process"`, `crates/plugins/src/process.rs`) could — it is unsandboxed and speaks the
  same request protocol over stdio — and that is a reasonable way to prototype this **outside** the
  RustGIS tree, with no upstream coordination needed. It cannot ship in the browser build either.
- **GRASS as a data provider** (reading a mapset's rasters/vectors directly as RustGIS layers). Both
  plausible and useful, but the native formats are undocumented-ish and version-bound; going through
  `r.out.gdal`/`v.out.ogr` into GeoTIFF/GeoPackage, which RustGIS reads natively, costs a copy and
  nothing else.
- **Replacing the GRASS GUI.** RustGIS's editing, cartography, layouts and labelling are far ahead of
  wxGUI, but RustGIS has no equivalent of the GRASS command console, module history, or the
  region/mapset model that experienced GRASS users work in. A bridge adds GRASS's *analysis* to a
  modern front end; it does not replace GRASS's *workflow*.

## 7. Assessment

**As a new interface to GRASS GIS: viable, and better-suited than it looks from outside.** The
decisive facts are that (a) the external-suite extension point exists, is public, and is already
exercised by a shipping bridge to a 1,000-tool program; (b) RustGIS reads and writes GeoTIFF,
GeoPackage and GeoJSON natively, so the exchange format question is answered; (c) the subprocess
plumbing — program discovery, timeouts, pipe draining, scratch folders, size budgets — is written and
tested; and (d) GRASS publishes machine-readable parameter metadata for every module, which is
exactly the shape `ToolSpec` wants, so the tool list needs no hand-maintained table and no GPL text
in the repo.

What makes it more than another tool bridge is the four front ends behind one command set. The same
`grass:r.watershed` registration yields a desktop dialog, a CLI invocation, a Python call and an MCP
tool an LLM can call with validated parameters — a credible answer to "give GRASS a scriptable,
agent-addressable, non-GPL front end", which neither wxGUI nor the QGIS GRASS provider offers.

The honest caveats are the region model (§5.2) and statefulness (§5.1): get those wrong and the
bridge produces plausible, silently misaligned rasters, which is precisely the failure mode both
projects say they refuse. Everything else is work, not risk.

**Suggested first slice**, if this is pursued: `crates/grass` registering a hand-picked ~20 modules
(`r.slope.aspect`, `r.watershed`, `r.viewshed`, `r.cost`, `r.sun`, `v.net.*`, `r.univar`,
`i.pca`, `i.segment`…), per-run `--tmp-project`, explicit `region=` parameter, a notice on every
run naming the CRS and region used, and `gp.grass` / `gp.setGrass`. If that holds up, generate the
full list from `--interface-description` and add the session mapset.

---

### Pointers
- Extension point: `crates/analysis/src/lib.rs:185-299` (`ToolSpec`, `register_external`).
- Reference bridge: `crates/geolibre/src/{lib,runner,native,install}.rs`.
- Subprocess helpers worth reusing: `crates/data/src/source/external.rs`.
- Suite commands to mirror: `crates/engine/src/cmd/gp.rs:26-52`.
- Project rules this must satisfy: `AGENTS.md` (Never crash, Never silent, Never break wasm,
  code origin), `CONTRIBUTING.md:70`.
- Agent interface it would feed: `docs/mcp.md`.
