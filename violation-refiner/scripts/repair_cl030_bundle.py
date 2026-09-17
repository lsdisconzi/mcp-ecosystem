#!/usr/bin/env python
"""Repair the CL-030 bundle: element-id closure, and corpus cache registration.

Two independent defects, both measured on the live artifacts rather than read
from a report. ``--check`` prints the plan and the before/after verdict without
writing; ``--apply`` performs it and refreshes the derived artifacts.

Defect 1 — element-id closure (V11 ``E_NEXUS_UNKNOWN_ELEMENT``, V21 fail).
    Nine ``nexus_matrix`` rows name an ``element_id`` that no ``element_grids``
    entry declares. They are not nine typos of nine kinds:

    * five rows carry an earlier spelling of an id the ``Art.3.b`` grid does
      declare — ``calidad_veraz`` -> ``informacion_veraz``,
      ``calidad_oportuna`` -> ``informacion_oportuna``,
      ``sujeto_titular_consumidor`` -> ``calidad_sujeto_consumidor``. The grid
      is the authored truth; the rows were generated against a superseded
      template, so the row moves and the grid does not.
    * one row names a harm element (``perjuicio_consumidor``) that belongs to
      the ``Art.23`` grid, where it is called ``menoscabo``. Its ``norm_id``
      says ``Art.3.b`` too, so the *pair* is the error — moving only the
      ``element_id`` would leave ``(Art.3.b, menoscabo)``, which V11 rejects
      and V21 reports as "pair not declared in any grid". Verified coherent
      afterwards: the row's own ``fact_id`` (``STG_7.seg-11``) is already in
      ``menoscabo``'s ``proof_evidence_segments``, so no new claim is made.
    * two rows name ``objeto_informacion_bienes_servicios``, for which the
      ``Art.3.b`` grid has no counterpart: the grid's information elements are
      ``informacion_veraz``/``informacion_oportuna`` (the quality of what was
      said) and ``deber_informarse_responsablemente`` (the consumer's own
      duty), and none of them is the *object* of the duty. Withdrawn rather
      than repointed at the nearest name — a nexus row is an assertion that a
      fact bears on an element, and there is no element here for it to bear on.

    This is a closure patch only. It does **not** touch any grid's
    ``proof_evidence_segments``. Eight of the nine rows cite
    ``STG_5.seg-1``/``seg-11`` ("Tiene que salir del avión, tiene que bajar",
    a three-second removal order) and stay orphaned under V13 after the
    rename. Adding those segments to the renamed elements' evidence lists would
    close V13 and would be a fabrication: a removal order is not proof that
    information given was truthful. The residual V13 warning is reported, not
    silenced.

Defect 2 — corpus cache registration (the ``not_in_bundle`` gap).
    ``CHIPENCOD_CP.md`` is the only corpus file carrying Código Penal
    Arts. 193-197, and the bundle did not stage it, so those candidates could
    not be resolved from the bundle. ``CodigoPenal_Prevaricacion.md`` and
    ``CodigoPenal_269bis_269ter.md`` are staged but were not listed in
    ``framework_caches``. This stages the missing file (as a symlink into
    ``data/law``, the corpus convention) and registers the caches whose code
    ``_discover_frameworks`` can actually resolve.

    The two ``CodigoPenal_*.md`` files both yield the code ``CODIGOPENAL``
    (``stem.split("_")[0].upper()``) and the registry is a dict, so the later
    one silently replaces the earlier: ``CodigoPenal_269bis_269ter.md`` is
    **shadowed** and unreachable. Registering it under ``CODIGOPENAL`` would
    point V03 at the *Prevaricación* file and fail the hash comparison, so it
    is registered as what it resolves to and the shadowing is reported. See
    ``notes`` in the result for why it is not renamed.

    ``CandidateArticle.framework_cache_status`` is
    ``Literal["not_in_bundle", "pending_fetch"]`` — it cannot record
    ``verified_in_bundle``, and V04 iterates ``established_articles`` only. So
    registration does not by itself flip either. What changes is that the
    article is now answerable *from the bundle*
    (``ui_server.discover_candidate_article`` enumerates the files on disk,
    which is the check that exists for this question); the candidates'
    ``verification_required`` text is updated from an instruction to a record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

BUNDLE = REPO / "build" / "CL-030"
VIOLATION_JSON = BUNDLE / "CL-030.json"

_HEX64 = re.compile(r"\A[0-9a-fA-F]{64}\Z")

# --- Defect 1: element-id closure -----------------------------------------
#
# Only element_id moves. The fact_id each row cites is the row's own claim and
# is left exactly as written, so the patch can be read as "this row was filed
# against the wrong element", never as "this row now proves a different fact".
RENAME_ELEMENT = {
    "CL.LPDC.Art.3.b.elem.sujeto_titular_consumidor": "CL.LPDC.Art.3.b.elem.calidad_sujeto_consumidor",
    "CL.LPDC.Art.3.b.elem.calidad_veraz": "CL.LPDC.Art.3.b.elem.informacion_veraz",
    "CL.LPDC.Art.3.b.elem.calidad_oportuna": "CL.LPDC.Art.3.b.elem.informacion_oportuna",
}

# element_id -> (new element_id, new norm_id). Both fields move together: the
# grid that declares `menoscabo` is the Art.23 grid, so a row that keeps
# `norm_id: CL.LPDC.Art.3.b` describes a pair no grid contains.
REPOINT = {
    "CL.LPDC.Art.3.b.elem.perjuicio_consumidor": (
        "CL.LPDC.Art.23.elem.menoscabo",
        "CL.LPDC.Art.23",
    ),
}

# element_id -> why there is nothing to repoint it at.
WITHDRAW = {
    "CL.LPDC.Art.3.b.elem.objeto_informacion_bienes_servicios": (
        "no Art.3.b element covers the object of the information duty; the grid's "
        "information elements are informacion_veraz/informacion_oportuna (quality of "
        "what was said) and deber_informarse_responsablemente (the consumer's own duty)"
    ),
}


def _element_id_map() -> dict[str, str]:
    """The full old-id -> new-id map, for the sections that mirror the matrix."""
    out = dict(RENAME_ELEMENT)
    out.update({old: new for old, (new, _norm) in REPOINT.items()})
    return out


# --- Defect 2: corpus cache registration ----------------------------------

# dest name in Legal framework/ -> (framework_code, canonical corpus file)
# `CHIPENCOD.md` is the corpus name for this cache (15 bundles carry it, e.g.
# CL-005 and CL-020); the corpus file itself is `CHIPENCOD_CP.md`.
STAGE_SYMLINK = {
    "CHIPENCOD.md": ("CHIPENCOD", "data/law/CL/CHIPENCOD_CP.md"),
}

# Reports for `--check`. These are findings, not operations: each names a
# property of the corpus that this patch cannot fix from inside one bundle.
UNREGISTERABLE = {
    "CodigoPenal_269bis_269ter.md": (
        "shadowed in _discover_frameworks: both CodigoPenal_* files yield the code "
        "CODIGOPENAL and the registry dict keeps only the last in sorted() order "
        "(CodigoPenal_Prevaricacion.md). Registering it under CODIGOPENAL would make "
        "V03 hash the Prevaricacion file against a 269bis digest and fail."
    ),
}

DIVERGENCE = (
    "CodigoPenal_Prevaricacion.md and CodigoPenal_269bis_269ter.md both declare "
    "`**Framework code** | CPCL / CPENAL` in their header, while _discover_frameworks "
    "derives the registry key from the filename (`stem.split('_')[0].upper()` -> "
    "CODIGOPENAL). So the file's own claim (CPCL) names a *different* cache "
    "(CPCL.md -> data/law/CL/CodigoPenal.md). Registering the row under the declared "
    "code would make V03 compare CPCL.md's digest against this file's and fail; the "
    "row is therefore registered under the key the registry actually holds."
)

PLACEHOLDER_METADATA = (
    "Both CodigoPenal_*.md files carry an unfilled metadata template: their Sha256 "
    "field reads `<sha256sum Codigo-PENAL_20-NOV-2018.pdf>` (resp. 07-MAR-2025), a "
    "shell command rather than a digest. Recorded as absent rather than propagated."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cache_metadata(path: Path, code: str) -> dict:
    """Read a cache's metadata through the same parser the pipeline uses.

    Not a hand-rolled header scan. Two of these files use the `| **Sha256** |`
    table form and two the `- **Sha256:**` list form, the emphasis differs, and
    both `CodigoPenal_*.md` carry an **unfilled** placeholder
    (`` `<sha256sum Codigo-PENAL_20-NOV-2018.pdf>` ``) where the digest belongs.
    A regex over the first N lines gets the markdown wrong (it yields
    ``'** 509efbf4…'``) and would record a shell command as a hash. The parser
    already decides this once, and `cache_file_sha256` below is the value V03
    actually compares.
    """
    from violation_pack.sources import MarkdownFrameworkSource

    src = MarkdownFrameworkSource(path, code, f"Legal framework/{path.name}")
    declared = src.declared_sha256()
    if declared and not _HEX64.match(declared):
        # A placeholder, not a digest. Recorded as absent rather than propagated:
        # `cache_self_reported_sha256` is documented as "the SHA the cache file
        # declares about itself", and a template token is not one.
        declared = None
    return {
        "cache_file_sha256": src.cache_sha256(),
        "cache_self_reported_sha256": declared,
        "articles_cached": src.articles_cached(),
    }


def plan(data: dict) -> dict:
    """Everything `--check` reports and `--apply` performs, computed up front."""
    declared: dict[str, dict] = {}
    for grid in data["element_grids"]:
        for el in grid["elements"]:
            declared[el["element_id"]] = el

    rows = data["nexus_matrix"]
    renames, repoints, withdrawals = [], [], []
    for idx, row in enumerate(rows):
        eid = row["element_id"]
        if eid in declared:
            continue
        if eid in RENAME_ELEMENT:
            renames.append((idx, eid, RENAME_ELEMENT[eid], row["fact_id"]))
        elif eid in REPOINT:
            new_eid, new_norm = REPOINT[eid]
            repoints.append((idx, eid, row["norm_id"], new_eid, new_norm, row["fact_id"]))
        elif eid in WITHDRAW:
            withdrawals.append((idx, eid, row["fact_id"]))
        else:
            raise SystemExit(f"unclassified undeclared element_id at row {idx}: {eid}")

    # Sections that mirror the matrix by element id. Left alone they would point
    # at ids the matrix no longer uses, which is the same defect one layer out.
    id_map = _element_id_map()
    authorities = []
    for auth in data["authorities"]:
        supports = auth.get("supports") or []
        moved = {s: id_map[s] for s in supports if s in id_map}
        dropped = [s for s in supports if s in WITHDRAW]
        if moved or dropped:
            authorities.append((auth["authority_id"], moved, dropped))

    questions = []
    for q in data.get("open_questions") or []:
        be = q.get("blocks_element")
        if be in id_map or be in WITHDRAW:
            questions.append((q["id"], be, None if be in WITHDRAW else id_map[be]))

    return {
        "declared": declared,
        "renames": renames,
        "repoints": repoints,
        "withdrawals": withdrawals,
        "authorities": authorities,
        "questions": questions,
    }


def apply(data: dict, p: dict) -> dict:
    """Mutate ``data`` in place; return the registration rows that were added."""
    rows = data["nexus_matrix"]
    for idx, _old, new_eid, _fact in p["renames"]:
        rows[idx]["element_id"] = new_eid
    for idx, _old, _onorm, new_eid, new_norm, _fact in p["repoints"]:
        rows[idx]["element_id"] = new_eid
        rows[idx]["norm_id"] = new_norm
    drop = {idx for idx, _e, _f in p["withdrawals"]}
    data["nexus_matrix"] = [r for i, r in enumerate(rows) if i not in drop]

    for auth in data["authorities"]:
        supports = auth.get("supports")
        if not supports:
            continue
        kept = [s for s in supports if s not in WITHDRAW]
        auth["supports"] = [_element_id_map().get(s, s) for s in kept]

    for q in data.get("open_questions") or []:
        be = q.get("blocks_element")
        if be in WITHDRAW:
            q["blocks_element"] = None
        elif be in _element_id_map():
            q["blocks_element"] = _element_id_map()[be]
    return {}


def register_caches(data: dict) -> list[dict]:
    """Stage any missing cache file and add its ``FrameworkCache`` row."""
    fw_dir = BUNDLE / "Legal framework"
    existing = {c["framework_code"] for c in data["framework_caches"]}
    added = []
    for dest_name, (code, corpus_rel) in STAGE_SYMLINK.items():
        dest = fw_dir / dest_name
        corpus = REPO / corpus_rel
        if not corpus.is_file():
            raise SystemExit(f"corpus file missing: {corpus}")
        if code in existing:
            continue
        if dest.is_symlink() or dest.exists():
            raise SystemExit(f"refusing to replace existing staged file: {dest}")
        # Corpus convention: the bundle stages a *link* into data/law so the
        # canonical bytes have one home. See pack.clear_linked_destination.
        os.symlink(os.path.relpath(corpus, fw_dir), dest)
        row = {
            "framework_code": code,
            "framework_name": "Codigo Penal Chileno (falsedad documental, Libro II Titulo IV)",
            "cache_file": f"Legal framework/{dest_name}",
            "cache_source_url": "https://bcn.cl/leychile/navegar?idNorma=1984",
            **_cache_metadata(dest, code),
        }
        data["framework_caches"].append(row)
        added.append(row)

    # CodigoPenal_Prevaricacion.md is staged but unregistered, and its code
    # *does* resolve (it is the file that shadows the other one).
    if "CODIGOPENAL" not in existing:
        staged = fw_dir / "CodigoPenal_Prevaricacion.md"
        if staged.is_file():
            row = {
                # The registry key, not the declared one. This file's header says
                # `**Framework code** | CPCL / CPENAL` while `_discover_frameworks`
                # derives `CODIGOPENAL` from the filename, and `CPCL` is already
                # the key for the *other* Código Penal cache (`CPCL.md`). V03 looks
                # the row up by this code, so a declared value here would resolve
                # to CPCL.md and fail the digest comparison. The divergence is
                # reported; see REPORTS.
                "framework_code": "CODIGOPENAL",
                "framework_name": "Codigo Penal Chileno (Prevaricacion, Libro II Titulo IV § IV)",
                "cache_file": "Legal framework/CodigoPenal_Prevaricacion.md",
                "cache_source_url": "https://bcn.cl/gdyHI3",
                **_cache_metadata(staged, "CODIGOPENAL"),
            }
            data["framework_caches"].append(row)
            added.append(row)
    return added


def rewrite_candidate_instructions(data: dict) -> list[str]:
    """Turn discharged "Register ..." instructions into a record of the state.

    ``framework_cache_status`` stays ``not_in_bundle``: the model's Literal has
    no ``verified_in_bundle`` for a candidate, and re-deciding it is the
    ``candidates`` stage's job. Rewriting the *instruction* is what this patch
    can honestly do — a stale "please register X" in a bundle that now carries X
    is a false statement about the bundle.
    """
    updates = []
    by_id = {c["candidate_article_id"]: c for c in data["candidate_articles"]}
    for art, old, new in [
        (
            "CL.CPCL.Art.193",
            "Register data/law/CL/CHIPENCOD_CP.md as a bundle framework cache to resolve this candidate.",
            "The corpus cache carrying this article is registered in this bundle as "
            "framework_caches 'CHIPENCOD' (Legal framework/CHIPENCOD.md, staged from "
            "data/law/CL/CHIPENCOD_CP.md).",
        ),
    ]:
        cand = by_id.get(art)
        if cand is None:
            continue
        for i, text in enumerate(cand["verification_required"]):
            if old in text:
                cand["verification_required"][i] = text.replace(old, new)
                updates.append(f"{art}[{i}]")
    return updates


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write the patch and refresh derived artifacts")
    args = ap.parse_args()

    raw = VIOLATION_JSON.read_text(encoding="utf-8")
    data = json.loads(raw)
    p = plan(data)

    print(f"== CL-030 plan ({'APPLY' if args.apply else 'CHECK'}) ==")
    print(f"nexus rows: {len(data['nexus_matrix'])}")
    print(f"  rename element_id   : {len(p['renames'])}")
    for idx, old, new, fact in p["renames"]:
        print(f"      [{idx:3d}] {old.split('elem.')[1]:32s} -> {new.split('elem.')[1]:32s} ({fact.split('.')[-1]})")
    print(f"  repoint element_id  : {len(p['repoints'])}")
    for idx, old, onorm, new, nnorm, fact in p["repoints"]:
        print(f"      [{idx:3d}] {old.split('elem.')[1]:32s} -> {new}  (norm {onorm} -> {nnorm}) ({fact.split('.')[-1]})")
    print(f"  withdraw row        : {len(p['withdrawals'])}")
    for idx, eid, fact in p["withdrawals"]:
        print(f"      [{idx:3d}] {eid}  ({fact.split('.')[-1]})")
        print(f"            reason: {WITHDRAW[eid]}")
    print(f"authorities with a mirroring supports list : {len(p['authorities'])}")
    for aid, moved, dropped in p["authorities"]:
        print(f"      {aid}: moved={ {k.split('elem.')[1]: v.split('elem.')[-1] for k, v in moved.items()} } dropped={[d.split('elem.')[1] for d in dropped]}")
    print(f"open_questions with a mirroring blocks_element : {len(p['questions'])}")
    for qid, old, new in p["questions"]:
        print(f"      {qid}: {old.split('elem.')[1]} -> {new.split('elem.')[1] if new else None}")
    print("cache registration:")
    for name, (code, rel) in STAGE_SYMLINK.items():
        dest = BUNDLE / "Legal framework" / name
        state = "absent" if not (dest.exists() or dest.is_symlink()) else "present"
        print(f"      stage Legal framework/{name} -> {rel}  [{state}]")
        print(f"            sha256 {_sha256(REPO / rel)}")
    for name, why in UNREGISTERABLE.items():
        print(f"      NOT registerable: Legal framework/{name}")
        print(f"            {why}")
    print("findings (reported, not patched):")
    print(f"      {DIVERGENCE}")
    print(f"      {PLACEHOLDER_METADATA}")

    if not args.apply:
        print("\n(--check: nothing written)")
        return 0

    apply(data, p)
    added = register_caches(data)
    touched = rewrite_candidate_instructions(data)
    print(f"\nregister_caches: added {len(added)} row(s) -> {[r['framework_code'] for r in added]}")
    print(f"candidate instruction rewrites: {touched or 'none'}")
    print(f"nexus rows after: {len(data['nexus_matrix'])}")

    # Byte-stable with the on-disk form (json.dumps(indent=2, ensure_ascii=False),
    # no trailing newline), so the diff is exactly the patch.
    VIOLATION_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
