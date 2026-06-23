"""
Area 61: synthesize today's Tokyo Open script in Christie's ElevenLabs voice.
Reads from tokyoopen/scripts/YYYY-MM-DD.txt, pushes area61/neil-voice.mp3.
"""

import os
import re
import sys
import json
import base64
import logging
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

VOICE_ID   = "wJGkbGKuvsunqgB3PHyW"  # christie
MODEL_ID   = "eleven_multilingual_v2"
CHUNK_SIZE = 4500

PRONUNCIATIONS = {
    "Nikkei": "Nikkay",
    "nikkei": "nikkay",
}

# ── TTS text normalisation ────────────────────────────────────────────────────

_TTS_ONES   = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_TTS_TEENS  = ["ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
               "sixteen", "seventeen", "eighteen", "nineteen"]
_TTS_TENS   = ["", "", "twenty", "thirty", "forty", "fifty",
               "sixty", "seventy", "eighty", "ninety"]
_TTS_DIGITS = ["zero", "one", "two", "three", "four", "five",
               "six", "seven", "eight", "nine"]


def _year_suffix(n: int) -> str:
    if n == 0:   return "hundred"
    if n <= 9:   return "oh " + _TTS_ONES[n]
    if n <= 19:  return _TTS_TEENS[n - 10]
    t, o = divmod(n, 10)
    return _TTS_TENS[t] + ("-" + _TTS_ONES[o] if o else "")


def _year_to_words(year: int) -> str:
    if year == 2000: return "two thousand"
    if 2001 <= year <= 2009: return "two thousand and " + _TTS_ONES[year % 10]
    if (1900 <= year <= 1999) or (2010 <= year <= 2099):
        return ("nineteen" if year < 2000 else "twenty") + " " + _year_suffix(year % 100)
    return str(year)


def normalize_for_tts(text: str) -> str:
    # 1. Decimals: 1.56 → "1 point five six"
    text = re.sub(
        r'\b(\d+)\.(\d+)\b',
        lambda m: m.group(1) + " point " + " ".join(_TTS_DIGITS[int(d)] for d in m.group(2)),
        text,
    )
    # 2. Years: 2026 → "twenty twenty-six", 2007 → "two thousand and seven"
    text = re.sub(r'\b((?:19|20)\d{2})\b', lambda m: _year_to_words(int(m.group(1))), text)
    # 3. Four-digit tickers: 6758 → "six seven five eight"
    text = re.sub(
        r'\b(\d{4})(?:\.T)?\b',
        lambda m: " ".join(_TTS_DIGITS[int(d)] for d in m.group(1)),
        text,
    )
    return text


def find_script() -> str | None:
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).strftime("%Y-%m-%d")
    path = Path(f"tokyoopen/scripts/{today}.txt")
    if path.exists():
        log.info("Found script: %s", path)
        return path.read_text()
    log.warning("No Tokyo Open script found at %s", path)
    return None


def clean_script(text: str) -> str:
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[ALEX]"):
            line = line[6:].strip()
        elif line.startswith("[MAYA]"):
            line = line[6:].strip()
        if line:
            for word, phonetic in PRONUNCIATIONS.items():
                line = line.replace(word, phonetic)
            lines.append(normalize_for_tts(line))
    return "\n\n".join(lines)


def split_chunks(text: str) -> list[str]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for para in paras:
        if len(current) + len(para) + 2 > CHUNK_SIZE and current:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para
    if current:
        chunks.append(current.strip())
    return chunks


def synthesize_chunk(api_key: str, text: str, out_path: Path) -> None:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"
    payload = json.dumps({
        "text": text,
        "model_id": MODEL_ID,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            out_path.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"ElevenLabs TTS {e.code}: {body}") from e
    log.info("  chunk → %s (%d KB)", out_path.name, out_path.stat().st_size // 1024)


def push_mp3(mp3_path: Path, token: str) -> None:
    repo    = "AlienPigDuck/special-doodle"
    path    = "area61/neil-voice.mp3"
    api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }
    content_b64 = base64.b64encode(mp3_path.read_bytes()).decode()

    sha = None
    req = urllib.request.Request(api_url, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            sha = json.loads(r.read())["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise

    payload = {
        "message": f"Area 61: neil-voice.mp3 {datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    req = urllib.request.Request(
        api_url, data=json.dumps(payload).encode(), headers=headers, method="PUT"
    )
    with urllib.request.urlopen(req) as r:
        r.read()
    log.info("Pushed neil-voice.mp3 (%.1f MB)", mp3_path.stat().st_size / 1_000_000)


def main():
    api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    token   = os.environ.get("GH_PUSH_TOKEN", "")
    if not api_key:
        log.error("ELEVENLABS_API_KEY not set — skipping ElevenLabs synthesis")
        sys.exit(0)

    script = find_script()
    if not script:
        log.warning("No Tokyo Open script available — skipping")
        sys.exit(0)

    script = clean_script(script)
    chunks = split_chunks(script)
    log.info("Script: %d chars → %d chunks", len(script), len(chunks))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        parts  = []

        for i, chunk in enumerate(chunks):
            out = tmpdir / f"chunk_{i:03d}.mp3"
            log.info("Chunk %d/%d (%d chars)...", i + 1, len(chunks), len(chunk))
            synthesize_chunk(api_key, chunk, out)
            parts.append(out)
            if i < len(chunks) - 1:
                time.sleep(0.5)

        concat = tmpdir / "concat.txt"
        concat.write_text("\n".join(f"file '{p}'" for p in parts))

        output = tmpdir / "neil-voice.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-acodec", "libmp3lame", "-b:a", "128k", str(output)],
            check=True, capture_output=True,
        )
        log.info("Stitched %d chunks → %.1f MB", len(parts), output.stat().st_size / 1_000_000)
        push_mp3(output, token)


if __name__ == "__main__":
    main()
