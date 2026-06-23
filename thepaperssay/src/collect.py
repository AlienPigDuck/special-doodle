"""
Collect articles for The Papers Say — Nikkei morning newspaper only.
Adds tokyoopen/src to the path so collectors are shared without duplication.
"""

import sys
import logging
from pathlib import Path

# Reuse collectors from tokyoopen — append so thepaperssay/src modules take priority
sys.path.append(str(Path(__file__).parent.parent.parent / "tokyoopen" / "src"))

from collectors.base import Article
from collectors import nikkei_jp

log = logging.getLogger(__name__)


def fetch_all() -> list[Article]:
    articles = nikkei_jp.fetch(max_age_hours=14)
    log.info("Collected %d Nikkei articles", len(articles))
    return articles
