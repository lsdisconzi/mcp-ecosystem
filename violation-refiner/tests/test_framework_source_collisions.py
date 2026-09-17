"""Regression tests for framework-cache articles that share an article number.

The defect this covers, measured on CL-010 on 2026-09-17: the caches are read by
``MarkdownFrameworkSource``, whose primary index is keyed by the *header
identifier* (``'3'``, ``'19.1'``, ``'3 letra b)'``). Two articles in one file can
carry the same identifier, and the later one silently overwrites the earlier, so
only the last survives. ``get_article_body`` was then called with a bare number —
six call sites derived it themselves with ``rsplit('.Art.', 1)`` and threw the
canonical id away — which meant the answer was always "whichever header came
last", never the article the citation named.

On ``CL/L20285_Transparencia.md`` that served the *Principio de Transparencia*
(a 220-char text) for a citation of ``CL.L20285.T1.Art.3``, so CL-010's excerpt
was validated against the wrong article and V03 failed. On ``CL/L19496_LPDC.md``
it served Art. 3 letra b) for a citation of letra e).

The rule pinned here is that a citation naming a canonical id is answered by the
id each article *declares* in its ``**ELI ID:**`` line, not by the number. Three
properties carry it:

* a declared id wins outright, so two articles that share a number are separately
  addressable;
* a citation omitting a hierarchy segment (``CL.LPDC.Art.3.b`` for the declared
  ``CL.LPDC.T1.Art.3.b``) is resolved only when exactly one article matches — an
  omitted segment is resolved, never guessed;
* when nothing matches, the old identifier lookup still answers, because callers
  that hold only a number must keep working. That fallback *is* the old
  behaviour, which is why it is asserted explicitly rather than left implicit.

The synthetic cache is **stipulated** (it is a fixture, not a sample) and carries
one collision per shape: an identical number, and a number reached by an omitted
segment. The corpus tests are **measured** — they read the real cache files and
assert the collisions are still there, so a fixed corpus makes them fail loudly
rather than pass vacuously.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from violation_pack.sources import MarkdownFrameworkSource


ROOT = Path(__file__).resolve().parents[1]
LAW_ROOT = ROOT / "data" / "law"


# Cache files that hold two headers with the same article number, with the
# identifiers they duplicate. Measured 2026-09-17; `L19496_LPDC.md` is *not* here
# because its identifiers ('3 letra b)', '3 letra e)') are already distinct — its
# collision was in the derived *number*, which is a separate test below.
COLLIDED_CACHES = [
    ("CL/L20285_Transparencia.md", "L20285", {"2", "3", "5", "7"}),
    ("BR/L7716_RacialCrime.md", "L7716", {"20"}),
    ("INT/BR/ICAO_Annex6.md", "ICAO_Annex6", {"13.1"}),
    ("INT/EN/ICAO_Annex6.md", "ICAO_Annex6", {"13.1"}),
]

needs_law_cache = pytest.mark.skipif(
    not LAW_ROOT.is_dir(),
    reason=f"the read-only law cache is not in this checkout ({LAW_ROOT})",
)


_SYNTHETIC_CACHE = """# Framework cache (synthetic)

---

### Art. 3 — Derecho de acceso a la información

**Theme:** acceso
**ELI ID:** `CL.LEX.Art.3`

Toda persona tiene derecho a solicitar.

---

### Art. 3 — Principio de Transparencia

**ELI ID:** `CL.LEX.T1.C1.Art.3`

La función pública se ejerce con transparencia.

---

### Art. 3 letra b) — Deber de informarse

**ELI ID:** `CL.LEX.T2.Art.3.b`

El consumidor tiene derecho a informarse.

---

### Art. 99 — Disposición final

**ELI ID:** `CL.LEX.Art.99`

