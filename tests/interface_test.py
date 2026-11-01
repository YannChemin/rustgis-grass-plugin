"""Tests for the GRASS parameter mapping and the plugin protocol.

The XML here is written for these tests, not taken from a GRASS installation,
so no module description of GRASS's travels with this repository.

SPDX-License-Identifier: Unlicense
"""

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from grass_bridge import interface, session

TASK = """<?xml version="1.0" encoding="UTF-8"?>
<task name="v.example">
  <label>Does something to a vector map.</label>
  <keywords>vector, example</keywords>
  <parameter name="input" type="string" required="yes" multiple="no">
    <description>Name of the input map</description>
    <gisprompt age="old" element="vector" prompt="vector" />
  </parameter>
  <parameter name="output" type="string" required="yes" multiple="no">
    <description>Name for the output map</description>
    <gisprompt age="new" element="vector" prompt="vector" />
  </parameter>
  <parameter name="elevation" type="string" required="no" multiple="no">
    <description>A raster this bridge cannot pass</description>
    <gisprompt age="old" element="cell" prompt="raster" />
  </parameter>
  <parameter name="helper" type="string" required="yes" multiple="no">
    <description>A second vector map</description>
    <gisprompt age="old" element="vector" prompt="vector" />
  </parameter>
  <parameter name="distance" type="float" required="no" multiple="no">
    <description>A distance in map units</description>
    <default>25.5</default>
  </parameter>
  <parameter name="method" type="string" required="no" multiple="no">
    <description>How to do it</description>
    <default>fast</default>
    <values>
      <value><name>fast</name></value>
      <value><name>careful</name></value>
    </values>
  </parameter>
  <parameter name="label" type="string" required="no" multiple="no">
    <description>Free text</description>
  </parameter>
  <flag name="t">
    <description>Do the optional extra</description>
  </flag>
  <flag name="overwrite">
    <description>Allow output files to overwrite existing files</description>
  </flag>
  <flag name="quiet">
    <description>Quiet module output</description>
  </flag>
</task>
"""


@pytest.fixture
def form():
    return interface.parse(TASK)


def test_reads_the_module_and_its_summary(form):
    assert form["module"] == "v.example"
    assert form["summary"] == "Does something to a vector map."


def test_maps_each_parameter_to_a_plugin_kind(form):
    kinds = {p["name"]: p["kind"] for p in form["params"]}
    assert kinds["helper"] == "vectorLayer"
    assert kinds["distance"] == "number"
    assert kinds["method"] == "choice"
    assert kinds["label"] == "text"
    assert kinds["flag_t"] == "bool"


def test_leaves_out_what_a_plugin_tool_cannot_carry(form):
    names = [p["name"] for p in form["params"]]
    # The output is named by the bridge; a raster cannot reach a plugin tool.
    assert "output" not in names
    assert "elevation" not in names
    assert form["skipped"] == ["elevation"]


def test_drops_the_flags_every_module_has(form):
    names = [p["name"] for p in form["params"]]
    assert "flag_overwrite" not in names and "flag_quiet" not in names


def test_keeps_choices_and_defaults(form):
    method = next(p for p in form["params"] if p["name"] == "method")
    assert method["choices"] == ["fast", "careful"]
    assert method["default"] == "fast"
    distance = next(p for p in form["params"] if p["name"] == "distance")
    assert distance["default"] == 25.5


def test_required_parameters_survive_truncation():
    many = TASK.replace(
        "</task>",
        "".join(
            f'<parameter name="p{i}" type="float" required="no"><description>x</description>'
            f"</parameter>"
            for i in range(40)
        )
        + "</task>",
    )
    form = interface.parse(many)
    assert len(form["params"]) == interface.MAX_PARAMS
    assert next(p for p in form["params"] if p["name"] == "helper")["required"] is True
    assert form["skipped"]


def test_refuses_what_is_not_a_module_description():
    with pytest.raises(ValueError):
        interface.parse("<html><body>not a task</body></html>")
    with pytest.raises(ValueError):
        interface.parse("not xml at all")


