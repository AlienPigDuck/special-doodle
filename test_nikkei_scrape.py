"""
Run this locally before triggering any workflow to confirm Playwright
is extracting full article bodies from Nikkei.

Usage:
    NIKKEI_STATE=$(cat nikkei_state_b64.txt) python test_nikkei_scrape.py

Or if you have a saved state JSON:
    python test_nikkei_scrape.py --state-file /path/to/nikkei_state.json

Prints the first 500 chars of each article body so you can confirm
it's real Japanese article text, not empty strings.
"""

import os
import sys
import json
import base64
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "tokyoopen" / "src"))

from collectors.nikkei_auth import make_page
from collectors.nikkei_jp import _get_morning_url, _extract_links, _scrape_article

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", help="Path to nikkei state JSON file")
    parser.add_argument("--count", type=int, default=5, help="Number of articles to test (default 5)")
    args = parser.parse_args()

    if args.state_file:
        state_json = Path(args.state_file).read_text()
        os.environ["NIKKEI_STATE"] = base64.b64encode(state_json.encode()).decode()

    if not os.environ.get("NIKKEI_STATE"):
        print("ERROR: NIKKEI_STATE not set. Run setup_nikkei_auth.py first, then:")
        print("  export NIKKEI_STATE=$(base64 -w0 nikkei_state.json)")
        print("  python test_nikkei_scrape.py")
        sys.exit(1)

    print("Connecting to Nikkei via Playwright...")
    result = make_page("nikkei_jp")
    if not result:
        print("ERROR: Authentication failed")
        sys.exit(1)

    pw, browser, page = result
    try:
        morning_url = _get_morning_url(page)
        print(f"Morning URL: {morning_url}")
        page.goto(morning_url, wait_until="domcontentloaded", timeout=30000)

        links = _extract_links(page)
        print(f"Found {len(links)} article links")
        print()

        ok = 0
        empty = 0
        for url, link_title, section in links[:args.count]:
            title, body = _scrape_article(page, url)
            body_len = len(body)
            status = "OK" if body_len > 100 else "EMPTY"
            if body_len > 100:
                ok += 1
            else:
                empty += 1

            print(f"[{status}] [{section}] {title or link_title}")
            print(f"  URL: {url}")
            print(f"  Body: {body_len} chars")
            if body:
                print(f"  Preview: {body[body.find('文字'):body.find('文字')+400] if '文字' in body else body[:400]}")
            print()

        print(f"RESULT: {ok}/{args.count} articles have body content, {empty} empty")
        if empty == args.count:
            print("FAIL — scraper is still broken, do not trigger workflow")
            sys.exit(1)
        elif empty > 0:
            print("PARTIAL — some articles empty, investigate before running")
        else:
            print("PASS — all tested articles have content, safe to run workflow")

    finally:
        browser.close()
        pw.stop()

if __name__ == "__main__":
    main()
