"""
Nikkei auth via Playwright.

Preferred: load NIKKEI_STATE (base64-encoded Playwright storage state from
setup_nikkei_auth.py) — skips login entirely, no OTP risk.

Fallback: live login with NIKKEI_USER / NIKKEI_PASS through id.nikkei.com SSO.
This will hit OTP on any unrecognised device (e.g. a fresh GitHub Actions runner),
so the state approach is strongly preferred for CI.
"""

import os
import json
import base64
import logging
from playwright.sync_api import sync_playwright, Page

log = logging.getLogger(__name__)

_USER       = os.environ.get("NIKKEI_USER", "")
_PASS       = os.environ.get("NIKKEI_PASS", "")
_STATE_B64  = os.environ.get("NIKKEI_STATE", "")

_LOGIN_URLS = {
    "nikkei_jp":   "https://www.nikkei.com/login/",
    "nikkei_asia": "https://asia.nikkei.com/login/",
}

_EMAIL_SEL = 'input[type="email"], input[name="email"], input[name="emailAddress"]'
_NEXT_BTN  = 'button:has-text("次に進む")'

_MEDIA_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
               ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm")

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)


def _block_media(context) -> None:
    context.route(
        lambda url: any(url.split("?")[0].lower().endswith(ext) for ext in _MEDIA_EXTS),
        lambda route: route.abort(),
    )


def _make_context_from_state(pw, state: dict):
    """Create a browser context pre-loaded with saved auth state."""
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(user_agent=_UA, storage_state=state)
    _block_media(context)
    return browser, context


def _verify_logged_in(page: Page, site: str) -> bool:
    """Navigate to the site homepage and confirm we are not redirected to login."""
    home = "https://www.nikkei.com/" if site == "nikkei_jp" else "https://asia.nikkei.com/"
    try:
        page.goto(home, wait_until="domcontentloaded", timeout=30000)
        if "id.nikkei.com" in page.url or "/login" in page.url:
            log.warning("Nikkei state [%s]: session has expired — re-login needed", site)
            return False
        log.info("Nikkei state [%s]: session valid, on %s", site, page.url[:60])
        return True
    except Exception as e:
        log.warning("Nikkei state [%s]: verification error: %s", site, e)
        return False


def _do_login(page: Page, login_url: str) -> bool:
    """
    Full login flow via id.nikkei.com SSO (email → password → redirect).
    Only used when NIKKEI_STATE is absent or expired.
    Will fail on fresh devices because Nikkei triggers OTP for unrecognised IPs.
    """
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

        try:
            page.wait_for_url("**/login/id**", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            log.warning("Nikkei login: SSO redirect to /login/id did not happen (url: %s)", page.url)
            return False

        try:
            page.wait_for_selector(_EMAIL_SEL, state="visible", timeout=10000)
        except Exception:
            log.warning("Nikkei login: email field not found on %s", page.url)
            return False

        page.fill(_EMAIL_SEL, _USER)
        page.wait_for_timeout(400)
        page.click(_NEXT_BTN)

        try:
            page.wait_for_url("**/login/password**", timeout=15000)
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            log.warning("Nikkei login: did not reach password page (url: %s)", page.url)
            return False

        try:
            page.wait_for_selector('input[type="password"]', state="visible", timeout=10000)
        except Exception:
            log.warning("Nikkei login: password field not found on %s", page.url)
            return False

        page.fill('input[type="password"]', _PASS)
        page.wait_for_timeout(400)
        page.click(_NEXT_BTN)

        try:
            page.wait_for_url(lambda url: "id.nikkei.com" not in url, timeout=20000)
        except Exception:
            log.warning("Nikkei login: still on SSO after password submit (url: %s)", page.url)
            return False

        log.info("Nikkei login: success, landed on %s", page.url[:80])
        return True
    except Exception as e:
        log.warning("Nikkei login: exception: %s", e)
        return False


def make_page(site: str):
    """
    Return (playwright, browser, page) authenticated and ready to scrape.
    Tries saved state first; falls back to live login if unavailable.
    Caller must call browser.close() and pw.stop() when done.
    """
    pw = sync_playwright().start()

    # ── Preferred: load saved storage state ──────────────────────────────────
    if _STATE_B64:
        try:
            state = json.loads(base64.b64decode(_STATE_B64))
            browser, context = _make_context_from_state(pw, state)
            page = context.new_page()
            if _verify_logged_in(page, site):
                return pw, browser, page
            browser.close()
            log.warning("Nikkei [%s]: saved state invalid — falling back to live login", site)
        except Exception as e:
            log.warning("Nikkei [%s]: failed to load NIKKEI_STATE: %s", site, e)

    # ── Fallback: live login ──────────────────────────────────────────────────
    if not _USER or not _PASS:
        log.warning("Nikkei [%s]: no credentials (NIKKEI_USER/NIKKEI_PASS) — skipping", site)
        pw.stop()
        return None

    login_url = _LOGIN_URLS.get(site)
    if not login_url:
        log.error("Nikkei auth: unknown site %s", site)
        pw.stop()
        return None

    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(user_agent=_UA)
    _block_media(context)
    page = context.new_page()

    if not _do_login(page, login_url):
        browser.close()
        pw.stop()
        return None

    return pw, browser, page
