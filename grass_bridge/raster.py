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

import os
import time

from . import session

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

    def raster_tool(self, command, source, target, values=None, centre=None):
        """Run one raster module over a GeoTIFF and write another.

        :param command: the local command id, a key of :data:`OPERATIONS`
        :param source: the exported input GeoTIFF
        :param target: where to write the result
        :param values: the panel's widget values
        :param centre: the map's centre as ``(longitude, latitude)``, for a
            module that works from a point
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

        point = None
        if centre is not None and module == "r.viewshed":
            point = self._project_point(project, centre, region)

        argv, notes = module_args(command, values, point)
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
                "Computational region taken from the raster: "
                f"{region.get('cols', '?')} by {region.get('rows', '?')} cells of "
                f"{region.get('ewres', '?')} by {region.get('nsres', '?')}, "
                f"{float(region.get('w', 0)):.0f} to {float(region.get('e', 0)):.0f} east, "
                f"{float(region.get('s', 0)):.0f} to {float(region.get('n', 0)):.0f} north."
            )
        messages += notes
        for text, count in self.warnings.items():
            messages.append(
                f"GRASS: {text}" + (f" ({count} times)" if count > 1 else "")
            )
        return messages

    def _region(self, project):
        """Return ``g.region -g`` as a dictionary."""
        try:
            lines = self.exec(project, "g.region", "-g").split()
        except session.GrassError:
            return {}
        return {k: v for k, v in (line.split("=", 1) for line in lines if "=" in line)}

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
