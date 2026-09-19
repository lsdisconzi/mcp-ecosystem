"""Open-question catalog and evidence store.

This module owns one thing: the **open questions declared by every bundle under
``build/``**, plus the **evidence records** that other projects (and this one)
attach to them.

Why it exists
-------------
Open questions are the bundle's own statement of what is still unknown. They
live inside ``build/<VID>/<VID>.json``, which is per-bundle and therefore
invisible to anything that wants to answer them — a search UI cannot search 81
bundle files, and an answer found in an email has nowhere to be recorded.
This module projects them into one store that all projects can read, and gives
them one place to write the answers back.

Layout (under ``<data root>/open-questions/``)::

    index.json                        catalog: totals, per-bundle summary, flat
                                      question list — the consumption surface
    by-violation/<VID>.json           full detail for one bundle (self-contained)
    evidence/<VID>/<evidence_key>/    one directory per open question
        <record-id>.json              one ATOMIC file per evidence record

The evidence half is deliberately **one file per record**: appending is
``create``, never ``read-modify-write``, so ``seeking`` and the ViolationRefiner
UI can both record answers at the same time with no lock and no clobbering, and
neither has to be running for the other to work. The catalog half is
single-writer (the watcher, or this module's CLI).

Identifier rules — measured, not assumed
----------------------------------------
Corpus-wide (81 bundles) the raw ``open_questions[].id`` values are **not**
usable as keys:

* they are **not globally unique** — ``OQ-016-CCTV`` is declared by ``CL-016``
  twice, and several ``"+ N additional"`` markers repeat across bundles;
* they are **not filename-safe** — real ids contain spaces, ``+``, ``[``/``]``
  (``OQ-001-COMUNICACION-PDI-[[SPK-antonela-latam-agent]]``) and an em dash.

So every question gets three identifiers, and consumers should use them in this
order:

``catalog_id``
    ``"<violation_id>::<open_question_id>"``, with ``"::<n>"`` appended for the
    n-th repeat of an id inside one bundle. **Globally unique by construction.**
``evidence_key``
    A filesystem-safe, human-readable, deterministic token
    (``OQ-016-CCTV--37fe8557``). This is the directory name under ``evidence/``.
    Consumers never compute it themselves — read it off the catalog entry.
``open_question_id``
    The raw id as written in the bundle. Display and provenance only; **never**
    a key, because it is neither unique nor safe.

What the corpus actually contains (measured 2026-09-17)
------------------------------------------------------
Of the 681 entries the bundles declare, 9 are ``"+ N additional"`` markers
standing in for **74 questions that are never enumerated** — they have no id
anywhere in the artifacts, so no evidence can ever be attached to them. Those 9
never become records; the 74 are reported as ``declared_undocumented_count``.
That leaves **672 records**: 654 with question text, and **18 with an id but an
empty ``question`` string** (``"question": ""``, exactly as written). The 18 are
kept — dropping them would hide questions a reviewer can still chase by id — and
flagged ``question_text_missing`` so nothing tries to embed or search an empty
string.

Bundle and contract agree exactly on their id lists (verified: zero differences
across all 81), so ``contract-only`` is 0 today. The drift path is kept anyway,
computed from the raw id sets — computing it against the *surviving records*
instead produced 20 false drift warnings when first implemented.

Reading is tolerant by design. Evidence records are written by other projects,
so unknown fields are preserved rather than rejected, and one malformed record
is reported (``evidence_issues``) instead of poisoning the store.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from .ui_server import bundle_jurisdiction, is_bundle_dir

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

STORE_DIRNAME = "open-questions"
INDEX_FILENAME = "index.json"
BY_VIOLATION_DIRNAME = "by-violation"
EVIDENCE_DIRNAME = "evidence"

#: Bumped when the *shape* of ``index.json`` / ``by-violation/*.json`` changes in
#: a way a reader must know about. Readers should compare, not assume.
CATALOG_SCHEMA_VERSION = 1

#: Bumped when the evidence record shape gains a required field.
EVIDENCE_SCHEMA_VERSION = 1

#: The verdict vocabulary. ``partial`` means "moves it, does not settle it", so
#: the four are mutually exclusive on purpose — a record cannot both confirm and
#: refute, and a run of records is what the reviewer reads.
EVIDENCE_VERDICTS: tuple[str, ...] = ("supports", "refutes", "partial", "neutral")

#: Where the bundle files are, relative to the workspace root.
DEFAULT_BUILD_ROOTNAME = "build"

#: An open-question id is *expected* to start with ``OQ-``. This is a data-quality
#: signal, not a rule: measured corpus-wide, one bundle carries a question whose id
#: is a bare em dash instead of an id.
_EXPECTED_ID_PREFIX = "OQ-"

#: A bundle may stand in for a run of questions with a marker such as
#: ``"+ 4 additional"`` instead of enumerating them. Measured corpus-wide: 9 such
#: markers, declaring 74 questions that have no id anywhere in the artifacts — so
#: no evidence can ever be attached to them. They are counted and reported, and
#: they never become catalog records.
_UNDOCUMENTED_MARKER_RE = re.compile(r"^\+\s*(\d+)\s*additional", re.IGNORECASE)

#: Characters allowed verbatim in a path component we create.
_SAFE_COMPONENT_RE = re.compile(r"(?!.*\.\.)[A-Za-z0-9][A-Za-z0-9._-]*")

#: Everything else collapses to ``-`` when slugging an id for a directory name.
_UNSAFE_RUN_RE = re.compile(r"[^A-Za-z0-9._-]+")

#: Consecutive dashes collapse too, so a slug never contains the ``--`` that
#: separates the readable stub from the hash in an evidence key.
_DASH_RUN_RE = re.compile(r"-{2,}")

_SLUG_MAX = 60


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def now_iso() -> str:
    """UTC timestamp, second precision, ``Z``-suffixed (the corpus convention)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def is_safe_component(value: str) -> bool:
    """True when ``value`` is usable as a single path component we create.

    Rejects ``..`` anywhere, separators, and a leading dot — so a caller-supplied
    id can never escape the store.
    """
    return bool(value) and bool(_SAFE_COMPONENT_RE.fullmatch(value))


