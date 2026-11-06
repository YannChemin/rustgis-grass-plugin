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

#: The first RustGIS that has everything this manifest uses: panel trees and
#: compact ribbon columns with nested menus (RustGIS 0.5.0), and tool `file`
#: parameters and assistant skills (earlier). An older RustGIS refuses a tab
#: that names a panel, so it is better to be refused with a reason than to
#: load with half the plugin missing.
MIN_RUSTGIS = "0.5.0"

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
        "raster layer, with GRASS's own defaults. A module that needs no "
        "raster runs with the form's values in the GRASS mapset chosen under "
        "Projects and mapsets.",
        "icon": "stats",
        "params": "{} (the panel's trees choose the module, the layer and the mapset)",
        # A download (t.in.era5) does not fit in the 120 seconds a command
        # normally gets.
        "timeout": 86400,
    },
    {
        "id": "imagery-state",
        "label": "Imagery\nModules",
        "help": "Open the GRASS GIS panel with its module tree filtered to the "
        "imagery (i.*) modules, and list the ones Run Module can drive.",
        "icon": "stats",
        "params": "{} (the panel's mode tree shows the same filter)",
    },
    {
        "id": "temporal-state",
        "label": "Temporal\nModules",
        "help": "Open the GRASS GIS panel with its module tree filtered to the "
        "temporal (t.*) modules. None can run from one raster: they read a "
        "space-time dataset, so the panel's tree gives each one's reason.",
        "icon": "stats",
        "params": "{} (the panel's mode tree shows the same filter)",
    },
    {
        "id": "all-state",
        "label": "All\nModules",
        "help": "Open the GRASS GIS panel with its module tree showing every "
        "installed module again.",
        "icon": "stats",
        "params": "{} (the panel's mode tree shows the same filter)",
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
    "help": "Reach the GRASS database, find a module, and run the ones that "
    "need only a raster in and one out on a raster layer of the map. The form "
    "sets the chosen module's own parameters. The catalogue can show every "
    "module, or only the imagery or temporal ones.",
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
            "id": "mode",
            "label": "Catalogue",
            "help": "Which modules the tree below lists: every installed module, "
            "the imagery (i.*) modules only, or the temporal (t.*) modules only.",
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
            "the reason the others cannot run here; 'Recently run' returns to one. The "
            "Catalogue tree above keeps all modules, or only the imagery or "
            "temporal ones.",
            "search": True,
            # Choosing a module refreshes the details under this tree (and the
            # chosen layer, which costs one raster.info) before Run Module is
            # pressed, so a module that cannot run says why there and then.
            "command": "raster-state",
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
                    "icon": "stats",
                    "params": "{} (the GRASS GIS panel chooses the layer, the "
                    "band and the region)",
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
    "Database": "Base de donnees",
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
    "Browse\nMapset": "Parcourir\nle jeu",
    "Region =\nMap View": "Region =\nvue",
    "Region =\nWhole Layer": "Region =\ncouche",
    "Refresh\nRasters": "Actualiser\nles rasters",
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
        1
        for entry in catalogue
        if entry["mapset_runnable"] and not entry["runnable"]
    )
    print(
        f"  {len(tools)} vector modules became tools, {len(left_out)} more could "
        f"have; {runnable} of {rasters} raster modules run from the panel with "
        f"defaults; {in_mapset} more run from their form in a chosen mapset; "
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
        "version": "0.9.0",
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
    stale = check_i18n({k: v for k, v in manifest.items() if k != "i18n"})
    if stale:
        print(f"  WARNING: translations for text no longer in the manifest: {stale}")
    return manifest, catalogue_out


def tab(tools, raster_menus=None, imagery_menus=None):
    """Return the plugin's own ribbon tab.

    A tab holds 8 groups and a small group 48 controls, so the vector tools and
    the curated raster and imagery modules go into menus: one per toolbox,
    which is one per GRASS keyword, and one per theme.
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
                "items": ["data-folder", "data-add", "data-browse"],
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
                    *(
                        {"menu": menu, "items": items[:32]}
                        for menu, items in sorted((raster_menus or {}).items())
                    ),
                ],
            },
            {
                "label": "Imagery",
                "layout": "small",
                "items": [
                    "panel",
                    "imagery-state",
                    *(
                        {"menu": menu, "items": items[:32]}
                        for menu, items in sorted((imagery_menus or {}).items())
                    ),
                ],
            },
            {"label": "Vector", "layout": "small", "items": menus[:48]},
            {
                "label": "Temporal",
                "layout": "small",
                "items": ["panel", "temporal-state"],
            },
            {
                "label": "Modules",
                "layout": "small",
                "items": ["panel", "all-state", "run-module"],
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
