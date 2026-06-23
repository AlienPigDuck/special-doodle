"""
News collection: RSS feeds + Bluesky public search.
Returns a list of headline dicts for the script generator.
"""

import os
import feedparser
import httpx
import logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)

RSS_FEEDS = [
    ("Nikkei Asia",       "https://asia.nikkei.com/rss/feed/nar"),
    ("Japan Times Biz",   "https://www.japantimes.co.jp/feed/business/"),
    ("Reuters Business",  "https://feeds.reuters.com/reuters/businessNews"),
    ("MarketWatch",       "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("AP Business",       "https://rsshub.app/apnews/topics/business-news"),
    ("Investing.com JP",  "https://jp.investing.com/rss/news_285.rss"),
    ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
]

BLUESKY_SEARCH_TERMS = [
    "Nikkei", "Tokyo stocks", "USDJPY", "Bank of Japan", "BOJ",
    "Japanese yen", "Tokyo Electron", "SoftBank", "Toyota earnings",
    "Nikkei 225", "Japan market",
]

BLUESKY_AUTH_URL   = "https://bsky.social/xrpc/com.atproto.server.createSession"
BLUESKY_SEARCH_URL = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"

MAX_AGE_HOURS = 14  # only stories from the last ~14h (covers US session)


def _is_recent(entry, max_age_hours: int = MAX_AGE_HOURS) -> bool:
    try:
        pub = entry.get("published_parsed") or entry.get("updated_parsed")
        if not pub:
            return True
        dt = datetime(*pub[:6], tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - dt < timedelta(hours=max_age_hours)
    except Exception:
        return True


def fetch_rss(max_age_hours: int = MAX_AGE_HOURS) -> list[dict]:
    headlines = []
    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                if not _is_recent(entry, max_age_hours):
                    continue
                headlines.append({
                    "source": source,
                    "title": entry.get("title", "").strip(),
                    "summary": (entry.get("summary") or "")[:300].strip(),
                    "url": entry.get("link", ""),
                })
        except Exception as e:
            log.warning("RSS fetch failed for %s: %s", source, e)
    log.info("Fetched %d RSS headlines", len(headlines))
    return headlines


def _bsky_auth(client: httpx.Client) -> str | None:
    handle = os.environ.get("BSKY_HANDLE")
    password = os.environ.get("BSKY_PASSWORD")
    if not handle or not password:
        return None
    try:
        resp = client.post(BLUESKY_AUTH_URL, json={"identifier": handle, "password": password})
        resp.raise_for_status()
        return resp.json()["accessJwt"]
    except Exception as e:
        log.warning("Bluesky auth failed: %s", e)
        return None


def fetch_bluesky(max_age_hours: int = MAX_AGE_HOURS) -> list[dict]:
    posts = []
    seen = set()
    with httpx.Client(timeout=10) as client:
        token = _bsky_auth(client)
        if not token:
            log.warning("Bluesky: no auth token, skipping search")
            return posts
        headers = {"Authorization": f"Bearer {token}"}
        for term in BLUESKY_SEARCH_TERMS:
            try:
                resp = client.get(BLUESKY_SEARCH_URL, params={"q": term, "limit": 10}, headers=headers)
                resp.raise_for_status()
                for post in resp.json().get("posts", []):
                    text = post.get("record", {}).get("text", "").strip()
                    if text and text not in seen:
                        seen.add(text)
                        posts.append({
                            "source": "Bluesky",
                            "title": text[:200],
                            "summary": "",
                            "url": "",
                        })
            except Exception as e:
                log.warning("Bluesky search failed for '%s': %s", term, e)
    log.info("Fetched %d Bluesky posts", len(posts))
    return posts


def fetch_all(max_age_hours: int = MAX_AGE_HOURS) -> list[dict]:
    rss = fetch_rss(max_age_hours=max_age_hours)
    bsky = fetch_bluesky(max_age_hours=max_age_hours)
    return rss + bsky
