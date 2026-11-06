"""GRASS module forms, read from the module's own parser metadata.

``<module> --interface-description`` prints an XML description of every
parameter and flag a module takes.  This turns one of those documents into the
parameter list a RustGIS plugin manifest declares, so no table of module forms
is kept by hand and no GRASS help text is copied anywhere.

SPDX-License-Identifier: Unlicense
"""

import re
import xml.etree.ElementTree as ET

#: What RustGIS takes as a tool parameter's name: a lower-case letter, then
#: letters and underscores. GRASS has parameters it would refuse, such as
#: v.gsflow.segments's "width1", so those are left out and reported.
VALID_NAME = re.compile(r"^[a-z][a-zA-Z_]*$")

#: Flags every GRASS module carries, which RustGIS has its own answer for.
PLUMBING_FLAGS = frozenset({"overwrite", "verbose", "quiet", "help", "ui"})

#: Parameters naming where data comes from or goes, which the bridge supplies.
PLUMBING_PARAMS = frozenset({"input", "output", "layer"})

#: ``gisprompt`` elements that name a space-time dataset: what GRASS's
#: temporal modules read instead of one raster.
TEMPORAL_ELEMENTS = frozenset({"stds", "strds", "stvds", "str3ds", "stdsp"})

#: Families whose modules can run with the form alone, writing into the GRASS
#: project/mapset chosen in the panel: they work on state and datasets rather
#: than on one raster in and one raster out.
MAPSET_FAMILIES = frozenset({"Temporal", "Database", "General", "Miscellaneous"})

#: A plugin manifest allows this many parameters per tool.
MAX_PARAMS = 32

#: A panel form allows this many fields, matching RustGIS's own limit.
MAX_FORM_FIELDS = 64


#: A file parameter the module writes rather than reads, whatever its
#: ``age`` says. Such a file would have to exist before the user could pick
#: it, and the module would then write over it outside RustGIS, so it is left
#: out and reported like any other parameter the bridge cannot offer.
WRITES_FILE = re.compile(r"\boutput\b|\bto write\b|\bwritten\b", re.IGNORECASE)


def _about(param):
    """Return a parameter's label and description as one string."""
    return f"{_text(param.find('label'))} {_text(param.find('description'))}"


def _text(node):
    """Return a node's text as one tidy line, or an empty string."""
    if node is None or not node.text:
        return ""
    return " ".join(node.text.split())


def _kind_of(param):
    """Return the RustGIS parameter kind for one GRASS ``<parameter>``.

    ``None`` means the bridge cannot offer it: an output name, or an input of
    a kind a plugin tool cannot receive (a raster, a 3D raster, a database
    table).
    """
    prompt = param.find("gisprompt")
    if prompt is not None:
        age = prompt.get("age")
        element = prompt.get("prompt") or prompt.get("element") or ""
        if age == "new":
            return None  # An output; the bridge names it.
        if element == "vector":
            return "vectorLayer"
        if element == "file":
            # RustGIS hands a tool the file the user picks (manifest kind
            # "file", which the "files" permission covers), so the rules and
            # control-point files of v.net, v.segment, v.extract, v.rectify
            # and v.lrs.segment are reachable instead of being left out.
            # Some modules declare a file they *write* as age="old" all the
            # same (v.rectify's rmsfile), and a file picker cannot name a file
            # that does not exist yet, so the module's own words decide.
            return None if WRITES_FILE.search(_about(param)) else "file"
        if element in ("raster", "cell", "raster_3d", "grid3", "dbtable"):
            return None
        if element in ("dbcolumn", "dbcolumn_name"):
            return "field"
    if param.findall("values/value"):
        return "choice"
    if param.get("type") in ("float", "integer", "double"):
        return "number"
    return "text"


def _choices(param):
    """Return a ``choice`` parameter's values, in the module's own order."""
    out = []
    for value in param.findall("values/value"):
        name = _text(value.find("name"))
        if name and name not in out:
            out.append(name)
    return out[:64]


#: What a module's prefix says it works on, for the module tree.
FAMILIES = {
    "d": "Display",
    "db": "Database",
    "g": "General",
    "i": "Imagery",
    "m": "Miscellaneous",
    "p": "Planetary",
    "ps": "PostScript",
    "r": "Raster",
    "r3": "3D Raster",
    "t": "Temporal",
    "test": "Tests",
    "v": "Vector",
}


def family_of(module):
    """Return the name of the family a module's prefix puts it in."""
    prefix = module.split(".", 1)[0]
    return FAMILIES.get(prefix, "Other")


