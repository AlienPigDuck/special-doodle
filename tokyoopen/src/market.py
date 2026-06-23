"""
Pulls market data via yfinance: US indices, FX, sector ETFs, key stocks.
"""

import yfinance as yf
import requests
from datetime import datetime, timedelta, timezone
import logging
from correlations import US_INDICES, SECTOR_ETFS, CORE_US_STOCKS, CORE_JP_STOCKS

log = logging.getLogger(__name__)

# Use requests.Session to bypass curl_cffi's bundled CA bundle issue
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; jpx-brief/1.0)"})


def _pct(ticker_obj) -> float | None:
    try:
        hist = ticker_obj.history(period="2d")
        if len(hist) < 2:
            return None
        prev, last = hist["Close"].iloc[-2], hist["Close"].iloc[-1]
        return round((last - prev) / prev * 100, 2)
    except Exception as e:
        log.warning("pct_change failed: %s", e)
        return None


def _latest_price(ticker_obj) -> float | None:
    try:
        hist = ticker_obj.history(period="1d")
        return round(float(hist["Close"].iloc[-1]), 4) if not hist.empty else None
    except Exception:
        return None


def fetch_indices() -> dict:
    results = {}
    tickers = yf.Tickers(" ".join(US_INDICES.keys()), session=_SESSION)
    for symbol, label in US_INDICES.items():
        t = tickers.tickers[symbol]
        results[symbol] = {
            "label": label,
            "price": _latest_price(t),
            "pct_change": _pct(t),
        }
    return results


def fetch_sector_etfs() -> dict:
    results = {}
    symbols = list(SECTOR_ETFS.keys())
    tickers = yf.Tickers(" ".join(symbols), session=_SESSION)
    for symbol in symbols:
        t = tickers.tickers[symbol]
        results[symbol] = {
            "label": SECTOR_ETFS[symbol],
            "pct_change": _pct(t),
        }
    return results


def fetch_us_stocks() -> dict:
    results = {}
    tickers = yf.Tickers(" ".join(CORE_US_STOCKS), session=_SESSION)
    for symbol in CORE_US_STOCKS:
        try:
            t = tickers.tickers[symbol]
            info = t.info
            results[symbol] = {
                "name": info.get("shortName", symbol),
                "price": _latest_price(t),
                "pct_change": _pct(t),
                "after_hours_pct": _after_hours_pct(t),
            }
        except Exception as e:
            log.warning("Skipping %s: %s", symbol, e)
    return results


def _after_hours_pct(ticker_obj) -> float | None:
    """Returns after-hours % move vs regular close if available."""
    try:
        info = ticker_obj.info
        reg_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
        post = info.get("postMarketPrice")
        if reg_close and post:
            return round((post - reg_close) / reg_close * 100, 2)
        return None
    except Exception:
        return None


def fetch_jp_stocks() -> dict:
    results = {}
    symbols = list(CORE_JP_STOCKS.keys())
    tickers = yf.Tickers(" ".join(symbols), session=_SESSION)
    for symbol, name in CORE_JP_STOCKS.items():
        t = tickers.tickers[symbol]
        results[symbol] = {
            "name": name,
            "price": _latest_price(t),
            "pct_change": _pct(t),
        }
    return results


def _last_session_date(symbol: str) -> str | None:
    """Return the date of the most recent trading session for a given ticker."""
    try:
        hist = yf.Ticker(symbol, session=_SESSION).history(period="5d")
        if hist.empty:
            return None
        return hist.index[-1].strftime("%Y-%m-%d")
    except Exception as e:
        log.warning("last_session_date failed for %s: %s", symbol, e)
        return None


def _jp_calendar_info(last_jp_session: str | None) -> dict:
    """
    Returns:
      jp_open_today  — True if TSE is open on today's JST date
      jp_holiday_gap — number of weekdays between last_jp_session and today
                       that were missed (0 on a normal trading day or after a weekend)
    Falls back gracefully if exchange_calendars is unavailable.
    """
    jst_tz = timezone(timedelta(hours=9))
    today = datetime.now(jst_tz).date()

    jp_open_today = True
    jp_holiday_gap = 0

    # ── is today a TSE session? ──────────────────────────────────────────────
    try:
        import exchange_calendars as xcals
        import pandas as pd
        cal = xcals.get_calendar("XTKS")
        jp_open_today = bool(cal.is_session(pd.Timestamp(today)))
    except Exception as e:
        log.warning("jp_open_today check failed: %s — assuming open", e)

    # ── how many weekdays did Japan miss since last session? ─────────────────
    if last_jp_session:
        from datetime import date as _date
        last = _date.fromisoformat(last_jp_session)
        cursor = last + timedelta(days=1)
        while cursor < today:
            if cursor.weekday() < 5:   # Mon–Fri only
                jp_holiday_gap += 1
            cursor += timedelta(days=1)

    return {"jp_open_today": jp_open_today, "jp_holiday_gap": jp_holiday_gap}


def _last_tse_session(today) -> str | None:
    """Most recent XTKS (Tokyo) session strictly before `today`, taken from the
    exchange calendar — authoritative and immune to yfinance's reporting lag on
    ^N225 (which previously made the script claim Tokyo had 'missed a session')."""
    try:
        import exchange_calendars as xcals
        import pandas as pd
        cal = xcals.get_calendar("XTKS")
        sessions = cal.sessions_in_range(
            pd.Timestamp(today) - pd.Timedelta(days=12),
            pd.Timestamp(today) - pd.Timedelta(days=1),
        )
        if len(sessions):
            return sessions[-1].strftime("%Y-%m-%d")
    except Exception as e:
        log.warning("last_tse_session calendar lookup failed: %s", e)
    return None


def fetch_all() -> dict:
    log.info("Fetching market data...")
    jst = timezone(timedelta(hours=9))
    today_jst = datetime.now(jst).date()
    # JP session DATE comes from the TSE calendar (authoritative). yfinance ^N225
    # can lag a day; relying on it made the script wrongly report a missed session.
    last_jp = _last_tse_session(today_jst) or _last_session_date("^N225")
    cal     = _jp_calendar_info(last_jp)
    return {
        "indices":          fetch_indices(),
        "sectors":          fetch_sector_etfs(),
        "us_stocks":        fetch_us_stocks(),
        "jp_stocks":        fetch_jp_stocks(),
        "last_us_session":  _last_session_date("SPY"),
        "last_jp_session":  last_jp,
        "jp_open_today":    cal["jp_open_today"],
        "jp_holiday_gap":   cal["jp_holiday_gap"],
        "fetched_at":       datetime.utcnow().isoformat() + "Z",
    }
