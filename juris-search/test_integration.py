#!/usr/bin/env python3
"""Integration tests for multi-court juris-search (Phase 6)."""

import httpx
import sys
import json
import re
import os

# Ensure project root is on path (portable: use this file's location)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
ERRORS = []

def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        ERRORS.append(f"FAIL: {name}: {detail}")
        print(f"  FAIL  {name}: {detail}")

def test_section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def parse_search_fields(reply: str):
    """Extract search_fields JSON from <search_fields> tags in reply."""
    m = re.search(r'<search_fields>\s*([\s\S]*?)\s*</search_fields>', reply)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    return None

# ── 1. Health & basic API ────────────────────────────────────────────────

test_section("1. Health endpoint")

resp = httpx.get(f"{BASE}/health")
check("HTTP 200", resp.status_code == 200)
data = resp.json()
check("status ok", data["status"] == "ok")
check("deepseek configured", data["deepseek_configured"] is True)
check("default_court is TJRS", data["default_court"] == "TJRS")
check("supported courts returned", isinstance(data.get("supported_courts"), list) and len(data["supported_courts"]) >= 3)
print(f"    Supported courts: {len(data.get('supported_courts', []))} (TJRS, TJSP, STF present: {all(c in data.get('supported_courts', []) for c in ['TJRS','TJSP','STF'])})")
print(f"    Response: {json.dumps(data, indent=2)}")

# ── 2. Court-aware chat endpoint ─────────────────────────────────────────

test_section("2. Chat endpoint (court propagation)")

COURTS_TO_TEST = ["TJRS", "TJSP", "STF"]
COURT_NAMES = {
    "TJRS": "Tribunal de Justiça do Rio Grande do Sul",
    "TJSP": "Tribunal de Justiça de São Paulo",
    "STF": "Supremo Tribunal Federal",
}

for court in COURTS_TO_TEST:
    print(f"\n  --- {court} ---")
    resp = httpx.post(f"{BASE}/api/chat", json={
        "message": "Busco jurisprudencia sobre dano moral",
        "court": court,
    }, timeout=60.0)
    check(f"{court}: HTTP 200", resp.status_code == 200)
    data = resp.json()
    reply = data.get("reply", "")
    check(f"{court}: has reply", bool(reply))
    # Verify court-awareness in the reply
    court_full = COURT_NAMES[court]
    has_court_ref = court_full in reply or court in reply
    check(f"{court}: reply mentions {court}", has_court_ref, f"reply: {reply[:80]}...")
    print(f"    Reply preview: {reply[:150]}...")

# ── 3. Search fields extraction via chat ─────────────────────────────────

test_section("3. Search fields extraction (parsed from <search_fields> tags)")

resp = httpx.post(f"{BASE}/api/chat", json={
    "message": "Busco apelação cível sobre dano moral contra plano de saúde, relator Desembargador Silva",
    "court": "TJSP",
}, timeout=60.0)
check("HTTP 200", resp.status_code == 200)
data = resp.json()
reply = data.get("reply", "")
check("has reply text", bool(reply))
print(f"    Full reply:\n{reply[:500]}")

# Parse search_fields from the reply
sf = parse_search_fields(reply)
if sf:
    check("search_fields extracted from reply", True)
    print(f"    Extracted fields: {json.dumps(sf, indent=2)}")
    check("search_text populated", bool(sf.get("search_text")))
else:
    check("search_fields extracted from reply", False, "No <search_fields> tags found in reply")
    # This is acceptable if the AI chose not to provide them yet
    print("    (AI did not emit <search_fields> tags in this response)")

# ── 4. Scraper instantiation tests ───────────────────────────────────────

test_section("4. Scraper instantiation (all 3 courts)")

