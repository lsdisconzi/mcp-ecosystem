"""The bundle's contract is a *view* of its violation, and must say what it holds.

``contract.json`` is written once by ``examples/vault_to_bundle.py``, and was then
maintained by a reconciler that rewrote only the four fields V08 and V17 compare.
``legal_basis`` was left as the vault wrote it on purpose — "the record of what
the vault said" — so a bundle could publish an article as
``status: "established"`` with an empty ``article_text`` while the violation
stored beside it held that same article as a *candidate*. V08 compares
``established_article_ids`` only, so the two lists contradicting each other
inside one file was invisible to every check.

These tests drive the projection against a contract in exactly that shape, and
then against the two checks that read it — on both states. The drifted contract
must fail them and the projected one must pass them: a check that has never been
seen to fail proves nothing about the projection.
"""
from __future__ import annotations

import ast
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from violation_pack.models import (
    CachedArticle,
    CandidateArticle,
    ConfidenceDerivation,
    CrossReference,
    FrameworkCache,
    Incident,
    OpenQuestion,
    Violation,
)
from violation_pack.pack import (
    CONTRACT_PROJECTED_KEYS,
    CONTRACT_VAULT_ONLY_KEYS,
    bundle_path,
    project_contract,
    reconcile_contract,
    write_violation_json,
)
from violation_pack.validation import v08_contract_consistency, v17_cross_view_consistency

REPO_ROOT = Path(__file__).parent.parent
VID = "CL-900"

# The article the vault converter published as established and the violation
# holds as a candidate — the CL-030 shape, which is why this is the id under test.
CANDIDATE_AS_ESTABLISHED = "CL.CPEL.C1.Art.269_ter"
CPCL_ARTICLE = "CL.CPCL.T4.Art.255"
LPDC_ARTICLE = "CL.LPDC.Art.23"

INCIDENT = Incident(
    date="2024-07-05",
    location="Santiago Airport (SCL), Chile",
    flight="LA8159",
    operator="LATAM Airlines",
    clock_time_estimate="2024-07-05T13:30:00-04:00",
    clock_time_confidence="unknown",
)


# ---------------------------------------------------------------------------
# Fixtures: a violation, and the contract the vault wrote about an older one
# ---------------------------------------------------------------------------

def _article(article_id: str, code: str, text: str) -> CachedArticle:
    return CachedArticle(
        article_id=article_id,
        article_name=f"Name of {article_id}",
        subsections_invoked=["1"],
        verbatim_excerpt=text,
        verbatim_excerpt_sha256="a" * 64,
        framework_code=code,
        framework_cache_status="verified_in_bundle",
        duty_bearer="state",
        norm_type="definition",
        applicability="supporting",
        applicability_rationale=f"why {article_id} applies",
    )


def _violation() -> Violation:
    """The bundle as the UI leaves it: retitled, re-scored, and holding one fewer
    established article than the contract still claims."""
    return Violation(
        violation_id=VID,
        title="Título editado en la UI",
        severity="HIGH",
        schema_version="3.0",
        incident=INCIDENT,
        framework_caches=[
            FrameworkCache(
                framework_code="CPCL",
                framework_name="CPCL",
                cache_file="Legal framework/CPCL.md",
                cache_file_sha256="b" * 64,
                articles_cached=["255"],
            ),
            FrameworkCache(
                framework_code="LPDC",
                framework_name="LPDC",
                cache_file="Legal framework/LPDC.md",
                cache_file_sha256="c" * 64,
                articles_cached=["23"],
            ),
        ],
        established_articles=[
            _article(CPCL_ARTICLE, "CPCL", "El empleado público que abusare…"),
            _article(LPDC_ARTICLE, "LPDC", "Las empresas de transporte aéreo…"),
        ],
        candidate_articles=[
            CandidateArticle(
                candidate_article_id=CANDIDATE_AS_ESTABLISHED,
                candidate_name="Obstrucción a la investigación",
                framework_cache_status="not_in_bundle",
                verification_required=["fetch the verbatim text"],
                preliminary_view=None,
                history_note=None,
            )
        ],
        confidence=ConfidenceDerivation(
            value=0.57,
            components={CPCL_ARTICLE: 0.68, LPDC_ARTICLE: 0.65},
            authorities_verification_factor=1.0,
            derivation_formula="min(components)",
            derived_at="2026-09-17T07:47:22Z",
        ),
        open_questions=[
            OpenQuestion(
                id="OQ-900-A",
                question="¿Participó un empleado público?",
                blocks_element="el.elem.1",
                priority="critical",
                obtaining_method="ask the operator",
            )
        ],
        cross_references=[CrossReference(ref="CL-001", relation="predicate")],
    )


