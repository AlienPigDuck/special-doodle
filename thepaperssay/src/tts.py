"""
Single-host TTS for The Papers Say.
Rotates voices on a 3-day cycle (JST date mod 3):
  0 → Christie  (ElevenLabs cloned voice)
  1 → Maya      (Google Cloud TTS, en-GB-Journey-F)
  2 → Sarah     (Google Cloud TTS, en-US-Journey-F)
"""

import os
import re
import json
import time
import logging
import subprocess
import tempfile
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

from google.cloud import texttospeech
from google.api_core.exceptions import ResourceExhausted

log = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

ELEVENLABS_VOICE_ID = "wJGkbGKuvsunqgB3PHyW"  # christie
ELEVENLABS_MODEL    = "eleven_multilingual_v2"
ELEVENLABS_CHUNK    = 4500

GOOGLE_VOICES = {
    "maya":  ("en-GB-Journey-F", "en-GB"),
    "sarah": ("en-US-Journey-F", "en-US"),
}

PAUSE_BETWEEN_PARAGRAPHS = 0.45

PRONUNCIATIONS = {
    "Nikkei 225": "Neekay two two five",
    "nikkei 225": "neekay two two five",
    "Nikkei":  "Neekay",
    "nikkei":  "neekay",
    "USD/JPY": "dollar yen",
    "usd/jpy": "dollar yen",
    "EUR/JPY": "euro yen",
    "EUR/USD": "euro dollar",
    "GBP/JPY": "pound yen",
    "GBP/USD": "cable",
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
    # 3. Alphanumeric TSE tickers: 285A → "two eight five A" (must run before pure-digit rule)
    text = re.sub(
        r'\b(\d{3}[A-Za-z])(?:\.T)?\b',
        lambda m: " ".join(_TTS_DIGITS[int(d)] if d.isdigit() else d.upper() for d in m.group(1)),
        text,
    )
    # 4. Four-digit tickers: 6758 → "six seven five eight"
    text = re.sub(
        r'\b(\d{4})(?:\.T)?\b',
        lambda m: " ".join(_TTS_DIGITS[int(d)] for d in m.group(1)),
        text,
    )
    return text


def _pick_voice() -> str:
    # The Papers Say is always read by Sarah (American female Google voice).
    log.info("TPS voice: sarah (en-US-Journey-F)")
    return "sarah"


def _fix_pronunciation(text: str) -> str:
    for word, phonetic in PRONUNCIATIONS.items():
        text = text.replace(word, phonetic)
    return normalize_for_tts(text)



def _split_paragraphs(script: str) -> list[str]:
    return [_fix_pronunciation(b.strip()) for b in script.split("\n\n") if b.strip()]


# ── ElevenLabs path ──────────────────────────────────────────────────────────

def _el_split_chunks(text: str) -> list[str]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, current = [], ""
    for para in paras:
        if len(current) + len(para) + 2 > ELEVENLABS_CHUNK and current:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para
    if current:
        chunks.append(current.strip())
    return chunks


def _el_synthesize_chunk(api_key: str, text: str, out: Path) -> None:
    payload = json.dumps({
        "text": text,
        "model_id": ELEVENLABS_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
        data=payload,
        headers={"xi-api-key": api_key, "Content-Type": "application/json", "Accept": "audio/mpeg"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            out.write_bytes(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"ElevenLabs {e.code}: {body}") from e
    log.info("  EL chunk → %s (%d KB)", out.name, out.stat().st_size // 1024)


def _synthesize_elevenlabs(script: str, output_path: str) -> None:
    api_key = os.environ["ELEVENLABS_API_KEY"]
    chunks = _el_split_chunks(script)
    log.info("ElevenLabs: %d chars → %d chunks", len(script), len(chunks))

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        parts = []
        for i, chunk in enumerate(chunks):
            out = tmpdir / f"chunk_{i:03d}.mp3"
            log.info("Chunk %d/%d (%d chars)...", i + 1, len(chunks), len(chunk))
            _el_synthesize_chunk(api_key, chunk, out)
            parts.append(out)
            if i < len(chunks) - 1:
                time.sleep(0.5)

        concat = tmpdir / "concat.txt"
        concat.write_text("\n".join(f"file '{p}'" for p in parts))
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat), "-acodec", "libmp3lame", "-b:a", "128k", output_path],
            check=True, capture_output=True,
        )

    size_mb = Path(output_path).stat().st_size / 1_000_000
    log.info("ElevenLabs TTS complete: %s (%.1f MB)", output_path, size_mb)


# ── Google TTS path ──────────────────────────────────────────────────────────

def _synthesize_segment_google(client, text: str, voice_name: str, lang: str, path: Path) -> None:
    for attempt in range(6):
        try:
            response = client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=text),
                voice=texttospeech.VoiceSelectionParams(language_code=lang, name=voice_name),
                audio_config=texttospeech.AudioConfig(
                    audio_encoding=texttospeech.AudioEncoding.MP3,
                ),
            )
            path.write_bytes(response.audio_content)
            return
        except ResourceExhausted:
            wait = 2 ** attempt
            log.warning("Rate limited, retrying in %ds...", wait)
            time.sleep(wait)
    raise RuntimeError(f"Failed to synthesize after retries: {text[:60]}")


def _make_silence(duration_s: float, tmpdir: Path, name: str) -> Path:
    out = tmpdir / name
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=24000:cl=mono",
         "-t", str(duration_s),
         "-q:a", "9", "-acodec", "libmp3lame", str(out)],
        check=True, capture_output=True,
    )
    return out


def _synthesize_google(script: str, output_path: str, voice_key: str) -> None:
    voice_name, lang = GOOGLE_VOICES[voice_key]
    paragraphs = _split_paragraphs(script)
    if not paragraphs:
        log.error("TTS: no paragraphs found in script")
        return

    log.info("Google TTS: %d paragraphs with %s...", len(paragraphs), voice_name)
    client = texttospeech.TextToSpeechClient()

    with tempfile.TemporaryDirectory() as _tmpdir:
        tmpdir = Path(_tmpdir)
        paths = [tmpdir / f"seg_{i:04d}.mp3" for i in range(len(paragraphs))]

        for i, text in enumerate(paragraphs):
            try:
                _synthesize_segment_google(client, text, voice_name, lang, paths[i])
                time.sleep(0.5)
            except Exception as e:
                log.error("Paragraph %d failed: %s", i, e)

        silence = _make_silence(PAUSE_BETWEEN_PARAGRAPHS, tmpdir, "silence.mp3")
        concat_list = tmpdir / "concat.txt"
        with concat_list.open("w") as f:
            for i, path in enumerate(paths):
                if not path.exists():
                    log.warning("Missing segment: %s", path)
                    continue
                if i > 0:
                    f.write(f"file '{silence}'\n")
                f.write(f"file '{path}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list),
             "-acodec", "libmp3lame", "-b:a", "128k", output_path],
            check=True, capture_output=True,
        )

    size_mb = Path(output_path).stat().st_size / 1_000_000
    log.info("Google TTS complete: %s (%.1f MB)", output_path, size_mb)


# ── Public entry point ───────────────────────────────────────────────────────

def synthesize(script: str, output_path: str) -> None:
    voice = _pick_voice()
    if voice == "christie":
        try:
            _synthesize_elevenlabs(_fix_pronunciation(script), output_path)
        except Exception as e:
            log.warning("ElevenLabs failed (%s) — falling back to Sarah", e)
            fallback = _fix_host_name(script, "sarah")
            _synthesize_google(fallback, output_path, "sarah")
    else:
        _synthesize_google(script, output_path, voice)
