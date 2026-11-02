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

#: A plugin manifest allows this many parameters per tool.
MAX_PARAMS = 32


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


def describe(xml_text):
    """Describe one module for the catalogue the panel's tree is built from.

    This is what tells a raster module from a vector one without running it
    again, and carries the one line GRASS gives for each.

    :param xml_text: the module's ``--interface-description`` output
    :return: ``{"module", "summary", "keywords", "family", ports...}``
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
    return out


def parse(xml_text):
    """Describe one module from its ``--interface-description`` output.

    :param xml_text: the XML the module printed
    :return: ``{"module", "summary", "keywords", "params", "skipped"}``, where
        ``params`` is ready for a plugin manifest and ``skipped`` names the
        parameters the bridge had to leave out, so a caller can say so
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
            "kind": kind,
            "required": param.get("required") == "yes",
        }
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
        if param.get("multiple") == "yes" and spec["kind"] == "vectorLayer":
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
        params.append(
            {
                "name": f"flag_{name}",
                "label": _text(flag.find("label"))
                or _text(flag.find("description"))
                or f"-{name}",
                "kind": "bool",
                "default": False,
            }
        )

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


def _is_number(text):
    try:
        float(text)
    except ValueError:
        return False
    return True
