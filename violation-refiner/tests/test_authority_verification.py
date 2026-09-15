"""The verification protocols and the prose field a human reads to see which ran.

`authority_verification.py` is the only module allowed to flip `verified=True`.
Two of its three protocols left `verification_protocol` blank, and those two are
exactly the ones the S6 "attach the official source" flow uses — so every stub a
reviewer verified by uploading or fetching its source would have carried
`verified=True` with no statement of how, which V16 reports as a warning
("verified=True but verification_protocol is blank").

The protocols are covered nowhere else: `test_verifier.py` tests the enrichment
report, and `test_validation.py` tests V16 against hand-built authorities rather
than against authorities a protocol produced.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from violation_pack.authority_verification import (
    VerificationError,
    verify_human_attested,
    verify_statute_external_fetch,
)
from violation_pack.models import Authority, Incident, Violation
from violation_pack.validation import v16_authority_verification_coherence


SOURCE_URI = "https://www.pjud.cl/sentencia/16622-2025"
SOURCE = (
    "Santiago, dieciocho de marzo de dos mil veinticinco. VISTOS: en estos "
    "autos sobre despido injustificado. Octavo: que el despido fue improcedente "
    "por falta de aviso previo, como exige el inciso primero del artículo 162."
)
# Exactly as it appears above, with the article's own punctuation detached, so
# the match proves substring semantics rather than a whole-sentence equality.
QUOTE = "el despido fue improcedente por falta de aviso previo"
SHA = hashlib.sha256(SOURCE.encode("utf-8")).hexdigest()


def _violation(*authorities: Authority) -> Violation:
    """The smallest violation the protocols can act on — they touch no other field."""
    return Violation(
        violation_id="CL-900",
        title="Prueba de protocolos",
        severity="HIGH",
        incident=Incident(date="2025-03-18", location="Santiago"),
        authorities=list(authorities),
    )


def _stub(authority_id: str, type_: str) -> Authority:
    return Authority(
        authority_id=authority_id,
        type=type_,
        supports=["CL.CHIPENCOD.T4.C3.Art.193"],
        research_query="buscar la sentencia que sostiene la proposición",
        proposition_to_verify="El despido fue improcedente por falta de aviso previo.",
    )


def _authority(v: Violation, authority_id: str) -> Authority:
    return next(a for a in v.authorities if a.authority_id == authority_id)


def _verify_jurisprudence(**overrides) -> Violation:
    args = dict(
        source_uri=SOURCE_URI,
        source_content=SOURCE,
        target_quote=QUOTE,
        attestor="reviewer@example.test",
        court="Corte Suprema",
        rol="16.622-2025",
        decision_date=datetime(2025, 3, 18, tzinfo=timezone.utc),
    )
    args.update(overrides)
    return verify_human_attested(
        _violation(_stub("AUTH-J-01", "jurisprudence")), authority_id="AUTH-J-01", **args
    )


def test_human_attested_names_the_protocol_the_source_and_the_attestor():
    auth = _authority(_verify_jurisprudence(), "AUTH-J-01")

    assert auth.verified is True
    assert auth.verification_provenance.protocol == "human_attested_v1"
    assert auth.verification_provenance.matched_offset == SOURCE.find(QUOTE)
    assert auth.verification_provenance.source_uri == SOURCE_URI
    assert auth.verification_provenance.source_sha256 == SHA
    # The prose counterpart: V16 reads this field, nothing reads the enum.
    assert "human_attested_v1" in auth.verification_protocol
    assert f"source={SOURCE_URI}" in auth.verification_protocol
    assert f"sha256={SHA}" in auth.verification_protocol
    # The attestor is the entire strength of this protocol — V11 keeps flagging
    # it as human-attested — so it cannot live only in `provenance.notes`.
    assert "attested_by=reviewer@example.test" in auth.verification_protocol


def test_external_fetch_names_the_protocol_and_the_hash_of_what_was_quoted():
    v = verify_statute_external_fetch(
        _violation(_stub("AUTH-S-01", "statute")),
        authority_id="AUTH-S-01",
        source_uri=SOURCE_URI,
        source_content=SOURCE,
        target_quote=QUOTE,
        instrument="Código del Trabajo Art. 162",
        pages="inciso primero",
    )
    auth = _authority(v, "AUTH-S-01")

    assert auth.verified is True
    assert auth.instrument == "Código del Trabajo Art. 162"
    assert auth.pages == "inciso primero"
    assert auth.verification_provenance.protocol == "statute_external_fetch_v1"
    assert auth.verification_protocol.startswith("statute_external_fetch_v1; ")
    assert f"sha256={SHA}" in auth.verification_protocol


def test_neither_upload_path_leaves_v16_with_a_blank_protocol_to_report():
    """The whole point of the fix, stated as the check that used to fire."""
    assert v16_authority_verification_coherence(_verify_jurisprudence(), {}).status == "pass"
    statute = verify_statute_external_fetch(
        _violation(_stub("AUTH-S-01", "statute")),
        authority_id="AUTH-S-01",
        source_uri=SOURCE_URI,
        source_content=SOURCE,
        target_quote=QUOTE,
        instrument="Código del Trabajo Art. 162",
    )
    assert v16_authority_verification_coherence(statute, {}).status == "pass"


def test_a_quote_the_source_does_not_contain_verifies_nothing():
    """The modal's offset verdict is advisory; the protocol is the gate.

    A paraphrased quote must raise rather than mark a stub verified against a
    quote that was never found — the reviewer is told so before calling, but the
    refusal has to hold on its own.
    """
    with pytest.raises(VerificationError) as excinfo:
        _verify_jurisprudence(target_quote=QUOTE + " del trabajador")
    assert "not found verbatim" in str(excinfo.value)

    with pytest.raises(VerificationError) as excinfo:
        verify_statute_external_fetch(
            _violation(_stub("AUTH-S-01", "statute")),
            authority_id="AUTH-S-01",
            source_uri=SOURCE_URI,
            source_content=SOURCE,
            target_quote=QUOTE + " del trabajador",
            instrument="Código del Trabajo Art. 162",
        )
    assert "not found verbatim" in str(excinfo.value)
