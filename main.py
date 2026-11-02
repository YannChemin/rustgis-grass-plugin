"""A RustGIS process plugin that runs GRASS GIS modules.

RustGIS starts this program once per call and speaks one JSON object per line
over standard input and output (see RustGIS docs/plugins.md). GRASS itself is
never linked: each run spawns the user's own installation.

Vector modules are geoprocessing tools: RustGIS hands them the layer's
features as GeoJSON and takes the result back the same way. Raster modules are
commands instead, because a tool gets no raster and makes no host requests;
a command asks RustGIS to export the layer and to add the result back (see
grass_bridge/raster.py).

Progress goes to RustGIS as {"progress": ...} lines, and GRASS modules report
their own percentages to MetaMonitor through its GRASS hook
(https://github.com/YannChemin/MetaMonitor).

SPDX-License-Identifier: Unlicense
"""

import json
import os
import pathlib
import sys

from grass_bridge import database, raster, session

HERE = pathlib.Path(__file__).parent


def emit(obj):
    """Write one protocol line."""
    print(json.dumps(obj), flush=True)


def progress(text):
    """Tell RustGIS what the run is doing now."""
    emit({"progress": text})


def log(text):
    """Add a line to the log, and to a tool's run messages."""
    emit({"log": text})


def call(op, params=None):
    """Make one host request and return its answer.

    :param op: a host operation (``host.layers``) or any command id RustGIS
        lets this plugin run within its permissions
    :return: the ``ok`` value
    :raises session.GrassError: when RustGIS refuses the request, so the
        reason reaches the user instead of a traceback
    """
    emit({"call": {"op": op, "params": params or {}}})
    line = sys.stdin.readline()
    if not line.strip():
        raise session.GrassError(f"RustGIS gave no answer to '{op}'")
    try:
        reply = json.loads(line)
    except ValueError as e:
        raise session.GrassError(f"unreadable answer to '{op}': {e}") from e
    if "error" in reply:
        raise session.GrassError(f"{op}: {reply['error']}")
    return reply.get("ok")


def load_catalogue():
    """Return what generate_manifest.py read from the GRASS installation."""
    try:
        return json.loads((HERE / "modules.json").read_text())
    except (OSError, ValueError):
        return {}


def load_modules():
    """Return the tool id to GRASS module map the generator wrote."""
    return load_catalogue().get("modules") or {}


def load_raster_commands():
    """Return the command id to GRASS raster module map the generator wrote."""
    return load_catalogue().get("rasterCommands") or {}


def split_params(declared, given):
    """Split a tool's parameters into GRASS parameters and flags.

    A ``file`` parameter is left out here: its value is only the file's name,
    and the path GRASS reads is written by :func:`file_params` from the
    contents RustGIS sent with the request.

    :param declared: the tool's parameter list from the manifest
    :param given: what the user supplied
    :return: ``(params, flags)``
    """
    params, flags = {}, []
    for spec in declared:
        name = spec["name"]
        if name == "input" or spec.get("kind") == "file":
            continue
        value = given.get(name, None)
        if value is None or value == "":
            continue
        if name.startswith("flag_"):
            if value is True:
                flags.append(name[len("flag_") :])
            continue
        if isinstance(value, bool):
            continue
        params[name] = value
    return params, flags


def file_params(declared, req, run):
    """Write the tool's ``file`` parameters and return them for GRASS.

    RustGIS reads the file the user picked and sends its contents with the
    request (docs/plugins.md > File parameters), so the bridge never opens a
    path of its own: it writes what arrived into the run's folder and gives
    GRASS that path.

    :param declared: the tool's parameter list from the manifest
    :param req: the tool request
    :param run: the :class:`session.Run` whose folder the files go in
    :return: ``({name: path}, [message, ...])``
    """
    sent = req.get("files") or {}
    given = req.get("params") or {}
    params, messages = {}, []
    for spec in declared:
        if spec.get("kind") != "file":
            continue
        name = spec["name"]
        if name not in sent:
            if given.get(name):
                # The parameter holds the file's name and the contents come
                # beside it; a name with nothing behind it would otherwise be
                # dropped without a word.
                raise session.GrassError(
                    f"{name}: RustGIS sent no contents for '{given[name]}'; pick "
                    "the file again in the Tools pane"
                )
            if spec.get("required"):
                raise session.GrassError(
                    f"{name} is required: pick the file in the Tools pane"
                )
            continue
        path = run.input_file(name, sent[name])
        params[name] = path
        messages.append(
            f"{name}: read {sent[name].get('name') or path} "
            f"({os.path.getsize(path)} bytes) as RustGIS sent it."
        )
    return params, messages


