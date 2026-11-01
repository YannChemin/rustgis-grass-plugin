"""A RustGIS process plugin that runs GRASS GIS vector modules.

RustGIS starts this program once per call and speaks one JSON object per line
over standard input and output (see RustGIS docs/plugins.md). GRASS itself is
never linked: each tool run spawns the user's own installation.

Progress goes to RustGIS as {"progress": ...} lines, and GRASS modules report
their own percentages to MetaMonitor through its GRASS hook
(https://github.com/YannChemin/MetaMonitor).

SPDX-License-Identifier: Unlicense
"""

import json
import pathlib
import sys

from grass_bridge import session

HERE = pathlib.Path(__file__).parent


def emit(obj):
    """Write one protocol line."""
    print(json.dumps(obj), flush=True)


def progress(text):
    """Tell RustGIS what the run is doing now."""
    emit({"progress": text})


def load_modules():
    """Return the tool id to GRASS module map the generator wrote."""
    try:
        return json.loads((HERE / "modules.json").read_text())["modules"]
    except (OSError, ValueError, KeyError):
        return {}


def split_params(declared, given):
    """Split a tool's parameters into GRASS parameters and flags.

    :param declared: the tool's parameter list from the manifest
    :param given: what the user supplied
    :return: ``(params, flags)``
    """
    params, flags = {}, []
    for spec in declared:
        name = spec["name"]
        if name == "input":
            continue
        value = given.get(name, None)
        if value is None or value == "":
            continue
        if name.startswith("flag_"):
            if value is True:
                flags.append(name[len("flag_") :])
            continue
        if isinstance(value, bool):
            continue
        params[name] = value
    return params, flags


def run_tool(req, modules):
    """Run one GRASS module for a tool request and return its ``ok`` value."""
    tool = req["id"]
    module = modules.get(tool)
    if not module:
        raise ValueError(f"no GRASS module is mapped to '{tool}'")
    manifest = json.loads((HERE / "plugin.json").read_text())
    declared = next((t["params"] for t in manifest["tools"] if t["id"] == tool), [])

    given = req.get("params") or {}
    layer = given.get("input")
    if not layer:
        raise ValueError("no input layer was given")
    geojson = (req.get("layers") or {}).get(layer)
    if geojson is None:
        raise ValueError(f"the input layer '{layer}' did not arrive with the request")

    params, flags = split_params(declared, given)
    with session.Run(progress=progress) as run:
        result, messages = run.vector_tool(module, geojson, params, flags)

    count = len(result.get("features") or [])
    messages.append(f"{module}: {count} features written.")
    return {
        "layers": [{"name": f"{layer} {module}", "geojson": result}],
        "messages": messages[:200],
    }


def main():
    """Read one request, answer it, and exit."""
    line = sys.stdin.readline()
    if not line.strip():
        emit({"error": "no request"})
        return
    try:
        req = json.loads(line)
    except ValueError as e:
        emit({"error": f"unreadable request: {e}"})
        return
    try:
        if req.get("kind") == "tool":
            emit({"ok": run_tool(req, load_modules())})
        else:
            emit({"error": f"unknown request '{req.get('id')}'"})
    except session.GrassError as e:
        emit({"error": str(e)})
    except (OSError, ValueError, KeyError) as e:
        emit({"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    main()
