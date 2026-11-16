"""Build plugin.json from GRASS's own parameter metadata.

Run this when the module list changes, or against another GRASS installation.
Nothing of GRASS is copied into the repository: the forms are read from the
installation each time this runs, and the file it writes is the plugin's own
manifest.

SPDX-License-Identifier: Unlicense
"""

import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys
import time

from grass_bridge import interface, panel, session

HERE = pathlib.Path(__file__).parent

#: A manifest takes at most this many tools, so only this many modules can
#: have a tool form of their own. Every other module is reached from the
#: panel's tree, which holds them all, and the panel's form shows its
#: parameters.
MAX_TOOLS = 64

#: Modules that get a tool first, whatever else is installed: the work RustGIS
#: has no equivalent for. The rest of the budget is filled in the order GRASS
#: lists them, so the same installation always gives the same manifest.
PREFERRED = [
    "v.voronoi",
    "v.delaunay",
    "v.cluster",
    "v.generalize",
    "v.to.points",
    "v.clean",
    "v.overlay",
    "v.select",
    "v.patch",
    "v.dissolve",
    "v.hull",
    "v.net",
    "v.net.alloc",
    "v.net.distance",
    "v.net.path",
    "v.net.salesman",
    "v.net.steiner",
    "v.segment",
    "v.split",
    "v.parallel",
    "v.perturb",
    "v.random",
    "v.extract",
    "v.type",
    "v.transform",
    "v.proj",
    "v.surf.rst",
    "v.outlier",
    "v.decimate",
    "v.lidar.edgedetection",
    "v.kernel",
    "v.distance",
    "v.sample",
    "v.clip",
    "v.category",
    "v.rectify",
    "v.build.polylines",
    "v.centroids",
]

#: Where GRASS keeps its own modules, and where a user's addons go.
ADDON_DIR = "~/.grass8/addons/bin"

#: The first RustGIS that has everything this manifest uses. The panel's
#: `form`, its `choice` dropdowns, its `pick`s and a command's own `timeout`
#: all came after 0.5.0; a panel item kind an older RustGIS does not know is a
#: hard manifest error ("panel item kind 'form' isn't text, checkbox, slider,
#: button, tree"), so a 0.5.0 floor had the whole plugin refused rather than
#: loaded with a widget missing. Better to be refused with a reason.
MIN_RUSTGIS = "0.6.0"

#: The most bands the panel's band slider reaches before raster.info narrows
#: it to the chosen raster: enough for a hyperspectral cube.
MAX_BANDS = 512

#: Skills the package carries for the AI Assistant, as skills/<name>/SKILL.md.
SKILLS = ["grass"]

#: Raster modules that get a command of their own, by the ribbon menu they go
#: in. A manifest holds 256 commands, so the common work of each family is on
#: the ribbon instead of only in the panel's tree; anything else is still
#: reached by choosing it there and pressing Run Module. Each runs with
#: GRASS's own defaults over the chosen layer, which is all a command (no
#: form) can do, and only the modules the installation actually has become
#: commands.
#: The ribbon icon each curated menu's commands carry, so a column of small
#: controls is read by its glyphs rather than by its labels alone.
MENU_ICONS = {
    "Terrain": "relief",
    "Hydrology": "measure_area",
    "Filters": "resample",
    "Surfaces": "graduated",
    "Sun": "brightness",
    "Enhance": "contrast",
    "Preprocess": "stretch",
    "Detect": "classify",
    "Geometry": "identity",
}

RASTER_COMMANDS = {
    "Terrain": [
        "r.slope.aspect",
        "r.relief",
        "r.param.scale",
        "r.geomorphon",
        "r.skyview",
        "r.local.relief",
    ],
    "Hydrology": [
        "r.watershed",
        "r.fill.dir",
        "r.flow",
        "r.stream.extract",
        "r.terraflow",
        "r.topidx",
    ],
    "Filters": [
        "r.neighbors",
        "r.mfilter",
        "r.resamp.interp",
        "r.resamp.stats",
        "r.resamp.filter",
        "r.denoise",
    ],
    "Surfaces": [
        "r.fillnulls",
        "r.grow.distance",
        "r.buffer",
        "r.thin",
        "r.clump",
        "r.texture",
    ],
    "Sun": ["r.sun", "r.sunmask", "r.horizon", "r.sunhours"],
}

#: Imagery modules that get a command of their own, by the ribbon menu they go
#: in. These are the i.* modules the panel can actually drive from one raster;
#: the rest need an imagery group or several bands and keep their reason in the
#: panel's tree.
IMAGERY_COMMANDS = {
    "Enhance": ["i.edge", "i.zc"],
    "Preprocess": ["i.destripe", "i.sar.speckle"],
    "Detect": ["i.water", "i.emissivity"],
    "Geometry": ["i.rotate"],
}


