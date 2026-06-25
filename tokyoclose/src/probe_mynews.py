"""
One-off probe: can the existing Nikkei login read /mynews and pull recent
articles WITH timestamps? Reuses the same auth as the daily collectors.
Run in GitHub Actions (where NIKKEI_STATE is available). Throwaway — delete after.
"""

import sys
import logging
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "tokyoopen" / "src"))
from collectors.nikkei_auth import make_page  # same auth as TPS / Tokyo Open

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s — %(message)s")
log = logging.getLogger("probe_mynews")

MYNEWS_URL = "https://www.nikkei.com/mynews"

# Permissive extractor: grab anything that looks like an article link plus any
# timestamp text near it, so we can learn the page's structure.
_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const links = document.querySelectorAll(
    'a[href*="/article/"], a[href*="/nkd/"], a[href*="/prime/"], a[href*="DGX"]'
  );
  links.forEach(a => {
    const href = a.getAttribute('href') || '';
    const title = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!href || title.length < 8 || seen.has(href)) return;
    seen.add(href);
    const box = a.closest('article, li, [class*="card"], div');
    let t = '';
    if (box) {
      const te = box.querySelector('time, [datetime], [class*="time"], [class*="date"]');
      if (te) t = (te.getAttribute('datetime') || te.textContent || '').replace(/\s+/g,' ').trim();
    }
    out.push({ href, title: title.slice(0, 130), time: t.slice(0, 50) });
  });
  return out;
}
"""


def main():
    result = make_page("nikkei_jp")
    if not result:
        log.error("Nikkei auth failed — no page returned")
        sys.exit(1)
    pw, browser, page = result
    try:
        log.info("navigating to %s ...", MYNEWS_URL)
        page.goto(MYNEWS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)  # let the feed render

        log.info("landed on : %s", page.url)
        log.info("page title: %s", page.title())
        if "id.nikkei.com" in page.url or "/login" in page.url:
            log.error("REDIRECTED TO LOGIN — auth state did not carry to /mynews")
            return

        items = page.evaluate(_JS)
        log.info("found %d candidate article links", len(items))
        for it in items[:50]:
            log.info("  time=[%s]  %s  -> %s", it["time"] or "—", it["title"], it["href"])

        # Surface raw timestamp formats so we know how to window to last 45 min
        times = page.evaluate(
            "() => Array.from(document.querySelectorAll('time, [datetime]'))"
            ".map(t => (t.getAttribute('datetime')||t.textContent||'').trim()).filter(Boolean).slice(0,25)"
        )
        log.info("sample <time>/[datetime] values: %s", times)
        log.info("total <time>/[datetime] elements: %s",
                 page.evaluate("() => document.querySelectorAll('time,[datetime]').length"))
    finally:
        browser.close()
        pw.stop()


if __name__ == "__main__":
    main()