def _contract() -> dict:
    """A contract in the converter's shape, drifted from the violation above.

    Every mismatch here is one the old reconciler could not remove: the title,
    the severity, the confidence and ``established_article_ids`` are compared by
    V08; the article lists and the open-question wording are what a reader of the
    contract actually sees.
    """
    return {
        "schema_version": "4.0",
        "violation_id": VID,
        "violation_number": VID,
        "title": "Título del vault",
        "case": {"id": "I-002", "name": "Caso LA8159"},
        "jurisdiction": "CL",
        "framework": {
            "codes": ["CPCL", "LPDC"],
            "files": {"CPCL": "CL/CodigoPenal.md", "LPDC": "CL/L19496_LPDC.md"},
        },
        "category": "air_operator_misconduct",
        "severity": "LOW",
        "confidence": {
            "value": 0.31,
            "components": {},
            "authorities_verification_factor": 0.46,
            "derivation_formula": "old formula",
            "derived_at": "2026-09-17T02:44:30Z",
            "history": [],
        },
        "incident": {
            "date": "2024-07-05",
            "location": "Santiago Airport (SCL), Chile",
            "flight": "LA8159",
            "operator": "LATAM Airlines",
            "clock_time_estimate": "2024-07-05T13:30:00-04:00",
            "clock_time_confidence": "unknown",
        },
        "incident_timestamp": "2024-07-05T13:30:00-04:00",
        "incident_timestamp_display": "2024-07-05",
        "allegation_summary": "El pasajero fue removido del vuelo.",
        "legal_basis": {
            "frameworks": [
                {
                    "framework_code": "CPCL",
                    "framework_name": "CPCL",
                    "framework_file": "CL/CodigoPenal.md",
                    "articles": [
                        # Published as established, with nothing behind it: the
                        # article is a candidate in the violation.
                        {
                            "article_id": CANDIDATE_AS_ESTABLISHED,
                            "article_name": CANDIDATE_AS_ESTABLISHED,
                            "article_text": "",
                            "applicability_rationale": "",
                            "duty_bearer": "state",
                            "norm_type": "definition",
                            "applicability": "supporting",
                            "subsections_invoked": [],
                            "status": "established",
                        },
                        {
                            "article_id": CPCL_ARTICLE,
                            "article_name": "Art. 255",
                            "article_text": "legacy paraphrase",
                            "applicability_rationale": "legacy paraphrase",
                            "duty_bearer": "state",
                            "norm_type": "definition",
                            "applicability": "supporting",
                            "subsections_invoked": [],
                            "status": "established",
                        },
                    ],
                }
            ]
        },
        "candidate_articles": [],
        "cross_references": [{"ref": "CL-001", "relation": "stale relation"}],
        "open_questions": [
            {
                "id": "OQ-900-A",
                "question": "¿Participó un funcionario?",
                "blocks_element": "",
                "priority": "low",
            }
        ],
        "related_violations": ["CL-002"],
        "tags": ["tag-from-vault"],
        "_provenance": {
            "source": "vault/I-002.md",
            "vault_operations": 3,
            "converted_by": "examples/vault_to_bundle.py",
        },
        "_vault_confidence": 0.98,
        "established_article_ids": [CANDIDATE_AS_ESTABLISHED, CPCL_ARTICLE],
    }