def run_tool(req, modules):
    """Run one GRASS module for a tool request and return its ``ok`` value."""
    tool = req["id"]
    module = modules.get(tool)
    if not module:
        raise ValueError(f"no GRASS module is mapped to '{tool}'")
    manifest = json.loads((HERE / "plugin.json").read_text())
    declared = next((t["params"] for t in manifest["tools"] if t["id"] == tool), [])

    given = req.get("params") or {}
    layer = given.get("input")
    if not layer:
        raise ValueError("no input layer was given")
    geojson = (req.get("layers") or {}).get(layer)
    if geojson is None:
        raise ValueError(f"the input layer '{layer}' did not arrive with the request")

    params, flags = split_params(declared, given)
    with session.Run(progress=progress) as run:
        files, file_notes = file_params(declared, req, run)
        params.update(files)
        result, messages = run.vector_tool(module, geojson, params, flags)
    messages += file_notes

    shaped, messages = split_result(result, f"{layer} {module}", module, messages)
    return {**shaped, "messages": messages[:200]}


def split_result(result, name, module, messages):
    """Split a module's result into output layers and standalone tables.

    A GRASS vector can hold attributes with no geometry (v.distance's upload
    table, a module that writes only a table), and RustGIS takes those as
    ``tables`` rather than as a layer with nothing to draw
    (docs/plugins.md > The ABI). Both halves are reported, so neither is
    dropped in silence.

    :return: ``({"layers"?, "tables"?}, [message, ...])``
    """
    features = (result or {}).get("features") or []
    drawn = [f for f in features if (f or {}).get("geometry")]
    plain = [f for f in features if not (f or {}).get("geometry")]
    shaped = {}
    if drawn or not plain:
        shaped["layers"] = [{"name": name, "geojson": {**result, "features": drawn}}]
        messages.append(f"{module}: {len(drawn)} features written.")
    if plain:
        shaped["tables"] = [
            {"name": f"{name} table", "geojson": {**result, "features": plain}}
        ]
        messages.append(
            f"{module}: {len(plain)} rows had no geometry; they are a standalone "
            f"table, '{name} table', not a layer."
        )
    return shaped, messages


#: Said whenever the database is put in the browser: its folders hold GRASS's
#: own formats, which RustGIS has no reader for.
NOT_READABLE = (
    "A mapset's own files are in GRASS's formats, which RustGIS does not read; "
    "use Add Map to bring one in."
)


def database_panel(chosen=None, notes=()):
    """Return the panel items describing the GRASS database.

    :param chosen: the tree node chosen, which decides the mapset listed
    :param notes: lines to add under the tree
    """
    base = database.gisdbase()
    if not base:
        return {
            "gisdbase": {"text": "No GRASS database found."},
            "database": {"nodes": []},
        }
    nodes, more = database.tree(base, database.opened(chosen))
    count = sum(node.get("count", 0) for node in nodes)
    text = f"{base}\n{len(nodes)} projects, {count} maps"
    for line in list(more) + list(notes):
        text += f"\n{line}"
    return {"gisdbase": {"text": text}, "database": {"nodes": nodes}}


def browse_database(req):
    """Answer the tree again, with the chosen mapset's maps in it."""
    chosen = ((req.get("panel") or {}).get("values") or {}).get("database")
    return {"panel": {"items": database_panel(chosen), "values": {"database": chosen}}}


def add_folder(req):
    """Put the GRASS database in RustGIS's browser, under Folders.

    A plugin cannot add an entry to the Add Data menu; this is the nearest
    thing it can do, and it is the same folder GRASS itself uses.
    """
    base = database.gisdbase()
    if not base:
        raise session.GrassError(
            "no GRASS database was found: GISDBASE is not set, GRASS's settings "
            "file names none, and there is no ~/grassdata"
        )
    call("project.addFolder", {"path": base})
    call("host.notify", {"text": f"{base} is in the browser, under Folders."})
    return {
        "folder": base,
        "panel": {"items": database_panel()},
        "messages": [f"{base} added to the browser's Folders.", NOT_READABLE],
    }


def add_map(req):
    """Export the map chosen in the tree and add it to the project."""
    values = (req.get("panel") or {}).get("values") or {}
    base = database.gisdbase()
    if not base:
        raise session.GrassError("no GRASS database was found")
    kind, project, mapset, name = database.parse_node(values.get("database"))
    # A raster goes out as a GeoTIFF and a vector as a GeoPackage, which both
    # carry the coordinate system RustGIS then reads them in.
    target = raster.output_path(f"{project}_{mapset}", name)
    if kind == "vector":
        target = target[: -len(".tif")] + ".gpkg"

    with database.Export(progress=progress) as run:
        messages = run.export(base, kind, project, mapset, name, target)

    added = call("layer.addData", {"path": target, "name": f"{name}@{mapset}"})
    messages.append(f"The export is kept at {target}.")
    for text in messages:
        log(text)
    call("host.notify", {"text": f"{name}@{mapset} added from {project}."})
    return {
        "layer": added,
        "messages": messages,
        "panel": {"items": database_panel(values.get("database"))},
    }