def installed_modules(grass):
    """Return every module name the installation offers, sorted.

    GRASS has no command that lists them, so this reads the folders its
    launcher puts on the PATH: the compiled modules, the scripts, and the
    user's own addons.
    """
    try:
        out = subprocess.run(
            [grass, "--config", "path"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        gisbase = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        gisbase = ""
    names = set()
    folders = [os.path.join(gisbase, "bin"), os.path.join(gisbase, "scripts")]
    folders.append(os.path.expanduser(ADDON_DIR))
    for folder in folders:
        try:
            entries = os.listdir(folder)
        except OSError:
            continue
        for entry in entries:
            prefix = entry.split(".", 1)[0]
            if "." in entry and prefix in interface.FAMILIES:
                names.add(entry)
    return sorted(names)


#: How many GRASS runs the form read keeps going at once. One module takes
#: about a quarter of a second, so a thousand in turn would take an afternoon.
READ_WORKERS = 24

#: What a command that can honestly take hours declares as its `timeout`: a
#: day, the most RustGIS allows. A download (t.in.era5) or r.watershed on a
#: national DEM does not fit in the 120 seconds a command gets by default.
#:
#: It holds on the command line, in Python and in scripts only: the desktop
#: app runs commands on its window's own thread and stops them at 120 seconds
#: whatever the manifest says. Nothing tells the plugin which host it is in,
#: so the run itself still keeps to 120 seconds unless the caller asks for
#: more with the command's own `timeout` parameter.
LONG_TIMEOUT = 86400

#: The MetaMonitor slot this run reports into
#: (https://github.com/YannChemin/MetaMonitor). One stable id, so running the
#: generator again overwrites its slot instead of adding another.
SLOT = "rustgis-grass-manifest"


def slot_dir():
    """Return MetaMonitor's spool folder, or None when there is none.

    ``METAMONITOR_SPOOL`` overrides it; cron has no ``XDG_RUNTIME_DIR``, so
    ``/run/user/<uid>`` is the fallback.
    """
    spool = os.environ.get("METAMONITOR_SPOOL")
    if spool:
        return pathlib.Path(spool)
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    base = pathlib.Path(run) / "metamonitor" / "slots"
    return base if base.is_dir() else None


def report(done, total, detail, state="running"):
    """Say how far the read has got, in MetaMonitor's spool.

    Reading 1,200 module forms takes minutes, which is long enough to look
    stalled; this is the progress bar for it. The slot is written here rather
    than through ``mmctl`` because this runs about once a second for the whole
    read, and a subprocess each time would cost more than the reporting is
    worth. Reporting must never break or slow the build, so every failure is
    ignored and a machine without MetaMonitor is unaffected.

    :param state: ``running``, ``done`` or ``failed``
    """
    base = slot_dir()
    if not base:
        return
    slot = {
        "name": "GRASS manifest",
        "percent": round(100 * done / total, 1) if total else 0,
        "detail": detail,
        "state": state,
        "pid": os.getpid(),
    }
    # MetaMonitor ignores dotfiles, so the temporary name is one; the rename
    # is what makes the new contents visible, whole.
    tmp = base / f".{SLOT}.{os.getpid()}"
    try:
        tmp.write_text(json.dumps(slot))
        tmp.replace(base / SLOT)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass


def read_all(modules, grass, workers=READ_WORKERS):
    """Read every module's interface description, several at a time.

    One module takes about a quarter of a second; a thousand of them in turn
    would take an afternoon. Even at 24 at a time it is a couple of minutes
    (129 s for 1,204 modules, measured on the author's machine), so it reports
    how far it has got, to the terminal and to MetaMonitor
    (https://github.com/YannChemin/MetaMonitor).

    :return: ``({module: xml}, [name of each that could not be read])``
    """

    def read(module):
        try:
            return module, session.interface_description(module, grass)
        except (session.GrassError, OSError):
            return module, None

    docs, failed = {}, []
    total, last = len(modules), 0.0
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for done, (module, xml) in enumerate(pool.map(read, modules), 1):
            if xml:
                docs[module] = xml
            else:
                failed.append(module)
            # About one line and one slot write a second, not one per module.
            now = time.monotonic()
            if now - last >= 1.0 or done == total:
                last = now
                print(
                    f"\r  {done}/{total} forms read ({100 * done // total}%)",
                    end="" if done < total else "\n",
                    flush=True,
                )
                report(done, total, f"{module} ({done}/{total})")
    report(total, total, f"{len(docs)} forms read", state="done")
    return docs, failed


def toolbox_of(described):
    """Return the Tools pane toolbox a vector module belongs in.

    GRASS's own keywords put it there: the first that is not the family's own
    name, capitalised, so v.voronoi lands in "GRASS > Vector > Proximity".
    """
    for word in (described.get("keywords") or "").split(","):
        word = word.strip()
        if word and word.lower() not in ("vector", "raster", "imagery", "display"):
            return f"GRASS › Vector › {word[:1].upper()}{word[1:]}"
    return "GRASS › Vector"


def name_of(module):
    """Return a readable tool name for a module, from its own name."""
    parts = module.split(".")[1:]
    return " ".join(part.replace("_", " ").title() for part in parts) or module


#: The raster modules, run as commands because a tool gets no raster.
COMMANDS = [
    {
        "id": "raster-slope",
        "label": "Slope",
        "help": "r.slope.aspect: the steepness of the chosen raster layer.",
        "icon": "relief",
        "params": '{"timeout"?: seconds} (the GRASS GIS panel chooses the '
        "layer and the unit)",
        "timeout": LONG_TIMEOUT,
    },
    {
        "id": "raster-aspect",
        "label": "Aspect",
        "help": "r.slope.aspect: the direction each cell of the chosen raster faces.",
        "icon": "directions",
        "params": '{"timeout"?: seconds} (the GRASS GIS panel chooses the layer)',
        "timeout": LONG_TIMEOUT,
    },
    {
        "id": "raster-viewshed",
        "label": "Viewshed",
        "help": "r.viewshed: what is visible from the place picked on the map, "
        "or from its centre when no viewpoint was picked.",
        "icon": "explore",
        "params": '{"timeout"?: seconds} (the GRASS GIS panel chooses the '
        "layer, the viewpoint, the viewer's height and the range)",
        "timeout": LONG_TIMEOUT,
    },
    {
        "id": "run-module",
        "label": "Run\nModule",
        "help": "Run the module chosen in the GRASS Modules tree on the chosen "
        "raster layer, with GRASS's own defaults. A module that needs no "
        "raster runs with the form's values in the GRASS mapset chosen under "
        "Projects and mapsets.",
        "icon": "run",
        "params": '{"module"?: "r.slope.aspect", "timeout"?: seconds} (without '
        "them the panel's trees choose the module, the layer and the mapset)",
        # A download (t.in.era5) does not fit in the 120 seconds a command
        # normally gets.
        "timeout": LONG_TIMEOUT,
    },
    {
        "id": "imagery-state",
        "label": "Imagery\nModules",
        "help": "Open the GRASS GIS panel with its module tree filtered to the "
        "imagery (i.*) modules, and list the ones Run Module can drive.",
        "icon": "bands",
        "params": "{} (the panel's mode tree shows the same filter)",
    },
    {
        "id": "temporal-state",
        "label": "Temporal\nModules",
        "help": "Open the GRASS GIS panel with its module tree filtered to the "
        "temporal (t.*) modules. None can run from one raster: they read a "
        "space-time dataset, so the panel's tree gives each one's reason.",
        "icon": "time_slider",
        "params": "{} (the panel's mode tree shows the same filter)",
    },
    {
        "id": "all-state",
        "label": "All\nModules",
        "help": "Open the GRASS GIS panel with its module tree showing every "
        "installed module again.",
        "icon": "catalog",
        "params": "{} (the panel's mode tree shows the same filter)",
    },
    {
        "id": "data-folder",
        "label": "GRASS\nDatabase",
        "help": "Put the GRASS database GRASS itself uses into the browser, "
        "under Folders.",
        "icon": "add_folder",
        "params": "{}",
    },
    {
        "id": "data-add",
        "label": "Add\nMap",
        "help": "Add the map chosen in the GRASS Data tree to this project, "
        "exported to a format RustGIS reads, and put the view in that GRASS "
        "project's own coordinate system.",
        "icon": "add_data",
        "params": '{"map"?: "raster/<project>/<mapset>/<name>"} (without it '
        "the panel's tree chooses the map)",
        "timeout": LONG_TIMEOUT,
    },
    {
        "id": "data-workspace",
        "label": "Load\nWorkspace",
        "help": "Open the GRASS workspace (.gxw) chosen under Workspaces as "
        "this project: its layers, its coordinate system and its extent. "
        "This replaces the current project.",
        "icon": "folder_open",
        "params": '{"workspace"?: "workspace/<percent-encoded path>", '
        '"discard"?: true} (without them the panel\'s tree chooses it, and a '
        "project with unsaved changes stops the load)",
        "timeout": LONG_TIMEOUT,
    },
    {
        "id": "data-browse",
        "label": "Browse\nMapset",
        "help": "List the maps of the mapset chosen in the GRASS Data tree.",
        "icon": "catalog",
        "params": "{}",
    },
    {
        "id": "region-view",
        "label": "Region =\nMap View",
        "help": "Set the Analysis Environment's extent to what the map shows, "
        "which becomes the computational region of every GRASS raster run.",
        "icon": "zoom_box",
        "params": "{}",
    },
    {
        "id": "region-box",
        "label": "Region =\nBox",
        "help": "Set the Analysis Environment's extent to a box drawn on the "
        "map, which becomes the computational region of every GRASS raster "
        "run. The panel's Region from a Box asks for the box.",
        "icon": "measure_area",
        "params": '{"panel": {"region-box": {"bbox": [w, s, e, n]}}}',
    },
    {
        "id": "region-full",
        "label": "Region =\nWhole Layer",
        "help": "Clear the Analysis Environment's extent, so a run covers the "
        "whole input raster.",
        "icon": "zoom_full",
        "params": "{}",
    },
    {
        "id": "panel-step",
        "label": "Panel Step",
        "help": "Show one step of the GRASS GIS panel: the GRASS project and "
        "its maps, the map layer and the region, the terrain runs, or the "
        "module catalogue. The panel's own dropdown sets it.",
        "icon": "pane_right",
        "params": '{"panel": {"step": "data|layer|terrain|modules"}}',
    },
    {
        "id": "layer-pick",
        "label": "Read Chosen Layer",
        "help": "Describe the raster layer chosen in the GRASS GIS panel: its "
        "source, its bands and the region a run would use. Answers nothing "
        "else, so choosing a layer does not rebuild the module catalogue.",
        "icon": "raster_layer",
        "params": '{"panel": {"raster": "<layer id>"}}',
    },
    {
        "id": "module-pick",
        "label": "Read Chosen Module",
        "help": "Describe the module chosen in the GRASS GIS panel and fill "
        "its form. Answers neither tree, so choosing one of 1,177 modules "
        "costs a few kilobytes instead of the whole catalogue.",
        "icon": "toolbox",
        "params": '{"panel": {"modules": "<branch>/<module>"}}',
    },
    {
        "id": "raster-state",
        "label": "Refresh\nRasters",
        "help": "List the map's raster layers in the GRASS Raster panel again.",
        "icon": "raster_layer",
        "params": "{}",
    },
]

#: The ribbon menus the vector tools go into, in the order they are shown,
#: with the icon each carries and the tools it holds by their manifest id.
#:
#: GRASS's own keywords put 64 tools into 27 menus, 20 of them holding a single
#: tool and two of them differing only in case (LIDAR and Lidar): a ribbon
#: column of menus that each open to one row. These nine group the same work by
#: what it does. The keyword stays in each tool's `toolbox`, which is what the
#: Tools pane and its search show, so nothing is lost.
VECTOR_MENUS = [
    (
        "Overlay & clip",
        "clip",
        ["v.clip", "v.dissolve", "v.extract", "v.select", "v.overlay", "v.patch"],
    ),
    (
        "Geometry",
        "hull",
        [
            "v.hull",
            "v.concave.hull",
            "v.delaunay",
            "v.voronoi",
            "v.centerpoint",
            "v.centroids",
            "v.centerline",
            "v.ellipse",
            "v.fill.holes",
            "v.parallel",
            "v.drape",
            "v.extrude",
        ],
    ),
    (
        "Points & lines",
        "split",
        ["v.to.points", "v.split", "v.segment", "v.explode", "v.type", "v.perturb"],
    ),
    (
        "Proximity & sampling",
        "near",
        ["v.distance", "v.sample", "v.random", "v.kernel", "v.outlier", "v.boxplot"],
    ),
    (
        "Network",
        "directions",
        [
            "v.net",
            "v.net.alloc",
            "v.net.distance",
            "v.net.path",
            "v.net.salesman",
            "v.net.steiner",
            "v.isochrones",
            "v.lrs.create",
            "v.lrs.label",
            "v.lrs.segment",
            "v.gsflow.export",
            "v.gsflow.gravres",
            "v.gsflow.grid",
            "v.gsflow.hruparams",
            "v.gsflow.reaches",
            "v.gsflow.segments",
        ],
    ),
    (
        "Point clouds & LIDAR",
        "point_layer",
        [
            "v.decimate",
            "v.lidar.correction",
            "v.lidar.edgedetection",
            "v.lidar.growing",
            "v.lidar.mcc",
            "v.cluster",
        ],
    ),
    (
        "Generalize & clean",
        "simplify",
        ["v.generalize", "v.build", "v.build.polylines", "v.clean"],
    ),
    (
        "Transform & project",
        "identity",
        ["v.transform", "v.proj", "v.rectify", "v.surf.rst"],
    ),
    (
        "Tables & import",
        "table",
        ["v.db.droprow", "v.category", "v.convert", "v.in.pygbif"],
    ),
]

#: Where a tool this file does not name by module goes, by its GRASS keyword:
#: another installation's addons still land in a themed menu rather than in one
#: of their own.
VECTOR_KEYWORDS = {
    "clip": "Overlay & clip",
    "dissolve": "Overlay & clip",
    "extract": "Overlay & clip",
    "buffer": "Overlay & clip",
    "geometry": "Geometry",
    "centroid": "Geometry",
    "lines central": "Geometry",
    "surface": "Geometry",
    "graphics": "Points & lines",
    "distance": "Proximity & sampling",
    "sampling": "Proximity & sampling",
    "kernel density": "Proximity & sampling",
    "statistics": "Proximity & sampling",
    "plot": "Proximity & sampling",
    "network": "Network",
    "linear reference system": "Network",
    "stream network": "Network",
    "lidar": "Point clouds & LIDAR",
    "point cloud": "Point clouds & LIDAR",
    "generalization": "Generalize & clean",
    "topology": "Generalize & clean",
    "transformation": "Transform & project",
    "projection": "Transform & project",
    "rectify": "Transform & project",
    "attribute table": "Tables & import",
    "category": "Tables & import",
    "import": "Tables & import",
    "export": "Tables & import",
}

#: The panel the raster commands take their parameters from. A command opens no
#: dialog, so without a panel it could only ever run with fixed defaults.
#:
#: RustGIS draws a panel as one flat column with no sections, so everything
#: GRASS needs came to 24 widgets and several screens of scrolling, four trees
#: among them. The `step` dropdown and `grass_bridge.panel` turn that into four
#: steps in the order the work is done -- project, layer and region, terrain,
#: modules -- and every answer sets `visible` from the step, so at most eight
#: widgets are drawn at once. The declaration order below is the order within a
#: step, since the widgets of the other steps are filtered out before drawing.
PANEL = {
    "title": "GRASS GIS",
    "icon": "stats",
    "help": "Four steps, in the order the work is done: choose a GRASS project "
    "and add its maps, choose the map layer and the computational region, run "
    "the shaped terrain modules, then find any of the installed modules and "
    "run it with its own form.",
    "state": "raster-state",
    "items": [
        {
            "kind": "choice",
            "id": "step",
            "label": "Step",
            "help": "Which part of the panel is shown. The steps are in the "
            "order GRASS needs them: a project before its maps, a layer and a "
            "region before a module can run on them.",
            "options": [{"id": step, "label": label} for step, label in panel.STEPS],
            "default": panel.FIRST,
            "command": "panel-step",
        },
        # 1. Project and data.
        {"kind": "text", "id": "gisdbase", "label": "GRASS database"},
        {
            "kind": "tree",
            "id": "database",
            "label": "Projects and mapsets",
            "help": "The database GRASS itself uses. Choose a mapset to list "
            "its maps, then a map, then Add Map. The workspaces found "
            "under the database and the home folder are listed first; "
            "choosing one and pressing Load Workspace opens it as this "
            "project.",
            "search": True,
            "command": "data-browse",
        },
        {"kind": "button", "command": "data-add"},
        {"kind": "button", "command": "data-workspace"},
        {"kind": "button", "command": "data-folder"},
        # 2. Layer and region.
        {
            "kind": "tree",
            "id": "raster",
            "label": "Raster layer",
            "help": "The layer the module reads. Only raster layers are listed.",
            "search": True,
            # layer-pick answers this layer's source, bands and region and
            # nothing else: a layer choice used to rebuild all 1,424 catalogue
            # nodes, 270 KB of JSON, for no change.
            "command": "layer-pick",
        },
        {"kind": "text", "id": "source", "label": "Chosen layer"},
        {
            "kind": "slider",
            "id": "band",
            "label": "Band sent to GRASS",
            "help": "RustGIS writes one band of a raster that is not a colour "
            "one, so this says which. The ends declared here cover a "
            "hyperspectral cube; raster.info narrows them to the chosen "
            "layer's own bands, with their names, as soon as there is one.",
            "min": 1,
            # RustGIS keeps a slider's value within the ends the manifest
            # declares until a command answers new ones, so the declared
            # maximum has to cover the widest raster rather than one band.
            "max": MAX_BANDS,
            "default": 1,
            "steps": True,
        },
        {
            "kind": "text",
            "id": "region",
            "label": "Computational region",
            "help": "What the region will be: the Analysis Environment's extent "
            "and cell size, which Analyze > Geoprocessing > Environments sets.",
        },
        {"kind": "button", "command": "region-view"},
        {"kind": "button", "command": "region-full"},
        {
            "kind": "pick",
            "id": "region-box",
            "label": "Region from a Box",
            "help": "Draw the computational region on the map. GRASS takes a "
            "raster module's extent from the region, not from its input, so "
            "this is the third way GRASS users expect to set it, beside the "
            "map view and the whole layer.",
            "shape": "box",
            "command": "region-box",
        },
        {
            "kind": "slider",
            "id": "res",
            "label": "Cell size in the raster's own units (0: from the environment)",
            "help": "Overrides the Analysis Environment's cell size. The region "
            "is aligned to it, and r.slope.aspect is stopped from putting the "
            "region back on the elevation map's grid.",
            "min": 0,
            "max": 1000,
            "default": 0,
            "steps": True,
        },
        # 3. Terrain: the three shaped runs and the parameters only they take.
        {
            "kind": "checkbox",
            "id": "percent",
            "label": "Slope in percent instead of degrees",
            "default": False,
        },
        {
            "kind": "slider",
            "id": "height",
            "label": "Viewer's height above the ground (m)",
            "min": 0,
            "max": 500,
            "default": 2,
            "steps": True,
        },
        {
            "kind": "slider",
            "id": "maxdist",
            "label": "Viewshed range (km; 0 for no limit)",
            "min": 0,
            "max": 200,
            "default": 0,
            "steps": True,
        },
        {
            "kind": "checkbox",
            "id": "curvature",
            "label": "Viewshed follows the curvature of the earth",
            "default": False,
        },
        {
            "kind": "pick",
            "id": "viewpoint",
            "label": "Viewpoint on the Map",
            "help": "Where the viewer stands for Viewshed. RustGIS marks the "
            "place on the map while the panel is open. Without one the "
            "viewshed falls back to the centre of the map, as it always did, "
            "and says so. It runs no command of its own: pick the place, then "
            "press Viewshed.",
            "shape": "point",
        },
        {"kind": "button", "command": "raster-slope"},
        {"kind": "button", "command": "raster-aspect"},
        {"kind": "button", "command": "raster-viewshed"},
        # 4. Modules.
        {
            "kind": "choice",
            "id": "family",
            "label": "Catalogue",
            "help": "Which modules the tree below lists: every installed module, "
            "the imagery (i.*) modules only, or the temporal (t.*) modules only. "
            "This was a three-node tree; a dropdown is one line and says what is "
            "chosen without being scrolled.",
            "options": [
                {"id": family, "label": label} for family, label, _ in panel.FAMILIES
            ],
            "default": panel.FAMILIES[0][0],
            # Filtering the catalogue is the one panel choice that has to
            # rebuild the module tree, so it asks for the whole state.
            "command": "raster-state",
        },
        {
            "kind": "tree",
            "id": "modules",
            "label": "GRASS modules (runs here first)",
            "help": "Searchable by module name, summary and GRASS keywords. "
            "'Runs from here' lists the modules Run Module can drive on the "
            "chosen raster, or with their form in the mapset chosen under "
            "Projects and mapsets; 'All modules' lists every installed one with "
            "the reason the others cannot run here; 'Recently run' returns to one. "
            "The Catalogue dropdown above keeps all modules, or only the imagery "
            "or temporal ones.",
            "search": True,
            # module-pick answers the details and the form only, so choosing a
            # module does not send the tree it was chosen from back again.
            "command": "module-pick",
        },
        {
            "kind": "text",
            "id": "details",
            "label": "Chosen module",
            "help": "What the module reads and writes, and whether Run Module "
            "can drive it from this panel.",
        },
        {
            "kind": "form",
            "id": "form",
            "label": "Module parameters",
            "help": "The chosen module's own parameters, from its GRASS "
            "interface description. A required field is marked *; Run Module "
            "passes the values the form holds.",
        },
        {"kind": "button", "command": "run-module"},
        # Shown in every step: what the last run did has to be readable from
        # wherever the user is.
        {"kind": "text", "id": "status", "label": "Last run"},
    ],
}


def raster_command_id(module):
    """Return the manifest's local command id for a raster module."""
    return module.replace(".", "-")


def raster_commands(catalogue, planned=None):
    """Return a command for each curated raster module the installation has.

    :param catalogue: the catalogue entries, which say what each module reads
        and writes
    :param planned: the menus to fill, :data:`RASTER_COMMANDS` by default
    :return: ``([command, ...], {command id: module}, {menu: [command id]})``
    """
    entries = {entry["module"]: entry for entry in catalogue}
    commands, modules, menus = [], {}, {}
    for menu, wanted in (RASTER_COMMANDS if planned is None else planned).items():
        for module in wanted:
            entry = entries.get(module)
            # Only a module Run Module can actually drive is offered; the
            # rest keep their reason in the panel's tree.
            if not entry or not entry.get("runnable"):
                continue
            cid = raster_command_id(module)
            commands.append(
                {
                    "id": cid,
                    "label": module,
                    "help": (
                        f"{module}: {entry['summary']}" if entry["summary"] else module
                    )[:300]
                    + " Runs on the layer chosen in the GRASS GIS panel, with "
                    "the band and region the panel holds.",
                    "icon": MENU_ICONS.get(menu, "raster_layer"),
                    "params": '{"timeout"?: seconds} (the GRASS GIS panel '
                    "chooses the layer, the band and the region)",
                    # r.watershed on a national DEM does not fit in the 120
                    # seconds a command gets by default. This holds on the
                    # command line, in Python and in scripts; the desktop app
                    # stops a command at 120 seconds whatever the manifest
                    # says, so the run keeps to 120 unless its own timeout
                    # parameter asks for more.
                    "timeout": LONG_TIMEOUT,
                }
            )
            modules[cid] = module
            menus.setdefault(menu, []).append(cid)
    return commands, modules, menus


#: The plugin's own interface text in French, keyed by the English exactly as
#: this file writes it (RustGIS looks a string up as the manifest declares it,
#: line breaks included). Only the plugin's own words are here: a tool's name,
#: summary and parameter labels come from the GRASS installation, which has
#: its own translations, and are left as GRASS wrote them.
FRENCH = {
    "GRASS GIS Tools": "Outils GRASS GIS",
    "Data": "Donnees",
    "Region": "Region",
    "Raster": "Raster",
    "Imagery": "Imagerie",
    "Temporal": "Temporel",
    "Vector": "Vecteur",
    "Modules": "Modules",
    "Terrain": "Relief",
    "Hydrology": "Hydrologie",
    "Filters": "Filtres",
    "Surfaces": "Surfaces",
    "Sun": "Soleil",
    "Overlay & clip": "Superposition et decoupe",
    "Points & lines": "Points et lignes",
    "Proximity & sampling": "Proximite et echantillonnage",
    "Network": "Reseau",
    "Point clouds & LIDAR": "Nuages de points et LIDAR",
    "Generalize & clean": "Generalisation et nettoyage",
    "Transform & project": "Transformation et projection",
    "Tables & import": "Tables et import",
    "Enhance": "Rehaussement",
    "Preprocess": "Pretraitement",
    "Detect": "Detection",
    "Geometry": "Geometrie",
    "GRASS GIS": "GRASS GIS",
    "Slope": "Pente",
    "Aspect": "Exposition",
    "Viewshed": "Bassin de visibilite",
    "Run\nModule": "Lancer le\nmodule",
    "Imagery\nModules": "Modules\nd'imagerie",
    "Temporal\nModules": "Modules\ntemporels",
    "All\nModules": "Tous les\nmodules",
    "GRASS\nDatabase": "Base GRASS",
    "Add\nMap": "Ajouter\nla carte",
    "Load\nWorkspace": "Charger\nl'espace",
    "Load Workspace": "Charger l'espace de travail",
    "Browse\nMapset": "Parcourir\nle jeu",
    "Region =\nMap View": "Region =\nvue",
    "Region =\nWhole Layer": "Region =\ncouche",
    "Region =\nBox": "Region =\nboite",
    "Region from a Box": "Region depuis une boite",
    "Viewpoint on the Map": "Point de vue sur la carte",
    "Refresh\nRasters": "Actualiser\nles rasters",
    "Panel Step": "Etape du panneau",
    "Read Chosen Layer": "Lire la couche choisie",
    "Read Chosen Module": "Lire le module choisi",
    "Step": "Etape",
    "1. Project & data": "1. Projet et donnees",
    "2. Layer & region": "2. Couche et region",
    "3. Terrain": "3. Relief",
    "4. Modules": "4. Modules",
    "Imagery only": "Imagerie seulement",
    "Temporal only": "Temporel seulement",
    "GRASS database": "Base de donnees GRASS",
    "Projects and mapsets": "Projets et jeux de donnees",
    "Raster layer": "Couche raster",
    "Chosen layer": "Couche choisie",
    "Band sent to GRASS": "Bande envoyee a GRASS",
    "Computational region": "Region de calcul",
    "Cell size in the raster's own units (0: from the environment)": (
        "Taille de cellule dans les unites du raster (0 : celle de l'environnement)"
    ),
    "Slope in percent instead of degrees": "Pente en pourcents plutot qu'en degres",
    "Viewer's height above the ground (m)": "Hauteur de l'observateur (m)",
    "Viewshed range (km; 0 for no limit)": "Portee de visibilite (km ; 0 : sans limite)",
    "Viewshed follows the curvature of the earth": (
        "La visibilite tient compte de la courbure de la Terre"
    ),
    "All modules": "Tous les modules",
    "GRASS modules (runs here first)": "Modules GRASS (ceux qui tournent d'abord)",
    "Chosen module": "Module choisi",
    "Catalogue": "Catalogue",
    "Last run": "Derniere execution",
}


def i18n():
    """Return the manifest's translation table.

    :return: ``{"fr": {...}}``
    """
    return {"fr": dict(FRENCH)}


def check_i18n(manifest):
    """Name every translation whose English string is not in the manifest.

    A translation RustGIS never looks up is dead weight and, worse, hides a
    label that was reworded here and not there, so the generator says so
    instead of writing it out quietly.
    """
    text = json.dumps(manifest, ensure_ascii=False)
    return sorted(
        k for k in FRENCH if json.dumps(k, ensure_ascii=False)[1:-1] not in text
    )


def tool_id(module):
    """Return the manifest's local tool id for a module name."""
    return module.replace(".", "-")


def build():
    """Return the manifest, the tool-to-module map and the module catalogue."""
    grass = session.find_grass()
    if not grass:
        sys.exit("GRASS GIS is not installed, or RUSTGIS_GRASS does not name it")
    print(f"reading forms from GRASS {session.version(grass)} at {grass}")

    names = installed_modules(grass)
    print(
        f"  {len(names)} modules installed; reading their forms "
        f"{READ_WORKERS} at a time. This takes a couple of minutes, now and "
        "again after a GRASS upgrade."
    )
    docs, failed = read_all(names, grass)
    print(f"  {len(docs)} read, {len(failed)} could not be")

    catalogue, eligible = [], []
    for module in sorted(docs):
        try:
            described = interface.describe(docs[module])
        except ValueError:
            failed.append(module)
            continue
        catalogue.append(
            {
                "module": module,
                "summary": described["summary"],
                "family": described["family"],
                "keywords": described["keywords"],
                # What the bridge can do with it, worked out once here rather
                # than by running the module again when the panel opens.
                "raster": bool(described["raster_in"] and described["raster_out"]),
                "vector": bool(described["vector_in"] and described["vector_out"]),
                # Every raster port, and the one Run Module names. A module
                # with several optional inputs can still run; the one it must
                # have is not always the first GRASS lists.
                "raster_in": described["raster_in"],
                "raster_out": described["raster_out"],
                "raster_input": described["raster_input"],
                "raster_output": described["raster_output"],
                # Whether one raster in and one out is all it needs, so the
                # panel can offer a "runs here" list instead of a promise.
                "runnable": described["runnable"],
                "reason": described["reason"],
                # A temporal, database or general module the form can drive in
                # a project/mapset the user chooses, without one raster in and
                # one out.
                "mapset_runnable": described["mapset_runnable"],
                "mapset_reason": described["mapset_reason"],
                "mapset_inputs": described["mapset_inputs"],
                # The new maps or datasets it must be given names for, each
                # checked against the mapset before the run.
                "mapset_outputs": described["mapset_outputs"],
                # A display module that can draw a picture from its form: the
                # bridge gives it a cairo monitor and imports the picture.
                "render_runnable": described["render_runnable"],
                "render_reason": described["render_reason"],
                "render_inputs": described["render_inputs"],
                "needs": described["needs"],
                "bands": described["bands"],
                "temporal": described["temporal"],
                # The parameters Run Module's form offers: what a command
                # cannot ask before the panel existed.
                "form": interface.form_fields(docs[module]),
            }
        )
        if described["vector_in"] and described["vector_out"]:
            eligible.append(module)

    # A tool needs a form, and a manifest holds 64 of them. The preferred
    # modules come first, then the rest in GRASS's own order, so the same
    # installation always gives the same manifest.
    chosen = [m for m in PREFERRED if m in eligible]
    rest = [m for m in eligible if m not in chosen]
    # Vector modules first: the budget is for work on features, and without
    # this an installation's addons (r.green.hydro.* and the like, which
    # happen to read and write a vector) crowd out v.clip and v.category.
    rest.sort(key=lambda m: (0 if m.startswith("v.") else 1, m))
    chosen += rest
    left_out = chosen[MAX_TOOLS:]
    chosen = chosen[:MAX_TOOLS]

    tools, modules, notes = [], {}, {}
    for module in chosen:
        try:
            form = interface.parse(docs[module])
        except ValueError as e:
            print(f"  {module}: skipped ({e})")
            continue
        params = [
            {
                "name": "input",
                "label": "Input features",
                "kind": "vectorLayer",
                "required": True,
            }
        ] + form["params"]
        described = interface.describe(docs[module])
        tools.append(
            {
                "id": tool_id(module),
                "name": name_of(module),
                "toolbox": toolbox_of(described),
                "summary": form["summary"][:300],
                "params": params[: interface.MAX_PARAMS],
            }
        )
        modules[tool_id(module)] = module
        notes[tool_id(module)] = form["skipped"]

    rasters = sum(1 for entry in catalogue if entry["raster"])
    runnable = sum(1 for entry in catalogue if entry["runnable"])
    in_mapset = sum(
        1 for entry in catalogue if entry["mapset_runnable"] and not entry["runnable"]
    )
    renders = sum(1 for entry in catalogue if entry["render_runnable"])
    print(
        f"  {len(tools)} vector modules became tools, {len(left_out)} more could "
        f"have; {runnable} of {rasters} raster modules run from the panel with "
        f"defaults; {in_mapset} more run from their form in a chosen mapset; "
        f"{renders} display modules render a picture; "
        f"{len(catalogue)} modules in the tree"
    )

    raster_cmds, raster_modules, raster_menus = raster_commands(catalogue)
    imagery_cmds, imagery_modules, imagery_menus = raster_commands(
        catalogue, IMAGERY_COMMANDS
    )
    print(
        f"  {len(raster_cmds)} raster modules got a command of their own, in "
        f"{len(raster_menus)} ribbon menus"
    )
    print(
        f"  {len(imagery_cmds)} imagery modules got a command of their own, in "
        f"{len(imagery_menus)} ribbon menus"
    )
    files = sum(
        1 for tool in tools for param in tool["params"] if param["kind"] == "file"
    )
    print(f"  {files} tool parameters are files the user picks")

    manifest = {
        "id": "grass-vector",
        "name": "GRASS GIS Tools",
        "version": "0.11.0",
        "description": (
            "Runs GRASS GIS modules: vector modules as geoprocessing tools, and "
            "every installed module from a panel and a tab of its own. GRASS "
            "must be installed separately; nothing of it ships here."
        ),
        "author": "Yann Chemin",
        "homepage": "https://github.com/YannChemin/rustgis-grass-plugin",
        "license": "Unlicense",
        "runtime": "process",
        "run": {
            "windows": ["python", "main.py"],
            "default": ["python3", "main.py"],
        },
        "minRustgisVersion": MIN_RUSTGIS,
        # The raster and database commands have RustGIS write and read the
        # files they work on, and a tool's `file` parameter is handed to the
        # plugin, which needs both.
        "permissions": ["edit", "files"],
        "commands": COMMANDS + raster_cmds + imagery_cmds,
        "tools": tools,
        "tab": tab(tools, raster_menus, imagery_menus),
        "panel": PANEL,
        "skills": list(SKILLS),
        "i18n": i18n(),
    }
    catalogue_out = {
        "modules": modules,
        "rasterCommands": {**raster_modules, **imagery_modules},
        "skipped": notes,
        "catalogue": catalogue,
        "unreadable": sorted(set(failed)),
        "toolsLeftOut": left_out,
    }
    # The panel's steps decide which widget is drawn when, so a widget the
    # steps do not mention would never be shown and a step naming one the
    # panel does not have would hide nothing. Fail here rather than ship a
    # panel with an unreachable widget in it.
    declared = {item.get("id") or item.get("command") for item in PANEL["items"]}
    stepped = panel.every_item()
    if declared != stepped:
        sys.exit(
            "the panel's widgets and grass_bridge.panel's steps disagree: "
            f"only in the panel {sorted(declared - stepped)}, "
            f"only in the steps {sorted(stepped - declared)}"
        )
    _, unnamed = vector_menus(tools)
    if unnamed:
        print(
            f"  WARNING: {len(unnamed)} vector tools are in the ribbon's More "
            f"menu: neither VECTOR_MENUS nor VECTOR_KEYWORDS names them "
            f"({', '.join(unnamed[:8])})"
        )
    stale = check_i18n({k: v for k, v in manifest.items() if k != "i18n"})
    if stale:
        print(f"  WARNING: translations for text no longer in the manifest: {stale}")
    return manifest, catalogue_out


def vector_menus(tools):
    """Return the ribbon menus for the vector tools, and what was left over.

    :data:`VECTOR_MENUS` names the tools by module; a tool the table does not
    name goes by its GRASS keyword (:data:`VECTOR_KEYWORDS`), and one neither
    names lands in "More" and is reported, so a new addon is never dropped in
    silence.

    :param tools: the manifest's tools
    :return: ``([menu, ...], [tool id, ...])``, the second being the unnamed
    """
    by_id = {tool["id"]: tool for tool in tools}
    placed, menus, unnamed = set(), [], []
    extra = {}
    for tool in tools:
        if any(tool_id(m) == tool["id"] for _, _, mods in VECTOR_MENUS for m in mods):
            continue
        box = tool["toolbox"].split("\u203a")[-1].strip().lower()
        label = VECTOR_KEYWORDS.get(box)
        if label:
            extra.setdefault(label, []).append(tool["id"])
        else:
            unnamed.append(tool["id"])
    for label, icon, modules in VECTOR_MENUS:
        items = [tool_id(m) for m in modules if tool_id(m) in by_id]
        items += sorted(extra.get(label, []))
        placed.update(items)
        if not items:
            continue
        # A menu takes 32 items.
        for start in range(0, len(items), 32):
            part = items[start : start + 32]
            name = label if len(items) <= 32 else f"{label} {start // 32 + 1}"
            menus.append(
                {
                    "menu": name,
                    "icon": icon,
                    "items": [f"tool:{i}" for i in part],
                }
            )
    if unnamed:
        # Untranslated on purpose: it only appears for an addon neither table
        # names, and a translation for a menu no manifest declares would be
        # reported as dead weight on every build.
        menus.append(
            {
                "menu": "More",
                "icon": "toolbox",
                "items": [f"tool:{i}" for i in sorted(unnamed)[:32]],
            }
        )
    return menus, unnamed


def tab(tools, raster_menus=None, imagery_menus=None):
    """Return the plugin's own ribbon tab.

    A tab holds 8 groups and a small group 48 controls. Seven groups in the
    order the work is done, each entry with an icon of its own: the panel, the
    GRASS database, the region, the terrain and raster modules, the imagery
    modules, the vector tools in nine themed menus, and the module catalogue.

    The panel is declared once, not in three groups; the three catalogue
    filters are in a menu rather than on the top level, because they set what
    the panel's tree lists instead of running anything.
    """
    menus, _ = vector_menus(tools)
    return {
        "label": "GRASS",
        "groups": [
            {"label": "GRASS", "items": ["panel"]},
            {
                "label": "Data",
                "layout": "small",
                "items": [
                    "data-folder",
                    "data-add",
                    "data-workspace",
                    "data-browse",
                ],
            },
            {
                "label": "Region",
                "layout": "small",
                "items": [
                    "region-view",
                    "region-full",
                    "region-box",
                    "raster-state",
                ],
            },
            {
                "label": "Terrain",
                "layout": "small",
                "items": [
                    "raster-slope",
                    "raster-aspect",
                    "raster-viewshed",
                    *(
                        {
                            "menu": menu,
                            "icon": MENU_ICONS.get(menu, "raster_layer"),
                            "items": items[:32],
                        }
                        for menu, items in sorted((raster_menus or {}).items())
                    ),
                ],
            },
            {
                "label": "Imagery",
                "layout": "small",
                "items": [
                    *(
                        {
                            "menu": menu,
                            "icon": MENU_ICONS.get(menu, "bands"),
                            "items": items[:32],
                        }
                        for menu, items in sorted((imagery_menus or {}).items())
                    ),
                ]
                or ["imagery-state"],
            },
            {"label": "Vector", "layout": "small", "items": menus[:48]},
            {
                "label": "Modules",
                "layout": "small",
                "items": [
                    "run-module",
                    {
                        "menu": "Catalogue",
                        "icon": "catalog",
                        "items": ["all-state", "imagery-state", "temporal-state"],
                    },
                ],
            },
        ],
    }


if __name__ == "__main__":
    manifest, catalogue = build()
    (HERE / "plugin.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    (HERE / "modules.json").write_text(
        json.dumps(catalogue, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        f"wrote plugin.json with {len(manifest['tools'])} tools, "
        f"{len(manifest['commands'])} commands and a tab of "
        f"{len(manifest['tab']['groups'])} groups; modules.json carries "
        f"{len(catalogue['catalogue'])} modules"
    )
