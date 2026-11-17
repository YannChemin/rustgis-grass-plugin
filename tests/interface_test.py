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
  <parameter name="rules" type="string" required="no" multiple="no">
    <description>Name of file containing rules</description>
    <gisprompt age="old" element="file" prompt="file" />
  </parameter>
  <parameter name="rmsfile" type="string" required="no" multiple="no">
    <description>Name of output file with RMS errors</description>
    <gisprompt age="old" element="file" prompt="file" />
  </parameter>
  <parameter name="table" type="string" required="no" multiple="no">
    <description>A database table this bridge cannot reach</description>
    <gisprompt age="old" element="dbtable" prompt="dbtable" />
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
    # RustGIS hands a tool the file the user picks, so a GRASS file input is
    # offered instead of being left out.
    assert kinds["rules"] == "file"


def test_leaves_out_what_a_plugin_tool_cannot_carry(form):
    names = [p["name"] for p in form["params"]]
    # The output is named by the bridge; a raster, a file the module writes
    # (v.rectify's rmsfile calls itself an old file), and a database table
    # cannot reach a plugin tool.
    assert "output" not in names
    assert "elevation" not in names
    assert "rmsfile" not in names
    assert "table" not in names
    assert form["skipped"] == ["elevation", "rmsfile", "table"]


def test_drops_the_flags_every_module_has(form):
    names = [p["name"] for p in form["params"]]
    assert "flag_overwrite" not in names and "flag_quiet" not in names


def test_keeps_choices_and_defaults(form):
    method = next(p for p in form["params"] if p["name"] == "method")
    assert method["choices"] == ["fast", "careful"]
    assert method["default"] == "fast"
    distance = next(p for p in form["params"] if p["name"] == "distance")
    assert distance["default"] == 25.5


def test_form_fields_leave_out_what_the_panel_names():
    fields = interface.form_fields(TASK)
    by = {f["id"]: f for f in fields}
    assert "input" not in by and "output" not in by
    assert "elevation" not in by and "rmsfile" not in by and "table" not in by
    assert by["helper"]["kind"] == "text", (
        "a vector layer the form cannot pass is typed"
    )
    assert by["rules"]["kind"] == "text"
    assert by["label"]["kind"] == "text"
    assert by["distance"]["kind"] == "number"
    assert by["distance"]["default"] == 25.5
    assert by["method"]["kind"] == "select"
    assert by["method"]["choices"] == ["fast", "careful"]
    assert by["method"]["default"] == "fast"
    assert by["flag_t"]["kind"] == "checkbox"
    assert "flag_overwrite" not in by


def test_form_fields_keep_multiple_choices_and_whole_numbers():
    xml = """<task name="t.example">
      <parameter name="variables" type="string" required="yes" multiple="yes">
        <description>Which ones</description>
        <values><value><name>a</name></value><value><name>b</name></value></values>
      </parameter>
      <parameter name="levels" type="integer" required="no" multiple="yes">
        <values><value><name>500</name></value><value><name>850</name></value></values>
      </parameter>
      <parameter name="count" type="integer" required="no">
        <default>3</default>
      </parameter>
    </task>"""
    by = {f["id"]: f for f in interface.form_fields(xml)}
    assert by["variables"]["kind"] == "multi"
    assert by["variables"]["choices"] == ["a", "b"]
    assert by["levels"]["kind"] == "multi"
    assert by["count"]["kind"] == "number"
    assert by["count"]["integer"] is True
    assert by["count"]["default"] == 3.0


def test_form_fields_keep_a_range_of_numbers_as_written():
    xml = """<task name="i.example">
      <parameter name="rescale" type="integer" required="no">
        <description>Rescaling range for output maps</description>
        <keydesc><item>min</item><item>max</item></keydesc>
        <default>0,255</default>
      </parameter>
      <parameter name="count" type="integer" required="no">
        <description>How many</description>
        <keydesc><item>count</item></keydesc>
        <default>3</default>
      </parameter>
    </task>"""
    by = {f["id"]: f for f in interface.form_fields(xml)}
    assert by["rescale"]["kind"] == "text", "one number field cannot hold a range"
    assert by["rescale"]["default"] == "0,255"
    assert by["count"]["kind"] == "number"


def test_form_fields_carry_a_separate_label_and_help():
    xml = """<task name="r.example">
      <parameter name="size" type="float" required="no">
        <label>Window size</label>
        <description>The size of the moving window, in cells.</description>
      </parameter>
    </task>"""
    field = interface.form_fields(xml)[0]
    assert field["label"] == "Window size"
    assert field["help"] == "The size of the moving window, in cells."


ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def test_required_parameters_survive_truncation():
    many = TASK.replace(
        "</task>",
        "".join(
            # Names of letters only: RustGIS refuses a digit in one.
            f'<parameter name="p{ALPHABET[i // 26]}{ALPHABET[i % 26]}" type="float" '
            f'required="no"><description>x</description></parameter>'
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


@pytest.mark.skipif(
    not (pathlib.Path(__file__).parent.parent / "plugin.json").exists(),
    reason="plugin.json is generated from the GRASS installation; run generate_manifest.py",
)
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


def test_a_parameter_rustgis_would_refuse_is_left_out_and_reported():
    xml = """<?xml version="1.0"?><task name="v.gsflow.segments">
      <parameter name="width1" type="float"><description>A width</description></parameter>
      <parameter name="width" type="float"><description>Another</description></parameter>
    </task>"""
    form = interface.parse(xml)
    assert [p["name"] for p in form["params"]] == ["width"]
    assert "width1" in form["skipped"]


def test_a_flag_named_like_a_parameter_is_not_declared_twice():
    xml = """<?xml version="1.0"?><task name="v.test">
      <parameter name="flag_t" type="string"><description>A parameter</description></parameter>
      <flag name="t"><description>A flag</description></flag>
    </task>"""
    form = interface.parse(xml)
    assert [p["name"] for p in form["params"]] == ["flag_t"]


def test_a_parameter_declared_twice_is_kept_once_and_reported():
    xml = """<?xml version="1.0"?><task name="v.gsflow.segments">
      <parameter name="width" type="float"><description>A width</description></parameter>
      <parameter name="width" type="float"><description>The same again</description></parameter>
    </task>"""
    form = interface.parse(xml)
    assert [p["name"] for p in form["params"]] == ["width"]
    assert "width (declared twice)" in form["skipped"]


def test_a_file_parameter_is_written_and_given_to_grass(tmp_path):
    import main

    class Fake:
        dir = str(tmp_path)
        input_file = session.Run.input_file

    declared = [
        {"name": "input", "kind": "vectorLayer"},
        {"name": "rules", "kind": "file"},
    ]
    req = {
        "params": {"input": "Roads", "rules": "rules.txt"},
        "files": {"rules": {"name": "rules.txt", "data": "TDEgMQ=="}},
    }
    params, messages = main.file_params(declared, req, Fake())
    assert list(params) == ["rules"]
    assert pathlib.Path(params["rules"]).read_bytes() == b"L1 1"
    assert "rules.txt" in messages[0]
    # Its own value is only the file's name, so it never reaches GRASS twice.
    assert main.split_params(declared, req["params"]) == ({}, [])


def test_a_required_file_that_was_not_picked_says_where_to_pick_it(tmp_path):
    import main

    declared = [{"name": "rules", "kind": "file", "required": True}]
    with pytest.raises(session.GrassError, match="Tools pane"):
        main.file_params(declared, {"params": {"rules": "r.txt"}, "files": {}}, None)


def test_unreadable_file_contents_are_an_error_not_a_traceback(tmp_path):
    class Fake:
        dir = str(tmp_path)
        input_file = session.Run.input_file

    with pytest.raises(session.GrassError, match="unreadable"):
        Fake().input_file("rules", {"name": "r.txt", "data": "not base64!!"})


def test_rows_without_geometry_come_back_as_a_table():
    import main

    result = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}},
            {"type": "Feature", "geometry": None, "properties": {"dist": 3}},
        ],
    }
    shaped, messages = main.split_result(result, "Roads v.distance", "v.distance", [])
    assert len(shaped["layers"][0]["geojson"]["features"]) == 1
    assert len(shaped["tables"][0]["geojson"]["features"]) == 1
    assert shaped["tables"][0]["name"] == "Roads v.distance table"
    assert any("no geometry" in m for m in messages)


