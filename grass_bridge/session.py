"""Running one GRASS module over GeoJSON, in a throwaway project.

A run makes its own GISDBASE in a temporary folder, so nothing of the user's
is touched and no lock outlives it.  Vector data arrives in longitude/latitude
(GeoJSON), is worked on in the metric projection of its own area, and is
projected back before it leaves, so a module's distances and areas are in
metres rather than degrees.

Progress is reported to MetaMonitor (https://github.com/YannChemin/MetaMonitor)
when mmctl is installed; without it the run is unaffected.

SPDX-License-Identifier: Unlicense
"""

import json
import os
import shutil
import subprocess
import tempfile
import time

#: Where to look for the GRASS launcher, before the PATH.
ENV = "RUSTGIS_GRASS"

#: A module run gets this long before it is given up on.
TIMEOUT = 1800

#: RustGIS stops a plugin command after this long (docs/plugins.md > The
#: protocol). A command's run keeps inside it and says so, rather than being
#: killed with a half-written file behind it.
COMMAND_LIMIT = 120


class GrassError(Exception):
    """A module, or GRASS itself, refused to do the work."""


def find_grass():
    """Return the GRASS launcher, or None when it is not installed.

    :return: a path to the ``grass`` program
    """
    named = os.environ.get(ENV)
    if named:
        return named if os.access(named, os.X_OK) else None
    found = shutil.which("grass")
    if found:
        return found
    for base in sorted(_candidates(), reverse=True):
        if os.access(base, os.X_OK):
            return base
    return None


def _candidates():
    """Return the usual installation paths, newest-looking last."""
    out = []
    for root in ("/usr/local", "/usr", "/opt"):
        try:
            for name in os.listdir(root):
                if name.startswith("grass"):
                    out.append(os.path.join(root, name, "bin", name))
        except OSError:
            continue
    return out