def slugify(value: str, *, max_length: int = _SLUG_MAX) -> str:
    """A readable, filesystem-safe stub of ``value`` (never trusted as unique).

    Runs of unsafe characters collapse to a single ``-`` so an id like
    ``...-PDI-[[SPK-antonela-latam-agent]]`` does not produce a ``--`` that reads
    like this module's own ``<slug>--<hash>`` separator.
    """
    slug = _UNSAFE_RUN_RE.sub("-", value or "")
    slug = _DASH_RUN_RE.sub("-", slug).strip("-.")
    slug = slug[:max_length].strip("-.")
    return slug or "question"


def evidence_key(violation_id: str, open_question_id: str, occurrence: int = 1) -> str:
    """The deterministic directory name that scopes one open question's evidence.

    Always ``<slug>--<hash8>``. The hash is taken over ``catalog_id``, so the key
    is stable across runs and unique across bundles — the ``"--"`` separator makes
    it obvious at a glance which part is the readable stub and which part is the
    disambiguator.
    """
    catalog_id = make_catalog_id(violation_id, open_question_id, occurrence)
    digest = hashlib.sha1(catalog_id.encode("utf-8")).hexdigest()[:8]
    return f"{slugify(open_question_id)}--{digest}"


def make_catalog_id(violation_id: str, open_question_id: str, occurrence: int = 1) -> str:
    """``<VID>::<id>``, plus ``::<n>`` for the n-th repeat inside one bundle."""
    base = f"{violation_id}::{open_question_id}"
    return base if occurrence <= 1 else f"{base}::{occurrence}"


#: ``evidence_key`` captured under a name that a same-named parameter cannot
#: shadow. ``make_evidence_record`` takes an ``evidence_key`` argument, and calling
#: the shadowed module function from inside it fails with the maximally confusing
#: ``TypeError: 'str' object is not callable``.
_evidence_key_for = evidence_key


