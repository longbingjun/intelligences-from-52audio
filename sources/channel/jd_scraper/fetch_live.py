"""Fetch live JD price by scraping the website (Playwright / CDP). No API required."""



from __future__ import annotations



from dataclasses import dataclass, field

from typing import Any



from sources.channel.jd_client import pick_best_hit, search_jd





@dataclass

class JdLivePrice:

    sku_id: str

    price_cny: float | None = None

    msrp_cny: float | None = None

    price_source: str = ""

    channel_url: str = ""

    shop_hint: str = ""

    fetch_error: str = ""

    probe: dict[str, Any] = field(default_factory=dict)



    def to_dict(self) -> dict:

        return {

            "sku_id": self.sku_id,

            "price_cny": self.price_cny,

            "msrp_cny": self.msrp_cny,

            "price_source": self.price_source,

            "channel_url": self.channel_url,

            "shop_hint": self.shop_hint,

            "fetch_error": self.fetch_error,

            "probe": self.probe,

        }





def _probe_result_to_live(sku: str, probe: dict) -> JdLivePrice:

    out = JdLivePrice(

        sku_id=sku,

        channel_url=f"https://item.jd.com/{sku}.html",

        probe=probe,

    )

    if probe.get("status") == "ok" and probe.get("price_cny") is not None:

        out.price_cny = probe["price_cny"]

        out.msrp_cny = probe.get("msrp_cny")

        src = probe.get("price_source") or "dom"

        out.price_source = f"jd_web_{src}"

        out.shop_hint = "京东（网页抓取）"

        return out

    out.fetch_error = probe.get("status") or probe.get("error") or "jd_web_no_price"

    return out





def fetch_jd_live_price(

    sku_id: str,

    *,

    brand: str = "",

    model: str = "",

    keyword: str | None = None,

    cdp_url: str | None = None,

    browser_context=None,

    use_browser: bool = True,

    allow_api_fallback: bool = False,

) -> JdLivePrice:

    """Scrape JD item page in a real browser (CDP or persistent Chrome profile)."""

    sku = str(sku_id or "").strip()

    out = JdLivePrice(sku_id=sku, channel_url=f"https://item.jd.com/{sku}.html" if sku else "")

    if not sku:

        out.fetch_error = "missing_sku"

        return out



    if not use_browser and not allow_api_fallback:

        out.fetch_error = "jd_browser_disabled"

        return out



    target = {

        "sku_id": sku,

        "label": keyword or sku,

        "keyword": keyword or f"{brand} {model}".strip(),

    }



    if use_browser:

        try:

            from sources.channel.jd_scraper.probe import probe_sku

            from sources.channel.jd_scraper.session import human_delay, jd_browser, jd_browser_cdp, profile_ready



            if browser_context is not None:

                probe = probe_sku(browser_context, target, keyword=target.get("keyword"))

                return _probe_result_to_live(sku, probe)



            if cdp_url:

                ctx_mgr = jd_browser_cdp(cdp_url)

            elif profile_ready():

                ctx_mgr = jd_browser(headless=False)

            else:

                out.fetch_error = "jd_browser_not_ready"

                out.probe = {

                    "hint": "Run: py scripts/jd_collect_prices.py --cdp-help",

                    "need": "Chrome with --remote-debugging-port=9222 logged into JD, or --login profile",

                }

                if not allow_api_fallback:

                    return out

                ctx_mgr = None



            if ctx_mgr is not None:

                with ctx_mgr as context:

                    probe = probe_sku(context, target, keyword=target.get("keyword"))

                return _probe_result_to_live(sku, probe)

        except Exception as exc:

            out.fetch_error = f"jd_web_error:{exc}"

            if not allow_api_fallback:

                return out



    if allow_api_fallback:

        from sources.channel.jd_client import fetch_jd_price



        live = fetch_jd_price(sku)

        if live and live.get("price_cny") is not None:

            out.price_cny = live["price_cny"]

            out.msrp_cny = live.get("msrp_cny")

            out.price_source = "jd_api"

            out.fetch_error = ""

            return out

        out.fetch_error = out.fetch_error or "jd_api_no_price"



    return out





def fetch_jd_live_prices_batch(

    items: list[dict],

    *,

    cdp_url: str | None = None,

) -> dict[str, JdLivePrice]:

    """Scrape multiple SKUs in one browser session (home -> search -> item per SKU)."""

    from sources.channel.jd_scraper.probe import probe_sku

    from sources.channel.jd_scraper.session import human_delay, jd_browser, jd_browser_cdp, profile_ready



    results: dict[str, JdLivePrice] = {}

    if not items:

        return results



    if cdp_url:

        ctx_mgr = jd_browser_cdp(cdp_url)

    elif profile_ready():

        ctx_mgr = jd_browser(headless=False)

    else:

        for it in items:

            sku = str(it.get("sku_id") or "")

            err = JdLivePrice(sku_id=sku, fetch_error="jd_browser_not_ready")

            results[sku] = err

        return results



    with ctx_mgr as context:

        for i, it in enumerate(items):

            sku = str(it.get("sku_id") or "").strip()

            if not sku:

                continue

            if i:

                human_delay()

            target = {

                "sku_id": sku,

                "label": it.get("label") or sku,

                "keyword": it.get("keyword") or it.get("search_query") or "",

            }

            probe = probe_sku(context, target, keyword=target.get("keyword"))

            results[sku] = _probe_result_to_live(sku, probe)

    return results





def discover_jd_sku(

    brand: str,

    model: str,

    *,

    keyword: str | None = None,

) -> JdLivePrice | None:

    """Best-effort SKU discovery via JD search HTML (price may still need browser scrape)."""

    q = keyword or f"{brand} {model}".strip()

    hits = search_jd(q)

    hit = pick_best_hit(hits, brand, model)

    if not hit:

        return None

    return JdLivePrice(

        sku_id=hit.sku_id,

        price_cny=hit.price_cny,

        msrp_cny=hit.msrp_cny,

        price_source="jd_search_html" if hit.price_cny is not None else "",

        channel_url=hit.channel_url,

        shop_hint=hit.shop_hint,

    )





def prices_differ(a: float | None, b: float | None, *, ratio: float = 0.12) -> bool:

    if a is None or b is None or a <= 0 or b <= 0:

        return False

    return abs(a - b) / max(a, b) > ratio

