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
    assert by["helper"]["kind"] == "text", "a vector layer the form cannot pass is typed"
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


def test_a_required_flag_or_parameter_is_a_reason_not_a_silent_failure():
    flag = interface.describe(raster_task('<flag name="c" required="yes" />'))
    assert flag["reason"] == "needs flag -c"
    param = interface.describe(
        raster_task(
            '<parameter name="threshold" type="float" required="yes">'
            "<description>Cut-off</description></parameter>"
        )
    )
    assert param["reason"] == "needs threshold"
    assert param["needs"] == ["threshold"]


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


def test_a_temporal_module_needing_a_dataset_says_the_form_cannot_name_it():
    extra = """<parameter name="input" type="string" required="yes">
      <description>Input space-time dataset</description>
      <gisprompt age="old" element="strds" prompt="strds" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is False
    assert "space-time dataset" in entry["mapset_reason"]


def test_a_required_output_name_is_not_something_the_form_can_fill():
    extra = """<parameter name="output" type="string" required="yes">
      <description>Output raster</description>
      <gisprompt age="new" element="cell" prompt="raster" />
    </parameter>"""
    entry = interface.describe(temporal_task(extra))
    assert entry["mapset_runnable"] is False
    assert "output name" in entry["mapset_reason"]


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


def test_a_display_module_is_not_offered_without_a_display():
    entry = interface.describe(raster_task(name="d.example"))
    assert entry["runnable"] is False
    assert entry["reason"] == "needs a display"


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
        "mode/imagery",
    )
    assert state["panel"]["values"]["mode"] == "mode/imagery"
    assert state["panel"]["items"]["mode"]["nodes"] == [
        {"id": "mode/all", "label": "All modules", "count": 1},
        {"id": "mode/imagery", "label": "Imagery", "count": 1},
        {"id": "mode/temporal", "label": "Temporal", "count": 0},
    ]
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
        lambda req, mode=None: seen.append(mode) or {"panel": {}},
    )
    assert main.run_command({"id": "temporal-state"}) == {"panel": {}}
    assert seen == ["mode/temporal"]
