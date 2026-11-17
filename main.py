"""A RustGIS process plugin that runs GRASS GIS modules.

RustGIS starts this program once per call and speaks one JSON object per line
over standard input and output (see RustGIS docs/plugins.md). GRASS itself is
never linked: each run spawns the user's own installation.

Vector modules are geoprocessing tools: RustGIS hands them the layer's
features as GeoJSON and takes the result back the same way. Raster modules are
commands instead, because a tool gets no raster and makes no host requests;
a command asks RustGIS to export the layer and to add the result back (see
grass_bridge/raster.py).

The panel is four steps, not one column of 24 widgets: grass_bridge/panel.py
holds which widget belongs to which step, and every command answers the
visibility of the step it leaves the panel in. A step also decides what an
answer carries, so choosing a layer no longer sends the 1,424-node module
catalogue back with it.

Progress goes to RustGIS as {"progress": ...} lines, and GRASS modules report
their own percentages to MetaMonitor through its GRASS hook
(https://github.com/YannChemin/MetaMonitor).

SPDX-License-Identifier: Unlicense
"""

import json
import os
import pathlib
import sys

from grass_bridge import database, interface, panel, raster, session

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


#: Said whenever a picture of maps arrives as a layer: a composed imagery
#: group or a display module's render is colours, not the values behind them.
NOT_DATA = (
    "This layer holds a picture of the bands, not their values: it is for "
    "looking at, not for running analysis on."
)


def panel_values(req):
    """Return the panel's widget values from a request.

    RustGIS keeps them between calls and sends them with every request,
    whatever ran the command.
    """
    return dict((req.get("panel") or {}).get("values") or {})


def panel_answer(items=None, values=None, step=None):
    """Return the ``panel`` part of an answer.

    :param items: widget updates, ``{id: {...}}``
    :param values: widget values to set
    :param step: the step to leave the panel in, which answers the visibility
        of every widget. Without one the visibility is left as it was, which
        is what a command whose result is visible from wherever the user is
        should do: jumping the panel to another step under the user is worse
        than showing the result where they are.
    """
    merged = {name: dict(state) for name, state in (items or {}).items()}
    out = {}
    if step is not None:
        for name, state in panel.visibility(step).items():
            merged.setdefault(name, {}).update(state)
        out["values"] = {**(values or {}), "step": step}
    elif values:
        out["values"] = dict(values)
    if merged:
        out["items"] = merged
    return out


def ask_in_tree(chosen, what, press):
    """Return the answer for a command that needs a choice in the data tree.

    **Why this is not an error.** Add Map, Load Workspace and Browse Mapset
    read the node chosen in the panel's GRASS Data tree, and they are on the
    ribbon as well as in the panel. A ribbon button cannot be greyed out --
    a command carries no runtime state -- and the tree is drawn by the
    Project & data step alone, so pressing one of them from the ribbon with
    another step showing, or with nothing chosen, used to answer nothing but
    a red error telling the user to choose something they could not see.

    So the press is taken as what it plainly means -- *I want to do this* --
    and answered by putting the panel on the step where the choice is made,
    with the tree in it, and saying what to choose there. The user's next
    click is the one that works instead of the one that is refused again.

    A plugin cannot open the panel itself: ``ui.pane.plugin`` is the host's
    own command and plugins do not reach the ``ui.*`` family, so the line
    also goes to the message log through ``host.notify`` for the case where
    the panel is closed and the tab row cannot be seen.

    :param chosen: the node that was chosen, if any
    :param what: what the command needs, as "a workspace under Workspaces"
    :param press: the button to press once it is chosen
    """
    said = f"Choose {what} in the GRASS Data tree below, then press {press}."
    if chosen:
        parts = str(chosen).split(database.SEP)
        named = database.SEP.join(parts[1:]) or str(chosen)
        said = (
            f"{named} is not {what}. Choose {what} in the GRASS Data tree "
            f"below, then press {press}."
        )
    call("host.notify", {"text": said})
    items = database_panel(chosen)
    items["status"] = {"text": said}
    items["data-add"] = {"enabled": False}
    items["data-workspace"] = {"enabled": False}
    # The chosen node is set again only when there is one: RustGIS keeps a
    # tree's value only while it was among the nodes last sent, and "" is no
    # node, so sending it back would be answered with "1 value(s) not taken".
    return {
        "asked": said,
        "messages": [said],
        "panel": panel_answer(items, {"database": chosen} if chosen else None, "data"),
    }


