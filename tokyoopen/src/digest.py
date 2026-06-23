"""
Turns raw collected articles into a structured market briefing.
Uses Claude Haiku — fast and cheap. Handles Japanese articles inline.
The briefing output is what script.py receives instead of raw headlines.
"""

import os
import logging
import anthropic
from collectors.base import Article

log = logging.getLogger(__name__)

_PROMPT = """You are a research assistant preparing a briefing for "Tokyo Open", a daily Japanese stock market podcast.

You have been given a set of articles collected from multiple sources. Some articles may be in Japanese — read them all regardless of language.

Your job is to extract only what is market-relevant and structure it into a concise briefing. Be specific: name companies, state ticker codes, give actual figures. Do not invent or infer beyond what the articles say.

Output the following six sections. Skip any section where you have no relevant material.

1. MARKET MOVERS
Specific Japanese stocks likely to move at Tokyo open. For each: company name, ticker, what happened, why it matters.

2. MACRO & FX
BOJ signals, yen direction, US rate moves, oil, gold, commodity shifts. What the direction means for Japan.

3. SECTOR THEMES
Which sectors are in focus and why. Semiconductors, autos, banks, pharma, energy — name specific names.

4. KEY EVENTS & EARNINGS
Earnings releases, economic data prints, central bank decisions, political events, trade developments.

5. SURPRISES & RISKS
Anything unexpected, contradicting recent trends, or that could catch the market off-guard.

6. ANALYST RATINGS
Any broker upgrades, downgrades, or price target changes for Nikkei 225 stocks published in today's articles. For each: company name, broker (e.g. Daiwa, Nomura, Jefferies, Mizuho, JPMorgan, Morgan Stanley, Goldman Sachs, SMBC Nikko, Citigroup, UBS), old rating → new rating, and new price target if stated. If no rating changes appear in the articles, omit this section entirely.

Rules:
- Only include information that appears in the articles.
- If an article is in Japanese, extract its key points in English.
- Skip sports, lifestyle, entertainment, food, culture, real estate unrelated to REITs.
- Keep total output under 1000 words.

JAPANESE NAMES: Japan's Prime Minister is Sanae Takaichi (高市早苗). Always romanise her surname as "Takaichi" — never "Takayama", "Takita", or any other spelling. Romanise other Japanese officials' and companies' names with the same care."""


# Section priority — highest value articles go in first with full bodies.
# Lower-priority sections get included only if budget allows.
_SECTION_PRIORITY = {
    '１面': 0,
    '総合１': 1, '総合２': 1, '総合３': 1, '総合４': 1, '総合５': 1,
    'グローバル市場': 2,
    '国際': 3,
    'アジアBiz': 4,
    'ビジネス１': 5, 'ビジネス２': 5,
    '投資１': 6, '投資２': 6,
    '商品': 7,
}
_RSS_PRIORITY = 8  # RSS articles after all Nikkei priority sections
_CHAR_BUDGET = 150_000  # ~50-60K tokens; leaves headroom under the 200K limit


def _prioritised(articles: list[Article]) -> list[Article]:
    def key(a):
        if a.source == "Nikkei JP":
            return _SECTION_PRIORITY.get(a.section or "", 99)
        return _RSS_PRIORITY
    return sorted(articles, key=key)


def generate(articles: list[Article]) -> str:
    if not articles:
        log.warning("Digest: no articles — returning empty briefing")
        return "No articles collected for this session."

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    ordered = _prioritised(articles)
    blocks = []
    used_chars = len(_PROMPT)
    skipped = 0

    for i, a in enumerate(ordered, 1):
        lang = " [JAPANESE]" if a.language == "ja" else ""
        body = a.body.strip() if a.body else "(headline only)"
        block = f"[{i}] {a.source}{lang} | {a.section or 'General'}\nTITLE: {a.title}\n{body}"
        if used_chars + len(block) > _CHAR_BUDGET:
            skipped += 1
            continue
        blocks.append(block)
        used_chars += len(block)

    if skipped:
        log.info("Digest: included %d/%d articles (%d skipped, budget %d chars used)",
                 len(blocks), len(ordered), skipped, used_chars)
    user_content = _PROMPT + "\n\n---\n\n" + "\n\n---\n\n".join(blocks)

    log.info("Digest: summarising %d articles with Haiku...", len(blocks))
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1500,
        messages=[{"role": "user", "content": user_content}],
    )
    result = msg.content[0].text
    log.info("Digest: complete (%d chars)", len(result))
    return result