def test_a_result_that_is_all_geometry_has_no_table():
    import main

    result = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 2]}}
        ],
    }
    shaped, _ = main.split_result(result, "Cities v.voronoi", "v.voronoi", [])
    assert "tables" not in shaped and len(shaped["layers"]) == 1


def test_an_empty_result_is_still_an_empty_layer():
    import main

    shaped, messages = main.split_result(
        {"type": "FeatureCollection", "features": []}, "X", "v.clean", []
    )
    assert shaped["layers"][0]["geojson"]["features"] == []
    assert "0 features" in messages[0]


def test_a_file_named_with_no_contents_behind_it_is_an_error():
    import main

    declared = [{"name": "rules", "kind": "file"}]
    with pytest.raises(session.GrassError, match="no contents"):
        main.file_params(declared, {"params": {"rules": "r.txt"}, "files": {}}, None)


def raster_task(extra="", name="r.example"):
    """Return a module description with one required raster input and output."""
    return f"""<task name="{name}">
  <label>Does something to a raster.</label>
  <parameter name="elevation" type="string" required="yes" multiple="no">
    <description>Input elevation</description>
    <gisprompt age="old" element="cell" prompt="raster" />
  </parameter>
  <parameter name="slope" type="string" required="yes" multiple="no">
    <description>Output slope</description>
    <gisprompt age="new" element="cell" prompt="raster" />
  </parameter>
  {extra}
</task>"""


def test_a_module_reading_and_writing_one_raster_runs_here():
    entry = interface.describe(raster_task())
    assert entry["runnable"] is True
    assert entry["reason"] == ""
    assert entry["raster_input"] == "elevation"
    assert entry["raster_output"] == "slope"
    assert entry["raster_in"] == ["elevation"]
    assert entry["raster_out"] == ["slope"]


def test_optional_rasters_do_not_stop_a_module_running():
    extra = """<parameter name="depression" type="string" required="no">
      <description>Optional second input</description>
      <gisprompt age="old" element="cell" prompt="raster" />
    </parameter>
    <parameter name="aspect" type="string" required="no">
      <description>Optional second output</description>
      <gisprompt age="new" element="cell" prompt="raster" />
    </parameter>"""
    entry = interface.describe(raster_task(extra))
    assert entry["runnable"] is True
    assert entry["raster_in"] == ["elevation", "depression"]
    assert entry["raster_out"] == ["slope", "aspect"]
    assert (entry["raster_input"], entry["raster_output"]) == ("elevation", "slope")


def test_a_module_needing_a_group_says_so_instead_of_offering_a_button():
    extra = """<parameter name="group" type="string" required="yes">
      <description>Imagery group</description>
      <gisprompt age="old" element="group" prompt="group" />
    </parameter>"""
    entry = interface.describe(raster_task(extra, name="i.example"))
    assert entry["runnable"] is False
    assert entry["reason"] == "needs an imagery group"
    assert entry["needs"] == ["group"]


def test_a_module_wanting_several_bands_is_marked_not_run():
    task = raster_task().replace(
        'name="elevation" type="string" required="yes" multiple="no"',
        'name="elevation" type="string" required="yes" multiple="yes"',
    )
    entry = interface.describe(task)
    assert entry["runnable"] is False
    assert entry["bands"] is True
    assert entry["reason"] == "needs several bands"


def test_a_required_flag_is_a_reason_not_a_silent_failure():
    flag = interface.describe(raster_task('<flag name="c" required="yes" />'))
    assert flag["reason"] == "needs flag -c"


def test_a_required_plain_value_is_a_form_field_not_a_refusal():
    # r.buffer's shape: one raster in, one out, and a required "distances"
    # with no default. The form has offered a field for it since 0.8.0; this
    # rule was written before the form existed and never learned, so the panel
    # showed Distance zone(s) filled with 100 above a greyed-out Run Module
    # and the words "Not runnable from this panel: needs distances".
    task = raster_task(
        '<parameter name="threshold" type="float" required="yes">'
        "<description>Cut-off</description></parameter>"
    )
    param = interface.describe(task)
    assert param["runnable"] is True
    assert param["reason"] == ""
    assert param["needs"] == []
    # And the field it is satisfied by is really there, marked required.
    field = next(f for f in interface.form_fields(task) if f["id"] == "threshold")
    assert field["kind"] == "number" and field["required"] is True


