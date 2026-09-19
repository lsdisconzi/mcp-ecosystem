#!/usr/bin/env python
"""Watch every bundle under ``build/`` and keep the open-question catalog current.

Why a watcher at all
--------------------
``violation_pack/open_questions.py`` can build the catalog, but the catalog is
only useful if it is *current*: the ViolationRefiner UI reads it to show what is
still unknown, and ``seeking`` reads it to search the corpora for answers. If it
is refreshed by hand, both surfaces quietly describe a corpus that has moved on.
So this polls ``build/`` and rewrites the catalog when — and only when — the
bundles actually change.

How it decides
--------------
Two levels of change detection, so a 15-second poll costs almost nothing:

1. Per bundle, a cheap ``mtime_ns:size`` signature per artifact. Unchanged
   signatures carry their previous ``sha256`` forward, so the ~16 MB of bundle
   JSON is never re-hashed unless a file was touched.
2. Per run, a digest of the whole catalog with ``generated_at`` excluded. If it
   matches the digest already stored in ``index.json``, **nothing is written at
   all** — otherwise every poll would rewrite the index and the store would churn
   endlessly in ``git status`` for no change.

When something *has* changed, only the affected bundles' detail files are
rewritten; the untouched 80 are left alone.

Two ways to run it
------------------
``--once``
    Scan, write if needed, exit. This is the mode ``start-all.sh`` and cron use,
    and the exit code is the answer: 0 = catalog current.
``--interval N`` (default)
    Poll every N seconds until interrupted. ``--interval 0`` scans exactly once,
    which makes "run it in the foreground and see" a single flag.

A transient failure is logged and retried, never fatal: a bundle being rewritten
by a batch job is a normal event, and a daemon that dies on one unreadable file
would be worse than useless. Ctrl-C or SIGTERM shuts it down cleanly.

Note the deliberate asymmetry with the refiner: the refiner *prefers*
``<VID>.json.bak`` when it exists, this cataloguer never reads it. Publishing the
backup would mean the catalog describes a previous generation of questions while
claiming to be current. The presence of a ``.bak`` is reported as a warning in
the catalog instead.
"""
from __future__ import annotations

import argparse
import signal
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from violation_pack import open_questions as oq  # noqa: E402

#: How long to sleep between polls when the caller does not say.
DEFAULT_INTERVAL = 15.0

#: Set by the signal handler; the loop checks it instead of dying mid-write.
_STOPPING = False


def _log(message: str, *, quiet: bool = False) -> None:
    if quiet:
        return
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def _bundle_fingerprints(catalog: dict) -> dict[str, dict]:
    return {
        violation_id: (summary or {}).get("fingerprint") or {}
        for violation_id, summary in (catalog.get("violations") or {}).items()
    }


def _changed_bundles(previous: dict | None, current: dict) -> set[str]:
    """Bundles that are new, gone, or whose tracked artifacts no longer match.

    "Gone" is included because ``write_catalog`` only prunes files for bundles it
    is told about — the index has to be rewritten for a deletion to be noticed at
    all, and returning an empty set on a pure deletion would suppress that.
    """
    before = _bundle_fingerprints(previous or {})
    after = _bundle_fingerprints(current)
    changed = {vid for vid, fingerprint in after.items() if before.get(vid) != fingerprint}
    changed |= set(before) - set(after)
    return changed


