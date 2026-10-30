"""
Area 61 — orchestrator.
Scrapes Nikkei morning edition listing, translates headlines to English,
outputs area61/headlines.json via GitHub Contents API.
"""

import os
import sys
import json
import base64
import logging
import re
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

import anthropic

sys.path.insert(0, os.path.dirname(__file__))
import collect

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# English names by base section (page numbers stripped and re-appended: 総合2 → General News 2).
SECTION_TRANSLATIONS = {
    '1面':             'Front Page',
    '総合':            'General News',
    '政治・外交':      'Politics & Diplomacy',
    '経済・政策':      'Economy & Policy',
    '金融経済':        'Finance',
    'グローバル市場':  'Global Markets',
    '国際':            'International',
    'アジアBiz':       'Asia Business',
    'ビジネス':        'Business',
    '投資':            'Investment',
    '商品':            'Commodities',
    '社説':            'Editorial',
    'オピニオン':      'Opinion',
    '経済教室':        'Economics Classroom',
    'マネーのまなび':  'Money & Investing',
    '医療・介護・健康': 'Healthcare',
    '詩歌・教養':      'Poetry & Culture',
    '読書':            'Books',
    '東京・首都圏経済': 'Tokyo & Metro Economy',
    '地域経済':        'Regional Economy',
    'スポーツ':        'Sports',
    '社会':            'Society',
    '社会・スポーツ':  'Society & Sports',
    '文化':            'Culture',
    'マーケット・投資': 'Markets & Investment',
    'ニュースぷらす':  'News Plus',
    'プラス1':         'Plus 1',
    'The STYLE':       'The STYLE',
    'unknown':         'Other',
}


def _section_base(name: str) -> str:
    """'総合２' → '総合', '１面' → '1面'."""
    return re.sub(r'\d+$', '', unicodedata.normalize('NFKC', name or '').strip())


def _translate_section(name: str) -> str:
    norm = unicodedata.normalize('NFKC', name or '').strip()
    base = _section_base(norm)
    num = norm[len(base):]
    return SECTION_TRANSLATIONS.get(base, base) + (f" {num}" if num else "")

# Sections to omit from Area 61 — keep it to news/markets, drop the arts/society pages.
EXCLUDE_SECTIONS = {'詩歌・教養', '読書', '社会', '文化'}  # base names, see _section_base


TRANSLATE_BATCH = 40  # keep each request well under the output token limit


def _translate_batch(client, titles_ja: list[str]) -> list[str]:
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles_ja))
    prompt = (
        "Translate these Japanese newspaper headlines to English. "
        "Return ONLY a JSON array of strings, same count and order, no explanation.\n\n"
        + numbered
    )
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(raw)


def translate_titles(titles_ja: list[str]) -> list[str]:
    if not titles_ja:
        return []
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    out: list[str] = []
    n_batches = (len(titles_ja) + TRANSLATE_BATCH - 1) // TRANSLATE_BATCH
    for b, i in enumerate(range(0, len(titles_ja), TRANSLATE_BATCH)):
        batch = titles_ja[i:i + TRANSLATE_BATCH]
        try:
            translated = _translate_batch(client, batch)
        except Exception as e:
            log.warning("Area 61: translate batch %d/%d failed (%s) — keeping originals", b + 1, n_batches, e)
            translated = []
        # Always keep alignment with the batch, whatever the model returned
        if len(translated) != len(batch):
            log.warning("Area 61: batch %d/%d count mismatch (%d vs %d) — padding with originals",
                        b + 1, n_batches, len(translated), len(batch))
            translated = (list(translated) + batch[len(translated):])[:len(batch)]
        out.extend(translated)
    log.info("Area 61: translated %d titles in %d batch(es)", len(out), n_batches)
    return out


def build_output(articles: list[tuple[str, str, str]], titles_en: list[str]) -> dict:
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)

    sections: dict[str, list[dict]] = {}
    section_order: list[str] = []

    for (url, title_ja, section_ja), title_en in zip(articles, titles_en):
        section_en = _translate_section(section_ja)
        if section_en not in sections:
            sections[section_en] = []
            section_order.append(section_en)
        sections[section_en].append({"title": title_en, "url": url})

    return {
        "date": now_jst.strftime("%Y-%m-%d"),
        "total": len(articles),
        "sections": [
            {"name": name, "articles": sections[name]}
            for name in section_order
        ],
    }


def push_to_github(content: dict, token: str) -> None:
    repo = "AlienPigDuck/special-doodle"
    path = "area61/headlines.json"
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    body_str = json.dumps(content, ensure_ascii=False, indent=2)
    body_b64 = base64.b64encode(body_str.encode()).decode()

    # Get current SHA if file exists
    sha = None
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read())["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    payload = {
        "message": f"Area 61: headlines {content['date']}",
        "content": body_b64,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="PUT",
    )
    with urllib.request.urlopen(req) as r:
        r.read()
    log.info("Area 61: pushed headlines.json (%d articles)", content["total"])


def main():
    token = os.environ.get("GH_PUSH_TOKEN", "")
    if not token:
        log.error("GH_PUSH_TOKEN not set")
        sys.exit(1)

    log.info("Area 61: collecting from Nikkei morning edition...")
    articles = collect.fetch()
    if not articles:
        log.error("Area 61: no articles collected — aborting")
        sys.exit(1)

    n0 = len(articles)
    articles = [a for a in articles if _section_base(a[2]) not in EXCLUDE_SECTIONS]
    log.info("Area 61: dropped %d articles from excluded sections (%d remain)", n0 - len(articles), len(articles))

    log.info("Area 61: translating %d titles...", len(articles))
    titles_ja = [title for _, title, _ in articles]
    titles_en = translate_titles(titles_ja)

    if len(titles_en) != len(articles):
        log.error("Area 61: translation count mismatch (%d vs %d)", len(titles_en), len(articles))
        sys.exit(1)

    output = build_output(articles, titles_en)
    log.info("Area 61: built output — %d sections, %d articles", len(output["sections"]), output["total"])

    push_to_github(output, token)
    log.info("Area 61: done — %s", output["date"])


if __name__ == "__main__":
    main()