def ask_for_module():
    """Return the answer for Run Module pressed with no module chosen.

    The counterpart of :func:`ask_in_tree` for the module catalogue: the
    press answers the Modules step, with its tree, rather than a refusal
    naming a module id that was never chosen (it said ``'None' is not a
    module of this GRASS installation``).
    """
    said = "Choose a module in the Modules tab below, then press Run Module."
    call("host.notify", {"text": said})
    catalogue = load_catalogue().get("catalogue") or []
    nodes, notes = raster.catalogue_tree(catalogue, None, raster.read_recents())
    return {
        "asked": said,
        "messages": [said] + list(notes),
        "panel": panel_answer(
            {
                "modules": {"nodes": nodes},
                "status": {"text": said},
                "run-module": {"enabled": False},
            },
            None,
            "modules",
        ),
    }


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
    """Answer the tree again, with the chosen mapset's maps in it.

    A display module's choices are the maps of the chosen mapset, so the form
    is refreshed here too: choosing a mapset must show its maps without making
    the user choose the module a second time.
    """
    values = panel_values(req)
    chosen = values.get("database")
    items = database_panel(chosen)
    catalogue = load_catalogue().get("catalogue") or []
    base = database.gisdbase()
    module = raster.entry_for(catalogue, values.get("modules"), quietly=True)
    if module and (module.get("render_runnable") or module.get("mapset_inputs")):
        target = database.chosen_mapset(base, chosen) if base else None
        maps = mapset_contents(base, *target, module) if target else []
        mapset = target[1] if target else ""
        items["form"] = {
            "fields": (
                raster.render_form(module, maps, mapset)
                if module.get("render_runnable")
                else raster.mapset_form(module, maps, mapset)
            )
        }
    # A node is a project, a mapset or a map; only a map can be added, so the
    # node is read here rather than with database.parse_node, which refuses
    # anything but a map.
    parts = str(chosen or "").split(database.SEP)
    named = len(parts) == 4 and parts[0] in ("raster", "vector", "group")
    workspace = parts[0] == "workspace" and len(parts) == 2
    workspace_ready = False
    if workspace:
        opening_path = database.parse_workspace_node(chosen)
        opening = database.read_workspace(opening_path)
        # Whether it can open at all is settled here, not after the press: the
        # project a .gxw names is often not where the file says any more.
        place = (
            database.workspace_place(opening_path, opening, base)
            if opening
            else ("", "")
        )
        if not opening:
            said = "That workspace cannot be read."
        elif not place[0]:
            said = (
                f"{opening['project']}/{opening['mapset']} is on none of the "
                "databases this workspace could be on, so it cannot be "
                "loaded: the project was not kept with it."
            )
        else:
            said = (
                f"{place[1]}/{opening['mapset']}, "
                f"{len(opening['layers'])} layer(s): press Load Workspace, "
                "which replaces this project."
            )
            if place[0] != (opening["database"] or ""):
                said += f" Read from {place[0]}, not the path it records."
        workspace_ready = bool(opening and place[0] and opening["layers"])
    elif named and parts[0] == "group":
        said = f"{parts[3]}@{parts[2]}: press Add Map for a composite of its bands."
    elif named:
        said = f"{parts[3]}@{parts[2]}: press Add Map."
    elif len(parts) > 2:
        said = f"{'/'.join(parts[1:])}: choose a map or an imagery group in it."
    else:
        said = "Choose a project and a mapset."
    items["status"] = {"text": said}
    items["data-add"] = {"enabled": named}
    # Load Workspace is only worth pressing for a workspace that can open.
    items["data-workspace"] = {"enabled": workspace and workspace_ready}
    # Pressed from the ribbon with nothing chosen, the whole answer is a tree
    # the user may not be looking at -- the panel can be closed, and a plugin
    # cannot open it. The line goes to the message log too, so the press says
    # something wherever it was made from.
    if not database.opened(chosen):
        call("host.notify", {"text": said})
    # Its whole answer is the database tree, which only this step draws, so a
    # Browse Mapset pressed from the ribbon has to bring the panel here.
    return {"panel": panel_answer(items, {"database": chosen}, "data")}


def save_workspace(req):
    """Write the project's GRASS layers to a workspace beside the one loaded.

    **It never writes the ``.gxw`` it read.** A GRASS GUI session holding
    that file open rewrites it on exit and would silently undo this, and the
    file is GRASS's own; the copy is ``<name>_rustgis.gxw`` in the same
    folder, the same project with the same layers, which the GRASS GUI opens
    like any other. ``{"to": "<path>.gxw"}`` names another file.

    What is saved is the stack as RustGIS now has it: which GRASS maps are
    in it, in which order, ticked or not, at what opacity, and the view as
    the display's extent. A layer that is not a GRASS map of that project --
    a file added from disk, a basemap, a web layer -- has no name a ``.gxw``
    can carry, so it is left out and named in the messages.

    The rest of the file is kept as it was, down to each surviving layer's
    own ``d.vect`` colours: see :func:`grass_bridge.database.write_workspace`.
    """
    params = req.get("params") or {}
    values = panel_values(req)
    base = database.gisdbase()
    if not base:
        raise session.GrassError("no GRASS database was found")
    asked = params.get("workspace") or ""
    path = asked if asked.lower().endswith(".gxw") else ""
    if not path and asked:
        path = database.parse_workspace_node(database.workspace_node(asked))
    chosen = values.get("database")
    if not path and database.is_workspace_node(chosen):
        path = database.parse_workspace_node(chosen)
    path = path or database.last_loaded()
    if not path:
        return ask_in_tree(chosen, "a workspace under Workspaces", "Save Workspace")
    workspace = database.read_workspace(path)
    if not workspace:
        raise session.GrassError(f"{path} is not a readable GRASS workspace")
    where, project = database.workspace_place(path, workspace, base)
    if not where:
        raise session.GrassError(
            f"{workspace['project']}/{workspace['mapset']} is on none of the "
            "databases this workspace could be on, so its maps cannot be "
            "checked; nothing was written"
        )

    kept, left_out = [], []
    for layer in call("host.layers") or []:
        name = str(layer.get("name") or "")
        map_name, _, mapset = name.partition("@")
        kind = (
            database.map_kind(where, project, mapset, map_name)
            if mapset and map_name
            else ""
        )
        if not kind:
            left_out.append(name or "a layer with no name")
            continue
        kept.append(
            {
                "map": map_name,
                "mapset": mapset,
                "kind": kind,
                "shown": layer.get("visible", True),
                # RustGIS keeps transparency, a .gxw keeps opacity.
                "opacity": 1.0 - float(layer.get("transparency") or 0.0),
            }
        )
    if not kept:
        raise session.GrassError(
            f"none of the project's layers is a map of {project}: a .gxw "
            "names GRASS maps, so there is nothing to write"
        )

    extent = None
    view = call("host.view") or {}
    box = view.get("extent")
    if box:
        try:
            with session.Run(progress=progress) as run:
                extent = run.from_degrees(os.path.join(where, project), box)
        except session.GrassError as e:
            # The layers are the point; a view that cannot be projected is
            # worth a line, not a refusal.
            left_out.append(f"the view's extent ({e})")

    target = params.get("to") or database.saved_path(path)
    database.write_workspace(path, target, kept, extent)
    saved_as = (
        f"{len(kept)} layer(s) saved to {target}, which opens in the GRASS "
        f"GUI as {project}/{workspace['mapset']}."
    )
    messages = [saved_as]
    if extent is None and box:
        messages.append("The display's own extent was kept.")
    if left_out:
        messages.append(f"Not saved, having no place in a .gxw: {', '.join(left_out)}.")
    messages.append(f"{path} itself was not touched.")
    for text in messages:
        log(text)
    call("host.notify", {"text": messages[0]})
    return {
        "saved": target,
        "messages": messages,
        "panel": panel_answer(
            {
                **database_panel(chosen),
                "status": {"text": messages[0]},
            },
            None,
            "data",
        ),
    }


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
        "panel": panel_answer(
            {
                **database_panel(),
                "status": {"text": f"{base} is in the browser, under Folders."},
            }
        ),
        "messages": [f"{base} added to the browser's Folders.", NOT_READABLE],
    }


