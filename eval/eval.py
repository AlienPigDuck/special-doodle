"""
Daily evaluation for Tokyo Open and The Papers Say.
Runs at 8:00 AM JST (23:00 UTC) after both podcasts have been generated.

For each project:
  1. Quality gate  — heuristic checks, no API call
  2. Self-critique — Haiku evaluates today's script
  3. Drift report  — Haiku compares this week's scripts for recurring themes / blind spots

Findings are written to {project}/findings/YYYY-MM-DD.md.
Scripts and findings older than 7 days are pruned.
"""

import os
import re
import json
import base64
import logging
import requests
import anthropic
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

GH_REPO = "AlienPigDuck/special-doodle"
KEEP_DAYS = 7


# ── GitHub helpers ────────────────────────────────────────────────────────────

def _headers() -> dict:
    token = os.environ["GH_PUSH_TOKEN"]
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}


def _gh_list(path: str) -> list[dict]:
    r = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
        headers=_headers(),
    )
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return r.json() if isinstance(r.json(), list) else []


def _gh_get_text(path: str) -> str | None:
    r = requests.get(
        f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
        headers=_headers(),
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    return base64.b64decode(data["content"]).decode("utf-8")


def _gh_put(path: str, content: bytes, message: str) -> None:
    h = _headers()
    body: dict = {"message": message, "content": base64.b64encode(content).decode()}
    r = requests.get(f"https://api.github.com/repos/{GH_REPO}/contents/{path}", headers=h)
    if r.status_code == 200:
        body["sha"] = r.json()["sha"]
    r2 = requests.put(f"https://api.github.com/repos/{GH_REPO}/contents/{path}", headers=h, json=body)
    r2.raise_for_status()
    log.info("GitHub ← %s", path)


def _gh_delete(path: str, sha: str, message: str) -> None:
    r = requests.delete(
        f"https://api.github.com/repos/{GH_REPO}/contents/{path}",
        headers=_headers(),
        json={"message": message, "sha": sha},
    )
    r.raise_for_status()
    log.info("GitHub ✕ %s", path)


def _prune(folder: str, keep: int) -> None:
    files = sorted(_gh_list(folder), key=lambda f: f["name"])
    for f in files[:-keep]:
        try:
            _gh_delete(f["path"], f["sha"], f"prune: {f['name']}")
        except Exception as e:
            log.warning("Prune failed [%s]: %s", f["path"], e)


# ── Quality gate (heuristic, no API) ─────────────────────────────────────────

def _quality_gate_tokyo(script: str) -> list[str]:
    lines = []
    words = len(script.split())
    tickers = set(re.findall(r'\b\d{4}\.T\b', script))
    citations = len(re.findall(r'(?:According to|Nikkei reports|Nikkei is reporting|a Nikkei)', script, re.I))
    paragraphs = len([p for p in script.split("\n\n") if p.strip()])
    ratings = len(re.findall(r'(?:upgrade|downgrade|price target|rating)', script, re.I))

    lines.append(f"- Word count: **{words}** {'✓' if words >= 600 else '✗ (target ≥600)'}")
    lines.append(f"- Paragraphs / segments: **{paragraphs}** {'✓' if paragraphs >= 10 else '✗ (target ≥10)'}")
    lines.append(f"- Unique JP tickers mentioned: **{len(tickers)}** {'✓' if len(tickers) >= 3 else '⚠ (target ≥3)'} — {', '.join(sorted(tickers)) or 'none'}")
    lines.append(f"- Nikkei source citations: **{citations}** {'✓' if citations >= 1 else '⚠ (target ≥1)'}")
    lines.append(f"- Analyst rating mentions: **{ratings}**")
    return lines


def _quality_gate_tps(script: str) -> list[str]:
    lines = []
    words = len(script.split())
    paragraphs = len([p for p in script.split("\n\n") if p.strip()])
    citations = len(re.findall(r'(?:According to|reports that|is reporting)', script, re.I))
    cap_words = re.findall(r'\b[A-Z][a-z]{2,}\b', script)
    unique_caps = len(set(cap_words))

    lines.append(f"- Word count: **{words}** {'✓' if words >= 800 else '✗ (target ≥800)'}")
    lines.append(f"- Paragraphs / segments: **{paragraphs}** {'✓' if paragraphs >= 8 else '✗ (target ≥8)'}")
    lines.append(f"- Source citations: **{citations}** {'✓' if citations >= 2 else '⚠ (target ≥2)'}")
    lines.append(f"- Unique named entities (proxy): **{unique_caps}** {'✓' if unique_caps >= 20 else '⚠ (target ≥20)'}")
    return lines


# ── Self-critique (Haiku) ─────────────────────────────────────────────────────

_CRITIQUE_TOKYO = """You are evaluating a script for "Tokyo Open", a daily Japanese stock market podcast.

Rate this script on four dimensions. For each, give a score 1–5 and 1–3 specific callouts (good or bad lines/passages).

1. SPECIFICITY — Are actual ticker codes, company names, and numeric figures used? Or is it vague?
2. COVERAGE — Does it cover macro/yen, specific JP stock catalysts, and at least one wildcard?
3. ACCURACY RISK — Any claims that seem invented, exaggerated, or unsupported by what a market brief would know?
4. ENGAGEMENT — Is the dialogue natural and interesting, or robotic and repetitive?

End with: OVERALL RECOMMENDATION — one sentence on what to improve next time.

Script:
"""

_CRITIQUE_TPS = """You are evaluating a script for "The Papers Say", a daily Japan news podcast hosted by a single American female voice.

Rate this script on four dimensions. For each, give a score 1–5 and 1–3 specific callouts (good or bad passages).

1. STORY COVERAGE — How many distinct news stories are discussed? Are the most important ones given enough depth?
2. SPECIFICITY — Are people, companies, countries, amounts, and dates named? Or is it vague?
3. TRANSLATION QUALITY — Is Japanese context explained clearly for an international audience?
4. PACING & VOICE — Does it sound like a natural radio monologue, or like a list being read aloud?

End with: OVERALL RECOMMENDATION — one sentence on what to improve next time.

Script:
"""


def _self_critique(script: str, project: str, client) -> str:
    prompt = _CRITIQUE_TOKYO if project == "tokyoopen" else _CRITIQUE_TPS
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt + script}],
    )
    return msg.content[0].text


