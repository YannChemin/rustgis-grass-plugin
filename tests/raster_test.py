"""Tests for the raster commands' own decisions.

Nothing here runs GRASS: these cover what the bridge works out before and
after a module runs, which is where a wrong answer would be silent.

SPDX-License-Identifier: Unlicense
"""

import time

import pytest

from grass_bridge import database, raster, session


def layer(id, name, raster_layer=True, active=False):
    """Return one entry as ``host.layers`` answers it."""
    return {"id": id, "name": name, "raster": raster_layer, "active": active}


def test_no_raster_layer_says_how_to_get_one():
    with pytest.raises(session.GrassError) as e:
        raster.choose_raster([layer(1, "Cities", raster_layer=False)])
    assert "no raster layer" in str(e.value)


def test_the_panel_choice_wins_over_the_active_layer():
    layers = [layer(1, "DEM A"), layer(2, "DEM B", active=True)]
    assert raster.choose_raster(layers, "1")["name"] == "DEM A"


def test_a_choice_of_a_layer_that_left_the_map_names_what_is_there():
    with pytest.raises(session.GrassError) as e:
        raster.choose_raster([layer(2, "DEM B")], "1")
    assert "DEM B" in str(e.value)


def test_the_active_raster_is_taken_when_nothing_is_chosen():
    layers = [layer(1, "DEM A"), layer(2, "DEM B", active=True)]
    assert raster.choose_raster(layers)["name"] == "DEM B"


def test_a_single_raster_needs_no_choosing():
    layers = [layer(1, "Cities", raster_layer=False), layer(2, "DEM")]
    assert raster.choose_raster(layers)["name"] == "DEM"


def test_several_rasters_and_no_choice_is_an_error_naming_them():
    with pytest.raises(session.GrassError) as e:
        raster.choose_raster([layer(1, "DEM A"), layer(2, "DEM B")])
    assert "DEM A" in str(e.value) and "DEM B" in str(e.value)


def test_only_raster_layers_reach_the_panel_tree():
    nodes = raster.raster_nodes(
        [layer(1, "Cities", raster_layer=False), layer(7, "DEM")]
    )
    assert nodes == [{"id": "7", "label": "DEM"}]


def test_slope_is_in_degrees_unless_the_panel_says_percent():
    argv, notes = raster.module_args("raster-slope", {})
    assert "format=degrees" in argv and "degrees" in notes[0]
    argv, notes = raster.module_args("raster-slope", {"percent": True})
    assert "format=percent" in argv and "percent" in notes[0]


def test_aspect_says_what_its_numbers_mean():
    argv, notes = raster.module_args("raster-aspect", {})
    assert argv[:2] == ["elevation=src", "aspect=out"]
    assert "-n" in argv
    assert "clockwise from north" in notes[0] and "-9999" in notes[0]


def test_a_viewshed_needs_somewhere_to_look_from():
    with pytest.raises(session.GrassError):
        raster.module_args("raster-viewshed", {})


def test_a_viewshed_range_is_given_in_metres_and_said_in_kilometres():
    argv, notes = raster.module_args(
        "raster-viewshed", {"height": 30, "maxdist": 5}, (500.0, 4000.0)
    )
    assert "coordinates=500.000000,4000.000000" in argv
    assert "observer_elevation=30" in argv
    assert "max_distance=5000" in argv
    assert any("5 km" in note for note in notes)


def test_a_viewshed_without_a_range_says_so_and_passes_none():
    argv, notes = raster.module_args("raster-viewshed", {"maxdist": 0}, (1.0, 2.0))
    assert not any(a.startswith("max_distance") for a in argv)
    assert any("not cut off" in note for note in notes)


def test_the_curvature_of_the_earth_is_a_choice_that_is_reported():
    argv, notes = raster.module_args("raster-viewshed", {"curvature": True}, (1.0, 2.0))
    assert "-c" in argv
    assert any("curvature" in note for note in notes)


