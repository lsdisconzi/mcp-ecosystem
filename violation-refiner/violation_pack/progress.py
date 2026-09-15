"""Process-wide progress slot for long-running tool calls.

Why this module exists
----------------------
``ToolManager`` calls a *synchronous* tool directly on the event loop
(``mcp/server/fastmcp/utilities/func_metadata.py`` ends in
``return fn(**arguments_parsed_dict)``), so ``enrich_violation_tool`` used to
freeze the whole UI server for its entire run. Measured against the live
server: a ``/api/health`` poll sent 0.02 s into an 8.96 s run was answered at
8.98 s, and nothing else was served in between. A full eight-stage run is
minutes, so "the pipeline is running" could not be shown at all — the page
could not even ask.

The fix is to run the call on a worker thread (``ui_server._call_tool_blocking``),
which frees the loop to answer polls. This module is what lets the freed loop
say something useful: the worker writes its stage into a module-level slot and
the polling request reads it.

One slot is enough. This is a local, single-operator tool, and the UI server
refuses to start a second tool call while one is running, so there is never
more than one writer.
"""

from __future__ import annotations

import threading
import time
from typing import Any

_lock = threading.Lock()
_slot: dict[str, Any] = {}


def begin(tool: str, total: int = 0) -> None:
    """Claim the slot for a fresh run, discarding whatever was there before."""
    with _lock:
        _slot.clear()
        _slot.update({
            "tool": tool,
            "stage": None,
            "index": 0,
            "total": int(total or 0),
            "started": time.time(),
            "finished": None,
            "running": True,
            "error": None,
        })


def stage(name: str, index: int = 0, total: int = 0) -> None:
    """Report that `name` is now running, as step `index` of `total`.

    A no-op when no run is in progress, so a tool that reports progress
    outside ``begin``/``end`` cannot invent a phantom run.
    """
    with _lock:
        if not _slot:
            return
        _slot["stage"] = str(name)
        if index:
            _slot["index"] = int(index)
        if total:
            _slot["total"] = int(total)


def end(tool: str, error: str | None = None) -> None:
    """Close the run. Ignores a mismatched `tool` so a late finishing call
    cannot close a run that a newer one has already claimed."""
    with _lock:
        if not _slot or _slot.get("tool") != tool:
            return
        _slot["running"] = False
        _slot["error"] = error
        _slot["finished"] = time.time()


def snapshot() -> dict[str, Any]:
    """The current run as plain JSON, or ``{}`` when nothing has ever run."""
    with _lock:
        if not _slot:
            return {}
        out = dict(_slot)
    started = out.get("started")
    if started:
        out["elapsed_seconds"] = round((out.get("finished") or time.time()) - started, 1)
    return out
