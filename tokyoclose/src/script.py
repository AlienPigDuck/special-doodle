"""
Generates Tokyo Close podcast scripts using Claude.
Three modes: WRAP (normal trading day), HOLIDAY, WEEKEND.
"""

import os
import logging
import anthropic
from datetime import date, timedelta

log = logging.getLogger(__name__)

# ── System prompts ────────────────────────────────────────────────────────────

WRAP_SYSTEM_PROMPT = """You write scripts for "Tokyo Close", a daily after-market podcast about the Japanese stock market.
The show has two hosts:
  [ALEX] - male, British, big-picture thinker, dry wit, likes macro and yen dynamics
  [MAYA] - female, American, stock-picker, always zeroes in on specific names and catalysts

Format every line as either [ALEX] or [MAYA] followed by what they say. No other tags or labels.
They talk TO each other naturally — they react, push back, finish each other's thoughts.
Short sentences. Write for the ear. Light banter is welcome.

Your listener is in London or New York, just waking up. They want to know exactly what happened in Tokyo today — definitive facts, not forecasts.

Cover these five areas across the conversation (weave them in naturally, don't announce them):
1. The headline number — Nikkei 225 and TOPIX final close, one-sentence verdict on the day
2. The main story — the 1-2 things that actually drove the market today (BOJ, yen, overnight US catalyst, earnings, macro data release)
3. Movers — 3-4 specific JP stocks that moved meaningfully today, with actual % figures and the reason why
4. Yen close — where USD/JPY closed and how it shaped exporters vs domestic names
5. London/NY handoff — one or two things the listener should watch tonight that could affect tomorrow's Tokyo session

Total: 600-800 words. End with a clear takeaway. No stage directions, no music cues.

ACCURACY RULE: Only use the numbers in the data provided. Do not invent or estimate figures. If Nikkei closed at 38,412, say 38,412 — do not say "around 38,400" or "above 38,000". If a stock fell 1.4%, say 1.4% — do not say "nearly 2%".
TONE: Confident and factual. These are things that already happened. Say "Toyota fell 1.4%" not "Toyota may have fallen".
NIKKEI CITATIONS: When a Nikkei article explains why a stock moved, cite it naturally — "According to Nikkei..." or "Nikkei reported this morning that...". Don't force citations everywhere, only where they add weight.
ANALYST RATINGS: If the briefing includes a broker upgrade, downgrade, or price-target change for a Nikkei 225 stock, work it in — name the broker and the new rating or target explicitly."""


HOLIDAY_SYSTEM_PROMPT = """You write very short scripts for "Tokyo Close", a daily podcast about the Japanese stock market.
The show has two hosts:
  [ALEX] - male, British, dry wit
  [MAYA] - female, American, warm and direct

Format every line as either [ALEX] or [MAYA] followed by what they say. No other tags.
Short sentences. Write for the ear.

Today is a Japanese national holiday. The Tokyo Stock Exchange is closed. Write a brief 3-5 line exchange that:
1. Acknowledges the holiday by name (it will be provided in the data below — use it)
2. States exactly when trading resumes (the next trading day will be provided — use that exact date)
3. Points listeners to "The Papers Say" at "christie dot vip slash t p s" for Japan news coverage

Total: 60-90 words only. Warm and brief — no filler."""


