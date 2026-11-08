"""Running one GRASS raster module over a raster layer of the map.

A plugin *tool* cannot do this: the ABI has no raster parameter kind, a tool
receives features as GeoJSON, and it makes no host requests at all.  A plugin
*command* can, because it may ask RustGIS to run any command its permissions
allow.  The round trip is:

1. ``share.exportRaster`` writes the chosen raster layer as a GeoTIFF
   (the ``files`` permission),
2. GRASS reads that file into a throwaway project of the raster's own
   coordinate system and runs the module,
3. ``layer.addData`` adds the written GeoTIFF back as a raster layer
   (``files`` and ``edit``).

RustGIS stops a command after two minutes, so the run carries a deadline and
gives up with a readable reason rather than being killed with a half-written
file behind it.

Progress is reported to MetaMonitor (https://github.com/YannChemin/MetaMonitor)
by GRASS's own hook, which forwards every ``G_percent()`` of the module;
nothing here writes slots itself.

SPDX-License-Identifier: Unlicense
"""

import json
import math
import os
import time

from . import interface, session

#: What each command does, by its local command id.
OPERATIONS = {
    "raster-slope": {
        "module": "r.slope.aspect",
        "suffix": "slope",
        "label": "Slope",
    },
    "raster-aspect": {
        "module": "r.slope.aspect",
        "suffix": "aspect",
        "label": "Aspect",
    },
    "raster-viewshed": {
        "module": "r.viewshed",
        "suffix": "viewshed",
        "label": "Viewshed",
    },
}

#: A slider gives whole numbers, so the maximum distance is in kilometres.
METRES_PER_KM = 1000.0

#: Metres in one degree of latitude, and of longitude at the equator. Used only
#: to turn the Analysis Environment's cell size, which is in degrees, into the
#: units of a projected raster.
METRES_PER_DEGREE_LAT = 110540.0
METRES_PER_DEGREE_LON = 111320.0


def check_source(info, name):
    """Fail loudly when the chosen raster cannot be worked on in GRASS.

    ``raster.info`` says whether RustGIS read a coordinate system with the
    raster. Without one, ``grass -c <file>`` makes a project with no
    projection at all and every distance a module reports is in cells, which
    is worse than refusing.

    :param info: what ``raster.info`` answered
    :raises session.GrassError: when the raster is not georeferenced
    """
    if info and info.get("georeferenced") is False:
        raise session.GrassError(
            f"{name} carries no coordinate system, so GRASS would work in cells, "
            "not on the ground; georeference it first (Analyze > Imagery > "
            "Georeference) or add a file that says what its coordinates are"
        )


def choose_band(info, values=None):
    """Return the band to send to GRASS, 1-based, and why.

    ``share.exportRaster`` writes one band of a raster that is not a colour
    one, its first unless told otherwise, so a module would silently see band
    1 of a hyperspectral cube. The panel's slider names the band instead.

    :param info: what ``raster.info`` answered
    :return: ``(band or None, note or None)``
    """
    bands = len((info or {}).get("bands") or [])
    if bands <= 1:
        return None, None
    chosen = int((values or {}).get("band") or 1)
    chosen = min(max(chosen, 1), bands)
    names = [b.get("name") for b in info["bands"]]
    label = names[chosen - 1] or f"band {chosen}"
    return chosen, (
        f"The raster has {bands} bands; band {chosen} ({label}) went to GRASS. "
        "The panel's band slider chooses another."
    )


def band_slider(info):
    """Return the panel item that lets the band be chosen, for ``raster.info``.

    A slider's ends come from the manifest but a command may answer new ones
    (docs/plugins.md > A panel), so the slider covers exactly the bands the
    chosen raster has and carries their names.
    """
    bands = (info or {}).get("bands") or []
    if len(bands) <= 1:
        return {"min": 1, "max": 1, "labels": ["the only band"], "enabled": False}
    labels = [str(b.get("name") or f"band {i}") for i, b in enumerate(bands, 1)]
    return {"min": 1, "max": len(bands), "labels": labels, "enabled": True}


def source_notes(info, export=None):
    """Return what to say about the raster that went to GRASS.

    :param info: what ``raster.info`` answered
    :param export: what ``share.exportRaster`` answered: it names the overview
        it wrote when the layer RustGIS holds is a downsampled one, which a
        module would otherwise be run on without anybody being told
    """
    notes = []
    info = info or {}
    if info:
        cell = info.get("cellSize") or []
        size = f"{cell[0]:g} by {cell[1]:g}" if len(cell) == 2 else "unknown"
        notes.append(
            f"Source: {info.get('width', '?')} by {info.get('height', '?')} cells of "
            f"{size} in {info.get('crs') or 'an unnamed coordinate system'}, "
            f"{info.get('dataType') or 'unknown'} values."
        )
    full = (export or {}).get("overviewOf")
    if full and len(full) == 2:
        notes.append(
            f"RustGIS holds a {export.get('width')} by {export.get('height')} overview "
            f"of this {full[0]} by {full[1]} raster, and that overview is what GRASS "
            "ran on: the result is coarser than the file on disk."
        )
    return notes