def ports(task):
    """Return what a module reads and writes, by element and age.

    :param task: the parsed ``<task>`` element
    :return: ``{"raster_in", "raster_out", "vector_in", "vector_out"}``, each
        a list of parameter names
    """
    out = {"raster_in": [], "raster_out": [], "vector_in": [], "vector_out": []}
    for param in task.findall("parameter"):
        prompt = param.find("gisprompt")
        if prompt is None:
            continue
        element = prompt.get("prompt") or prompt.get("element") or ""
        if element in ("raster", "cell"):
            kind = "raster"
        elif element == "vector":
            kind = "vector"
        else:
            continue
        side = "out" if prompt.get("age") == "new" else "in"
        out[f"{kind}_{side}"].append(param.get("name") or "")
    return out


def _prompt(gisprompt):
    """Return a ``<gisprompt>``'s element, whichever attribute names it."""
    if gisprompt is None:
        return ""
    return gisprompt.get("prompt") or gisprompt.get("element") or ""


def _needs_text(names):
    """Return a short, human reason for required parameters with no default."""
    if len(names) == 1:
        name = names[0]
        if name in ("group", "input_group", "input_group_to_decompose"):
            return "needs an imagery group"
        if name in ("config", "parameters", "rules"):
            return "needs a config file"
        if name in ("coordinates", "coordinate"):
            return "needs coordinates"
        return f"needs {name}"
    shown = ", ".join(names[:3])
    return f"needs {shown}" + ("..." if len(names) > 3 else "")




def _offerable(task):
    """Return the parameter and flag names a form can offer for a module."""
    names, seen = set(), set()
    for param in task.findall("parameter"):
        name = param.get("name") or ""
        if not name or name in PLUMBING_PARAMS or name in seen:
            continue
        seen.add(name)
        if _kind_of(param) is not None and VALID_NAME.match(name):
            names.add(name)
    for flag in task.findall("flag"):
        name = flag.get("name") or ""
        if name and name not in PLUMBING_FLAGS and VALID_NAME.match(f"flag_{name}"):
            names.add(f"flag_{name}")
    return names


def _cannot_name(param):
    """Return what a form cannot name for a parameter, or None when it can."""
    prompt = param.find("gisprompt")
    if prompt is None:
        return None
    if prompt.get("age") == "new":
        return "an output name, which the form cannot name"
    element = _prompt(prompt)
    if element in TEMPORAL_ELEMENTS:
        return "a space-time dataset, which the form cannot name"
    if element in ("raster", "cell", "raster_3d", "grid3"):
        return "a raster, which the form cannot name"
    if element == "vector":
        return "a vector map, which the form cannot name"
    if element == "dbtable":
        return "a database table, which the form cannot name"
    return None


def _mapset_runnability(task):
    """Return whether the form alone can run a module in a chosen mapset.

    Temporal, database and general modules do not read one raster and write
    another: they create or change datasets in a GRASS project. The panel's
    form names their parameters, and the project/mapset chosen under Projects
    and mapsets says where the work goes. A required parameter the form cannot
    name (a raster, a space-time dataset, an output) still stops the module.

    :return: ``{"mapset_runnable": bool, "mapset_reason": str}``
    """
    out = {"mapset_runnable": False, "mapset_reason": ""}
    name = task.get("name") or ""
    if family_of(name) not in MAPSET_FAMILIES:
        out["mapset_reason"] = "works on a raster or vector layer"
        return out
    offered = _offerable(task)
    missing = []
    for param in task.findall("parameter"):
        if param.get("required") != "yes":
            continue
        pname = param.get("name") or ""
        if pname in offered or _text(param.find("default")):
            continue
        missing.append(_cannot_name(param) or (f"'{pname}'" if pname else "a parameter"))
    for flag in task.findall("flag"):
        if flag.get("required") != "yes":
            continue
        fname = flag.get("name") or ""
        if f"flag_{fname}" not in offered:
            missing.append(f"flag -{fname}")
    if missing:
        out["mapset_reason"] = "needs " + ", ".join(missing[:3])
        if len(missing) > 3:
            out["mapset_reason"] += "..."
        return out
    out["mapset_runnable"] = True
    return out