WEEKEND_SYSTEM_PROMPT = """You write very short scripts for "Tokyo Close", a daily podcast about the Japanese stock market.
The show has two hosts:
  [ALEX] - male, British, dry wit
  [MAYA] - female, American, warm and direct

Format every line as either [ALEX] or [MAYA] followed by what they say. No other tags.
Short sentences. Write for the ear.

Today is a Saturday or Sunday — the Tokyo Stock Exchange is closed for the weekend. Write a brief 3-5 line exchange that:
1. Acknowledges it's the weekend and markets are closed
2. Mentions when trading resumes (next trading day provided below — use that exact date)
3. Points listeners to "The Papers Say" at "christie dot vip slash t p s" for Japan news over the weekend

Total: 60-90 words only. Light and casual."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _next_trading_day(today: date) -> date:
    try:
        import exchange_calendars as xcals
        import pandas as pd
        cal = xcals.get_calendar("XTKS")
        check = today + timedelta(days=1)
        for _ in range(14):
            if cal.is_session(pd.Timestamp(check)):
                return check
            check += timedelta(days=1)
        return check
    except Exception:
        check = today + timedelta(days=1)
        while check.weekday() >= 5:
            check += timedelta(days=1)
        return check


def _holiday_name(today: date) -> str | None:
    try:
        import exchange_calendars as xcals
        import pandas as pd
        cal = xcals.get_calendar("XTKS")
        ts = pd.Timestamp(today)
        try:
            series = cal.regular_holidays.holidays(start=ts, end=ts, return_name=True)
            if len(series) > 0:
                name = str(series.iloc[0])
                if name and name.lower() not in ("nat", "none", "nan"):
                    return name
        except Exception:
            pass
        # Fallback: scan all regular holidays for this date
        try:
            all_hols = cal.regular_holidays.holidays(return_name=True)
            for dt, name in all_hols.items():
                if pd.Timestamp(dt).date() == today:
                    return str(name)
        except Exception:
            pass
    except Exception:
        pass
    return None


def _format_date_spoken(d: date) -> str:
    """Format date as 'Monday the 23rd of June' for TTS."""
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    month_names = ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December"]
    day = d.day
    if 11 <= day <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
    return f"{day_names[d.weekday()]} the {day}{suffix} of {month_names[d.month - 1]}"


# ── Market data formatter ─────────────────────────────────────────────────────

def _format_market_data(data: dict) -> str:
    lines = ["=== TODAY'S TOKYO CLOSE ==="]
    jp_session = data.get("last_jp_session")
    us_session = data.get("last_us_session")
    if jp_session:
        lines.append(f"  TSE session date : {jp_session}")
    if us_session:
        lines.append(f"  Last US session  : {us_session}")
    lines.append("")

    lines.append("=== INDICES (NIKKEI 225 + TOPIX TODAY) ===")
    for sym, d in data["indices"].items():
        pct = d.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        lines.append(f"  {d['label']} ({sym}): {d.get('price', 'N/A')} | {pct_str}")

    lines.append("\n=== KEY JAPANESE STOCKS — TODAY'S CLOSE ===")
    for sym, d in data["jp_stocks"].items():
        pct = d.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        lines.append(f"  {sym} ({d['name']}): {pct_str}")

    lines.append("\n=== US SECTOR ETFs (set the tone before today's TSE open) ===")
    for sym, d in data["sectors"].items():
        pct = d.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        label = d["label"].split("-")[0].strip() if "-" in d["label"] else d["label"]
        lines.append(f"  {sym}: {pct_str} - {label}")

    lines.append("\n=== KEY US STOCKS (last session — context for today's Tokyo moves) ===")
    for sym, d in data["us_stocks"].items():
        pct = d.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        lines.append(f"  {sym} ({d['name']}): {pct_str}")

    return "\n".join(lines)


# ── Public entry point ────────────────────────────────────────────────────────

def generate_script(
    market_data: dict,
    briefing: str,
    is_weekend: bool = False,
    is_holiday: bool = False,
) -> str:
    from datetime import timezone, timedelta, datetime
    jst = timezone(timedelta(hours=9))
    today = datetime.now(jst).date()

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if is_holiday:
        next_day = _next_trading_day(today)
        holiday = _holiday_name(today) or "a public holiday"
        next_spoken = _format_date_spoken(next_day)
        system = HOLIDAY_SYSTEM_PROMPT
        user_content = (
            f"HOLIDAY: {holiday}\n"
            f"NEXT TRADING DAY: {next_spoken} ({next_day.isoformat()})\n\n"
            "Write the holiday edition now. Name the holiday. Use the exact next trading day date provided."
        )
        edition = "holiday"

    elif is_weekend:
        next_day = _next_trading_day(today)
        next_spoken = _format_date_spoken(next_day)
        system = WEEKEND_SYSTEM_PROMPT
        user_content = (
            f"NEXT TRADING DAY: {next_spoken} ({next_day.isoformat()})\n\n"
            "Write the weekend edition now. Use the exact next trading day date provided."
        )
        edition = "weekend"

    else:
        system = WRAP_SYSTEM_PROMPT
        sections = [
            _format_market_data(market_data),
            "=== NEWS BRIEFING ===\n" + briefing,
            "Now write today's Tokyo Close episode. Factual, confident, specific. Write for the ear.",
        ]
        user_content = "\n\n".join(sections)
        edition = "wrap"

    log.info("Generating Tokyo Close %s script with Claude...", edition)
    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2500 if edition == "wrap" else 400,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return message.content[0].text