def version(grass=None):
    """Return the installed GRASS version, or None."""
    grass = grass or find_grass()
    if not grass:
        return None
    try:
        out = subprocess.run(
            [grass, "--version"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first = out.stdout.splitlines()[0] if out.stdout else ""
    return first.replace("GRASS", "").strip() or None


def interface_description(module, grass=None):
    """Return a module's ``--interface-description`` XML.

    :raises GrassError: when the module or GRASS cannot be run
    """
    grass = grass or find_grass()
    if not grass:
        raise GrassError(
            "GRASS GIS is not installed, or RUSTGIS_GRASS does not name it"
        )
    argv = [grass, "--tmp-project", "XY", "--exec", module, "--interface-description"]
    try:
        out = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=120
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise GrassError(f"{module}: {e}") from e
    if out.returncode != 0 or not out.stdout.strip().startswith("<?xml"):
        raise GrassError(f"{module}: {_why(out)}")
    return out.stdout


def utm_epsg(lon, lat):
    """Return the EPSG code of the UTM zone holding one coordinate."""
    zone = int((lon + 180.0) // 6.0) + 1
    zone = min(60, max(1, zone))
    return (32600 if lat >= 0 else 32700) + zone


#: Widest span of longitude, in degrees, still worked on in a single UTM zone.
UTM_SPAN = 6.0

#: Web Mercator is undefined towards the poles.
MERCATOR_LIMIT = 85.0


def bbox_of(geojson):
    """Return a FeatureCollection's bounding box, or None when it has none.

    :return: ``(min_lon, min_lat, max_lon, max_lat)``
    """
    lons, lats = [], []

    def walk(coords):
        if not isinstance(coords, (list, tuple)) or not coords:
            return
        if isinstance(coords[0], (int, float)) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
                lons.append(lon)
                lats.append(lat)
            return
        for part in coords:
            walk(part)

    for feature in (geojson or {}).get("features") or []:
        geometry = (feature or {}).get("geometry") or {}
        walk(geometry.get("coordinates"))
    if not lons:
        return None
    return (min(lons), min(lats), max(lons), max(lats))


def choose_crs(bbox):
    """Pick the metric projection to work in, and say why.

    A UTM zone is right for data inside one, and wrong for data spanning the
    world: forced into a zone, the coordinates come out invalid and GRASS
    refuses the region. Wider data is worked on in Web Mercator instead, whose
    metres stretch away from the equator.

    :param bbox: ``(min_lon, min_lat, max_lon, max_lat)``
    :return: ``(epsg, reason)``
    :raises GrassError: for data reaching past the limits of both
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    if max(abs(min_lat), abs(max_lat)) > MERCATOR_LIMIT:
        raise GrassError(
            f"the layer reaches latitude {max(abs(min_lat), abs(max_lat)):.1f}\u00b0, beyond what "
            "a metric projection covers here; work on a subset further from the pole"
        )
    lon_span = max_lon - min_lon
    if lon_span <= UTM_SPAN and max(abs(min_lat), abs(max_lat)) <= 84.0:
        centre_lon = (min_lon + max_lon) / 2.0
        centre_lat = (min_lat + max_lat) / 2.0
        epsg = utm_epsg(centre_lon, centre_lat)
        return epsg, f"EPSG:{epsg} (UTM), the zone the layer sits in"
    return 3857, (
        f"EPSG:3857 (Web Mercator), because the layer spans {lon_span:.1f}\u00b0 of longitude, "
        "more than one UTM zone; its metres stretch away from the equator, so distances and "
        "areas are least reliable towards the poles"
    )


def centre_of(geojson):
    """Return the centre of a FeatureCollection's coordinates.

    :return: ``(lon, lat)``, or None when it holds no usable coordinate
    """
    lons, lats = [], []

    def walk(coords):
        if not isinstance(coords, (list, tuple)) or not coords:
            return
        if isinstance(coords[0], (int, float)) and len(coords) >= 2:
            lon, lat = coords[0], coords[1]
            if isinstance(lon, (int, float)) and isinstance(lat, (int, float)):
                lons.append(lon)
                lats.append(lat)
            return
        for part in coords:
            walk(part)

    for feature in (geojson or {}).get("features") or []:
        geometry = (feature or {}).get("geometry") or {}
        walk(geometry.get("coordinates"))
    if not lons:
        return None
    return (sum(lons) / len(lons), sum(lats) / len(lats))


def _warnings(text):
    """Return the whole of each warning GRASS wrote.

    GRASS wraps a long warning over several lines, continuing it indented
    under the first, so taking only the line holding ``WARNING`` cuts the
    sentence in half.

    :param text: a module's error output
    :return: one tidy line per warning, in the order they were written
    """
    out, inside = [], False
    for line in text.splitlines():
        if "WARNING" in line:
            out.append(line.split("WARNING:", 1)[-1].strip())
            inside = True
        elif inside and line.startswith((" ", "\t")) and line.strip():
            out[-1] = f"{out[-1]} {line.strip()}"
        elif line.strip():
            # Any other output ends the warning being continued.
            inside = False
    return [line for line in out if line]


def _why(out):
    """Return the most useful line of a failed run's output."""
    text = (out.stderr or "") + (out.stdout or "")
    fatal = [line for line in text.splitlines() if "ERROR" in line or "FATAL" in line]
    if fatal:
        return fatal[-1].strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else f"exited with status {out.returncode}"


class Run:
    """One module run: its own GISDBASE, removed when the run ends."""

    def __init__(self, grass=None, progress=None, deadline=None):
        self.grass = grass or find_grass()
        if not self.grass:
            raise GrassError(
                "GRASS GIS is not installed, or RUSTGIS_GRASS does not name it"
            )
        self.progress = progress or (lambda text: None)
        # When set, the moment (time.monotonic) by which every step must be
        # over: a command's whole run has to fit in what RustGIS allows it.
        self.deadline = deadline
        self.dir = tempfile.mkdtemp(prefix="rustgis-grass-")
        self.messages = []
        # One entry per distinct warning, with how often GRASS said it: a
        # module repeats the same line for every step it runs.
        self.warnings = {}

    def close(self):
        """Remove the whole throwaway database, locks included."""
        shutil.rmtree(self.dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def left(self):
        """Return the seconds a step may take, from the run's deadline.

        :raises GrassError: when the time allowed is already spent
        """
        if self.deadline is None:
            return TIMEOUT
        left = self.deadline - time.monotonic()
        if left <= 1.0:
            raise GrassError(
                f"the work did not fit in the {COMMAND_LIMIT} seconds RustGIS gives a "
                "plugin command; run it on a smaller raster, or zoom in and export the "
                "part you need"
            )
        return left

    def _project(self, name, crs):
        """Create a project for ``crs`` and return its path.

        :param crs: an EPSG code, ``"XY"``, or a georeferenced file whose own
            coordinate system the project takes
        """
        path = os.path.join(self.dir, name)
        argv = [self.grass, "-c", crs, path, "-e"]
        out = subprocess.run(
            argv, capture_output=True, text=True, check=False, timeout=self.left()
        )
        if out.returncode != 0 or not os.path.isdir(os.path.join(path, "PERMANENT")):
            raise GrassError(f"cannot create a project from {crs}: {_why(out)}")
        return path

    def exec(self, project, module, *args):
        """Run one module in ``project`` and return its standard output."""
        argv = [self.grass, os.path.join(project, "PERMANENT"), "--exec", module, *args]
        allowed = self.left()
        try:
            out = subprocess.run(
                argv, capture_output=True, text=True, check=False, timeout=allowed
            )
        except subprocess.TimeoutExpired as e:
            raise GrassError(f"{module}: gave up after {allowed:.0f} seconds") from e
        except OSError as e:
            raise GrassError(f"{module}: {e}") from e
        if out.returncode != 0:
            raise GrassError(f"{module}: {_why(out)}")
        for text in _warnings(out.stderr or ""):
            self.warnings[text] = self.warnings.get(text, 0) + 1
        return out.stdout

    def vector_tool(self, module, geojson, params, flags=()):
        """Run a vector module over a FeatureCollection.

        :param module: the GRASS module, such as ``v.voronoi``
        :param geojson: the input layer as a FeatureCollection
        :param params: the module's own ``key=value`` parameters
        :param flags: single-letter flags to pass
        :return: ``(FeatureCollection, [message, ...])``
        :raises GrassError: when any step fails
        """
        features = (geojson or {}).get("features") or []
        if not features:
            raise GrassError("the input layer has no features")
        bbox = bbox_of(geojson)
        if bbox is None:
            raise GrassError("the input layer has no usable coordinates")
        epsg, reason = choose_crs(bbox)

        self.progress("Preparing a working project…")
        work = self._project(f"work_{epsg}", f"EPSG:{epsg}")
        latlon = self._project("latlon", "EPSG:4326")
        source = os.path.join(self.dir, "input.geojson")
        with open(source, "w", encoding="utf-8") as fh:
            json.dump(geojson, fh)

        self.progress(f"Importing {len(features)} features…")
        self.exec(
            work, "v.import", f"input={source}", "output=src", "--overwrite", "--quiet"
        )

        # The computational region, not the inputs, decides what a module sees:
        # a new project's region is one cell at the origin, so every feature
        # would fall outside it. v.voronoi reports "0 points" that way, and a
        # raster module would quietly write a single cell.
        self.exec(work, "g.region", "vector=src")
        region = self.exec(work, "g.region", "-g").split()
        extent = {
            k: v for k, v in (line.split("=", 1) for line in region if "=" in line)
        }
        # Vector modules work on geometry, not cells, and g.region's default
        # resolution of one metre over a wide extent gives a region of tens of
        # millions of them. Keep the grid sane for any module that does read it.
        try:
            width = float(extent["e"]) - float(extent["w"])
            height = float(extent["n"]) - float(extent["s"])
            res = max(1.0, round(max(width, height) / 2000.0))
            self.exec(work, "g.region", f"res={res:g}", "-a")
            extent["res"] = f"{res:g}"
        except (KeyError, ValueError, GrassError):
            pass

        self.progress(f"Running {module}…")
        argv = ["input=src", "output=out", *[f"{k}={v}" for k, v in params.items()]]
        argv += [f"-{f}" for f in flags]
        self.exec(work, module, *argv, "--overwrite", "--quiet")

        self.progress("Projecting the result back to longitude/latitude…")
        self.exec(
            latlon,
            "v.proj",
            f"project={os.path.basename(work)}",
            "mapset=PERMANENT",
            f"dbase={self.dir}",
            "input=out",
            "output=out_ll",
            "--overwrite",
            "--quiet",
        )
        target = os.path.join(self.dir, "output.geojson")
        self.exec(
            latlon,
            "v.out.ogr",
            "input=out_ll",
            f"output={target}",
            "format=GeoJSON",
            "--overwrite",
            "--quiet",
        )
        with open(target, encoding="utf-8") as fh:
            result = json.load(fh)

        self.messages.insert(
            0,
            (
                f"{module} ran in {reason}. Distances and areas are in metres, and the result is "
                "projected back to longitude/latitude."
            ),
        )
        if extent:
            self.messages.insert(
                1,
                (
                    "Computational region set from the input layer: "
                    f"{float(extent.get('w', 0)):.0f} to {float(extent.get('e', 0)):.0f} east, "
                    f"{float(extent.get('s', 0)):.0f} to {float(extent.get('n', 0)):.0f} north"
                    + (f", at {extent['res']} m." if extent.get("res") else ".")
                ),
            )
        for text, count in self.warnings.items():
            self.messages.append(
                f"GRASS: {text}" + (f" ({count} times)" if count > 1 else "")
            )
        return result, list(self.messages)