def scan_once(build_root: Path, store: Path, *, quiet: bool, verbose: bool) -> int:
    """One poll. Returns a process exit code."""
    previous = oq.load_index(store)
    current = oq.scan_build(build_root, previous=previous)

    missing = oq.missing_detail_files(store, current)
    unchanged = (previous is not None
                 and previous.get("digest")
                 and current["digest"] == previous.get("digest"))
    if unchanged and not missing:
        if verbose:
            totals = current["totals"]
            _log(f"no change — {totals['questions']} question(s) in "
                 f"{totals['bundles']} bundle(s)", quiet=quiet)
        return 0
    if unchanged and missing:
        # Content is current but the store is not: repair it rather than reporting
        # "no change", which would leave the index pointing at absent files forever
        # — the corpus being stable is exactly when this would never self-heal.
        _log(f"store incomplete — rewriting {len(missing)} missing detail file(s): "
             + ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else ""), quiet=quiet)

    changed = _changed_bundles(previous, current) | set(missing)
    # Always write detail files for bundles that changed; `write_catalog` also writes
    # any detail file that is missing from disk, so passing the changed set is enough.
    stats = oq.write_catalog(current, store, detail_ids=changed)
    totals = current["totals"]
    first_run = previous is None
    verb = "wrote" if first_run else "updated"
    detail = (f"{stats['details_written']} detail file(s) written "
              f"({len(changed)} bundle(s) changed, {stats['details_skipped']} untouched")
    if stats["details_removed"]:
        detail += f", {stats['details_removed']} removed"
    detail += ")"
    _log(f"{verb} {_display(store)} — {totals['questions']} question(s) in "
         f"{totals['bundles']} bundle(s); {detail}", quiet=quiet)

    new_bundles = sorted(set(_bundle_fingerprints(current)) - set(_bundle_fingerprints(previous or {})))
    if new_bundles and not first_run:
        _log(f"  new bundle(s): {', '.join(new_bundles)}", quiet=quiet)
    if totals["declared_undocumented"]:
        _log(f"  {totals['declared_undocumented']} question(s) are declared but never enumerated "
             "— they have no id, so no evidence can be attached to them", quiet=quiet)
    orphans = oq.orphaned_evidence(store)
    if orphans:
        total = sum(entry["records"] for entry in orphans)
        _log(f"  {total} evidence record(s) belong to questions no longer in the catalog: "
             + ", ".join(f"{o['violation_id']}/{o['evidence_key']}" for o in orphans[:3])
             + (" ..." if len(orphans) > 3 else ""), quiet=quiet)
    return 0


def _display(path: Path) -> str:
    """A path relative to the repo when it is inside it, so log lines stay short."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def _install_signal_handlers(*, quiet: bool) -> None:
    def handler(signum, _frame):  # noqa: ANN001
        global _STOPPING
        _STOPPING = True
        _log(f"signal {signum} — finishing up", quiet=quiet)

    for name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), handler)


def main(argv: list[str] | None = None) -> int:
    try:
        build_default, store_default = oq.default_paths()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(
        prog="watch-open-questions",
        description="Keep the open-question catalog in sync with the bundles under build/.",
    )
    parser.add_argument("--build-root", default=str(build_default),
                        help="bundle root to watch (default: <workspace>/build)")
    parser.add_argument("--store", default=str(store_default),
                        help="store directory (default: <workspace>/data/open-questions)")
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL,
                        help=f"seconds between polls, 0 to scan once (default: {DEFAULT_INTERVAL:g})")
    parser.add_argument("--once", action="store_true", help="scan once and exit (implies --interval 0)")
    parser.add_argument("--quiet", action="store_true",
                        help="log nothing on a poll that finds no change (errors still go to stderr)")
    parser.add_argument("--verbose", action="store_true", help="also report polls that found no change")
    args = parser.parse_args(argv)

    build_root = Path(args.build_root)
    store = Path(args.store)
    if not build_root.is_dir():
        print(f"build root not found: {build_root}", file=sys.stderr)
        return 1

    if args.once or args.interval <= 0:
        return scan_once(build_root, store, quiet=args.quiet, verbose=True)

    _install_signal_handlers(quiet=args.quiet)
    _log(f"watching {build_root} every {args.interval:g}s -> {oq.index_path(store)}", quiet=args.quiet)
    failures = 0
    while not _STOPPING:
        try:
            scan_once(build_root, store, quiet=args.quiet, verbose=args.verbose)
            failures = 0
        except Exception as error:  # noqa: BLE001 - a daemon must survive its input
            failures += 1
            print(f"[watch] scan failed ({failures} in a row): {type(error).__name__}: {error}",
                  file=sys.stderr, flush=True)
            if args.verbose:
                traceback.print_exc()
            if failures == 10:
                print("[watch] 10 consecutive failures — still running, but something is wrong",
                      file=sys.stderr, flush=True)
        # Sleep in short slices so a signal is honoured promptly.
        deadline = time.monotonic() + args.interval
        while not _STOPPING and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
    _log("stopped", quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