# ── Drift detection (Haiku) ───────────────────────────────────────────────────

_DRIFT_TOKYO = """You are analyzing a week of scripts from "Tokyo Open", a daily Japanese stock market podcast.

Compare today's script (marked TODAY) against the previous scripts (marked DAY-1, DAY-2, etc.).

SYSTEM CONTEXT — three changes were made on 2026-06-23 to reduce anchoring:
  (a) US→JP correlation map now only surfaces entries where the US stock, SOX, S&P 500, or Dow moved significantly — flat days produce no correlation triggers.
  (b) A "recently covered" warning is injected listing JP stocks mentioned in the last 3 scripts, telling the model to avoid them without a fresh catalyst.
  (c) Sector ETF labels were stripped of their embedded JP ticker hints — the model now sees only the ETF name and % move, and must draw its own conclusions about which JP stocks are affected.
These changes are intentional. Evaluate whether they are helping or hurting.

Answer these questions:
1. RECURRING THEMES — What topics, company names, or tickers appeared in almost every episode this week? List them.
2. BLIND SPOTS — What important market themes or sectors have been consistently absent or underrepresented?
3. ANCHORING — Is the show still over-relying on the same 2–3 JP stock names regardless of news? Name them. If anchoring has reduced, say so explicitly.
4. ANTI-ANCHOR CHECK — For each of the previously overused stocks (Kioxia 285A, Advantest 6857, Tokyo Electron 8035): did they appear this week? If so, was there a clear catalyst, or were they still used as reflexive filler?
5. DIVERSITY — Are new or less-frequently-covered JP stocks appearing? Name any that stand out as fresh picks.
6. UNINTENDED CONSEQUENCES — Does anything look worse since the changes? For example: are sectors being missed that were previously covered via the ETF hints? Is the show less specific or less grounded than before?
7. YEN COVERAGE — Has USD/JPY and its implications been covered each day, or dropped some days?
8. RECOMMENDATION — One concrete suggestion based on this week's evidence.

"""