Esta ley entrará en vigencia.
"""

_DERECHO_DE_ACCESO = "Toda persona tiene derecho a solicitar."
_PRINCIPIO = "La función pública se ejerce con transparencia."
_DEBER = "El consumidor tiene derecho a informarse."


def _synthetic(tmp_path: Path) -> MarkdownFrameworkSource:
    path = tmp_path / "LEX.md"
    path.write_text(_SYNTHETIC_CACHE, encoding="utf-8")
    return MarkdownFrameworkSource(path, "LEX", "Legal framework/LEX.md")


def _load(rel: str, code: str) -> MarkdownFrameworkSource:
    path = LAW_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} is not in this checkout")
    return MarkdownFrameworkSource(path, code, f"Legal framework/{code}.md")


# ---------------------------------------------------------------------------
# The rule, on a stipulating fixture
# ---------------------------------------------------------------------------


def test_two_articles_sharing_a_number_are_separately_addressable(tmp_path: Path) -> None:
    source = _synthetic(tmp_path)

    assert source.get_article_body("CL.LEX.Art.3") == _DERECHO_DE_ACCESO
    assert source.get_article_body("CL.LEX.T1.C1.Art.3") == _PRINCIPIO


def test_an_omitted_hierarchy_segment_resolves_when_it_is_unambiguous(tmp_path: Path) -> None:
    source = _synthetic(tmp_path)

    # Declared as CL.LEX.T2.Art.3.b; the citation omits the T2 segment. The tail
    # '3.b' matches exactly one declared id, so it is resolved, not guessed.
    assert source.get_article_body("CL.LEX.Art.3.b") == _DEBER
    # The segment the cache does declare is equally valid.
    assert source.get_article_body("CL.LEX.T2.Art.3.b") == _DEBER


def test_an_ambiguous_tail_is_refused_and_falls_back_to_the_number(tmp_path: Path) -> None:
    source = _synthetic(tmp_path)

    # 'CL.LEX.T9.Art.3' names no declared id, and its tail '3' matches two of
    # them, so resolution refuses it outright...
    assert source._resolve_citation("CL.LEX.T9.Art.3") is None
    # ...and the identifier lookup answers instead, returning the *last* article
    # numbered 3. That is the pre-fix behaviour, kept so a caller holding only a
    # number still works; it is also why a citation that needs a definite answer
    # must pass the id, because this path cannot refuse.
    assert source.get_article_body("CL.LEX.T9.Art.3") == _PRINCIPIO


# ---------------------------------------------------------------------------
# The corpus, as measured
# ---------------------------------------------------------------------------


@needs_law_cache
@pytest.mark.parametrize(
    "rel, code, collided",
    COLLIDED_CACHES,
    ids=[entry[0] for entry in COLLIDED_CACHES],
)
def test_every_declared_id_in_a_collided_cache_resolves_to_its_own_article(
    rel: str, code: str, collided: set[str]
) -> None:
    source = _load(rel, code)
    # Read the private index deliberately: it is the only place the declared ids
    # and bodies are paired, and this test is about exactly that pairing.
    ordered = source._ordered
    identifiers = [identifier for identifier, _, _ in ordered]

    # First, that the collision is still there — otherwise this test would have
    # quietly stopped testing anything.
    assert {i for i in identifiers if identifiers.count(i) > 1} == collided

    declared = [meta["eli_id"] for _, _, meta in ordered]
    assert all(declared), f"{rel}: an article declares no ELI ID"

    # Every article must be reachable by the id it declares, and none may answer
    # with another article's body. Comparing the whole list catches both a
    # citation that resolves to the wrong article and two ids collapsing onto
    # one, without needing to know which article is which.
    assert [source.get_article_body(eli) for eli in declared] == [
        body for _, body, _ in ordered
    ]


@needs_law_cache
def test_the_two_transparency_law_editions_are_separately_addressable() -> None:
    source = _load("CL/L20285_Transparencia.md", "L20285")

    current = source.get_article_body("CL.L20285.T1.Art.3")
    earlier = source.get_article_body("CL.L20285.T1.C1.Art.3")

    assert current is not None and current.startswith("Toda persona tiene derecho a solicitar")
    assert earlier is not None and earlier.startswith(
        "Artículo 3° - Principio de Transparencia"
    )
    assert current != earlier

    # The identifier lookup can only ever reach the last of them. This is the
    # exact answer CL-010's excerpt used to be validated against, and it is why
    # the number path cannot be trusted to identify an article.
    assert source.get_article_body("3") == earlier


@needs_law_cache
def test_lpdc_art_3_letras_are_separately_addressable() -> None:
    source = _load("CL/L19496_LPDC.md", "LPDC")

    letra_b = source.get_article_body("CL.LPDC.Art.3.b")
    letra_e = source.get_article_body("CL.LPDC.Art.3.e")

    # Both entries open with the same Art. 3 header line, so an equality test on
    # a prefix would pass on either; the bodies must differ in length and text.
    assert letra_b is not None and letra_e is not None
    assert letra_b != letra_e
    # The cache declares both with a T1 segment the citations omit.
    assert source.get_article_body("CL.LPDC.T1.Art.3.b") == letra_b
    assert source.get_article_body("CL.LPDC.T1.Art.3.e") == letra_e


@needs_law_cache
def test_a_bare_number_is_unchanged_where_it_is_unambiguous() -> None:
    source = _load("CL/L20285_Transparencia.md", "L20285")

    # Art. 19 is numbered once, so the fallback still answers — the fix changes
    # only the citations the identifier key could not answer correctly.
    body = source.get_article_body("19")
    assert body is not None and body.startswith("Esta ley entrará en vigencia")