def test_an_unmapped_command_is_an_error():
    with pytest.raises(session.GrassError):
        raster.module_args("raster-watershed", {})


def test_results_are_named_after_the_layer_and_never_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    first = raster.output_path("DEM 1/2", "slope")
    assert first.endswith("DEM_1_2_slope.tif")
    open(first, "w").close()
    assert raster.output_path("DEM 1/2", "slope") != first


def test_a_run_past_its_deadline_names_the_limit_rustgis_sets():
    run = session.Run.__new__(session.Run)
    run.deadline = time.monotonic() - 1
    with pytest.raises(session.GrassError) as e:
        run.left()
    assert str(session.COMMAND_LIMIT) in str(e.value)


def test_a_run_without_a_deadline_gets_the_module_timeout():
    run = session.Run.__new__(session.Run)
    run.deadline = None
    assert run.left() == session.TIMEOUT


class FakeRun(raster.RasterRun):
    """A run that answers m.proj itself, so the region logic needs no GRASS."""

    def __init__(self, answers):
        self.answers = answers
        self.calls = []
        self.deadline = None
        self.warnings = {}

    def exec(self, project, module, *args):
        self.calls.append((module, args))
        answer = self.answers.get(module, "")
        # A list answers one call after another, as projecting corners does.
        if isinstance(answer, list):
            return answer[min(len(self.calls), len(answer)) - 1]
        return answer


REGION = {"w": "500000", "e": "510000", "s": "4790000", "n": "4800000"}


def test_a_cell_size_in_degrees_is_kept_for_a_raster_in_degrees():
    ns, ew, how = FakeRun({})._cell_size(None, 0.001, True, REGION)
    assert (ns, ew) == (0.001, 0.001)
    assert "taken as it is" in how


def test_a_cell_size_in_degrees_shortens_eastwards_for_a_projected_raster():
    run = FakeRun({"m.proj": "3.03,43.31\n"})
    ns, ew, how = run._cell_size("p", 0.001, False, REGION)
    assert ns == pytest.approx(110.54)
    assert ew == pytest.approx(81.0, abs=0.5)  # 111320 * cos(43.31 degrees)
    assert ew < ns and "43.31" in how


def test_an_unreadable_latitude_falls_back_to_the_equator():
    ns, ew, _ = FakeRun({"m.proj": "rubbish"})._cell_size("p", 0.001, False, REGION)
    assert ew == pytest.approx(raster.METRES_PER_DEGREE_LON * 0.001)
    assert ns == pytest.approx(raster.METRES_PER_DEGREE_LAT * 0.001)


def test_an_environment_extent_is_clipped_to_the_raster():
    # The corners project to a box reaching past the raster to the west and
    # south, and stopping short of it to the east and north.
    run = FakeRun(
        {
            "m.proj": [
                "495000,4785000\n",
                "495000,4795000\n",
                "505000,4785000\n",
                "505000,4795000\n",
                "500000,4785000\n",
                "500000,4795000\n",
            ]
        }
    )
    box = run._box("p", [2.9, 43.2, 3.1, 43.4], REGION)
    assert box == {"w": 500000.0, "e": 505000.0, "s": 4790000.0, "n": 4795000.0}


def test_an_extent_that_misses_the_raster_is_an_error_that_says_where_to_set_it():
    run = FakeRun({"m.proj": "100,200\n"})
    with pytest.raises(session.GrassError) as e:
        run._box("p", [-70, -30, -60, -20], REGION)
    assert "Environments" in str(e.value)


def test_a_warning_wrapped_over_several_lines_is_kept_whole():
    text = (
        "WARNING: East-west resolution does not equal north-south resolution.\n"
        "         The viewshed will be computed anyway.\n"
        "Reading elevation map...\n"
    )
    whole = (
        "East-west resolution does not equal north-south resolution. "
        "The viewshed will be computed anyway."
    )
    assert session._warnings(text) == [whole]


def test_an_indented_line_after_other_output_is_not_taken_for_a_warning():
    assert session._warnings("Reading...\n   100%\n") == []