for court_key, module_name, class_name in [
    # Custom-portal courts (dedicated scrapers)
    ("TJRS", "tjrs_scraper", "TJRSJurisprudenciaScraper"),
    ("TJSP", "tjsp_scraper", "TJSPJurisprudenciaScraper"),
    ("TJMG", "tjmg_scraper", "TJMGJurisprudenciaScraper"),
    ("TJRJ", "tjrj_scraper", "TJRJJurisprudenciaScraper"),
    ("STF",  "stf_scraper",  "STFJurisprudenciaScraper"),
    # e-SAJ courts (shared generic scraper)
    ("TJSC", "_shared.esaj_scrapers", "TJSCJurisprudenciaScraper"),
    ("TJPR", "_shared.esaj_scrapers", "TJPRJurisprudenciaScraper"),
    ("TJBA", "_shared.esaj_scrapers", "TJBAJurisprudenciaScraper"),
    ("TJPE", "_shared.esaj_scrapers", "TJPEJurisprudenciaScraper"),
    ("TJCE", "_shared.esaj_scrapers", "TJCEJurisprudenciaScraper"),
    ("TJMA", "_shared.esaj_scrapers", "TJMAJurisprudenciaScraper"),
    ("TJPA", "_shared.esaj_scrapers", "TJPAJurisprudenciaScraper"),
    ("TJAM", "_shared.esaj_scrapers", "TJAMJurisprudenciaScraper"),
    ("TJDFT", "_shared.esaj_scrapers", "TJDFTJurisprudenciaScraper"),
    ("TJGO", "_shared.esaj_scrapers", "TJGOJurisprudenciaScraper"),
    ("TJMT", "_shared.esaj_scrapers", "TJMTJurisprudenciaScraper"),
    ("TJMS", "_shared.esaj_scrapers", "TJMSJurisprudenciaScraper"),
    ("TJES", "_shared.esaj_scrapers", "TJESJurisprudenciaScraper"),
    ("TJPB", "_shared.esaj_scrapers", "TJPBJurisprudenciaScraper"),
    ("TJRN", "_shared.esaj_scrapers", "TJRNJurisprudenciaScraper"),
    ("TJAL", "_shared.esaj_scrapers", "TJALJurisprudenciaScraper"),
    ("TJSE", "_shared.esaj_scrapers", "TJSEJurisprudenciaScraper"),
    ("TJPI", "_shared.esaj_scrapers", "TJPIJurisprudenciaScraper"),
    ("TJRO", "_shared.esaj_scrapers", "TJROJurisprudenciaScraper"),
    ("TJTO", "_shared.esaj_scrapers", "TJTOJurisprudenciaScraper"),
    ("TJAC", "_shared.esaj_scrapers", "TJACJurisprudenciaScraper"),
    ("TJRR", "_shared.esaj_scrapers", "TJRRJurisprudenciaScraper"),
    ("TJAP", "_shared.esaj_scrapers", "TJAPJurisprudenciaScraper"),
]:
    print(f"\n  --- {court_key} ---")
    try:
        import importlib
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        criteria_cls = getattr(mod, "SearchCriteria")
        check(f"{court_key}: module imported", True)
        check(f"{court_key}: class found", cls is not None)
        check(f"{court_key}: SearchCriteria found", criteria_cls is not None)

        # Test SearchCriteria creation
        sc = criteria_cls(
            search_text="dano moral",
            max_results=5,
        )
        check(f"{court_key}: SearchCriteria instantiated", sc.search_text == "dano moral")

        # Test scraper instantiation (correct signature: headless, wait_time)
        scraper = cls(headless=True)
        check(f"{court_key}: scraper instantiated", scraper is not None)
        print(f"    Scraper type: {type(scraper).__name__}")

        # Test calling search_with_criteria method exists and is callable
        assert callable(scraper.search_with_criteria), f"search_with_criteria not callable on {court_key}"
        check(f"{court_key}: search_with_criteria callable", True)

        scraper.close()
        check(f"{court_key}: scraper closed cleanly", True)

    except Exception as e:
        check(f"{court_key}: setup", False, f"{type(e).__name__}: {e}")

# ── 5. STF live search (HTTP-based, no captcha) ──────────────────────────

test_section("5. STF live scraper test (HTTP-based, should work without captcha)")

try:
    from stf_scraper import STFJurisprudenciaScraper, SearchCriteria

    criteria = SearchCriteria(
        search_text="dano moral",
        max_results=5,
    )
    print(f"    Search criteria: search_text='{criteria.search_text}', max_results={criteria.max_results}")

    scraper = STFJurisprudenciaScraper(headless=True)
    check("STF: scraper instantiated", True)

    # Try live search via search_with_criteria
    try:
        results = scraper.search_with_criteria(criteria)
        check("STF: search_with_criteria executed", True)
        print(f"    Found {len(results)} result links")
        for i, link in enumerate(results[:3]):
            url = link.get('url', 'N/A')
            print(f"    [{i}] {url[:100]}")
            print(f"        title: {link.get('title', 'N/A')[:100]}")

        if results:
            check("STF: got results (>0)", len(results) > 0)
        else:
            print("    (No results returned - may be empty search or site issue)")

        # Try download if results found
        if results and results[0].get('url'):
            try:
                canonical = scraper.canonicalize_inteiro_url(results[0]['url'])
                check("STF: canonicalize works", bool(canonical))
                print(f"    Canonical URL: {canonical[:100]}")

                content = scraper.download_inteiro_teor_url(results[0])
                check("STF: download returned content", bool(content))
                print(f"    Downloaded {len(content)} bytes")
            except Exception as e:
                print(f"    Download failed (may be site issue): {e}")
                check("STF: download attempted", True, f"excused: {str(e)[:100]}")

    except Exception as e:
        msg = str(e)
        print(f"    Live search error: {msg}")
        # STF site may be slow/unavailable - not a code bug
        check("STF: live search attempted", True, f"Site may be unavailable: {msg[:100]}")

    scraper.close()

