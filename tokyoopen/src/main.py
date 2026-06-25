"""
Orchestrator: collect data → generate script → synthesize → push to GitHub.
"""

import os
import re
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

import market
import collect
import digest
import script
import tts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

OUTPUT_DIR  = Path(os.environ.get("OUTPUT_DIR", "/output"))
GH_REPO     = "AlienPigDuck/special-doodle"
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _gh_get_sha(headers: dict, path: str) -> str | None:
    r = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
        headers=headers,
    )
    return r.json().get("sha") if r.status_code == 200 else None


def _gh_put(headers: dict, path: str, content: bytes, message: str) -> None:
    body: dict = {
        "message": message,
        "content": base64.b64encode(content).decode(),
    }
    sha = _gh_get_sha(headers, path)
    if sha:
        body["sha"] = sha
    r = requests.put(
        f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
        headers=headers,
        json=body,
    )
    r.raise_for_status()
    log.info("GitHub ← %s", path)


def push_to_github(mp3_path: Path, date_str: str) -> None:
    token = os.environ.get("GH_PUSH_TOKEN")
    if not token:
        log.warning("GH_PUSH_TOKEN not set — skipping GitHub push")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    log.info("Pushing to GitHub...")
    _gh_put(headers, "tokyoopen/latest.mp3", mp3_path.read_bytes(), f"podcast: {date_str}")

    episode = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _gh_put(
        headers,
        "tokyoopen/episode.json",
        json.dumps(episode, indent=2).encode(),
        f"podcast metadata: {date_str}",
    )
    log.info("GitHub push complete")


def _get_recent_mentions(lookback: int = 3) -> dict[str, int]:
    """Count how many of the last `lookback` scripts mention each JP ticker."""
    from correlations import CORE_JP_STOCKS
    known = set(CORE_JP_STOCKS.keys())
    if not SCRIPTS_DIR.exists():
        return {}
    files = sorted(SCRIPTS_DIR.glob("*.txt"), reverse=True)[:lookback]
    counts: dict[str, int] = {}
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r'\b(\d{4})(?:\.T)?\b', text):
                sym = m.group(1) + ".T"
                if sym in known:
                    counts[sym] = counts.get(sym, 0) + 1
        except Exception as e:
            log.warning("Could not parse %s for recent mentions: %s", path, e)
    log.info("Recent mentions (%d scripts): %s", len(files), counts)
    return counts


def push_script(script_txt: Path, date_str: str) -> None:
    token = os.environ.get("GH_PUSH_TOKEN")
    if not token:
        return
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    _gh_put(
        headers,
        f"tokyoopen/scripts/{date_str}.txt",
        script_txt.read_bytes(),
        f"script: {date_str}",
    )
    log.info("Script archived to tokyoopen/scripts/%s.txt", date_str)


def run() -> None:
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    date_str = now_jst.strftime("%Y-%m-%d")
    is_weekend = now_jst.weekday() >= 5  # 5=Saturday, 6=Sunday in JST

    output_mp3 = OUTPUT_DIR / f"tokyo-open-{date_str}.mp3"
    script_txt = OUTPUT_DIR / f"tokyo-open-{date_str}.txt"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    edition = "Weekend" if is_weekend else "Weekday"
    log.info("=== Tokyo Open %s | %s ===", edition, date_str)

    max_age = 96 if is_weekend else 14
    market_data      = market.fetch_all()
    articles         = collect.fetch_all(max_age_hours=max_age)

    # Daily pre-open preview (（先読み株式相場）, ~07:30 JST) — a human-written read on
    # the day ahead. Purely additive and fully defensive: if it's missing or the
    # fetch fails, we log and carry on with the existing sources unchanged.
    if not is_weekend:
        try:
            import mynews_preview
            preview = mynews_preview.fetch()
        except Exception as e:
            log.warning("先読み preview step failed (%s) — continuing without it", e)
            preview = []
        if preview:
            articles = preview + articles  # lead with the day-ahead preview
            log.info("Tokyo Open: prepended （先読み株式相場）preview article as a source")

    briefing         = digest.generate(articles)
    recent_mentions  = _get_recent_mentions()

    episode_script = script.generate_script(
        market_data, briefing, is_weekend=is_weekend, recent_mentions=recent_mentions
    )
    script_txt.write_text(episode_script, encoding="utf-8")
    log.info("Script saved: %s", script_txt)

    tts.synthesize(episode_script, str(output_mp3))
    log.info("Audio: %s", output_mp3)

    push_to_github(output_mp3, date_str)
    push_script(script_txt, date_str)


if __name__ == "__main__":
    run()