def choose_raster(layers, chosen=None):
    """Return the raster layer to work on.

    :param layers: what ``host.layers`` answered
    :param chosen: the id of the layer picked in the panel, if any
    :return: that layer's entry
    :raises session.GrassError: when there is nothing to work on, or nothing
        says which raster of several to take
    """
    rasters = [layer for layer in layers if layer.get("raster")]
    if not rasters:
        raise session.GrassError(
            "the map has no raster layer; add one (Home > Add > Add Data) and "
            "choose it in the GRASS Raster panel"
        )
    if chosen is not None:
        for layer in rasters:
            if str(layer.get("id")) == str(chosen):
                return layer
        raise session.GrassError(
            f"the raster chosen in the panel is no longer on the map; it lists "
            f"{', '.join(str(layer.get('name')) for layer in rasters)}"
        )
    active = [layer for layer in rasters if layer.get("active")]
    if active:
        return active[0]
    if len(rasters) == 1:
        return rasters[0]
    raise session.GrassError(
        "the map has several raster layers and none is active; choose one in the "
        f"GRASS Raster panel ({', '.join(str(layer.get('name')) for layer in rasters)})"
    )


def raster_nodes(layers):
    """Return the panel tree's nodes: one per raster layer of the map."""
    return [
        {"id": str(layer.get("id")), "label": str(layer.get("name") or layer.get("id"))}
        for layer in layers
        if layer.get("raster")
    ]


def module_args(command, values, point=None):
    """Return the module's arguments, and what to say about them.

    The input raster is always ``src`` and the output always ``out``; the
    caller names the files.

    :param command: the local command id, a key of :data:`OPERATIONS`
    :param values: the panel's widget values
    :param point: the viewing position in the project's own coordinates,
        as ``(east, north)``
    :return: ``(argv, [note, ...])``
    :raises session.GrassError: for a command with no operation, or a viewshed
        with nowhere to look from
    """
    operation = OPERATIONS.get(command)
    if not operation:
        raise session.GrassError(f"no GRASS raster module is mapped to '{command}'")
    values = values or {}
    notes = []

    if command == "raster-slope":
        unit = "percent" if values.get("percent") else "degrees"
        notes.append(f"Slope is reported in {unit}.")
        return ["elevation=src", "slope=out", f"format={unit}"], notes

    if command == "raster-aspect":
        notes.append(
            "Aspect is degrees clockwise from north, with flat cells at -9999 "
            "(r.slope.aspect's -n)."
        )
        return ["elevation=src", "aspect=out", "-n"], notes

    if point is None:
        raise session.GrassError("the viewshed has no viewing position")
    east, north = point
    height = float(values.get("height", 2) or 0)
    distance = float(values.get("maxdist", 0) or 0)
    argv = [
        "input=src",
        "output=out",
        f"coordinates={east:.6f},{north:.6f}",
        f"observer_elevation={height:g}",
        "-b",
    ]
    if distance > 0:
        argv.append(f"max_distance={distance * METRES_PER_KM:g}")
        notes.append(f"Visibility is cut off at {distance:g} km.")
    else:
        notes.append("Visibility is not cut off by distance.")
    if values.get("curvature"):
        argv.append("-c")
        notes.append("The curvature of the earth is taken into account.")
    notes.append(
        f"The viewer stands {height:g} m above the ground at the centre of the map. "
        "Visible cells are 1 and invisible ones 0 (r.viewshed's -b)."
    )
    return argv, notes


#: The tree branches a module node can sit under. A module appears in more
#: than one branch, so its id carries the branch and stays unique in the tree.
NODE_PREFIXES = ("runs/", "all/", "recent/")

#: The catalogue modes the panel's mode tree offers, and the family each keeps.
MODE_FAMILIES = {
    "mode/all": None,
    "mode/imagery": "Imagery",
    "mode/temporal": "Temporal",
}


def mode_family(mode):
    """Return the family a mode tree node shows, or None for every module."""
    return MODE_FAMILIES.get(str(mode or ""), None)


def mode_nodes(catalogue):
    """Return the panel tree's catalogue modes, with how many modules each holds."""
    counts = {}
    for entry in catalogue:
        counts[entry["family"]] = counts.get(entry["family"], 0) + 1
    return [
        {"id": "mode/all", "label": "All modules", "count": len(catalogue)},
        {
            "id": "mode/imagery",
            "label": "Imagery",
            "count": counts.get("Imagery", 0),
        },
        {
            "id": "mode/temporal",
            "label": "Temporal",
            "count": counts.get("Temporal", 0),
        },
    ]

#: How many modules the "Recently run" branch keeps.
MAX_RECENT = 12

#: The name of the file that remembers them, in the cache beside the results.
RECENT_FILE = "recent.json"


def module_of(node):
    """Return the module a panel tree node names, without its branch prefix."""
    text = str(node or "")
    for prefix in NODE_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :]
    return text


def _clip(text, limit=200):
    """Keep a tree label within the 200 characters RustGIS allows."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _module_label(entry):
    """Return one tree label: whether it runs, its name, summary and keywords."""
    runs = (
        entry.get("runnable")
        or entry.get("mapset_runnable")
        or entry.get("render_runnable")
    )
    mark = "▸ " if runs else "  "
    text = f"{mark}{entry['module']}"
    if entry.get("mapset_runnable") and not entry.get("runnable"):
        text += " [in a chosen mapset]"
    if (
        entry.get("render_runnable")
        and not entry.get("runnable")
        and not entry.get("mapset_runnable")
    ):
        text += " [renders a picture]"
    if entry.get("summary"):
        text += f" — {entry['summary']}"
    if entry.get("keywords"):
        text += f" — {entry['keywords']}"
    if not runs and entry.get("reason"):
        text += f" [{entry['reason']}]"
    return _clip(text)


def _family_nodes(catalogue, prefix):
    """Return family branches holding ``prefix``'s module nodes."""
    families = {}
    for entry in catalogue:
        families.setdefault(entry["family"], []).append(entry)
    nodes = []
    for family in sorted(families):
        entries = sorted(families[family], key=lambda e: e["module"])
        nodes.append(
            {
                "id": f"{prefix}family/{family}",
                "label": family,
                "count": len(entries),
                "children": [
                    {
                        "id": f"{prefix}{entry['module']}",
                        "label": _module_label(entry),
                    }
                    for entry in entries
                ],
            }
        )
    return nodes