def _bundle(tmp_path: Path, contract: dict | None = None) -> Path:
    bundle = tmp_path / "build" / VID
    bundle.mkdir(parents=True)
    if contract is not None:
        bundle_path(bundle, "contract", VID).write_text(
            json.dumps(contract, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return bundle


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------

def test_the_projection_replaces_the_fields_the_violation_determines():
    violation = _violation()

    out = project_contract(_contract(), violation)

    assert out["violation_id"] == VID
    assert out["violation_number"] == VID
    assert out["title"] == violation.title
    assert out["severity"] == violation.severity
    assert out["incident"] == json.loads(INCIDENT.model_dump_json())
    assert out["confidence"] == json.loads(violation.confidence.model_dump_json())
    assert out["established_article_ids"] == sorted([CPCL_ARTICLE, LPDC_ARTICLE])
    assert out["cross_references"] == [{"ref": "CL-001", "relation": "predicate"}]
    assert out["open_questions"] == [
        {
            "id": "OQ-900-A",
            "question": "¿Participó un empleado público?",
            "blocks_element": "el.elem.1",
            "priority": "critical",
        }
    ]
    assert [c["candidate_article_id"] for c in out["candidate_articles"]] == [
        CANDIDATE_AS_ESTABLISHED
    ]


def test_a_candidate_cannot_stay_published_as_an_established_article():
    """The CL-030 regression, at the level a reader of the contract sees it.

    The article is a candidate in the violation and "established" in the
    contract, which is exactly how one file came to assert two different legal
    bases for the same bundle.
    """
    violation = _violation()
    assert CANDIDATE_AS_ESTABLISHED not in {
        a.article_id for a in violation.established_articles
    }

    out = project_contract(_contract(), violation)

    published = [
        a["article_id"]
        for fw in out["legal_basis"]["frameworks"]
        for a in fw["articles"]
    ]
    assert published == [CPCL_ARTICLE, LPDC_ARTICLE]
    assert CANDIDATE_AS_ESTABLISHED not in published
    assert [c["candidate_article_id"] for c in out["candidate_articles"]] == [
        CANDIDATE_AS_ESTABLISHED
    ]


def test_article_text_is_the_excerpt_the_bundle_verified():
    """Not the vault's paraphrase, and never empty: the text a contract reader
    sees is the one V03 hashes and the framework cache holds."""
    out = project_contract(_contract(), _violation())

    articles = {
        a["article_id"]: a
        for fw in out["legal_basis"]["frameworks"]
        for a in fw["articles"]
    }
    assert articles[CPCL_ARTICLE]["article_text"] == "El empleado público que abusare…"
    assert articles[CPCL_ARTICLE]["applicability_rationale"] == f"why {CPCL_ARTICLE} applies"
    assert articles[CPCL_ARTICLE]["subsections_invoked"] == ["1"]
    assert all(a["status"] == "established" for a in articles.values())
    assert all(a["article_text"] for a in articles.values())


def test_the_frameworks_are_grouped_by_the_violation_and_keep_their_corpus_files():
    """The contract records a *corpus-relative* file (``CL/CodigoPenal.md``); the
    violation only knows a bundle-relative cache path (``Legal framework/CPCL.md``).
    Those are different namespaces, and getting it wrong is not cosmetic:
    ``examples/vault_to_bundle.py`` joins ``framework_file`` back onto the law
    corpus root on a re-read, so a bundle-relative path written here would make
    that pass fail to find the file and silently demote the framework's
    established articles to candidates.

    So the file travels over from the contract where the contract has it, and is
    recorded as unknown where it does not — never guessed from the cache path.
    """
    out = project_contract(_contract(), _violation())

    assert [fw["framework_code"] for fw in out["legal_basis"]["frameworks"]] == ["CPCL", "LPDC"]
    assert out["legal_basis"]["frameworks"][0]["framework_file"] == "CL/CodigoPenal.md"
    # This fixture's contract lists CPCL alone, yet the violation establishes an
    # LPDC article: the framework is in the contract now, its corpus file is not.
    assert out["legal_basis"]["frameworks"][1]["framework_file"] is None
    assert out["framework"] == {
        "codes": ["CPCL", "LPDC"],
        "files": {"CPCL": "CL/CodigoPenal.md", "LPDC": None},
    }
    # The framework *name* does come from the violation's cache when the contract
    # had no block for it.
    assert [fw["framework_name"] for fw in out["legal_basis"]["frameworks"]] == ["CPCL", "LPDC"]


def test_the_vault_only_fields_survive_the_projection():
    contract = _contract()

    out = project_contract(contract, _violation())

    for key in sorted(CONTRACT_VAULT_ONLY_KEYS):
        assert out[key] == contract[key], f"{key} is the vault's record, not a projection"
    assert out["schema_version"] == "4.0", (
        "the contract versions the vault document, the violation versions the "
        "bundle schema — they are not meant to agree"
    )


def test_a_key_the_projection_has_never_heard_of_is_left_alone():
    """A contract from a newer converter must not lose a field here."""
    contract = _contract()
    contract["something_new"] = {"kept": True}

    out = project_contract(contract, _violation())

    assert out["something_new"] == {"kept": True}


def test_no_confidence_in_the_violation_drops_the_key_rather_than_nulling_it():
    violation = _violation().model_copy(update={"confidence": None})

    out = project_contract(_contract(), violation)

    assert "confidence" not in out
    assert out["_vault_confidence"] == 0.98, "the vault's snapshot is still the vault's"


# ---------------------------------------------------------------------------
# What the two checks that read the contract say about it
# ---------------------------------------------------------------------------

def test_the_drifted_contract_fails_v08_and_v17_and_the_projected_one_passes():
    """The point of the change, asserted through the real checks: the projection
    has to be what turns a failing pair of views into an agreeing pair."""
    violation = _violation()
    drifted = _contract()

    before_08 = v08_contract_consistency(violation, {"contract": drifted})
    before_17 = v17_cross_view_consistency(violation, {"contract": drifted})
    assert before_08.status == "fail", before_08.details
    assert before_17.status in {"fail", "warn"}, before_17.details
    assert "established_articles set mismatch" in before_08.details

    projected = project_contract(drifted, violation)
    after_08 = v08_contract_consistency(violation, {"contract": projected})
    after_17 = v17_cross_view_consistency(violation, {"contract": projected})

    assert after_08.status == "pass", after_08.details
    assert after_17.status == "pass", after_17.details


# ---------------------------------------------------------------------------
# reconcile_contract: the file-level behaviour a writer depends on
# ---------------------------------------------------------------------------

def test_reconcile_contract_writes_the_projection_and_is_idempotent(tmp_path):
    bundle = _bundle(tmp_path, _contract())
    violation = _violation()

    first = reconcile_contract(bundle, violation)
    assert first["contract_changed"] is True
    assert first["contract_path"] == str(bundle / "contract.json")
    written = (bundle / "contract.json").read_bytes()

    second = reconcile_contract(bundle, violation)
    assert second["contract_changed"] is False, "a second write must change no bytes"
    assert (bundle / "contract.json").read_bytes() == written

    on_disk = json.loads(written.decode("utf-8"))
    assert on_disk["title"] == violation.title
    assert CANDIDATE_AS_ESTABLISHED not in on_disk["established_article_ids"]


def test_a_bundle_without_a_contract_is_left_without_one(tmp_path):
    """The contract is written by the vault converter. Inventing one here would
    publish a view for a bundle that never had one."""
    bundle = _bundle(tmp_path, None)

    result = reconcile_contract(bundle, _violation())

    assert result == {"contract_path": None, "contract_changed": False}
    assert not (bundle / "contract.json").exists()


def test_an_unparseable_contract_is_reported_not_raised(tmp_path):
    """This runs inside the write gate, after the violation JSON has landed. A
    corrupt optional artifact must not turn a completed write into a failure."""
    bundle = _bundle(tmp_path)
    (bundle / "contract.json").write_text("{not json", encoding="utf-8")

    result = reconcile_contract(bundle, _violation())

    assert result == {"contract_path": None, "contract_changed": False}
    assert (bundle / "contract.json").read_text(encoding="utf-8") == "{not json"


# ---------------------------------------------------------------------------
# The projection over the whole corpus
# ---------------------------------------------------------------------------

def _corpus_bundles() -> list[Path]:
    """Every bundle that has both halves of the pair, i.e. a violation and a
    contract. ``build/CL-0301`` has a contract but no ``CL-0301.json``, so it
    cannot be projected and is not a counterexample to anything here."""
    root = REPO_ROOT / "build"
    if not root.is_dir():
        return []
    return [
        d
        for d in sorted(p for p in root.iterdir() if p.is_dir())
        if bundle_path(d, "violation_main", d.name).is_file() and (d / "contract.json").is_file()
    ]


def test_every_bundle_projects_into_the_bundle_s_own_established_law():
    """The invariant the user asked for, over all 81 real bundles rather than a
    fixture: after projection the contract's operative law *is* the violation's.

    A fixture cannot carry this claim. It is written by the same hand as the
    projection, so it agrees with it by construction; the corpus is what the
    converter actually produced, including the bundles whose contract still
    lists a different set of articles from the one beside it.
    """
    bundles = _corpus_bundles()
    assert len(bundles) > 50, "the build/ corpus is the point of this test"
    failures: dict[str, list[str]] = {}

    for bundle in bundles:
        violation = Violation.model_validate_json(
            bundle_path(bundle, "violation_main", bundle.name).read_text(encoding="utf-8")
        )
        before = json.loads((bundle / "contract.json").read_text(encoding="utf-8"))
        after = project_contract(json.loads((bundle / "contract.json").read_text(encoding="utf-8")), violation)
        established = sorted({a.article_id for a in violation.established_articles})
        published = [a for fw in after["legal_basis"]["frameworks"] for a in fw["articles"]]
        issues = []

        if after["established_article_ids"] != established:
            issues.append(f"ids {after['established_article_ids']} != {established}")
        if sorted({a["article_id"] for a in published}) != established:
            issues.append("legal_basis names different articles than the violation establishes")
        if any(a["status"] != "established" for a in published):
            issues.append("legal_basis publishes a row that is not established")
        if any(not a["article_text"] for a in published):
            issues.append("legal_basis publishes an established article with no text")
        if [c["candidate_article_id"] for c in after["candidate_articles"]] != [
            c.candidate_article_id for c in violation.candidate_articles
        ]:
            issues.append("candidate articles differ from the violation's")
        if json.dumps(after["incident"], sort_keys=True) != json.dumps(
            json.loads(violation.incident.model_dump_json()), sort_keys=True
        ):
            issues.append("incident differs from the violation's")
        if after["title"] != violation.title or after["severity"] != violation.severity:
            issues.append("title/severity differ from the violation's")
        if violation.confidence is not None:
            if after["confidence"]["value"] != violation.confidence.value:
                issues.append("confidence.value differs from the violation's")
        if after["schema_version"] != before["schema_version"]:
            issues.append("schema_version was overwritten by the bundle schema")
        if issues:
            failures[bundle.name] = issues

    assert failures == {}, f"bundles whose projection contradicts the violation: {failures}"


def test_projecting_a_real_bundle_twice_changes_nothing():
    """Idempotency measured on real data: the projection runs on every UI write,
    so a second run over 81 bundles must be a no-op or the bundle churns."""
    for bundle in _corpus_bundles():
        violation = Violation.model_validate_json(
            bundle_path(bundle, "violation_main", bundle.name).read_text(encoding="utf-8")
        )
        raw = (bundle / "contract.json").read_text(encoding="utf-8")
        once = project_contract(json.loads(raw), violation)
        twice = project_contract(json.loads(raw), violation)
        assert json.dumps(once, sort_keys=True) == json.dumps(twice, sort_keys=True), bundle.name


def test_the_projection_neither_invents_nor_drops_a_contract_key():
    """Measured over the corpus: the projection only *adds* keys the vault left
    out (``established_article_ids`` in 79 bundles, ``confidence`` in the five
    whose contract dropped it), and replaces none that a check would read as a
    different document's field.

    ``CL-f7dd941e`` is the one legacy numeric ``confidence``: its violation
    derives ``0.0`` ("no element grids"), so the contract now carries the derived
    value instead of the old scalar. V08 called that scalar a warning, not a
    failure, precisely because a legacy snapshot is not something the bundle
    stands behind.
    """
    for bundle in _corpus_bundles():
        violation = Violation.model_validate_json(
            bundle_path(bundle, "violation_main", bundle.name).read_text(encoding="utf-8")
        )
        before = json.loads((bundle / "contract.json").read_text(encoding="utf-8"))
        after = project_contract(json.loads((bundle / "contract.json").read_text(encoding="utf-8")), violation)

        # Only ever additive, and only ever the words the classifier declared.
        assert set(after) - set(before) <= {"established_article_ids", "confidence"}, bundle.name
        assert set(before) - set(after) == set(), bundle.name
        assert set(before) <= CONTRACT_PROJECTED_KEYS | CONTRACT_VAULT_ONLY_KEYS, bundle.name
        # Per-row: the projection rebuilds legal_basis from the violation, so a
        # key the converter wrote and this does not would vanish silently.
        for fw in (before.get("legal_basis") or {}).get("frameworks") or []:
            for row in fw.get("articles") or []:
                assert set(row) == {
                    "article_id", "article_name", "article_text", "applicability_rationale",
                    "duty_bearer", "norm_type", "applicability", "subsections_invoked", "status",
                }, bundle.name


def test_one_article_established_for_several_reasons_keeps_every_reason():
    """``BR.CDC.T3.Art.6`` is established four times in BR-004, once per inciso
    the incident engages, with a different rationale each time — so the article
    rows are mirrored one-for-one and only the id *index* collapses. Deduplicating
    the rows would drop three rationales that nothing else records."""
    bundle = REPO_ROOT / "build" / "BR-004"
    violation_json = bundle_path(bundle, "violation_main", bundle.name)
    if not violation_json.is_file():
        pytest.skip("BR-004 is not in this checkout")
    violation = Violation.model_validate_json(violation_json.read_text(encoding="utf-8"))
    repeated = [a for a in violation.established_articles if a.article_id == "BR.CDC.T3.Art.6"]
    assert len(repeated) > 1, "the bundle this test is about no longer repeats the article"
    assert len({a.applicability_rationale for a in repeated}) == len(repeated)

    out = project_contract(json.loads((bundle / "contract.json").read_text(encoding="utf-8")), violation)

    rows = [
        a for fw in out["legal_basis"]["frameworks"] for a in fw["articles"]
        if a["article_id"] == "BR.CDC.T3.Art.6"
    ]
    assert [a["applicability_rationale"] for a in rows] == [
        a.applicability_rationale for a in repeated
    ]
    assert out["established_article_ids"].count("BR.CDC.T3.Art.6") == 1, (
        "the id index is read as a set by V08 and must not repeat"
    )


# ---------------------------------------------------------------------------
# The pairing: a writer that syncs the manifest must reconcile the contract
# ---------------------------------------------------------------------------

def _own_nodes(fn):
    """The nodes written in ``fn`` itself, not in a function it defines.

    ``mcp_server.build_server`` holds all 39 tool definitions, so a plain
    ``ast.walk`` would attribute every tool's calls to ``build_server`` and no
    tool could be identified by name. Same concern as the manifest guard in
    ``tests/test_segment_sync.py``, which is why the helper is written once more
    here rather than imported from a sibling test module.
    """
    stack = list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _called_name(func) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _callers(pack_dir: Path, callee: str) -> set[str]:
    """``module.py::function`` for every function that calls ``callee``.

    Substring match on the last attribute name, so an aliased import
    (``_reconcile_contract``) counts as the call it is.
    """
    found: set[str] = set()
    for path in sorted(pack_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if any(
                isinstance(node, ast.Call) and callee in _called_name(node.func)
                for node in _own_nodes(fn)
            ):
                found.add(f"{path.name}::{fn.name}")
    return found


def test_every_function_that_syncs_the_manifest_also_reconciles_the_contract():
    """The manifest and the contract are both derived views of one violation, and
    a writer that refreshes one must refresh the other.

    The guard in ``tests/test_segment_sync.py`` freezes the *writers* and requires
    the manifest sync; this freezes the *sync* and requires the contract beside
    it. Two writers each forgetting a different half of the same artifact pair is
    how contract.json fell 80 bundles behind, so a third writer must fail here
    rather than be discovered later.
    """
    pack_dir = REPO_ROOT / "violation_pack"
    syncing = _callers(pack_dir, "sync_segment_artifacts")
    reconciling = _callers(pack_dir, "reconcile_contract")

    assert syncing == {
        "mcp_server.py::write_violation_json_tool",
        "refine_batch_core.py::_process_one",
    }, (
        "a new function syncs the manifest — does it reconcile the contract too? "
        f"{sorted(reconciling)}"
    )
    assert syncing <= reconciling, (
        "these sync the manifest but leave contract.json as it was: "
        f"{sorted(syncing - reconciling)}"
    )


def test_the_pairing_guard_can_fail(tmp_path):
    """Prove the guard above can see a writer that syncs the manifest and skips
    the contract — the exact drift this module was written to end.

    The mutation deletes the contract reconcile from
    ``refine_batch_core._process_one``; the guard must name that function. A
    pairing guard that cannot report an unpaired writer is decorative.
    """
    import shutil

    pack_dir = tmp_path / "violation_pack"
    shutil.copytree(
        REPO_ROOT / "violation_pack", pack_dir, ignore=shutil.ignore_patterns("__pycache__")
    )
    target = pack_dir / "refine_batch_core.py"
    source = target.read_text(encoding="utf-8")
    mutated = source.replace(
        "    contract_sync = reconcile_contract(bundle_dir, v)\n"
        "    if contract_sync[\"contract_path\"] is None:\n"
        "        notes.append(\"contract_sync: no contract.json in this bundle\")\n"
        "\n",
        "",
    )
    assert mutated != source, "the reconcile block moved — update this mutation to match"
    target.write_text(mutated, encoding="utf-8")

    syncing = _callers(pack_dir, "sync_segment_artifacts")
    reconciling = _callers(pack_dir, "reconcile_contract")

    assert "refine_batch_core.py::_process_one" in syncing
    assert "refine_batch_core.py::_process_one" not in reconciling
    assert syncing - reconciling == {"refine_batch_core.py::_process_one"}, (
        "the guard's own failure condition, reproduced"
    )


# ---------------------------------------------------------------------------
# The write gate
# ---------------------------------------------------------------------------

def test_the_write_tool_is_what_keeps_the_contract_in_step(tmp_path):
    """The UI path: S3 edits a title, ``invokeTool`` persists through this tool,
    and the contract has to follow — it has no other writer on that path."""
    pytest.importorskip("mcp", reason="needs the [mcp] extra")
    from violation_pack.mcp_server import build_server

    bundle = _bundle(tmp_path, _contract())
    violation = _violation()
    server = build_server()

    result = asyncio.run(server._tool_manager.call_tool(
        "write_violation_json_tool",
        {"violation": json.loads(violation.model_dump_json()), "bundle_root": str(bundle)},
    ))

    assert result["contract_changed"] is True
    assert result["contract_path"] == str(bundle / "contract.json")
    on_disk = json.loads((bundle / "contract.json").read_text(encoding="utf-8"))
    assert on_disk["title"] == violation.title
    assert on_disk["established_article_ids"] == sorted([CPCL_ARTICLE, LPDC_ARTICLE])

    again = asyncio.run(server._tool_manager.call_tool(
        "write_violation_json_tool",
        {"violation": json.loads(violation.model_dump_json()), "bundle_root": str(bundle)},
    ))
    assert again["contract_changed"] is False, "the write gate is idempotent"


def test_the_write_tool_still_works_without_a_contract(tmp_path):
    """``--inputs-only`` bundles and hand-built ones have no contract; the write
    gate must not require one."""
    pytest.importorskip("mcp", reason="needs the [mcp] extra")
    from violation_pack.mcp_server import build_server

    bundle = _bundle(tmp_path, None)
    server = build_server()

    result = asyncio.run(server._tool_manager.call_tool(
        "write_violation_json_tool",
        {
            "violation": json.loads(_violation().model_dump_json()),
            "bundle_root": str(bundle),
        },
    ))

    assert result["path"] == str(bundle / f"{VID}.json")
    assert result["contract_path"] is None
    assert not (bundle / "contract.json").exists()


# ---------------------------------------------------------------------------
# The boundary itself
# ---------------------------------------------------------------------------

def _unclassified_contract_keys(root: Path) -> dict[str, list[str]]:
    """Contract keys that are in neither declared set, per bundle.

    Shared by the corpus guard and its mutation proof on purpose: a mutation test
    with its own copy of the logic proves the *copy* reports, not the guard.
    """
    classified = CONTRACT_PROJECTED_KEYS | CONTRACT_VAULT_ONLY_KEYS
    found: dict[str, list[str]] = {}
    for path in sorted(root.glob("*/contract.json")):
        contract = json.loads(path.read_text(encoding="utf-8"))
        stray = sorted(set(contract) - classified)
        if stray:
            found[path.parent.name] = stray
    return found


def test_every_contract_key_is_either_projected_or_called_vault_only():
    """The two sets are the whole design, so a key in neither is a field nobody
    classified — a new converter field that would sit unprojected forever.

    Asserted against the real corpus rather than a fixture: the fixtures here are
    written by the same hand as the projection, so they cannot tell us what the
    converter actually emits.
    """
    assert not (CONTRACT_PROJECTED_KEYS & CONTRACT_VAULT_ONLY_KEYS)

    contracts = sorted((REPO_ROOT / "build").glob("*/contract.json"))
    if not contracts:
        pytest.skip("no build/ corpus in this checkout")
    assert _unclassified_contract_keys(REPO_ROOT / "build") == {}


def test_the_boundary_guard_can_fail(tmp_path):
    """A corpus guard is only worth having if a contract shaped the way it forbids
    makes it report. Verified on a synthetic corpus, because the real one is the
    tree the guard reads."""
    corpus = tmp_path / "build" / VID
    corpus.mkdir(parents=True)
    contract_path = corpus / "contract.json"
    contract_path.write_text(json.dumps(_contract(), ensure_ascii=False), encoding="utf-8")
    assert _unclassified_contract_keys(tmp_path / "build") == {}, (
        "the fixture must be in the converter's own shape for the mutation to mean anything"
    )

    contract = _contract()
    contract["brand_new_field"] = 1
    contract_path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")

    assert _unclassified_contract_keys(tmp_path / "build") == {VID: ["brand_new_field"]}


# ---------------------------------------------------------------------------
# The maintenance script that applied the projection to the existing corpus
# ---------------------------------------------------------------------------

def _load_example_module(name: str, path: Path, source: str | None = None):
    """Import a module from ``examples/`` (not a package) or from given source."""
    if source is not None:
        path = path.parent / f"{name}.py"
        path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def reconcile_script():
    return _load_example_module(
        "reconcile_contracts", REPO_ROOT / "examples" / "reconcile_contracts.py"
    )


def test_the_script_repairs_a_bundle_only_when_asked(reconcile_script, tmp_path):
    """81 bundles were written before the projection existed, so the repair has to
    be a script. It writes to a tracked tree, so the dry run is the point: the
    default must report and change nothing."""
    bundle = _bundle(tmp_path, _contract())
    write_violation_json(_violation(), bundle)
    before = (bundle / "contract.json").read_text(encoding="utf-8")

    outcome, changed = reconcile_script.reconcile_bundle(bundle, write=False)

    assert outcome == "would rewrite"
    assert "legal_basis" in changed, "the frozen legal basis is the drift being repaired"
    assert (bundle / "contract.json").read_text(encoding="utf-8") == before, (
        "a dry run that touches the corpus is not a dry run"
    )

    outcome, changed = reconcile_script.reconcile_bundle(bundle, write=True)

    assert outcome == "rewritten"
    assert json.loads((bundle / "contract.json").read_text(encoding="utf-8")) == (
        project_contract(json.loads(before), _violation())
    )
    assert reconcile_script.reconcile_bundle(bundle, write=True) == ("unchanged", []), (
        "re-running the repair must be a no-op, not a rewrite loop"
    )


def test_the_script_cannot_write_through_a_symlink(reconcile_script, tmp_path):
    """The corpus's layout artifacts are symlinks into other trees, so following
    one would edit the corpus instead of the bundle."""
    bundle = _bundle(tmp_path, None)
    write_violation_json(_violation(), bundle)
    target = tmp_path / "outside" / "contract.json"
    target.parent.mkdir()
    target.write_text(json.dumps(_contract(), indent=2, ensure_ascii=False), encoding="utf-8")
    (bundle / "contract.json").symlink_to(target)

    outcome, changed = reconcile_script.reconcile_bundle(bundle, write=True)

    assert outcome.startswith("refused")
    assert changed == []
    assert json.loads(target.read_text(encoding="utf-8")) == _contract()


def test_the_script_walks_every_bundle_shape_and_skips_the_one_with_no_violation(
    reconcile_script, tmp_path
):
    """Discovery is structural, not ``CL-\\d{3}``: the corpus carries ``BR-``,
    ``INT-`` and one opaque id. ``build/CL-0301`` has a contract and no
    ``CL-0301.json``, so there is nothing to project from."""
    root = tmp_path / "build"
    for name in (VID, "BR-900", "INT-900"):
        bundle = root / name
        bundle.mkdir(parents=True)
        write_violation_json(_violation().model_copy(update={"violation_id": name}), bundle)
    orphan = root / "CL-0301"
    orphan.mkdir()
    (orphan / "contract.json").write_text("{}", encoding="utf-8")

    assert [p.name for p in reconcile_script._bundle_dirs(root)] == ["BR-900", VID, "INT-900"]


def test_the_script_reports_a_bundle_it_cannot_read(reconcile_script, tmp_path, monkeypatch, capsys):
    """One unreadable bundle must not stop the run, and must not look like success:
    the exit code is what a shell over a corpus reads."""
    good = _bundle(tmp_path, _contract())
    write_violation_json(_violation(), good)
    broken = tmp_path / "build" / "CL-901"
    broken.mkdir()
    (broken / "contract.json").write_text("{}", encoding="utf-8")
    (broken / "CL-901.json").write_text("{not json", encoding="utf-8")
    root = tmp_path / "build"

    monkeypatch.setattr(sys, "argv", ["reconcile_contracts.py", "--build-root", str(root)])
    assert reconcile_script.main() == 1
    captured = capsys.readouterr()
    assert "would rewrite" in captured.out
    assert "CL-901" in captured.err
    assert "1 contract(s) would be rewritten." in captured.out
    assert json.loads((good / "contract.json").read_text(encoding="utf-8")) != (
        project_contract(json.loads((good / "contract.json").read_text(encoding="utf-8")), _violation())
    ), "reporting must not have written anything"

    monkeypatch.setattr(
        sys, "argv", ["reconcile_contracts.py", "--build-root", str(root), "--write"]
    )
    assert reconcile_script.main() == 1, "a bundle it could not read is still a failure"
    assert "1 contract(s) rewritten." in capsys.readouterr().out
    assert reconcile_script.reconcile_bundle(good, write=True) == ("unchanged", [])


def test_the_dry_run_guard_can_fail(tmp_path):
    """Mutation: make ``reconcile_bundle`` write on every call. The dry run's
    "the bytes did not change" assertion must be able to see that — a guard that
    only ever ran against a correct script proves nothing."""
    source = (REPO_ROOT / "examples" / "reconcile_contracts.py").read_text(encoding="utf-8")
    mutated = source.replace("    if write:\n", "    if True:\n", 1)
    assert mutated != source, "the mutation must land, or this proves nothing"
    mutant = _load_example_module("reconcile_contracts_mutant", tmp_path / "x.py", source=mutated)

    bundle = _bundle(tmp_path, _contract())
    write_violation_json(_violation(), bundle)
    before = (bundle / "contract.json").read_text(encoding="utf-8")

    assert mutant.reconcile_bundle(bundle, write=False)[0] == "rewritten"
    assert (bundle / "contract.json").read_text(encoding="utf-8") != before
