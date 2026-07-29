"""Optional reCAPTCHA solving for e-SAJ portals (TJAL, TJAM, etc.).

Some Tribunais serve an inteiro teor behind a Google reCAPTCHA, which the
legacy OCR image-captcha path cannot solve. This module integrates an
external captcha-solving *service* (a proxy that returns the g-recaptcha
response token) and injects it into the page so the Selenium session can
proceed to the actual document.

This is OPT-IN and configured entirely through environment variables so that
no API key or provider secret is ever committed to source:

    JURIS_CAPTCHA_SOLVER      one of: "" (disabled), "2captcha", "anticaptcha"
    JURIS_CAPTCHA_API_KEY     the provider API key
    JURIS_CAPTCHA_MAX_WAIT    max seconds to wait for a token (default 120)

Supported providers both implement the same userrecaptcha flow:
  * 2Captcha   - https://2captcha.com
  * Anti-Captcha - https://anti-captcha.com

The token is injected into every ``#g-recaptcha-response`` textarea and the
enclosing form is submitted, matching how e-SAJ portals consume the token.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import List, Optional

import requests

logger = logging.getLogger("juris-search.captcha_solver")

DEFAULT_WAIT = 120
POLL_INTERVAL = 5


def _configured_solver() -> Optional["CaptchaSolver"]:
    """Build a solver from env vars, or None when disabled/unconfigured."""
    service = os.environ.get("JURIS_CAPTCHA_SOLVER", "").strip().lower()
    api_key = os.environ.get("JURIS_CAPTCHA_API_KEY", "").strip()
    if not service or not api_key:
        return None
    if service not in ("2captcha", "anticaptcha"):
        logger.warning("Unknown JURIS_CAPTCHA_SOLVER=%r; captcha solving disabled", service)
        return None
    max_wait = int(os.environ.get("JURIS_CAPTCHA_MAX_WAIT", str(DEFAULT_WAIT)))
    return CaptchaSolver(service=service, api_key=api_key, max_wait=max_wait)


class CaptchaSolver:
    """Thin client for a reCAPTCHA-solving service."""

    def __init__(self, service: str, api_key: str, *, max_wait: int = DEFAULT_WAIT) -> None:
        self.service = service
        self.api_key = api_key
        self.max_wait = max_wait

    # -- Provider APIs --------------------------------------------------------

    def _solve_2captcha(self, sitekey: str, page_url: str) -> str:
        base = "https://2captcha.com"
        r = requests.get(
            base + "/in.php",
            params={
                "key": self.api_key,
                "method": "userrecaptcha",
                "googlekey": sitekey,
                "pageurl": page_url,
                "json": 1,
            },
            timeout=30,
        )
        data = r.json()
        if data.get("status") != 1:
            raise RuntimeError(f"2captcha submit failed: {data}")
        cap_id = data["request"]
        deadline = time.time() + self.max_wait
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            res = requests.get(
                base + "/res.php",
                params={"key": self.api_key, "action": "get", "id": cap_id, "json": 1},
                timeout=30,
            ).json()
            if res.get("status") == 1:
                return res["request"]
            if res.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2captcha poll failed: {res}")
        raise RuntimeError("2captcha timed out waiting for token")

    def _solve_anticaptcha(self, sitekey: str, page_url: str) -> str:
        base = "https://api.anti-captcha.com"
        create = requests.post(
            base + "/createTask",
            json={
                "clientKey": self.api_key,
                "task": {
                    "type": "NoCaptchaTaskProxyless",
                    "websiteURL": page_url,
                    "websiteKey": sitekey,
                },
            },
            timeout=30,
        ).json()
        if create.get("errorId", 0) != 0:
            raise RuntimeError(f"anti-captcha createTask failed: {create}")
        task_id = create["taskId"]
        deadline = time.time() + self.max_wait
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            res = requests.post(
                base + "/getTaskResult",
                json={"clientKey": self.api_key, "taskId": task_id},
                timeout=30,
            ).json()
            if res.get("status") == "ready":
                return res["solution"]["gRecaptchaResponse"]
            if res.get("errorId", 0) != 0:
                raise RuntimeError(f"anti-captcha getTaskResult failed: {res}")
        raise RuntimeError("anti-captcha timed out waiting for token")

    def solve_recaptcha(self, sitekey: str, page_url: str) -> str:
        if self.service == "2captcha":
            return self._solve_2captcha(sitekey, page_url)
        if self.service == "anticaptcha":
            return self._solve_anticaptcha(sitekey, page_url)
        raise RuntimeError(f"unsupported solver service: {self.service}")

    # -- Image captcha (e-SAJ "Código de Acesso") ----------------------------

    def _solve_image_2captcha(self, image_path: str) -> str:
        import base64
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        r = requests.post(
            "https://2captcha.com/in.php",
            data={"key": self.api_key, "method": "base64", "json": 1},
            files={"file": ("captcha.png", b64)},
            timeout=30,
        ).json()
        if r.get("status") != 1:
            raise RuntimeError(f"2captcha image submit failed: {r}")
        cap_id = r["request"]
        deadline = time.time() + self.max_wait
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            res = requests.get(
                "https://2captcha.com/res.php",
                params={"key": self.api_key, "action": "get", "id": cap_id, "json": 1},
                timeout=30,
            ).json()
            if res.get("status") == 1:
                return res["request"]
            if res.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2captcha image poll failed: {res}")
        raise RuntimeError("2captcha image timed out")

    def _solve_image_anticaptcha(self, image_path: str) -> str:
        import base64
        with open(image_path, "rb") as fh:
            b64 = base64.b64encode(fh.read()).decode()
        create = requests.post(
            "https://api.anti-captcha.com/createTask",
            json={
                "clientKey": self.api_key,
                "task": {"type": "ImageToTextTask", "body": b64},
            },
            timeout=30,
        ).json()
        if create.get("errorId", 0) != 0:
            raise RuntimeError(f"anti-captcha createTask failed: {create}")
        task_id = create["taskId"]
        deadline = time.time() + self.max_wait
        while time.time() < deadline:
            time.sleep(POLL_INTERVAL)
            res = requests.post(
                "https://api.anti-captcha.com/getTaskResult",
                json={"clientKey": self.api_key, "taskId": task_id},
                timeout=30,
            ).json()
            if res.get("status") == "ready":
                return res["solution"]["text"]
            if res.get("errorId", 0) != 0:
                raise RuntimeError(f"anti-captcha getTaskResult failed: {res}")
        raise RuntimeError("anti-captcha image timed out")

    def solve_image_captcha(self, image_path: str) -> str:
        if self.service == "2captcha":
            return self._solve_image_2captcha(image_path)
        if self.service == "anticaptcha":
            return self._solve_image_anticaptcha(image_path)
        raise RuntimeError(f"unsupported solver service: {self.service}")


# -- Selenium integration ----------------------------------------------------

def extract_recaptcha_sitekey(driver) -> Optional[str]:
    """Find the reCAPTCHA sitekey from the current page or its iframe."""
    # 1) main document
    m = re.search(r'data-sitekey=["\']([^"\']+)', driver.page_source)
    if m:
        return m.group(1)
    # 2) inside a recaptcha iframe src
    try:
        for frame in driver.find_elements("css selector", "iframe"):
            src = frame.get_attribute("src") or ""
            if "google.com/recaptcha" in src:
                km = re.search(r"[?&]k=([^&]+)", src)
                if km:
                    return km.group(1)
    except Exception as exc:
        logger.debug("iframe sitekey scan failed: %s", exc)
    return None


def inject_recaptcha_token(driver, token: str) -> None:
    """Set the g-recaptcha-response token and submit the enclosing form."""
    script = """
    var token = arguments[0];
    var els = document.getElementsByName('g-recaptcha-response');
    for (var i = 0; i < els.length; i++) {
        els[i].style.display = 'block';
        els[i].style.visibility = 'visible';
        els[i].value = token;
    }
    // notify any grecaptcha callback listeners
    if (window.___captchaSubmitForm) { window.___captchaSubmitForm(); }
    """
    driver.execute_script(script, token)
    # Attempt to submit the form that holds the captcha (e-SAJ pattern).
    try:
        driver.execute_script(
            """
            var el = document.querySelector('textarea[name="g-recaptcha-response"]');
            if (el && el.form) { el.form.requestSubmit ? el.form.requestSubmit() : el.form.submit(); }
            """
        )
    except Exception as exc:
        logger.debug("recaptcha form submit trigger failed: %s", exc)


def solve_and_submit(driver, *, max_wait: Optional[int] = None) -> bool:
    """Solve any reCAPTCHA on the current page and submit it.

    Returns True if a token was obtained and injected, False if solving is not
    configured or failed. Does not raise.
    """
    solver = _configured_solver()
    if solver is None:
        return False
    sitekey = extract_recaptcha_sitekey(driver)
    if not sitekey:
        logger.warning("reCAPTCHA detected but no sitekey found; cannot solve")
        return False
    page_url = driver.current_url
    logger.info("Solving reCAPTCHA via %s (sitekey=%s…)", solver.service, sitekey[:12])
    try:
        token = solver.solve_recaptcha(sitekey, page_url)
    except Exception as exc:
        logger.error("reCAPTCHA solving failed: %s", exc)
        return False
    inject_recaptcha_token(driver, token)
    time.sleep(4)
    return True


def click_checkbox_captcha(driver, *, settle: float = 1.5) -> bool:
    """Solve a *checkbox* reCAPTCHA by ticking it in the live browser.

    Some e-SAJ portals (e.g. TJAL/TJAM) present the basic "I'm not a robot"
    checkbox. On a real browser session a plain *pointer* click often resolves
    it via Google's risk analysis without any paid solving service: tick the
    box, wait ~1s for the challenge to settle, then click the form's submit
    button (``pbEnviar`` on e-SAJ) so the document request proceeds.

    A real mouse event (not a scripted .click()) is required, otherwise Google
    escalates to the image challenge. We therefore move the pointer onto the
    checkbox inside its iframe and click it physically via ActionChains.

    Returns True if the checkbox was ticked and tried to submit, False on any
    error. Does not raise.
    """
    from selenium.common.exceptions import NoSuchElementException, WebDriverException

    try:
        clicked = False
        try:
            for fr in driver.find_elements(By.CSS_SELECTOR, "iframe"):
                src = fr.get_attribute("src") or ""
                if "recaptcha" in src and "anchor" in src:
                    driver.switch_to.frame(fr)
                    try:
                        anchor = driver.find_element(By.ID, "recaptcha-anchor")
                        anchor.click()  # native click = real pointer event
                        clicked = True
                    except (NoSuchElementException, WebDriverException):
                        try:
                            driver.execute_script("arguments[0].click();", anchor)
                            clicked = True
                        except (NoSuchElementException, WebDriverException):
                            pass
                    finally:
                        driver.switch_to.default_content()
                    break
        except (NoSuchElementException, WebDriverException):
            pass

        if not clicked:
            for sel in (".recaptcha-checkbox-border", ".recaptcha-checkbox", "div[role='checkbox']"):
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    try:
                        el.click()
                    except (NoSuchElementException, WebDriverException):
                        driver.execute_script("arguments[0].click();", el)
                    clicked = True
                    break
                except (NoSuchElementException, WebDriverException):
                    continue

        if not clicked:
            logger.warning("reCAPTCHA checkbox element not found to click")
            return False

        logger.info("Clicked reCAPTCHA checkbox; waiting for challenge to settle…")
        time.sleep(settle)

        try:
            submit = driver.find_element(By.NAME, "pbEnviar")
            ActionChains(driver).move_to_element(submit).pause(0.2).click().perform()
        except (NoSuchElementException, WebDriverException):
            logger.debug("pbEnviar submit button not found; relying on auto-submit")
        time.sleep(2)
        return True
    except Exception as exc:
        logger.debug("checkbox captcha click failed: %s", exc)
        return False