def catalogue_tree(catalogue, chosen=None, recent=(), family=None):
    """Return the panel tree of every module installed, in three branches.

    "Runs from here" holds the modules Run Module can actually drive on one
    raster, "All modules" holds every installed module with the reason the
    others need a form, and "Recently run" is a short way back to one. A tree
    holds 5,000 nodes; the three branches hold about 1,300.

    :param catalogue: the entries ``generate_manifest.py`` wrote
    :param chosen: the module to open the tree on, if any
    :param recent: module names to list under "Recently run", newest first
    :param family: keep only this GRASS family, as the panel's mode tree asks
    :return: ``(nodes, [note, ...])``
    """
    if family:
        catalogue = [entry for entry in catalogue if entry["family"] == family]
    runs = [
        entry
        for entry in catalogue
        if entry.get("runnable")
        or entry.get("mapset_runnable")
        or entry.get("render_runnable")
    ]
    all_label = f"All {family.lower()} modules" if family else "All modules"
    nodes = [
        {
            "id": "branch/runs",
            "label": f"Runs from here ({len(runs)})",
            "count": len(runs),
            "children": _family_nodes(runs, "runs/"),
        },
        {
            "id": "branch/all",
            "label": f"{all_label} ({len(catalogue)})",
            "count": len(catalogue),
            "children": _family_nodes(catalogue, "all/"),
        },
    ]
    by_name = {entry["module"]: entry for entry in catalogue}
    entries = [by_name[name] for name in recent if name in by_name]
    nodes.append(
        {
            "id": "branch/recent",
            "label": f"Recently run ({len(entries)})",
            "count": len(entries),
            "children": [
                {
                    "id": f"recent/{entry['module']}",
                    "label": _module_label(entry),
                }
                for entry in entries
            ],
        }
    )
    notes = []
    if chosen:
        entry = entry_for(catalogue, chosen, quietly=True)
        if entry and not entry.get("runnable"):
            if entry.get("mapset_runnable"):
                notes.append(
                    f"{entry['module']} runs with the form above in the GRASS "
                    "project and mapset chosen under Projects and mapsets."
                )
            elif entry.get("render_runnable"):
                notes.append(
                    f"{entry['module']} renders a picture from the form above: "
                    "choose its raster or vector layers, then the result is a "
                    "new raster layer of colours rather than data values."
                )
            else:
                notes.append(
                    f"{entry['module']} cannot be run from this panel: "
                    f"{entry.get('reason') or 'it needs a form'}. "
                    "Run Module names only one raster in and one out; every "
                    "other parameter would be GRASS's default."
                )
    return nodes, notes


def entry_for(catalogue, module, quietly=False):
    """Return one module's catalogue entry.

    :param module: a module name, or a tree node id carrying a branch prefix
    :raises session.GrassError: when the tree holds no such module
    """
    name = module_of(module)
    for entry in catalogue:
        if entry["module"] == name:
            return entry
    if quietly:
        return None
    raise session.GrassError(
        "choose a module in the GRASS Modules tree, not a family or a branch"
        if name.startswith(("family/", "branch/"))
        else f"'{module}' is not a module of this GRASS installation"
    )


def module_details(entry):
    """Return the text under the tree saying what the chosen module needs.

    This is where a module that cannot be run stops being a dead end: its
    reason is stated rather than hidden behind a button that would fail.
    """
    if not entry:
        return (
            "Choose a module in the tree above. 'Runs from here' holds the "
            "ones this panel can drive; 'All modules' says why the others "
            "need a form."
        )
    lines = [entry["module"]]
    if entry.get("summary"):
        lines.append(entry["summary"])
    if entry.get("family"):
        lines.append(f"Family: {entry['family']}")
    reads = entry.get("raster_in") or []
    writes = entry.get("raster_out") or []
    if reads:
        lines.append("Reads: " + ", ".join(reads))
    if writes:
        lines.append("Writes: " + ", ".join(writes))
    vector_reads = entry.get("vector_in") or []
    vector_writes = entry.get("vector_out") or []
    if vector_reads:
        lines.append("Reads (vector): " + ", ".join(vector_reads))
    if vector_writes:
        lines.append("Writes (vector): " + ", ".join(vector_writes))
    if entry.get("runnable"):
        lines.append(
            "Runs here; the form above sets its parameters, GRASS's defaults "
            "until changed."
        )
    elif entry.get("mapset_runnable"):
        lines.append(
            "Runs here in a GRASS mapset: choose the project and mapset under "
            "Projects and mapsets, then Run Module runs the form's values "
            "there. GRASS's defaults are used until changed."
        )
    elif entry.get("render_runnable"):
        lines.append(
            "Renders a picture: the form above chooses its layers, and the "
            "result is a new raster layer holding the colours of the display "
            "module, not its input's values. Tick 'Keep the PNG preview' to "
            "also write the picture itself."
        )
    else:
        lines.append(
            "Not runnable from this panel: "
            + (entry.get("reason") or "it needs a form")
            + ". The form above shows the parameters it takes."
        )
    if entry.get("needs"):
        lines.append("Needs: " + ", ".join(entry["needs"]))
    if entry.get("temporal"):
        lines.append(
            "This is a temporal module: it reads a space-time dataset, not one "
            "raster."
        )
    if entry.get("keywords"):
        lines.append("Keywords: " + entry["keywords"])
    return "\n".join(lines)[:4000]


