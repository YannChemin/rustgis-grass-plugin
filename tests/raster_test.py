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
    closed, _ = database.tree(base, home="")
    assert closed[0]["count"] == 2
    assert "children" not in closed[0]["children"][0]
    open_, _ = database.tree(base, ("site", "PERMANENT"), home="")
    assert [c["label"] for c in open_[0]["children"][0]["children"]] == [
        "dem (raster)",
        "slope (raster)",
    ]


def test_an_empty_mapset_is_left_out(tmp_path):
    base = fake_database(tmp_path, {"site": {"PERMANENT": []}})
    assert database.tree(base, home="") == ([], [])


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
    assert [n["id"] for n in every["children"][0]["children"]] == ["all/t.rast.series"]
    assert recent["children"] == []


def test_the_catalogue_dropdown_names_a_family_and_the_old_tree_ids_still_read():
    assert raster.mode_family("imagery") == "Imagery"
    assert raster.mode_family("temporal") == "Temporal"
    assert raster.mode_family("all") is None
    assert raster.mode_family("no-such-family") is None
    # The ids of the three-node tree the dropdown replaced.
    assert raster.mode_family("mode/imagery") == "Imagery"
    assert raster.mode_family("mode/temporal") == "Temporal"
    assert raster.mode_family("mode/all") is None


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
    assert (
        raster.missing_form_values(
            entry,
            {
                "variables": ["t2m"],
                "start": "2020-01-01",
                "flag_c": True,
                "levels": 3,
            },
        )
        == []
    )
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


def inplace_entry(module="r.colors", **fields):
    """Return a raster module that changes a map of the chosen mapset."""
    return entry(
        module,
        "Raster",
        False,
        reason="writes no raster",
        mapset_runnable=True,
        mapset_inputs=[
            {
                "name": "map",
                "kind": "raster",
                "label": "Name of raster map(s)",
                "help": "",
                "required": True,
                "multiple": True,
            }
        ],
        **fields,
    )


def test_a_mapset_form_offers_the_chosen_mapsets_maps():
    module = inplace_entry(
        form=[{"id": "color", "kind": "select", "choices": ["grey"]}]
    )
    fields = raster.mapset_form(
        module, [("raster", "DEM"), ("raster", "NDVI")], "PERMANENT"
    )
    by = {field["id"]: field for field in fields}
    assert by["map"]["kind"] == "multi"
    assert by["map"]["choices"] == ["DEM", "NDVI"]
    assert by["map"]["required"] is True
    assert by["color"]["choices"] == ["grey"]


def test_a_mapset_form_replaces_a_vector_maps_text_field():
    module = entry(
        "v.db.update",
        "Vector",
        False,
        mapset_runnable=True,
        mapset_inputs=[
            {
                "name": "map",
                "kind": "vector",
                "label": "Name of vector map",
                "help": "",
                "required": True,
                "multiple": False,
            }
        ],
        form=[{"id": "map", "kind": "text"}, {"id": "column", "kind": "text"}],
    )
    fields = raster.mapset_form(module, [("vector", "Roads")], "PERMANENT")
    by = {field["id"]: field for field in fields}
    assert by["map"]["kind"] == "select"
    assert by["map"]["choices"] == ["Roads"]
    assert [field["id"] for field in fields].count("map") == 1
    assert "column" in by


def test_a_mapset_plan_takes_the_map_by_name_from_that_mapset():
    ports = raster.mapset_plan(
        inplace_entry(),
        {"map": ["DEM", "NDVI"]},
        [("raster", "DEM"), ("raster", "NDVI")],
        "PERMANENT",
    )
    assert ports == [
        {
            "name": "map",
            "kind": "raster",
            "multiple": True,
            "maps": ["DEM", "NDVI"],
        }
    ]


def test_a_mapset_plan_refuses_a_map_of_another_mapset():
    with pytest.raises(session.GrassError) as e:
        raster.mapset_plan(
            inplace_entry(),
            {"map": ["DEM@elsewhere"]},
            [("raster", "DEM")],
            "PERMANENT",
        )
    assert "not a raster map of the PERMANENT mapset" in str(e.value)


