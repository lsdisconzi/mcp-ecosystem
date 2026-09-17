"""The bundle's three segment artifacts must agree after one write.

``<VID>.json`` is the statement of which segments the pack cites;
``segments_manifest.json`` and ``Transcripts/<id>.json`` are two more. They were
produced once, by ``examples/vault_to_bundle.py``, and nothing rewrote them
afterwards — so every segment added in S2 landed in the violation alone. The
drift is what ``examples/validate_preflight.py`` refuses to pass, so the two
checks are loaded here and run against a real temp bundle: first on the drifted
state (they must report errors) and then after ``sync_segment_artifacts()`` (they
must be clean). A green test that never saw the check fail proves nothing.
"""
from __future__ import annotations

import asyncio
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from violation_pack.models import EvidenceSegment, Incident, Violation
from violation_pack.pack import write_violation_json
from violation_pack.segment_sync import sync_segment_artifacts

REPO_ROOT = Path(__file__).parent.parent
VID = "CL-900"
PRE_BOARDING = "I-002_01_NAR-01_STG_1_pre_boarding"
JETBRIDGE = "I-002_04_NAR-06_STG_6_jetbridge_standoff"


@pytest.fixture(scope="module")
def preflight():
    """``examples/validate_preflight.py`` — the consumer whose checks define
    what "in sync" means. Loaded from its path because ``examples/`` is not a
    package, and it has no import-time side effects."""
    path = REPO_ROOT / "examples" / "validate_preflight.py"
    spec = importlib.util.spec_from_file_location("validate_preflight", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Fixtures: a bundle shaped the way the converter writes one
# ---------------------------------------------------------------------------

def _write_corpus(root: Path, transcript_id: str, count: int = 6) -> Path:
    """A full canonical transcript in the corpus every bundle links to.

    ``_source_candidates`` reads ``<bundle>/../../data/transcripts/json/``, so the
    bundle must sit under ``<root>/build/<VID>`` for this to be the input it finds
    in the workspace.
    """
    path = root / "data" / "transcripts" / "json" / f"{transcript_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "transcript_id": transcript_id,
        "source_file": f"{transcript_id}.mp3",
        "source_path": f"audio/{transcript_id}.mp3",
        "language": "pt",
        "provider": "test",
        "metadata": {"imported_by": "test"},
        "title": "Pre-Boarding",
        "case_id": "I-002",
        "audio_id": "aeropuerto_STG_1",
        "participants": ["passenger", "pilot"],
        "reviewed": True,
        "segments": [
            {
                "index": i,
                "speaker": "passenger",
                "start": i * 2.0,
                "end": i * 2.0 + 1.5,
                "duration": 1.5,
                "text": f"frase {i}",
                "reviewed": True,
                "segment_datetime": f"2024-07-05T13:33:{i:02d}.000",
            }
            for i in range(count)
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _bundle(root: Path, *, link: str | None = PRE_BOARDING) -> Path:
    """``<root>/build/CL-900`` with a converter-style relative corpus link."""
    bundle = root / "build" / VID
    transcripts = bundle / "Transcripts"
    transcripts.mkdir(parents=True, exist_ok=True)
    if link:
        (transcripts / f"{link}.json").symlink_to(
            f"../../../data/transcripts/json/{link}.json"
        )
    return bundle


def _segment(transcript_id: str, index: int, quote: str, start: float, end: float,
             role: str = "fact", notes: str | None = None) -> EvidenceSegment:
    return EvidenceSegment(
        segment_id=f"{transcript_id}.seg-{index}",
        role_in_argument=role,
        audio_offset_start=start,
        audio_offset_end=end,
        speaker="passenger",
        verbatim_es=quote,
        verbatim_sha256="a" * 64,
        translation_en=f"EN {quote}",
        transcription_notes=notes,
        source_uri=f"data/transcripts/json/{transcript_id}.json#seg-{index}",
        source_sha256="b" * 64,
    )


def _violation(*segments: EvidenceSegment) -> Violation:
    return Violation(
        violation_id=VID,
        title="t",
        severity="LOW",
        incident=Incident(date="2024-07-05", location="Santiago"),
        schema_version="4.0",
        segments=list(segments),
    )


def _manifest(bundle: Path, rows: list[dict], files: dict[str, str]) -> Path:
    path = bundle / "segments_manifest.json"
    path.write_text(json.dumps({
        "schema_version": "4.0",
        "violation_id": VID,
        "matched_audio_sources": sorted(files),
        "total_segments_matched": len(rows),
        "segments": rows,
        "clip_offset_deltas": {"a": 0.5},
        "transcript_files": files,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _converted_row(transcript_id: str, index: int, legacy: str) -> dict:
    """A row as the converter writes it: text de-accented, offsets re-anchored."""
    return {
        "segment_id": f"{transcript_id}.seg-{index}",
        "legacy_segment_id": legacy,
        "role_in_argument": "fact",
        "audio_offset_start": 1.0,
        "audio_offset_end": 4.0,
        "verbatim_es": "convertida",
        "translation_en": "converted",
        "transcription_notes": "reanchored from STG-1.seg-7 (method=text, confidence=high)",
    }


def _drifted(tmp_path: Path) -> tuple[Path, Violation]:
    """The state CL-030 is in: two S2 segments the manifest never heard of.

    Reproduces it faithfully — the converted row exists, the two later segments
    do not, and one of the later segments comes from a transcript the bundle has
    never carried.
    """
    _write_corpus(tmp_path, PRE_BOARDING)
    bundle = _bundle(tmp_path, link=PRE_BOARDING)
    _manifest(
        bundle,
        [_converted_row(PRE_BOARDING, 1, "STG-1.seg-7")],
        {PRE_BOARDING: f"{PRE_BOARDING}.json"},
    )
    violation = _violation(
        _segment(PRE_BOARDING, 1, "convertida", 1.0, 4.0),
        _segment(PRE_BOARDING, 3, "Da onde que ele chegou eu nao sei", 22.7, 27.3),
        _segment(JETBRIDGE, 12, "Ya activamos seguridad", 50.0, 52.0),
    )
    write_violation_json(violation, bundle)
    return bundle, violation


# ---------------------------------------------------------------------------
# What the checks the pack already trusts say
# ---------------------------------------------------------------------------

def test_the_preflight_checks_reject_the_drifted_bundle(tmp_path, preflight):
    """The control. A green "the checks pass" test proves nothing until the same
    checks have been seen to fail on the state this module exists to repair."""
    bundle, _ = _drifted(tmp_path)
    segment_errors = preflight.check_bundle_segments(tmp_path / "build", VID)
    assert segment_errors and "disagree" in segment_errors[0]

    # check_transcripts reads the *manifest*, so the drift is invisible to it: it
    # sees the one segment the converter recorded and nothing about the two the
    # violation added. Both halves of the shape are asserted, because "no errors"
    # here is the honest reading of a half-written bundle, not a check that works.
    errors, found, _ = preflight.check_transcripts(
        bundle / "segments_manifest.json", bundle / "Transcripts"
    )
    assert errors == []
    assert len(found) == 1, "the manifest names one transcript; the violation cites two"


def test_the_transcripts_check_rejects_a_manifest_its_files_cannot_cover(tmp_path, preflight):
    """The other half of the control: what that check *does* catch, and therefore
    what the sync has to guarantee against — a manifest promising an index its
    transcript does not have."""
    bundle, _ = _drifted(tmp_path)
    _manifest(
        bundle,
        [_converted_row(PRE_BOARDING, 3, "STG-1.seg-9")],
        {PRE_BOARDING: f"{PRE_BOARDING}.json"},
    )
    link = bundle / "Transcripts" / f"{PRE_BOARDING}.json"
    doc = json.loads(link.read_text(encoding="utf-8"))
    doc["segments"] = [s for s in doc["segments"] if s["index"] == 1]
    link.unlink()  # through the symlink would rewrite the shared corpus
    link.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

    errors, _, _ = preflight.check_transcripts(
        bundle / "segments_manifest.json", bundle / "Transcripts"
    )

    assert errors, "the check must report a promised index the transcript lacks"
    assert "missing referenced segment index" in errors[0]


def test_the_preflight_checks_accept_the_synced_bundle(tmp_path, preflight):
    """The point of the whole module: one write, and the checks the pipeline
    gates on go green."""
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    assert preflight.check_bundle_segments(tmp_path / "build", VID) == []
    errors, found, _ = preflight.check_transcripts(
        bundle / "segments_manifest.json", bundle / "Transcripts"
    )
    assert errors == []
    assert len(found) == 2, "both cited transcripts must be in the bundle now"


# ---------------------------------------------------------------------------
# The manifest
# ---------------------------------------------------------------------------

def test_the_manifest_row_set_is_the_violations_row_set(tmp_path):
    bundle, violation = _drifted(tmp_path)
    summary = sync_segment_artifacts(violation, bundle)
    manifest = json.loads((bundle / "segments_manifest.json").read_text(encoding="utf-8"))

    assert {r["segment_id"] for r in manifest["segments"]} == {
        s.segment_id for s in violation.segments
    }
    assert manifest["total_segments_matched"] == 3 == summary["manifest_segments"]
    assert manifest["matched_audio_sources"] == sorted([PRE_BOARDING, JETBRIDGE])
    assert manifest["violation_id"] == VID
    assert summary["manifest_changed"] is True


def test_a_legacy_id_is_carried_over_and_never_invented(tmp_path):
    """``STG-1.seg-7`` states where the re-anchor came from. No live artifact
    still knows it, so the copy on disk is the only source there is."""
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    manifest = json.loads((bundle / "segments_manifest.json").read_text(encoding="utf-8"))
    legacy = {r["segment_id"]: r["legacy_segment_id"] for r in manifest["segments"]}
    assert legacy[f"{PRE_BOARDING}.seg-1"] == "STG-1.seg-7"
    assert legacy[f"{PRE_BOARDING}.seg-3"] == ""
    assert legacy[f"{JETBRIDGE}.seg-12"] == ""


def test_the_manifest_keeps_the_converters_own_fields(tmp_path):
    """``schema_version`` and ``clip_offset_deltas`` describe the conversion, not
    this run. Dropping them would silently discard the per-clip drift correction."""
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    manifest = json.loads((bundle / "segments_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "4.0"
    assert manifest["clip_offset_deltas"] == {"a": 0.5}
    row = next(r for r in manifest["segments"] if r["segment_id"].endswith("seg-3"))
    assert list(row) == list(_converted_row(PRE_BOARDING, 1, "x")), (
        "the manifest row's field order is the converter's contract"
    )


def test_transcript_files_names_exactly_the_files_on_disk(tmp_path):
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    manifest = json.loads((bundle / "segments_manifest.json").read_text(encoding="utf-8"))
    tmap = manifest["transcript_files"]
    assert sorted(tmap) == sorted([PRE_BOARDING, JETBRIDGE])
    for transcript_id, name in tmap.items():
        assert (bundle / "Transcripts" / name).is_file(), name
        assert name == f"{transcript_id}.json"


# ---------------------------------------------------------------------------
# The transcripts
# ---------------------------------------------------------------------------

def test_the_bundle_transcript_holds_only_the_cited_segments(tmp_path):
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    doc = json.loads((bundle / "Transcripts" / f"{PRE_BOARDING}.json").read_text(encoding="utf-8"))

    assert [s["index"] for s in doc["segments"]] == [1, 3]
    # Text and offsets come from the violation, so the file cannot disagree with
    # the segment V02 matches its quote against.
    assert [s["text"] for s in doc["segments"]] == ["convertida", "Da onde que ele chegou eu nao sei"]
    assert (doc["segments"][1]["start"], doc["segments"][1]["end"]) == (22.7, 27.3)
    assert doc["segments"][1]["duration"] == pytest.approx(4.6)
    # …but the review metadata the corpus already carried is kept, so the subset
    # is not a degraded stand-in for the transcript it came from.
    assert doc["segments"][1]["segment_datetime"] == "2024-07-05T13:33:03.000"
    assert doc["title"] == "Pre-Boarding"
    assert doc["case_id"] == "I-002"
    assert doc["participants"] == ["passenger", "pilot"]
    assert doc["language"] == "pt"
    assert doc["transcript_id"] == PRE_BOARDING


def test_the_subset_says_what_it_is_and_how_much_is_missing(tmp_path):
    """A file that holds 2 of 6 segments while calling itself the transcript is a
    silent evidence problem; the marker is what makes the omission visible."""
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    doc = json.loads((bundle / "Transcripts" / f"{PRE_BOARDING}.json").read_text(encoding="utf-8"))
    marker = doc["metadata"]["violation_refiner_subset"]
    assert marker["violation_id"] == VID
    assert marker["segments"] == ["seg-1", "seg-3"]
    assert marker["source_segment_count"] == 6
    assert doc["metadata"]["imported_by"] == "test", "the corpus metadata was replaced, not merged"


def test_a_linked_transcript_is_replaced_never_written_through(tmp_path):
    """The bundle's transcript is a symlink into the shared corpus. Writing the
    subset through it would rewrite ``data/transcripts/json/<id>.json`` for every
    bundle in the workspace at once."""
    corpus = _write_corpus(tmp_path, PRE_BOARDING)
    before = hashlib.sha256(corpus.read_bytes()).hexdigest()
    bundle, violation = _drifted(tmp_path)
    link = bundle / "Transcripts" / f"{PRE_BOARDING}.json"
    assert link.is_symlink()

    sync_segment_artifacts(violation, bundle)

    assert not link.is_symlink(), "the subset overwrote the corpus through the link"
    assert "violation_refiner_subset" in link.read_text(encoding="utf-8")
    assert hashlib.sha256(corpus.read_bytes()).hexdigest() == before


def test_a_transcript_added_in_s2_is_written_into_the_bundle(tmp_path):
    """The segment the converter never saw names the corpus, not the bundle, so
    its transcript has to be created rather than found."""
    bundle, violation = _drifted(tmp_path)
    assert not (bundle / "Transcripts" / f"{JETBRIDGE}.json").exists()
    sync_segment_artifacts(violation, bundle)
    doc = json.loads((bundle / "Transcripts" / f"{JETBRIDGE}.json").read_text(encoding="utf-8"))
    assert [s["index"] for s in doc["segments"]] == [12]
    assert doc["segments"][0]["text"] == "Ya activamos seguridad"


# ---------------------------------------------------------------------------
# Idempotence and the edges
# ---------------------------------------------------------------------------

def test_a_second_run_writes_nothing_at_all(tmp_path):
    """The persistence block calls this on every tool run, so a rewrite that is
    not needed would churn mtimes and invalidate MANIFEST.txt for no reason."""
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    touched = {
        p: p.stat().st_mtime_ns
        for p in [bundle / "segments_manifest.json", *(bundle / "Transcripts").iterdir()]
    }

    summary = sync_segment_artifacts(violation, bundle)

    assert summary["manifest_changed"] is False
    assert [t["changed"] for t in summary["transcripts"]] == [False, False]
    assert {p: p.stat().st_mtime_ns for p in touched} == touched


def test_a_violation_with_no_segments_leaves_the_bundle_alone(tmp_path):
    """A pack that cites no audio is legitimate, and emptying its manifest would
    report that as a run that removed 40 segments."""
    bundle, _ = _drifted(tmp_path)
    before = (bundle / "segments_manifest.json").read_bytes()

    summary = sync_segment_artifacts({"violation_id": VID, "segments": []}, bundle)

    assert summary["manifest_changed"] is False
    assert summary["transcripts"] == []
    assert (bundle / "segments_manifest.json").read_bytes() == before
    assert summary["warnings"], "silently keeping a manifest the violation contradicts"


def test_a_segment_from_the_vendored_render_is_kept_and_flagged_sourceless(
    tmp_path, preflight
):
    """``STG-7.seg-44`` is a real id — the vendored HTML render names its rows that
    way — and a pack that cites one without ever being converted still has to end
    up with a manifest that agrees with it. What must not happen is the file
    quietly claiming to be the transcript of ``STG-7``: there is no such
    transcript to read, so the subset says so and the warning is raised."""
    bundle, _ = _drifted(tmp_path)
    scoped = EvidenceSegment(
        segment_id="STG-7.seg-44",
        role_in_argument="fact",
        audio_offset_start=0.0,
        audio_offset_end=1.0,
        speaker="SPK",
        verbatim_es="x",
        verbatim_sha256="a" * 64,
        translation_en="",
        source_uri="Transcripts/timeline_aeropuerto_STG_7.html#seg-44",
        source_sha256="b" * 64,
    )
    violation = _violation(_segment(PRE_BOARDING, 1, "convertida", 1.0, 4.0), scoped)

    summary = sync_segment_artifacts(violation, bundle)
    write_violation_json(violation, bundle)

    manifest = json.loads((bundle / "segments_manifest.json").read_text(encoding="utf-8"))
    assert {r["segment_id"] for r in manifest["segments"]} == {
        f"{PRE_BOARDING}.seg-1", "STG-7.seg-44",
    }
    assert preflight.check_bundle_segments(tmp_path / "build", VID) == []
    assert any(
        w.startswith("STG-7: no full transcript was found") for w in summary["warnings"]
    ), summary["warnings"]
    written = json.loads((bundle / "Transcripts" / "STG-7.json").read_text(encoding="utf-8"))
    assert written["metadata"]["violation_refiner_subset"]["source_segment_count"] is None, (
        "'how much of the full transcript is missing' is unknown here, and None is how "
        "unknown is written down"
    )


def test_a_segment_id_that_is_not_scoped_to_a_transcript_is_skipped(tmp_path, preflight):
    """``SEG-44`` names no transcript at all. Filing it under one would be a guess,
    so it is reported and left out — and because it is left out, the bundle's
    ids cannot be made to agree, which is the visible state the pre-flight reports
    rather than one the sync papers over."""
    bundle, _ = _drifted(tmp_path)
    unscoped = EvidenceSegment(
        segment_id="SEG-44",
        role_in_argument="fact",
        audio_offset_start=0.0,
        audio_offset_end=1.0,
        speaker="SPK",
        verbatim_es="x",
        verbatim_sha256="a" * 64,
        translation_en="",
        source_uri="data/transcripts/json/SEG-44.json#seg-44",
        source_sha256="b" * 64,
    )
    violation = _violation(_segment(PRE_BOARDING, 1, "convertida", 1.0, 4.0), unscoped)

    summary = sync_segment_artifacts(violation, bundle)
    write_violation_json(violation, bundle)

    assert any("SEG-44" in w and "not '<transcript_id>" in w for w in summary["warnings"])
    manifest = json.loads((bundle / "segments_manifest.json").read_text(encoding="utf-8"))
    assert {r["segment_id"] for r in manifest["segments"]} == {f"{PRE_BOARDING}.seg-1"}
    errors = preflight.check_bundle_segments(tmp_path / "build", VID)
    assert errors and "disagree" in errors[0]


def test_a_violation_that_has_gone_back_to_the_legacy_ids_rewrites_nothing(tmp_path):
    """The reason the manifest is rebuilt from the violation and still cannot
    become a copy of it. A stale ``<VID>.json.bak`` makes the refiner load the
    vault's pre-re-anchor ids; rebuilding the manifest from those would let the
    drift overwrite the only record that the conversion happened, and
    ``check_bundle_segments`` would then agree with the wrong bundle forever."""
    bundle, _ = _drifted(tmp_path)
    before = (bundle / "segments_manifest.json").read_bytes()
    legacy = _violation(_segment(PRE_BOARDING, 1, "do cofre", 1.1, 3.9))
    legacy.segments[0].segment_id = "STG-1.seg-7"

    summary = sync_segment_artifacts(legacy, bundle)

    assert summary["manifest_changed"] is False
    assert summary["transcripts"] == [], "nothing is read from a bundle in that state"
    assert (bundle / "segments_manifest.json").read_bytes() == before
    assert any("STG-1.seg-7" in w for w in summary["warnings"])
    assert any(".bak" in w for w in summary["warnings"])


def test_an_uncited_transcript_is_reported_not_deleted(tmp_path):
    """Removing a segment must not take a reviewer's file with it behind their back."""
    bundle, violation = _drifted(tmp_path)
    sync_segment_artifacts(violation, bundle)
    stray = bundle / "Transcripts" / "I-002_09_NAR-99_old.json"
    stray.write_text("{}", encoding="utf-8")

    summary = sync_segment_artifacts(violation, bundle)

    assert stray.exists()
    assert any("I-002_09_NAR-99_old.json" in w for w in summary["warnings"])


# ---------------------------------------------------------------------------
# The write gate
# ---------------------------------------------------------------------------

def test_the_write_tool_is_what_keeps_them_in_step(tmp_path):
    """The side effect belongs to ``write_violation_json_tool``: it is the only
    tool in the pack that writes, and every build/verify tool above it returns an
    updated violation and touches nothing (V02 and the UI both depend on that)."""
    pytest.importorskip("mcp", reason="needs the [mcp] extra")
    from violation_pack.mcp_server import build_server

    bundle, violation = _drifted(tmp_path)
    server = build_server()
    result = asyncio.run(server._tool_manager.call_tool(
        "write_violation_json_tool",
        {"violation": json.loads(violation.model_dump_json()), "bundle_root": str(bundle)},
    ))

    assert result["path"] == str(bundle / f"{VID}.json")
    assert result["manifest_changed"] is True
    assert result["manifest_segments"] == 3
    assert sorted(t["transcript_id"] for t in result["transcripts"]) == sorted(
        [PRE_BOARDING, JETBRIDGE]
    )
    manifest = json.loads((bundle / "segments_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["segments"]) == 3


def _called_name(func: ast.expr) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _own_nodes(fn: ast.FunctionDef | ast.AsyncFunctionDef):
    """The nodes written in ``fn`` itself, not in a function it defines.

    ``mcp_server.build_server`` is one function containing all 39 tool
    definitions, so a plain ``ast.walk`` sees every tool's body as its own and
    nothing can be attributed to a tool by name.
    """
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _functions(pack_dir: Path):
    for path in sorted(pack_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield path.name, fn


def _violation_writers(pack_dir: Path) -> dict[str, list[int]]:
    """Every function in ``pack_dir`` that serializes a Violation to disk.

    Two shapes count, because both exist: calling the primitive
    (``write_violation_json``, however it is aliased) and dumping the model
    straight to a file (``path.write_text(v.model_dump_json(...))``). The
    primitive itself is not a "writer" in this sense — it is the thing the
    callers use, and it has no bundle context to reconcile with.

    ``examples/vault_to_bundle.py`` is deliberately out of scope: the converter
    is what *establishes* ``segments_manifest.json``, so its manifest is the
    independent record of the conversion and must never be rebuilt from the
    violation it just wrote (that is the whole point of the legacy-id guard).
    """
    writers: dict[str, list[int]] = {}
    for name, fn in _functions(pack_dir):
        if name == "pack.py" and fn.name == "write_violation_json":
            continue
        writes = [
            node.lineno
            for node in _own_nodes(fn)
            if isinstance(node, ast.Call)
            and (
                "write_violation_json" in _called_name(node.func)
                or (
                    _called_name(node.func) in ("write_text", "write_bytes")
                    and "model_dump_json" in ast.unparse(node)
                )
            )
        ]
        if writes:
            writers[f"{name}::{fn.name}"] = writes
    return writers


def _synced_writers(pack_dir: Path) -> set[str]:
    """The writers that call the sync, keyed the same way."""
    synced: set[str] = set()
    for name, fn in _functions(pack_dir):
        if any(
            isinstance(node, ast.Call) and "sync_segment_artifacts" in _called_name(node.func)
            for node in _own_nodes(fn)
        ):
            synced.add(f"{name}::{fn.name}")
    return synced


def test_every_writer_of_a_violation_reconciles_the_derived_artifacts():
    """A frozen inventory of the functions that can leave a bundle's manifest
    and Transcripts/ describing an older generation of the violation.

    This is the bug this module exists for, so it is pinned: a third writer must
    fail here rather than be discovered as drift three months later. Freezing
    the names is the point — the assertion is meant to need an edit.
    """
    pack_dir = REPO_ROOT / "violation_pack"
    writers = _violation_writers(pack_dir)
    assert set(writers) == {
        "mcp_server.py::write_violation_json_tool",
        "refine_batch_core.py::_process_one",
    }, f"a new violation writer appeared — does it sync? {sorted(_synced_writers(pack_dir))}"
    assert set(writers) <= _synced_writers(pack_dir)


def test_the_writer_guard_can_fail(tmp_path):
    """Prove the guard above is loadable against a broken tree.

    ``refine_batch_core._process_one`` writes the violation JSON directly, so
    deleting its sync line is exactly the regression to catch. Verified on a
    copy: the guard must name the function that now writes without reconciling.
    """
    import shutil

    pack_dir = tmp_path / "violation_pack"
    shutil.copytree(
        REPO_ROOT / "violation_pack",
        pack_dir,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    target = pack_dir / "refine_batch_core.py"
    source = target.read_text(encoding="utf-8")
    mutated = source.replace(
        "    sync = sync_segment_artifacts(v, bundle_dir)\n"
        "    notes.extend(f\"segment_sync: {w}\" for w in sync[\"warnings\"])\n",
        "",
    )
    assert mutated != source, "the sync block moved — update this mutation to match"
    target.write_text(mutated, encoding="utf-8")

    writers = _violation_writers(pack_dir)
    assert "refine_batch_core.py::_process_one" in writers
    assert "refine_batch_core.py::_process_one" not in _synced_writers(pack_dir)
    # The inventory test's own failure condition, reproduced: a writer that is
    # not in the synced set. Without this the guard could be green and toothless.
    assert set(writers) - _synced_writers(pack_dir) == {"refine_batch_core.py::_process_one"}
