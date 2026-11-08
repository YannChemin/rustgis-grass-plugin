"""Integration tests for rendering a display module to a GeoTIFF.

These run the installed GRASS, so they are skipped when it is absent or when
the GDAL Python bindings used to make the inputs are not available.

SPDX-License-Identifier: Unlicense
"""

import json
import subprocess

import pytest

from grass_bridge import session

np = pytest.importorskip("numpy")
gdal = pytest.importorskip("osgeo.gdal")

pytestmark = pytest.mark.skipif(
    session.find_grass() is None, reason="GRASS GIS is not installed"
)


def raster(path, function, width=120, height=80):
    """Write a small georeferenced GeoTIFF and return its path."""
    dataset = gdal.GetDriverByName("GTiff").Create(
        str(path), width, height, 1, gdal.GDT_Byte
    )
    dataset.SetGeoTransform([10.0, 0.01, 0.0, 20.0, 0.0, -0.01])
    dataset.SetProjection("EPSG:4326")
    band = dataset.GetRasterBand(1)
    band.SetNoDataValue(255)
    band.WriteArray(
        np.fromfunction(function, (height, width)).astype("uint8")
    )
    dataset = None
    return str(path)


def make_project(tmp_path):
    """Make a GRASS database with one project and return ``(base, project)``."""
    base = tmp_path / "db"
    base.mkdir()
    project = base / "P"
    subprocess.run(
        [
            session.find_grass(),
            "-c",
            "EPSG:4326",
            str(project),
            "--exec",
            "g.version",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return base, project


def import_into(project, *args):
    """Run one import in the project's PERMANENT mapset."""
    subprocess.run(
        [session.find_grass(), str(project / "PERMANENT"), "--exec", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def check_picture(path, width=120, height=80):
    """Open a rendered GeoTIFF and return it, checking it is an RGB picture."""
    dataset = gdal.Open(str(path))
    assert dataset is not None, f"no GeoTIFF at {path}"
    assert (dataset.RasterXSize, dataset.RasterYSize) == (width, height)
    assert dataset.RasterCount == 3
    assert dataset.GetProjection()
    return dataset


def test_a_raster_display_module_renders_an_rgb_picture(tmp_path):
    base, project = make_project(tmp_path)
    source = raster(
        tmp_path / "a.tif", lambda y, x: (x * 3 + y * 2) % 250
    )
    import_into(project, "r.in.gdal", f"input={source}", "output=src1")
    target = tmp_path / "out.tif"
    with session.DisplayRun() as run:
        messages = run.render_mapset(
            str(base),
            "P",
            "PERMANENT",
            "d.rast",
            ["map=src1@PERMANENT"],
            ["src1@PERMANENT"],
            [],
            str(target),
        )
    dataset = check_picture(target)
    west, _, _, north = dataset.GetGeoTransform()[:4]
    assert abs(west - 10.0) < 1e-9 and abs(north - 20.0) < 1e-9
    assert any("rendered" in message for message in messages)


def test_his_and_rgb_render_several_maps_of_the_same_mapset(tmp_path):
    base, project = make_project(tmp_path)
    red = raster(tmp_path / "r.tif", lambda y, x: (x * 2) % 250)
    green = raster(tmp_path / "g.tif", lambda y, x: (y * 3) % 250)
    blue = raster(tmp_path / "b.tif", lambda y, x: (x + y) % 250)
    for name, path in (("src1", red), ("src2", green), ("src3", blue)):
        import_into(project, "r.in.gdal", f"input={path}", f"output={name}")
    maps = ["src1@PERMANENT", "src2@PERMANENT", "src3@PERMANENT"]
    for module, args in (
        ("d.his", ["hue=src1@PERMANENT", "intensity=src2@PERMANENT",
                   "saturation=src3@PERMANENT"]),
        ("d.rgb", ["red=src1@PERMANENT", "green=src2@PERMANENT",
                   "blue=src3@PERMANENT"]),
    ):
        target = tmp_path / f"{module.replace('.', '_')}.tif"
        with session.DisplayRun() as run:
            run.render_mapset(
                str(base), "P", "PERMANENT", module, args, maps, [], str(target)
            )
        check_picture(target)


def test_a_vector_display_module_renders_and_frames_the_vector(tmp_path):
    base, project = make_project(tmp_path)
    vector = tmp_path / "vector.geojson"
    vector.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"value": 1},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [10.1, 19.1],
                                    [10.9, 19.1],
                                    [10.9, 19.9],
                                    [10.1, 19.9],
                                    [10.1, 19.1],
                                ]
                            ],
                        },
                    }
                ],
            }
        )
    )
    import_into(project, "v.in.ogr", f"input={vector}", "output=src1")
    target = tmp_path / "vect.tif"
    with session.DisplayRun() as run:
        run.render_mapset(
            str(base),
            "P",
            "PERMANENT",
            "d.vect",
            ["map=src1@PERMANENT", "display=shape", "color=red"],
            [],
            ["src1@PERMANENT"],
            str(target),
        )
    dataset = check_picture(target, 1001, 1001)
    west, res, _, north = dataset.GetGeoTransform()[:4]
    assert west == pytest.approx(10.1, abs=1e-3)
    assert north == pytest.approx(19.9, abs=1e-3)
    assert res > 0