def load_workspace(req):
    """Open a GRASS workspace as this RustGIS project.

    A ``.gxw`` names a GRASS project and mapset and the layers that were
    displayed in it. Loading one replaces the RustGIS project with those
    layers, puts the view in the GRASS project's own coordinate system and
    frames the workspace's own extent.

    **It replaces the project**, which is why it is a button and not what a
    click in the tree does, and why a project with unsaved changes stops it:
    losing someone's unsaved work to a mis-click in a tree is not a thing to
    do quietly. ``{"discard": true}`` says to go ahead anyway.
    """
    values = panel_values(req)
    params = req.get("params") or {}
    chosen = params.get("workspace") or values.get("database")
    if not database.is_workspace_node(chosen):
        return ask_in_tree(chosen, "a workspace under Workspaces", "Load Workspace")
    path = database.parse_workspace_node(chosen)
    workspace = database.read_workspace(path)
    if not workspace:
        raise session.GrassError(f"{path} is not a readable GRASS workspace")

    # The workspace names the database it was written for, which is right
    # while the project is still there, and often it is not: a .gxw outlives
    # the machine it was made on. database.workspace_place also looks in the
    # folder the file itself is in, since a backup carries the project and the
    # workspace together while the recorded path goes stale.
    base, project = database.workspace_place(path, workspace, database.gisdbase())
    if not base:
        tried = [workspace["database"] or "no database recorded"]
        tried.append(os.path.dirname(os.path.dirname(os.path.abspath(path))))
        here = database.gisdbase()
        if here:
            tried.append(here)
        raise session.GrassError(
            f"{path} opens GRASS project <{workspace['project']}>, mapset "
            f"<{workspace['mapset']}>, which is on none of the databases it "
            f"could be on: {', '.join(dict.fromkeys(tried))}. The workspace "
            "outlived its project, or the project was not copied with it."
        )
    if project != workspace["project"]:
        log(
            f"{os.path.basename(path)} records project "
            f"<{workspace['project']}>, and is being read from <{project}> in "
            f"{base}, the project folder it is kept in."
        )
    workspace = {**workspace, "project": project}
    if not workspace["layers"]:
        raise session.GrassError(
            f"{path} has no raster or vector layer to load: its map display "
            "holds none, or holds only ones RustGIS has no kind for"
        )

    open_now = call("info.project") or {}
    if open_now.get("unsaved") and not params.get("discard"):
        raise session.GrassError(
            "this RustGIS project has unsaved changes, and loading a "
            "workspace clears its layers; save it first, or pass "
            '{"discard": true} to lose them'
        )

    opened_as = (
        f"{os.path.basename(path)}: GRASS project {workspace['project']}, "
        f"mapset {workspace['mapset']}, {len(workspace['layers'])} layer(s)."
    )
    messages = [opened_as]
    if workspace["displays"] > 1:
        messages.append(
            f"The workspace has {workspace['displays']} map displays; the "
            "first one's layers were loaded, because RustGIS has one map."
        )
    # `project.new` is reserved: RustGIS refuses every Effect::Replaces
    # command to a plugin, because replacing someone's project is the user's
    # own action. Clearing the layers is what a plugin may do, and it is what
    # "clean from any previous project" means in practice; the project itself
    # -- its name, its file, its layouts -- is left alone, and the messages
    # say so rather than implying a new project was made.
    standing = call("host.layers") or []
    if standing:
        call("layer.remove", {"layer": [layer.get("id") for layer in standing]})
        messages.append(
            f"{len(standing)} layer(s) already in this project were removed. "
            "The project itself is not replaced: a plugin may not do that, "
            "so its name and its file are unchanged."
        )

    loaded, failed = 0, []
    with database.Export(progress=progress) as run:
        epsg = run.crs(base, workspace["project"])
        # The first <layer> of a display is the top of the stack: GRASS's
        # layer tree is written top first (core/workspace.py walks it from
        # its first child) and drawn bottom first (lmgr/layertree.py's
        # GetVisibleLayers reverses the tree order before rendering).
        # RustGIS keeps its layers top first too and layer.addData puts each
        # new one on top, so the workspace is loaded from the bottom up.
        for layer in reversed(workspace["layers"]):
            name, mapset, kind = layer["map"], layer["mapset"], layer["kind"]
            target = raster.output_path(f"{workspace['project']}_{mapset}", name)
            if kind == "vector":
                target = target[: -len(".tif")] + ".gpkg"
            progress(f"Loading {name}@{mapset}...")
            try:
                run.export(base, kind, workspace["project"], mapset, name, target)
                added = call(
                    "layer.addData", {"path": target, "name": f"{name}@{mapset}"}
                )
            except session.GrassError as e:
                # One unreadable map is not a reason to abandon the rest of
                # the workspace, but it is never passed over in silence.
                failed.append(f"{name}@{mapset}: {e}")
                continue
            loaded += 1
            if not layer["shown"] and isinstance(added, dict):
                # The workspace had it unchecked; it is loaded but not drawn,
                # so the project matches what GRASS was showing.
                call(
                    "layer.visibility",
                    {"layer": added.get("layer"), "visible": False},
                )

    if not loaded:
        raise session.GrassError(
            f"none of {len(workspace['layers'])} layer(s) could be loaded: "
            + "; ".join(failed)
        )
    messages.append(f"{loaded} layer(s) loaded from {workspace['project']}.")
    for text in failed:
        messages.append(f"Not loaded - {text}")
    messages += harmonise_projection(epsg, workspace["project"], False)
    messages += frame_workspace(base, workspace)
    # Save Workspace saves the one that was loaded, which the tree may no
    # longer be on by the time the layers have been worked with.
    database.remember_loaded(path)

    for text in messages:
        log(text)
    call("host.notify", {"text": messages[0]})
    return {
        "messages": messages,
        "panel": panel_answer(
            {
                **database_panel(chosen),
                "status": {"text": f"{workspace['project']}: {loaded} layer(s)."},
            },
            None,
            "data",
        ),
    }


