"""
Runs all collectors in parallel and returns a unified article list.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from collectors.base import Article
from collectors import rss, nikkei_jp

log = logging.getLogger(__name__)

_COLLECTORS = {
    "rss":       rss.fetch,
    "nikkei_jp": nikkei_jp.fetch,
}


def fetch_all(max_age_hours: int = 14) -> list[Article]:
    results: list[Article] = []

    with ThreadPoolExecutor(max_workers=len(_COLLECTORS)) as pool:
        futures = {
            pool.submit(fn, max_age_hours): name
            for name, fn in _COLLECTORS.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                articles = future.result()
                results.extend(articles)
                log.info("Collector [%s]: %d articles", name, len(articles))
            except Exception as e:
                log.error("Collector [%s] failed: %s", name, e)

    log.info("Total collected: %d articles", len(results))
    return results
