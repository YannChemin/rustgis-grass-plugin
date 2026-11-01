"""Tests for the raster commands' own decisions.

Nothing here runs GRASS: these cover what the bridge works out before and
after a module runs, which is where a wrong answer would be silent.

SPDX-License-Identifier: Unlicense
"""

import time

import pytest

from grass_bridge import raster, session


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