def test_a_required_name_from_the_mapset_is_still_a_refusal():
    # The raster path runs in a throwaway project holding only the exported
    # layer, so a typed imagery group or vector name would name nothing there.
    # A form field is not an answer for those.
    group = interface.describe(
        raster_task(
            '<parameter name="group" type="string" required="yes">'
            "<description>Imagery group</description>"
            '<gisprompt age="old" element="group" prompt="group" /></parameter>',
            name="i.example",
        )
    )
    assert group["runnable"] is False
    assert group["needs"] == ["group"]


def test_temporal_modules_are_recognised_by_their_dataset_prompt():
    extra = """<parameter name="strds" type="string" required="no">
      <description>Space-time raster dataset</description>
      <gisprompt age="old" element="strds" prompt="strds" />
    </parameter>"""
    entry = interface.describe(raster_task(extra, name="t.example"))
    assert entry["temporal"] is True


def temporal_task(extra="", name="t.import"):
    """Return a temporal module description with a form and no raster."""
    return f"""<task name="{name}">
  <label>Imports a dataset into a mapset.</label>
  <parameter name="variables" type="string" required="yes" multiple="yes">
    <description>Variables to import</description>
    <values><value><name>t2m</name></value><value><name>tp</name></value></values>
  </parameter>
  <parameter name="prefix" type="string" required="yes">
    <description>Output prefix</description>
    <default>out</default>
  </parameter>
  {extra}
</task>"""


def test_a_temporal_module_runs_with_its_form_in_a_chosen_mapset():
    entry = interface.describe(temporal_task())
    assert entry["runnable"] is False
    assert entry["mapset_runnable"] is True
    assert entry["mapset_reason"] == ""
    fields = interface.form_fields(temporal_task())
    assert [f["id"] for f in fields] == ["variables", "prefix"]


def test_a_long_description_becomes_a_short_label_with_the_full_text_as_help():
    extra = """<parameter name="cache" type="string" required="no">
      <description>Directory to permanently cache full-world ARCO-ERA5 monthly data in, reused across every future run regardless of the selected period.</description>
    </parameter>"""
    fields = interface.form_fields(temporal_task(extra))
    field = next(f for f in fields if f["id"] == "cache")
    assert len(field["label"]) <= 48
    assert field["label"].endswith("…")
    assert field["help"].startswith("Directory to permanently cache full-world")


def display_task(extra="", name="d.example"):
    """Return a display module description drawing one raster."""
    return f"""<task name="{name}">
  <label>Draws a raster on a display.</label>
  <parameter name="map" type="string" required="yes" multiple="no">
    <description>Name of raster map</description>
    <gisprompt age="old" element="cell" prompt="raster" />
  </parameter>
  {extra}
</task>"""


def test_a_display_module_that_writes_a_map_is_not_a_picture():
    entry = interface.describe(raster_task(name="d.example"))
    assert entry["runnable"] is False
    assert entry["render_runnable"] is False
    assert entry["reason"] == "writes a map, not a picture"


def test_a_temporal_module_takes_a_dataset_of_the_chosen_mapset():
    # A space-time dataset is named like a map and lives in the mapset, so the
    # form offers the mapset's datasets rather than refusing the module. The
    # gisprompt is the only thing that says so: GRASS declares it type="string"
    # and --help shows nothing to distinguish it from any other name.
    extra = """<parameter name="input" type="string" required="yes">
      <description>Input space-time dataset</description>
      <gisprompt age="old" element="strds" prompt="strds" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is True
    assert entry["mapset_reason"] == ""
    assert [(p["name"], p["kind"], p["required"]) for p in entry["mapset_inputs"]] == [
        ("input", "strds", True)
    ]


def test_a_dataset_module_that_names_its_output_runs():
    # t.rast.series' shape: an old strds in, a new raster out. The dataset is
    # a dropdown of the mapset's own, the output a name the user types and the
    # bridge checks against that mapset before running.
    extra = """<parameter name="input" type="string" required="yes">
      <description>Input space-time dataset</description>
      <gisprompt age="old" element="strds" prompt="strds" />
    </parameter>
    <parameter name="output" type="string" required="yes" multiple="yes">
      <description>Name for output raster map</description>
      <gisprompt age="new" element="cell" prompt="raster" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is True
    assert entry["mapset_reason"] == ""
    assert [(p["name"], p["kind"]) for p in entry["mapset_inputs"]] == [
        ("input", "strds")
    ]
    assert [(p["name"], p["kind"], p["multiple"]) for p in entry["mapset_outputs"]] == [
        ("output", "raster", True)
    ]


def test_an_in_place_raster_module_takes_maps_of_the_chosen_mapset():
    xml = """<task name="r.colors">
  <description>Creates/modifies the color table.</description>
  <parameter name="map" type="string" required="no" multiple="yes">
    <description>Name of raster map(s)</description>
    <gisprompt age="old" element="cell" prompt="raster" />
  </parameter>
  <parameter name="raster" type="string" required="no">
    <description>Raster map from which to copy color table</description>
    <gisprompt age="old" element="cell" prompt="raster" />
  </parameter>
  <parameter name="color" type="string" required="no">
    <description>Name of color table</description>
    <values><value><name>grey</name></value></values>
  </parameter>
</task>"""
    entry = interface.describe(xml)
    assert entry["mapset_runnable"] is True
    assert [port["name"] for port in entry["mapset_inputs"]] == ["map", "raster"]
    assert entry["runnable"] is False
    assert entry["reason"] == "writes no raster"


def test_an_addon_that_mislabels_its_output_is_not_an_in_place_run():
    xml = """<task name="r.agent.aco">
  <description>Runs an ant colony optimisation.</description>
  <parameter name="outputmap" type="string" required="yes">
    <description>Output raster</description>
    <gisprompt age="old" element="cell" prompt="raster" />
  </parameter>
  <parameter name="costmap" type="string" required="yes">
    <description>Cost raster</description>
    <gisprompt age="old" element="cell" prompt="raster" />
  </parameter>
</task>"""
    entry = interface.describe(xml)
    assert entry["mapset_runnable"] is False
    assert "raster or vector" in entry["mapset_reason"]