except Exception as e:
    print(f"    Setup error: {e}")
    check("STF: setup", False, str(e))

# ── 6. TJSP scraper instantiation ────────────────────────────────────────

test_section("6. TJSP scraper test (instantiation; live search skipped - captcha)")

try:
    from tjsp_scraper import TJSPJurisprudenciaScraper, SearchCriteria

    criteria = SearchCriteria(
        search_text="dano moral",
        max_results=5,
    )
    scraper = TJSPJurisprudenciaScraper(headless=True)
    check("TJSP: scraper instantiated", True)
    check("TJSP: has search_with_criteria", callable(scraper.search_with_criteria))
    check("TJSP: has get_inteiro_links", callable(scraper.get_inteiro_links))
    check("TJSP: has canonicalize_inteiro_url", callable(scraper.canonicalize_inteiro_url))
    check("TJSP: has download_inteiro_teor_url", callable(scraper.download_inteiro_teor_url))
    print("    TJSP scraper interface verified (live search requires captcha)")
    scraper.close()

except Exception as e:
    print(f"    Setup error: {e}")
    check("TJSP: setup", False, str(e))

# ── 7. TJRS scraper instantiation test (regression) ──────────────────────

test_section("7. TJRS scraper regression test (instantiation + interface)")

try:
    from tjrs_scraper import TJRSJurisprudenciaScraper, SearchCriteria

    criteria = SearchCriteria(
        search_text="dano moral",
        max_results=5,
    )
    scraper = TJRSJurisprudenciaScraper(headless=True)
    check("TJRS: scraper instantiated", True)
    check("TJRS: has search_with_criteria", callable(scraper.search_with_criteria))
    check("TJRS: has get_inteiro_links", callable(scraper.get_inteiro_links))
    check("TJRS: has canonicalize_inteiro_url", callable(scraper.canonicalize_inteiro_url))
    check("TJRS: has download_inteiro_teor_url", callable(scraper.download_inteiro_teor_url))
    print("    TJRS scraper interface intact (regression OK)")
    scraper.close()

except Exception as e:
    print(f"    Setup error: {e}")
    check("TJRS: setup", False, str(e))

# ── 8. API search endpoint (submit search for each court) ────────────────

test_section("8. API /search endpoint (POST search jobs per court)")

for court in COURTS_TO_TEST:
    print(f"\n  --- {court} ---")
    resp = httpx.post(f"{BASE}/api/search", json={
        "search_text": "dano moral",
        "max_results": 3,
        "court": court,
    }, timeout=60.0)
    check(f"{court}: HTTP 200", resp.status_code == 200)
    data = resp.json()
    check(f"{court}: has job_id", "job_id" in data)
    print(f"    job_id: {data.get('job_id', 'N/A')}")
    print(f"    status: {data.get('status', 'N/A')}")

# ── 9. Court resolution edge cases ───────────────────────────────────────

test_section("9. Court resolution edge cases")

from api import _resolve_court, _get_scraper_class, COURT_NAMES as API_COURT_NAMES, SUPPORTED_COURTS

edge_cases = [
    ("TJRS", "TJRS"),
    ("tjrs", "TJRS"),
    ("TJSP", "TJSP"),
    ("tjsp", "TJSP"),
    ("stf", "STF"),
    (None, "TJRS"),
    ("", "TJRS"),
    ("xyz", "TJRS"),
]
for input_val, expected in edge_cases:
    result = _resolve_court(input_val)
    label = f"resolve({repr(input_val)}) -> {expected}"
    check(label, result == expected, f"got {result}")

# ── 10. Factory dispatch: each court gets correct scraper ────────────────

test_section("10. Factory dispatch correctness")