def test_mapset_args_put_the_map_before_the_modules_own_parameters():
    module = inplace_entry(
        form=[{"id": "color", "kind": "select", "choices": ["grey", "elevation"]}]
    )
    args = raster.mapset_args(
        module,
        {"map": "DEM", "color": "elevation"},
        {"map": ["DEM"]},
    )
    assert args == ["map=DEM", "color=elevation"]


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
    assert raster.render_args(thematic, {"breaks": "10,20"}, {}) == ["breaks=10,20"]


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


def test_a_viewshed_says_whether_the_viewpoint_was_picked_or_assumed():
    _, picked = raster.module_args(
        "raster-viewshed", {"height": 2}, (500.0, 4000.0), picked=True
    )
    assert any("the place picked on the map" in note for note in picked)
    assert any("500.000000, 4000.000000" in note for note in picked)
    _, assumed = raster.module_args("raster-viewshed", {"height": 2}, (500.0, 4000.0))
    # Falling back to the centre of the map is the old behaviour; it is kept,
    # but never silently.
    assert any("no viewpoint was picked" in note for note in assumed)


def test_a_run_keeps_to_two_minutes_unless_the_caller_asks_for_longer():
    # The desktop app stops a command at 120 seconds whatever the manifest
    # declares, and nothing tells the plugin which host it is in, so the
    # default has to stay 120 and a longer one has to be asked for.
    assert session.budget_asked(None) == session.COMMAND_LIMIT
    assert session.budget_asked({}) == session.COMMAND_LIMIT
    assert session.budget_asked({"timeout": 3600}) == 3600
    assert session.budget_asked({"timeout": "90"}) == 90
    for bad in ({"timeout": "soon"}, {"timeout": 0}, {"timeout": 86401}):
        with pytest.raises(session.GrassError):
            session.budget_asked(bad)


def test_a_run_that_runs_out_says_what_it_was_given():
    run = raster.RasterRun.__new__(raster.RasterRun)
    run.deadline = time.monotonic() - 1
    run.budget = 3600
    with pytest.raises(session.GrassError) as raised:
        run.left()
    assert "3600 seconds" in str(raised.value)
    assert "timeout parameter" in str(raised.value)


def test_a_project_s_crs_is_read_from_its_srid(monkeypatch):
    # g.proj -g prints srid=EPSG:32630 for a project with a coordinate system
    # and no srid at all for an XY one, so the EPSG code is read rather than
    # rebuilt from the projection parameters.
    import subprocess

    out = {
        "with": "name=WGS 84 / UTM zone 30N\nproj=utm\nzone=30\nsrid=EPSG:32630\nunit=meter\n",
        "without": "name=xy_location_unprojected\n",
    }
    run = database.Export.__new__(database.Export)
    run.grass = "grass"
    run.deadline = None

    for key, expected in (("with", "EPSG:32630"), ("without", None)):
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, _text=out[key], **k: subprocess.CompletedProcess(
                [], 0, _text, ""
            ),
        )
        assert run.crs("/db", "project") == expected


def test_a_crs_that_cannot_be_read_is_not_guessed_at(monkeypatch):
    import subprocess

    run = database.Export.__new__(database.Export)
    run.grass = "grass"
    run.deadline = None
    # A failed g.proj, and one whose srid is not an EPSG code, both mean "not
    # known" -- never a code invented from what else it printed.
    for result in (
        subprocess.CompletedProcess([], 1, "", "no such project"),
        subprocess.CompletedProcess([], 0, "srid=IAU_2015:49900\n", ""),
    ):
        monkeypatch.setattr(subprocess, "run", lambda *a, _done=result, **k: _done)
        assert run.crs("/db", "project") is None


def test_a_group_s_bands_are_read_from_its_ref_in_band_order(tmp_path):
    ref = tmp_path / "utm" / "PERMANENT" / "group" / "scene"
    ref.mkdir(parents=True)
    # REF is "<map> <mapset>" per line, in the band order i.group was given.
    (ref / "REF").write_text("red PERMANENT\ngreen PERMANENT\nblue other\n")
    found = database.groups(str(tmp_path), "utm", "PERMANENT")
    assert found == [
        ("scene", [("red", "PERMANENT"), ("green", "PERMANENT"), ("blue", "other")])
    ]