def test_a_new_map_is_a_name_the_form_asks_for():
    extra = """<parameter name="output" type="string" required="yes">
      <description>Output raster</description>
      <gisprompt age="new" element="cell" prompt="raster" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is True
    assert [(p["name"], p["kind"], p["required"]) for p in entry["mapset_outputs"]] == [
        ("output", "raster", True)
    ]


def test_a_new_file_path_is_not_offered_and_says_so():
    # A file is written wherever the user says, and nothing here can promise
    # not to overwrite a path of their choosing, so it stays refused -- but
    # the reason now names a file rather than "an output".
    extra = """<parameter name="output" type="string" required="yes">
      <description>Name for output file</description>
      <gisprompt age="new" element="file" prompt="file" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is False
    assert entry["mapset_reason"] == (
        "needs a file path to write to, which this panel does not ask for"
    )
    assert entry["mapset_outputs"] == []


def test_a_new_database_table_is_not_offered_either():
    extra = """<parameter name="to_table" type="string" required="yes">
      <description>Table to copy to</description>
      <gisprompt age="new" element="dbtable" prompt="dbtable" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is False
    assert "database table" in entry["mapset_reason"]


def test_the_panel_renders_a_display_module_from_the_chosen_mapset(
    monkeypatch, tmp_path
):
    import main

    base = tmp_path / "db"
    mapset = base / "P" / "PERMANENT"
    (mapset / "cellhd").mkdir(parents=True)
    (mapset / "WIND").write_text("")
    (mapset / "cellhd" / "DEM").write_text("")
    (mapset / "vector" / "Roads").mkdir(parents=True)
    monkeypatch.setenv("GISDBASE", str(base))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(
        main,
        "call",
        lambda op, params=None: (
            {"id": 9, "name": params.get("name")} if op == "layer.addData" else {}
        ),
    )
    monkeypatch.setattr(main, "progress", lambda text: None)
    monkeypatch.setattr(main, "log", lambda text: None)
    seen = {}

    class FakeDisplayRun:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def render_mapset(
            self,
            base,
            project,
            mapset,
            module,
            args,
            rasters,
            vectors,
            target,
            preview=None,
        ):
            seen.update(
                base=base,
                project=project,
                mapset=mapset,
                module=module,
                args=args,
                rasters=rasters,
                vectors=vectors,
                target=target,
                preview=preview,
            )
            pathlib.Path(target).write_text("tif")
            return [f"{module} rendered a picture."]

    monkeypatch.setattr(main.session, "DisplayRun", FakeDisplayRun)
    entry = {
        "module": "d.vect",
        "family": "Display",
        "summary": "Draws a vector.",
        "keywords": "",
        "runnable": False,
        "reason": "renders a picture",
        "render_runnable": True,
        "render_inputs": [
            {
                "name": "map",
                "kind": "vector",
                "label": "Map",
                "help": "",
                "required": True,
                "multiple": False,
            }
        ],
        "form": [{"id": "color", "kind": "text"}],
    }
    answer = main.run_display_module(
        [entry],
        entry,
        {
            "raster": "1",
            "database": "mapset/P/PERMANENT",
            "form": {"map": "Roads", "color": "red"},
            "family": "all",
        },
    )
    assert seen["base"] == str(base)
    assert seen["project"] == "P"
    assert seen["mapset"] == "PERMANENT"
    assert seen["module"] == "d.vect"
    assert seen["args"] == ["map=Roads@PERMANENT", "color=red"]
    assert seen["rasters"] == []
    assert seen["vectors"] == ["Roads@PERMANENT"]
    assert seen["target"].endswith(".tif")
    assert seen["preview"] is None
    assert answer["layer"]["id"] == 9
    assert answer["panel"]["items"]["form"]["fields"][0]["id"] == "map"


def test_choosing_a_mapset_refreshes_a_display_modules_maps(monkeypatch, tmp_path):
    import main

    base = tmp_path / "db"
    mapset = base / "P" / "PERMANENT"
    (mapset / "cellhd").mkdir(parents=True)
    (mapset / "WIND").write_text("")
    (mapset / "cellhd" / "DEM").write_text("")
    monkeypatch.setenv("GISDBASE", str(base))
    display = {
        "module": "d.rgb",
        "family": "Display",
        "summary": "Draws red, green and blue.",
        "keywords": "",
        "runnable": False,
        "reason": "renders a picture",
        "render_runnable": True,
        "render_inputs": [
            {
                "name": name,
                "kind": "raster",
                "label": name,
                "required": True,
                "multiple": False,
            }
            for name in ("red", "green", "blue")
        ],
        "form": [],
    }
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": [display]})
    answer = main.browse_database(
        {
            "panel": {
                "values": {
                    "modules": "d.rgb",
                    "database": "mapset/P/PERMANENT",
                }
            }
        }
    )
    fields = answer["panel"]["items"]["form"]["fields"]
    by = {field["id"]: field for field in fields}
    assert by["red"]["choices"] == ["DEM"]
    assert by["green"]["choices"] == ["DEM"]
    assert by["blue"]["choices"] == ["DEM"]


def test_the_panel_runs_a_mapset_module_with_the_form(monkeypatch, tmp_path):
    import main

    base = tmp_path / "db"
    (base / "P" / "PERMANENT").mkdir(parents=True)
    (base / "P" / "PERMANENT" / "WIND").write_text("")
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(main.database, "gisdbase", lambda: str(base))
    monkeypatch.setattr(main, "call", lambda op, params=None: {})
    monkeypatch.setattr(main, "progress", lambda text: None)
    seen = {}

    class FakeRun:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def mapset_module(self, base, project, mapset, module, args):
            seen.update(
                base=base, project=project, mapset=mapset, module=module, args=args
            )
            return [f"{module} ran in {project}/{mapset}."]

    monkeypatch.setattr(main.session, "Run", FakeRun)
    module = "t.in.era5"
    entry = {
        "module": module,
        "summary": "Imports ERA5.",
        "family": "Temporal",
        "keywords": "",
        "runnable": False,
        "mapset_runnable": True,
        "mapset_reason": "",
        "reason": "takes no raster",
        "form": [
            {"id": "variables", "kind": "multi", "required": True, "choices": ["t2m"]},
            {"id": "start", "kind": "text", "required": True},
            {"id": "end", "kind": "text", "required": True},
            {"id": "prefix", "kind": "text", "required": True, "default": "era5"},
        ],
    }
    answer = main.run_module_in_mapset(
        [entry],
        entry,
        {
            "database": "mapset/P/PERMANENT",
            "form": {
                "variables": ["t2m"],
                "start": "2020-01-01",
                "end": "2020-01-02",
            },
        },
    )
    assert seen == {
        "base": str(base),
        "project": "P",
        "mapset": "PERMANENT",
        "module": module,
        "args": ["variables=t2m", "start=2020-01-01", "end=2020-01-02"],
    }
    assert "ran in P/PERMANENT" in answer["messages"][0]


def test_the_panel_runs_an_in_place_module_on_a_map_of_the_mapset(
    monkeypatch, tmp_path
):
    import main

    base = tmp_path / "db"
    mapset = base / "P" / "PERMANENT"
    (mapset / "cellhd").mkdir(parents=True)
    (mapset / "WIND").write_text("")
    (mapset / "cellhd" / "DEM").write_text("")
    monkeypatch.setenv("GISDBASE", str(base))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(main, "call", lambda op, params=None: {})
    seen = {}

    class FakeRun:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def mapset_module(self, base, project, mapset, module, args):
            seen.update(
                base=base, project=project, mapset=mapset, module=module, args=args
            )
            return [f"{module} ran in {project}/{mapset}."]

    monkeypatch.setattr(main.session, "Run", FakeRun)
    monkeypatch.setattr(main, "progress", lambda text: None)
    monkeypatch.setattr(main, "log", lambda text: None)
    entry = {
        "module": "r.colors",
        "summary": "Changes a colour table.",
        "family": "Raster",
        "keywords": "",
        "runnable": False,
        "reason": "writes no raster",
        "mapset_runnable": True,
        "mapset_reason": "",
        "mapset_inputs": [
            {
                "name": "map",
                "kind": "raster",
                "label": "Map",
                "help": "",
                "required": False,
                "multiple": True,
            }
        ],
        "form": [{"id": "color", "kind": "select", "choices": ["grey", "elevation"]}],
    }
    answer = main.run_module_in_mapset(
        [entry],
        entry,
        {
            "database": "mapset/P/PERMANENT",
            "form": {"map": ["DEM"], "color": "elevation"},
        },
    )
    assert seen == {
        "base": str(base),
        "project": "P",
        "mapset": "PERMANENT",
        "module": "r.colors",
        "args": ["map=DEM", "color=elevation"],
    }
    assert answer["panel"]["items"]["form"]["fields"][0]["id"] == "map"


def test_the_panel_refuses_a_module_it_cannot_drive(monkeypatch):
    import main

    entry = {
        "module": "i.pca",
        "summary": "Principal components.",
        "family": "Imagery",
        "keywords": "",
        "runnable": False,
        "reason": "needs several bands",
        "mapset_runnable": False,
        "mapset_reason": "works on a raster or vector layer",
    }
    monkeypatch.setattr(
        main,
        "load_catalogue",
        lambda: {"catalogue": [entry]},
    )
    monkeypatch.setattr(
        main, "call", lambda op, params=None: (_ for _ in ()).throw(AssertionError(op))
    )
    with pytest.raises(main.session.GrassError, match="needs several bands"):
        main.run_module({"panel": {"values": {"modules": "all/i.pca"}}})


def test_a_raster_module_is_not_offered_as_a_mapset_run():
    entry = interface.describe(raster_task())
    assert entry["mapset_runnable"] is False
    assert "raster or vector" in entry["mapset_reason"]


def test_a_required_3d_raster_named_input_is_not_mistaken_for_plumbing():
    extra = """<parameter name="input" type="string" required="yes">
      <description>3D raster to slice</description>
      <gisprompt age="old" element="grid3" prompt="3d-raster" />
    </parameter>"""
    entry = interface.describe(raster_task(extra, name="r3.example"))
    assert entry["runnable"] is False
    assert entry["reason"] == "needs input"
    assert entry["needs"] == ["input"]


def test_a_module_taking_a_base_name_reads_several_bands():
    task = raster_task(name="i.landsat.toar").replace(
        "<description>Input elevation</description>",
        "<label>Base name of input raster bands</label>",
    )
    entry = interface.describe(task)
    assert entry["runnable"] is False
    assert entry["bands"] is True
    assert entry["reason"] == "needs several bands"


def test_a_display_module_is_offered_when_it_can_render_its_input():
    entry = interface.describe(display_task())
    assert entry["runnable"] is False
    assert entry["render_runnable"] is True
    assert entry["reason"] == "renders a picture"
    assert entry["render_inputs"] == [
        {
            "name": "map",
            "kind": "raster",
            "label": "Name of raster map",
            "help": "Name of raster map",
            "required": True,
            "multiple": False,
        }
    ]


def test_a_display_module_waiting_for_a_click_is_not_rendered():
    entry = interface.describe(display_task(name="d.what.rast"))
    assert entry["render_runnable"] is False
    assert entry["render_reason"] == "waits for a click on the display"


def test_a_display_module_with_no_layer_only_draws_on_a_display():
    entry = interface.describe(
        """<task name="d.barscale">
  <label>Draws a scale bar on a display.</label>