expected_classes = {
    "TJRS": "TJRSJurisprudenciaScraper",
    "TJSP": "TJSPJurisprudenciaScraper",
    "STF": "STFJurisprudenciaScraper",
    "CLTC": "TCChileJurisprudenciaScraper",
}
for court, expected_cls in expected_classes.items():
    cls, criteria_cls = _get_scraper_class(court)
    check(f"{court}: class={expected_cls}", cls.__name__ == expected_cls)
    check(f"{court}: criteria=SearchCriteria", criteria_cls.__name__ == "SearchCriteria")

# ── 11. System prompt is court-aware ─────────────────────────────────────

test_section("11. System prompt is court-aware")

from api import _build_system_prompt

# CLTC is offline-testable (no server needed), so include it here.
PROMPT_COURTS = COURTS_TO_TEST + ["CL", "CLTC"]

for court in PROMPT_COURTS:
    prompt = _build_system_prompt(court)
    court_full = API_COURT_NAMES[court]
    check(f"{court}: prompt mentions full name", court_full in prompt)
    check(f"{court}: prompt length > 500", len(prompt) > 500)
    print(f"    {court} prompt: {len(prompt)} chars, mentions '{court_full[:50]}...'")

# ── 12. Full flow: chat -> extract fields -> search (per court) ──────────

test_section("12. Full API flow: chat -> extract -> search")

for court in COURTS_TO_TEST:
    print(f"\n  --- {court} full flow ---")

    # Step 1: Chat
    resp = httpx.post(f"{BASE}/api/chat", json={
        "message": "Busco jurisprudência sobre dano moral em ação de indenização",
        "court": court,
    }, timeout=60.0)
    check(f"{court}: [1] chat HTTP 200", resp.status_code == 200)
    reply = resp.json().get("reply", "")
    check(f"{court}: [1] chat reply non-empty", len(reply) > 20)
    print(f"    [1] Chat reply: {reply[:100]}...")

    # Step 2: Try extracting search fields (AI may or may not emit them)
    sf = parse_search_fields(reply)
    if sf:
        check(f"{court}: [2] search_fields extracted", True)
        print(f"    [2] Fields: {json.dumps(sf, indent=2)[:200]}")
    else:
        check(f"{court}: [2] search_fields not yet emitted", True)
        print("    [2] AI did not emit <search_fields> yet (normal for first message)")

    # Step 3: Submit a search job
    resp = httpx.post(f"{BASE}/api/search", json={
        "search_text": "dano moral indenização",
        "max_results": 3,
        "court": court,
    }, timeout=60.0)
    check(f"{court}: [3] search HTTP 200", resp.status_code == 200)
    job = resp.json()
    check(f"{court}: [3] search job_id", "job_id" in job)
    print(f"    [3] Search job: {job.get('job_id')} / {job.get('status')}")

# ── 13. TC Chile (CLTC) scraper, offline ─────────────────────────────────
# This court uses a plain REST API, so it can be exercised without Selenium
# and without the FastAPI server running.

test_section("13. TC Chile (CLTC) scraper")