def _clean(value: Any) -> str | None:
    """A non-empty stripped string, or ``None``. Models use ``None``, contracts ``""``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _undocumented_marker(value: str | None) -> int:
    """How many questions a ``"+ N additional"`` marker stands in for, else ``0``."""
    match = _UNDOCUMENTED_MARKER_RE.match(value or "")
    return int(match.group(1)) if match else 0


def read_json(path: Path, default: Any = None) -> Any:
    """Parse a JSON file, or return ``default`` when absent/unreadable.

    A malformed artifact is treated exactly like a missing one: cataloguing 81
    bundles must not fail because one of them is mid-write.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def atomic_write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as indented UTF-8 JSON via ``tmp`` + ``os.replace``.

    ``os.replace`` is atomic on POSIX, so a reader never observes a half-written
    file. The temp file is created in the *destination* directory, which is what
    makes the rename atomic — ``/tmp`` may be a different filesystem.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle_fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(handle_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------
# Store paths
# --------------------------------------------------------------------------


def store_dir(data_root: str | Path) -> Path:
    """``<data root>/open-questions`` — the store root (not created here)."""
    return Path(data_root) / STORE_DIRNAME


def index_path(store: str | Path) -> Path:
    return Path(store) / INDEX_FILENAME


def by_violation_dir(store: str | Path) -> Path:
    return Path(store) / BY_VIOLATION_DIRNAME


def by_violation_path(store: str | Path, violation_id: str) -> Path:
    return by_violation_dir(store) / f"{violation_id}.json"


def evidence_root(store: str | Path) -> Path:
    return Path(store) / EVIDENCE_DIRNAME


def evidence_dir(store: str | Path, violation_id: str, key: str) -> Path:
    """``evidence/<VID>/<evidence_key>/`` — one directory per open question.

    Both components are validated: the violation id is checked as a path
    component even though it comes from a bundle directory name, because this is
    the one place in the module that turns two strings into a writable path.
    """
    if not is_safe_component(violation_id):
        raise ValueError(f"unsafe violation id: {violation_id!r}")
    if not is_safe_component(key):
        raise ValueError(f"unsafe evidence key: {key!r}")
    return evidence_root(store) / violation_id / key


# --------------------------------------------------------------------------
# Catalog: reading
# --------------------------------------------------------------------------


def load_index(store: str | Path) -> dict[str, Any] | None:
    """The parsed ``index.json``, or ``None`` when the store has not been built."""
    payload = read_json(index_path(store))
    return payload if isinstance(payload, dict) else None


def load_catalog_questions(
    store: str | Path,
    violation_id: str | None = None,
    priority: str | None = None,
) -> list[dict[str, Any]]:
    """Flat question records, optionally filtered by bundle and/or priority."""
    index = load_index(store) or {}
    questions = index.get("questions")
    if not isinstance(questions, list):
        return []
    selected = []
    for entry in questions:
        if not isinstance(entry, dict):
            continue
        if violation_id and entry.get("violation_id") != violation_id:
            continue
        if priority and entry.get("priority") != priority:
            continue
        selected.append(entry)
    return selected


def load_questions_by_violation(store: str | Path) -> dict[str, list[dict[str, Any]]]:
    """``{violation_id: [question records]}`` projected from the flat index list."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in load_catalog_questions(store):
        grouped.setdefault(entry["violation_id"], []).append(entry)
    return grouped


def load_bundle_detail(store: str | Path, violation_id: str) -> dict[str, Any] | None:
    """The full ``by-violation/<VID>.json`` record, or ``None``."""
    if not is_safe_component(violation_id):
        return None
    payload = read_json(by_violation_path(store, violation_id))
    return payload if isinstance(payload, dict) else None


def lookup_question(
    store: str | Path,
    open_question_id: str,
    violation_id: str | None = None,
) -> list[dict[str, Any]]:
    """Every catalog entry carrying ``open_question_id``.

    A **list**, because the id is not unique: ``OQ-016-CCTV`` is declared twice by
    ``CL-016`` alone, and 10 ids appear in more than one bundle. A lookup that
    returned one entry would silently pick a winner.
    """
    matches = [
        entry
        for entry in load_catalog_questions(store, violation_id=violation_id)
        if entry.get("open_question_id") == open_question_id
    ]
    return matches


def lookup_by_evidence_key(store: str | Path, key: str) -> dict[str, Any] | None:
    for entry in load_catalog_questions(store):
        if entry.get("evidence_key") == key:
            return entry
    return None


# --------------------------------------------------------------------------
# Catalog: extraction from a bundle
# --------------------------------------------------------------------------

#: Bundle-relative artifacts the catalog fingerprints and reads. The violation
#: JSON is authoritative for the questions; the contract is read to *detect
#: drift*, never to add questions on its own authority.
_BUNDLE_FILES: tuple[str, ...] = ("{violation_id}.json", "contract.json")


def _bundle_file_paths(bundle_dir: Path) -> dict[str, Path]:
    return {
        name.format(violation_id=bundle_dir.name): bundle_dir / name.format(violation_id=bundle_dir.name)
        for name in _BUNDLE_FILES
    }


def _stat_signature(path: Path) -> str | None:
    """Cheap change detector: ``<mtime_ns>:<size>``, or ``None`` when absent.

    mtime *and* size, because a same-second rewrite can preserve mtime on a
    coarse-grained filesystem while changing the bytes.
    """
    try:
        stat = path.stat()
    except OSError:
        return None
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def _sha256_file(path: Path) -> str | None:
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def bundle_fingerprint(bundle_dir: Path, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Per-artifact ``{sig, sha256}``, reusing the previous sha when nothing changed.

    Hashing 81 bundles on every poll would read ~16 MB per tick for nothing, so
    the cheap stat signature gates it: a matching signature carries the previous
    hash forward, and only a changed file is actually hashed.
    """
    fingerprint: dict[str, Any] = {}
    for name, path in _bundle_file_paths(bundle_dir).items():
        signature = _stat_signature(path)
        if signature is None:
            fingerprint[name] = {"sig": None, "sha256": None}
            continue
        prior = (previous or {}).get(name) or {}
        if prior.get("sig") == signature and prior.get("sha256"):
            fingerprint[name] = {"sig": signature, "sha256": prior["sha256"]}
        else:
            fingerprint[name] = {"sig": signature, "sha256": _sha256_file(path)}
    return fingerprint


def _question_records(
    raw_questions: Iterable[Any],
    *,
    violation_id: str,
    jurisdiction: str,
    source: str,
    contract_ids: set[str],
) -> list[dict[str, Any]]:
    """Normalise one bundle's question list into catalog records.

    An entry is kept whenever it has a usable **id** — even when its ``question``
    text is empty. Measured corpus-wide that is 18 real entries: the bundle
    recorded id + priority and never filled in the text, so dropping them would
    hide 18 questions that a reviewer could still chase by id.

    ``occurrence`` counts repeats of the same raw id **within this list**. It is
    load-bearing: ``CL-016`` declares eight of its ids twice, so without it the
    second ``OQ-016-CCTV`` would be indistinguishable from the first.
    """
    records: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for raw in raw_questions:
        if not isinstance(raw, dict):
            continue
        open_question_id = _clean(raw.get("id"))
        if not open_question_id or _undocumented_marker(open_question_id):
            # No id at all, or a "+ N additional" marker standing in for questions
            # that the bundle chose not to enumerate. Neither is a question; the
            # caller counts the markers and reports them.
            continue
        question_text = _clean(raw.get("question"))
        seen[open_question_id] = seen.get(open_question_id, 0) + 1
        occurrence = seen[open_question_id]
        records.append({
            "catalog_id": make_catalog_id(violation_id, open_question_id, occurrence),
            "open_question_id": open_question_id,
            "violation_id": violation_id,
            "jurisdiction": jurisdiction,
            "evidence_key": evidence_key(violation_id, open_question_id, occurrence),
            "occurrence": occurrence,
            "question": question_text,
            "question_text_missing": question_text is None,
            "priority": _clean(raw.get("priority")),
            "blocks_element": _clean(raw.get("blocks_element")),
            "obtaining_method": _clean(raw.get("obtaining_method")),
            "source": source,
            "in_bundle": source == "bundle",
            "in_contract": open_question_id in contract_ids,
        })
    return records


def extract_bundle(bundle_dir: Path, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read one bundle and return its catalog detail record (questions included).

    Reads ``<VID>.json`` **only** — never ``<VID>.json.bak``. The refiner prefers
    the backup, so cataloguing it would silently publish a previous generation's
    questions; the presence of a backup is reported as a warning instead.
    """
    violation_id = bundle_dir.name
    jurisdiction = bundle_jurisdiction(violation_id)
    payload_path = bundle_dir / f"{violation_id}.json"
    fingerprint = bundle_fingerprint(bundle_dir, previous)

    warnings: list[str] = []
    if (bundle_dir / f"{violation_id}.json.bak").is_file():
        warnings.append(
            f"{violation_id}.json.bak is present and was NOT catalogued — "
            "the live bundle is the source of truth, and the refiner prefers the backup"
        )

    violation = read_json(payload_path)
    contract = read_json(bundle_dir / "contract.json")

    if not isinstance(violation, dict):
        warnings.append(f"unreadable violation payload: {payload_path.name}")
        return {
            "schema_version": CATALOG_SCHEMA_VERSION,
            "violation_id": violation_id,
            "jurisdiction": jurisdiction,
            "title": None,
            "severity": None,
            "bundle_path": f"{DEFAULT_BUILD_ROOTNAME}/{violation_id}/{payload_path.name}",
            "fingerprint": fingerprint,
            "question_count": 0,
            "searchable_question_count": 0,
            "stub_count": 0,
            "declared_undocumented_count": 0,
            "contract_only_count": 0,
            "bundle_only_count": 0,
            "warnings": warnings,
            "questions": [],
        }

    bundle_questions = violation.get("open_questions") or []
    contract_questions = (contract or {}).get("open_questions") or [] if isinstance(contract, dict) else []

    contract_ids = {
        cid for cid in (_clean(item.get("id")) for item in contract_questions if isinstance(item, dict)) if cid
    }
    bundle_id_set = {
        bid for bid in (_clean(item.get("id")) for item in bundle_questions if isinstance(item, dict)) if bid
    }

    records = _question_records(
        bundle_questions,
        violation_id=violation_id,
        jurisdiction=jurisdiction,
        source="bundle",
        contract_ids=contract_ids,
    )

    # Drift is computed from the raw id SETS, never from the surviving records.
    # Comparing against the records once produced 20 false "contract declares
    # questions absent from the bundle" warnings, because the records were the
    # post-filter list and the filter had already removed those ids.
    contract_only = sorted(contract_ids - bundle_id_set)
    if contract_only:
        wanted = set(contract_only)
        records.extend(_question_records(
            [item for item in contract_questions
             if isinstance(item, dict) and _clean(item.get("id")) in wanted],
            violation_id=violation_id,
            jurisdiction=jurisdiction,
            source="contract-only",
            contract_ids=contract_ids,
        ))
        shown = ", ".join(contract_only[:5])
        more = f" (+{len(contract_only) - 5} more)" if len(contract_only) > 5 else ""
        warnings.append(
            f"contract.json declares {len(contract_only)} open question id(s) absent from the bundle "
            f"({shown}{more}) — V17 fails on this drift"
        )

    stubs = [record for record in records if record["question_text_missing"]]
    if stubs:
        shown = ", ".join(record["open_question_id"] for record in stubs[:5])
        more = f" (+{len(stubs) - 5} more)" if len(stubs) > 5 else ""
        warnings.append(
            f"{len(stubs)} open question(s) carry an id but no question text: {shown}{more} — "
            "they are catalogued so they can still be answered by id, but nothing can be searched for"
        )

    markers = [item for item in bundle_questions
               if isinstance(item, dict) and _undocumented_marker(_clean(item.get("id")))]
    undocumented = sum(_undocumented_marker(_clean(item.get("id"))) for item in markers)
    if undocumented:
        warnings.append(
            f"{len(markers)} marker(s) stand in for {undocumented} open question(s) that are not enumerated "
            "— their ids are unknown, so no evidence can ever be attached to them"
        )

    odd_ids = sorted({
        record["open_question_id"] for record in records
        if not record["open_question_id"].startswith(_EXPECTED_ID_PREFIX)
    })
    if odd_ids:
        shown = ", ".join(repr(value) for value in odd_ids[:5])
        more = f" (+{len(odd_ids) - 5} more)" if len(odd_ids) > 5 else ""
        warnings.append(f"{len(odd_ids)} open question id(s) do not match the OQ- form: {shown}{more}")

    repeated = sorted({
        record["open_question_id"] for record in records if record["occurrence"] > 1
    })
    if repeated:
        warnings.append(f"{len(repeated)} open question id(s) repeat within this bundle: "
                        + ", ".join(repeated[:5]))

    title = _clean(violation.get("title"))
    severity = _clean(violation.get("severity"))

    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "violation_id": violation_id,
        "jurisdiction": jurisdiction,
        "title": title,
        "severity": severity,
        "bundle_path": f"{DEFAULT_BUILD_ROOTNAME}/{violation_id}/{payload_path.name}",
        "fingerprint": fingerprint,
        "question_count": len(records),
        "searchable_question_count": sum(1 for record in records if not record["question_text_missing"]),
        "stub_count": len(stubs),
        "declared_undocumented_count": undocumented,
        "contract_only_count": sum(1 for record in records if record["source"] == "contract-only"),
        "bundle_only_count": sum(
            1 for record in records
            if record["source"] == "bundle" and not record["in_contract"]
        ),
        "warnings": warnings,
        "questions": records,
    }


def _reuse_detail(
    violation_id: str,
    summary: dict[str, Any],
    questions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rebuild a bundle's detail record from a previous catalog entry.

    Every field the detail file carries is taken from the summary, so a reused
    bundle is indistinguishable from a freshly extracted one — reuse is an
    optimisation, never a second shape.
    """
    return {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "violation_id": violation_id,
        "jurisdiction": summary.get("jurisdiction"),
        "title": summary.get("title"),
        "severity": summary.get("severity"),
        "bundle_path": summary.get("bundle_path"),
        "fingerprint": summary.get("fingerprint") or {},
        "question_count": summary.get("question_count", 0),
        "searchable_question_count": summary.get("searchable_question_count", 0),
        "stub_count": summary.get("stub_count", 0),
        "declared_undocumented_count": summary.get("declared_undocumented_count", 0),
        "contract_only_count": summary.get("contract_only_count", 0),
        "bundle_only_count": summary.get("bundle_only_count", 0),
        "warnings": summary.get("warnings") or [],
        "questions": questions,
    }


def iter_bundle_dirs(build_root: str | Path) -> list[Path]:
    """Every real bundle directory under ``build/``, in name order.

    Structural test (``<dir>/<dir>.json`` exists), never a name pattern: the
    ``CL-\\d+`` form this used to mirror hid all 20 BR and all 19 INT bundles.
    """
    root = Path(build_root)
    if not root.is_dir():
        return []
    return [path for path in sorted(root.iterdir(), key=lambda item: item.name)
            if is_bundle_dir(path)]


def scan_build(
    build_root: str | Path,
    *,
    previous: dict[str, Any] | None = None,
    only: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build the whole catalog from ``build/``.

    ``previous`` is a previously loaded ``index.json``; its per-bundle
    fingerprints let unchanged bundles be reused byte-for-byte instead of
    re-extracted. ``only`` restricts the scan to named bundles — the watcher uses
    it to rebuild just what changed.
    """
    root = Path(build_root)
    previous_violations = (previous or {}).get("violations") or {}
    selected = set(only) if only is not None else None

    # The previous flat list is the reuse source. Keeping the records in exactly
    # one place inside the index means the two copies cannot drift apart, and
    # halves the file compared with carrying them in the per-bundle summary too.
    #
    # Seeded from the violation map, not from the question list: 41 of the 81
    # bundles declare no questions at all, and those have nothing to put in the
    # flat list — seeding from it left them looking like new bundles on every
    # scan and re-extracted them forever.
    previous_questions: dict[str, list[dict[str, Any]]] = {
        violation_id: [] for violation_id in (previous_violations or {})
    }
    for entry in (previous or {}).get("questions") or []:
        if isinstance(entry, dict) and entry.get("violation_id"):
            previous_questions.setdefault(entry["violation_id"], []).append(entry)

    details: list[dict[str, Any]] = []
    reused: list[str] = []
    seen: set[str] = set()
    for bundle_dir in iter_bundle_dirs(root):
        violation_id = bundle_dir.name
        if selected is not None and violation_id not in selected:
            continue
        seen.add(violation_id)
        prior_summary = previous_violations.get(violation_id) if isinstance(previous_violations, dict) else None
        prior_fingerprint = prior_summary.get("fingerprint") if isinstance(prior_summary, dict) else None
        prior_questions = previous_questions.get(violation_id)
        prior_detail = None
        if isinstance(prior_fingerprint, dict) and prior_questions is not None:
            if bundle_fingerprint(bundle_dir, prior_fingerprint) == prior_fingerprint:
                prior_detail = _reuse_detail(violation_id, prior_summary, prior_questions)
                reused.append(violation_id)
        details.append(prior_detail or extract_bundle(
            bundle_dir, prior_fingerprint if isinstance(prior_fingerprint, dict) else None))

    # A partial scan must still produce a COMPLETE catalog: `write_catalog` prunes
    # every detail file it does not see, so re-scanning one bundle without this
    # would delete the other eighty. Carrying the untouched bundles forward is
    # what makes `--only` safe.
    if selected is not None:
        for violation_id, prior_summary in (previous_violations or {}).items():
            if violation_id in seen or violation_id not in previous_questions:
                continue
            if not is_bundle_dir(root / violation_id):
                continue
            details.append(_reuse_detail(violation_id, prior_summary, previous_questions[violation_id]))
            seen.add(violation_id)
            reused.append(violation_id)

    details.sort(key=lambda item: item["violation_id"])

    questions: list[dict[str, Any]] = []
    violations: dict[str, Any] = {}
    for detail in details:
        questions.extend(detail["questions"])
        violations[detail["violation_id"]] = {
            "title": detail.get("title"),
            "severity": detail.get("severity"),
            "jurisdiction": detail.get("jurisdiction"),
            "question_count": detail.get("question_count", 0),
            "searchable_question_count": detail.get("searchable_question_count", 0),
            "stub_count": detail.get("stub_count", 0),
            "declared_undocumented_count": detail.get("declared_undocumented_count", 0),
            "contract_only_count": detail.get("contract_only_count", 0),
            "bundle_only_count": detail.get("bundle_only_count", 0),
            "warnings": detail.get("warnings") or [],
            "fingerprint": detail.get("fingerprint") or {},
            "open_question_ids": [q["open_question_id"] for q in detail["questions"]],
            "evidence_keys": [q["evidence_key"] for q in detail["questions"]],
            "by_violation_file": f"{BY_VIOLATION_DIRNAME}/{detail['violation_id']}.json",
        }

    catalog = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "build_root": DEFAULT_BUILD_ROOTNAME,
        "store": {
            "index": INDEX_FILENAME,
            "by_violation": BY_VIOLATION_DIRNAME,
            "evidence": EVIDENCE_DIRNAME,
        },
        "totals": {
            "bundles": len(details),
            "questions": len(questions),
            "searchable_questions": sum(1 for q in questions if not q["question_text_missing"]),
            "stub_questions": sum(1 for q in questions if q["question_text_missing"]),
            "declared_undocumented": sum(d.get("declared_undocumented_count", 0) for d in details),
            "bundles_with_questions": sum(1 for d in details if d["question_count"]),
            "contract_only": sum(1 for q in questions if q["source"] == "contract-only"),
            "bundle_only": sum(1 for q in questions if q["source"] == "bundle" and not q["in_contract"]),
            "bundles_with_warnings": sum(1 for d in details if d["warnings"]),
            "reused_from_previous": len(reused),
        },
        "violations": violations,
        "questions": questions,
    }
    catalog["digest"] = catalog_digest(catalog)
    return catalog


def write_catalog(
    catalog: dict[str, Any],
    store: str | Path,
    detail_ids: Iterable[str] | None = None,
) -> dict[str, int]:
    """Write ``by-violation/*.json`` then ``index.json``; return what was written.

    Order matters: the detail files land first so the index never points at a
    file that does not exist yet. Only bundles present in this catalog are
    rewritten; a detail file for a bundle that has since vanished is removed, so
    the store cannot accumulate ghost bundles.

    ``detail_ids`` restricts which detail files are *written* (the watcher passes
    only the bundles that actually changed, so one bundle edit touches one file
    instead of all 81). It never restricts pruning — a bundle absent from
    ``catalog`` is removed from disk regardless.
    """
    store_path = Path(store)
    detail_dir = by_violation_dir(store_path)
    detail_dir.mkdir(parents=True, exist_ok=True)
    writable = set(detail_ids) if detail_ids is not None else None
    questions = catalog.get("questions") or []
    by_violation: dict[str, list[dict[str, Any]]] = {}
    for entry in questions:
        by_violation.setdefault(entry["violation_id"], []).append(entry)

    written = 0
    skipped = 0
    for violation_id, summary in catalog.get("violations", {}).items():
        target = by_violation_path(store_path, violation_id)
        # A detail file that does not exist must always be written, or a store
        # built from a fresh clone would have an index pointing at nothing.
        if writable is not None and violation_id not in writable and target.is_file():
            skipped += 1
            continue
        detail = dict(summary)
        detail["violation_id"] = violation_id
        detail["schema_version"] = CATALOG_SCHEMA_VERSION
        detail["generated_at"] = catalog.get("generated_at")
        # The records live once, in the index; the detail file carries its own
        # copy so a bundle can be read without the whole catalog.
        detail["questions"] = by_violation.get(violation_id, [])
        detail.pop("open_question_ids", None)
        detail.pop("evidence_keys", None)
        atomic_write_json(target, detail)
        written += 1

    known = set(catalog.get("violations", {}))
    removed = 0
    if detail_dir.is_dir():
        for existing in detail_dir.glob("*.json"):
            if existing.stem not in known:
                try:
                    existing.unlink()
                    removed += 1
                except OSError:
                    pass

    atomic_write_json(index_path(store_path), catalog)
    return {
        "details_written": written,
        "details_skipped": skipped,
        "details_removed": removed,
        "index": 1,
    }


def build_catalog(
    build_root: str | Path,
    store: str | Path,
    *,
    only: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Load → scan → write, in one call. Returns the catalog that was written."""
    store_path = Path(store)
    previous = load_index(store_path)
    catalog = scan_build(build_root, previous=previous, only=only)
    write_catalog(catalog, store_path)
    return catalog


def bundled_questions(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Every question record in a catalog (convenience for callers holding one)."""
    return list(catalog.get("questions") or [])


def missing_detail_files(store: str | Path, catalog: dict[str, Any]) -> list[str]:
    """Catalogued bundles whose ``by-violation/<VID>.json`` is absent.

    A store can be *content-current* and still broken: a fresh clone, a partial
    copy, or an interrupted write leaves the index describing files that are not
    there. The digest cannot see that, because the digest is about the bundles,
    not about this directory — so intake checks this separately, otherwise the
    store would stay inconsistent forever precisely when the corpus is stable.
    """
    store_path = Path(store)
    return [
        violation_id for violation_id in (catalog.get("violations") or {})
        if not by_violation_path(store_path, violation_id).is_file()
    ]


def catalog_digest(catalog: dict[str, Any]) -> str:
    """A digest of everything in the catalog that is a *fact about the bundles*.

    Excludes the three fields that legitimately differ between two scans of
    identical data — ``generated_at``, the digest itself, and
    ``totals.reused_from_previous`` (which is a property of the previous run, not
    of the corpus). The watcher compares this against the stored digest to decide
    whether to write at all: without it, a 15-second poll would rewrite
    ``index.json`` forever and show up as endless churn in ``git status``.
    """
    payload = {key: value for key, value in catalog.items() if key != "digest"}
    payload.pop("generated_at", None)
    totals = dict(payload.get("totals") or {})
    totals.pop("reused_from_previous", None)
    payload["totals"] = totals
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Evidence: writing
# --------------------------------------------------------------------------


def make_evidence_record(
    *,
    open_question_id: str,
    violation_id: str,
    evidence_key: str,
    occurrence: int = 1,
    catalog_id: str | None = None,
    verdict: str = "neutral",
    note: str | None = None,
    excerpt: str | None = None,
    source: dict[str, Any] | None = None,
    author: str | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    """Assemble one evidence record, validating everything that becomes a path or a key.

    ``verdict`` must be one of ``EVIDENCE_VERDICTS``. It is raised, not coerced:
    a typo'd verdict silently stored as ``neutral`` would read as "the reviewer
    looked and it says nothing", which is the opposite of what they meant.

    ``occurrence`` identifies *which* declaration of a repeated id the evidence
    belongs to, and all three identifiers are checked against it. That check is
    not decoration: ``CL-016`` declares eight of its ids twice, so evidence filed
    under occurrence 1 when the reviewer answered the second declaration would
    still be written, still be readable, and still be attached to the wrong
    question — with nothing anywhere reporting it. ``catalog_id`` may be passed
    by a caller that read it from the catalog (the API does), and is then
    required to agree with its own derivation rather than overriding it.
    """
    if not _clean(open_question_id):
        raise ValueError("open_question_id is required")
    if not is_safe_component(violation_id):
        raise ValueError(f"unsafe violation id: {violation_id!r}")
    if not is_safe_component(evidence_key):
        raise ValueError(f"unsafe evidence key: {evidence_key!r}")
    if verdict not in EVIDENCE_VERDICTS:
        raise ValueError(f"verdict must be one of {EVIDENCE_VERDICTS}, got {verdict!r}")
    try:
        occurrence = int(occurrence)
    except (TypeError, ValueError):
        raise ValueError(f"occurrence must be an integer, got {occurrence!r}") from None
    if occurrence < 1:
        raise ValueError(f"occurrence starts at 1, got {occurrence}")

    derived_catalog_id = make_catalog_id(violation_id, open_question_id, occurrence)
    derived_key = _evidence_key_for(violation_id, open_question_id, occurrence)
    if derived_key != evidence_key:
        raise ValueError(
            f"evidence_key {evidence_key!r} does not belong to {violation_id!r}/"
            f"{open_question_id!r} occurrence {occurrence} — expected {derived_key!r}"
        )
    if catalog_id is not None and _clean(catalog_id) != derived_catalog_id:
        raise ValueError(
            f"catalog_id {catalog_id!r} contradicts its own parts — "
            f"expected {derived_catalog_id!r}"
        )

    identifier = _clean(record_id) or uuid.uuid4().hex
    if not is_safe_component(identifier):
        raise ValueError(f"unsafe evidence record id: {identifier!r}")

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "id": identifier,
        "catalog_id": derived_catalog_id,
        "open_question_id": open_question_id,
        "violation_id": violation_id,
        "evidence_key": evidence_key,
        "occurrence": occurrence,
        "verdict": verdict,
        "note": _clean(note),
        "excerpt": _clean(excerpt),
        "source": source if isinstance(source, dict) else {},
        "author": _clean(author),
        "created_at": now_iso(),
    }


def add_evidence(store: str | Path, record: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Persist one evidence record atomically. ``(record, created)``.

    Writing by ``id`` makes the call idempotent: re-posting the same record (a
    double-clicked button, a retried request) rewrites the same file with the
    same content instead of minting a second copy.
    """
    if not isinstance(record, dict):
        raise ValueError("evidence record must be a JSON object")
    violation_id = _clean(record.get("violation_id"))
    key = _clean(record.get("evidence_key"))
    open_question_id = _clean(record.get("open_question_id"))
    identifier = _clean(record.get("id"))
    if not (violation_id and key and open_question_id and identifier):
        raise ValueError("evidence record needs id, open_question_id, violation_id and evidence_key")

    target_dir = evidence_dir(store, violation_id, key)
    target = target_dir / f"{identifier}.json"
    created = not target.exists()
    atomic_write_json(target, record)
    return record, created


def delete_evidence(store: str | Path, violation_id: str, evidence_key: str,
                    record_id: str) -> bool:
    """Delete one record. ``True`` when a file was removed, ``False`` when it was absent.

    Unsafe arguments **raise** rather than returning ``False``, matching
    ``add_evidence`` and ``evidence_dir``: a path-traversal attempt must be a loud
    error, not a silent no-op indistinguishable from "the record did not exist".

    Removing the last record for a question also removes the directories it leaves
    behind, so the tree keeps meaning what it looks like: ``evidence/<VID>/<key>/``
    exists **iff** that question has evidence. An empty directory is not a count
    (``evidence_counts`` yields nothing for it and ``orphaned_evidence`` ignores a
    key with no ``*.json``), but a store that says "there is evidence here" and
    holds none is exactly the kind of misleading state the rest of this module is
    built to avoid. ``rmdir`` only ever removes an *empty* directory, so a record
    written by another process in the meantime makes it fail harmlessly — which is
    why the ``OSError`` is swallowed rather than raised.
    """
    if not is_safe_component(record_id):
        raise ValueError(f"unsafe evidence record id: {record_id!r}")
    target_dir = evidence_dir(store, violation_id, evidence_key)
    target = target_dir / f"{record_id}.json"
    try:
        target.unlink()
    except OSError:
        return False

    for empty in (target_dir, target_dir.parent):
        try:
            empty.rmdir()
        except OSError:
            break
    return True


# --------------------------------------------------------------------------
# Evidence: reading
# --------------------------------------------------------------------------


def iter_evidence(
    store: str | Path,
    violation_id: str | None = None,
    evidence_key_filter: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every readable evidence record, newest last by directory order."""
    root = evidence_root(store)
    if not root.is_dir():
        return
    violation_dirs = [root / violation_id] if violation_id else sorted(root.iterdir())
    for violation_dir in violation_dirs:
        if not violation_dir.is_dir():
            continue
        key_dirs = ([violation_dir / evidence_key_filter] if evidence_key_filter
                    else sorted(violation_dir.iterdir()))
        for key_dir in key_dirs:
            if not key_dir.is_dir():
                continue
            for record_path in sorted(key_dir.glob("*.json")):
                payload = read_json(record_path)
                if isinstance(payload, dict):
                    yield payload


def evidence_issues(store: str | Path) -> list[dict[str, str]]:
    """Every unreadable evidence file, as ``{path, error}``.

    Reporting beats raising: one hand-edited or half-written record must not make
    the whole store unreadable, and a silent skip would hide it.
    """
    issues: list[dict[str, str]] = []
    root = evidence_root(store)
    if not root.is_dir():
        return issues
    for record_path in sorted(root.rglob("*.json")):
        try:
            with record_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                issues.append({"path": str(record_path), "error": "not a JSON object"})
        except (OSError, ValueError) as error:
            issues.append({"path": str(record_path), "error": f"{type(error).__name__}: {error}"})
    return issues


def evidence_counts(store: str | Path, violation_id: str | None = None) -> dict[str, int]:
    """``{evidence_key: record_count}`` — computed from disk, never stored.

    Derived on read on purpose: a count cached in the catalog goes stale the
    moment seeking records an answer, and a stale count on screen is worse than
    no count.
    """
    counts: dict[str, int] = {}
    for record in iter_evidence(store, violation_id=violation_id):
        key = _clean(record.get("evidence_key"))
        if key:
            counts[key] = counts.get(key, 0) + 1
    return counts


def evidence_for_violation(store: str | Path, violation_id: str) -> dict[str, list[dict[str, Any]]]:
    """``{evidence_key: [records]}`` for one bundle's questions."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in iter_evidence(store, violation_id=violation_id):
        key = _clean(record.get("evidence_key"))
        if key:
            grouped.setdefault(key, []).append(record)
    for records in grouped.values():
        records.sort(key=lambda item: str(item.get("created_at") or ""))
    return grouped


def orphaned_evidence(store: str | Path) -> list[dict[str, int]]:
    """Evidence whose bundle or question is no longer in the catalog.

    Not deleted, and not an error: a question can leave a bundle while the
    evidence that answered it is still worth reading. Surfacing it lets a human
    decide, which is the only honest option — the record may be the last trace of
    a question someone removed by accident.
    """
    index = load_index(store) or {}
    known_bundles = set(index.get("violations") or {})
    known_keys = {entry.get("evidence_key") for entry in (index.get("questions") or [])}

    orphans: dict[tuple[str, str], int] = {}
    root = evidence_root(store)
    if not root.is_dir():
        return []
    for violation_dir in sorted(root.iterdir()):
        if not violation_dir.is_dir():
            continue
        for key_dir in sorted(violation_dir.iterdir()):
            if not key_dir.is_dir():
                continue
            if violation_dir.name in known_bundles and key_dir.name in known_keys:
                continue
            count = sum(1 for _ in key_dir.glob("*.json"))
            if count:
                orphans[(violation_dir.name, key_dir.name)] = count
    return [
        {"violation_id": violation_id, "evidence_key": key, "records": count}
        for (violation_id, key), count in sorted(orphans.items())
    ]


def summarise_evidence(records: list[dict[str, Any]]) -> dict[str, int]:
    """Count records per verdict (``neutral`` included), for a UI header."""
    summary = {verdict: 0 for verdict in EVIDENCE_VERDICTS}
    for record in records:
        verdict = record.get("verdict")
        if verdict in summary:
            summary[verdict] += 1
    summary["total"] = len(records)
    return summary


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def default_paths() -> tuple[Path, Path]:
    """``(build root, store)`` derived from the package location, not the cwd.

    Raises ``RuntimeError`` rather than exiting, because this is called from the
    watcher script as well as from the CLI, and a library helper must not decide
    that the whole process should die.
    """
    here = Path(__file__).resolve().parent
    for base in (here, *here.parents):
        if (base / "pyproject.toml").is_file() and (base / "violation_pack").is_dir():
            data_root = base / "data"
            return base / DEFAULT_BUILD_ROOTNAME, store_dir(data_root)
    raise RuntimeError("could not locate the workspace root (no pyproject.toml found)")


def main(argv: list[str] | None = None) -> int:
    import argparse

    try:
        build_default, store_default = default_paths()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(
        prog="violation-pack-open-questions",
        description="Build the open-question catalog and report on its evidence store.",
    )
    parser.add_argument("--build-root", default=str(build_default),
                        help="bundle root to scan (default: <workspace>/build)")
    parser.add_argument("--store", default=str(store_default),
                        help="store directory (default: <workspace>/data/open-questions)")
    parser.add_argument("--only", nargs="*", default=None,
                        help="restrict the scan to these bundle ids")
    parser.add_argument("--check", action="store_true",
                        help="do not write; report catalog drift, orphans and unreadable evidence")
    parser.add_argument("--quiet", action="store_true", help="suppress the per-bundle table")
    args = parser.parse_args(argv)

    store = Path(args.store)
    if args.check:
        index = load_index(store)
        if index is None:
            print(f"no catalog at {index_path(store)} — run without --check to build it")
            return 1
        issues = evidence_issues(store)
        orphans = orphaned_evidence(store)
        counts = evidence_counts(store)
        print(f"catalog:  {len(index.get('questions') or [])} questions in "
              f"{(index.get('totals') or {}).get('bundles', 0)} bundles "
              f"(generated {index.get('generated_at')})")
        print(f"evidence: {sum(counts.values())} record(s) across {len(counts)} question(s)")
        missing = missing_detail_files(store, index)
        for violation_id in missing:
            print(f"  missing detail file: {BY_VIOLATION_DIRNAME}/{violation_id}.json")
        for issue in issues:
            print(f"  unreadable evidence: {issue['path']} — {issue['error']}")
        for orphan in orphans:
            print(f"  orphaned evidence: {orphan['violation_id']}/{orphan['evidence_key']} "
                  f"({orphan['records']} record(s))")
        stale = check_freshness(Path(args.build_root), index)
        for violation_id in stale:
            print(f"  stale bundle (changed since cataloguing): {violation_id}")
        return 1 if (issues or orphans or stale or missing) else 0

    catalog = build_catalog(args.build_root, store, only=args.only)
    totals = catalog["totals"]
    print(f"catalogued {totals['questions']} open question(s) across "
          f"{totals['bundles']} bundle(s) -> {index_path(store)}")
    print(f"  searchable {totals['searchable_questions']} · "
          f"id-only stubs {totals['stub_questions']} · "
          f"declared-but-not-enumerated {totals['declared_undocumented']} · "
          f"contract-only {totals['contract_only']} · reused {totals['reused_from_previous']}")
    if not args.quiet:
        for violation_id, summary in catalog["violations"].items():
            if not summary["question_count"] and not summary["warnings"]:
                continue
            flags = []
            if summary.get("stub_count"):
                flags.append(f"stubs={summary['stub_count']}")
            if summary.get("declared_undocumented_count"):
                flags.append(f"not-enumerated={summary['declared_undocumented_count']}")
            if summary["contract_only_count"]:
                flags.append(f"contract-only={summary['contract_only_count']}")
            if summary["bundle_only_count"]:
                flags.append(f"bundle-only={summary['bundle_only_count']}")
            if summary["warnings"]:
                flags.append(f"warnings={len(summary['warnings'])}")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            print(f"  {violation_id:<16} {summary['question_count']:>3} question(s){suffix}")
    for orphan in orphaned_evidence(store):
        print(f"  orphaned evidence: {orphan['violation_id']}/{orphan['evidence_key']} "
              f"({orphan['records']} record(s))")
    return 0


def check_freshness(build_root: str | Path, index: dict[str, Any]) -> list[str]:
    """Bundle ids whose on-disk fingerprint no longer matches the catalog."""
    previous_violations = index.get("violations") or {}
    stale: list[str] = []
    for bundle_dir in iter_bundle_dirs(build_root):
        prior = previous_violations.get(bundle_dir.name)
        prior_fingerprint = (prior or {}).get("fingerprint")
        if not isinstance(prior_fingerprint, dict):
            stale.append(bundle_dir.name)
            continue
        if bundle_fingerprint(bundle_dir, prior_fingerprint) != prior_fingerprint:
            stale.append(bundle_dir.name)
    catalogued = set(previous_violations)
    on_disk = {path.name for path in iter_bundle_dirs(build_root)}
    stale.extend(sorted(catalogued - on_disk))
    return sorted(set(stale))


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