def _runnability(task):
    """Return whether the bridge can drive a module from one raster.

    Run Module names one input and one output and leaves everything else at
    GRASS's own default. So a module is runnable this way only when it has one
    required raster input (not a group of bands), at least one output, no
    second required raster, and every other required parameter has a default.

    The answer is deliberately conservative: a module that reads several
    rasters or needs an imagery group is marked with the reason instead of
    being offered and failing after the user waits for it.
    """
    params = task.findall("parameter")
    raster_ins, raster_outs, required = [], [], []
    temporal = False
    for param in params:
        gisprompt = param.find("gisprompt")
        element = _prompt(gisprompt)
        if element in TEMPORAL_ELEMENTS:
            temporal = True
        if element in ("raster", "cell"):
            is_output = gisprompt.get("age") == "new"
            (raster_outs if is_output else raster_ins).append(param)
        if param.get("required") == "yes":
            required.append(param)
    required_flags = [
        flag.get("name") or "?"
        for flag in task.findall("flag")
        if flag.get("required") == "yes"
    ]

    out = {
        "runnable": False,
        "reason": "",
        "needs": [],
        "raster_input": None,
        "raster_output": None,
        "bands": False,
        "temporal": temporal,
    }
    out.update(_mapset_runnability(task))
    if not raster_ins:
        out["reason"] = "takes no raster"
        return out
    if not raster_outs:
        out["reason"] = "writes no raster"
        return out

    required_ins = [p for p in raster_ins if p.get("required") == "yes"]
    if not required_ins:
        out["reason"] = "needs an input chosen for it"
        return out
    if len(required_ins) > 1:
        out["reason"] = f"needs {len(required_ins)} raster inputs"
        return out
    chosen_in = required_ins[0]
    out["raster_input"] = chosen_in.get("name")

    required_outs = [p for p in raster_outs if p.get("required") == "yes"]
    chosen_out = required_outs[0] if required_outs else raster_outs[0]
    out["raster_output"] = chosen_out.get("name")
    if len(required_outs) > 1:
        out["reason"] = f"writes {len(required_outs)} rasters"
        return out
    if "basename" in _about(chosen_out).lower():
        out["reason"] = "writes several rasters"
        return out

    if chosen_in.get("multiple") == "yes":
        out["bands"] = True
        out["reason"] = "needs several bands"
        return out
    # i.landsat.toar and i.landsat.acca take a *base name* and read B.1, B.2,
    # ... beside it; naming one raster there would fail once GRASS looked for
    # the band that follows.
    if "base name" in _about(chosen_in).lower():
        out["bands"] = True
        out["reason"] = "needs several bands"
        return out

    if required_flags:
        out["reason"] = f"needs flag -{required_flags[0]}"
        return out

    needs = []
    for param in required:
        if param is chosen_in or param is chosen_out:
            continue
        name = param.get("name") or ""
        if _text(param.find("default")):
            continue
        needs.append(name)
    if needs:
        out["needs"] = needs
        out["reason"] = _needs_text(needs)
        return out

    # d.* modules open or drive a display, and Run Module has no display to
    # give them: d.rast.edit would wait for an editor that never appears.
    if family_of(task.get("name") or "") == "Display":
        out["reason"] = "needs a display"
        return out

    out["runnable"] = True
    return out


def describe(xml_text):
    """Describe one module for the catalogue the panel's tree is built from.

    This is what tells a raster module from a vector one without running it
    again, and carries the one line GRASS gives for each. It also works out
    whether Run Module can drive the module, so the panel can offer the ones
    that will actually run and say why the others will not.

    :param xml_text: the module's ``--interface-description`` output
    :return: ``{"module", "summary", "keywords", "family", ports...,
        "runnable", "reason", ...}``
    :raises ValueError: when the document is not a task description
    """
    try:
        task = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"not a module description: {e}") from e
    name = task.get("name") or ""
    if task.tag != "task" or not name:
        raise ValueError("not a module description: no <task name=...>")
    out = {
        "module": name,
        "summary": (_text(task.find("label")) or _text(task.find("description")))[:300],
        "keywords": _text(task.find("keywords")),
        "family": family_of(name),
    }
    out.update(ports(task))
    out.update(_runnability(task))
    return out


