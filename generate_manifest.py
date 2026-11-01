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

from grass_bridge import interface, session

HERE = pathlib.Path(__file__).parent

#: The vector modules this prototype offers. A plugin tool can only take and
#: return vector data (the ABI has no raster layer), so raster modules are out
#: until the bridge lives in a crate of its own.
MODULES = [
    ("v.voronoi", "Voronoi Polygons", "GRASS › Vector › Proximity"),
    ("v.delaunay", "Delaunay Triangulation", "GRASS › Vector › Proximity"),
    ("v.cluster", "Point Clusters", "GRASS › Vector › Statistics"),
    ("v.generalize", "Generalize", "GRASS › Vector › Geometry"),
    ("v.to.points", "Points Along Lines", "GRASS › Vector › Geometry"),
]


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
        "name": "GRASS GIS Vector Tools",
        "version": "0.1.0",
        "description": (
            "Runs GRASS GIS vector modules as geoprocessing tools. GRASS must be "
            "installed separately; nothing of it ships here."
        ),
        "runtime": "process",
        "run": {
            "windows": ["python", "main.py"],
            "default": ["python3", "main.py"],
        },
        "permissions": [],
        "tools": tools,
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
    print(f"wrote plugin.json with {len(manifest['tools'])} tools")