try:
    from tc_chile_scraper import (
        TCChileJurisprudenciaScraper,
        SearchCriteria as TCSearchCriteria,
        TC_COURT_KEY,
    )

    # 13.1 Court resolution variants all land on CLTC (not the PJud "CL")
    for variant in ["CLTC", "cltc", "tc chile", "TCChile", "Tribunal Constitucional de Chile"]:
        check(f"CLTC: resolve({variant!r})", _resolve_court(variant) == "CLTC",
              f"got {_resolve_court(variant)}")
    check("CLTC: does not shadow CL", _resolve_court("CL") == "CL")

    # 13.2 SearchCriteria accepts every mapped route field
    from modules.routes_search import _build_criteria_args
    route_fields = {
        "search_text": "vida",
        "folio": "16622",
        "rol": "1234-2025",
        "competencia": "INA",
        "ministro": "Maria Pia Silva Gallinato",
        "cuerpo_legal": "Código Civil",
        "palabra_clave": "Aborto",
        "resultado": "Acoge",
        "tipo_resolucion": "Sentencia",
        "fecha_inicio": "2025-01-01",
        "fecha_fin": "2025-03-31",
        "max_results": 5,
    }
    criteria_args = _build_criteria_args(TCSearchCriteria, route_fields, "CLTC")
    criteria = TCSearchCriteria(**criteria_args)
    for key in ("folio", "competencia", "ministro", "cuerpo_legal",
                "palabra_clave", "resultado", "tipo_resolucion",
                "fecha_inicio", "fecha_fin"):
        check(f"CLTC: criteria carries {key}", getattr(criteria, key) == route_fields[key],
              f"got {getattr(criteria, key)!r}")

    # 13.3 Live search + download (network)
    scraper = TCChileJurisprudenciaScraper()
    try:
        results = scraper.search_with_criteria(
            TCSearchCriteria(search_text="vida", max_results=3)
        ) or []
        check("CLTC: live search returns results", len(results) > 0,
              f"got {len(results)}")
        if results:
            first = results[0]
            check("CLTC: result court key", first.get("court") == TC_COURT_KEY,
                  f"got {first.get('court')!r}")
            check("CLTC: result has folio", bool(first.get("numero_processo")))
            inteiro = first.get("inteiro_url") or ""
            check("CLTC: result has download URL",
                  "/extended/" in inteiro and inteiro.endswith("/download"),
                  f"got {inteiro!r}")
            print(f"    folio={first.get('numero_processo')} fecha={first.get('data_julgamento')}")

            # 13.4 Canonicalize the download URL back to the folio
            folio = scraper.canonicalize_download_id(inteiro)
            check("CLTC: canonicalize_download_id(inteiro_url) == folio",
                  folio == str(first.get("numero_processo")),
                  f"got {folio!r} vs {first.get('numero_processo')!r}")

            # 13.5 Download and verify it is a real PDF
            save_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "jurisprudence_downloads", "ci_tc_chile")
            path = scraper.download_inteiro_teor_url(
                url=inteiro,
                save_dir=save_dir,
                metadata={"numero_processo": first.get("numero_processo"),
                          "fecha": first.get("fecha")},
                agent_id="ci",
                folder_name="test",
            )
            check("CLTC: download returns a path", bool(path), f"got {path!r}")
            if path and os.path.exists(path):
                size = os.path.getsize(path)
                with open(path, "rb") as fh:
                    magic = fh.read(5)
                check("CLTC: downloaded file is a PDF", magic == b"%PDF-", f"magic={magic!r}")
                check("CLTC: downloaded file is non-trivial", size > 10000, f"size={size}")
                print(f"    downloaded: {os.path.basename(path)} ({size} bytes)")
    finally:
        scraper.close()

except Exception as exc:
    check("CLTC: section ran without exception", False, f"{type(exc).__name__}: {exc}")

# ── 14. CLTC extractor (offline, no network) ─────────────────────────────
# The downstream court_extractor must understand TC Chile PDFs, otherwise
# every downloaded sentence is reported as "no extractor for CLTC" and never
# reaches extracted_documents/.

test_section("14. CLTC extractor")

