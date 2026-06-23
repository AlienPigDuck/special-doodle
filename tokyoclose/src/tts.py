"""
Two-host Google TTS for Tokyo Close.
ALEX = en-GB-Journey-D (male British)
MAYA = en-US-Journey-F (female American)
No ElevenLabs — Google TTS only.
"""

import re
import time
import logging
import subprocess
import tempfile
from pathlib import Path

from google.cloud import texttospeech
from google.api_core.exceptions import ResourceExhausted

log = logging.getLogger(__name__)

GOOGLE_VOICES = {
    "ALEX": ("en-GB-Journey-D", "en-GB"),
    "MAYA": ("en-US-Journey-F", "en-US"),
}

LINE_RE = re.compile(r"^\[(ALEX|MAYA)\]\s*(.+)$")

PAUSE_BETWEEN_TURNS = 0.40
PAUSE_SAME_SPEAKER  = 0.15

PRONUNCIATIONS = {
    "Nikkei 225": "Nikkay two two five",
    "nikkei 225": "nikkay two two five",
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
    # 2. Years: 2026 → "twenty twenty-six"
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


def _fix_pronunciation(text: str) -> str:
    for word, phonetic in PRONUNCIATIONS.items():
        text = text.replace(word, phonetic)
    return normalize_for_tts(text)


def _parse_script(script: str) -> list[tuple[str, str]]:
    segments = []
    for line in script.splitlines():
        m = LINE_RE.match(line.strip())
        if m:
            segments.append((m.group(1), _fix_pronunciation(m.group(2).strip())))
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


def _synthesize_segment_google(client, text: str, voice_name: str, lang_code: str, path: Path) -> None:
    for attempt in range(6):
        try:
            response = client.synthesize_speech(
                input=texttospeech.SynthesisInput(text=text),
                voice=texttospeech.VoiceSelectionParams(
                    language_code=lang_code,
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


def synthesize(script: str, output_path: str) -> None:
    segments = _parse_script(script)
    if not segments:
        log.error("No [ALEX]/[MAYA] lines found in script")
        return

    log.info("Google TTS: %d segments (Journey-D=Alex, Journey-F=Maya)", len(segments))
    client = texttospeech.TextToSpeechClient()

    with tempfile.TemporaryDirectory() as _tmpdir:
        tmpdir = Path(_tmpdir)
        paths = [tmpdir / f"seg_{i:04d}_{spk}.mp3" for i, (spk, _) in enumerate(segments)]

        for i, (spk, text) in enumerate(segments):
            voice_name, lang_code = GOOGLE_VOICES[spk]
            try:
                _synthesize_segment_google(client, text, voice_name, lang_code, paths[i])
                time.sleep(0.5)
            except Exception as e:
                log.error("Segment %d (%s) failed: %s", i, spk, e)

        _stitch(segments, paths, tmpdir, output_path)