def test_utm_zone_from_a_coordinate():
    assert session.utm_epsg(5.4, 43.5) == 32631  # France, north
    assert session.utm_epsg(-60.0, -30.0) == 32721  # Argentina, south
    assert session.utm_epsg(-179.9, 0.0) == 32601
    assert session.utm_epsg(179.9, 0.0) == 32660


def test_centre_of_a_collection_walks_any_geometry():
    fc = {
        "features": [
            {"geometry": {"type": "Point", "coordinates": [0.0, 0.0]}},
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2.0, 2.0], [2.0, 2.0], [2.0, 2.0]]],
                }
            },
        ]
    }
    lon, lat = session.centre_of(fc)
    assert round(lon, 3) == 1.5 and round(lat, 3) == 1.5
    assert session.centre_of({"features": []}) is None
    assert session.centre_of(None) is None


def test_centre_survives_a_hostile_collection():
    fc = {
        "features": [
            None,
            {"geometry": None},
            {"geometry": {"coordinates": None}},
            {"geometry": {"coordinates": ["x", "y"]}},
            {"geometry": {"type": "Point", "coordinates": [1.0, 2.0]}},
        ]
    }
    assert session.centre_of(fc) == (1.0, 2.0)


def test_parameters_and_flags_are_told_apart():
    import main

    declared = [
        {"name": "input", "kind": "vectorLayer"},
        {"name": "distance", "kind": "number"},
        {"name": "method", "kind": "choice"},
        {"name": "label", "kind": "text"},
        {"name": "flag_t", "kind": "bool"},
        {"name": "flag_b", "kind": "bool"},
    ]
    given = {
        "input": "Cities",
        "distance": 100,
        "method": "fast",
        "label": "",
        "flag_t": True,
        "flag_b": False,
    }
    params, flags = main.split_params(declared, given)
    assert params == {"distance": 100, "method": "fast"}  # No input, no empty text.
    assert flags == ["t"]


def test_the_plugin_reports_an_unmapped_tool():
    here = pathlib.Path(__file__).parent.parent
    req = {"abi": 1, "kind": "tool", "id": "no-such-tool", "params": {}, "layers": {}}
    out = subprocess.run(
        [sys.executable, "main.py"],
        cwd=here,
        input=json.dumps(req),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    reply = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" in reply and "no-such-tool" in reply["error"]


def test_the_plugin_refuses_a_request_with_no_layer():
    here = pathlib.Path(__file__).parent.parent
    req = {
        "abi": 1,
        "kind": "tool",
        "id": "v-voronoi",
        "params": {"input": "Missing"},
        "layers": {},
    }
    out = subprocess.run(
        [sys.executable, "main.py"],
        cwd=here,
        input=json.dumps(req),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    reply = json.loads(out.stdout.strip().splitlines()[-1])
    assert "error" in reply and "Missing" in reply["error"]


@pytest.mark.skipif(session.find_grass() is None, reason="GRASS GIS is not installed")
def test_a_real_module_round_trips_through_geojson():
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"n": i},
                "geometry": {
                    "type": "Point",
                    "coordinates": [5.4 + 0.01 * i, 43.5 + 0.013 * (i % 7)],
                },
            }
            for i in range(10)
        ],
    }
    with session.Run() as run:
        result, messages = run.vector_tool("v.delaunay", fc, {})
    assert result["features"], "the module returned no features"
    assert any("EPSG:326" in m for m in messages), "the CRS was not reported"
    assert any("region" in m for m in messages), "the region was not reported"


@pytest.mark.skipif(session.find_grass() is None, reason="GRASS GIS is not installed")
def test_an_empty_layer_fails_loudly():
    with (
        session.Run() as run,
        pytest.raises(session.GrassError, match="no features"),
    ):
        run.vector_tool("v.delaunay", {"type": "FeatureCollection", "features": []}, {})
