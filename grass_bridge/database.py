"""Reading the GRASS database the way GRASS itself finds it.

GRASS keeps the database it last used in its own settings file,
``~/.grass8/rc``, as ``GISDBASE:``; inside a session it is the ``GISDBASE``
environment variable. That is where this looks, so the plugin offers the same
projects the user's GRASS does, rather than a path written down here.

A project is a folder holding a PERMANENT mapset, a mapset a folder holding a
WIND file, and a mapset's maps are its ``cellhd`` files (rasters) and
``vector`` folders. Reading that layout from the file system costs nothing,
where asking GRASS would mean one run per mapset.

A plugin cannot add an entry to RustGIS's own Add Data menu; only the host
can. What it can do is put the database in the browser's Folders
(``project.addFolder``) and hand over a map on request, by exporting it to a
format RustGIS reads natively.

SPDX-License-Identifier: Unlicense
"""

import fnmatch
import os
import subprocess
import urllib.parse
from xml.etree import ElementTree

from . import session

#: GRASS's own settings files, newest first.
RC_FILES = ("~/.grass8/rc", "~/.grass7/rc")

#: Where GRASS puts a database when it has never been told otherwise.
DEFAULT_DIR = "~/grassdata"

#: A panel tree holds this many nodes; leave room for the branches.
MAX_NODES = 4000

#: What joins the parts of a node's id. Projects, mapsets and maps are all
#: file names, so a slash can appear in none of them, and an id stays readable
#: from a script: "raster/C2RD_drone/PERMANENT/lidarhd_mnt".
SEP = "/"


#: How deep under the home folder a workspace is looked for. GRASS writes one
#: beside its project (``~/grassdata/<project>/default.gxw``, depth 3), and a
#: user keeps others a folder or two down. Measured here: 0.06 s for the whole
#: of a home folder at this depth, so it is done on each panel open rather than
#: cached, which would go stale.
WORKSPACE_DEPTH = 4

#: Folder names never walked for workspaces: caches and checkouts hold no GRASS
#: workspace and are where a home folder's file count actually is. Hidden
#: folders are skipped as well.
WORKSPACE_SKIP = frozenset(
    {
        "node_modules",
        "__pycache__",
        "venv",
        ".venv",
        "target",
        "build",
        "dist",
        "site-packages",
    }
)

#: The most a ``.gxw`` may be before it is passed over: a workspace is a few
#: kilobytes of XML, and parsing an arbitrarily large file found by a scan is
#: not something a panel open should do.
WORKSPACE_MAX_BYTES = 4 * 1024 * 1024


def gisdbase():
    """Return the GRASS database GRASS itself would use, or None.

    :return: a path, from ``GISDBASE``, then GRASS's settings file, then the
        usual ``~/grassdata``; None when none of them is a folder
    """
    for candidate in [os.environ.get("GISDBASE")] + _from_rc() + [DEFAULT_DIR]:
        if not candidate:
            continue
        path = os.path.expanduser(candidate)
        if os.path.isdir(path):
            return path
    return None