def test_a_node_id_names_a_map_and_reads_back(tmp_path):
    node = database.node_id("raster", "C2RD_drone", "PERMANENT", "lidarhd_mnt")
    assert node == "raster/C2RD_drone/PERMANENT/lidarhd_mnt"
    assert database.parse_node(node) == (
        "raster",
        "C2RD_drone",
        "PERMANENT",
        "lidarhd_mnt",
    )


def test_choosing_a_project_instead_of_a_map_says_so():
    with pytest.raises(session.GrassError) as e:
        database.parse_node("project/C2RD_drone")
    assert "choose a map" in str(e.value)


def test_a_mapset_or_a_map_both_say_which_mapset_to_open():
    assert database.opened("mapset/P/PERMANENT") == ("P", "PERMANENT")
    assert database.opened("raster/P/PERMANENT/dem") == ("P", "PERMANENT")
    assert database.opened("project/P") is None
    assert database.opened(None) is None


def test_a_chosen_mapset_is_checked_before_a_module_writes_there(tmp_path):
    base = tmp_path
    (base / "P" / "PERMANENT").mkdir(parents=True)
    (base / "P" / "PERMANENT" / "WIND").write_text("")
    assert database.chosen_mapset(str(base), "mapset/P/PERMANENT") == (
        "P",
        "PERMANENT",
    )
    assert database.chosen_mapset(str(base), "raster/P/PERMANENT/dem") == (
        "P",
        "PERMANENT",
    )
    assert database.chosen_mapset(str(base), "mapset/../PERMANENT") is None
    assert database.chosen_mapset(str(base), "mapset/P/NOPE") is None
    assert database.chosen_mapset(str(base), "project/P") is None
    assert database.chosen_mapset(str(base), None) is None


def fake_database(root, layout):
    """Write a GRASS database of empty maps and return its path."""
    for project, mapsets_ in layout.items():
        for mapset, names in mapsets_.items():
            base = root / project / mapset
            (base).mkdir(parents=True)
            (base / "WIND").write_text("")
            for kind, name in names:
                if kind == "raster":
                    (base / "cellhd").mkdir(exist_ok=True)
                    (base / "cellhd" / name).write_text("")
                else:
                    (base / "vector" / name).mkdir(parents=True)
    return str(root)


def test_only_folders_holding_a_permanent_mapset_are_projects(tmp_path):
    base = fake_database(tmp_path, {"site": {"PERMANENT": [("raster", "dem")]}})
    (tmp_path / "notes.txt").write_text("a log beside the projects")
    (tmp_path / "stray").mkdir()
    assert database.projects(base) == ["site"]


def test_permanent_comes_first_among_the_mapsets(tmp_path):
    base = fake_database(
        tmp_path,
        {"site": {"PERMANENT": [("raster", "dem")], "alpha": [("vector", "roads")]}},
    )
    assert database.mapsets(base, "site") == ["PERMANENT", "alpha"]


def test_rasters_and_vectors_are_both_found(tmp_path):
    base = fake_database(
        tmp_path, {"site": {"PERMANENT": [("raster", "dem"), ("vector", "roads")]}}
    )
    assert database.maps(base, "site", "PERMANENT") == [
        ("raster", "dem"),
        ("vector", "roads"),
    ]


def test_a_mapset_lists_its_maps_only_when_it_is_the_one_opened(tmp_path):
    base = fake_database(
        tmp_path, {"site": {"PERMANENT": [("raster", "dem"), ("raster", "slope")]}}
    )
    closed, _ = database.tree(base)
    assert closed[0]["count"] == 2
    assert "children" not in closed[0]["children"][0]
    open_, _ = database.tree(base, ("site", "PERMANENT"))
    assert [c["label"] for c in open_[0]["children"][0]["children"]] == [
        "dem (raster)",
        "slope (raster)",
    ]


def test_an_empty_mapset_is_left_out(tmp_path):
    base = fake_database(tmp_path, {"site": {"PERMANENT": []}})
    assert database.tree(base) == ([], [])


