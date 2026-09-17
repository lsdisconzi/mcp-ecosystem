#!/usr/bin/env python3
"""Offline tests for Chile result/detail readiness (no network, no Chrome).

`_wait_for_results` and `_wait_for_detail` are driven with a *scripted* stub
driver whose `execute_script` returns a predetermined value per poll, so the
timeline can be controlled exactly. That is what lets these tests express the
defect: a page whose visible id set never changes must NOT be reported ready,
which is the step-6 failure (`pages == [1]`, `total == 10`) in miniature.

See `.dev/chilean-jurisprudence/03-chile_scraper-playbook.md` §B-3 and
`verification_report.md` open issue 9.

Run:  .venv/bin/python test_chile_readiness.py
"""
import os
import sys

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

import chile_scraper as cs

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "chile_scraper.py")

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class ScriptedDriver:
    """Returns scripted[i] on the i-th execute_script call; clamps at the end."""

    def __init__(self, scripted, page_source="<html>ok</html>"):
        self.scripted = list(scripted)
        self.page_source = page_source
        self.calls = 0

    def execute_script(self, script, *args):
        value = self.scripted[min(self.calls, len(self.scripted) - 1)]
        self.calls += 1
        if isinstance(value, Exception):
            raise value
        return value


def make(scripted, timeout=0.6):
    """A scraper instance without __init__ — no browser is launched."""
    scraper = cs.ChileJurisprudenciaScraper.__new__(cs.ChileJurisprudenciaScraper)
    scraper.driver = ScriptedDriver(scripted)
    scraper.wait_time = timeout
    return scraper


def main():
    print("\n1. _current_result_ids")
    scraper = make([RuntimeError("boom")])
    check("driver exception -> frozenset()", scraper._current_result_ids() == frozenset())

    scraper = make([["200791920", "200791920", "200917190"]])
    check(
        "7x-replicated attribute collapses to a set",
        scraper._current_result_ids() == frozenset({"200791920", "200917190"}),
    )

    scraper = make([None])
    check("script returns null -> frozenset()", scraper._current_result_ids() == frozenset())

    # Falsy-filtering lives in the JS, so assert on the script text rather than
    # on a stubbed return value that the JS could never produce.
    seen = {}

    class CapturingDriver:
        page_source = "<html>ok</html>"

        def execute_script(self, script, *args):
            seen["js"] = script
            return []

    capturer = cs.ChileJurisprudenciaScraper.__new__(cs.ChileJurisprudenciaScraper)
    capturer.driver = CapturingDriver()
    capturer._current_result_ids()
    check(
        "JS filters hidden nodes and empty ids",
        "offsetParent !== null" in seen["js"] and "filter(Boolean)" in seen["js"],
    )

    print("\n2. _wait_for_results — change mode")
    # The real timeline: rows vanish for ~2 s, then return with a DIFFERENT set.
    scraper = make([[], [], ["200791920"]], timeout=2.0)
    ok = scraper._wait_for_results(previous_ids=frozenset({"200917190"}))
    check("empty window is not ready; True once the set changes", ok is True)

    # The step-6 failure: the set never changes. The old predicate passed here.
    scraper = make([["200917190"], ["200917190"]], timeout=0.6)
    ok = scraper._wait_for_results(previous_ids=frozenset({"200917190"}))
    check("unchanged set -> timeout -> False", ok is False)

    # Timeout must be distinguishable from success — B-2b depends on it.
    scraper = make([[]], timeout=0.6)
    check("timeout returns False, not None", scraper._wait_for_results(previous_ids=frozenset()) is False)

    scraper = make([["200917190"]], timeout=0.6)
    check("legacy mode (previous_ids=None) returns True on any non-empty set", scraper._wait_for_results() is True)

    print("\n3. Prove the guard can fail (mutation)")
    # Re-implement the OLD existence predicate against the same scenario. If it
    # also failed, the test above would prove nothing about the defect.
    class OldDriver:
        """Existence-only view: node count per poll; ids are irrelevant."""

        def __init__(self, per_poll):
            self.per_poll = list(per_poll)
            self.calls = 0
            self.page_source = "<html>ok</html>"

        def find_elements(self, by, selector):
            n = self.per_poll[min(self.calls, len(self.per_poll) - 1)]
            self.calls += 1
            return [object()] * n

    def old_ready(d):
        if cs.ChileJurisprudenciaScraper._is_f5_block(d.page_source):
            return True
        return bool(d.find_elements(By.CSS_SELECTOR, "[data-idsentencia]"))

    try:
        WebDriverWait(OldDriver([10, 10]), 0.6).until(old_ready)
        old_passed = True
    except Exception:
        old_passed = False
    check(
        "OLD predicate accepts an unchanged 10-node page (so the new test is meaningful)",
        old_passed is True,
        "mutation is observable",
    )

    print("\n4. _wait_for_detail — content, not visibility")
    # Displayed from t=0, but the AJAX payload only lands on the third poll.
    scraper = make([False, False, True], timeout=2.0)
    check("does not return on the empty-but-displayed panel", scraper._wait_for_detail() is True)

    scraper = make([False], timeout=0.6)
    check("still-empty panel -> timeout -> False", scraper._wait_for_detail() is False)

    blocked = cs.ChileJurisprudenciaScraper.__new__(cs.ChileJurisprudenciaScraper)
    blocked.driver = ScriptedDriver(
        [False], page_source="<title>La URL solicitada ha sido rechazada</title>"
    )
    blocked.wait_time = 0.6
    try:
        blocked._wait_for_detail()
        f5_outcome = "returned"
    except RuntimeError:
        f5_outcome = "raised"
    check("F5 body -> short-circuit, then _assert_not_blocked raises", f5_outcome == "raised")

    print("\n5. Constants match the measured page")
    check(
        "detail container id is the measured one",
        cs._DETAIL_CONTAINER_ID == "capa_contenedor_detalle_sentencia",
    )
    check(
        "char floor sits between the measured 94 and ~78,900",
        94 < cs._DETAIL_MIN_CHARS < 78900,
    )

    print("\n6. Call sites")
    src = open(SOURCE, encoding="utf-8").read()
    in_links = src[src.index("def get_inteiro_links"):src.index("def _run_search_ui")]
    in_detail = src[src.index("def _open_detail"):src.index("def download_inteiro_teor_url")]
    check("no time.sleep left in get_inteiro_links", "time.sleep" not in in_links)
    check("no time.sleep left in _open_detail", "time.sleep" not in in_detail)
    check("_open_detail waits on the detail panel", "_wait_for_detail(" in in_detail)
    check(
        "every readiness wait after a result-set mutation passes previous_ids",
        in_links.count("_wait_for_results(") == in_links.count("previous_ids="),
    )

    failed = [r for r in results if not r[1]]
    print("\n" + "=" * 60)
    print(f"  Total: {len(results)}, Passed: {len(results) - len(failed)}, Failed: {len(failed)}")
    if failed:
        print("\n  Errors:")
        for name, _, detail in failed:
            print(f"    FAIL: {name}" + (f"  [{detail}]" if detail else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