def frame_workspace(base, workspace):
    """Zoom the view to the workspace's own display extent.

    The extent is in the GRASS project's coordinate system and
    ``map.zoomToExtent`` takes degrees, so it is projected with ``m.proj``.
    A failure here is not worth failing a load that worked: the layers are
    there, and the view can be moved by hand.

    :return: ``[message, ...]``
    """
    extent = workspace.get("extent")
    if not extent:
        return ["The workspace names no display extent, so the view was left."]
    try:
        with session.Run(progress=progress) as run:
            degrees = run.to_degrees(os.path.join(base, workspace["project"]), extent)
        call("map.zoomToExtent", {"extent": degrees})
    except session.GrassError as e:
        return [f"The view was not framed on the workspace's extent ({e})."]
    west, south, east, north = degrees
    framed = (
        f"The view is framed on the workspace's own extent "
        f"({west:.5f}, {south:.5f} to {east:.5f}, {north:.5f})."
    )
    return [framed]


def compose_group(base, project, mapset, name, target):
    """Draw one imagery group as a single picture, and say what was drawn.

    A group's bands are meant to be seen together, so the group is composed
    by the display module that fits it -- ``d.rgb`` for three bands or more,
    ``d.his`` for two -- and imported back as one RGB layer, rather than
    being added as a stack of grey rasters the user then has to compose.

    The result is a **picture** of the bands, not the band values: it is for
    looking at, not for running analysis on, and the messages say so.

    :return: ``([message, ...], epsg)``
    """
    members = database.group_members(base, project, mapset, name)
    module, args, bands, notes = raster.group_display(members, mapset)
    with session.DisplayRun(progress=progress) as run:
        messages = run.render_mapset(
            base, project, mapset, module, args, bands, [], target
        )
        epsg = run.crs(base, project)
    return messages + notes + [NOT_DATA], epsg


def add_map(req):
    """Export the map chosen in the tree and add it to the project."""
    values = panel_values(req)
    base = database.gisdbase()
    if not base:
        raise session.GrassError("no GRASS database was found")
    # As with run-module, RustGIS keeps a tree's value only while the node is
    # among the ones it was last sent, so a script that has not browsed the
    # tree cannot set it. Naming the map in the command's own parameters is
    # the way in for the command line, for Python and for scripts.
    asked = (req.get("params") or {}).get("map")
    chosen = asked or values.get("database")
    if not database.is_map_node(chosen):
        return ask_in_tree(chosen, "a map or an imagery group", "Add Map")
    kind, project, mapset, name = database.parse_node(chosen)
    # A raster goes out as a GeoTIFF and a vector as a GeoPackage, which both
    # carry the coordinate system RustGIS then reads them in.
    target = raster.output_path(f"{project}_{mapset}", name)
    if kind == "vector":
        target = target[: -len(".tif")] + ".gpkg"

    # Read before the map is added, so "the only layer in the view" means
    # what it says when the view's projection is decided below.
    other_layers = bool(call("host.layers"))
    if kind == "group":
        messages, epsg = compose_group(base, project, mapset, name, target)
    else:
        with database.Export(progress=progress) as run:
            messages = run.export(base, kind, project, mapset, name, target)
            epsg = run.crs(base, project)

    if not epsg:
        # RustGIS reads a layer's coordinate system from the file and refuses
        # one it cannot recognise ("the file's coordinate system isn't
        # recognised"). An XY project has none to write, so say which project
        # is the reason rather than leaving that message to stand alone.
        raise session.GrassError(
            f"{name}@{mapset} cannot be placed on the map: GRASS project "
            f"{project} has no coordinate system (an XY project), so the "
            "export carries none and RustGIS has nothing to place it by"
        )
    added = call("layer.addData", {"path": target, "name": f"{name}@{mapset}"})
    messages += harmonise_projection(epsg, project, other_layers)
    messages.append(f"The export is kept at {target}.")
    for text in messages:
        log(text)
    call("host.notify", {"text": f"{name}@{mapset} added from {project}."})
    return {
        "layer": added,
        "messages": messages,
        "panel": panel_answer(
            {
                **database_panel(values.get("database")),
                "status": {"text": f"{name}@{mapset} added from {project}."},
            }
        ),
    }