def _specs(xml_text):
    """Read one module's parameters, before a caller trims them to its own budget.

    Each parameter carries the details a tool's manifest ignores but a form
    uses: whether it is ``multiple``, whether a number is an ``integer``, and
    the description as ``help`` when the parameter has a separate label.

    :return: ``(task, module, summary, params, skipped)``
    :raises ValueError: when the document is not a GRASS task description
    """
    try:
        task = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"not a module description: {e}") from e
    if task.tag != "task" or not task.get("name"):
        raise ValueError("not a module description: no <task name=...>")

    module = task.get("name")
    label = _text(task.find("label")) or _text(task.find("description"))
    params, skipped = [], []

    seen = set()
    for param in task.findall("parameter"):
        name = param.get("name") or ""
        if not name or name in PLUMBING_PARAMS:
            continue
        if name in seen:
            # Some modules declare a parameter twice (v.gsflow.segments does);
            # RustGIS refuses a repeated name, so the second is left out.
            skipped.append(f"{name} (declared twice)")
            continue
        seen.add(name)
        kind = _kind_of(param)
        if kind is None or not VALID_NAME.match(name):
            skipped.append(name)
            continue
        spec = {
            "name": name,
            "label": _text(param.find("label"))
            or _text(param.find("description"))
            or name,
            "help": "",
            "kind": kind,
            "required": param.get("required") == "yes",
            "multiple": param.get("multiple") == "yes",
            "integer": param.get("type") == "integer",
            # A parameter with several key values takes a list or a range,
            # which one number field cannot hold (i.pca's rescale=0,255).
            "keys": len(param.findall("keydesc/item")),
        }
        description = _text(param.find("description"))
        written = _text(param.find("label"))
        if written and description and written != description:
            spec["help"] = description
        if kind == "choice":
            spec["choices"] = _choices(param)
            if not spec["choices"]:
                spec["kind"] = "text"
                del spec["choices"]
        default = _text(param.find("default"))
        if default:
            spec["default"] = (
                float(default)
                if spec["kind"] == "number" and _is_number(default)
                else default
            )
        if spec["multiple"] and spec["kind"] == "vectorLayer":
            # Several layers would arrive as one name; keep the first only.
            spec["label"] += " (one layer)"
        params.append(spec)

    taken = {spec["name"] for spec in params}
    for flag in task.findall("flag"):
        name = flag.get("name") or ""
        if not name or name in PLUMBING_FLAGS or f"flag_{name}" in taken:
            continue
        if not VALID_NAME.match(f"flag_{name}"):
            skipped.append(f"-{name}")
            continue
        written = _text(flag.find("label"))
        description = _text(flag.find("description"))
        params.append(
            {
                "name": f"flag_{name}",
                "label": written or description or f"-{name}",
                "help": description if written and description and written != description else "",
                "kind": "bool",
                "required": False,
                "multiple": False,
                "integer": False,
                "keys": 0,
                "default": False,
            }
        )

    return task, module, label, params, skipped


def parse(xml_text):
    """Describe one module from its ``--interface-description`` output.

    :param xml_text: the XML the module printed
    :return: ``{"module", "summary", "keywords", "params", "skipped"}``, where
        ``params`` is ready for a plugin manifest and ``skipped`` names the
        parameters the bridge had to leave out, so a caller can say so
    :raises ValueError: when the document is not a GRASS task description
    """
    task, module, label, params, skipped = _specs(xml_text)
    params = [
        {k: p[k] for k in ("name", "label", "kind", "required", "default", "choices") if k in p}
        for p in params
    ]
    if len(params) > MAX_PARAMS:
        # Required parameters first, so truncation never drops one.
        params.sort(key=lambda p: not p.get("required"))
        skipped += [p["name"] for p in params[MAX_PARAMS:]]
        params = params[:MAX_PARAMS]
    return {
        "module": module,
        "summary": label,
        "keywords": _text(task.find("keywords")),
        "params": params,
        "skipped": skipped,
    }


def form_fields(xml_text):
    """Return a module's parameters as a panel form's fields.

    The input, output and layer parameters a module's caller names are left
    out, as are rasters and database tables the plugin cannot pass; what
    remains is what a user can choose. A ``multiple`` choice becomes a
    ``multi`` field (several of its choices), any other choice a ``select``, a
    flag a ``checkbox``, a number a ``number`` (whole numbers marked
    ``integer``) and everything else ``text``.

    :raises ValueError: when the document is not a GRASS task description
    """
    _, _, _, params, _ = _specs(xml_text)
    out = []
    for spec in params[:MAX_FORM_FIELDS]:
        kind = {
            "bool": "checkbox",
            "choice": "multi" if spec["multiple"] else "select",
            "number": "number",
            "text": "text",
            "file": "text",
            "field": "text",
            "vectorLayer": "text",
        }.get(spec["kind"])
        if kind is None:
            continue
        if kind == "number" and (
            spec.get("keys", 0) > 1 or isinstance(spec.get("default"), str)
        ):
            # A range or a list of numbers stays as it is written.
            kind = "text"
        field = {
            "id": spec["name"],
            "kind": kind,
            "label": _clip(spec["label"], 200),
        }
        if spec.get("help"):
            field["help"] = _clip(spec["help"], 2000)
        if spec.get("required"):
            field["required"] = True
        if spec.get("integer") and kind == "number":
            field["integer"] = True
        if kind in ("select", "multi"):
            field["choices"] = spec["choices"][:256]
        default = spec.get("default")
        if default is not None and kind != "checkbox":
            if kind == "multi":
                parts = default.split(",") if isinstance(default, str) else default
                picked = [str(p).strip() for p in parts if str(p).strip() in spec["choices"]]
                if picked:
                    field["default"] = picked
            elif kind in ("number", "text") or (
                kind == "select" and default in spec["choices"]
            ):
                field["default"] = default
        out.append(field)
    return out


def _clip(text, limit):
    """Keep a field's label or help within what RustGIS allows."""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _is_number(text):
    try:
        float(text)
    except ValueError:
        return False
    return True