def recent_path():
    """Return the file that remembers the last modules run."""
    return os.path.join(output_dir(), RECENT_FILE)


def read_recents(limit=MAX_RECENT):
    """Return the module names most recently run, newest first."""
    try:
        with open(recent_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    names = []
    for item in data:
        if isinstance(item, str) and item and item not in names:
            names.append(item)
    return names[: max(0, limit)]


def remember(module, limit=MAX_RECENT):
    """Put a module at the front of the recently-run list and write it back.

    Failing to remember must never fail a run: the result is already on the
    map by then, and the list is a convenience.
    """
    names = [module] + [name for name in read_recents(limit * 2) if name != module]
    names = names[: max(1, limit)]
    temporary = ""
    try:
        path = recent_path()
        temporary = f"{path}.{os.getpid()}.tmp"
        with open(temporary, "w", encoding="utf-8") as f:
            json.dump(names, f)
        os.replace(temporary, path)
    except OSError:
        if temporary:
            try:
                os.remove(temporary)
            except OSError:
                pass
    return names


def free_module_args(entry):
    """Return the arguments for running one module on ``src`` into ``out``.

    Only a module that reads one raster and writes one can be driven this way:
    the bridge names its input and its output and leaves every other parameter
    at GRASS's own default, because a command has no form to ask with. The
    input is the one the module requires, which is not always the first it
    lists (r.watershed lists five optional inputs after its elevation).

    :raises session.GrassError: when the module needs more than one raster in
        or out, an imagery group, or another required parameter with no default
    """
    if not entry.get("runnable"):
        reason = entry.get("reason") or "it needs a form"
        raise session.GrassError(
            f"{entry['module']} cannot be run from this panel: {reason}. "
            "Run Module names only one raster in and one out; the modules it "
            "can drive are under 'Runs from here'."
        )
    source = entry.get("raster_input") or (entry.get("raster_in") or [None])[0]
    target = entry.get("raster_output") or (entry.get("raster_out") or [None])[0]
    if not source or not target:
        raise session.GrassError(
            f"{entry['module']} has no single input and output the bridge can name"
        )
    return [f"{source}=src", f"{target}=out"]


def form_of(entry):
    """Return the fields the panel's form shows for one module, if any."""
    return (entry or {}).get("form") or []


def form_args(entry, values):
    """Return GRASS arguments for the form fields the user set.

    Only fields the module's own form declares are read: a checkbox set to
    true is its flag, a choice must be one the module offers, a ``multi``
    field is its choices joined by commas, and an empty text field is left
    out so GRASS keeps its own default.

    :param entry: a catalogue entry, whose ``form`` names its fields
    :param values: the panel's form value, ``{field id: value}``
    :return: a list of ``name=value`` and ``-flag`` arguments
    """
    fields = {f["id"]: f for f in form_of(entry)}
    args = []
    for name, value in (values or {}).items():
        field = fields.get(name)
        if not field:
            continue
        kind = field.get("kind")
        if kind == "checkbox":
            if value is True:
                args.append(f"-{name.removeprefix('flag_')}")
            continue
        if kind == "multi":
            if isinstance(value, str):
                parts = value.split(",")
            elif isinstance(value, list):
                parts = value
            else:
                continue
            choices = field.get("choices") or []
            picked = [
                str(p).strip()
                for p in parts
                if str(p).strip() and str(p).strip() in choices
            ]
            if picked:
                args.append(f"{name}={','.join(picked)}")
            continue
        if kind == "select":
            text = str(value)
            if text and text in (field.get("choices") or []):
                args.append(f"{name}={text}")
            continue
        if kind == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            args.append(f"{name}={int(value) if field.get('integer') else value}")
            continue
        text = str(value)
        if text:
            args.append(f"{name}={text}")
    return args


def missing_form_values(entry, values):
    """Return the required form fields that hold no usable value.

    A field with a default can be left empty: GRASS itself fills it. Every
    other required field has to hold something the module accepts before the
    run starts, so the error names the field instead of waiting for GRASS.

    :param entry: a catalogue entry, whose ``form`` names its fields
    :param values: the panel's form value, ``{field id: value}``
    :return: the missing field ids, in the form's own order
    """
    values = values or {}
    missing = []
    for field in form_of(entry):
        if not field.get("required") or "default" in field:
            continue
        name = field["id"]
        value = values.get(name)
        kind = field.get("kind")
        if kind == "checkbox":
            good = value is True
        elif kind == "multi":
            parts = value.split(",") if isinstance(value, str) else value
            choices = field.get("choices") or []
            good = isinstance(parts, list) and any(
                str(p).strip() in choices for p in parts
            )
        elif kind == "select":
            good = str(value or "") in (field.get("choices") or [])
        elif kind == "number":
            good = not isinstance(value, bool) and isinstance(value, (int, float))
            if good and field.get("integer"):
                good = float(value).is_integer()
        else:
            good = bool(str(value or "").strip())
        if not good:
            missing.append(name)
    return missing


#: The form's own checkbox for keeping the picture the display module drew.
PREVIEW_FIELD = "preview_png"


def _map_names(maps, kind):
    """Return the names of the ``kind`` maps in a ``[(kind, name), ...]`` list."""
    return [name for map_kind, name in (maps or []) if map_kind == kind]


def _with_form(values):
    """Return the panel values with a nested ``form`` mapping merged in.

    The host keeps every form field under ``form``, while the raster tree's
    choice and the band slider are beside it. Either shape is accepted, so a
    caller can pass the panel's values as they arrived.
    """
    values = values or {}
    form = values.get("form")
    if isinstance(form, dict):
        return {**values, **form}
    return values


def _map_fields(inputs, maps, mapset=None):
    """Return one form field for each map a module reads.

    :param inputs: ``render_inputs`` or ``mapset_inputs``
    :param maps: ``database.maps``, the chosen mapset's ``[(kind, name), ...]``
    :param mapset: the chosen mapset's name, for a missing-kind message
    """
    where = f"the {mapset} mapset" if mapset else "the chosen mapset"
    fields = []
    for port in inputs or []:
        kind = port.get("kind")
        choices = _map_names(maps, kind)
        label = interface._short_label(port.get("label") or port.get("name") or "")
        help_text = port.get("help") or ""
        if not choices:
            # Keep the field visible when the mapset has no map of that kind:
            # hiding it leaves only the flags and no clue why they are alone.
            missing = f"(no {kind} maps in {where})"
            if port.get("multiple"):
                field = {
                    "id": port["name"],
                    "kind": "multi",
                    "label": label,
                    "choices": [missing],
                }
            else:
                field = {
                    "id": port["name"],
                    "kind": "select",
                    "label": label,
                    "choices": [missing],
                }
            if port.get("required"):
                field["required"] = True
            field["help"] = (
                (help_text + " " if help_text else "")
                + f"Choose a {kind} map from the mapset selected under "
                "Projects and mapsets."
            )[:2000]
            fields.append(field)
            continue
        if port.get("multiple"):
            field = {
                "id": port["name"],
                "kind": "multi",
                "label": label,
                "choices": choices[:256],
            }
            if help_text:
                field["help"] = help_text[:2000]
            if port.get("required"):
                field["required"] = True
            elif len(choices) == 1:
                field["default"] = [choices[0]]
            fields.append(field)
            continue
        values = choices if port.get("required") else ["none"] + choices
        field = {
            "id": port["name"],
            "kind": "select",
            "label": label,
            "choices": values[:256],
        }
        if help_text:
            field["help"] = help_text[:2000]
        if port.get("required"):
            field["required"] = True
            if len(choices) == 1:
                field["default"] = choices[0]
        else:
            field["default"] = "none"
        fields.append(field)
    return fields


def _with_module_form(entry, inputs, maps, mapset):
    """Return the map fields followed by the module's own form fields."""
    fields = _map_fields(inputs, maps, mapset)
    named = {port["name"] for port in inputs or []}
    fields += [field for field in form_of(entry) if field["id"] not in named]
    return fields[: interface.MAX_FORM_FIELDS]


def render_form(entry, maps, mapset=None):
    """Return the form fields for a display module that renders a picture.

    The module's own parameters are kept, and one field is added for each map
    input the module declares. The choices are the maps of one GRASS mapset,
    because a display module reads maps from the project's database, not the
    RustGIS project's layers.

    :param entry: a catalogue entry with ``render_inputs``
    :param maps: ``database.maps``, the chosen mapset's ``[(kind, name), ...]``
    :param mapset: the chosen mapset's name, for a missing-kind message
    :return: the fields the panel shows
    """
    fields = _with_module_form(
        entry, (entry or {}).get("render_inputs"), maps, mapset
    )
    fields = fields[: interface.MAX_FORM_FIELDS - 1]
    fields.append(
        {
            "id": PREVIEW_FIELD,
            "kind": "checkbox",
            "label": "Keep the PNG preview beside the GeoTIFF",
            "help": (
                "RustGIS loads the GeoTIFF as a new layer. Tick this to also "
                "keep the picture the display module drew, on disk."
            ),
            "default": False,
        }
    )
    return fields


def mapset_form(entry, maps, mapset=None):
    """Return a mapset module's form, with a field for each map it reads.

    A module such as ``r.colors`` changes a map of the chosen mapset rather
    than writing a new one, so its map parameters are choices from that
    mapset. The module's own parameters follow them.
    """
    return _with_module_form(
        entry, (entry or {}).get("mapset_inputs"), maps, mapset
    )


def _map_ports(entry, inputs, values, maps, mapset=None):
    """Resolve a module's map fields into the maps of the chosen mapset."""
    values = _with_form(values)
    by_kind = {
        kind: set(_map_names(maps, kind)) for kind in ("raster", "vector")
    }
    ports, missing = [], []
    for port in inputs or []:
        name, kind = port["name"], port.get("kind")
        raw = values.get(name)
        if port.get("multiple"):
            parts = raw.split(",") if isinstance(raw, str) else (raw or [])
            names = [
                str(part).strip()
                for part in parts
                if str(part).strip() and str(part).strip() != "none"
            ]
        else:
            text = str(raw or "").strip()
            names = [text] if text and text != "none" else []
        picked = []
        for text in names:
            if text not in by_kind.get(kind, set()):
                where = f"the {mapset} mapset" if mapset else "the chosen mapset"
                raise session.GrassError(
                    f"{entry['module']}: {text} is not a {kind} map of {where}"
                )
            picked.append(text)
        if not picked and port.get("required"):
            missing.append(port.get("label") or name)
        if picked:
            ports.append(
                {
                    "name": name,
                    "kind": kind,
                    "multiple": bool(port.get("multiple")),
                    "maps": picked,
                }
            )
    return ports, missing


def render_plan(entry, values, maps, mapset=None):
    """Resolve a display module's form into the maps it will draw.

    Every input must name a map of the same mapset: a display module reads
    GRASS maps, and its choices come from the mapset selected under Projects
    and mapsets.

    :param entry: a catalogue entry with ``render_inputs``
    :param values: the panel's form values
    :param maps: ``database.maps``, the chosen mapset's ``[(kind, name), ...]``
    :param mapset: the chosen mapset's name, for error messages
    :return: ``(ports, preview)``, where each port is
        ``{"name", "kind", "multiple", "maps"}`` and ``preview`` says
        whether to keep the PNG
    :raises session.GrassError: when a required input is missing or names no
        map of the chosen mapset
    """
    ports, missing = _map_ports(
        entry, (entry or {}).get("render_inputs"), values, maps, mapset
    )
    if missing:
        raise session.GrassError(
            f"{entry['module']} needs {', '.join(missing)} before it can render"
        )
    if not ports:
        raise session.GrassError(f"{entry['module']} needs a map to draw")
    return ports, bool(_with_form(values).get(PREVIEW_FIELD))


def mapset_plan(entry, values, maps, mapset=None):
    """Resolve a mapset module's map fields into that mapset's maps.

    :return: ``[{"name", "kind", "multiple", "maps"}, ...]``, empty when the
        module's map inputs are all optional and left empty
    :raises session.GrassError: when a required map is missing or names no
        map of the chosen mapset
    """
    ports, missing = _map_ports(
        entry, (entry or {}).get("mapset_inputs"), values, maps, mapset
    )
    if missing:
        raise session.GrassError(
            f"{entry['module']} needs {', '.join(missing)} before it can run"
        )
    return ports


def render_args(entry, values, imported):
    """Return a display module's arguments for the imported layers.

    :param entry: a catalogue entry with ``render_inputs``
    :param values: the panel's form values
    :param imported: ``{port name: [GRASS map name, ...]}``
    :return: a list of ``name=value`` and ``-flag`` arguments
    """
    values = _with_form(values)
    ports = {port["name"] for port in (entry.get("render_inputs") or [])}
    form_values = {
        name: value
        for name, value in values.items()
        if name not in ports and name != PREVIEW_FIELD
    }
    args = []
    for port in entry.get("render_inputs") or []:
        maps = imported.get(port["name"]) or []
        if maps:
            args.append(f"{port['name']}={','.join(maps)}")
    args += form_args(entry, form_values)
    # Without -d, d.title only prints the title it would draw.
    if entry.get("module") == "d.title" and "-d" not in args:
        args.append("-d")
    # d.vect.thematic takes either an algorithm or explicit class breaks;
    # neither is required on its own, so name the default when neither is set.
    if entry.get("module") == "d.vect.thematic":
        named = {arg.split("=", 1)[0] for arg in args if "=" in arg}
        if "algorithm" not in named and "breaks" not in named:
            args.append("algorithm=int")
    return args


def output_dir():
    """Return the folder the results are written to, created if need be.

    The GeoTIFF has to outlive the run: RustGIS reads it when the layer is
    added, and keeps the path for the project.  So results go to the user's
    cache rather than to a temporary folder that is swept away.
    """
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = os.path.join(base, "rustgis-grass-plugin")
    os.makedirs(path, exist_ok=True)
    return path


def output_path(layer, suffix):
    """Return a free path for one result, named after its input and operation."""
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(layer))[:48]
    folder = output_dir()
    for attempt in range(1000):
        tail = "" if attempt == 0 else f"_{attempt}"
        path = os.path.join(folder, f"{stem}_{suffix}{tail}.tif")
        if not os.path.exists(path):
            return path
    raise session.GrassError(f"cannot find a free name for a result in {folder}")


