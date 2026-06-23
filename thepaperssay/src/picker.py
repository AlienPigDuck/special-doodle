"""
Story picker: Haiku reads all collected articles and produces an English
briefing of the top stories from Japan's morning newspaper.
"""

import os
import logging
import anthropic

log = logging.getLogger(__name__)

_PROMPT = """You are a research assistant preparing the story briefing for "The Papers Say", a daily English-language podcast that reads and discusses Japan's morning newspaper for an international audience.

You have been given articles from today's Japanese morning newspaper. All articles are in Japanese — read and translate them all.

Your job is to identify the 10-12 most newsworthy stories and write a clear English briefing on each one. Always include every article from the 1面 (front page) section. Fill the remaining slots with the most important stories from other sections.

Output each story as follows. Skip any section where you have no material.

1. LEAD STORY
The single most important story today. What happened, who is involved, key figures and numbers, why it matters internationally. 3-5 sentences.

2. FRONT PAGE
All remaining 1面 front-page stories. For each: what happened, key details, significance. 2-3 sentences each.

3. POLITICS & ECONOMY
Major domestic Japanese political or economic developments. One sentence each: what happened and why it matters.

4. INTERNATIONAL
Stories about other countries or global events covered in the Japanese press today. One sentence each: what happened and why it matters.

5. BUSINESS & CORPORATE
Company news, earnings, deals, strategy announcements. One sentence each: company, what happened, the number.

6. MARKETS & INVESTMENT
Market moves, analyst calls, investment themes. One sentence each.

7. THE BURIED STORY
One story from deeper in the paper that deserves more attention than it got. Explain why it caught your eye. 2-3 sentences.

Rules:
- If an article is in Japanese, translate its key points into clear English.
- Be specific: name people, companies, countries, amounts, percentages.
- Skip pure sports, lifestyle, food, and entertainment.
- Keep total output under 1200 words.

JAPANESE NAMES: Japan's Prime Minister is Sanae Takaichi (高市早苗). Always romanise her surname as "Takaichi" — never "Takayama", "Takita", or any other spelling. Romanise other Japanese officials' and companies' names with the same care."""


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
_CHAR_BUDGET = 150_000


def pick(articles) -> str:
    if not articles:
        log.warning("Picker: no articles")
        return "No articles collected for this session."

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    ordered = sorted(articles, key=lambda a: _SECTION_PRIORITY.get(a.section or "", 99))
    blocks = []
    used_chars = len(_PROMPT)
    skipped = 0

    for i, a in enumerate(ordered, 1):
        lang = " [JAPANESE]" if a.language == "ja" else ""
        body = a.body.strip() if a.body else "(headline only)"
        block = f"[{i}] Section: {a.section or 'Unknown'}{lang}\nTitle: {a.title}\n{body}"
        if used_chars + len(block) > _CHAR_BUDGET:
            skipped += 1
            continue
        blocks.append(block)
        used_chars += len(block)

    if skipped:
        log.info("Picker: included %d/%d articles (%d skipped)", len(blocks), len(ordered), skipped)

    user_content = _PROMPT + "\n\n---\n\n" + "\n\n---\n\n".join(blocks)

    log.info("Picker: briefing top stories from %d articles with Haiku...", len(articles))
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": user_content}],
    )
    result = msg.content[0].text
    log.info("Picker: complete (%d chars)", len(result))
    log.info("Picker output:\n%s", result)
    return result
