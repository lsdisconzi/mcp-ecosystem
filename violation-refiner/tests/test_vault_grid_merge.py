"""One article must yield exactly one ``element_grids`` entry.

A vault document can hold **two** grid keys that canonicalize to the same
``article_id``. The corpus does: ``CL-013`` carries ``CL.CPCL.C1.Art.412``
(8 elements, *including* ``modalidad_tipica``) alongside the mis-prefixed
``CL.CPCL.T2.P6.Art.412`` (7 elements, *without* it) for the same article, and
``build_violation_document`` rewrites both prefixes onto the established
spelling.

The converter used to *append* both, leaving two ``element_grids`` entries that
share one ``article_id``. Everything downstream that indexes grids by article
then resolved against whichever entry happened to come first, so:

* V11 ``enrichment_integrity`` failed with ``E_NEXUS_UNKNOWN_ELEMENT`` for
  ``CL.CPCL.C1.Art.412.elem.modalidad_tipica`` — an element the *other* copy
  carried; and
* V21 ``element_id_closure`` reported ``CL.CPCL.C1.Art.412`` **twice**, once
  per duplicate entry.

Measured on the seeded corpus (``data/violations``) before the fix — 7 of 80
documents were affected::

    BR-001 {BR.CDC.T3.Art.6.IV: 2, BR.CDC.T5.C4.Art.39.II: 2}
    BR-005 {BR.CDC.T5.C4.Art.39: 5}
    BR-006 {BR.CDC.T2.Art.4: 3, BR.CDC.T5.C5.Art.42: 2}
    BR-010 {BR.CDC.T5.C4.Art.39: 3}
    CL-013 {CL.CPCL.C1.Art.412: 2}
    CL-017 {CL.CPCL.T2.P6.Art.412: 2}
    CL-023 {CL.CPCL.C1.Art.412: 2}

The corpus half of this module is skipped where ``data/violations`` has not been
seeded (it is untracked); the unit half always runs.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
VIOLATIONS_DIR = DATA_DIR / "violations"


def _load_example_module(name: str, path: Path):
    """Import a module from ``examples/`` (which is not a package)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def converter():
    return _load_example_module(
        "vault_to_bundle", REPO_ROOT / "examples" / "vault_to_bundle.py"
    )


@pytest.fixture(scope="module")
def converter_runtime(converter):
    """The transcript index and law resolver ``main`` builds, built once."""
    transcripts = converter.build_transcript_index(converter.DEFAULT_TRANSCRIPT_DIR)
    resolver = converter.FrameworkResolver(converter.DEFAULT_LAW_ROOT)
    return transcripts, resolver


def _duplicate_article_ids(bundle_json: Path) -> dict[str, int]:
    """``{article_id: count}`` for every article the grid lists more than once."""
    grid = json.loads(bundle_json.read_text(encoding="utf-8"))["element_grids"]
    counts: dict[str, int] = {}
    for entry in grid:
        counts[entry["article_id"]] = counts.get(entry["article_id"], 0) + 1
    return {article_id: n for article_id, n in counts.items() if n > 1}


# ---------------------------------------------------------------------------
# The merge primitive
# ---------------------------------------------------------------------------

def _element(element_id: str, status: str = "strong", evidence=(), **extra):
    base = {
        "element_id": element_id,
        "label": "",
        "doctrinal_basis": None,
        "proof_status": status,
        "proof_evidence_segments": list(evidence),
        "argument_es": "",
        "weaknesses": [],
        "open_questions": [],
    }
    base.update(extra)
    return base


def test_merge_unions_element_ids_without_duplicating_them(converter):
    """A new element is added; an element present in both is not duplicated."""
    target = {"article_id": "A", "elements": [_element("A.elem.one")]}

    added, upgraded = converter._merge_grid_elements(
        target, [_element("A.elem.one"), _element("A.elem.two")]
    )

    assert added == 1
    assert upgraded == 0
    assert [e["element_id"] for e in target["elements"]] == [
        "A.elem.one",
        "A.elem.two",
    ]


def test_merge_upgrades_a_placeholder_status_only(converter):
    """``not_developed`` is replaced by a real status; two real ones keep the first."""
    target = {
        "article_id": "A",
        "elements": [
            _element("A.elem.placeholder", status="not_developed"),
            _element("A.elem.contested", status="contested"),
        ],
    }

    added, upgraded = converter._merge_grid_elements(
        target,
        [
            _element("A.elem.placeholder", status="established"),
            _element("A.elem.contested", status="strong"),
        ],
    )

    assert added == 0
    assert upgraded == 1
    by_id = {e["element_id"]: e for e in target["elements"]}
    assert by_id["A.elem.placeholder"]["proof_status"] == "established"
    # Both are real statuses, so the first-seen (canonical grid) opinion stands.
    assert by_id["A.elem.contested"]["proof_status"] == "contested"


def test_merge_unions_evidence_without_duplicating_rows(converter):
    """Evidence is a union, and the shared segment is not listed twice."""
    target = {
        "article_id": "A",
        "elements": [_element("A.elem.one", evidence=["seg-1", "seg-2"])],
    }

    converter._merge_grid_elements(
        target, [_element("A.elem.one", evidence=["seg-2", "seg-3"])]
    )

    assert target["elements"][0]["proof_evidence_segments"] == [
        "seg-1",
        "seg-2",
        "seg-3",
    ]