_DRIFT_TPS = """You are analyzing a week of scripts from "The Papers Say", a daily Japan news podcast.

Compare today's script (marked TODAY) against the previous scripts (marked DAY-1, DAY-2, etc.).

Answer these questions:
1. RECURRING STORIES — What topics or story types came up in almost every episode this week?
2. MISSING ANGLES — What kinds of Japanese news stories have been consistently absent (e.g. regional news, labour, environment, culture with economic significance)?
3. TONE CONSISTENCY — Is the host's voice consistent across episodes, or does it vary significantly?
4. DEPTH VS BREADTH — Is the show covering many stories shallowly, or fewer stories with real depth? Has this varied?
5. RECOMMENDATION — One concrete suggestion for next week.

"""


def _drift_report(scripts_by_day: list[tuple[str, str]], project: str, client) -> str:
    if len(scripts_by_day) < 2:
        return "_Not enough scripts yet for drift analysis (need at least 2 days)._"

    prompt = _DRIFT_TOKYO if project == "tokyoopen" else _DRIFT_TPS
    labelled = []
    for i, (date, text) in enumerate(scripts_by_day):
        label = "TODAY" if i == 0 else f"DAY-{i}"
        labelled.append(f"--- {label} ({date}) ---\n{text[:3000]}")

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt + "\n\n".join(labelled)}],
    )
    return msg.content[0].text


# ── Main per-project eval ─────────────────────────────────────────────────────

def evaluate_project(project: str, scripts_folder: str, findings_folder: str,
                     date_str: str, client) -> None:
    log.info("Evaluating %s...", project)

    # Fetch all scripts from the repo, sorted newest first
    files = sorted(_gh_list(scripts_folder), key=lambda f: f["name"], reverse=True)
    if not files:
        log.warning("%s: no scripts found in %s", project, scripts_folder)
        return

    scripts_by_day: list[tuple[str, str]] = []
    for f in files[:7]:
        text = _gh_get_text(f["path"])
        if text:
            day = f["name"].replace(".txt", "")
            scripts_by_day.append((day, text))

    if not scripts_by_day:
        log.warning("%s: could not download any scripts", project)
        return

    today_date, today_script = scripts_by_day[0]
    log.info("%s: today's script is %s (%d words)", project, today_date, len(today_script.split()))

    # 1. Quality gate
    gate_lines = _quality_gate_tokyo(today_script) if project == "tokyoopen" else _quality_gate_tps(today_script)

    # 2. Self-critique
    log.info("%s: running self-critique...", project)
    critique = _self_critique(today_script, project, client)

    # 3. Drift detection
    log.info("%s: running drift detection (%d scripts)...", project, len(scripts_by_day))
    drift = _drift_report(scripts_by_day, project, client)

    # Build findings markdown
    project_label = "Tokyo Open" if project == "tokyoopen" else "The Papers Say"
    md = f"""# {project_label} — Daily Eval — {date_str}

Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
Scripts analysed: {len(scripts_by_day)} (today + {len(scripts_by_day)-1} previous)

---

## 1. Quality Gate

{chr(10).join(gate_lines)}

---

## 2. Self-Critique

{critique}

---

## 3. Drift Report

{drift}
"""

    _gh_put(
        f"{findings_folder}/{date_str}.md",
        md.encode("utf-8"),
        f"eval findings: {date_str}",
    )

    # Prune old scripts and findings
    _prune(scripts_folder, KEEP_DAYS)
    _prune(findings_folder, KEEP_DAYS)
    log.info("%s: eval complete", project)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    jst = timezone(timedelta(hours=9))
    date_str = datetime.now(jst).strftime("%Y-%m-%d")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    evaluate_project(
        project="tokyoopen",
        scripts_folder="tokyoopen/scripts",
        findings_folder="tokyoopen/findings",
        date_str=date_str,
        client=client,
    )

    evaluate_project(
        project="tps",
        scripts_folder="tps/scripts",
        findings_folder="tps/findings",
        date_str=date_str,
        client=client,
    )


if __name__ == "__main__":
    main()
