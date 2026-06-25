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

        # ── Body-extraction test: visit a few real articles and compare selectors ──
        real = [it["href"] for it in items
                if "/article/" in it["href"] and it["time"]]
        real = real[:3]
        log.info("=== BODY TEST on %d articles ===", len(real))
        for href in real:
            url = href if href.startswith("http") else "https://www.nikkei.com" + href
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2500)
                h1 = page.evaluate("() => (document.querySelector('h1')?.textContent||'').trim()")
                cand = page.evaluate(r"""
                  () => {
                    const sels = ['article', 'main', 'div[class*="article_body"]',
                      'div[class*="ArticleBody"]', 'section[class*="article"]',
                      'div[class*="paywall"]', 'div[class*="container"]'];
                    const r = {};
                    for (const s of sels) {
                      const el = document.querySelector(s);
                      r[s] = el ? (el.innerText||'').trim().length : -1;
                    }
                    const ps = Array.from(document.querySelectorAll('p'))
                      .map(p => (p.innerText||'').trim()).filter(t => t.length > 20);
                    r['__P_JOINED_LEN'] = ps.join('\n').length;
                    r['__P_SAMPLE'] = ps.slice(0,4).join(' | ').slice(0,400);
                    r['__BODY_LEN'] = (document.body.innerText||'').length;
                    return r;
                  }
                """)
                log.info("ARTICLE %s", url)
                log.info("  h1: %s", h1[:120])
                log.info("  selector lengths: %s",
                         {k: v for k, v in cand.items() if not k.startswith("__P_SAMPLE")})
                log.info("  <p> sample: %s", cand.get("__P_SAMPLE"))
            except Exception as e:
                log.warning("  body fetch failed for %s: %s", url, e)
    finally:
        browser.close()
        pw.stop()


if __name__ == "__main__":
    main()