def test_the_settings_file_says_where_the_database_is(tmp_path, monkeypatch):
    (tmp_path / "grassdata").mkdir()
    rc = tmp_path / "rc"
    rc.write_text(f"GISDBASE: {tmp_path / 'grassdata'}\nMAPSET: PERMANENT\n")
    monkeypatch.delenv("GISDBASE", raising=False)
    monkeypatch.setattr(database, "RC_FILES", (str(rc),))
    monkeypatch.setattr(database, "DEFAULT_DIR", str(tmp_path / "nothing"))
    assert database.gisdbase() == str(tmp_path / "grassdata")


def test_the_environment_wins_over_the_settings_file(tmp_path, monkeypatch):
    (tmp_path / "session").mkdir()
    monkeypatch.setenv("GISDBASE", str(tmp_path / "session"))
    monkeypatch.setattr(database, "RC_FILES", ())
    assert database.gisdbase() == str(tmp_path / "session")


def test_no_database_anywhere_is_none(tmp_path, monkeypatch):
    monkeypatch.delenv("GISDBASE", raising=False)
    monkeypatch.setattr(database, "RC_FILES", ())
    monkeypatch.setattr(database, "DEFAULT_DIR", str(tmp_path / "nothing"))
    assert database.gisdbase() is None


def test_a_size_is_readable():
    assert database._size(512) == "512 bytes"
    assert database._size(2048) == "2.0 kB"
    assert database._size(5 * 1024 * 1024) == "5.0 MB"


def test_a_raster_with_no_coordinate_system_is_refused():
    with pytest.raises(session.GrassError, match="no coordinate system"):
        raster.check_source({"georeferenced": False}, "scan.tif")


def test_a_georeferenced_raster_passes_and_so_does_a_silent_one():
    raster.check_source({"georeferenced": True}, "dem")
    raster.check_source({}, "dem")  # raster.info said nothing; do not guess.


def test_a_single_band_raster_needs_no_band_choice():
    band, note = raster.choose_band({"bands": [{"name": "elevation"}]}, {})
    assert band is None and note is None


def test_the_panel_chooses_the_band_and_it_is_reported():
    info = {"bands": [{"name": "b1"}, {"name": "b2"}, {"name": "b3"}]}
    band, note = raster.choose_band(info, {"band": 2})
    assert band == 2
    assert "3 bands" in note and "b2" in note


def test_a_band_outside_the_raster_is_brought_back_inside():
    info = {"bands": [{"name": "b1"}, {"name": "b2"}]}
    assert raster.choose_band(info, {"band": 9})[0] == 2
    assert raster.choose_band(info, {"band": 0})[0] == 1


def test_the_band_slider_covers_exactly_the_bands_there_are():
    item = raster.band_slider({"bands": [{"name": "red"}, {"name": "nir"}]})
    assert item["min"] == 1 and item["max"] == 2
    assert item["labels"] == ["red", "nir"] and item["enabled"] is True
    assert raster.band_slider({"bands": [{"name": "only"}]})["enabled"] is False


def test_the_source_is_described_in_its_own_units():
    note = raster.source_notes(
        {
            "width": 100,
            "height": 50,
            "cellSize": [30, 30],
            "crs": "EPSG:32631",
            "dataType": "Float32",
        }
    )[0]
    assert "100 by 50" in note and "30 by 30" in note and "EPSG:32631" in note


def test_a_run_on_an_overview_says_the_result_is_coarser():
    notes = raster.source_notes(
        {"width": 1000, "height": 500},
        {"width": 1000, "height": 500, "overviewOf": [8000, 4000]},
    )
    assert any("overview" in n and "coarser" in n for n in notes)


def test_a_full_resolution_export_adds_no_overview_note():
    notes = raster.source_notes({"width": 10, "height": 10}, {"path": "x.tif"})
    assert not any("overview" in n for n in notes)