</task>"""
    )
    assert entry["render_runnable"] is False
    assert entry["render_reason"] == "draws on a display, not into a layer"


def test_the_panel_keeps_an_imagery_mode_and_filters_the_module_tree(monkeypatch):
    import main

    catalogue = [
        {
            "module": "i.edge",
            "family": "Imagery",
            "summary": "",
            "keywords": "",
            "raster_in": ["input"],
            "raster_out": ["output"],
            "raster_input": "input",
            "raster_output": "output",
            "runnable": True,
            "reason": "",
            "needs": [],
            "bands": False,
            "temporal": False,
            "form": [{"id": "n", "kind": "number", "integer": True}],
        }
    ]
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": catalogue})
    monkeypatch.setattr(main.session, "version", lambda *a, **k: "8.6")
    monkeypatch.setattr(main.raster, "read_recents", lambda *a, **k: [])

    def fake_call(op, params=None):
        if op == "host.layers":
            return [{"id": 1, "name": "scene", "raster": True, "active": True}]
        return {}

    monkeypatch.setattr(main, "call", fake_call)
    state = main.panel_state(
        {"panel": {"values": {"raster": "1", "modules": "all/i.edge"}}},
        "imagery",
    )
    assert state["panel"]["values"]["family"] == "imagery"
    # A family is only chosen to look through the catalogue, so the panel goes
    # to the step that draws it.
    assert state["panel"]["values"]["step"] == "modules"
    assert state["panel"]["items"]["modules"]["visible"] is True
    assert state["panel"]["items"]["database"]["visible"] is False
    assert (
        state["panel"]["items"]["modules"]["nodes"][1]["label"]
        == "All imagery modules (1)"
    )
    assert "Showing imagery modules only." in state["panel"]["items"]["status"]["text"]
    assert state["panel"]["items"]["form"]["fields"] == [
        {"id": "n", "kind": "number", "integer": True}
    ]


def test_the_temporal_state_command_opens_the_temporal_mode(monkeypatch):
    import main

    seen = []
    monkeypatch.setattr(
        main,
        "panel_state",
        lambda req, family=None, step=None: seen.append(family) or {"panel": {}},
    )
    assert main.run_command({"id": "temporal-state"}) == {"panel": {}}
    assert seen == ["temporal"]


def test_a_step_draws_its_own_widgets_and_hides_the_others():
    from grass_bridge import panel

    for step, _ in panel.STEPS:
        shown = {
            name for name, state in panel.visibility(step).items() if state["visible"]
        }
        assert shown == set(panel.ALWAYS) | set(panel.STEP_ITEMS[step])
        # The panel's whole point is that a step is a screenful, not a column.
        assert len(shown) <= 12
    # Every widget belongs to a step, and the two that are always drawn are
    # the step chooser and the line saying what the last run did.
    assert set(panel.ALWAYS) == {"step", "status"}
    assert panel.step_of("no-such-step") == panel.FIRST
    assert panel.step_of("modules") == "modules"


def test_only_the_step_that_draws_a_tree_pays_for_its_nodes():
    from grass_bridge import panel

    # The module tree is 1,424 nodes and about 270 KB of JSON, and a mapset's
    # can be thousands of maps; the raster tree is one node per raster layer
    # and a tree keeps a chosen value only while its node was last sent.
    assert panel.sends_nodes("modules", "modules") is True
    assert panel.sends_nodes("layer", "modules") is False
    assert panel.sends_nodes("data", "database") is True
    assert panel.sends_nodes("modules", "database") is False
    for step, _ in panel.STEPS:
        assert panel.sends_nodes(step, "raster") is True


def test_choosing_a_layer_answers_the_layer_and_not_the_catalogue(monkeypatch):
    import main

    asked = []

    def fake_call(op, params=None):
        asked.append(op)
        if op == "host.layers":
            return [{"id": 1, "name": "dem", "raster": True, "active": True}]
        if op == "raster.info":
            return {"crs": "EPSG:2154", "bands": [{"name": "elevation"}]}
        return {}

    monkeypatch.setattr(main, "call", fake_call)
    monkeypatch.setattr(
        main, "load_catalogue", lambda: pytest.fail("the catalogue was read")
    )
    answer = main.layer_pick({"panel": {"values": {"raster": "1"}}})
    items = answer["panel"]["items"]
    assert set(items) == {"raster", "source", "band", "region", "status"}
    assert "modules" not in items
    assert items["source"]["text"].startswith("dem")
    assert answer["panel"]["values"] == {"raster": "1"}
    # It must not move the panel either: the user chose a layer, not a step.
    assert "step" not in answer["panel"].get("values", {})
    assert asked == ["host.layers", "raster.info", "gp.env"]


def test_choosing_a_module_answers_the_details_and_the_form_only(monkeypatch):
    import main

    catalogue = [
        {
            "module": "r.slope.aspect",
            "family": "Raster",
            "summary": "",
            "keywords": "",
            "raster_in": ["elevation"],
            "raster_out": ["slope"],
            "raster_input": "elevation",
            "raster_output": "slope",
            "runnable": True,
            "reason": "",
            "needs": [],
            "bands": False,
            "temporal": False,
            "form": [{"id": "zscale", "kind": "text"}],
        }
    ]
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": catalogue})
    monkeypatch.setattr(
        main, "call", lambda op, params=None: pytest.fail(f"host request {op}")
    )
    answer = main.module_pick({"panel": {"values": {"modules": "runs/r.slope.aspect"}}})
    items = answer["panel"]["items"]
    assert set(items) == {"details", "form", "status", "run-module"}
    assert items["form"]["fields"] == [{"id": "zscale", "kind": "text"}]
    assert items["run-module"]["enabled"] is True
    assert "r.slope.aspect" in items["status"]["text"]


def test_run_module_is_disabled_for_a_module_the_panel_cannot_drive(monkeypatch):
    import main

    catalogue = [
        {
            "module": "r.patch",
            "family": "Raster",
            "summary": "",
            "keywords": "",
            "raster_in": ["input"],
            "raster_out": ["output"],
            "raster_input": "input",
            "raster_output": "output",
            "runnable": False,
            "reason": "needs several rasters",
            "mapset_runnable": False,
            "render_runnable": False,
            "needs": [],
            "bands": False,
            "temporal": False,
            "form": [],
        }
    ]
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": catalogue})
    monkeypatch.setattr(main, "call", lambda op, params=None: {})
    answer = main.module_pick({"panel": {"values": {"modules": "all/r.patch"}}})
    assert answer["panel"]["items"]["run-module"]["enabled"] is False
    assert "needs several rasters" in answer["panel"]["items"]["status"]["text"]


def test_run_module_takes_its_module_from_the_commands_parameters(monkeypatch):
    import main

    # A tree keeps a value only while that value was among the nodes last
    # sent, and the module tree is sent only by the step that draws it, so a
    # script names the module instead of walking the panel there.
    catalogue = [
        {
            "module": "r.slope.aspect",
            "family": "Raster",
            "summary": "",
            "keywords": "",
            "raster_in": ["elevation"],
            "raster_out": ["slope"],
            "raster_input": "elevation",
            "raster_output": "slope",
            "runnable": False,
            "reason": "not runnable in this test",
            "mapset_runnable": False,
            "render_runnable": False,
            "needs": [],
            "bands": False,
            "temporal": False,
            "form": [],
        }
    ]
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": catalogue})
    with pytest.raises(main.session.GrassError) as raised:
        main.run_module(
            {
                "id": "run-module",
                "params": {"module": "r.slope.aspect"},
                "panel": {"values": {}},
            }
        )
    # It reached that module from the parameters alone, with nothing chosen.
    assert "r.slope.aspect cannot be run" in str(raised.value)


def test_a_picked_box_becomes_an_extent_and_a_wrapped_one_is_refused():
    import main

    place = {
        "bbox": [-2.0, 47.0, -1.0, 48.0],
        "extent": [1, 2, 3, 4],
        "crs": "EPSG:3857",
    }
    assert main.picked_box({"region-box": place}) == [-2.0, 47.0, -1.0, 48.0]
    assert main.picked_box({}) is None
    assert main.picked_box({"region-box": {"bbox": [1, 2]}}) is None
    # gp.env takes four increasing degrees, so a box drawn across the
    # antimeridian cannot be turned into an extent without meaning the rest of
    # the world instead.
    with pytest.raises(main.session.GrassError) as raised:
        main.picked_box({"region-box": {"bbox": [179.0, 47.0, -179.0, 48.0]}})
    assert "antimeridian" in str(raised.value)
    with pytest.raises(main.session.GrassError):
        main.picked_box({"region-box": {"bbox": [-2.0, 48.0, -1.0, 48.0]}})


def test_the_region_box_command_sets_the_extent_it_was_given(monkeypatch):
    import main

    seen = []

    def fake_call(op, params=None):
        seen.append((op, params))
        return {"extent": [-2.0, 47.0, -1.0, 48.0]}

    monkeypatch.setattr(main, "call", fake_call)
    answer = main.run_command(
        {
            "id": "region-box",
            "panel": {"values": {"region-box": {"bbox": [-2.0, 47.0, -1.0, 48.0]}}},
        }
    )
    assert ("gp.env", {"extent": [-2.0, 47.0, -1.0, 48.0]}) in seen
    assert "box drawn on the map" in answer["panel"]["items"]["status"]["text"]


def test_the_region_box_command_says_when_no_box_was_drawn(monkeypatch):
    import main

    monkeypatch.setattr(main, "call", lambda op, params=None: {})
    with pytest.raises(main.session.GrassError) as raised:
        main.run_command({"id": "region-box", "panel": {"values": {}}})
    assert "no box has been drawn" in str(raised.value)


def harmonise(monkeypatch, projection, epsg, other_layers=False):
    """Run ``harmonise_projection`` against a view in ``projection``.

    :return: ``(messages, [(op, params), ...])``
    """
    import main

    seen = []

    def fake_call(op, params=None):
        seen.append((op, params))
        return {"projection": projection} if op == "host.view" else {}

    monkeypatch.setattr(main, "call", fake_call)
    said = main.harmonise_projection(epsg, "utmproj", other_layers)
    return said, seen


def test_a_world_projection_is_replaced_by_the_grass_project_s_own(monkeypatch):
    # A map from a projected GRASS project drawn in a world projection is in
    # the right place but not in the system the user's GRASS work is in.
    for world in ("globe", "mercator", "robinson"):
        said, seen = harmonise(monkeypatch, world, "EPSG:32630")
        assert ("map.projection", {"type": "EPSG:32630"}) in seen
        assert "now in EPSG:32630" in said[0]


def test_a_view_already_in_the_system_is_left_alone(monkeypatch):
    said, seen = harmonise(monkeypatch, "EPSG:32630", "EPSG:32630")
    assert not any(op == "map.projection" for op, _ in seen)
    assert "already in EPSG:32630" in said[0]


def test_a_view_in_another_system_with_layers_in_it_is_not_flipped(monkeypatch):
    # Changing it would move someone else's data under them, and RustGIS
    # reprojects for display anyway, so the map is still in the right place.
    said, seen = harmonise(monkeypatch, "EPSG:32631", "EPSG:32630", other_layers=True)
    assert not any(op == "map.projection" for op, _ in seen)
    assert "left in EPSG:32631" in said[0]
    assert "right place" in said[0]


def test_a_view_in_another_system_with_nothing_in_it_is_harmonised(monkeypatch):
    said, seen = harmonise(monkeypatch, "EPSG:32631", "EPSG:32630", other_layers=False)
    assert ("map.projection", {"type": "EPSG:32630"}) in seen
    assert "now in EPSG:32630" in said[0]


def test_a_projection_rustgis_refuses_does_not_fail_the_load(monkeypatch):
    import main

    def fake_call(op, params=None):
        if op == "host.view":
            return {"projection": "globe"}
        raise main.session.GrassError("no such projection")

    monkeypatch.setattr(main, "call", fake_call)
    said = main.harmonise_projection("EPSG:99999", "utmproj", False)
    assert "stays in globe" in said[0] and "no such projection" in said[0]
    assert "right place" in said[0]


def test_a_project_with_no_epsg_code_leaves_the_view_as_it_is(monkeypatch):
    said, seen = harmonise(monkeypatch, "globe", None)
    assert not any(op == "map.projection" for op, _ in seen)
    assert "names no EPSG code" in said[0]


def test_a_group_node_is_offered_above_the_loose_rasters(tmp_path):
    from grass_bridge import database

    mapset = tmp_path / "utm" / "PERMANENT"
    (mapset / "cellhd").mkdir(parents=True)
    for name in ("red", "green", "blue"):
        (mapset / "cellhd" / name).write_text("")
    (mapset / "WIND").write_text("")
    (tmp_path / "utm" / "PERMANENT" / "group" / "scene").mkdir(parents=True)
    (mapset / "group" / "scene" / "REF").write_text(
        "red PERMANENT\ngreen PERMANENT\nblue PERMANENT\n"
    )
    (mapset / "group" / "one").mkdir(parents=True)
    (mapset / "group" / "one" / "REF").write_text("red PERMANENT\n")

    nodes, _ = database.tree(str(tmp_path), ("utm", "PERMANENT"), home="")
    labels = [child["label"] for child in nodes[0]["children"][0]["children"]]
    # The composite comes before the parts it is made of.
    assert labels[0] == "one (group of 1, not a composite)"
    assert labels[1] == "scene (group of 3)"
    assert labels[2:] == ["blue (raster)", "green (raster)", "red (raster)"]
    assert nodes[0]["children"][0]["children"][1]["id"] == ("group/utm/PERMANENT/scene")


def test_a_group_node_enables_add_map_and_says_what_it_will_do(monkeypatch):
    import main

    monkeypatch.setattr(main, "call", lambda op, params=None: {})
    monkeypatch.setattr(main, "database_panel", lambda chosen=None: {})
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": []})
    answer = main.run_command(
        {
            "id": "data-browse",
            "panel": {"values": {"database": "group/utm/PERMANENT/scene"}},
        }
    )
    items = answer["panel"]["items"]
    assert items["data-add"]["enabled"] is True
    assert "composite of its bands" in items["status"]["text"]


def test_a_mapset_module_is_not_told_it_takes_no_raster(monkeypatch):
    import main

    # "takes no raster" is the raster path's reason, and a temporal module was
    # never on that path: the panel used to show it for a module Run Module
    # runs perfectly well.
    entry = {
        "module": "t.rast.list",
        "runnable": False,
        "mapset_runnable": True,
        "render_runnable": False,
        "reason": "takes no raster",
        "mapset_inputs": [],
        "form": [],
    }
    monkeypatch.setattr(main, "call", lambda op, params=None: {})
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": [entry]})
    monkeypatch.setattr(main, "database_panel", lambda chosen=None: {})
    monkeypatch.setattr(main.database, "gisdbase", lambda: None)
    answer = main.run_command(
        {"id": "module-pick", "panel": {"values": {"modules": "runs/t.rast.list"}}}
    )
    items = answer["panel"]["items"]
    assert items["status"]["text"] == "t.rast.list: press Run Module."
    assert items["run-module"]["enabled"] is True


def test_a_3d_raster_input_is_offered_from_the_mapset():
    extra = """<parameter name="input" type="string" required="yes">
      <description>Name of the 3D raster</description>
      <gisprompt age="old" element="grid3" prompt="raster_3d" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is True
    assert [(p["name"], p["kind"]) for p in entry["mapset_inputs"]] == [
        ("input", "raster_3d")
    ]