def test_merge_fills_blank_text_fields_and_keeps_real_ones(converter):
    """A blank label/argument is filled from the other copy; a real one is kept."""
    target = {
        "article_id": "A",
        "elements": [
            _element("A.elem.blank", label="", argument_es=""),
            _element("A.elem.named", label="Canonical label", argument_es="Kept"),
        ],
    }

    converter._merge_grid_elements(
        target,
        [
            _element("A.elem.blank", label="Recovered", argument_es="Recovered too"),
            _element("A.elem.named", label="Other label", argument_es="Other argument"),
        ],
    )

    by_id = {e["element_id"]: e for e in target["elements"]}
    assert by_id["A.elem.blank"]["label"] == "Recovered"
    assert by_id["A.elem.blank"]["argument_es"] == "Recovered too"
    assert by_id["A.elem.named"]["label"] == "Canonical label"
    assert by_id["A.elem.named"]["argument_es"] == "Kept"


# ---------------------------------------------------------------------------
# The real corpus
# ---------------------------------------------------------------------------

#: Measured duplicate counts on the seeded corpus before the fix; the two
#: CL ids resolve one display prefix onto the other, which is why CL-017
#: reports the T2.P6 spelling while CL-013 and CL-023 report the C1 one.
@pytest.mark.skipif(
    not VIOLATIONS_DIR.is_dir(), reason="data/violations has not been seeded"
)
def test_no_seeded_document_converts_to_a_duplicate_article_id(
    converter, converter_runtime, tmp_path
):
    """Every seeded vault document yields one grid per article, and none is lost."""
    transcripts, resolver = converter_runtime
    documents = sorted(VIOLATIONS_DIR.glob("*.json"))
    assert documents, "data/violations holds no JSON documents"

    offenders: dict[str, dict[str, int]] = {}
    converted = 0
    for path in documents:
        bundle_dir, _warnings = converter.convert_one(
            path,
            tmp_path,
            transcripts,
            resolver,
            law_root=converter.DEFAULT_LAW_ROOT,
            transcript_dir=converter.DEFAULT_TRANSCRIPT_DIR,
            speaker_index=converter.DEFAULT_SPEAKER_INDEX,
        )
        bundle_json = bundle_dir / f"{bundle_dir.name}.json"
        if not bundle_json.is_file():
            continue
        converted += 1
        duplicates = _duplicate_article_ids(bundle_json)
        if duplicates:
            offenders[path.stem] = duplicates

    assert converted >= 70, f"only {converted} documents converted; the corpus moved"
    assert offenders == {}, f"duplicate article_id in element_grids: {offenders}"


@pytest.mark.skipif(
    not (VIOLATIONS_DIR / "CL-013.json").is_file(),
    reason="data/violations has not been seeded",
)
def test_cl013_article_412_grid_keeps_the_element_only_one_copy_carries(
    converter, converter_runtime, tmp_path
):
    """The regression V11 caught: ``modalidad_tipica`` must survive the merge."""
    transcripts, resolver = converter_runtime
    bundle_dir, _warnings = converter.convert_one(
        VIOLATIONS_DIR / "CL-013.json",
        tmp_path,
        transcripts,
        resolver,
        law_root=converter.DEFAULT_LAW_ROOT,
        transcript_dir=converter.DEFAULT_TRANSCRIPT_DIR,
        speaker_index=converter.DEFAULT_SPEAKER_INDEX,
    )
    grid = json.loads(
        (bundle_dir / "CL-013.json").read_text(encoding="utf-8")
    )["element_grids"]

    grids = [g for g in grid if g["article_id"] == "CL.CPCL.C1.Art.412"]
    assert len(grids) == 1, f"expected one C1.Art.412 grid, got {len(grids)}"

    element_ids = {e["element_id"] for e in grids[0]["elements"]}
    assert "CL.CPCL.C1.Art.412.elem.modalidad_tipica" in element_ids
    # The elements the mis-prefixed copy contributed under the canonical id.
    assert "CL.CPCL.C1.Art.412.elem.dolo" in element_ids
    assert len(element_ids) == 8


@pytest.mark.skipif(
    not (VIOLATIONS_DIR / "CL-013.json").is_file(),
    reason="data/violations has not been seeded",
)
def test_every_blocks_element_names_an_element_the_grids_actually_carry(
    converter, converter_runtime, tmp_path
):
    """V11's remainder: ``blocks_element`` must follow the grid prefix rewrite.

    The grid pass canonicalizes a mis-prefixed article onto the established
    spelling. A question that blocks an element by its *old* prefix then names
    an element_id no grid carries, and V11 reports ``W_OQ_BLOCKS_UNKNOWN``:

        blocks_element 'CL.CPCL.T2.P6.Art.412.elem.sujeto_activo' is not a
        known element_id
    """
    transcripts, resolver = converter_runtime
    bundle_dir, _warnings = converter.convert_one(
        VIOLATIONS_DIR / "CL-013.json",
        tmp_path,
        transcripts,
        resolver,
        law_root=converter.DEFAULT_LAW_ROOT,
        transcript_dir=converter.DEFAULT_TRANSCRIPT_DIR,
        speaker_index=converter.DEFAULT_SPEAKER_INDEX,
    )
    document = json.loads(
        (bundle_dir / "CL-013.json").read_text(encoding="utf-8")
    )

    known = {
        e["element_id"]
        for grid in document["element_grids"]
        for e in grid["elements"]
    }
    blocking = [
        oq["blocks_element"]
        for oq in document["open_questions"]
        if oq.get("blocks_element")
    ]
    assert blocking, "expected some open questions to block an element"
    unknown = sorted(b for b in blocking if b not in known)
    assert unknown == [], f"blocks_element names an unknown element_id: {unknown}"