def entry(module, family="Raster", runnable=True, **fields):
    """Return one catalogue entry as ``generate_manifest.py`` writes it."""
    out = {
        "module": module,
        "family": family,
        "summary": f"{module} summary",
        "keywords": "keyword",
        "raster_in": ["input"],
        "raster_out": ["output"],
        "raster_input": "input",
        "raster_output": "output",
        "runnable": runnable,
        "reason": "" if runnable else "takes no raster",
        "needs": [],
        "bands": False,
        "temporal": False,
    }
    out.update(fields)
    return out


def test_the_module_tree_branches_into_runs_all_and_recent():
    catalogue = [
        entry("r.slope.aspect"),
        entry("r.watershed"),
        entry("i.pca", "Imagery", False, reason="needs several bands"),
    ]
    nodes, notes = raster.catalogue_tree(
        catalogue, "runs/r.watershed", ["i.pca", "r.slope.aspect"]
    )
    assert [n["id"] for n in nodes] == ["branch/runs", "branch/all", "branch/recent"]
    runs, every, recent = nodes
    assert runs["label"] == "Runs from here (2)"
    assert every["label"] == "All modules (3)"
    assert recent["label"] == "Recently run (2)"
    assert recent["children"][0]["id"] == "recent/i.pca"
    # The runnable modules are the two raster ones in their family branch.
    family = runs["children"][0]
    assert family["id"] == "runs/family/Raster"
    assert [n["id"] for n in family["children"]] == [
        "runs/r.slope.aspect",
        "runs/r.watershed",
    ]
    # A module that cannot run is marked with the reason in the all-modules tree.
    imagery = next(n for n in every["children"] if n["label"] == "Imagery")
    assert "[needs several bands]" in imagery["children"][0]["label"]
    assert notes == []


def test_the_module_tree_can_show_one_family_only():
    catalogue = [
        entry("r.slope.aspect"),
        entry("i.edge", "Imagery"),
        entry("i.pca", "Imagery", False, reason="needs several bands"),
    ]
    nodes, _ = raster.catalogue_tree(catalogue, family="Imagery")
    runs, every, recent = nodes
    assert runs["label"] == "Runs from here (1)"
    assert every["label"] == "All imagery modules (2)"
    assert [n["id"] for n in runs["children"][0]["children"]] == ["runs/i.edge"]
    assert [n["id"] for n in every["children"][0]["children"]] == [
        "all/i.edge",
        "all/i.pca",
    ]
    assert recent["children"] == []


def test_the_module_tree_keeps_only_temporal_modules_in_its_mode():
    catalogue = [
        entry("r.slope.aspect"),
        entry(
            "t.rast.series",
            "Temporal",
            False,
            reason="takes no raster",
            temporal=True,
        ),
    ]
    nodes, _ = raster.catalogue_tree(catalogue, family="Temporal")
    runs, every, recent = nodes
    assert runs["label"] == "Runs from here (0)"
    assert every["label"] == "All temporal modules (1)"
    assert [n["id"] for n in every["children"][0]["children"]] == [
        "all/t.rast.series"
    ]
    assert recent["children"] == []


def test_the_mode_tree_names_the_families_and_their_sizes():
    catalogue = [
        entry("r.slope.aspect"),
        entry("i.edge", "Imagery"),
        entry("i.pca", "Imagery", False, reason="needs several bands"),
    ]
    assert raster.mode_nodes(catalogue) == [
        {"id": "mode/all", "label": "All modules", "count": 3},
        {"id": "mode/imagery", "label": "Imagery", "count": 2},
        {"id": "mode/temporal", "label": "Temporal", "count": 0},
    ]
    assert raster.mode_family("mode/imagery") == "Imagery"
    assert raster.mode_family("mode/temporal") == "Temporal"
    assert raster.mode_family("mode/all") is None
    assert raster.mode_family("mode/no-such-mode") is None


def test_the_recent_branch_is_present_before_anything_has_run():
    nodes, _ = raster.catalogue_tree([entry("r.slope.aspect")])
    assert [n["id"] for n in nodes] == ["branch/runs", "branch/all", "branch/recent"]
    assert nodes[-1]["label"] == "Recently run (0)"
    assert nodes[-1]["children"] == []