def harmonise_projection(epsg, project, other_layers):
    """Put the view in the GRASS project's own coordinate system.

    RustGIS reads the coordinate system from the file the plugin exports and
    reprojects a layer for display, so a map always lands in the right place.
    What it does not do is adopt that system as the view's own: a map from a
    projected GRASS project is drawn in whatever world projection the view
    happens to be in, which is not the system the user's GRASS work is in.
    This is the same step the QGIS import makes (``crates/engine/src/cmd/qgis.rs``),
    for the same reason.

    The view is only changed when changing it cannot move someone else's data
    under them: either the view is still in a world projection (the code is
    not an EPSG one), or this map is the only thing in it. A view already in
    another EPSG system is left alone and said to be left alone, because that
    system was chosen -- by the user, or by the last GRASS map loaded -- and
    the layers in it are drawn there.

    :param epsg: the project's system as :meth:`database.Export.crs` reads it,
        or None when it names none
    :param project: the GRASS project's name, for the message
    :param other_layers: whether the view holds any layer but the new one
    :return: ``[message, ...]``
    """
    view = call("host.view") or {}
    now = str(view.get("projection") or "")
    if not epsg:
        said = (
            f"The view's projection was left as it is: GRASS project {project} "
            "names no EPSG code for its coordinate system."
        )
        return [said]
    if now.upper() == epsg.upper():
        return [f"The view is already in {epsg}, the coordinate system of {project}."]
    if now.upper().startswith("EPSG:") and other_layers:
        said = (
            f"The view was left in {now}: {project} is in {epsg}, but the view "
            "already holds layers drawn in its own system. The map is "
            "reprojected for display, so it is in the right place."
        )
        return [said]
    try:
        call("map.projection", {"type": epsg})
    except session.GrassError as e:
        # An unsupported system is not a reason to fail the load: the layer is
        # there and reprojected for display, so say what was not done.
        said = (
            f"The view stays in {now}: it cannot be put in {epsg}, the "
            f"coordinate system of {project} ({e}). The map is reprojected "
            "for display, so it is in the right place."
        )
        return [said]
    return [f"The view is now in {epsg}, the coordinate system of {project}."]


def export_source(name, values, tag=""):
    """Have RustGIS write the chosen raster layer, and say what went out.

    ``raster.info`` describes the layer before it leaves (its coordinate
    system, its cell size, how many bands it has) and ``share.exportRaster``
    says what it actually wrote, so a run on a downsampled overview or on one
    band of many is reported rather than passed off as the whole raster.

    :param name: the layer's name
    :param values: the panel's widget values
    :param tag: a suffix keeping several exports of one run apart
    :return: ``(path, [note, ...], info)``
    """
    info = call("raster.info", {"layer": name}) or {}
    raster.check_source(info, name)
    band, band_note = raster.choose_band(info, values)
    exported = os.path.join(raster.output_dir(), f".export-{os.getpid()}{tag}.tif")
    progress(f"Exporting {name}...")
    params = {"layer": name, "path": exported}
    if band:
        params["band"] = band
    written = call("share.exportRaster", params) or {}
    notes = raster.source_notes(info, written)
    if band_note:
        notes.append(band_note)
    return exported, notes, info


def export_vector(name, tag=""):
    """Have RustGIS write a vector layer as GeoJSON for a display module.

    :param name: the layer's name
    :param tag: a suffix keeping several exports of one run apart
    :return: ``(path, [note, ...])``
    """
    target = os.path.join(raster.output_dir(), f".export-{os.getpid()}{tag}.geojson")
    try:
        os.remove(target)
    except OSError:
        pass
    progress(f"Exporting {name}...")
    call("share.exportLayer", {"layer": name, "path": target, "crs": "EPSG:4326"})
    if not os.path.exists(target):
        raise session.GrassError(
            f"RustGIS exported no file for {name}; the layer may be empty"
        )
    return target, []


def run_display_module(catalogue, entry, values):
    """Render a display module over maps of the chosen GRASS mapset.

    A ``d.*`` module draws on a monitor rather than writing a raster. The
    bridge draws it in a throwaway mapset of the chosen GRASS project, reads
    the maps from the selected mapset, and turns the picture into a GeoTIFF,
    so the result arrives in RustGIS as an ordinary raster layer of colours.
    """
    base = database.gisdbase()
    if not base:
        raise session.GrassError(
            "no GRASS database was found: GISDBASE is not set, GRASS's settings "
            "file names none, and there is no ~/grassdata"
        )
    target_mapset = database.chosen_mapset(base, values.get("database"))
    if not target_mapset:
        raise session.GrassError(
            f"{entry['module']} draws maps from one GRASS mapset: choose the "
            "project and mapset under Projects and mapsets."
        )
    project, mapset = target_mapset
    maps = database.maps(base, project, mapset)
    form = values.get("form") if isinstance(values.get("form"), dict) else {}
    ports, preview = raster.render_plan(entry, values, maps, mapset)
    missing = raster.missing_form_values(entry, form)
    if missing:
        raise session.GrassError(
            f"{entry['module']} needs {', '.join(missing)} before it can render"
        )

    imported = {
        port["name"]: [f"{name}@{mapset}" for name in port["maps"]] for port in ports
    }
    rasters, vectors = [], []
    for port in ports:
        into = rasters if port["kind"] == "raster" else vectors
        into += imported[port["name"]]

    label = str(ports[0]["maps"][0])
    target = raster.output_path(label, entry["module"].replace(".", "-"))
    preview_path = target[: -len(".tif")] + ".png" if preview else None
    with session.DisplayRun(progress=progress) as run:
        messages = run.render_mapset(
            base,
            project,
            mapset,
            entry["module"],
            raster.render_args(entry, form, imported),
            rasters,
            vectors,
            target,
            preview=preview_path,
        )

    added = call(
        "layer.addData",
        {"path": target, "name": f"{label} {entry['module']} (picture)"},
    )
    messages.append(f"The result is kept at {target}.")
    for text in messages:
        log(text)
    call("host.notify", {"text": f"{entry['module']}: {messages[0]}"})
    recent = raster.remember(entry["module"])
    family = raster.mode_family(values.get("family", values.get("mode")))
    nodes, tree_notes = raster.catalogue_tree(
        catalogue, entry["module"], recent, family=family
    )
    return {
        "layer": added,
        "messages": messages + tree_notes,
        "panel": panel_answer(
            {
                "modules": {"nodes": nodes},
                "details": {"text": raster.module_details(entry)},
                "form": {"fields": raster.render_form(entry, maps, mapset)},
                "status": {"text": "\n".join(messages + tree_notes)},
                **database_panel(values.get("database")),
            }
        ),
    }


