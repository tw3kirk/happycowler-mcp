# -*- coding: utf-8 -*-
"""Standalone Playwright fetcher for HappyCow pages.

Run as a subprocess (keeps Playwright's sync API out of the MCP server's
asyncio loop). Prints the rendered page's visible text to stdout, or exits
non-zero with a message on an anti-bot block.

Usage:
    python -m happycowler._fetch <url>

Env:
    HC_HEADED=1   show a real Chrome window (better at getting past the WAF)
"""
import os
import sys


def fetch_text(url, timeout_ms=45000):
    from playwright.sync_api import sync_playwright

    headed = os.environ.get("HC_HEADED", "0") == "1"
    args = ["--disable-blink-features=AutomationControlled"]
    ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="chrome", headless=not headed, args=args)
        except Exception:
            browser = p.chromium.launch(headless=not headed, args=args)
        ctx = browser.new_context(user_agent=ua, locale="en-US",
                                  viewport={"width": 1280, "height": 1000})
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(4000)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        for _ in range(8):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)
        text = page.evaluate("() => document.body ? document.body.innerText : ''")
        browser.close()
        return text or ""


def _is_blocked(text):
    return (("Incapsula incident" in text) or ("Request unsuccessful" in text)
            or len(text.strip()) < 300)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.stderr.write("usage: python -m happycowler._fetch <url>\n")
        sys.exit(1)
    try:
        out = fetch_text(sys.argv[1])
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("FETCH_ERROR: %s\n" % str(exc)[:300])
        sys.exit(3)
    if _is_blocked(out):
        sys.stderr.write(
            "BLOCKED: HappyCow served an anti-bot (Incapsula) page. "
            "The IP is temporarily flagged; try again later or set HC_HEADED=1.\n")
        sys.exit(2)
    sys.stdout.write(out)
