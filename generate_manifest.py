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

from grass_bridge import interface, session

HERE = pathlib.Path(__file__).parent

#: A manifest takes at most this many tools, so only this many modules can
#: have a form of their own. Every other module is reached from the panel's
#: tree, which holds them all.
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


def read_all(modules, grass, workers=24):
    """Read every module's interface description, several at a time.

    One module takes about a quarter of a second; a thousand of them in turn
    would take an afternoon.

    :return: ``({module: xml}, [name of each that could not be read])``
    """

    def read(module):
        try:
            return module, session.interface_description(module, grass)
        except (session.GrassError, OSError):
            return module, None

    docs, failed = {}, []
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        for module, xml in pool.map(read, modules):
            if xml:
                docs[module] = xml
            else:
                failed.append(module)
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
        "icon": "stats",
        "params": "{} (the GRASS Raster panel chooses the layer and the unit)",
    },
    {
        "id": "raster-aspect",
        "label": "Aspect",
        "help": "r.slope.aspect: the direction each cell of the chosen raster faces.",
        "icon": "stats",
        "params": "{} (the GRASS Raster panel chooses the layer)",
    },
    {
        "id": "raster-viewshed",
        "label": "Viewshed",
        "help": "r.viewshed: what is visible from the centre of the map.",
        "icon": "zoom_full",
        "params": "{} (the GRASS Raster panel chooses the layer, the viewer's height and the range)",
    },
    {
        "id": "run-module",
        "label": "Run\nModule",
        "help": "Run the module chosen in the GRASS Modules tree on the chosen "
        "raster layer, with GRASS's own defaults.",
        "icon": "stats",
        "params": "{} (the panel's trees choose the module and the layer)",
    },
    {
        "id": "data-folder",
        "label": "GRASS\nDatabase",
        "help": "Put the GRASS database GRASS itself uses into the browser, "
        "under Folders.",
        "icon": "bookmark",
        "params": "{}",
    },
    {
        "id": "data-add",
        "label": "Add\nMap",
        "help": "Add the map chosen in the GRASS Data tree to this project, "
        "exported to a format RustGIS reads.",
        "icon": "stats",
        "params": "{} (the panel's tree chooses the map)",
    },
    {
        "id": "data-browse",
        "label": "Browse\nMapset",
        "help": "List the maps of the mapset chosen in the GRASS Data tree.",
        "icon": "zoom_full",
        "params": "{}",
    },
    {
        "id": "region-view",
        "label": "Region =\nMap View",
        "help": "Set the Analysis Environment's extent to what the map shows, "
        "which becomes the computational region of every GRASS raster run.",
        "icon": "zoom_full",
        "params": "{}",
    },
    {
        "id": "region-full",
        "label": "Region =\nWhole Layer",
        "help": "Clear the Analysis Environment's extent, so a run covers the "
        "whole input raster.",
        "icon": "zoom_world",
        "params": "{}",
    },
    {
        "id": "raster-state",
        "label": "Refresh\nRasters",
        "help": "List the map's raster layers in the GRASS Raster panel again.",
        "icon": "bookmark",
        "params": "{}",
    },
]

#: The panel the raster commands take their parameters from. A command opens no
#: dialog, so without a panel it could only ever run with fixed defaults.
PANEL = {
    "title": "GRASS GIS",
    "icon": "stats",
    "help": "Reach the GRASS database, and run GRASS raster modules on a "
    "raster layer of the map.",
    "state": "raster-state",
    "items": [
        {"kind": "text", "id": "gisdbase", "label": "GRASS database"},
        {
            "kind": "tree",
            "id": "database",
            "label": "Projects and mapsets",
            "help": "The database GRASS itself uses. Choose a mapset to list "
            "its maps, then a map, then Add Map.",
            "search": True,
            "command": "data-browse",
        },
        {"kind": "button", "command": "data-add"},
        {"kind": "button", "command": "data-folder"},
        {
            "kind": "tree",
            "id": "raster",
            "label": "Raster layer",
            "help": "The layer the module reads. Only raster layers are listed.",
            "search": True,
            "command": "raster-state",
        },
        {"kind": "text", "id": "source", "label": "Chosen layer"},
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
        {"kind": "button", "command": "raster-slope"},
        {"kind": "button", "command": "raster-aspect"},
        {"kind": "button", "command": "raster-viewshed"},
        {
            "kind": "tree",
            "id": "modules",
            "label": "Every GRASS module installed",
            "help": "Searchable. Choosing a raster module and pressing Run "
            "Module runs it on the chosen raster layer.",
            "search": True,
        },
        {"kind": "button", "command": "run-module"},
        {"kind": "text", "id": "status", "label": "Last run"},
    ],
}


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
    print(f"  {len(names)} modules installed; reading their forms...")
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
                # The first of each, which is what Run Module wires up.
                "raster_in": described["raster_in"][:1],
                "raster_out": described["raster_out"][:1],
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
    print(
        f"  {len(tools)} vector modules became tools, {len(left_out)} more could "
        f"have; {rasters} raster modules run from the panel; "
        f"{len(catalogue)} modules in the tree"
    )

    manifest = {
        "id": "grass-vector",
        "name": "GRASS GIS Tools",
        "version": "0.3.0",
        "description": (
            "Runs GRASS GIS modules: vector modules as geoprocessing tools, and "
            "every installed module from a panel and a tab of its own. GRASS "
            "must be installed separately; nothing of it ships here."
        ),
        "runtime": "process",
        "run": {
            "windows": ["python", "main.py"],
            "default": ["python3", "main.py"],
        },
        # The raster and database commands have RustGIS write and read the
        # files they work on, which needs both.
        "permissions": ["edit", "files"],
        "commands": COMMANDS,
        "tools": tools,
        "tab": tab(tools),
        "panel": PANEL,
    }
    catalogue_out = {
        "modules": modules,
        "skipped": notes,
        "catalogue": catalogue,
        "unreadable": sorted(set(failed)),
        "toolsLeftOut": left_out,
    }
    return manifest, catalogue_out


def tab(tools):
    """Return the plugin's own ribbon tab.

    A tab holds 8 groups and a group 16 buttons, so the vector tools go into
    menus: one per toolbox, which is one per GRASS keyword.
    """
    boxes = {}
    for tool in tools:
        boxes.setdefault(tool["toolbox"].split("›")[-1].strip(), []).append(tool)
    menus = []
    for box in sorted(boxes):
        items = [
            f"tool:{tool['id']}" for tool in sorted(boxes[box], key=lambda t: t["name"])
        ]
        # A menu takes 32 items; a bigger toolbox is split in two.
        for start in range(0, len(items), 32):
            part = items[start : start + 32]
            label = box if len(items) <= 32 else f"{box} {start // 32 + 1}"
            menus.append({"menu": label, "items": part})
    return {
        "label": "GRASS",
        "groups": [
            {
                "label": "Database",
                "layout": "small",
                "items": ["panel", "data-folder", "data-add", "data-browse"],
            },
            {
                "label": "Region",
                "layout": "small",
                "items": ["region-view", "region-full", "raster-state"],
            },
            {
                "label": "Raster",
                "layout": "small",
                "items": [
                    "raster-slope",
                    "raster-aspect",
                    "raster-viewshed",
                    "run-module",
                ],
            },
            {"label": "Vector", "layout": "small", "items": menus[:48]},
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