def run_module_in_mapset(catalogue, entry, values):
    """Run a module the form drives in the chosen GRASS project and mapset.

    A temporal, database or general module does not read one raster and write
    another: it imports a dataset or changes the project it runs in. The form
    names its parameters, and the project and mapset chosen under Projects
    and mapsets say where the work should go.
    """
    base = database.gisdbase()
    if not base:
        raise session.GrassError(
            "no GRASS database was found: GISDBASE is not set, GRASS's settings "
            "file names none, and there is no ~/grassdata"
        )
    chosen = values.get("database")
    target = database.chosen_mapset(base, chosen)
    if not target:
        named = (chosen or "").split(database.SEP)[1:]
        raise session.GrassError(
            f"{entry['module']} runs in a GRASS mapset, and "
            f"{database.SEP.join(named)} is not one of {base}"
            if named
            else f"{entry['module']} runs in a GRASS mapset: choose the "
            "project and mapset it should write to under Projects and mapsets."
        )
    project, mapset = target
    maps = mapset_contents(base, project, mapset, entry)
    ports = raster.mapset_plan(entry, values, maps, mapset)
    form = values.get("form") or {}
    missing = raster.missing_form_values(entry, form)
    if missing:
        raise session.GrassError(
            f"{entry['module']} needs {', '.join(missing)} before it can run"
        )
    imported = {port["name"]: port["maps"] for port in ports}
    args = raster.mapset_args(entry, form, imported, maps, mapset)
    with session.Run(progress=progress) as run:
        messages = run.mapset_module(base, project, mapset, entry["module"], args)
    for text in messages:
        log(text)
    call("host.notify", {"text": f"{entry['module']}: {messages[0]}"})
    recent = raster.remember(entry["module"])
    family = raster.mode_family(values.get("family", values.get("mode")))
    nodes, notes = raster.catalogue_tree(
        catalogue, entry["module"], recent, family=family
    )
    return {
        "messages": messages + notes,
        "panel": panel_answer(
            {
                "modules": {"nodes": nodes},
                "details": {"text": raster.module_details(entry)},
                "form": {"fields": raster.mapset_form(entry, maps, mapset)},
                "status": {"text": "\n".join(messages + notes)},
                **database_panel(values.get("database")),
            }
        ),
    }


def with_params(values, params):
    """Return the panel's values with a command's own parameters laid over.

    A script cannot choose in a tree or type in a form: RustGIS keeps a
    tree's value only while that value was among the nodes last sent, and a
    form takes values only for the fields it currently holds. So reaching a
    module from the command line meant walking the panel there first -- four
    calls before the run. These parameters say the same things directly:

    ``{"module": "t.rast.series", "mapset": "Busoga/PERMANENT",
    "values": {"input": "s2_B04@PERMANENT", "output": "b04_mean"}}``

    They are laid **over** the panel, so a parameter wins where both say
    something, and they go through the very same checks: the mapset must hold
    the maps and datasets named, and an output name is still refused if it is
    taken. Nothing here is a way around a check.
    """
    params = params or {}
    out = dict(values or {})
    named = database.mapset_node(params.get("mapset"))
    if named:
        out["database"] = named
    elif params.get("mapset"):
        raise session.GrassError(
            f"mapset: {params['mapset']!r} is not a project and mapset; "
            'name them as "<project>/<mapset>"'
        )
    given = params.get("values")
    if given is not None:
        if not isinstance(given, dict):
            raise session.GrassError(
                "values: the module's parameters go in an object, "
                '{"input": "...", "output": "..."}'
            )
        out["form"] = {**(out.get("form") or {}), **given}
    return out