def export_source(name, values):
    """Have RustGIS write the chosen raster layer, and say what went out.

    ``raster.info`` describes the layer before it leaves (its coordinate
    system, its cell size, how many bands it has) and ``share.exportRaster``
    says what it actually wrote, so a run on a downsampled overview or on one
    band of many is reported rather than passed off as the whole raster.

    :param name: the layer's name
    :param values: the panel's widget values
    :return: ``(path, [note, ...], info)``
    """
    info = call("raster.info", {"layer": name}) or {}
    raster.check_source(info, name)
    band, band_note = raster.choose_band(info, values)
    exported = os.path.join(raster.output_dir(), f".export-{os.getpid()}.tif")
    progress(f"Exporting {name}...")
    params = {"layer": name, "path": exported}
    if band:
        params["band"] = band
    written = call("share.exportRaster", params) or {}
    notes = raster.source_notes(info, written)
    if band_note:
        notes.append(band_note)
    return exported, notes, info


def run_module(req, module=None):
    """Run a raster module on the chosen raster layer.

    Every installed module is in the panel's tree, and the common ones have a
    ribbon command of their own (``module`` names that one). Either way only a
    module that reads a raster and writes one can be run: a command has no
    form, so the bridge names the input and the output and nothing else. A
    module that needs more than that has to be a tool, and a manifest holds 64
    of those.

    :param module: the GRASS module a curated command runs, or None to take
        the one chosen in the tree
    """
    values = (req.get("panel") or {}).get("values") or {}
    catalogue = load_catalogue().get("catalogue") or []
    entry = raster.entry_for(catalogue, module or values.get("modules"))
    argv = raster.free_module_args(entry)

    layers = call("host.layers") or []
    layer = raster.choose_raster(layers, values.get("raster"))
    name = str(layer.get("name"))
    env = call("gp.env", {}) or {}

    target = raster.output_path(name, entry["module"].replace(".", "-"))
    exported, source = export_source(name, values)[:2]
    try:
        with raster.RasterRun(progress=progress) as run:
            messages = run.free_module(entry["module"], argv, exported, target, env)
        messages += source
    finally:
        try:
            os.remove(exported)
        except OSError:
            pass

    added = call("layer.addData", {"path": target, "name": f"{name} {entry['module']}"})
    messages.append(f"The result is kept at {target}.")
    for text in messages:
        log(text)
    call("host.notify", {"text": f"{entry['module']}: {messages[0]}"})
    nodes, notes = raster.catalogue_tree(catalogue, entry["module"])
    return {
        "layer": added,
        "messages": messages + notes,
        "panel": {
            "items": {
                "modules": {"nodes": nodes},
                "status": {"text": "\n".join(messages)},
            }
        },
    }


def describe_region(env):
    """Return one line saying what region a run would use."""
    env = env or {}
    extent, cell = env.get("extent"), env.get("cellSize")
    where = (
        "Extent: {:.5f}, {:.5f} to {:.5f}, {:.5f}".format(*extent)
        if extent and len(extent) == 4
        else "Extent: the whole input raster"
    )
    size = f"Cell size: {cell:g} degrees" if cell else "Cell size: the raster's own"
    return f"{where}\n{size}"


def set_region(req, extent):
    """Set the Analysis Environment's extent and answer the panel.

    :param extent: ``"view"`` for the map view, or None for the whole layer
    """
    env = call("gp.env", {"extent": extent})
    told = "the map view" if extent == "view" else "the whole layer"
    text = describe_region(env)
    call("host.notify", {"text": f"Computational region: {told}."})
    return {
        "environment": env,
        "panel": {"items": {"region": {"text": text}}},
    }