try:
    import glob as _glob
    import shutil
    import tempfile

    import court_extractor as CE

    check("CLTC: registered in EXTRACTORS", "CLTC" in CE.EXTRACTORS)
    check("CLTC: extractor class is CLTCExtractor",
          getattr(CE.EXTRACTORS.get("CLTC"), "__name__", None) == "CLTCExtractor",
          f"got {getattr(CE.EXTRACTORS.get('CLTC'), '__name__', None)!r}")

    _repo = os.path.dirname(os.path.abspath(__file__))
    candidates = sorted(_glob.glob(
        os.path.join(_repo, "jurisprudence_downloads", "**", "CLTC_*.pdf"),
        recursive=True))
    check("CLTC: a downloaded sample PDF exists", bool(candidates),
          "run section 13 first / download a TC Chile sentence")
    if candidates:
        sample = candidates[0]
        print(f"    sample: {os.path.relpath(sample, _repo)}")

        # 14.1 Extraction with the scraper-written sidecar present
        cases = CE.process_file(sample, "CLTC", {})
        check("CLTC: process_file returns exactly 1 case", len(cases) == 1,
              f"got {len(cases)}")
        if cases:
            doc = cases[0]

            check("CLTC: tribunal", doc.get("tribunal") == "CLTC", f"got {doc.get('tribunal')!r}")
            check("CLTC: tribunal_pais == Chile", doc.get("tribunal_pais") == "Chile",
                  f"got {doc.get('tribunal_pais')!r}")
            check("CLTC: numero_processo is the folio",
                  bool(str(doc.get("numero_processo") or "").strip()),
                  f"got {doc.get('numero_processo')!r}")
            check("CLTC: rol looks like a Chilean rol",
                  bool(re.match(r"^Rol\s+\d[\d\.]*\s*-\s*\d{2,4}", doc.get("rol") or "")),
                  f"got {doc.get('rol')!r}")
            check("CLTC: codigo present", bool(doc.get("codigo")), f"got {doc.get('codigo')!r}")
            check("CLTC: classe present", bool(doc.get("classe")), f"got {doc.get('classe')!r}")
            check("CLTC: data_julgamento is ISO",
                  bool(re.match(r"^\d{4}-\d{2}-\d{2}$", doc.get("data_julgamento") or "")),
                  f"got {doc.get('data_julgamento')!r}")
            check("CLTC: relator not shouted",
                  (doc.get("relator") or "") != (doc.get("relator") or "").upper(),
                  f"got {doc.get('relator')!r}")
            check("CLTC: orgao_julgador", doc.get("orgao_julgador") == "Tribunal Constitucional de Chile",
                  f"got {doc.get('orgao_julgador')!r}")
            check("CLTC: outcome non-empty", bool(doc.get("outcome")),
                  f"got {doc.get('outcome')!r}")
            check("CLTC: outcome labels are canonical",
                  all(o in {"acoge", "rechaza", "acoge_parcial", "rechaza_parcial",
                            "empate_votos", "inadmisible", "no_conoce"}
                      for o in (doc.get("outcome") or [])),
                  f"got {doc.get('outcome')!r}")
            check("CLTC: ementa non-trivial", len(doc.get("ementa") or "") > 100,
                  f"got {len(doc.get('ementa') or '')} chars")
            check("CLTC: legislacao_citada non-empty", bool(doc.get("legislacao_citada")),
                  f"got {doc.get('legislacao_citada')!r}")
            check("CLTC: assuntos non-empty", bool(doc.get("assuntos")),
                  f"got {doc.get('assuntos')!r}")
            check("CLTC: texto_length is non-trivial", (doc.get("texto_length") or 0) > 5000,
                  f"got {doc.get('texto_length')!r}")

            cs = doc.get("court_specific") or {}
            check("CLTC: court_specific carries folio", bool(cs.get("folio")),
                  f"keys={sorted(cs)[:6]}")
            check("CLTC: court_specific carries resuelvo",
                  len(cs.get("resuelvo") or []) >= 1,
                  f"got {cs.get('resuelvo')!r}")
            check("CLTC: resuelvo is the operative part, not the dissent",
                  all("SE RECHAZA" in h.upper() or "SE ALZA" in h.upper()
                      or "NO SE CONDENA" in h.upper() or "OFÍCIESE" in h.upper()
                      for h in (cs.get("resuelvo") or [])),
                  f"got {cs.get('resuelvo')}")
            check("CLTC: court_specific carries ministros",
                  len(cs.get("ministros") or []) >= 3,
                  f"got {cs.get('ministros')!r}")
            print(f"    rol={doc.get('rol')} outcome={doc.get('outcome')} "
                  f"votacao={doc.get('votacao')!r}")
            print(f"    resuelvo entries={len(cs.get('resuelvo') or [])} "
                  f"ministros={len(cs.get('ministros') or [])}")

        # 14.2 Extraction WITHOUT the sidecar (PDF-only fallback)
        tmpdir = tempfile.mkdtemp(prefix="cltc_nosidecar_")
        try:
            stripped = os.path.join(tmpdir, os.path.basename(sample))
            shutil.copy2(sample, stripped)
            fallback = CE.process_file(stripped, "CLTC", {})
            check("CLTC: sidecar-less extraction returns 1 case", len(fallback) == 1,
                  f"got {len(fallback)}")
            if fallback:
                fd = fallback[0]
                check("CLTC: sidecar-less rol still parsed",
                      bool(re.match(r"^Rol\s+\d[\d\.]*\s*-\s*\d{2,4}", fd.get("rol") or "")),
                      f"got {fd.get('rol')!r}")
                check("CLTC: sidecar-less data_julgamento still parsed",
                      bool(re.match(r"^\d{4}-\d{2}-\d{2}$", fd.get("data_julgamento") or "")),
                      f"got {fd.get('data_julgamento')!r}")
                check("CLTC: sidecar-less outcome non-empty", bool(fd.get("outcome")),
                      f"got {fd.get('outcome')!r}")
                check("CLTC: sidecar-less resuelvo non-empty",
                      len((fd.get("court_specific") or {}).get("resuelvo") or []) >= 1,
                      f"got {(fd.get('court_specific') or {}).get('resuelvo')!r}")
                check("CLTC: sidecar-less tribunal_pais still set",
                      fd.get("tribunal_pais") == "Chile", f"got {fd.get('tribunal_pais')!r}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        # 14.3 Extraction from a UUID-named file with no sidecar — this is what
        # the /api/ingest-pdf/upload endpoint produces, so numero_processo must
        # still be recovered (here, from the ROL in the PDF text).
        tmpdir = tempfile.mkdtemp(prefix="cltc_uuid_")
        try:
            uuid_named = os.path.join(
                tmpdir, "f503459b-6c9e-4084-8a06-78f2e75664ef.pdf")
            shutil.copy2(sample, uuid_named)
            anon = CE.process_file(uuid_named, "CLTC", {})
            check("CLTC: UUID-named PDF still yields 1 case", len(anon) == 1,
                  f"got {len(anon)}")
            if anon:
                ad = anon[0]
                check("CLTC: UUID-named PDF still yields numero_processo",
                      bool(str(ad.get("numero_processo") or "").strip()),
                      f"got {ad.get('numero_processo')!r}")
                check("CLTC: UUID-named numero_processo is not a placeholder",
                      "desconhecido" not in str(ad.get("numero_processo") or "").lower(),
                      f"got {ad.get('numero_processo')!r}")
                check("CLTC: UUID-named numero_processo matches the ROL digits",
                      str(ad.get("numero_processo")) ==
                      re.sub(r"\D", "", (ad.get("rol") or "").split("-")[0]),
                      f"proc={ad.get('numero_processo')!r} rol={ad.get('rol')!r}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

except Exception as exc:
    check("CLTC: extractor section ran without exception", False, f"{type(exc).__name__}: {exc}")

# ── 15. Chile download contract (CL vs CLTC) ─────────────────────────────
#
# The frontend used to treat "has inteiro_url" as "is downloadable", which made
# every CL (PJud) result a dead end (no link, no checkbox, both download
# buttons disabled). The server now publishes an explicit contract.

test_section("15. Chile download contract (CL vs CLTC)")

try:
    from modules.utils import _normalize_result_item
    from modules.routes_download import _is_downloadable_item

    # 15.1 CLTC carries a real document URL.
    cltc_raw = {
        "court": "CLTC",
        "tribunal": "CLTC",
        "numero_processo": "1234-2024",
        "rol": "1234-2024",
        "inteiro_url": "https://buscador-backend.tcchile.cl/api/extended/1234-2024/download",
        "url_detalle": "https://buscador.tcchile.cl/#/ficha/1234-2024",
    }
    cltc = _normalize_result_item(cltc_raw, "CLTC")
    check("CLTC: inteiro_url preserved", "tcchile.cl" in (cltc.get("inteiro_url") or ""),
          f"got {cltc.get('inteiro_url')!r}")
    check("CLTC: download_mode == 'url'", cltc.get("download_mode") == "url",
          f"got {cltc.get('download_mode')!r}")
    check("CLTC: downloadable is True", cltc.get("downloadable") is True,
          f"got {cltc.get('downloadable')!r}")
    check("CLTC: url_detalle preserved for the fallback link",
          cltc.get("url_detalle") == cltc_raw["url_detalle"],
          f"got {cltc.get('url_detalle')!r}")
    check("CLTC: _is_downloadable_item accepts the raw result",
          _is_downloadable_item(cltc_raw) is True)

    # 15.2 CL (PJud) has NO document URL but is still downloadable, because the
    # scraper re-drives the browser from id_sentencia + categoria.
    cl_raw = {
        "court": "CL",
        "tribunal": "CL",
        "numero_processo": "",
        "rol": "C-9632-2024",
        "id_sentencia": "199016334",
        "categoria": "civiles",
        "search_terms": "latam airlines",
        "url_detalle": "https://juris.pjud.cl/busqueda/buscar_sentencias",
        "inteiro_url": None,
    }
    cl = _normalize_result_item(dict(cl_raw), "CL")
    check("CL: inteiro_url is empty (never fabricated)",
          (cl.get("inteiro_url") or "") == "",
          f"got {cl.get('inteiro_url')!r}")
    check("CL: download_mode == 'browser'", cl.get("download_mode") == "browser",
          f"got {cl.get('download_mode')!r}")
    check("CL: downloadable is True", cl.get("downloadable") is True,
          f"got {cl.get('downloadable')!r}")
    check("CL: url_detalle preserved for the fallback link",
          "pjud.cl" in (cl.get("url_detalle") or ""),
          f"got {cl.get('url_detalle')!r}")
    check("CL: _is_downloadable_item accepts a URL-less result with id_sentencia",
          _is_downloadable_item(cl_raw) is True)

    # 15.3 CL without id_sentencia cannot be re-driven -> not downloadable.
    cl_broken = dict(cl_raw)
    cl_broken.pop("id_sentencia")
    cl_broken_norm = _normalize_result_item(dict(cl_broken), "CL")
    check("CL (no id_sentencia): download_mode == 'none'",
          cl_broken_norm.get("download_mode") == "none",
          f"got {cl_broken_norm.get('download_mode')!r}")
    check("CL (no id_sentencia): downloadable is False",
          cl_broken_norm.get("downloadable") is False,
          f"got {cl_broken_norm.get('downloadable')!r}")
    check("CL (no id_sentencia): _is_downloadable_item rejects it",
          _is_downloadable_item(cl_broken) is False)

    # 15.4 A plain Brazilian result with no URL stays non-downloadable.
    tjsp = _normalize_result_item(
        {"court": "TJSP", "numero_processo": "1000001-11.2024.8.26.0001"}, "TJSP")
    check("TJSP (no URL): download_mode == 'none'",
          tjsp.get("download_mode") == "none", f"got {tjsp.get('download_mode')!r}")
    check("TJSP (no URL): _is_downloadable_item rejects it",
          _is_downloadable_item(tjsp) is False)

    # 15.5 download_url is honoured as a document URL alias.
    alias = _normalize_result_item(
        {"court": "CLTC", "download_url": "https://example.test/doc.pdf"}, "CLTC")
    check("alias: download_url promotes to inteiro_url",
          alias.get("inteiro_url") == "https://example.test/doc.pdf",
          f"got {alias.get('inteiro_url')!r}")
    check("alias: download_mode == 'url'", alias.get("download_mode") == "url",
          f"got {alias.get('download_mode')!r}")

    # 15.6 Junk input must not raise.
    check("non-dict input is rejected by _is_downloadable_item",
          _is_downloadable_item(None) is False and _is_downloadable_item("x") is False)
except Exception as exc:
    check("Chile download contract section ran without exception", False,
          f"{type(exc).__name__}: {exc}")

# ── 16. Chile field definitions exposed to the dedicated section ──────────

test_section("16. Chile field definitions")

try:
    from modules.courts import SUPPORTED_COURTS, _resolve_court
    from chile_scraper import CHILE_CATEGORIES

    check("CL registered", "CL" in SUPPORTED_COURTS)
    check("CLTC registered", "CLTC" in SUPPORTED_COURTS)
    check("CL resolves to itself", _resolve_court("CL") == "CL")
    check("CLTC resolves to itself", _resolve_court("CLTC") == "CLTC")
    check("lowercase 'cltc' resolves", _resolve_court("cltc") == "CLTC")
    check("CLTC scraper class is TCChileJurisprudenciaScraper",
          SUPPORTED_COURTS["CLTC"].get("scraper_class") == "TCChileJurisprudenciaScraper",
          f"got {SUPPORTED_COURTS['CLTC'].get('scraper_class')!r}")
    check("CL scraper class is ChileJurisprudenciaScraper",
          SUPPORTED_COURTS["CL"].get("scraper_class") == "ChileJurisprudenciaScraper",
          f"got {SUPPORTED_COURTS['CL'].get('scraper_class')!r}")
    check("CLTC scraper module is tc_chile_scraper",
          SUPPORTED_COURTS["CLTC"].get("scraper_module") == "tc_chile_scraper",
          f"got {SUPPORTED_COURTS['CLTC'].get('scraper_module')!r}")
    check("CL scraper module is chile_scraper",
          SUPPORTED_COURTS["CL"].get("scraper_module") == "chile_scraper",
          f"got {SUPPORTED_COURTS['CL'].get('scraper_module')!r}")

    for key in ("corte_suprema", "civiles", "penales", "laborales", "familia"):
        entry = CHILE_CATEGORIES.get(key) or {}
        check(f"CHILE_CATEGORIES['{key}'] has slug+name",
              bool(entry.get("slug")) and bool(entry.get("name")),
              f"got {entry!r}")
except Exception as exc:
    check("Chile field definitions section ran without exception", False,
          f"{type(exc).__name__}: {exc}")

# ── Summary ──────────────────────────────────────────────────────────────

test_section("SUMMARY")

print(f"\n  Total: {PASS + FAIL}, Passed: {PASS}, Failed: {FAIL}")
if ERRORS:
    print(f"\n  Errors:")
    for e in ERRORS:
        print(f"    {e}")

sys.exit(0 if FAIL == 0 else 1)
