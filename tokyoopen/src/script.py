"""
Generates the podcast script using Claude.
Takes market data + news and returns a spoken-word script string.
"""

import os
import re
import logging
import anthropic
from correlations import US_TO_JP, SECTOR_ETFS, CORE_JP_STOCKS, SEMI_US_STOCKS

US_MOVE_THRESHOLD = 2.0   # only show US→JP correlation entries where US moved ≥ this %

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You write scripts for "Tokyo Open", a daily pre-market podcast about the Japanese stock market.
The show has two hosts:
  [ALEX] - male, big-picture thinker, loves macro and yen dynamics, slightly dry humor
  [MAYA] - female, stock-picker, always zeroes in on specific names and catalysts, enthusiastic

Format every line as either [ALEX] or [MAYA] followed by what they say. No other tags or labels.
They talk TO each other naturally - they react, agree, push back, finish each other's thoughts.
Short sentences. Write for the ear. Light banter is welcome. No jargon dumps.
Listeners are retail investors who care about specific stocks.

Cover these five areas across the conversation (weave them in naturally, don't announce them):
1. Hook - the most important thing in 1-2 lines to open the show
2. US market close - S&P, Nasdaq, Dow; VIX and 10yr yield if they moved
3. Yen - USD/JPY move and what it means for exporters vs importers
4. Tokyo movers - 2-4 specific Japanese stocks with clear US catalysts; always name the company AND ticker
5. Wild cards - oil, gold, macro events, anything else relevant

Total: 600-800 words. End warmly. No stage directions, no music cues, no parenthetical notes - just dialogue.

ACCURACY RULE: Only use numbers and figures from the data provided. Never round up to a level that was not actually reached. If the Nikkei closed at 71,250, say 71,250 — do not say "above 72,000". If a stock moved 1.8%, say 1.8% — do not say "nearly 2%". Invented or exaggerated figures destroy listener trust.

TRADING SESSION DATES: The briefing includes the actual last US and Japanese trading session dates. Use these when referring to when a move happened — never infer the day from the calendar. If the data notes that Tokyo already traded after the last US session, treat US moves from that session as potentially already priced into Japanese stocks; do not present them as fresh catalysts for today's Tokyo open unless there is specific evidence they have not yet been reflected.

NIKKEI CITATIONS: When a Nikkei article underpins a claim, cite it naturally — e.g. "According to Nikkei…", "A Nikkei report this morning says…", or "Nikkei is reporting that…". Use citations to add authority, not as filler. Don't force a citation on every line — only where it adds weight.

ANALYST RATINGS: If the briefing includes a broker upgrade, downgrade, or price-target change for any Nikkei 225 stock, work it into the dialogue. Name the broker (Daiwa, Nomura, Jefferies, Mizuho, JPMorgan, Morgan Stanley, Goldman Sachs, SMBC Nikko, Citigroup, UBS, etc.) and state the new rating or target explicitly. A rating change from a major house on a large-cap is always worth a line."""

HOLIDAY_PREVIEW_SYSTEM_PROMPT = """You write scripts for "Tokyo Open", a daily pre-market podcast about the Japanese stock market.
The show has two hosts:
  [ALEX] - male, big-picture thinker, loves macro and yen dynamics, slightly dry humor
  [MAYA] - female, stock-picker, always zeroes in on specific names and catalysts, enthusiastic

Format every line as either [ALEX] or [MAYA] followed by what they say. No other tags or labels.
They talk TO each other naturally — short sentences, write for the ear, light banter welcome.

Today is a Japanese national holiday — the Tokyo Stock Exchange is closed. This is a short holiday edition.

Open by acknowledging the holiday (name it if the data mentions it, otherwise just say markets are closed today).
Then cover briefly:
1. What US and other major markets did in the most recent session
2. One or two key catalysts or stocks to watch when Tokyo reopens tomorrow
3. A warm, short close ("see you tomorrow" energy)

Total: 200-300 words. Keep it brief — this is a heads-up, not a full episode.

ACCURACY RULE: Only use numbers and figures from the data provided. Never invent figures.
TRADING SESSION DATES: Use the actual last US session date from the briefing — never infer from the calendar."""

WEEKEND_SYSTEM_PROMPT = """You write scripts for "Tokyo Open Weekend", a weekly review and preview podcast about the Japanese stock market.
The show has two hosts:
  [ALEX] - male, big-picture thinker, loves macro and yen dynamics, slightly dry humor
  [MAYA] - female, stock-picker, always zeroes in on specific names and catalysts, enthusiastic

Format every line as either [ALEX] or [MAYA] followed by what they say. No other tags or labels.
They talk TO each other naturally - they react, agree, push back, finish each other's thoughts.
Short sentences. Write for the ear. Light banter is welcome. No jargon dumps.
Listeners are retail investors planning their week ahead.

This is a weekend edition. Markets are closed. Cover these four areas naturally:
1. Week in review - the 2-3 biggest stories that moved or will move Japanese markets; name specific stocks and sectors
2. Macro picture - yen trend, US rates, oil, gold; what the direction means for Japan
3. World news impact - geopolitical events, trade developments, central bank signals that Japan investors should watch
4. Week ahead preview - key events coming up (central bank meetings, major earnings, economic data releases, political events) and how they may impact the Tokyo session

Total: 700-900 words. End with a clear takeaway for the week. No stage directions, no music cues, no parenthetical notes - just dialogue.

ACCURACY RULE: Only use numbers and figures from the data provided. Never round up to a level that was not actually reached. Invented or exaggerated figures destroy listener trust.

TRADING SESSION DATES: The briefing includes the actual last US and Japanese trading session dates. Use these when referring to when a move happened — never infer the day from the calendar. If the data notes that Tokyo already traded after the last US session, treat those US moves as potentially already priced in.

NIKKEI CITATIONS: When a Nikkei article underpins a claim, cite it naturally — e.g. "According to Nikkei…" or "Nikkei is reporting that…". Use citations to add authority, not as filler.

ANALYST RATINGS: If the briefing includes a broker upgrade, downgrade, or price-target change for any Nikkei 225 stock, work it into the dialogue. Name the broker and state the new rating or target explicitly."""


def _format_market_data(data: dict) -> str:
    from datetime import date as _date
    lines = ["=== LAST TRADING SESSIONS ==="]
    us_session = data.get("last_us_session")
    jp_session = data.get("last_jp_session")
    if us_session:
        lines.append(f"  Last US session date : {us_session}")
    if jp_session:
        lines.append(f"  Last JP session date : {jp_session}")
    if us_session and jp_session:
        us_d = _date.fromisoformat(us_session)
        jp_d = _date.fromisoformat(jp_session)
        if jp_d > us_d:
            lines.append(
                f"  NOTE: Tokyo had a trading session on {jp_session} AFTER the last US "
                f"close on {us_session}. US moves from {us_session} may already be "
                f"reflected in Japanese stocks — treat them as potentially priced in, "
                f"not as fresh catalysts."
            )
        elif us_d > jp_d:
            gap = data.get("jp_holiday_gap", 0)
            sessions_word = "session" if gap == 1 else "sessions"
            lines.append(
                f"  NOTE: Japan missed {gap} trading {sessions_word} (last JP close was "
                f"{jp_session}; last US close was {us_session}). Tokyo is reopening today "
                f"having not yet reacted to US moves from that period — treat them as "
                f"fresh catalysts accumulated during Japan's absence."
            )
    lines.append("")
    lines.append("=== US INDICES ===")
    for sym, d in data["indices"].items():
        pct = d.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        lines.append(f"  {d['label']} ({sym}): {d.get('price', 'N/A')} | {pct_str}")

    lines.append("\n=== SECTOR ETFs (US) ===")
    for sym, d in data["sectors"].items():
        pct = d.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        label = d['label'].split('-')[0].strip() if '-' in d['label'] else d['label']
        lines.append(f"  {sym}: {pct_str} - {label}")

    lines.append("\n=== KEY US STOCKS ===")
    for sym, d in data["us_stocks"].items():
        pct = d.get("pct_change")
        ah = d.get("after_hours_pct")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        ah_str = f" | AH: {ah:+.2f}%" if ah is not None else ""
        lines.append(f"  {sym} ({d['name']}): {pct_str}{ah_str}")

    lines.append("\n=== KEY JAPANESE STOCKS (previous Tokyo close) ===")
    for sym, d in data["jp_stocks"].items():
        pct = d.get("pct_change")
        pct_str = f"{pct:+.2f}%" if pct is not None else "N/A"
        lines.append(f"  {sym} ({d['name']}): {pct_str}")

    return "\n".join(lines)


def _format_correlation_map(market_data: dict | None = None) -> str:
    us_stocks = (market_data or {}).get("us_stocks", {})
    indices   = (market_data or {}).get("indices", {})

    def _idx_pct(sym):
        return (indices.get(sym) or {}).get("pct_change")

    sp_pct  = _idx_pct("^GSPC")
    dow_pct = _idx_pct("^DJI")
    sox_pct = _idx_pct("^SOX")

    broad_market = any(
        p is not None and abs(p) >= US_MOVE_THRESHOLD
        for p in (sp_pct, dow_pct)
    )
    sox_move = sox_pct is not None and abs(sox_pct) >= US_MOVE_THRESHOLD

    lines = ["=== US->JP CORRELATION MAP ==="]
    shown_corr = 0
    for us_sym, jp_list in US_TO_JP.items():
        us_pct = (us_stocks.get(us_sym) or {}).get("pct_change")
        individual  = us_pct is not None and abs(us_pct) >= US_MOVE_THRESHOLD
        sox_trigger = sox_move and us_sym in SEMI_US_STOCKS

        if not (individual or sox_trigger or broad_market):
            continue
        for jp_sym, jp_name, reason in jp_list:
            lines.append(f"  {us_sym} move -> {jp_name} ({jp_sym}): {reason}")
            shown_corr += 1

    if shown_corr == 0:
        lines.append("  (No significant moves in S&P, Dow, SOX, or individual stocks today)")
    return "\n".join(lines)


def generate_script(market_data: dict, briefing: str, is_weekend: bool = False,
                    recent_mentions: dict[str, int] | None = None) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    jp_open   = market_data.get("jp_open_today", True)
    is_holiday = not jp_open and not is_weekend

    if is_holiday:
        system  = HOLIDAY_PREVIEW_SYSTEM_PROMPT
        closing = "Now write today's Tokyo Open holiday edition. Keep it short and warm — Tokyo is closed but we're keeping an eye on things."
        edition = "holiday"
    elif is_weekend:
        system  = WEEKEND_SYSTEM_PROMPT
        closing = "Now write today's Tokyo Open Weekend episode. Weekly review, week ahead preview. Warm, conversational, specific. Write for the ear."
        edition = "weekend"
    else:
        system  = SYSTEM_PROMPT
        closing = "Now write today's Tokyo Open episode. Remember: warm, conversational, specific. Write for the ear."
        edition = "weekday"

    sections = [_format_market_data(market_data), _format_correlation_map(market_data)]

    if recent_mentions:
        total = max(recent_mentions.values()) if recent_mentions else 1
        mention_lines = ["=== RECENTLY COVERED JP STOCKS (last 3 episodes) ==="]
        for sym, count in sorted(recent_mentions.items(), key=lambda x: -x[1]):
            name = CORE_JP_STOCKS.get(sym, sym)
            mention_lines.append(f"  {sym} ({name}) — {count}/{total} recent episodes")
        mention_lines.append(
            "  NOTE: Do not mention these stocks unless today's market data or news "
            "briefing contains a specific new catalyst for them."
        )
        sections.append("\n".join(mention_lines))

    sections += ["=== NEWS BRIEFING ===\n" + briefing, closing]
    user_content = "\n\n".join(sections)

    log.info("Generating %s script with Claude...", edition)
    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=2500,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )
    return message.content[0].text
