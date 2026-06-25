"""
Tokyo Close primary source: Nikkei "My News" (/mynews).

Fresh, human-written market articles published after the TSE close — far better
raw material for the wrap than the model inferring "why" from price moves alone.
Reuses the same Nikkei auth as the daily collectors, keeps only articles in a
post-close time window, and returns full-body Article objects.
"""

import re
import sys
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "tokyoopen" / "src"))
from collectors.nikkei_auth import make_page  # same auth as TPS / Tokyo Open
from collectors.base import Article

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
MYNEWS_URL = "https://www.nikkei.com/mynews"

# Nikkei prepends these standard promo/notice paragraphs to article bodies.
_BOILERPLATE = (
    "朝夕刊や電子版ではお伝えしきれない",
    "企業での記事共有や会議資料への転載",
)

# Pull every article link in the feed with its ISO <time> and relative-time text.
_LIST_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/article/"]').forEach(a => {
    const href = a.getAttribute('href') || '';
    const title = (a.textContent || '').replace(/\s+/g, ' ').trim();
    if (!href || title.length < 8 || seen.has(href)) return;
    seen.add(href);
    const box = a.closest('article, li, [class*="card"], div');
    let iso = '', rel = '';
    if (box) {
      const t = box.querySelector('time[datetime], [datetime]');
      if (t) iso = t.getAttribute('datetime') || '';
      const r = box.querySelector('time, [class*="time"], [class*="date"]');
      if (r) rel = (r.textContent || '').replace(/\s+/g, ' ').trim();
    }
    out.push({ href, title: title.slice(0, 160), iso, rel });
  });
  return out;
}
"""

# Body lives in <article>/<main>; class-based selectors don't exist on these pages.
_BODY_JS = ("() => (document.querySelector('article') || document.querySelector('main'))"
            "?.innerText || ''")


def _parse_time(iso: str, rel: str, now: datetime) -> datetime | None:
    if iso:
        try:
            return datetime.fromisoformat(iso)
        except ValueError:
            pass
    m = re.search(r"(\d+)\s*分前", rel)
    if m:
        return now - timedelta(minutes=int(m.group(1)))
    m = re.search(r"(\d+)\s*時間前", rel)
    if m:
        return now - timedelta(hours=int(m.group(1)))
    return None


def _clean_body(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not any(b in ln for b in _BOILERPLATE)]
    return "\n".join(lines)


def _article_id(href: str) -> str:
    return re.sub(r"[#?].*$", "", href)


def _abs(href: str) -> str:
    return href if href.startswith("http") else "https://www.nikkei.com" + href


def fetch(after: datetime, max_articles: int = 15) -> list[Article]:
    """Full-body /mynews articles published at/after `after` (a JST datetime)."""
    result = make_page("nikkei_jp")
    if not result:
        log.warning("Nikkei MyNews: auth failed — skipping")
        return []
    pw, browser, page = result
    now = datetime.now(JST)
    articles: list[Article] = []

    try:
        page.goto(MYNEWS_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(4000)
        if "id.nikkei.com" in page.url or "/login" in page.url:
            log.warning("Nikkei MyNews: not authenticated on /mynews")
            return []

        items = page.evaluate(_LIST_JS)
        picked, seen_ids = [], set()
        for it in items:
            pub = _parse_time(it.get("iso", ""), it.get("rel", ""), now)
            if pub is None or pub < after:
                continue
            aid = _article_id(it["href"])
            if aid in seen_ids:
                continue
            seen_ids.add(aid)
            picked.append((it["title"], _abs(it["href"]), pub))
        picked.sort(key=lambda x: x[2], reverse=True)
        picked = picked[:max_articles]
        log.info("Nikkei MyNews: %d articles after %s JST (of %d listed)",
                 len(picked), after.strftime("%H:%M"), len(items))

        for title, url, pub in picked:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(1500)
                h1 = page.evaluate("() => (document.querySelector('h1')?.textContent || '').trim()")
                body = _clean_body(page.evaluate(_BODY_JS))
                if len(body) < 80:
                    log.info("  skip (thin body): %s", (h1 or title)[:60])
                    continue
                articles.append(Article(
                    title=(h1 or title).strip(),
                    body=body[:4000],
                    source="Nikkei Close (/mynews)",
                    url=url,
                    published_at=pub,
                    language="ja",
                ))
            except Exception as e:
                log.warning("Nikkei MyNews: body fetch failed %s: %s", url, e)

        log.info("Nikkei MyNews: collected %d full-body articles", len(articles))
        return articles
    finally:
        browser.close()
        pw.stop()
