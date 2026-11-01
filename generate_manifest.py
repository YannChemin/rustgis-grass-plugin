"""Build plugin.json from GRASS's own parameter metadata.

Run this when the module list changes, or against another GRASS installation.
Nothing of GRASS is copied into the repository: the forms are read from the
installation each time this runs, and the file it writes is the plugin's own
manifest.

SPDX-License-Identifier: Unlicense
"""

import json
import pathlib
import sys

from grass_bridge import interface, raster, session

HERE = pathlib.Path(__file__).parent

#: The vector modules this prototype offers as geoprocessing tools. A tool can
#: only take and return vector data: the ABI has no raster parameter kind and a
#: tool makes no host requests. Raster modules run as commands instead, from
#: the panel below, which asks RustGIS to export and add the files.
MODULES = [
    ("v.voronoi", "Voronoi Polygons", "GRASS › Vector › Proximity"),
    ("v.delaunay", "Delaunay Triangulation", "GRASS › Vector › Proximity"),
    ("v.cluster", "Point Clusters", "GRASS › Vector › Statistics"),
    ("v.generalize", "Generalize", "GRASS › Vector › Geometry"),
    ("v.to.points", "Points Along Lines", "GRASS › Vector › Geometry"),
]


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
    "title": "GRASS Raster",
    "icon": "stats",
    "help": "Run GRASS raster modules on a raster layer of the map.",
    "state": "raster-state",
    "items": [
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
        {"kind": "text", "id": "status", "label": "Last run"},
    ],
}


def tool_id(module):
    """Return the manifest's local tool id for a module name."""
    return module.replace(".", "-")


def build():
    """Return the manifest and the tool-to-module map."""
    grass = session.find_grass()
    if not grass:
        sys.exit("GRASS GIS is not installed, or RUSTGIS_GRASS does not name it")
    print(f"reading forms from GRASS {session.version(grass)} at {grass}")

    tools, modules, notes = [], {}, {}
    for module, name, toolbox in MODULES:
        try:
            form = interface.parse(session.interface_description(module, grass))
        except (interface.ET.ParseError, ValueError, session.GrassError) as e:
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
        tools.append(
            {
                "id": tool_id(module),
                "name": name,
                "toolbox": toolbox,
                "summary": form["summary"][:300],
                "params": params[: interface.MAX_PARAMS],
            }
        )
        modules[tool_id(module)] = module
        notes[tool_id(module)] = form["skipped"]
        print(f"  {module}: {len(params)} parameters, {len(form['skipped'])} left out")

    manifest = {
        "id": "grass-vector",
        "name": "GRASS GIS Tools",
        "version": "0.1.0",
        "description": (
            "Runs GRASS GIS modules: vector modules as geoprocessing tools, raster "
            "modules from a panel of its own. GRASS must be installed separately; "
            "nothing of it ships here."
        ),
        "runtime": "process",
        "run": {
            "windows": ["python", "main.py"],
            "default": ["python3", "main.py"],
        },
        # The raster commands ask RustGIS to write and read GeoTIFFs
        # (share.exportRaster, layer.addData), which needs both.
        "permissions": ["edit", "files"],
        "commands": COMMANDS,
        "tools": tools,
        "panel": PANEL,
    }
    return manifest, modules, notes


if __name__ == "__main__":
    manifest, modules, notes = build()
    (HERE / "plugin.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    )
    (HERE / "modules.json").write_text(
        json.dumps({"modules": modules, "skipped": notes}, indent=2) + "\n"
    )
    print(
        f"wrote plugin.json with {len(manifest['tools'])} tools and "
        f"{len(manifest['commands'])} commands "
        f"({', '.join(sorted(raster.OPERATIONS))} + the panel's state)"
    )
