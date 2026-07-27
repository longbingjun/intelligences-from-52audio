"""Playwright sessions: persistent profile OR attach to real Chrome via CDP."""

from __future__ import annotations

import random
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from playwright.sync_api import Browser, BrowserContext, sync_playwright

from sources.channel.jd_scraper.config import DEFAULT_CDP_URL, MAX_DELAY_SEC, MIN_DELAY_SEC, PROFILE_DIR, USER_AGENT


def profile_ready() -> bool:
    return PROFILE_DIR.exists() and any(PROFILE_DIR.iterdir())


def print_cdp_instructions(profile_dir: Path | None = None) -> None:
    prof = profile_dir or PROFILE_DIR
    prof.mkdir(parents=True, exist_ok=True)
    prof_win = str(prof.resolve()).replace("\\", "/")
    print(
        "\n=== Recommended: attach to YOUR Chrome (avoids Playwright automation fingerprint) ===\n"
        "1. Close ALL Chrome windows first.\n"
        "2. Open PowerShell and run ONE of:\n\n"
        '   & "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
        f'--remote-debugging-port=9222 --user-data-dir="{prof_win}"\n\n'
        "   (If Chrome is elsewhere, use your chrome.exe path.)\n"
        "3. In that Chrome: log into JD, manually open a product page and confirm price shows.\n"
        "4. Leave Chrome running, then in Cursor terminal:\n\n"
        "   py scripts/jd_collect_prices.py --probe --cdp --sku 10192266796615\n"
    )


def _launch_kwargs(*, headless: bool) -> dict:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return {
        "user_data_dir": str(PROFILE_DIR),
        "headless": headless,
        "locale": "zh-CN",
        "viewport": {"width": 1366, "height": 900},
        "user_agent": USER_AGENT,
        "channel": "chrome",
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
        ],
        "ignore_default_args": ["--enable-automation"],
    }


@contextmanager
def jd_browser(*, headless: bool = False) -> Iterator[BrowserContext]:
    """Playwright-launched Chrome. JD may still show soft-block even when logged in."""
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(**_launch_kwargs(headless=headless))
        except Exception:
            kwargs = _launch_kwargs(headless=headless)
            kwargs.pop("channel", None)
            context = p.chromium.launch_persistent_context(**kwargs)
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        try:
            yield context
        finally:
            context.close()


@contextmanager
def jd_browser_cdp(cdp_url: str = DEFAULT_CDP_URL) -> Iterator[BrowserContext]:
    """Attach to Chrome YOU started with --remote-debugging-port=9222."""
    with sync_playwright() as p:
        browser: Browser = p.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError(f"No browser context on {cdp_url}. Is Chrome running with --remote-debugging-port?")
        context = browser.contexts[0]
        try:
            yield context
        finally:
            browser.close()


def human_delay() -> None:
    time.sleep(random.uniform(MIN_DELAY_SEC, MAX_DELAY_SEC))


def interactive_login() -> None:
    print_cdp_instructions()
    print(
        "Alternative (often blocked by JD): Playwright opens Chrome for you.\n"
        "Press Enter to try Playwright login anyway, or Ctrl+C to use CDP steps above.\n"
    )
    input(">>> Enter to continue with Playwright login... ")
    print(f"Browser profile dir: {PROFILE_DIR}")
    with jd_browser(headless=False) as context:
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://passport.jd.com/new/login.aspx", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)
        page.goto("https://www.jd.com/", wait_until="domcontentloaded", timeout=60000)
        input("\n>>> Press Enter after JD login attempt... ")