def test_a_group_with_no_readable_band_is_left_out_and_then_refused(tmp_path):
    base = tmp_path / "utm" / "PERMANENT" / "group"
    (base / "empty").mkdir(parents=True)
    (base / "empty" / "REF").write_text("")
    (base / "broken").mkdir(parents=True)
    # A half-written line names no (map, mapset) pair, and guessing at it
    # would put a wrong map in a composite.
    (base / "broken" / "REF").write_text("just_a_name\n")
    (base / "noref").mkdir(parents=True)
    assert database.groups(str(tmp_path), "utm", "PERMANENT") == []
    with pytest.raises(session.GrassError, match="no readable band"):
        database.group_members(str(tmp_path), "utm", "PERMANENT", "empty")


def test_three_bands_or_more_are_composed_with_d_rgb():
    members = [("red", "PERMANENT"), ("green", "PERMANENT"), ("blue", "PERMANENT")]
    module, args, bands, notes = raster.group_display(members, "PERMANENT")
    assert module == "d.rgb"
    assert args == [
        "red=red@PERMANENT",
        "green=green@PERMANENT",
        "blue=blue@PERMANENT",
    ]
    assert bands == [f"{n}@PERMANENT" for n, _ in members]
    assert "band order" in notes[0]


def test_a_fourth_band_is_left_out_and_said_to_be():
    members = [(n, "PERMANENT") for n in ("red", "green", "blue", "nir")]
    module, _, bands, notes = raster.group_display(members, "PERMANENT")
    assert module == "d.rgb" and len(bands) == 3
    assert "4 bands" in notes[1] and "nir@PERMANENT" in notes[1]


def test_two_bands_are_composed_with_d_his():
    module, args, _, _ = raster.group_display(
        [("ndvi", "PERMANENT"), ("shade", "PERMANENT")], "PERMANENT"
    )
    assert module == "d.his"
    assert args == ["hue=ndvi@PERMANENT", "intensity=shade@PERMANENT"]


def test_one_band_is_not_a_composite():
    # Dropping to a single-band render would be a grey picture of a raster the
    # user can simply add, so it is refused with that advice.
    with pytest.raises(session.GrassError, match="add that band on its own"):
        raster.group_display([("red", "PERMANENT")], "PERMANENT")


def test_a_band_that_names_no_mapset_takes_the_group_s():
    _, args, _, _ = raster.group_display([("a", ""), ("b", "elsewhere")], "PERMANENT")
    assert args == ["hue=a@PERMANENT", "intensity=b@elsewhere"]


GXW = """<?xml version="1.0" encoding="UTF-8"?>
<gxw>
    <session>
        <database>{base}</database>
        <location>IGN</location>
        <mapset>PERMANENT</mapset>
    </session>
    <display name="Map Display 1" extent="1.0,2.0,3.0,4.0,0.000000,255.000000">
        <layer type="raster" name="psri@PERMANENT" checked="0"/>
        <layer type="vector" name="study_areas@other" checked="1"/>
        <layer type="raster" name="no_mapset" checked="1"/>
        <layer type="3d-raster" name="cube@PERMANENT" checked="1"/>
    </display>
</gxw>
"""