def test_the_tree_says_when_the_chosen_module_cannot_run():
    _nodes, notes = raster.catalogue_tree(
        [entry("i.pca", "Imagery", False, reason="needs several bands")],
        "all/i.pca",
    )
    assert "i.pca cannot be run from this panel: needs several bands" in notes[0]


def test_a_tree_node_names_its_module_whatever_branch_it_sits_in():
    catalogue = [entry("r.slope.aspect")]
    for node in (
        "r.slope.aspect",
        "runs/r.slope.aspect",
        "all/r.slope.aspect",
        "recent/r.slope.aspect",
    ):
        assert raster.entry_for(catalogue, node)["module"] == "r.slope.aspect"


def test_choosing_a_family_or_a_branch_asks_for_a_module_by_name():
    catalogue = [entry("r.slope.aspect")]
    for node in ("branch/runs", "runs/family/Raster", "all/family/Imagery"):
        with pytest.raises(session.GrassError) as e:
            raster.entry_for(catalogue, node)
        assert "choose a module" in str(e.value)
    assert raster.entry_for(catalogue, "branch/runs", quietly=True) is None


def test_run_module_names_the_input_and_output_the_module_requires():
    watershed = entry(
        "r.watershed",
        raster_in=["elevation", "depression", "flow"],
        raster_out=["basin", "accumulation"],
        raster_input="elevation",
        raster_output="basin",
    )
    assert raster.free_module_args(watershed) == ["elevation=src", "basin=out"]


def test_form_args_name_flags_choices_multiples_and_numbers():
    entry = {
        "module": "r.example",
        "form": [
            {"id": "method", "kind": "select", "choices": ["fast", "slow"]},
            {"id": "vars", "kind": "multi", "choices": ["a", "b"]},
            {"id": "count", "kind": "number", "integer": True},
            {"id": "distance", "kind": "number"},
            {"id": "label", "kind": "text"},
            {"id": "flag_n", "kind": "checkbox"},
        ],
    }
    values = {
        "method": "fast",
        "vars": ["a", "b"],
        "count": 2.0,
        "distance": 1.5,
        "label": "",
        "flag_n": True,
        "not_a_field": "ignored",
    }
    assert raster.form_args(entry, values) == [
        "method=fast",
        "vars=a,b",
        "count=2",
        "distance=1.5",
        "-n",
    ]
    # A value the module does not offer, and an empty text, are left out.
    assert raster.form_args(entry, {"method": "nope", "label": ""}) == []
    assert raster.form_args(entry, {"vars": "a,b"}) == ["vars=a,b"]
    assert raster.form_args(entry, None) == []


def test_missing_form_values_names_only_what_has_no_default_or_value():
    entry = {
        "module": "t.in.era5",
        "form": [
            {"id": "variables", "kind": "multi", "required": True, "choices": ["t2m"]},
            {"id": "start", "kind": "text", "required": True},
            {"id": "prefix", "kind": "text", "required": True, "default": "era5"},
            {"id": "flag_c", "kind": "checkbox", "required": True},
            {"id": "levels", "kind": "number", "required": True, "integer": True},
        ],
    }
    assert raster.missing_form_values(entry, {}) == [
        "variables",
        "start",
        "flag_c",
        "levels",
    ]
    assert raster.missing_form_values(
        entry,
        {
            "variables": ["t2m"],
            "start": "2020-01-01",
            "flag_c": True,
            "levels": 3,
        },
    ) == []
    assert raster.missing_form_values(
        entry,
        {
            "variables": ["nope"],
            "start": " ",
            "flag_c": False,
            "levels": 3.5,
        },
    ) == ["variables", "start", "flag_c", "levels"]


