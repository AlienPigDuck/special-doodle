"""
Generic RSS collector for non-Nikkei sources.
Returns full entry summaries — no auth required.
"""

import feedparser
import logging
from datetime import datetime, timezone, timedelta
from .base import Article

log = logging.getLogger(__name__)

FEEDS = [
    ("Reuters Business",  "https://feeds.reuters.com/reuters/businessNews"),
    ("MarketWatch",       "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"),
    ("AP Business",       "https://rsshub.app/apnews/topics/business-news"),
    ("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    ("Japan Times Biz",   "https://www.japantimes.co.jp/feed/business/"),
    ("Investing.com JP",  "https://jp.investing.com/rss/news_285.rss"),
]


def fetch(max_age_hours: int = 14) -> list[Article]:
    articles = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)

    for source, url in FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:15]:
                pub = entry.get("published_parsed") or entry.get("updated_parsed")
                pub_dt = datetime(*pub[:6], tzinfo=timezone.utc) if pub else None
                if pub_dt and pub_dt < cutoff:
                    continue
                articles.append(Article(
                    title=entry.get("title", "").strip(),
                    body=(entry.get("summary") or "")[:600].strip(),
                    source=source,
                    url=entry.get("link", ""),
                    published_at=pub_dt,
                ))
        except Exception as e:
            log.warning("RSS feed failed [%s]: %s", source, e)

    log.info("RSS: %d articles from %d feeds", len(articles), len(FEEDS))
    return articles