class RasterRun(session.Run):
    """One raster module run, inside the time RustGIS gives a command."""

    def __init__(self, grass=None, progress=None, budget=None):
        budget = session.COMMAND_LIMIT if budget is None else budget
        super().__init__(
            grass=grass, progress=progress, deadline=time.monotonic() + budget
        )

    def raster_tool(self, command, source, target, values=None, centre=None, env=None):
        """Run one raster module over a GeoTIFF and write another.

        :param command: the local command id, a key of :data:`OPERATIONS`
        :param source: the exported input GeoTIFF
        :param target: where to write the result
        :param values: the panel's widget values
        :param centre: the map's centre as ``(longitude, latitude)``, for a
            module that works from a point
        :param env: RustGIS's Analysis Environment, as ``gp.env`` answers it:
            ``{"extent": [w, s, e, n], "cellSize": degrees}``
        :return: ``[message, ...]``
        :raises session.GrassError: when any step fails
        """
        operation = OPERATIONS.get(command)
        if not operation:
            raise session.GrassError(f"no GRASS raster module is mapped to '{command}'")
        module = operation["module"]

        self.progress("Preparing a working project...")
        # The project takes the raster's own coordinate system, so the module
        # works in the units the data is in and the result needs no projecting.
        project = self._project("raster", source)
        proj = " ".join(
            self.exec(project, "g.proj", "-p", "-f", "format=proj4").split()
        )

        self.progress("Importing the raster...")
        self.exec(
            project,
            "r.in.gdal",
            f"input={source}",
            "output=src",
            "--overwrite",
            "--quiet",
        )
        # The computational region, not the input, decides what a module reads
        # and writes. A new project's region is a single cell at the origin.
        self.exec(project, "g.region", "raster=src")
        region = self._region(project)
        region, region_notes, narrowed = self._apply_environment(
            project, region, proj, env, (values or {}).get("res")
        )

        point = None
        if centre is not None and module == "r.viewshed":
            point = self._project_point(project, centre, region)

        argv, notes = module_args(command, values, point)
        if narrowed and module == "r.slope.aspect":
            # Otherwise it puts the region back on the elevation map's own grid
            # and the region asked for is silently ignored.
            argv.append("-a")
        self.progress(f"Running {module}...")
        self.exec(project, module, *argv, "--overwrite", "--quiet")

        self.progress("Writing the result...")
        self.exec(
            project,
            "r.out.gdal",
            "input=out",
            f"output={target}",
            "format=GTiff",
            # A colour table GDAL cannot hold in a float GeoTIFF is an error
            # from GDAL itself; the data matters here, not GRASS's colours.
            "-c",
            "--overwrite",
            "--quiet",
        )
        if not os.path.exists(target):
            raise session.GrassError(f"{module} wrote no file at {target}")

        where = proj or "the raster's own projection"
        messages = [f"{module} ran in {where}."]
        if region:
            messages.append(
                "Computational region used: "
                f"{region.get('cols', '?')} by {region.get('rows', '?')} cells of "
                f"{region.get('ewres', '?')} by {region.get('nsres', '?')}, "
                f"{float(region.get('w', 0)):.0f} to {float(region.get('e', 0)):.0f} east, "
                f"{float(region.get('s', 0)):.0f} to {float(region.get('n', 0)):.0f} north."
            )
        messages += region_notes
        messages += notes
        for text, count in self.warnings.items():
            messages.append(
                f"GRASS: {text}" + (f" ({count} times)" if count > 1 else "")
            )
        return messages

    def free_module(self, module, argv, source, target, env=None):
        """Run any raster module over a GeoTIFF, with its own defaults.

        The same round trip as :meth:`raster_tool`, for a module the bridge
        knows nothing about beyond which parameter takes its raster and which
        names its output.

        :param module: the GRASS module
        :param argv: its input and output arguments
        :return: ``[message, ...]``
        :raises session.GrassError: when any step fails
        """
        self.progress("Preparing a working project...")
        project = self._project("raster", source)
        proj = " ".join(
            self.exec(project, "g.proj", "-p", "-f", "format=proj4").split()
        )
        self.progress("Importing the raster...")
        self.exec(
            project,
            "r.in.gdal",
            f"input={source}",
            "output=src",
            "--overwrite",
            "--quiet",
        )
        self.exec(project, "g.region", "raster=src")
        region = self._region(project)
        region, region_notes, _ = self._apply_environment(
            project, region, proj, env, None
        )

        self.progress(f"Running {module}...")
        self.exec(project, module, *argv, "--overwrite", "--quiet")
        self.progress("Writing the result...")
        self.exec(
            project,
            "r.out.gdal",
            "input=out",
            f"output={target}",
            "format=GTiff",
            "-c",
            "--overwrite",
            "--quiet",
        )
        if not os.path.exists(target):
            raise session.GrassError(f"{module} wrote no file at {target}")

        where = proj or "the raster's own projection"
        messages = [f"{module} ran in {where}, with GRASS's own defaults."]
        if region:
            messages.append(
                "Computational region used: "
                f"{region.get('cols', '?')} by {region.get('rows', '?')} cells of "
                f"{region.get('ewres', '?')} by {region.get('nsres', '?')}."
            )
        messages += region_notes
        messages.append(
            f"Only {argv[0].split('=')[0]} and {argv[1].split('=')[0]} were set; "
            "every other parameter is GRASS's default, because a command has no "
            "form to ask with."
        )
        for text, count in self.warnings.items():
            messages.append(
                f"GRASS: {text}" + (f" ({count} times)" if count > 1 else "")
            )
        return messages

    def _apply_environment(self, project, region, proj, env, res):
        """Narrow the region to RustGIS's Analysis Environment and the panel.

        The region, not the input, decides what a GRASS raster module reads and
        writes, so this is where **Analyze > Geoprocessing > Environments**
        reaches GRASS: its extent becomes the region's bounds and its cell size
        the resolution. The panel's own cell size wins over both.

        :param region: the region taken from the raster
        :param proj: the project's PROJ.4 description
        :param env: ``gp.env``'s answer, or None
        :param res: the panel's cell size, in the project's units, or 0
        :return: ``(region, [note, ...], narrowed)``
        :raises session.GrassError: when nothing of the raster is left
        """
        env = env or {}
        extent = env.get("extent")
        cell = env.get("cellSize")
        notes, narrowed = [], False
        degrees = "+proj=longlat" in proj

        if extent and len(extent) == 4:
            box = self._box(project, extent, region)
            self.exec(
                project,
                "g.region",
                f"n={box['n']:.6f}",
                f"s={box['s']:.6f}",
                f"e={box['e']:.6f}",
                f"w={box['w']:.6f}",
                "align=src",
            )
            narrowed = True
            notes.append(
                "The region is the Analysis Environment's extent "
                f"({extent[0]:.5f}, {extent[1]:.5f}) to ({extent[2]:.5f}, {extent[3]:.5f}), "
                "clipped to the raster and aligned to its grid."
            )

        if res:
            self.exec(project, "g.region", f"res={float(res):g}", "-a")
            narrowed = True
            notes.append(f"Cell size {float(res):g} (the panel's), aligned to it.")
        elif cell:
            ns, ew, how = self._cell_size(project, cell, degrees, region)
            self.exec(project, "g.region", f"nsres={ns:.10g}", f"ewres={ew:.10g}", "-a")
            narrowed = True
            notes.append(
                f"Cell size from the Analysis Environment: {cell:g} degrees, {how}."
            )

        if narrowed:
            region = self._region(project)
            if region.get("cells") in ("0", None) or region.get("rows") == "0":
                raise session.GrassError(
                    "the region asked for leaves no cell of the raster; widen the "
                    "Analysis Environment's extent or move the map over the data"
                )
        else:
            notes.append(
                "The region is the whole raster: no extent or cell size is set in "
                "Analyze > Geoprocessing > Environments."
            )
        return region, notes, narrowed

    def _cell_size(self, project, cell, degrees, region):
        """Return ``(nsres, ewres, how)`` for a cell size given in degrees.

        The Analysis Environment states a cell size in degrees, which means
        nothing to a projected raster, so it is turned into that projection's
        units at the latitude of the region's centre. A degree of longitude
        shortens away from the equator; a degree of latitude does not.
        """
        if degrees:
            return cell, cell, "the raster is in degrees, so it is taken as it is"
        lat = self._centre_latitude(project, region)
        ns = cell * METRES_PER_DEGREE_LAT
        ew = cell * METRES_PER_DEGREE_LON * math.cos(math.radians(lat))
        how = (
            f"{ns:.1f} north-south by {ew:.1f} east-west in the raster's units, "
            f"at latitude {lat:.2f} degrees"
        )
        return ns, ew, how

    def _centre_latitude(self, project, region):
        """Return the latitude of the region's centre, or 0 when unreadable."""
        try:
            east = (float(region["w"]) + float(region["e"])) / 2.0
            north = (float(region["s"]) + float(region["n"])) / 2.0
        except (KeyError, ValueError):
            return 0.0
        try:
            out = self.exec(
                project,
                "m.proj",
                "-o",
                "-d",
                f"coordinates={east},{north}",
                "separator=comma",
            )
            return float(out.strip().splitlines()[0].split(",")[1])
        except (session.GrassError, IndexError, ValueError):
            return 0.0

    def _box(self, project, extent, region):
        """Return the longitude/latitude extent, projected and clipped.

        :raises session.GrassError: when it does not meet the raster
        """
        west, south, east, north = (float(v) for v in extent)
        corners = [
            (west, south),
            (west, north),
            (east, south),
            (east, north),
            ((west + east) / 2.0, south),
            ((west + east) / 2.0, north),
        ]
        xs, ys = [], []
        for lon, lat in corners:
            out = self.exec(
                project,
                "m.proj",
                "-i",
                "-d",
                f"coordinates={lon},{lat}",
                "separator=comma",
            )
            parts = (out.strip().splitlines() or [""])[0].split(",")
            try:
                xs.append(float(parts[0]))
                ys.append(float(parts[1]))
            except (IndexError, ValueError) as e:
                raise session.GrassError(
                    "cannot put the Analysis Environment's extent into the raster's "
                    f"projection: m.proj answered {out.strip()!r}"
                ) from e
        try:
            box = {
                "w": max(min(xs), float(region["w"])),
                "e": min(max(xs), float(region["e"])),
                "s": max(min(ys), float(region["s"])),
                "n": min(max(ys), float(region["n"])),
            }
        except (KeyError, ValueError) as e:
            raise session.GrassError("the raster has no readable region") from e
        if box["w"] >= box["e"] or box["s"] >= box["n"]:
            raise session.GrassError(
                "the Analysis Environment's extent does not meet the raster; widen "
                "it, or set it to the layer (Analyze > Geoprocessing > Environments)"
            )
        return box

    def _project_point(self, project, centre, region):
        """Return the map's centre in the project's coordinates.

        :param centre: ``(longitude, latitude)``
        :raises session.GrassError: when it cannot be converted, or falls
            outside the raster
        """
        lon, lat = centre
        out = self.exec(
            project, "m.proj", "-i", "-d", f"coordinates={lon},{lat}", "separator=comma"
        )
        parts = (out.strip().splitlines() or [""])[0].split(",")
        try:
            east, north = float(parts[0]), float(parts[1])
        except (IndexError, ValueError) as e:
            raise session.GrassError(
                f"cannot put the map's centre ({lon:.5f}, {lat:.5f}) into the raster's "
                f"projection: m.proj answered {out.strip()!r}"
            ) from e
        try:
            inside = float(region["w"]) <= east <= float(region["e"]) and float(
                region["s"]
            ) <= north <= float(region["n"])
        except (KeyError, ValueError):
            inside = True
        if not inside:
            raise session.GrassError(
                f"the centre of the map ({lon:.5f}, {lat:.5f}) is outside the raster; "
                "move the map over it first"
            )
        return east, north
