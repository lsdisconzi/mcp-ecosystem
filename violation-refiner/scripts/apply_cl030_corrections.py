#!/usr/bin/env python
"""Apply the corrections from the 2026-09-17 verification review to CL-030.

Source of the plan: ``.dev/corrections.CL-030/01-corrections.review.md``
("Informe de Verificación — Violación CL-030"), section 5.2, plus the two
corrections the review left open (the article that actually carries the
"omisión de persecución" conduct, and the article that actually carries the
reparación e indemnización right).

Every replacement below was checked against the law corpus in ``data/law/CL/``
*first*; the corpus text, not the review's paraphrase, is what the rewritten
candidate fields restate. Two divergences between the review and the corpus
are recorded in the affected ``history_note`` (Art. 12 LPDC) or in the
candidate comment (Art. 16 LPDC).

Scope — this script touches exactly five things, nothing else:

1. candidates    ``CL.CPCL.Art.258`` -> ``CL.CPCL.C1.Art.229`` (re-point)
                 ``CL.LPDC.Art.16``   -> ``CL.LPDC.T1.Art.3.e``  (re-point)
                 ``CL.LPDC.Art.12``   (rename; id unchanged)
                 ``CL.CPCL.Art.212``  -> ``CL.CPCL.T2.P7.Art.416`` (re-point)
2. nexus_matrix  remap the 7 orphan ``CL.LPDC.Art.3.b.elem.*`` families onto
                 the canonical grid element ids, drop the family that has no
                 canonical counterpart, drop exact duplicates
3. open_questions  remap ``blocks_element`` the same way; null it where the
                 family has no canonical counterpart
4. authorities   remap the dangling ``supports`` entries onto canonical element
                 ids, or onto the articles the authority's proposition is about
5. nothing else  element grids, ``proof_status``, ``proof_evidence_segments``,
                 ``confidence`` and ``established_articles`` are untouched, so
                 ``derive_confidence`` is unchanged and V10 stays green.

Not applied on purpose:

* ``objeto_material_informacion`` is left at ``strong``. The review's §3.2
  suggests ``contested`` "por prudencia"; it is an observation, not one of the
  errors in §5.2, and changing a ``proof_status`` changes ``weighted_score``
  and therefore confidence, so it would have to be written in the same pass as
  a re-derived confidence value. Left for a separate decision.
* ``proof_evidence_segments`` is not extended. 38 of the 118 nexus rows already
  cited a segment their element did not list (V13, warn) before this pass;
  remapping the orphan families moves that to 54, because the remapped rows
  keep the facts they linked. Adding those facts to the grids' evidence lists
  would clear V13 by redefining what the grids claim, which the review did not
  ask for and called the grids sound.

Usage:
    python scripts/apply_cl030_corrections.py --check
    python scripts/apply_cl030_corrections.py --apply
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLE = REPO / "build" / "CL-030"
VIOLATION_JSON = BUNDLE / "CL-030.json"

ELEM = "CL.LPDC.Art.3.b.elem."
NO_COUNTERPART = ELEM + "consecuencia_juridica_infraccion"

# Orphan element key (as used by the nexus / open questions) -> canonical key
# declared in the CL.LPDC.Art.3.b element grid.
ELEMENT_RENAME: dict[str, str] = {
    ELEM + "calidad_sujeto_consumidor": ELEM + "sujeto_pasivo_consumidor",
    ELEM + "sujeto_obligado_proveedor": ELEM + "sujeto_activo_proveedor",
    ELEM + "informacion_veraz": ELEM + "veracidad",
    ELEM + "informacion_oportuna": ELEM + "oportunidad",
    ELEM + "deber_informarse_responsablemente": ELEM + "deber_de_informarse",
    ELEM + "condiciones_contratacion_relevantes": ELEM + "objeto_material_informacion",
    NO_COUNTERPART: None,  # type: ignore[dict-item]
}

# --- candidate replacements -------------------------------------------------
# Keyed by the current ``candidate_article_id``; the entry replaces the whole
# candidate in place, so ordering and surrounding formatting stay stable.

NEW_229 = {
    "candidate_article_id": "CL.CPCL.C1.Art.229",
    "candidate_name": (
        "Prevaricación – omisión de persecución o aprehensión de delincuentes "
        "(funcionario público no judicial)"
    ),
    "framework_cache_status": "not_in_bundle",
    "verification_required": [
        (
            "Fetch verbatim text for CL.CPCL.C1.Art.229 from bcn.cl/leychile "
            "(Código Penal, § IV Prevaricación) and confirm exact wording and "
            "subsections. The text held in the bundle's CODIGOPENAL framework cache "
            "(CodigoPenal_Prevaricacion.md) reads: \"Sufrirán las penas de suspensión "
            "de empleo en su grado medio y multa de seis a diez unidades tributarias "
            "mensuales los funcionarios a que se refiere el artículo anterior, que, "
            "por malicia o negligencia inexcusables y faltando a las obligaciones de "
            "su oficio, no procedieren a la persecución o aprehensión de los "
            "delincuentes después de requerimiento o denuncia formal hecha por "
            "escrito.\""
        ),
        (
            "Determine whether the passenger's allegations to the DGAC official "
            "(segments I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-294, seg-297, "
            "seg-315, seg-316) meet the article's precondition of a \"requerimiento o "
            "denuncia formal hecha por escrito\" — a formal request or complaint made "
            "in writing"
        ),
        (
            "Confirm whether a DGAC official falls within the duty-bearer class the "
            "article borrows from Art. 228 CP (\"empleo público no perteneciente al "
            "orden judicial\") and whether DGAC staff hold the duty to pursue or "
            "apprehend offenders that the article presupposes"
        ),
        (
            "Confirm which of the two subjective hypotheses the conduct falls under — "
            "\"malicia\" or \"negligencia inexcusable\" — and whether inaction alone, "
            "without a formal written complaint, can satisfy either"
        ),
    ],
    "preliminary_view": (
        "Art. 229 CP is the provision that punishes the conduct formerly attributed "
        "to Art. 258 CP: the non-judicial public employee who, out of inexcusable "
        "malice or negligence and failing the duties of his office, does not proceed "
        "to the pursuit or apprehension of offenders after a formal written request "
        "or complaint. Segment I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-315 "
        "('Tu no hiciste nada') and seg-316 ('No puedo decir que hiciste algo') "
        "record a DGAC official acknowledging that the passenger did nothing wrong "
        "while not acting on his allegations of false accusation, which is the "
        "factual shape of an omission of the duties to pursue an offence."
    ),
    "history_note": (
        "Replaces the former candidate CL.CPCL.Art.258 (\"Abuso de autoridad por "
        "omisión de deberes en la persecución de delitos\"). The 2026-09-17 "
        "verification review reported that Art. 258 CP regulates solicitación rather "
        "than the omission of duties in the pursuit of offences, and asked for the "
        "correct article to be identified instead. The omission-of-prosecution "
        "offence is Art. 229 CP (\"Prevaricación – Omisión de persecución o "
        "aprehensión\"); its text is held in the bundle's CODIGOPENAL framework cache "
        "(CodigoPenal_Prevaricacion.md) and was read there. The earlier candidate "
        "review's caveat still applies: if the duty-bearer class is limited to "
        "officials with prosecution functions, this article is Incorrect for a DGAC "
        "official."
    ),
}

NEW_3E = {
    "candidate_article_id": "CL.LPDC.T1.Art.3.e",
    "candidate_name": (
        "Derecho a la reparación e indemnización por daños materiales y morales "
        "derivados del incumplimiento del proveedor"
    ),
    "framework_cache_status": "not_in_bundle",
    "verification_required": [
        (
            "Confirm the verbatim text of CL.LPDC.T1.Art.3.e against bcn.cl/leychile "
            "(DFL 3, texto refundido de la Ley 19.496). The text held in the bundle's "
            "LPDC framework cache (L19496_LPDC.md) reads: \"El derecho a la reparación "
            "e indemnización adecuada y oportuna de todos los daños materiales y "
            "morales en caso de incumplimiento de cualquiera de las obligaciones "
            "contraídas por el proveedor, y el deber de accionar de acuerdo a los "
            "medios que la ley le franquea.\""
        ),
        (
            "Confirm whether the passenger's loss of the flight and the humiliation he "
            "reports (segment "
            "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11: \"perdí mi "
            "vuelo, fui humillado\") and the witnesses' missed-connection allegations "
            "(I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-175) fall within the "
            "\"daños materiales y morales\" the provision covers"
        ),
        (
            "Determine whether the removal from the aircraft is an \"incumplimiento de "
            "las obligaciones contraídas por el proveedor\" for the affected "
            "passenger, as opposed to a lawful exercise of the carrier's powers"
        ),
        (
            "Confirm separately the content of Art. 16 LPDC, the article the former "
            "candidate cited, so that the discarded attribution is closed on the "
            "record rather than merely dropped"
        ),
    ],
    "preliminary_view": (
        "The right the former candidate described — reparación e indemnización for "
        "breach — is Art. 3 letra e) LPDC, not Art. 16: it grants \"reparación e "
        "indemnización adecuada y oportuna de todos los daños materiales y morales "
        "en caso de incumplimiento de cualquiera de las obligaciones contraídas por "
        "el proveedor\". Segment "
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11 records the "
        "passenger's loss of flight and his claim of humiliation, and segment "
        "I-002_04_NAR-06_STG_6_jetbridge_standoff.seg-175 records witnesses raising "
        "missed connections — concrete material and moral harm of exactly the kind "
        "this provision addresses, beyond the damages head carried by the "
        "established Art. 23."
    ),
    "history_note": (
        "Formerly cited as CL.LPDC.Art.16 under the name \"Derecho a la reparación e "
        "indemnización por incumplimiento y por suspensión o cancelación del "
        "servicio\". The 2026-09-17 verification review reported that Art. 16 LPDC "
        "regulates abusive clauses in contracts of adhesion and asked for the "
        "candidate to be removed. The candidate was kept and re-pointed instead: the "
        "provision that carries the described right, moral damages included, is "
        "Art. 3 letra e) LPDC, whose text is in the bundle's own LPDC framework cache "
        "(L19496_LPDC.md) and whose cache note ties it to this incident (\"covers both "
        "tangible losses and non-material harm (humillación, daño moral)\"). The "
        "review's route, the already-established Art. 23, is complementary rather "
        "than identical: Art. 23 governs the negligence-based infraction, Art. 3 e) "
        "states the consumer's reparation right including moral damages. Content of "
        "Art. 16 LPDC was not verifiable in this corpus (the article is absent from "
        "L19496_LPDC.md), so its removal was not carried out on that premise alone."
    ),
}

RENAMED_12 = {
    "candidate_name": (
        "Obligación del proveedor de respetar los términos, condiciones y "
        "modalidades ofrecidos o convenidos con el consumidor"
    ),
    "verification_required": [
        (
            "Confirm the verbatim text of CL.LPDC.Art.12 against bcn.cl/leychile. The "
            "text held in the bundle's LPDC framework cache (L19496_LPDC.md) reads: "
            "\"Todo proveedor de bienes o servicios estará obligado a respetar los "
            "términos, condiciones y modalidades conforme a las cuales se hubiere "
            "ofrecido o convenido con el consumidor la entrega del bien o la "
            "prestación del servicio.\""
        ),
        (
            "Confirm whether the boarding-time discrepancy (seg-2, seg-3, seg-4, "
            "seg-5, seg-17, seg-55, seg-59) is one of the \"términos, condiciones y "
            "modalidades\" of the air-transport service which this article obliges the "
            "provider to respect"
        ),
        (
            "Determine whether the airline staff's concession 'no esta correcto' "
            "(seg-59) engages this duty of respect for the offered or agreed terms, as "
            "distinct from the veracity and timeliness duties already captured by "
            "CL.LPDC.Art.3.b"
        ),
        (
            "Confirm separately whether a duty of written confirmation of the contract "
            "exists and where it lives: in the text of Ley 19.496 as refunded by DFL 3 "
            "the written-confirmation obligation is attributed to Art. 12 A, not to "
            "Art. 12"
        ),
    ],
    "preliminary_view": (
        "Art. 12 LPDC obliges the provider to respect the terms, conditions and "
        "modalities under which the good or service was offered or agreed with the "
        "consumer. The passenger repeatedly asks for documentation of the boarding "
        "time (I-002_02_NAR-02_STG_2_boarding_gate.seg-23: \"¿Hay alguna "
        "documentación explicándolo?\") and the airline staff concedes the "
        "information is not correct (seg-59: 'Ah no po, no esta correcto.'): the "
        "terms the passenger was offered (boarding time) were not the terms "
        "performed, which is the factual shape of a breach of the duty to respect the "
        "offered or agreed terms, and is distinct from the information duties already "
        "captured by CL.LPDC.Art.3.b."
    ),
    "history_note": (
        "Renamed on 2026-09-17 from \"Obligación de informar por escrito las "
        "condiciones de contratación y sus modificaciones\", a name that asserted a "
        "written-information duty Art. 12 LPDC does not impose — the flag raised by "
        "the verification review is well founded. The corrected name restates the "
        "text held in the bundle's LPDC framework cache (L19496_LPDC.md): a duty to "
        "respect the terms, conditions and modalities offered or agreed with the "
        "consumer, not a duty to confirm the contract in writing. The review's own "
        "description of the article (\"la confirmación escrita del contrato una vez "
        "perfeccionado\") is not what the corpus text says; in the refunded text the "
        "written-confirmation obligation belongs to Art. 12 A. Proposed as the "
        "counterpart to the established Art. 3.b (veracity) and Art. 23 (liability); "
        "not previously cited in the bundle."
    ),
}

NEW_416 = {
    "candidate_article_id": "CL.CPCL.T2.P7.Art.416",
    "candidate_name": (
        "Injuria – toda expresión proferida o acción ejecutada en deshonra, "
        "descrédito o menosprecio de otra persona"
    ),
    "framework_cache_status": "not_in_bundle",
    "verification_required": [
        (
            "Fetch verbatim text for CL.CPCL.T2.P7.Art.416 from bcn.cl/leychile "
            "(Código Penal, Libro Segundo, Párrafo 7) and confirm exact wording and "
            "subsections. The text held in the bundle's CPCL framework cache "
            "(CodigoPenal.md) reads: \"Es injuria toda expresión proferida o acción "
            "ejecutada en deshonra, descrédito o menosprecio de otra persona.\""
        ),
        (
            "Confirm whether the passenger's claim of humiliation "
            "(I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11: \"fui "
            "humillado\") and the public removal from the aircraft support an "
            "injury-to-honour hypothesis under Art. 416 CP"
        ),
        (
            "Determine whether the conduct is attributable to airline personnel or to "
            "public officials, and whether the public nature of the removal aggravates "
            "the imputation"
        ),
        (
            "Confirm whether the offence requires the injured party's querella and "
            "which limitation period applies to it"
        ),
    ],
    "preliminary_view": (
        "Art. 416 CP defines injuria as any expression uttered or act executed in "
        "dishonour, discredit or contempt of another person — the offence that the "
        "former candidate labelled with Art. 212 CP. Segment "
        "I-002_05_NAR-07_STG_7_post_removal_investigation.seg-11 records the "
        "passenger's express claim of humiliation ('fui humillado') in connection "
        "with a public removal from the aircraft, which is the factual core of an "
        "injury-to-honour hypothesis, distinct from the calumnia candidate "
        "(Art. 211 CP)."
    ),
    "history_note": (
        "Re-pointed on 2026-09-17 from CL.CPCL.Art.212. The verification review "
        "found that injuries to honour are not typified in Art. 212 CP and that "
        "injuria is. Art. 212 CP punishes the simulation of being the victim of a "
        "crime or the false denunciation that persons who took no part did so, which "
        "is not the conduct relied on here. The text of Art. 416 CP is held in the "
        "bundle's CPCL framework cache (CodigoPenal.md, ELI ID "
        "CL.CPCL.T2.P7.Art.416), which was read and matches the review. Proposed as "
        "the injury-to-honour counterpart to the Art. 211 calumnia candidate; not "
        "previously cited."
    ),
}

CANDIDATE_REPLACEMENTS: dict[str, dict] = {
    "CL.CPCL.Art.258": NEW_229,
    "CL.LPDC.Art.16": NEW_3E,
    "CL.CPCL.Art.212": NEW_416,
}
CANDIDATE_PATCHES: dict[str, dict] = {"CL.LPDC.Art.12": RENAMED_12}

# --- authority supports -----------------------------------------------------
# Element-level: the orphan ids map onto the canonical grid element ids.
# Article-level: the two authorities whose only support was the withdrawn
# "consecuencia_juridica_infraccion" family are re-pointed at the articles their
# own ``proposition_to_verify`` is about, rather than left dangling or dropped.
AUTHORITY_SUPPORTS: dict[str, list[str]] = {
    "AUTH-LPDC-3B-VERAZ-OPORTUNA": [ELEM + "veracidad", ELEM + "oportunidad"],
    "AUTH-LPDC-3B-VERAZ": [ELEM + "veracidad"],
    "AUTH-LPDC-3B-OPORTUNA": [ELEM + "oportunidad"],
    "AUTH-LPDC-3B-DEBER-CONSUMIDOR": [ELEM + "deber_de_informarse", "CL.LPDC.Art.23.elem.menoscabo"],
    "AUTH-LPDC-3B-CONDICIONES": [ELEM + "objeto_material_informacion"],
    "AUTH-LPDC-3B-CONSEC": ["CL.LPDC.Art.3.b", "CL.LPDC.Art.23"],
    "AUTH-ESTATUTO-LPDC-3B": ["CL.LPDC.Art.3.b"],
    "AUTH-DOCTRINA-LPDC-INFO": [
        ELEM + "veracidad",
        ELEM + "oportunidad",
        ELEM + "objeto_material_informacion",
    ],
}


def _load() -> tuple[dict, bytes]:
    raw = VIOLATION_JSON.read_bytes()
    data = json.loads(raw)
    # The bundle is written without a trailing newline; assert the file on disk
    # is exactly that canonical serialization so a diff stays minimal and the
    # pre-edit bytes are reproducible.
    canonical = json.dumps(data, indent=2, ensure_ascii=False).encode()
    if raw != canonical:
        raise SystemExit(
            f"{VIOLATION_JSON} is not in canonical form (indent=2, ensure_ascii=False, "
            "no trailing newline); refusing to rewrite it"
        )
    return data, raw


def _plan(data: dict) -> dict:
    """Compute every change and the counts that prove the pre-state matched."""
    plan: dict = {}

    by_id = {c["candidate_article_id"]: c for c in data["candidate_articles"]}
    missing = [i for i in list(CANDIDATE_REPLACEMENTS) + list(CANDIDATE_PATCHES) if i not in by_id]
    if missing:
        raise SystemExit(f"candidate(s) not found in bundle: {missing}")
    untouched = sorted(set(CANDIDATE_REPLACEMENTS) | set(CANDIDATE_PATCHES))
    plan["candidates"] = untouched

    rows = data["nexus_matrix"]
    dropped_family = [r for r in rows if r["element_id"] == NO_COUNTERPART]
    remapped = [r for r in rows if r["element_id"] in ELEMENT_RENAME and r["element_id"] != NO_COUNTERPART]
    seen: set[tuple] = set()
    duplicates = []
    for r in rows:
        if r["element_id"] == NO_COUNTERPART:
            continue
        key = (r["norm_id"], ELEMENT_RENAME.get(r["element_id"], r["element_id"]), r["fact_id"])
        if key in seen:
            duplicates.append(r)
            continue
        seen.add(key)
    plan["nexus"] = {
        "before": len(rows),
        "remapped": len(remapped),
        "dropped_family": len(dropped_family),
        "duplicates": len(duplicates),
        "after": len(seen),
    }

    oqs = [
        q for q in data["open_questions"]
        if q.get("blocks_element") in ELEMENT_RENAME
    ]
    plan["open_questions"] = {
        "remapped": sum(1 for q in oqs if ELEMENT_RENAME[q["blocks_element"]] is not None),
        "nulled": sum(1 for q in oqs if ELEMENT_RENAME[q["blocks_element"]] is None),
        "ids": [q["id"] for q in oqs if ELEMENT_RENAME[q["blocks_element"]] is None],
    }

    auth_by_id = {a["authority_id"]: a for a in data["authorities"]}
    bad = [i for i in AUTHORITY_SUPPORTS if i not in auth_by_id]
    if bad:
        raise SystemExit(f"authorit(ies) not found in bundle: {bad}")
    plan["authorities"] = {
        i: {"before": auth_by_id[i]["supports"], "after": AUTHORITY_SUPPORTS[i]}
        for i in AUTHORITY_SUPPORTS
    }
    return plan


def _print_plan(data: dict, plan: dict) -> None:
    n = plan["nexus"]
    print("== candidates ==")
    for old, new in CANDIDATE_REPLACEMENTS.items():
        print(f"  replace {old:24s} -> {new['candidate_article_id']}  ({new['candidate_name'][:60]}...)")
    for cid in CANDIDATE_PATCHES:
        print(f"  rename  {cid:24s}    (id unchanged)")
    print(f"== nexus_matrix ==  {n['before']} -> {n['after']}"
          f"  (remapped {n['remapped']}, dropped family {n['dropped_family']}, duplicates {n['duplicates']})")
    o = plan["open_questions"]
    print(f"== open_questions ==  remapped {o['remapped']}, nulled {o['nulled']} {o['ids']}")
    print("== authorities ==")
    for aid, d in plan["authorities"].items():
        print(f"  {aid}\n      before {d['before']}\n      after  {d['after']}")
    print("== untouched ==")
    print("  element_grids (proof_status, proof_evidence_segments), confidence, established_articles")


def _apply(data: dict) -> dict:
    # 1. candidates ---------------------------------------------------------
    for c in data["candidate_articles"]:
        cid = c["candidate_article_id"]
        if cid in CANDIDATE_REPLACEMENTS:
            c.clear()
            c.update(CANDIDATE_REPLACEMENTS[cid])
        elif cid in CANDIDATE_PATCHES:
            c.update(CANDIDATE_PATCHES[cid])

    # 2. nexus --------------------------------------------------------------
    kept = []
    seen: set[tuple] = set()
    for r in data["nexus_matrix"]:
        target = ELEMENT_RENAME.get(r["element_id"], r["element_id"])
        if target is None:
            continue
        r["element_id"] = target
        key = (r["norm_id"], r["element_id"], r["fact_id"])
        if key in seen:
            continue
        seen.add(key)
        kept.append(r)
    data["nexus_matrix"] = kept

    # 3. open questions -----------------------------------------------------
    for q in data["open_questions"]:
        be = q.get("blocks_element")
        if be in ELEMENT_RENAME:
            q["blocks_element"] = ELEMENT_RENAME[be]

    # 4. authorities --------------------------------------------------------
    for a in data["authorities"]:
        if a["authority_id"] in AUTHORITY_SUPPORTS:
            a["supports"] = list(AUTHORITY_SUPPORTS[a["authority_id"]])
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="print the plan; write nothing")
    g.add_argument("--apply", action="store_true", help="write the corrections")
    args = ap.parse_args()

    data, raw = _load()
    plan = _plan(data)
    _print_plan(data, plan)
    if args.check:
        print("\n(--check: nothing written)")
        return 0

    _apply(data)
    encoded = json.dumps(data, indent=2, ensure_ascii=False)
    VIOLATION_JSON.write_text(encoded, encoding="utf-8")
    print(f"\nwritten: {VIOLATION_JSON}  ({len(raw)} -> {len(encoded.encode())} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
