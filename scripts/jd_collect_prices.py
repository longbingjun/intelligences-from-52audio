#!/usr/bin/env python3
"""JD price probe/collect via Playwright persistent Chrome profile.

First-time login (opens real Chrome on YOUR machine):
  py scripts/jd_collect_prices.py --login

Probe 1-2 SKUs after login:
  py scripts/jd_collect_prices.py --probe
  py scripts/jd_collect_prices.py --probe --sku 10192266796615 --headed
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources.channel.jd_scraper.config import DEFAULT_PROBE_SKUS, PROBE_OUTPUT  # noqa: E402
from sources.channel.jd_scraper.probe import probe_sku  # noqa: E402
from sources.channel.jd_scraper.session import (  # noqa: E402
    human_delay,
    interactive_login,
    jd_browser,
    jd_browser_cdp,
    print_cdp_instructions,
    profile_ready,
)


def run_probe(
    targets: list[dict],
    *,
    headed: bool,
    cdp_url: str | None = None,
    wait_for_login: bool = False,
) -> dict:
    use_cdp = bool(cdp_url)
    if not use_cdp and not profile_ready():
        print("No browser profile yet.")
        print_cdp_instructions()
        print("Or run: py scripts/jd_collect_prices.py --login")
        sys.exit(2)
    results = []
    ctx_mgr = jd_browser_cdp(cdp_url) if use_cdp else jd_browser(headless=not headed)
    with ctx_mgr as context:
        for i, target in enumerate(targets):
            if i:
                human_delay()
            results.append(
                probe_sku(
                    context,
                    target,
                    keyword=target.get("keyword"),
                    wait_for_login=wait_for_login,
                )
            )
    ok = sum(1 for r in results if r["status"] == "ok")
    report = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "mode": "cdp" if use_cdp else "playwright_profile",
        "cdp_url": cdp_url or "",
        "profile_ready": profile_ready(),
        "headed": headed,
        "summary": {"total": len(results), "ok": ok, "overall": "WORKS" if ok else "FAILS"},
        "results": results,
    }
    PROBE_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROBE_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="JD price probe via Playwright profile")
    parser.add_argument("--login", action="store_true", help="Open Chrome to log into JD (first time)")
    parser.add_argument("--probe", action="store_true", help="Probe SKU(s) using saved profile")
    parser.add_argument("--sku", action="append", help="SKU id (repeatable); default: 2 test SKUs")
    parser.add_argument("--headed", action="store_true", help="Show browser window during probe (profile mode)")
    parser.add_argument(
        "--wait-login",
        action="store_true",
        help="遇到京东登录页时暂停，手动登录后按 Enter 继续",
    )
    parser.add_argument(
        "--cdp",
        nargs="?",
        const="http://127.0.0.1:9222",
        default=None,
        help="Attach to Chrome started with --remote-debugging-port (recommended)",
    )
    parser.add_argument("--cdp-help", action="store_true", help="Print how to start Chrome for CDP mode")
    args = parser.parse_args()

    if args.cdp_help:
        print_cdp_instructions()
        return

    if args.login:
        interactive_login()
        print("Profile saved. Next: py scripts/jd_collect_prices.py --probe --headed")
        return

    if args.probe:
        if args.sku:
            targets = [{"label": s, "sku_id": s} for s in args.sku]
        else:
            targets = DEFAULT_PROBE_SKUS
        report = run_probe(
            targets,
            headed=args.headed,
            cdp_url=args.cdp,
            wait_for_login=args.wait_login,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["summary"]["ok"] == 0:
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()