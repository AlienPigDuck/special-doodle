"""
Tokyo Close — orchestrator.
Runs at ~17:17 JST after TSE close. Reports what actually happened today.
"""

import os
import json
import base64
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _load_dotenv() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

_load_dotenv()

import sys
sys.path.append(str(Path(__file__).parent.parent.parent / "tokyoopen" / "src"))

import market
import collect
import digest
import script
import tts
import mynews  # Tokyo Close primary source: Nikkei /mynews post-close articles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))
GH_REPO    = "AlienPigDuck/special-doodle"


def _gh_get_sha(headers: dict, path: str) -> str | None:
    r = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
        headers=headers,
    )
    return r.json().get("sha") if r.status_code == 200 else None


def _gh_put(headers: dict, path: str, content: bytes, message: str) -> None:
    body: dict = {"message": message, "content": base64.b64encode(content).decode()}
    sha = _gh_get_sha(headers, path)
    if sha:
        body["sha"] = sha
    r = requests.put(
        f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
        headers=headers, json=body,
    )
    r.raise_for_status()
    log.info("GitHub ← %s", path)


def push_to_github(mp3_path: Path, script_txt: Path, date_str: str) -> None:
    token = os.environ.get("GH_PUSH_TOKEN")
    if not token:
        log.warning("GH_PUSH_TOKEN not set — skipping GitHub push")
        return
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    _gh_put(headers, "tokyoclose/latest.mp3",
            mp3_path.read_bytes(), f"close: {date_str}")
    _gh_put(headers, f"tokyoclose/scripts/{date_str}.txt",
            script_txt.read_bytes(), f"close script: {date_str}")
    episode = {"date": date_str}
    _gh_put(headers, "tokyoclose/episode.json",
            json.dumps(episode, indent=2).encode(), f"close meta: {date_str}")
    log.info("GitHub push complete")


def run() -> None:
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    date_str = now_jst.strftime("%Y-%m-%d")
    is_weekend = now_jst.weekday() >= 5

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_mp3 = OUTPUT_DIR / f"tokyo-close-{date_str}.mp3"
    script_txt = OUTPUT_DIR / f"tokyo-close-{date_str}.txt"

    log.info("=== Tokyo Close | %s ===", date_str)

    market_data = market.fetch_all()
    jp_open     = market_data.get("jp_open_today", True)
    is_holiday  = not jp_open and not is_weekend

    max_age = 24 if (is_holiday or is_weekend) else 12
    articles = collect.fetch_all(max_age_hours=max_age)

    # Primary source on trading days: Nikkei /mynews articles published after the
    # 15:30 TSE close — the actual, human-written wrap of today's session.
    if not (is_holiday or is_weekend):
        close_dt = now_jst.replace(hour=15, minute=30, second=0, microsecond=0)
        try:
            close_articles = mynews.fetch(after=close_dt)
        except Exception as e:
            log.warning("MyNews fetch failed (%s) — continuing without it", e)
            close_articles = []
        if close_articles:
            articles = close_articles + articles  # lead with the post-close coverage
            log.info("Tokyo Close: %d post-close /mynews articles prepended as primary source",
                     len(close_articles))

    briefing = digest.generate(articles)

    episode_script = script.generate_script(
        market_data=market_data,
        briefing=briefing,
        is_weekend=is_weekend,
        is_holiday=is_holiday,
    )
    script_txt.write_text(episode_script, encoding="utf-8")
    log.info("Script saved: %s", script_txt)

    tts.synthesize(episode_script, str(output_mp3))
    log.info("Audio: %s", output_mp3)

    push_to_github(output_mp3, script_txt, date_str)


if __name__ == "__main__":
    run()
