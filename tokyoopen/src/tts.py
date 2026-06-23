"""
Two-host TTS for Tokyo Open.
Alternates on a 2-day cycle (JST date mod 2):
  0 → ElevenLabs  (christie = Alex, isla = Maya)
  1 → Google TTS  (en-GB-Journey-D = Alex, en-GB-Journey-F = Maya)
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

# ElevenLabs
EL_VOICES = {
    "ALEX": "wJGkbGKuvsunqgB3PHyW",  # christie
    "MAYA": "h8eW5xfRUGVJrZhAFxqK",  # isla
}
EL_MODEL = "eleven_multilingual_v2"

# Google TTS
GOOGLE_VOICES = {
    "ALEX": "en-GB-Journey-D",
    "MAYA": "en-GB-Journey-F",
}

LINE_RE = re.compile(r"^\[(ALEX|MAYA)\]\s*(.+)$")

PAUSE_BETWEEN_TURNS = 0.40
PAUSE_SAME_SPEAKER  = 0.15

PRONUNCIATIONS = {
    "Nikkei":  "Nikkay",
    "nikkei":  "nikkay",
    "USD/JPY": "dollar yen",
    "usd/jpy": "dollar yen",
    "EUR/JPY": "euro yen",
    "EUR/USD": "euro dollar",
    "GBP/JPY": "pound yen",
    "GBP/USD": "cable",
}

EL_PRONUNCIATIONS = {
    "Nikkei":  "Nikkay",
    "nikkei":  "nikkay",
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
    # 3. Four-digit tickers: 6758 → "six seven five eight" (years already replaced above)
    text = re.sub(
        r'\b(\d{4})(?:\.T)?\b',
        lambda m: " ".join(_TTS_DIGITS[int(d)] for d in m.group(1)),
        text,
    )
    return text


def _use_elevenlabs() -> bool:
    day = datetime.now(JST).timetuple().tm_yday
    if day % 2 == 0:
        if not os.environ.get("ELEVENLABS_API_KEY"):
            log.warning("ElevenLabs day but no API key — falling back to Google TTS")
            return False
        return True
    return False


def _fix_pronunciation(text: str, el: bool = False) -> str:
    table = EL_PRONUNCIATIONS if el else PRONUNCIATIONS
    for word, phonetic in table.items():
        text = text.replace(word, phonetic)
    return normalize_for_tts(text)


def _parse_script(script: str, el: bool = False) -> list[tuple[str, str]]:
    segments = []
    for line in script.splitlines():
        m = LINE_RE.match(line.strip())
        if m:
            segments.append((m.group(1), _fix_pronunciation(m.group(2).strip(), el=el)))
    return segments


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


def _stitch(segments: list[tuple[str, str]], paths: list[Path], tmpdir: Path, output_path: str) -> None:
    silence_turn = _make_silence(PAUSE_BETWEEN_TURNS, tmpdir, "silence_turn.mp3")
    silence_same = _make_silence(PAUSE_SAME_SPEAKER,  tmpdir, "silence_same.mp3")

    concat_list = tmpdir / "concat.txt"
    with concat_list.open("w") as f:
        prev_speaker = None
        for (speaker, _), path in zip(segments, paths):
            if not path.exists():
                log.warning("Missing segment: %s", path)
                continue
            if prev_speaker is not None:
                pause = silence_turn if speaker != prev_speaker else silence_same
                f.write(f"file '{pause}'\n")
            f.write(f"file '{path}'\n")
            prev_speaker = speaker

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(concat_list),
         "-acodec", "libmp3lame", "-b:a", "128k", output_path],
        check=True, capture_output=True,
    )
    size_mb = Path(output_path).stat().st_size / 1_000_000
    log.info("TTS complete: %s (%.1f MB)", output_path, size_mb)


# ── ElevenLabs path ──────────────────────────────────────────────────────────

def _el_synthesize_segment(api_key: str, text: str, voice_id: str, out: Path) -> None:
    payload = json.dumps({
        "text": text,
        "model_id": EL_MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
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
    log.info("  EL seg → %s (%d KB)", out.name, out.stat().st_size // 1024)


def _synthesize_elevenlabs(script: str, output_path: str) -> None:
    api_key = os.environ["ELEVENLABS_API_KEY"]
    segments = _parse_script(script, el=True)
    if not segments:
        log.error("No [ALEX]/[MAYA] lines found in script")
        return

    log.info("ElevenLabs: %d segments (christie=Alex, isla=Maya)", len(segments))
    with tempfile.TemporaryDirectory() as _tmpdir:
        tmpdir = Path(_tmpdir)
        paths = [tmpdir / f"seg_{i:04d}_{spk}.mp3" for i, (spk, _) in enumerate(segments)]

        for i, (spk, text) in enumerate(segments):
            try:
                _el_synthesize_segment(api_key, text, EL_VOICES[spk], paths[i])
                time.sleep(0.3)
            except Exception as e:
                log.error("Segment %d failed: %s", i, e)

        _stitch(segments, paths, tmpdir, output_path)


# ── Google TTS path ──────────────────────────────────────────────────────────

def _synthesize_segment_google(client, text: str, voice_name: str, path: Path) -> None:
    for attempt in range(6):
        try:
            response = client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=text),
                voice=texttospeech.VoiceSelectionParams(
                    language_code="en-GB",
                    name=voice_name,
                ),
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
    raise RuntimeError(f"Failed to synthesize after retries: {text[:50]}")


def _synthesize_google(script: str, output_path: str) -> None:
    segments = _parse_script(script, el=False)
    if not segments:
        log.error("No [ALEX]/[MAYA] lines found in script")
        return

    log.info("Google TTS: %d segments (Journey-D=Alex, Journey-F=Maya)", len(segments))
    client = texttospeech.TextToSpeechClient()

    with tempfile.TemporaryDirectory() as _tmpdir:
        tmpdir = Path(_tmpdir)
        paths = [tmpdir / f"seg_{i:04d}_{spk}.mp3" for i, (spk, _) in enumerate(segments)]

        for i, (spk, text) in enumerate(segments):
            try:
                _synthesize_segment_google(client, text, GOOGLE_VOICES[spk], paths[i])
                time.sleep(0.5)
            except Exception as e:
                log.error("Segment %d failed: %s", i, e)

        _stitch(segments, paths, tmpdir, output_path)


# ── Public entry point ───────────────────────────────────────────────────────

def synthesize(script: str, output_path: str) -> None:
    if _use_elevenlabs():
        log.info("Tokyo Open voice: ElevenLabs (christie + isla)")
        try:
            _synthesize_elevenlabs(script, output_path)
        except Exception as e:
            log.warning("ElevenLabs failed (%s) — falling back to Google TTS", e)
            _synthesize_google(script, output_path)
    else:
        log.info("Tokyo Open voice: Google TTS (Journey-D + Journey-F)")
        _synthesize_google(script, output_path)