def run_raster_command(req):
    """Run one GRASS raster module over a raster layer of the map.

    A tool could not do this: it gets no raster and makes no host requests.
    This command asks RustGIS to export the layer, works on the file, and asks
    it to add the result back. See ``grass_bridge/raster.py``.

    :param req: the command request
    :return: its ``ok`` value, the panel's new state included
    """
    command = req["id"]
    operation = raster.OPERATIONS[command]
    panel = req.get("panel") or {}
    values = panel.get("values") or {}

    layers = call("host.layers") or []
    nodes = raster.raster_nodes(layers)
    layer = raster.choose_raster(layers, values.get("raster"))
    name = str(layer.get("name"))
    # The computational region decides what a raster module reads and writes,
    # so RustGIS's own Analysis Environment is what sets it.
    env = call("gp.env", {}) or {}

    target = raster.output_path(name, operation["suffix"])
    centre = None
    if operation["module"] == "r.viewshed":
        view = call("host.view") or {}
        centre = tuple((view.get("center") or [None, None])[:2])
        if centre[0] is None:
            raise session.GrassError("RustGIS did not say where the map is centred")

    exported, source, info = export_source(name, values)
    try:
        with raster.RasterRun(progress=progress) as run:
            messages = run.raster_tool(command, exported, target, values, centre, env)
        messages += source
    finally:
        try:
            os.remove(exported)
        except OSError:
            pass

    added = call(
        "layer.addData", {"path": target, "name": f"{name} {operation['suffix']}"}
    )
    messages.append(f"The result is kept at {target}.")
    for text in messages:
        log(text)
    call("host.notify", {"text": f"{operation['label']}: {messages[0]}"})
    return {
        "layer": added,
        "messages": messages,
        "panel": {
            "values": {"raster": str(layer.get("id"))},
            "items": {
                "raster": {"nodes": nodes},
                "source": {"text": name},
                "band": raster.band_slider(info),
                "region": {"text": describe_region(env)},
                "status": {"text": "\n".join(messages)},
            },
        },
    }


def panel_state(req):
    """Answer the panel's state when it is opened.

    It reads the map only, so it is no undo step.
    """
    layers = call("host.layers") or []
    nodes = raster.raster_nodes(layers)
    values = (req.get("panel") or {}).get("values") or {}
    chosen = values.get("raster")
    if chosen is not None and not any(n["id"] == str(chosen) for n in nodes):
        chosen = None
    if chosen is None:
        active = [
            layer for layer in layers if layer.get("raster") and layer.get("active")
        ]
        if active:
            chosen = str(active[0].get("id"))
        elif len(nodes) == 1:
            chosen = nodes[0]["id"]
    env = call("gp.env", {}) or {}
    label = next((n["label"] for n in nodes if n["id"] == chosen), None)
    # raster.info describes the layer RustGIS holds: its bands fill the band
    # slider, so it covers exactly the ones this raster has.
    try:
        info = call("raster.info", {"layer": label}) if label else {}
    except session.GrassError as e:
        # Opening the panel must never fail over one unreadable layer.
        info = {}
        log(f"raster.info: {e}")
    installed = session.version()
    status = (
        f"GRASS GIS {installed}."
        if installed
        else "GRASS GIS was not found. Install it, or set RUSTGIS_GRASS to its launcher."
    )
    if not nodes:
        status += " The map has no raster layer."
    return {
        "panel": {
            "values": {"raster": chosen} if chosen else {},
            "items": {
                "raster": {"nodes": nodes},
                "source": {
                    "text": "\n".join([label] + raster.source_notes(info))
                    if label
                    else "No raster chosen"
                },
                "band": raster.band_slider(info),
                "region": {"text": describe_region(env)},
                "status": {"text": status},
                "modules": {
                    "nodes": raster.catalogue_tree(
                        load_catalogue().get("catalogue") or []
                    )[0]
                },
                **database_panel(values.get("database")),
            },
        }
    }


def run_command(req):
    """Answer one command request."""
    command = req.get("id")
    if command == "raster-state":
        return panel_state(req)
    if command == "run-module":
        return run_module(req)
    module = load_raster_commands().get(command)
    if module:
        return run_module(req, module)
    if command == "data-browse":
        return browse_database(req)
    if command == "data-folder":
        return add_folder(req)
    if command == "data-add":
        return add_map(req)
    if command == "region-view":
        return set_region(req, "view")
    if command == "region-full":
        return set_region(req, None)
    if command in raster.OPERATIONS:
        return run_raster_command(req)
    raise ValueError(f"unknown command '{command}'")


def main():
    """Read one request, answer it, and exit."""
    line = sys.stdin.readline()
    if not line.strip():
        emit({"error": "no request"})
        return
    try:
        req = json.loads(line)
    except ValueError as e:
        emit({"error": f"unreadable request: {e}"})
        return
    try:
        if req.get("kind") == "tool":
            emit({"ok": run_tool(req, load_modules())})
        elif req.get("kind") == "command":
            emit({"ok": run_command(req)})
        else:
            emit({"error": f"unknown request '{req.get('id')}'"})
    except session.GrassError as e:
        emit({"error": str(e)})
    except (OSError, ValueError, KeyError) as e:
        emit({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