def test_a_mapset_module_is_marked_before_its_summary_is_clipped():
    label = raster._module_label(
        entry(
            "t.in.era5",
            "Temporal",
            False,
            mapset_runnable=True,
            mapset_reason="",
            summary="A summary long enough to clip later.",
        )
    )
    assert label.startswith("▸ t.in.era5 [in a chosen mapset] — ")


def test_the_details_text_says_a_mapset_module_runs_in_a_chosen_mapset():
    details = raster.module_details(
        entry(
            "t.in.era5",
            "Temporal",
            False,
            mapset_runnable=True,
            mapset_reason="",
            reason="takes no raster",
        )
    )
    assert "Runs here in a GRASS mapset" in details
    assert "Projects and mapsets" in details
    assert "Not runnable from this panel" not in details


def test_run_module_refuses_a_module_it_cannot_drive_and_says_why():
    with pytest.raises(session.GrassError) as e:
        raster.free_module_args(
            entry("i.pca", "Imagery", False, reason="needs several bands")
        )
    assert "needs several bands" in str(e.value)


def test_the_details_text_states_what_a_module_needs():
    runnable = raster.module_details(entry("r.slope.aspect"))
    assert "r.slope.aspect" in runnable
    assert "Reads: input" in runnable and "Writes: output" in runnable
    assert "the form above sets its parameters" in runnable

    blocked = raster.module_details(
        entry(
            "i.emissivity",
            "Imagery",
            False,
            reason="needs an imagery group",
            needs=["group"],
            temporal=True,
        )
    )
    assert "Not runnable from this panel" in blocked
    assert "needs an imagery group" in blocked
    assert "Needs: group" in blocked
    assert "space-time dataset" in blocked
    assert "Choose a module" in raster.module_details(None)


