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

import math
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


def catalogue_tree(catalogue, chosen=None):
    """Return the panel tree of every module installed, by family.

    A tree holds 5,000 nodes and there are about 1,200 modules, so all of them
    fit; what a manifest cannot hold is a tool or a command for each.

    :param catalogue: the entries ``generate_manifest.py`` wrote
    :param chosen: the module whose family is opened
    :return: ``(nodes, [note, ...])``
    """
    families = {}
    for entry in catalogue:
        families.setdefault(entry["family"], []).append(entry)
    nodes = []
    for family in sorted(families):
        entries = sorted(families[family], key=lambda e: e["module"])
        nodes.append(
            {
                "id": f"family/{family}",
                "label": family,
                "count": len(entries),
                "children": [
                    {
                        "id": entry["module"],
                        # A leading mark tells the modules Run Module can
                        # drive from the ones that would need a form.
                        "label": (
                            f"{'▸ ' if entry.get('raster') else '  '}"
                            f"{entry['module']}"
                            + (
                                f" - {entry['summary'][:90]}"
                                if entry["summary"]
                                else ""
                            )
                        ),
                    }
                    for entry in entries
                ],
            }
        )
    notes = []
    if chosen:
        entry = next((e for e in catalogue if e["module"] == chosen), None)
        if entry and not entry["raster"]:
            notes.append(
                f"{chosen} does not take a raster and write one, so Run Module "
                "cannot drive it; a module needing a form has to be a tool."
            )
    return nodes, notes


def entry_for(catalogue, module):
    """Return one module's catalogue entry.

    :raises session.GrassError: when the tree holds no such module
    """
    for entry in catalogue:
        if entry["module"] == module:
            return entry
    raise session.GrassError(
        "choose a module in the GRASS Modules tree, not a family"
        if str(module or "").startswith("family/")
        else f"'{module}' is not a module of this GRASS installation"
    )


def free_module_args(entry):
    """Return the arguments for running one module on ``src`` into ``out``.

    Only a module that reads a raster and writes one can be driven this way:
    the bridge names its input and its output and leaves every other parameter
    at GRASS's own default, because a command has no form to ask with.

    :raises session.GrassError: when the module takes no raster, or writes none
    """
    if not entry.get("raster"):
        raise session.GrassError(
            f"{entry['module']} does not read a raster and write one, so it "
            "cannot be run from the tree; the modules that can are marked in it"
        )
    return [
        f"{entry['raster_in'][0]}=src",
        f"{entry['raster_out'][0]}=out",
    ]


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
