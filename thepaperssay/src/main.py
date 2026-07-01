"""
Orchestrator for The Papers Say.
collect → pick stories → write monologue → synthesize → push to GitHub.
"""

import os
import sys
import json
import base64
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Shared collectors live in tokyoopen/src — append so thepaperssay/src modules take priority
sys.path.append(str(Path(__file__).parent.parent.parent / "tokyoopen" / "src"))


def _load_dotenv() -> None:
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())

_load_dotenv()

import collect
import picker
import script
import tts

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
    _gh_put(headers, "tps/latest.mp3", mp3_path.read_bytes(), f"tps: {date_str}")

    episode = {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _gh_put(
        headers,
        "tps/episode.json",
        json.dumps(episode, indent=2).encode(),
        f"tps metadata: {date_str}",
    )
    log.info("GitHub push complete — available at https://christie.vip/tps/latest.mp3")


def run() -> None:
    jst = timezone(timedelta(hours=9))
    now_jst = datetime.now(jst)
    date_str = now_jst.strftime("%Y-%m-%d")
    # Human-readable date WITH weekday — passed to the script so the model
    # never has to infer the day of week from a bare ISO date (it guessed wrong).
    display_date = now_jst.strftime("%A, %-d %B %Y")

    output_mp3  = OUTPUT_DIR / f"the-papers-say-{date_str}.mp3"
    script_txt  = OUTPUT_DIR / f"the-papers-say-{date_str}.txt"
    stories_txt = OUTPUT_DIR / f"the-papers-say-{date_str}-stories.txt"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log.info("=== The Papers Say | %s ===", date_str)

    articles       = collect.fetch_all()
    selected       = picker.pick(articles)
    stories_txt.write_text(selected, encoding="utf-8")

    episode_script = script.generate_script(selected, display_date)
    script_txt.write_text(episode_script, encoding="utf-8")
    log.info("Script saved: %s", script_txt)

    tts.synthesize(episode_script, str(output_mp3))
    log.info("Audio: %s", output_mp3)

    push_to_github(output_mp3, date_str)

    token = os.environ.get("GH_PUSH_TOKEN")
    if token:
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }
        _gh_put(
            headers,
            f"tps/scripts/{date_str}.txt",
            script_txt.read_bytes(),
            f"tps script: {date_str}",
        )
        log.info("Script archived to tps/scripts/%s.txt", date_str)


if __name__ == "__main__":
    run()
