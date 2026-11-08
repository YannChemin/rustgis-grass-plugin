"""Integration tests for rendering a display module to a GeoTIFF.

These run the installed GRASS, so they are skipped when it is absent or when
the GDAL Python bindings used to make the inputs are not available.

SPDX-License-Identifier: Unlicense
"""

import json

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


def check_picture(path, width=120, height=80):
    """Open a rendered GeoTIFF and return it, checking it is an RGB picture."""
    dataset = gdal.Open(str(path))
    assert dataset is not None, f"no GeoTIFF at {path}"
    assert (dataset.RasterXSize, dataset.RasterYSize) == (width, height)
    assert dataset.RasterCount == 3
    assert dataset.GetProjection()
    return dataset


def test_a_raster_display_module_renders_an_rgb_picture(tmp_path):
    source = raster(
        tmp_path / "a.tif", lambda y, x: (x * 3 + y * 2) % 250
    )
    target = tmp_path / "out.tif"
    with session.DisplayRun() as run:
        messages = run.render(
            "d.rast", ["map=src1"], [("raster", source, "src1")], str(target)
        )
    dataset = check_picture(target)
    west, _, _, north = dataset.GetGeoTransform()[:4]
    assert abs(west - 10.0) < 1e-9 and abs(north - 20.0) < 1e-9
    assert any("rendered" in message for message in messages)


def test_his_and_rgb_render_several_layers(tmp_path):
    red = raster(tmp_path / "r.tif", lambda y, x: (x * 2) % 250)
    green = raster(tmp_path / "g.tif", lambda y, x: (y * 3) % 250)
    blue = raster(tmp_path / "b.tif", lambda y, x: (x + y) % 250)
    layers = [
        ("raster", red, "src1"),
        ("raster", green, "src2"),
        ("raster", blue, "src3"),
    ]
    for module, args in (
        ("d.his", ["hue=src1", "intensity=src2", "saturation=src3"]),
        ("d.rgb", ["red=src1", "green=src2", "blue=src3"]),
    ):
        target = tmp_path / f"{module.replace('.', '_')}.tif"
        with session.DisplayRun() as run:
            run.render(module, args, layers, str(target))
        check_picture(target)


def test_a_vector_display_module_renders_and_frames_the_vector(tmp_path):
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
    target = tmp_path / "vect.tif"
    with session.DisplayRun() as run:
        run.render(
            "d.vect",
            ["map=src1", "display=shape", "color=red"],
            [("vector", str(vector), "src1")],
            str(target),
        )
    dataset = check_picture(target, 1001, 1001)
    west, res, _, north = dataset.GetGeoTransform()[:4]
    assert west == pytest.approx(10.1, abs=1e-3)
    assert north == pytest.approx(19.9, abs=1e-3)
    assert res > 0