def test_recents_are_newest_first_without_repeats(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert raster.read_recents() == []
    raster.remember("r.slope.aspect")
    raster.remember("r.watershed")
    raster.remember("r.slope.aspect")
    assert raster.read_recents() == ["r.slope.aspect", "r.watershed"]


def test_recents_are_capped_and_a_broken_file_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    for number in range(raster.MAX_RECENT + 3):
        raster.remember(f"r.example{number}")
    assert len(raster.read_recents()) == raster.MAX_RECENT
    assert raster.read_recents()[0] == f"r.example{raster.MAX_RECENT + 2}"
    with open(raster.recent_path(), "w") as f:
        f.write("{not json")
    assert raster.read_recents() == []


def test_a_cache_that_cannot_be_written_never_fails_a_run(monkeypatch):
    def refuse():
        raise PermissionError("read-only cache")

    monkeypatch.setattr(raster, "output_dir", refuse)
    assert raster.read_recents() == []
    assert raster.remember("r.slope.aspect") == ["r.slope.aspect"]


def vector_layer(id, name):
    """Return one vector entry as ``host.layers`` answers it."""
    return {
        "id": id,
        "name": name,
        "raster": False,
        "geometry": "Polygon",
        "active": False,
    }


def display_entry(module="d.vect", **fields):
    """Return a display module entry with one vector input."""
    return entry(
        module,
        "Display",
        False,
        reason="renders a picture",
        render_runnable=True,
        render_inputs=[
            {
                "name": "map",
                "kind": "vector",
                "label": "Name of vector map",
                "help": "",
                "required": True,
                "multiple": False,
            }
        ],
        **fields,
    )


def test_a_render_form_asks_for_each_map_kind_of_the_chosen_mapset():
    maps = [("raster", "DEM"), ("vector", "Roads")]
    fields = raster.render_form(display_entry(), maps, "PERMANENT")
    by = {f["id"]: f for f in fields}
    assert by["map"]["kind"] == "select"
    assert by["map"]["choices"] == ["Roads"]
    assert by["map"]["required"] is True
    assert by[raster.PREVIEW_FIELD]["kind"] == "checkbox"
    assert by[raster.PREVIEW_FIELD]["default"] is False


def test_a_render_form_keeps_a_field_whose_kind_the_mapset_lacks():
    maps = [("raster", "DEM")]
    fields = raster.render_form(display_entry(), maps, "PERMANENT")
    by = {f["id"]: f for f in fields}
    assert by["map"]["choices"] == ["(no vector maps in the PERMANENT mapset)"]
    assert by["map"]["required"] is True
    assert "Choose a vector map" in by["map"]["help"]


def test_a_render_form_does_not_ask_twice_for_the_vector_map():
    maps = [("vector", "Roads")]
    fields = raster.render_form(
        display_entry(form=[{"id": "map", "kind": "text"}]), maps
    )
    assert [f["id"] for f in fields].count("map") == 1


def test_a_render_plan_takes_each_input_by_name_from_the_one_mapset():
    maps = [("raster", "DEM"), ("vector", "Roads")]
    ports, preview = raster.render_plan(
        {
            "module": "d.vect",
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
        },
        {"raster": "1", "map": "Roads", raster.PREVIEW_FIELD: True},
        maps,
        "PERMANENT",
    )
    assert ports[0]["maps"] == ["Roads"]
    assert ports[0]["kind"] == "vector"
    assert preview is True


def test_a_render_plan_refuses_a_map_of_another_mapset():
    maps = [("raster", "DEM"), ("vector", "Roads")]
    with pytest.raises(session.GrassError) as e:
        raster.render_plan(
            display_entry(), {"map": "Roads@elsewhere"}, maps, "PERMANENT"
        )
    assert "not a vector map of the PERMANENT mapset" in str(e.value)


def test_a_render_plan_names_a_missing_required_layer():
    with pytest.raises(session.GrassError) as e:
        raster.render_plan(display_entry(), {}, [("raster", "DEM")], "PERMANENT")
    assert "map" in str(e.value).lower()


def test_render_args_keep_the_ports_out_of_the_module_form_values():
    entry = {
        "module": "d.his",
        "render_inputs": [
            {"name": "hue", "kind": "raster", "label": "Hue"},
            {"name": "intensity", "kind": "raster", "label": "Intensity"},
        ],
        "form": [{"id": "brighten", "kind": "select", "choices": ["1", "3"]}],
    }
    args = raster.render_args(
        entry,
        {
            "hue": "h",
            "intensity": "i",
            "brighten": "3",
            raster.PREVIEW_FIELD: True,
        },
        {"hue": ["src1"], "intensity": ["src2"]},
    )
    assert args == ["hue=src1", "intensity=src2", "brighten=3"]


def test_a_display_module_gets_the_flag_its_picture_needs():
    title = {"module": "d.title", "render_inputs": [], "form": []}
    assert raster.render_args(title, {}, {}) == ["-d"]
    thematic = {
        "module": "d.vect.thematic",
        "render_inputs": [],
        "form": [{"id": "breaks", "kind": "text"}],
    }
    assert raster.render_args(thematic, {}, {}) == ["algorithm=int"]
    assert (
        raster.render_args(thematic, {"breaks": "10,20"}, {})
        == ["breaks=10,20"]
    )


def test_a_render_module_is_in_runs_from_here_and_says_it_renders():
    catalogue = [display_entry()]
    nodes, notes = raster.catalogue_tree(catalogue, "d.vect")
    runs = next(node for node in nodes if node["id"] == "branch/runs")
    assert runs["count"] == 1
    assert "renders a picture" in nodes[0]["children"][0]["children"][0]["label"]
    assert "renders a picture" in notes[0]
    assert "Renders a picture" in raster.module_details(display_entry())


def test_a_render_form_offers_a_none_for_an_optional_input():
    display = entry(
        "d.rast",
        "Display",
        False,
        render_runnable=True,
        render_inputs=[
            {
                "name": "map",
                "kind": "raster",
                "label": "Name of raster map",
                "help": "",
                "required": False,
                "multiple": False,
            }
        ],
    )
    fields = raster.render_form(display, [("raster", "DEM")], "PERMANENT")
    by = {field["id"]: field for field in fields}
    assert by["map"]["choices"] == ["none", "DEM"]
    assert by["map"]["default"] == "none"
