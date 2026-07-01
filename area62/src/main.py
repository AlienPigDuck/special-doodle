"""
Area 62 — orchestrator.
Scrapes Nikkei evening edition (夕刊) listing, translates headlines to English,
outputs area62/headlines.json via GitHub Contents API.
"""

import os
import sys
import json
import base64
import logging
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

SECTION_TRANSLATIONS = {
    '１面':             'Front Page',
    'ビジネス':         'Business',
    '総合':             'General News',
    'マーケット・投資': 'Markets & Investment',
    'ニュースぷらす':   'News Plus',
    '社会':             'Society',
    '文化':             'Culture',
    'other':            'Other',
}


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
            log.warning("Area 62: translate batch %d/%d failed (%s) — keeping originals", b + 1, n_batches, e)
            translated = []
        # Always keep alignment with the batch, whatever the model returned
        if len(translated) != len(batch):
            log.warning("Area 62: batch %d/%d count mismatch (%d vs %d) — padding with originals",
                        b + 1, n_batches, len(translated), len(batch))
            translated = (list(translated) + batch[len(translated):])[:len(batch)]
        out.extend(translated)
    log.info("Area 62: translated %d titles in %d batch(es)", len(out), n_batches)
    return out


def build_output(articles: list[tuple[str, str, str]], titles_en: list[str]) -> dict:
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)

    sections: dict[str, list[dict]] = {}
    section_order: list[str] = []

    for (url, title_ja, section_ja), title_en in zip(articles, titles_en):
        section_en = SECTION_TRANSLATIONS.get(section_ja, section_ja)
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
    path = "area62/headlines.json"
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
        "message": f"Area 62: headlines {content['date']}",
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
    log.info("Area 62: pushed headlines.json (%d articles)", content["total"])


def main():
    token = os.environ.get("GH_PUSH_TOKEN", "")
    if not token:
        log.error("GH_PUSH_TOKEN not set")
        sys.exit(1)

    log.info("Area 62: collecting from Nikkei evening edition...")
    articles = collect.fetch()
    if not articles:
        log.error("Area 62: no articles collected — aborting (no evening edition today?)")
        sys.exit(1)

    log.info("Area 62: translating %d titles...", len(articles))
    titles_ja = [title for _, title, _ in articles]
    titles_en = translate_titles(titles_ja)

    if len(titles_en) != len(articles):
        log.error("Area 62: translation count mismatch (%d vs %d)", len(titles_en), len(articles))
        sys.exit(1)

    output = build_output(articles, titles_en)
    log.info("Area 62: built output — %d sections, %d articles", len(output["sections"]), output["total"])

    push_to_github(output, token)
    log.info("Area 62: done — %s", output["date"])


if __name__ == "__main__":
    main()
