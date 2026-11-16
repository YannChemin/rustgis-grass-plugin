"""The panel's four steps, shared by the manifest and the protocol loop.

RustGIS draws a panel as one flat column of widgets, with no section, tab or
accordion (``crates/ui-egui/src/pluginpanel.rs``), and it draws only the
widgets whose runtime state says ``visible``. Everything GRASS needs -- a
project, a layer, a region, a module and its form -- came to 24 widgets in one
column, which is several screens of scrolling with four trees in it.

So the panel is a four-step workflow instead, in the order the work is done: a
GRASS project and its maps, then the map layer and the computational region,
then the shaped terrain runs, then the module catalogue and its form. A
``choice`` at the top chooses the step and every answer sets ``visible`` from
it, so at most eight widgets are drawn at once. The steps are declared here
because the manifest generator and the protocol loop have to agree on them.

Visibility is runtime state, not a manifest field: before the panel's state
command has answered, RustGIS shows every widget. That is one frame on
opening, and it is also why a command that answers anything at all answers the
visibility of the step it leaves the panel in.

SPDX-License-Identifier: Unlicense
"""

#: The steps, in the order they are worked through, with the label of the
#: dropdown option that chooses each. The numbers are part of the label
#: because a dropdown shows one option at a time: without them the panel does
#: not say how far along it is.
STEPS = (
    ("data", "1. Project & data"),
    ("layer", "2. Layer & region"),
    ("terrain", "3. Terrain"),
    ("modules", "4. Modules"),
)

#: The step the panel opens in.
FIRST = STEPS[0][0]

#: The picks, which ask for a place on the map, and what each is for. A pick is
#: drawn only in its own step, and RustGIS marks the place it holds on the map
#: while the panel is open, so a pick left visible in another step would mark a
#: place that step has nothing to do with.
PICKS = {
    "region-box": "box",
    "viewpoint": "point",
}

#: Widgets drawn in every step: the step chooser itself and the line that says
#: what the last run did, which has to be readable from wherever the user is.
ALWAYS = ("step", "status")

#: The widgets each step draws. A widget may belong to several steps: the
#: chosen layer and the region are shown in every step that acts on them,
#: because a run is about to use them.
STEP_ITEMS = {
    "data": ("gisdbase", "database", "data-add", "data-folder"),
    "layer": (
        "raster",
        "source",
        "band",
        "region",
        "region-view",
        "region-full",
        "region-box",
        "res",
    ),
    "terrain": (
        "source",
        "region",
        "percent",
        "height",
        "maxdist",
        "curvature",
        "viewpoint",
        "raster-slope",
        "raster-aspect",
        "raster-viewshed",
    ),
    "modules": (
        "source",
        "region",
        "family",
        "modules",
        "details",
        "form",
        "run-module",
    ),
}

#: Which module family each option of the catalogue dropdown keeps, as
#: :func:`grass_bridge.raster.mode_family` reads it.
FAMILIES = (
    ("all", "All modules", None),
    ("imagery", "Imagery only", "Imagery"),
    ("temporal", "Temporal only", "Temporal"),
)


def every_item():
    """Return every widget id the panel has, in no particular order."""
    ids = set(ALWAYS)
    for names in STEP_ITEMS.values():
        ids.update(names)
    return ids


def step_of(value, default=FIRST):
    """Return the step a panel value names, or ``default`` when it names none.

    :param value: the ``step`` widget's value, which RustGIS keeps between
        calls and a script may set to anything
    """
    text = str(value or "")
    return text if any(text == step for step, _ in STEPS) else default


def visibility(step):
    """Return the ``items`` entries that draw one step and hide the rest.

    :param step: the step to show, as :func:`step_of` returns it
    :return: ``{widget id: {"visible": bool}}`` for every widget of the panel
    """
    shown = set(ALWAYS) | set(STEP_ITEMS.get(step, ()))
    return {name: {"visible": name in shown} for name in sorted(every_item())}


def sends_nodes(step, widget):
    """Say whether an answer for ``step`` should carry ``widget``'s nodes.

    A tree's nodes are the costly part of an answer -- the module tree is
    1,424 nodes and 270 KB of JSON, and a mapset's can be thousands of maps --
    and RustGIS keeps what an answer leaves out. So a step sends only the trees
    it draws. The raster tree is the exception: it is one node per raster layer
    of the map, and the chosen layer's value is only kept while its node is
    among them, so it is always sent.

    :param step: the step the answer leaves the panel in
    :param widget: ``"database"``, ``"modules"`` or ``"raster"``
    """
    if widget == "raster":
        return True
    return widget in STEP_ITEMS.get(step, ())
