"""Phase 3 final — end-to-end validation through the PRODUCTION code path.

Calls `TJSPJurisprudenciaScraper.search_with_criteria()` exactly as
modules/routes_search.py::_run_scraper does, and checks that a judgement-date
window actually constrains the returned decisions.

Usage:  .venv/bin/python .dev/validate_tjsp_e2e.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tjsp_scraper import TJSPJurisprudenciaScraper, SearchCriteria

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

QUERY = "dano moral"
MAX = 20

SCENARIOS = [
    ("3.1 no window", None, None),
    ("3.2 window 2024-01-01..2024-03-31", "2024-01-01", "2024-03-31"),
    ("3.3 window 2001-01-01..2001-01-31", "2001-01-01", "2001-01-31"),
]


def iso(dd: str) -> str:
    """'21/03/2024' -> '2024-03-21'"""
    day, mon, yr = dd.split("/")
    return f"{yr}-{mon}-{day}"


def main() -> int:
    scraper = TJSPJurisprudenciaScraper(headless=True)
    summary = {}
    try:
        for label, di, df in SCENARIOS:
            criteria = SearchCriteria(
                search_text=QUERY,
                tipo_decisao="acórdão",
                data_julgamento_inicio=di,
                data_julgamento_fim=df,
                max_results=MAX,
            )
            print(f"\n=== {label} ===", flush=True)
            try:
                items = scraper.search_with_criteria(criteria) or []
            except Exception as exc:  # noqa: BLE001
                print(f"  ERROR: {exc!r}", flush=True)
                summary[label] = None
                continue

            dates = [str(i.get("data_julgamento") or "").strip() for i in items]
            dates = [d for d in dates if d]
            inside = None
            if di and df and dates:
                inside = all(di <= iso(d) <= df for d in dates)

            summary[label] = {"n": len(items), "inside": inside, "span": (min(dates), max(dates)) if dates else None}
            print(f"  results returned      : {len(items)}", flush=True)
            print(f"  judgement date span   : {summary[label]['span']}", flush=True)
            print(f"  all inside window?    : {inside}", flush=True)

    finally:
        try:
            scraper.close()
        except Exception:  # noqa: BLE001
            pass

    print("\n─── summary ───")
    for label, _di, _df in SCENARIOS:
        s = summary.get(label)
        print(f"  {label:36} -> {s}")

    print("\n─── verdict ───")
    base = summary.get(SCENARIOS[0][0])
    narrow = summary.get(SCENARIOS[1][0])
    old = summary.get(SCENARIOS[2][0])
    checks = [
        ("3.1 production path returns results at all", bool(base and base["n"] > 0)),
        ("3.2 subset of returned dates are inside the window", bool(narrow and narrow["inside"] is True)),
        ("3.3 old window also fully inside", bool(old and old["inside"] is True)),
        ("3.1 baseline dates are OUTSIDE the 2024 window (proves filtering)", bool(
            base and base["span"] and not ("2024-01-01" <= iso(base["span"][0]) <= "2024-03-31")
        )),
    ]
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all(ok for _n, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