def test_a_new_3d_raster_is_a_name_too():
    # t.rast.to.rast3's shape. The old rule hit the grid3 branch before it
    # looked at the age and told it "needs a 3D raster", sending the reader to
    # look for a map that does not exist yet; what it needs is a name for one.
    extra = """<parameter name="output" type="string" required="yes">
      <description>Name of the output 3D raster</description>
      <gisprompt age="new" element="grid3" prompt="raster_3d" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is True
    assert [(p["name"], p["kind"]) for p in entry["mapset_outputs"]] == [
        ("output", "raster_3d")
    ]


def test_a_command_s_parameters_are_laid_over_the_panel():
    import main

    values = {"database": "mapset/A/PERMANENT", "form": {"input": "from_panel"}}
    out = main.with_params(
        values,
        {"mapset": "B/PERMANENT", "values": {"output": "new", "input": "from_params"}},
    )
    # A parameter wins where both say something, and the rest of the panel is
    # left alone.
    assert out["database"] == "mapset/B/PERMANENT"
    assert out["form"] == {"input": "from_params", "output": "new"}
    # Nothing given means nothing changed.
    assert main.with_params(values, {}) == values


def test_a_mapset_parameter_that_names_no_mapset_is_refused():
    import main

    with pytest.raises(session.GrassError, match="is not a project and mapset"):
        main.with_params({}, {"mapset": "just-one-part"})


def test_module_values_must_be_an_object():
    import main

    with pytest.raises(session.GrassError, match="go in an object"):
        main.with_params({}, {"values": "input=a"})


def test_a_parameter_taking_several_numbers_is_a_text_field():
    # r.buffer's distances=100,200,500. One number box cannot hold a list, and
    # offering one made the module's own point unreachable: the screenshot
    # showed "Distance zone(s) 100" with no way to add a second zone.
    task = raster_task(
        '<parameter name="distances" type="double" required="yes" multiple="yes">'
        "<description>Distance zone(s)</description></parameter>"
    )
    field = next(f for f in interface.form_fields(task) if f["id"] == "distances")
    assert field["kind"] == "text"
    # One number is still a number box.
    one = raster_task(
        '<parameter name="threshold" type="double" required="yes">'
        "<description>Cut-off</description></parameter>"
    )
    assert (
        next(f for f in interface.form_fields(one) if f["id"] == "threshold")["kind"]
        == "number"
    )


def test_a_ribbon_press_with_nothing_chosen_opens_the_tree_instead_of_refusing(
    monkeypatch, tmp_path
):
    """Add Map and Load Workspace are on the ribbon, where no tree can be seen.

    A command carries no runtime state, so a ribbon button cannot be greyed
    out, and the GRASS Data tree is drawn by one step of the panel. Pressed
    with nothing chosen, these used to answer a red error naming a tree the
    user was not looking at; they answer the tree itself now, on the step
    that draws it, with the line saying what to choose.
    """
    import main

    said = []
    monkeypatch.setattr(main, "call", lambda op, params=None: said.append(params) or {})
    monkeypatch.setattr(main.database, "gisdbase", lambda: str(tmp_path))

    for handler, press in (
        (main.load_workspace, "Load Workspace"),
        (main.add_map, "Add Map"),
    ):
        out = handler({"params": {}, "panel": {"values": {}}})
        panel_out = out["panel"]
        assert panel_out["values"]["step"] == "data"
        assert panel_out["items"]["database"]["visible"] is True
        assert press in out["asked"] and press in panel_out["items"]["status"]["text"]
        assert panel_out["items"]["data-add"]["enabled"] is False
    # The panel can be closed, and a plugin cannot open it, so the line is in
    # the message log as well.
    assert any(press in (params or {}).get("text", "") for params in said)


def test_a_ribbon_press_on_the_wrong_node_names_what_was_chosen(monkeypatch, tmp_path):
    import main

    monkeypatch.setattr(main, "call", lambda op, params=None: {})
    monkeypatch.setattr(main.database, "gisdbase", lambda: str(tmp_path))
    node = main.database.mapset_node("Normandie/PERMANENT")
    out = main.load_workspace({"params": {}, "panel": {"values": {"database": node}}})
    assert (
        "Normandie" in out["asked"] and "a workspace under Workspaces" in out["asked"]
    )


def test_run_module_with_nothing_chosen_opens_the_catalogue(monkeypatch, tmp_path):
    """It said "'None' is not a module of this GRASS installation" before."""
    import main

    said = []
    monkeypatch.setattr(main, "call", lambda op, params=None: said.append(params) or {})
    monkeypatch.setattr(main, "load_catalogue", lambda: {"catalogue": []})
    monkeypatch.setattr(main.raster, "read_recents", lambda *a, **k: [])
    out = main.run_module({"params": {}, "panel": {"values": {}}})
    panel_out = out["panel"]
    assert panel_out["values"]["step"] == "modules"
    assert panel_out["items"]["modules"]["visible"] is True
    assert panel_out["items"]["run-module"]["enabled"] is False
    assert "Run Module" in out["asked"]
    assert any("Run Module" in (params or {}).get("text", "") for params in said)