def run_module(req, module=None):
    """Run the module chosen in the tree, on a raster or in a mapset.

    Every installed module is in the panel's tree, and the common ones have a
    ribbon command of their own (``module`` names that one). A module that
    reads a raster and writes one runs on the chosen layer. A temporal,
    database or general module the form can drive runs in the GRASS project
    and mapset chosen under Projects and mapsets, so what it writes outlives
    the run.

    A script can name the module in the command's own parameters
    (``{"module": "r.slope.aspect"}``) instead of the tree: RustGIS keeps a
    tree's value only while that value was among the nodes last sent, and the
    module tree is only sent by the step that draws it, so a run from the
    command line would otherwise have to walk the panel there first.

    :param module: the GRASS module a curated command runs, or None to take
        the one named in the request's parameters, or the one chosen in the
        tree
    """
    values = with_params(panel_values(req), req.get("params"))
    catalogue = load_catalogue().get("catalogue") or []
    asked = (req.get("params") or {}).get("module")
    chosen = module or asked or values.get("modules")
    if not chosen:
        # Run Module is on the ribbon too, where the module tree cannot be
        # seen: the press means "run one", so it answers the catalogue on the
        # step that draws it, as the tree commands do. See ask_in_tree.
        return ask_for_module()
    entry = raster.entry_for(catalogue, chosen)
    if not entry.get("runnable"):
        if entry.get("mapset_runnable"):
            return run_module_in_mapset(catalogue, entry, values)
        if entry.get("render_runnable"):
            return run_display_module(catalogue, entry, values)
        raise session.GrassError(
            f"{entry['module']} cannot be run from this panel: "
            f"{entry.get('reason') or 'its form cannot name what it needs'}"
        )
    # A required field the user has not filled is caught here, before the
    # export and the GRASS run: the module would fail on it anyway, and a
    # message now beats one after the wait.
    missing = raster.missing_form_values(entry, values.get("form"))
    if missing:
        raise session.GrassError(
            f"{entry['module']} needs {', '.join(missing)} before it can run"
        )
    argv = raster.free_module_args(entry) + raster.form_args(entry, values.get("form"))

    layers = call("host.layers") or []
    layer = raster.choose_raster(layers, values.get("raster"))
    name = str(layer.get("name"))
    env = call("gp.env", {}) or {}

    target = raster.output_path(name, entry["module"].replace(".", "-"))
    exported, source = export_source(name, values)[:2]
    budget = session.budget_asked(req.get("params"))
    try:
        with raster.RasterRun(progress=progress, budget=budget) as run:
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
    recent = raster.remember(entry["module"])
    family = raster.mode_family(values.get("family", values.get("mode")))
    nodes, notes = raster.catalogue_tree(
        catalogue, entry["module"], recent, family=family
    )
    return {
        "layer": added,
        "messages": messages + notes,
        "panel": panel_answer(
            {
                "modules": {"nodes": nodes},
                "details": {"text": raster.module_details(entry)},
                "form": {"fields": raster.form_of(entry)},
                "status": {"text": "\n".join(messages)},
            }
        ),
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


def picked_box(values, name="region-box"):
    """Return a box pick's ``[west, south, east, north]`` in degrees, or None.

    :raises session.GrassError: for a box drawn across the antimeridian, whose
        west is east of its east. RustGIS's Analysis Environment takes an
        extent as four increasing degrees, so such a box has to be refused
        rather than turned into an extent that means the rest of the world.
    """
    place = (values or {}).get(name)
    if not isinstance(place, dict):
        return None
    box = place.get("bbox")
    if not isinstance(box, list) or len(box) != 4:
        return None
    try:
        west, south, east, north = (float(x) for x in box)
    except (TypeError, ValueError):
        return None
    if west > east:
        raise session.GrassError(
            f"the box crosses the antimeridian ({west:.5f} to {east:.5f}); "
            "draw one that does not, or set the region from the map view"
        )
    if south >= north:
        raise session.GrassError(
            f"the box has no height ({south:.5f} to {north:.5f}); draw a larger one"
        )
    return [west, south, east, north]


def set_region(req, extent):
    """Set the Analysis Environment's extent and answer the panel.

    :param extent: ``"view"`` for the map view, or None for the whole layer
    """
    env = call("gp.env", {"extent": extent})
    told = (
        "the map view"
        if extent == "view"
        else "the whole layer"
        if extent is None
        else "the box drawn on the map"
    )
    text = describe_region(env)
    call("host.notify", {"text": f"Computational region: {told}."})
    return {
        "environment": env,
        "panel": panel_answer(
            {
                "region": {"text": text},
                "status": {"text": f"Computational region: {told}.\n{text}"},
            }
        ),
    }


def panel_state(req, family=None, step=None):
    """Answer the panel's state, for the step it is in.

    It reads the map only, so it is no undo step.

    A step decides what the answer carries as well as what is drawn. The
    module tree is 1,424 nodes and about 270 KB of JSON and a mapset's tree can
    be thousands of maps, and RustGIS keeps what an answer leaves out, so a
    tree is sent only by the step that draws it. The raster tree is small and
    always sent: a tree keeps a chosen value only while its node is among the
    ones last sent.

    :param family: a module family to show (``imagery``, ``temporal``,
        ``all``), which also moves the panel to the module step; without one
        the family the panel already had is kept
    :param step: the step to show; without one the step the panel is in
    """
    layers = call("host.layers") or []
    nodes = raster.raster_nodes(layers)
    values = panel_values(req)
    if family is not None:
        values["family"] = family
        step = step or "modules"
    # `mode` was the id of the tree this dropdown replaced; a script that
    # still sends it is read rather than ignored.
    family = raster.mode_family(values.get("family", values.get("mode")))
    chosen_family = next(
        (name for name, _, keeps in panel.FAMILIES if keeps == family), "all"
    )
    step = panel.step_of(step if step is not None else values.get("step"))
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
    catalogue = load_catalogue().get("catalogue") or []
    runnable = sum(1 for entry in catalogue if entry.get("runnable"))
    in_mapset = sum(
        1
        for entry in catalogue
        if entry.get("mapset_runnable") and not entry.get("runnable")
    )
    renders = sum(
        1
        for entry in catalogue
        if entry.get("render_runnable")
        and not entry.get("runnable")
        and not entry.get("mapset_runnable")
    )
    if catalogue:
        status += (
            f" {runnable} of {len(catalogue)} modules run on the chosen raster "
            "with GRASS's own defaults"
        )
        if in_mapset:
            status += (
                f"; {in_mapset} more run with their form in a chosen GRASS "
                "project and mapset"
            )
        if renders:
            status += f"; {renders} display modules render a picture"
        status += "; the tree gives the reason for the others."
        if family:
            status += f" Showing {family.lower()} modules only."
    chosen_module = raster.entry_for(catalogue, values.get("modules"), quietly=True)
    render_maps, render_mapset, render_project = [], "", ""
    needs_maps = bool(
        chosen_module
        and (chosen_module.get("render_runnable") or chosen_module.get("mapset_inputs"))
    )
    if needs_maps:
        base = database.gisdbase()
        target = database.chosen_mapset(base, values.get("database")) if base else None
        if target:
            render_project, render_mapset = target
            render_maps = database.maps(base, render_project, render_mapset)
        if not base:
            status += " No GRASS database was found; this module works on maps in one."
        elif not target:
            status += (
                " Choose a project and mapset under Projects and mapsets; this "
                "module chooses its maps from one mapset."
            )
        elif not render_maps:
            status += f" {render_project}/{render_mapset} has no maps to draw on."
    if not nodes and not (
        chosen_module
        and (
            chosen_module.get("mapset_runnable") or chosen_module.get("render_runnable")
        )
    ):
        status += " The map has no raster layer."
    items = {
        "raster": {"nodes": nodes},
        "source": {
            "text": "\n".join([label] + raster.source_notes(info))
            if label
            else "No raster chosen"
        },
        "band": raster.band_slider(info),
        "region": {"text": describe_region(env)},
        "status": {"text": status},
        "details": {"text": raster.module_details(chosen_module)},
        "form": {"fields": module_form(chosen_module, render_maps, render_mapset)},
        "run-module": {"enabled": can_run(chosen_module)},
    }
    shown = {"family": chosen_family}
    if chosen:
        shown["raster"] = chosen
    if panel.sends_nodes(step, "modules"):
        module_nodes, _ = raster.catalogue_tree(
            catalogue,
            values.get("modules"),
            raster.read_recents(),
            family=family,
        )
        items["modules"] = {"nodes": module_nodes}
    if panel.sends_nodes(step, "database"):
        # Reading the database is a file-system walk; the step that draws it is
        # the only one that needs it.
        items.update(database_panel(values.get("database")))
    return {"panel": panel_answer(items, shown, step)}


def can_run(entry):
    """Say whether Run Module can drive this module at all.

    A module it cannot drive keeps its reason in Chosen module; the button is
    disabled rather than failing after the click.
    """
    return bool(
        entry
        and (
            entry.get("runnable")
            or entry.get("mapset_runnable")
            or entry.get("render_runnable")
        )
    )


def mapset_contents(base, project, mapset, entry):
    """Return what a module's form may choose from in one mapset.

    The maps are read from the file system, which is free. A space-time
    dataset is not a folder but a row in the mapset's temporal database, so
    listing those costs a GRASS run -- and it is only made when the module
    actually names one, which few do.

    :return: ``[(kind, name), ...]``, datasets alongside the maps
    """
    found = list(database.maps(base, project, mapset))
    # The outputs count too: a new dataset's name is checked against the ones
    # already there, so nothing of the user's is overwritten.
    ports = ((entry or {}).get("mapset_inputs") or []) + (
        (entry or {}).get("mapset_outputs") or []
    )
    wanted = {
        port.get("kind")
        for port in ports
        if port.get("kind") in interface.TEMPORAL_ELEMENTS
    }
    for kind in sorted(wanted):
        with database.Export(progress=progress) as run:
            found += [
                (kind, name) for name in run.datasets(base, project, mapset, kind)
            ]
    return found


def module_form(entry, maps=(), mapset=""):
    """Return the form fields of the chosen module, whatever kind it is."""
    if not entry:
        return raster.form_of(entry)
    if entry.get("render_runnable"):
        return raster.render_form(entry, list(maps), mapset)
    if entry.get("mapset_inputs"):
        return raster.mapset_form(entry, list(maps), mapset)
    return raster.form_of(entry)


def layer_pick(req):
    """Describe the raster layer chosen in the panel, and nothing else.

    The raster tree used to ask for the whole state, which rebuilt and sent
    all 1,424 catalogue nodes for a choice that cannot change them. This
    answers the four widgets a layer choice does change.
    """
    values = panel_values(req)
    layers = call("host.layers") or []
    nodes = raster.raster_nodes(layers)
    chosen = str(values.get("raster") or "")
    label = next((n["label"] for n in nodes if n["id"] == chosen), None)
    try:
        info = call("raster.info", {"layer": label}) if label else {}
    except session.GrassError as e:
        info = {}
        log(f"raster.info: {e}")
    env = call("gp.env", {}) or {}
    notes = raster.source_notes(info)
    items = {
        "raster": {"nodes": nodes},
        "source": {"text": "\n".join([label] + notes) if label else "No raster chosen"},
        "band": raster.band_slider(info),
        "region": {"text": describe_region(env)},
        "status": {"text": f"{label}: ready to run." if label else "No raster chosen."},
    }
    values = {"raster": chosen} if label else {}
    return {"panel": panel_answer(items, values)}


def module_pick(req):
    """Describe the module chosen in the panel, and fill its form.

    Neither tree is answered, so choosing one of 1,177 modules costs a few
    kilobytes rather than the catalogue it was chosen from.
    """
    values = panel_values(req)
    catalogue = load_catalogue().get("catalogue") or []
    entry = raster.entry_for(catalogue, values.get("modules"), quietly=True)
    maps, mapset = [], ""
    if entry and (entry.get("render_runnable") or entry.get("mapset_inputs")):
        base = database.gisdbase()
        target = database.chosen_mapset(base, values.get("database")) if base else None
        if target:
            mapset = target[1]
            maps = mapset_contents(base, *target, entry)
    # A module that runs in a mapset or draws a picture is runnable, and its
    # raster-path reason ("takes no raster") describes a path it was never on:
    # saying that about a module Run Module will happily run is wrong.
    if not entry:
        status = "Choose a module in the tree."
    elif can_run(entry):
        status = f"{entry['module']}: press Run Module."
    else:
        status = f"{entry['module']}: {entry.get('reason') or 'see Chosen module'}."
    return {
        "panel": panel_answer(
            {
                "details": {"text": raster.module_details(entry)},
                "form": {"fields": module_form(entry, maps, mapset)},
                "status": {"text": status},
                # Run Module is only worth pressing for a module this panel can
                # drive; the reason for the others is in Chosen module.
                "run-module": {"enabled": can_run(entry)},
            }
        )
    }


def run_command(req):
    """Answer one command request."""
    command = req.get("id")
    if command == "raster-state":
        return panel_state(req)
    if command == "panel-step":
        return panel_state(req)
    if command == "layer-pick":
        return layer_pick(req)
    if command == "module-pick":
        return module_pick(req)
    if command == "imagery-state":
        return panel_state(req, "imagery")
    if command == "temporal-state":
        return panel_state(req, "temporal")
    if command == "all-state":
        return panel_state(req, "all")
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
    if command == "data-workspace":
        return load_workspace(req)
    if command == "data-save":
        return save_workspace(req)
    if command == "region-view":
        return set_region(req, "view")
    if command == "region-full":
        return set_region(req, None)
    if command == "region-box":
        box = picked_box(panel_values(req))
        if box is None:
            raise session.GrassError(
                "no box has been drawn: press Region from a Box in the GRASS "
                "GIS panel, then drag one on the map"
            )
        return set_region(req, box)
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
