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
from sources.channel.jd_scraper.extractors import (  # noqa: E402
    best_price,
    classify_page,
    extract_dom_prices,
    fetch_p3_price,
    fetch_ware_business,
)
from sources.channel.jd_scraper.session import (  # noqa: E402
    human_delay,
    interactive_login,
    jd_browser,
    jd_browser_cdp,
    print_cdp_instructions,
    profile_ready,
)


def _open_item_page(page, sku: str, keyword: str | None = None) -> None:
    """Warm path: home -> optional search -> item (reduces bot signals vs direct deep link)."""
    page.goto("https://www.jd.com/", wait_until="domcontentloaded", timeout=45000)
    human_delay()
    if keyword:
        from urllib.parse import quote

        search_url = f"https://search.jd.com/Search?keyword={quote(keyword)}&enc=utf-8"
        page.goto(search_url, wait_until="domcontentloaded", timeout=45000, referer="https://www.jd.com/")
        human_delay()
        link = page.locator(f'a[href*="{sku}"]').first
        if link.count():
            link.click(timeout=10000)
            page.wait_for_load_state("domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000)
            return
    url = f"https://item.jd.com/{sku}.html"
    page.goto(url, wait_until="domcontentloaded", timeout=45000, referer="https://www.jd.com/")
    page.wait_for_timeout(2500)


def probe_sku(context, target: dict, *, keyword: str | None = None) -> dict:
    sku = target["sku_id"]
    url = f"https://item.jd.com/{sku}.html"
    page = context.new_page()
    result = {
        "label": target.get("label", sku),
        "sku_id": sku,
        "url": url,
        "final_url": "",
        "title": "",
        "page_flags": [],
        "dom": {},
        "p3_api": {},
        "ware_business": {},
        "price_cny": None,
        "msrp_cny": None,
        "price_source": None,
        "status": "fail",
        "probed_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        _open_item_page(page, sku, keyword=keyword or target.get("keyword"))
        result["final_url"] = page.url
        result["title"] = page.title() or ""
        body_snip = ""
        try:
            body_snip = page.locator("body").inner_text(timeout=5000)[:2000]
        except Exception:
            pass
        result["page_flags"] = classify_page(page.url, result["title"], body_snip)
        result["dom"] = extract_dom_prices(page)
        result["p3_api"] = fetch_p3_price(page, sku)
        result["ware_business"] = fetch_ware_business(page, sku)
        price, msrp, source = best_price(result["dom"], result["p3_api"], result["ware_business"])
        result["price_cny"] = price
        result["msrp_cny"] = msrp
        result["price_source"] = source
        if "freq403" in result["page_flags"]:
            result["status"] = "freq403"
        elif "soft_block" in result["page_flags"]:
            result["status"] = "soft_block"
        elif price is not None:
            result["status"] = "ok"
        elif "login_redirect" in result["page_flags"] or "login_wall" in result["page_flags"]:
            result["status"] = "login_required"
        else:
            result["status"] = "no_price"
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
    finally:
        page.close()
    return result


def run_probe(targets: list[dict], *, headed: bool, cdp_url: str | None = None) -> dict:
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
            results.append(probe_sku(context, target, keyword=target.get("keyword")))
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
        report = run_probe(targets, headed=args.headed, cdp_url=args.cdp)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if report["summary"]["ok"] == 0:
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    main()