def _from_rc():
    """Return the GISDBASE lines of GRASS's settings files."""
    out = []
    for name in RC_FILES:
        try:
            with open(os.path.expanduser(name), encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("GISDBASE:"):
                        out.append(line.split(":", 1)[1].strip())
        except OSError:
            continue
    return out


def projects(base):
    """Return the names of the projects in a database, in order.

    A project is a folder with a PERMANENT mapset in it, which leaves out the
    scripts and logs users keep beside their projects.
    """
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return []
    return [
        name for name in names if os.path.isdir(os.path.join(base, name, "PERMANENT"))
    ]


def mapsets(base, project):
    """Return the names of a project's mapsets, PERMANENT first."""
    path = os.path.join(base, project)
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return []
    found = [name for name in names if os.path.isfile(os.path.join(path, name, "WIND"))]
    return sorted(found, key=lambda name: (name != "PERMANENT", name))


def maps(base, project, mapset):
    """Return a mapset's maps as ``[(kind, name), ...]``.

    :return: ``kind`` is ``"raster"``, ``"vector"`` or ``"raster_3d"``
    """
    path = os.path.join(base, project, mapset)
    out = []
    try:
        out += [
            ("raster", name)
            for name in sorted(os.listdir(os.path.join(path, "cellhd")))
        ]
    except OSError:
        pass
    try:
        for name in sorted(os.listdir(os.path.join(path, "vector"))):
            if os.path.isdir(os.path.join(path, "vector", name)):
                out.append(("vector", name))
    except OSError:
        pass
    try:
        # A 3D raster is a folder under grid3, so it lists as cheaply as the
        # rest. g.list type=raster3d would say the same thing and cost a GRASS
        # run; the file system is the same answer for free.
        for name in sorted(os.listdir(os.path.join(path, "grid3"))):
            out.append(("raster_3d", name))
    except OSError:
        pass
    return out


def groups(base, project, mapset):
    """Return a mapset's imagery groups as ``[(name, [(map, mapset), ...])]``.

    A GRASS imagery group (``i.group``) is a named, ordered set of bands meant
    to be seen or classified together. It is a folder under the mapset's
    ``group``, holding a ``REF`` file of ``<map> <mapset>`` lines in the band
    order the user set, so it is read from the file system like everything
    else here rather than by running ``i.group``.

    A group whose ``REF`` is missing or empty is left out: there is nothing to
    display and nothing to say about it.

    :return: the groups in name order, each with its bands in **band order**
    """
    path = os.path.join(base, project, mapset, "group")
    out = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return out
    for name in names:
        members = _members(os.path.join(path, name, "REF"))
        if members:
            out.append((name, members))
    return out


def _members(ref):
    """Return the ``[(map, mapset), ...]`` a group's ``REF`` file names."""
    try:
        with open(ref, encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        parts = line.split()
        # A band is "<map> <mapset>"; anything else is not one, and guessing
        # at a half-written line would put a wrong map in a composite.
        if len(parts) == 2:
            found.append((parts[0], parts[1]))
    return found


def group_members(base, project, mapset, name):
    """Return one group's bands, in band order.

    :raises session.GrassError: when the group holds no readable band
    """
    for found, members in groups(base, project, mapset):
        if found == name:
            return members
    raise session.GrassError(
        f"imagery group <{name}> of {project}/{mapset} names no readable band "
        "(its REF file is missing or empty)"
    )


def workspaces(base=None, home=None):
    """Find the GRASS workspaces under the database and the home folder.

    A ``.gxw`` is the GRASS GUI's own workspace: XML naming a database, a
    project and a mapset, with the layers that were displayed. GRASS writes
    one beside each project it is used in, and users keep others in their own
    folders, so both places are looked at, bounded by
    :data:`WORKSPACE_DEPTH` and skipping hidden folders and
    :data:`WORKSPACE_SKIP`.

    A file that cannot be read or does not parse is left out rather than
    reported here: it is not a workspace as far as this is concerned, and a
    panel open is not the place to raise it.

    :return: ``[(path, workspace), ...]`` in path order, without duplicates,
        where ``workspace`` is :func:`read_workspace`'s dictionary
    """
    seen, found = set(), []
    for path in _workspace_files(base, home):
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        workspace = read_workspace(path)
        if workspace:
            found.append((path, workspace))
    found.sort(key=lambda pair: pair[0])
    return found


def _workspace_files(base, home):
    """Yield every ``.gxw`` path to consider, the cheap way first.

    The GRASS database is not walked: GRASS writes a project's workspace
    beside it, at ``<base>/<project>/*.gxw``, so one listing of the project
    folders finds them. Walking it instead would descend into the mapsets,
    where this database's 35,000 maps are, and cost seconds.
    """
    if base and os.path.isdir(base):
        for project in _listing(base):
            folder = os.path.join(base, project)
            for name in _listing(folder):
                if name.endswith(".gxw"):
                    yield os.path.join(folder, name)
    root = os.path.expanduser("~") if home is None else home
    if root and os.path.isdir(root):
        yield from _walk_for(root, "*.gxw", skip=base)


def _listing(folder):
    """Return a folder's entry names, or nothing when it cannot be read."""
    try:
        return sorted(os.listdir(folder))
    except OSError:
        return []


def _walk_for(root, pattern, skip=None):
    """Yield the files matching ``pattern`` under ``root``, bounded.

    The walk prunes as it goes rather than filtering afterwards, so the cost
    is the folders kept, not the ones there are. What it prunes matters more
    than the depth: a GRASS **mapset** (a folder holding a `WIND` file) is
    where a database's maps are -- tens of thousands of files on this machine
    -- and holds no workspace, so it is never listed.

    :param skip: a folder not to walk at all, its subfolders included; the
        GRASS database passes itself, having been listed the cheap way
    """
    root = os.path.abspath(root)
    skip = os.path.abspath(skip) if skip else None
    depth_of = root.rstrip(os.sep).count(os.sep)
    for folder, children, files in os.walk(root, onerror=lambda _: None):
        if skip and (folder == skip or folder.startswith(skip + os.sep)):
            children[:] = []
            continue
        if "WIND" in files:
            # A mapset: its maps are not workspaces, and listing them is the
            # whole cost of a scan over a GRASS database.
            children[:] = []
            continue
        if folder.rstrip(os.sep).count(os.sep) - depth_of >= WORKSPACE_DEPTH:
            children[:] = []
        else:
            children[:] = [
                child
                for child in children
                if not child.startswith(".") and child not in WORKSPACE_SKIP
            ]
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                yield os.path.join(folder, name)


def read_workspace(path):
    """Return what a ``.gxw`` workspace names, or None when it is not one.

    The parts that matter here are the session (which database, project and
    mapset it belongs to), the layers of its **first** map display, and that
    display's extent. The rest of the file is the GRASS GUI's own window
    layout, which RustGIS has no use for.

    A layer is kept only when it names a map of a kind RustGIS can hold: a
    ``d.rast`` or ``d.vect`` layer has a ``name`` of ``map@mapset``, while a
    command layer or a 3D view has nothing to add.

    :return: ``{"project", "mapset", "database", "layers", "extent",
        "displays"}``, or None when the file is not a readable workspace
    """
    try:
        if os.path.getsize(path) > WORKSPACE_MAX_BYTES:
            return None
        root = ElementTree.parse(path).getroot()
    except (OSError, ElementTree.ParseError, ValueError):
        return None
    if root.tag != "gxw":
        return None
    session_part = root.find("session")
    if session_part is None:
        return None
    named = {
        part: (session_part.findtext(part) or "").strip()
        for part in ("database", "location", "mapset")
    }
    if not named["location"] or not named["mapset"]:
        return None

    displays = root.findall("display")
    layers, extent = [], None
    if displays:
        extent = _display_extent(displays[0].get("extent"))
        for layer in displays[0].findall("layer"):
            kind = (layer.get("type") or "").strip()
            name = (layer.get("name") or "").strip()
            if kind not in ("raster", "vector") or "@" not in name:
                continue
            map_name, _, mapset = name.partition("@")
            layers.append(
                {
                    "kind": kind,
                    "map": map_name,
                    "mapset": mapset or named["mapset"],
                    # GRASS writes checked="1" for a layer that was shown.
                    "shown": (layer.get("checked") or "1").strip() != "0",
                }
            )
    return {
        "database": named["database"],
        "project": named["location"],
        "mapset": named["mapset"],
        "layers": layers,
        "extent": extent,
        "displays": len(displays),
    }


def _display_extent(text):
    """Return ``[west, south, east, north]`` from a display's ``extent``.

    GRASS writes six numbers, the last two being the height range, and they
    are in the **project's own** coordinate system, not degrees.
    """
    parts = [part for part in (text or "").split(",") if part.strip()]
    if len(parts) < 4:
        return None
    try:
        west, south, east, north = (float(part) for part in parts[:4])
    except ValueError:
        return None
    if west >= east or south >= north:
        return None
    return [west, south, east, north]


def workspace_node(path):
    """Return the tree node id naming one workspace file.

    The path is percent-encoded, because it holds the separator the other node
    ids are built from and would otherwise be read as a project and a mapset.
    """
    return "workspace" + SEP + urllib.parse.quote(path, safe="")


def parse_workspace_node(node):
    """Return the path a workspace node names.

    :raises session.GrassError: when the id names no workspace
    """
    kind, _, quoted = (node or "").partition(SEP)
    if kind != "workspace" or not quoted:
        raise session.GrassError(
            "choose a GRASS workspace under Workspaces, not a project or a map"
        )
    return urllib.parse.unquote(quoted)


def node_id(kind, project, mapset, name):
    """Return the tree node id naming one map."""
    return f"{kind}{SEP}{project}{SEP}{mapset}{SEP}{name}"


def parse_node(node):
    """Return ``(kind, project, mapset, name)`` for a map's node id.

    :raises session.GrassError: when the id names no map
    """
    parts = (node or "").split(SEP, 3)
    if len(parts) != 4 or parts[0] not in ("raster", "vector", "group"):
        raise session.GrassError(
            "choose a map or an imagery group in the GRASS Data tree, not a "
            "project or a mapset"
        )
    return tuple(parts)


def tree(base, open_mapset=None, home=None):
    """Return the panel tree of a database, and what it had to leave out.

    Every project and mapset is listed, but a mapset's maps only when it is
    the one chosen: a database here holds 35,000 maps, far past the 5,000
    nodes a panel tree takes, and listing them all would be useless anyway.
    Choosing a mapset asks for its maps, which is what the tree's command is
    for.

    :param open_mapset: ``(project, mapset)`` to list the maps of
    :param home: where to look for workspaces besides the database, or None
        for the user's home folder; ``""`` looks nowhere but the database
    :return: ``(nodes, [note, ...])``
    """
    nodes, notes = [], []
    # The workspaces come first: a workspace is a project someone already set
    # up, so offering them above the raw projects and mapsets is offering the
    # finished thing before its parts.
    found = workspaces(base, home)
    if found:
        nodes.append(
            {
                "id": "branch" + SEP + "workspaces",
                "label": f"Workspaces ({len(found)})",
                "count": len(found),
                "children": [
                    {
                        "id": workspace_node(path),
                        "label": _workspace_label(path, workspace),
                    }
                    for path, workspace in found[:MAX_NODES]
                ],
            }
        )
        if len(found) > MAX_NODES:
            notes.append(
                f"{len(found)} workspaces were found; the tree shows the first "
                f"{MAX_NODES}, which is what it takes."
            )
    for project in projects(base):
        branches = []
        for mapset in mapsets(base, project):
            found = maps(base, project, mapset)
            sets = (
                groups(base, project, mapset)
                if open_mapset == (project, mapset)
                else []
            )
            if not found:
                continue
            branch = {
                "id": f"mapset{SEP}{project}{SEP}{mapset}",
                "label": mapset,
                "count": len(found),
            }
            if open_mapset == (project, mapset):
                shown = found[:MAX_NODES]
                # The groups go first: a group is what the bands under it are
                # for, so offering it above them is offering the composite
                # before the parts.
                branch["children"] = [
                    {
                        "id": node_id("group", project, mapset, name),
                        # A group of one band cannot be composed into a
                        # picture, so the label says so rather than letting
                        # Add Map refuse it as a surprise.
                        "label": f"{name} (group of {len(members)})"
                        if len(members) > 1
                        else f"{name} (group of 1, not a composite)",
                    }
                    for name, members in sets
                ] + [
                    {
                        "id": node_id(kind, project, mapset, name),
                        "label": f"{name} ({kind})",
                    }
                    for kind, name in shown
                ]
                if len(shown) < len(found):
                    branch["label"] = f"{mapset} (first {len(shown)})"
                    notes.append(
                        f"{project}/{mapset} holds {len(found)} maps; the tree "
                        f"shows the first {len(shown)}, which is what it takes."
                    )
            branches.append(branch)
        if branches:
            nodes.append(
                {
                    "id": f"project{SEP}{project}",
                    "label": project,
                    "count": sum(b["count"] for b in branches),
                    "children": branches,
                }
            )
    return nodes, notes


def _workspace_label(path, workspace):
    """Return the tree label for one workspace.

    It says the project and mapset it opens and how many layers it holds,
    because the file name is almost always ``default.gxw`` and would tell the
    user nothing.
    """
    where = f"{workspace['project']}/{workspace['mapset']}"
    layers = len(workspace["layers"])
    folder = os.path.basename(os.path.dirname(path)) or path
    counted = "1 layer" if layers == 1 else f"{layers} layers"
    return f"{where} ({counted}) - {folder}/{os.path.basename(path)}"


def opened(node):
    """Return the ``(project, mapset)`` a chosen node belongs to, or None."""
    parts = (node or "").split(SEP, 3)
    if len(parts) == 3 and parts[0] == "mapset":
        return parts[1], parts[2]
    if len(parts) == 4 and parts[0] in ("raster", "vector", "group"):
        return parts[1], parts[2]
    return None


def chosen_mapset(base, node):
    """Return the ``(project, mapset)`` a chosen node names, if it is a mapset.

    A node naming a map (``raster/Project/MAPSET/name``) also answers with its
    mapset, so a run writes beside the map the user was looking at. Names are
    checked to be one folder each, so a crafted node cannot walk out of the
    database.

    :return: ``(project, mapset)``, or None when the node names no mapset
    """
    found = opened(node)
    if not found:
        return None
    for part in found:
        if part in ("", ".", "..") or SEP in part or "\\" in part:
            return None
    project, mapset = found
    if not os.path.isfile(os.path.join(base, project, mapset, "WIND")):
        return None
    return found


def _size(count):
    """Return a byte count a reader can take in at a glance."""
    for unit in ("bytes", "kB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "bytes" else f"{count:.1f} {unit}"
        count /= 1024.0
    return f"{count:.1f} GB"


class Export(session.Run):
    """Exporting one map of the user's own database, without locking it."""

    def export(self, base, kind, project, mapset, name, target):
        """Write one map to a file RustGIS reads, and say what was done.

        The work happens in a throwaway mapset of that project, so the user's
        own mapset is never locked and nothing of theirs is written to. The
        map is read across mapsets as ``name@mapset``.

        :param kind: ``"raster"`` or ``"vector"``
        :param target: the file to write
        :return: ``[message, ...]``
        :raises session.GrassError: when any step fails
        """
        full = f"{name}@{mapset}"
        project_path = os.path.join(base, project)
        self.progress(f"Exporting {full} from {project}...")
        if kind == "raster":
            # The region, not the map, decides what r.out.gdal writes, and a
            # throwaway mapset starts on the project's default region.
            steps = [
                ["g.region", f"raster={full}"],
                [
                    "r.out.gdal",
                    f"input={full}",
                    f"output={target}",
                    "format=GTiff",
                    "-c",
                    "--overwrite",
                    "--quiet",
                ],
            ]
        else:
            # GeoPackage rather than GeoJSON: it carries the coordinate system,
            # where GeoJSON would be read as longitude and latitude.
            steps = [
                [
                    "v.out.ogr",
                    f"input={full}",
                    f"output={target}",
                    "format=GPKG",
                    "--overwrite",
                    "--quiet",
                ]
            ]
        self._in_temp_mapset(project_path, steps)
        if not os.path.exists(target):
            raise session.GrassError(f"nothing was written for {full}")
        where = (
            f"{full} exported from {project} to {target} "
            f"({_size(os.path.getsize(target))})."
        )
        messages = [where]
        for text, count in self.warnings.items():
            messages.append(
                f"GRASS: {text}" + (f" ({count} times)" if count > 1 else "")
            )
        return messages

    def datasets(self, base, project, mapset, kind="strds"):
        """Return the space-time datasets of one mapset, by name.

        A dataset is not a folder: it is a row in the mapset's own temporal
        database (``<mapset>/tgis/sqlite.db``), so unlike the maps it cannot
        be read from the file system and ``t.list`` is asked instead. It runs
        in a throwaway mapset naming the user's with ``mapset=``, so their own
        is never locked.

        Nothing here is fatal: a project with no temporal database, or a
        GRASS without the temporal framework, simply has no dataset to offer,
        and the form says so rather than the panel failing to open.

        :param kind: ``strds``, ``str3ds`` or ``stvds``
        :return: ``["name@mapset", ...]``, empty when there are none
        """
        path = os.path.join(base, project)
        command = [
            self.grass,
            "--tmp-mapset",
            path + os.sep,
            "--exec",
            "t.list",
            f"type={kind}",
            f"mapset={mapset}",
            "format=line",
            "--quiet",
        ]
        try:
            out = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=self.left(),
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if out.returncode != 0:
            return []
        found = []
        for line in (out.stdout or "").splitlines():
            for name in line.split(","):
                name = name.strip()
                if name and "@" in name:
                    found.append(name)
        return sorted(set(found))

    def _in_temp_mapset(self, project_path, steps):
        """Run modules in a throwaway mapset of one of the user's projects.

        ``--tmp-mapset`` makes and removes a mapset of its own, so the user's
        mapsets keep their own locks and a session of theirs open elsewhere is
        not disturbed.
        """
        for step in steps:
            command = [
                self.grass,
                "--tmp-mapset",
                project_path + os.sep,
                "--exec",
                *step,
            ]
            try:
                out = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=self.left(),
                )
            except subprocess.TimeoutExpired as e:
                raise session.GrassError(f"{step[0]}: gave up waiting") from e
            except OSError as e:
                raise session.GrassError(f"{step[0]}: {e}") from e
            if out.returncode != 0:
                raise session.GrassError(f"{step[0]}: {session._why(out)}")
            for text in session._warnings(out.stderr or ""):
                self.warnings[text] = self.warnings.get(text, 0) + 1