def workspace_file(folder, text=GXW, name="default.gxw"):
    """Write one .gxw and return its path."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text.format(base=str(folder)))
    return str(path)


def test_a_workspace_names_its_project_layers_and_extent(tmp_path):
    path = workspace_file(tmp_path / "IGN")
    found = database.read_workspace(path)
    assert found["project"] == "IGN" and found["mapset"] == "PERMANENT"
    # The display's extent is four numbers of six: the last two are heights.
    assert found["extent"] == [1.0, 2.0, 3.0, 4.0]
    # A layer with no mapset in its name, and one of a kind RustGIS has no
    # layer for, are both left out rather than guessed at.
    assert [
        (layer["map"], layer["mapset"], layer["shown"]) for layer in found["layers"]
    ] == [
        ("psri", "PERMANENT", False),
        ("study_areas", "other", True),
    ]


def test_what_is_not_a_workspace_is_not_read(tmp_path):
    folder = tmp_path / "x"
    folder.mkdir()
    for name, text in (
        ("notxml.gxw", "this is not XML at all"),
        ("other.gxw", "<?xml version='1.0'?><project><a/></project>"),
        ("nosession.gxw", "<?xml version='1.0'?><gxw><display/></gxw>"),
    ):
        (folder / name).write_text(text)
        assert database.read_workspace(str(folder / name)) is None
    assert database.read_workspace(str(folder / "missing.gxw")) is None


def test_a_workspace_too_big_to_be_one_is_passed_over(tmp_path, monkeypatch):
    path = workspace_file(tmp_path / "IGN")
    monkeypatch.setattr(database, "WORKSPACE_MAX_BYTES", 10)
    assert database.read_workspace(path) is None


def test_a_display_extent_with_no_area_is_not_used(tmp_path):
    for extent in ("3,2,1,4,0,255", "1,2,1,4", "1,2", "", "a,b,c,d"):
        assert database._display_extent(extent) is None
    assert database._display_extent("1,2,3,4,0,255") == [1.0, 2.0, 3.0, 4.0]


def test_a_workspace_node_survives_the_separator_in_its_path():
    # The node id is built with the same separator a path uses, so the path
    # is percent-encoded; without it a path would read as project/mapset.
    path = "/home/someone/My Maps/grass/default.gxw"
    node = database.workspace_node(path)
    assert database.SEP not in node[len("workspace") + 1 :]
    assert database.parse_workspace_node(node) == path
    for wrong in ("raster/utm/PERMANENT/dem", "workspace", "", None):
        with pytest.raises(session.GrassError):
            database.parse_workspace_node(wrong)


def test_the_scan_skips_mapsets_hidden_folders_and_caches(tmp_path):
    # A mapset holds a database's maps -- tens of thousands of files -- and
    # never a workspace, so it must not be listed.
    home = tmp_path / "home"
    workspace_file(home / "work")
    mapset = home / "data" / "proj" / "PERMANENT"
    mapset.mkdir(parents=True)
    (mapset / "WIND").write_text("")
    workspace_file(mapset / "deep")
    workspace_file(home / ".cache" / "x")
    workspace_file(home / "node_modules" / "y")
    found = database.workspaces(base=None, home=str(home))
    assert [path for path, _ in found] == [str(home / "work" / "default.gxw")]


def test_the_database_is_listed_not_walked(tmp_path):
    # GRASS writes a project's workspace beside it, so one listing finds it.
    base = tmp_path / "grassdata"
    workspace_file(base / "IGN")
    mapset = base / "IGN" / "PERMANENT"
    mapset.mkdir(parents=True)
    (mapset / "WIND").write_text("")
    found = database.workspaces(base=str(base), home=str(tmp_path / "empty"))
    assert [path for path, _ in found] == [str(base / "IGN" / "default.gxw")]


def test_a_dataset_field_offers_the_mapset_s_datasets():
    entry = {
        "module": "t.rast.list",
        "mapset_inputs": [
            {"name": "input", "kind": "strds", "label": "Input", "required": True}
        ],
        "form": [],
    }
    # The datasets travel beside the maps, as (kind, name) pairs.
    maps = [
        ("raster", "dem"),
        ("strds", "s2_B04@PERMANENT"),
        ("strds", "s1_vv@PERMANENT"),
    ]
    field = raster.mapset_form(entry, maps, "PERMANENT")[0]
    assert field["id"] == "input" and field["kind"] == "select"
    assert field["choices"] == ["s2_B04@PERMANENT", "s1_vv@PERMANENT"]


def test_an_empty_dataset_field_says_dataset_not_map():
    entry = {
        "module": "t.rast.list",
        "mapset_inputs": [
            {"name": "input", "kind": "strds", "label": "Input", "required": True}
        ],
        "form": [],
    }
    field = raster.mapset_form(entry, [("raster", "dem")], "PERMANENT")[0]
    assert field["choices"] == [
        "(no space-time raster datasets in the PERMANENT mapset)"
    ]
    assert "space-time raster dataset" in field["help"]


def test_a_dataset_that_is_not_in_the_mapset_is_refused_as_a_dataset():
    entry = {
        "module": "t.rast.list",
        "mapset_inputs": [
            {"name": "input", "kind": "strds", "label": "Input", "required": True}
        ],
        "form": [],
    }
    with pytest.raises(session.GrassError, match="space-time raster dataset"):
        raster.mapset_plan(
            entry,
            {"form": {"input": "nope@PERMANENT"}},
            [("strds", "a@PERMANENT")],
            "PERMANENT",
        )


def test_a_mapset_s_3d_rasters_are_listed_beside_its_maps(tmp_path):
    mapset = tmp_path / "proj" / "PERMANENT"
    for folder, name in (("cellhd", "dem"), ("grid3", "cube"), ("vector", "roads")):
        (mapset / folder).mkdir(parents=True, exist_ok=True)
        if folder == "vector":
            (mapset / folder / name).mkdir()
        else:
            (mapset / folder / name).write_text("")
    found = database.maps(str(tmp_path), "proj", "PERMANENT")
    assert ("raster_3d", "cube") in found
    assert ("raster", "dem") in found and ("vector", "roads") in found


def mapset_at(folder, mapset="PERMANENT"):
    """Make <folder>/<mapset> a GRASS mapset, as its WIND file does."""
    (folder / mapset).mkdir(parents=True, exist_ok=True)
    (folder / mapset / "WIND").write_text("proj: 1\n")
    return folder


def test_a_workspace_is_read_from_the_database_it_records(tmp_path):
    # The recorded database is right while the project is still there, and is
    # preferred over every guess.
    base = tmp_path / "grassdata"
    mapset_at(base / "IGN")
    path = workspace_file(base / "IGN")
    found = database.read_workspace(path)
    assert database.workspace_place(path, found, None) == (str(base), "IGN")


def test_a_workspace_whose_recorded_project_is_gone_is_read_beside_itself(tmp_path):
    # The real case: a 2021 .gxw records /home/yann/grassdata and the project
    # Normandie. That database still exists, and its Normandie does not -- the
    # project went to a backup drive together with the workspace file.
    recorded = tmp_path / "grassdata"
    recorded.mkdir()
    backup = tmp_path / "backup" / "grassdata"
    mapset_at(backup / "IGN")
    path = backup / "IGN" / "default.gxw"
    path.write_text(GXW.format(base=str(recorded)))
    found = database.read_workspace(str(path))
    assert found["database"] == str(recorded)
    assert database.workspace_place(str(path), found, None) == (str(backup), "IGN")


def test_a_renamed_backup_folder_is_believed_over_the_recorded_name(tmp_path):
    # The folder a .gxw is kept in is the project, whatever the file records,
    # so a copy renamed on the way to the backup still opens.
    backup = tmp_path / "backup"
    mapset_at(backup / "IGN_2021")
    path = backup / "IGN_2021" / "default.gxw"
    path.write_text(GXW.format(base="/gone"))
    found = database.read_workspace(str(path))
    assert database.workspace_place(str(path), found, None) == (
        str(backup),
        "IGN_2021",
    )


def test_a_workspace_kept_away_from_its_project_falls_back_to_this_machine(tmp_path):
    here = tmp_path / "grassdata"
    mapset_at(here / "IGN")
    elsewhere = tmp_path / "Documents"
    path = workspace_file(elsewhere)  # records <elsewhere> as its database
    found = database.read_workspace(path)
    assert database.workspace_place(path, found, str(here)) == (str(here), "IGN")


def test_a_workspace_whose_project_is_nowhere_resolves_to_nothing(tmp_path):
    # Three of the user's 26 .gxw files are like this: kept in a folder of
    # scripts, with the project never copied along.
    scripts = tmp_path / "Backup" / "NorthKorea"
    path = workspace_file(scripts)
    found = database.read_workspace(path)
    assert database.workspace_place(path, found, str(tmp_path / "grassdata")) == (
        "",
        "",
    )


def test_a_folder_of_the_right_name_without_a_mapset_is_not_a_project(tmp_path):
    # The mapset's WIND is what makes it a project; a folder of the same name
    # is not enough, or a backup of scripts named after the project would be
    # loaded as one.
    base = tmp_path / "grassdata"
    (base / "IGN").mkdir(parents=True)
    path = workspace_file(base / "IGN")
    found = database.read_workspace(path)
    assert database.workspace_place(path, found, None) == ("", "")


def test_a_workspace_that_cannot_open_says_so_in_its_tree_label(tmp_path):
    path = workspace_file(tmp_path / "IGN")
    found = database.read_workspace(path)
    lost = database._workspace_label(path, found, ("", ""))
    fine = database._workspace_label(path, found, (str(tmp_path), "IGN"))
    assert lost.endswith("project not found")
    assert "project not found" not in fine
    # Said nothing about it when the caller does not know.
    assert "project not found" not in database._workspace_label(path, found, None)
