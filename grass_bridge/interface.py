"""GRASS module forms, read from the module's own parser metadata.

``<module> --interface-description`` prints an XML description of every
parameter and flag a module takes.  This turns one of those documents into the
parameter list a RustGIS plugin manifest declares, so no table of module forms
is kept by hand and no GRASS help text is copied anywhere.

SPDX-License-Identifier: Unlicense
"""

import xml.etree.ElementTree as ET

#: Flags every GRASS module carries, which RustGIS has its own answer for.
PLUMBING_FLAGS = frozenset({"overwrite", "verbose", "quiet", "help", "ui"})

#: Parameters naming where data comes from or goes, which the bridge supplies.
PLUMBING_PARAMS = frozenset({"input", "output", "layer"})

#: A plugin manifest allows this many parameters per tool.
MAX_PARAMS = 32


def _text(node):
    """Return a node's text as one tidy line, or an empty string."""
    if node is None or not node.text:
        return ""
    return " ".join(node.text.split())


def _kind_of(param):
    """Return the RustGIS parameter kind for one GRASS ``<parameter>``.

    ``None`` means the bridge cannot offer it: an output name, or an input of
    a kind a plugin tool cannot receive (a raster, a 3D raster, a file).
    """
    prompt = param.find("gisprompt")
    if prompt is not None:
        age = prompt.get("age")
        element = prompt.get("prompt") or prompt.get("element") or ""
        if age == "new":
            return None  # An output; the bridge names it.
        if element == "vector":
            return "vectorLayer"
        if element in ("raster", "cell", "raster_3d", "grid3", "file", "dbtable"):
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

    for param in task.findall("parameter"):
        name = param.get("name") or ""
        if not name or name in PLUMBING_PARAMS:
            continue
        kind = _kind_of(param)
        if kind is None:
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

    for flag in task.findall("flag"):
        name = flag.get("name") or ""
        if not name or name in PLUMBING_FLAGS:
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
