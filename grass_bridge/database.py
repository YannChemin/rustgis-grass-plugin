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

import os
import subprocess

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

    :return: ``kind`` is ``"raster"`` or ``"vector"``
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
    return out


def node_id(kind, project, mapset, name):
    """Return the tree node id naming one map."""
    return f"{kind}{SEP}{project}{SEP}{mapset}{SEP}{name}"


def parse_node(node):
    """Return ``(kind, project, mapset, name)`` for a map's node id.

    :raises session.GrassError: when the id names no map
    """
    parts = (node or "").split(SEP, 3)
    if len(parts) != 4 or parts[0] not in ("raster", "vector"):
        raise session.GrassError(
            "choose a map in the GRASS Data tree, not a project or a mapset"
        )
    return tuple(parts)


def tree(base, open_mapset=None):
    """Return the panel tree of a database, and what it had to leave out.

    Every project and mapset is listed, but a mapset's maps only when it is
    the one chosen: a database here holds 35,000 maps, far past the 5,000
    nodes a panel tree takes, and listing them all would be useless anyway.
    Choosing a mapset asks for its maps, which is what the tree's command is
    for.

    :param open_mapset: ``(project, mapset)`` to list the maps of
    :return: ``(nodes, [note, ...])``
    """
    nodes, notes = [], []
    for project in projects(base):
        branches = []
        for mapset in mapsets(base, project):
            found = maps(base, project, mapset)
            if not found:
                continue
            branch = {
                "id": f"mapset{SEP}{project}{SEP}{mapset}",
                "label": mapset,
                "count": len(found),
            }
            if open_mapset == (project, mapset):
                shown = found[:MAX_NODES]
                branch["children"] = [
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


def opened(node):
    """Return the ``(project, mapset)`` a chosen node belongs to, or None."""
    parts = (node or "").split(SEP, 3)
    if len(parts) == 3 and parts[0] == "mapset":
        return parts[1], parts[2]
    if len(parts) == 4 and parts[0] in ("raster", "vector"):
        return parts[1], parts[2]
    return None


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
