#!/usr/bin/env python3
"""渠道（ZOL + 京东 + 官网）enrich：补售价与电商溯源。

用法:
  python scripts/enrich_commerce.py huawei--freebuds-pro-5
  python scripts/enrich_commerce.py --headphones --limit 20
  python scripts/enrich_commerce.py huawei--freebuds-pro-5 --jd-cdp

价格优先级：京东网页抓取 live > ZOL li.b2c-jd > ZOL 参考价 > hints > 官网 MSRP

京东价默认通过 Playwright 打开网页抓取（无需 API）。请先登录京东：
  py scripts/jd_collect_prices.py --cdp-help
  py scripts/enrich_commerce.py huawei--freebuds-pro-5 --jd-cdp
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.paths import (  # noqa: E402
    commerce_hints_path,
    products_dir,
    products_index_path,
    write_channel_enrich,
    write_official_enrich,
)
from core.scope import HEADPHONE_CATEGORIES  # noqa: E402
from sources.channel.jd_scraper.fetch_live import (  # noqa: E402
    JdLivePrice,
    discover_jd_sku,
    fetch_jd_live_price,
    prices_differ,
)
from sources.channel.jd_union_client import (  # noqa: E402
    pick_best_union_hit,
    union_configured,
    union_detail,
    union_search,
)
from sources.channel.smzdm_client import fetch_smzdm_prices, smzdm_configured  # noqa: E402
from sources.channel.zol_client import (  # noqa: E402
    _commerce_search_query,
    fetch_zol_prices,
    score_product_title,
    zol_jd_quote,
)
from sources.official.fetcher import (  # noqa: E402
    fetch_official_page,
    resolve_official_url,
    search_official_site,
)

INDEX_PATH = products_index_path()


def _load_hints() -> dict:
    path = commerce_hints_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_product(canonical_id: str) -> dict | None:
    path = products_dir() / f"{canonical_id}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _list_headphone_products(limit: int | None = None) -> list[str]:
    idx_path = products_index_path()
    if not idx_path.exists():
        return []
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    ids: list[str] = []
    for p in index.get("products") or []:
        if p.get("category") in HEADPHONE_CATEGORIES:
            ids.append(p["canonical_id"])
    if limit:
        return ids[:limit]
    return ids


def _pick_channel_price(
    *,
    zol_jd_price: float | None,
    zol_tmall_price: float | None,
    jd_live_price: float | None,
    jd_live_source: str,
    zol_reference: float | None,
    hint_price: float | None,
    official_msrp: float | None,
    zol_only: bool = False,
) -> tuple[float | None, str, str]:
    """Return (price_cny, price_source, price_note)."""
    note_parts: list[str] = []

    if jd_live_price is not None:
        if zol_jd_price is not None and prices_differ(zol_jd_price, jd_live_price):
            note_parts.append(f"ZOL京东价¥{zol_jd_price:g} vs 京东live¥{jd_live_price:g}")
        return jd_live_price, jd_live_source or "jd_live", "; ".join(note_parts)

    if zol_jd_price is not None:
        note = "仅ZOL京东区块价，未拿到京东live复核"
        if zol_reference and prices_differ(zol_jd_price, zol_reference):
            note += f"；ZOL参考价¥{zol_reference:g}"
        return zol_jd_price, "zol_jd", note

    if zol_tmall_price is not None:
        return zol_tmall_price, "zol_tmall", "ZOL天猫区块价"

    if zol_reference is not None:
        return zol_reference, "zol_reference", "ZOL参考报价区间"

    if not zol_only and hint_price is not None:
        return hint_price, "jd_hint", ""

    if not zol_only and official_msrp is not None:
        return official_msrp, "official_msrp", "渠道价缺失，使用官网MSRP"

    return None, "unresolved", ""


def enrich_channel(
    canonical_id: str,
    brand: str,
    model: str,
    hints: dict,
    *,
    skip_zol: bool = False,
    use_jd_browser: bool = True,
    cdp_url: str | None = None,
    browser_context=None,
    allow_jd_api_fallback: bool = False,
    no_union: bool = True,
    jd_live_prefetched: JdLivePrice | None = None,
    zol_only: bool = False,
) -> dict:
    product_hint = hints.get(canonical_id) or {}
    zol_hint = product_hint.get("zol") or {}
    jd_hint = product_hint.get("jd") or {}
    query = _commerce_search_query(brand, model) or f"{brand} {model}".strip()

    smzdm_info = (
        fetch_smzdm_prices(brand=brand, model=model, query=query)
        if not zol_only and smzdm_configured()
        else None
    )
    smzdm_hit = smzdm_info.best_hit if smzdm_info else None

    zol_info = None
    zol_jd = None
    zol_tmall = None
    if not skip_zol:
        zol_info = fetch_zol_prices(
            brand=brand,
            model=model,
            query=query,
            product_id=zol_hint.get("product_id"),
            product_url=zol_hint.get("product_url"),
        )
        if zol_info.product_name and score_product_title(zol_info.product_name, brand, model) < 1.5:
            zol_info.fetch_error = "zol_product_mismatch"
            zol_info.reference_price_cny = None
            zol_info.channel_quotes = []
        else:
            zol_jd = zol_jd_quote(zol_info)
            zol_tmall = next(
                (q for q in zol_info.channel_quotes if q.platform == "tmall"),
                None,
            )

    zol_jd_price = zol_jd.price_cny if zol_jd else None
    zol_tmall_price = zol_tmall.price_cny if zol_tmall else None
    zol_reference = zol_info.reference_price_cny if zol_info else None
    sku_id = (zol_jd.sku_id if zol_jd else None) or jd_hint.get("sku_id")
    channel_url = (
        (zol_jd.url if zol_jd and zol_jd_price is not None else "")
        or (zol_tmall.url if zol_tmall and zol_tmall_price is not None else "")
        or (zol_info.product_url if zol_info and zol_reference is not None else "")
        or jd_hint.get("channel_url", "")
    )
    shop_hint = (
        "京东（ZOL li.b2c-jd）"
        if zol_jd_price is not None
        else "天猫（ZOL li.b2c-tmall）"
        if zol_tmall_price is not None
        else ""
    )
    live_error = zol_info.fetch_error if zol_info and zol_info.fetch_error else ""

    # 值得买（若已配置）
    if not zol_only and smzdm_hit and smzdm_hit.price_cny is not None:
        return {
            "canonical_id": canonical_id,
            "price_cny": smzdm_hit.price_cny,
            "msrp_cny": zol_reference,
            "reference_price_cny": zol_reference,
            "zol_jd_price_cny": zol_jd_price,
            "zol_tmall_price_cny": zol_tmall_price,
            "zol_jd_url": zol_jd.url if zol_jd else "",
            "zol_tmall_url": zol_tmall.url if zol_tmall else "",
            "jd_live_price_cny": None,
            "price_source": "smzdm_jd" if "京东" in (smzdm_hit.mall_name or "") else "smzdm",
            "channel_url": smzdm_hit.url or channel_url,
            "sku_id": smzdm_hit.sku_id or sku_id,
            "shop_hint": f"值得买 · {smzdm_hit.mall_name or ''}".strip(),
            "search_query": query,
            "price_note": "",
            "live_error": "",
            "smzdm": smzdm_info.to_dict() if smzdm_info else None,
            "zol": zol_info.to_dict() if zol_info else None,
            "jd_live": None,
            "captured_at": datetime.now(timezone.utc).date().isoformat(),
            "source_layer": "channel",
        }

    # 京东联盟（默认关闭，--allow-union 可启用）
    jd_live = None
    if not zol_only and not no_union and union_configured():
        if sku_id:
            u = union_detail(str(sku_id))
            if u and u.price_cny is not None:
                return _channel_result(
                    canonical_id,
                    price_cny=u.price_cny,
                    msrp_cny=u.msrp_cny or zol_reference,
                    zol_jd_price=zol_jd_price,
                    zol_tmall_price=zol_tmall_price,
                    jd_live_price=u.price_cny,
                    price_source="jd_union",
                    channel_url=u.channel_url or channel_url,
                    sku_id=str(sku_id),
                    shop_hint=u.shop_hint or shop_hint,
                    query=query,
                    zol_info=zol_info,
                    smzdm_info=smzdm_info,
                    jd_live_dict={"price_source": "jd_union", "price_cny": u.price_cny},
                )
        u_hits = union_search(query)
        u_best = pick_best_union_hit(u_hits, brand, model)
        if u_best and u_best.price_cny is not None:
            sku_id = sku_id or u_best.sku_id
            channel_url = channel_url or u_best.channel_url
            return _channel_result(
                canonical_id,
                price_cny=u_best.price_cny,
                msrp_cny=zol_reference,
                zol_jd_price=zol_jd_price,
                zol_tmall_price=zol_tmall_price,
                jd_live_price=u_best.price_cny,
                price_source="jd_union",
                channel_url=channel_url,
                sku_id=sku_id,
                shop_hint=u_best.shop_hint or shop_hint,
                query=query,
                zol_info=zol_info,
                smzdm_info=smzdm_info,
                jd_live_dict={"price_source": "jd_union", "price_cny": u_best.price_cny},
            )

    # 京东 live：默认从网页抓取（Playwright/CDP），不用 API
    jd_live = None if zol_only else jd_live_prefetched
    if jd_live is None and sku_id and use_jd_browser:
        jd_live = fetch_jd_live_price(
            str(sku_id),
            brand=brand,
            model=model,
            keyword=query,
            cdp_url=cdp_url,
            browser_context=browser_context,
            use_browser=True,
            allow_api_fallback=allow_jd_api_fallback,
        )
    elif jd_live is None and not sku_id and use_jd_browser:
        discovered = discover_jd_sku(brand, model, keyword=query)
        if discovered:
            sku_id = discovered.sku_id
            channel_url = channel_url or discovered.channel_url
            shop_hint = shop_hint or discovered.shop_hint
            jd_live = fetch_jd_live_price(
                discovered.sku_id,
                brand=brand,
                model=model,
                keyword=query,
                cdp_url=cdp_url,
                browser_context=browser_context,
                use_browser=True,
                allow_api_fallback=allow_jd_api_fallback,
            )
    elif not zol_only and jd_live is None and not sku_id:
        discovered = discover_jd_sku(brand, model, keyword=query)
        if discovered:
            sku_id = discovered.sku_id
            channel_url = channel_url or discovered.channel_url
            shop_hint = shop_hint or discovered.shop_hint
            if discovered.price_cny is not None:
                jd_live = discovered

    jd_live_price = jd_live.price_cny if jd_live else None
    jd_live_source = jd_live.price_source if jd_live else ""
    if jd_live and jd_live.channel_url:
        channel_url = jd_live.channel_url
    if jd_live and jd_live.shop_hint:
        shop_hint = jd_live.shop_hint

    hint_price = jd_hint.get("price_cny")
    price_cny, price_source, price_note = _pick_channel_price(
        zol_jd_price=zol_jd_price,
        zol_tmall_price=zol_tmall_price,
        jd_live_price=jd_live_price,
        jd_live_source=jd_live_source,
        zol_reference=zol_reference,
        hint_price=hint_price,
        official_msrp=None,
        zol_only=zol_only,
    )

    if price_cny is None:
        live_error = live_error or (jd_live.fetch_error if jd_live else "") or "no_channel_price"

    msrp_cny = (jd_live.msrp_cny if jd_live else None) or jd_hint.get("msrp_cny") or zol_reference

    return _channel_result(
        canonical_id,
        price_cny=price_cny,
        msrp_cny=msrp_cny,
        zol_jd_price=zol_jd_price,
        zol_tmall_price=zol_tmall_price,
        jd_live_price=jd_live_price,
        price_source=price_source,
        channel_url=channel_url,
        sku_id=str(sku_id) if sku_id else None,
        shop_hint=shop_hint or jd_hint.get("shop_hint", ""),
        query=query,
        price_note=price_note or jd_hint.get("price_note", ""),
        live_error=live_error if price_cny is None else "",
        zol_info=zol_info,
        smzdm_info=smzdm_info,
        jd_live_dict=jd_live.to_dict() if jd_live else None,
    )


def _channel_result(
    canonical_id: str,
    *,
    price_cny,
    msrp_cny,
    zol_jd_price,
    zol_tmall_price,
    jd_live_price,
    price_source,
    channel_url,
    sku_id,
    shop_hint,
    query,
    price_note="",
    live_error="",
    zol_info=None,
    smzdm_info=None,
    jd_live_dict=None,
) -> dict:
    zol_reference = zol_info.reference_price_cny if zol_info else None
    return {
        "canonical_id": canonical_id,
        "price_cny": price_cny,
        "msrp_cny": msrp_cny,
        "reference_price_cny": zol_reference,
        "zol_jd_price_cny": zol_jd_price,
        "zol_tmall_price_cny": zol_tmall_price,
        "zol_jd_url": (
            next((q.url for q in zol_info.channel_quotes if q.platform == "jd"), "")
            if zol_info
            else ""
        ),
        "zol_tmall_url": (
            next((q.url for q in zol_info.channel_quotes if q.platform == "tmall"), "")
            if zol_info
            else ""
        ),
        "jd_live_price_cny": jd_live_price,
        "price_source": price_source,
        "channel_url": channel_url or "",
        "sku_id": sku_id,
        "shop_hint": shop_hint or "",
        "search_query": query,
        "price_note": price_note,
        "live_error": live_error,
        "smzdm": smzdm_info.to_dict() if smzdm_info else None,
        "zol": zol_info.to_dict() if zol_info else None,
        "jd_live": jd_live_dict,
        "captured_at": datetime.now(timezone.utc).date().isoformat(),
        "source_layer": "channel",
    }


def _needs_official_fallback(channel: dict) -> bool:
    if channel.get("price_source") == "unresolved" or channel.get("price_cny") is None:
        return True
    zol = channel.get("zol") or {}
    err = zol.get("fetch_error") or ""
    if err in ("zol_product_mismatch", "zol_search_no_hit"):
        return True
    # 仅有 ZOL 价、无京东 live 复核时也尝试官网 MSRP
    if channel.get("price_source") == "zol_jd" and channel.get("jd_live_price_cny") is None:
        return True
    return False


def _merge_official_into_channel(channel: dict, official_page) -> dict:
    if channel.get("price_cny") is not None and channel.get("price_source") not in ("unresolved", "zol_jd"):
        if official_page and official_page.msrp_cny is not None:
            channel = dict(channel)
            channel["msrp_cny"] = channel.get("msrp_cny") or official_page.msrp_cny
            channel["official_msrp_cny"] = official_page.msrp_cny
        return channel
    msrp = official_page.msrp_cny if official_page else None
    if msrp is None:
        return channel
    channel = dict(channel)
    channel["official_msrp_cny"] = msrp
    if channel.get("price_cny") is None:
        channel["price_cny"] = msrp
        channel["msrp_cny"] = channel.get("msrp_cny") or msrp
        channel["price_source"] = "official_msrp"
        channel["live_error"] = ""
        if official_page.official_url and not channel.get("channel_url"):
            channel["channel_url"] = official_page.official_url
            channel["shop_hint"] = channel.get("shop_hint") or "品牌官网"
    else:
        channel["msrp_cny"] = channel.get("msrp_cny") or msrp
    return channel


def enrich_official(
    canonical_id: str,
    brand: str,
    model: str,
    hints: dict,
    *,
    official_page=None,
    force_search: bool = False,
) -> dict:
    hint = (hints.get(canonical_id) or {}).get("official") or {}
    page = official_page

    if page is None:
        url = resolve_official_url(brand, model, hint.get("url"))
        if url and not force_search:
            page = fetch_official_page(url, brand=brand)
            if page.fetch_error or (not page.msrp_cny and not page.selling_points):
                page = search_official_site(brand, model)
        elif force_search or not url:
            page = search_official_site(brand, model)
        else:
            page = None

    url = (page.official_url if page else "") or hint.get("url", "")
    msrp = (page.msrp_cny if page and page.msrp_cny else None) or hint.get("msrp_cny")
    tagline = (page.tagline if page and page.tagline else "") or hint.get("tagline", "")
    highlights = (page.highlights if page and page.highlights else []) or hint.get("highlights", [])
    selling_points = page.selling_points if page and page.selling_points else []
    if not selling_points and highlights:
        selling_points = [{"text": h, "tag": "其他", "source_type": "official_hint"} for h in highlights]
    fetch_error = ""
    if page:
        fetch_error = page.fetch_error
    elif not url:
        fetch_error = "no_official_url"
    return {
        "canonical_id": canonical_id,
        "official_url": url or "",
        "vmall_url": hint.get("vmall_url", ""),
        "product_name": (page.product_name if page else "") or f"{brand} {model}".strip(),
        "msrp_cny": msrp,
        "tagline": tagline,
        "selling_points": selling_points,
        "highlights": highlights,
        "search_query": page.search_query if page else "",
        "fetch_error": fetch_error,
        "captured_at": datetime.now(timezone.utc).date().isoformat(),
        "source_layer": "official",
    }


def write_enrich(canonical_id: str, channel: dict, official: dict) -> None:
    write_channel_enrich(canonical_id, channel)
    write_official_enrich(canonical_id, official)


def enrich_one(
    canonical_id: str,
    hints: dict,
    *,
    skip_zol: bool = False,
    use_jd_browser: bool = True,
    cdp_url: str | None = None,
    browser_context=None,
    allow_jd_api_fallback: bool = False,
    no_union: bool = True,
    jd_live_prefetched: JdLivePrice | None = None,
    zol_only: bool = False,
) -> dict:
    product = _load_product(canonical_id)
    if product:
        brand = product.get("brand", "")
        model = product.get("model", "")
    else:
        h = hints.get(canonical_id) or {}
        brand = h.get("brand", "")
        model = h.get("model", "")

    channel = enrich_channel(
        canonical_id,
        brand,
        model,
        hints,
        skip_zol=skip_zol,
        use_jd_browser=use_jd_browser,
        cdp_url=cdp_url,
        browser_context=browser_context,
        allow_jd_api_fallback=allow_jd_api_fallback,
        no_union=no_union,
        jd_live_prefetched=jd_live_prefetched,
        zol_only=zol_only,
    )

    official_page = None
    if _needs_official_fallback(channel):
        official_page = search_official_site(brand, model)
        channel = _merge_official_into_channel(channel, official_page)

    official = enrich_official(
        canonical_id,
        brand,
        model,
        hints,
        official_page=official_page,
        force_search=_needs_official_fallback(channel) and official_page is None,
    )
    write_enrich(canonical_id, channel, official)
    return {"canonical_id": canonical_id, "channel": channel, "official": official}


def _enrich_batch(
    ids: list[str],
    hints: dict,
    *,
    skip_zol: bool,
    use_jd_browser: bool,
    cdp_url: str | None,
    allow_jd_api_fallback: bool,
    no_union: bool,
    zol_only: bool,
) -> list[dict]:
    """Batch enrich; reuse one browser session for all JD web scrapes."""
    common = dict(
        skip_zol=skip_zol,
        allow_jd_api_fallback=allow_jd_api_fallback,
        no_union=no_union,
        zol_only=zol_only,
    )
    if not use_jd_browser:
        return [enrich_one(i, hints, use_jd_browser=False, **common) for i in ids]

    from sources.channel.jd_scraper.session import human_delay, jd_browser, jd_browser_cdp, profile_ready

    if cdp_url:
        ctx_mgr = jd_browser_cdp(cdp_url)
    elif profile_ready():
        ctx_mgr = jd_browser(headless=False)
    else:
        print(
            "警告：京东浏览器未就绪（请先 --cdp-help 登录 Chrome），本批仅 ZOL/官网",
            file=sys.stderr,
        )
        return [enrich_one(i, hints, use_jd_browser=False, **common) for i in ids]

    results: list[dict] = []
    with ctx_mgr as context:
        for n, cid in enumerate(ids):
            if n:
                human_delay()
            results.append(
                enrich_one(
                    cid,
                    hints,
                    use_jd_browser=True,
                    browser_context=context,
                    cdp_url=None,
                    **common,
                )
            )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("canonical_id", nargs="?", help="产品 canonical_id")
    parser.add_argument("--canonical", dest="canonical_alt", help="同上")
    parser.add_argument("--headphones", action="store_true", help="批量处理耳机品类")
    parser.add_argument("--limit", type=int, default=None, help="批量上限（默认全部）")
    parser.add_argument("--skip-zol", action="store_true", help="跳过 ZOL 抓取")
    parser.add_argument(
        "--zol-only",
        action="store_true",
        help="仅抓取 ZOL（跳过 SMZDM、京东浏览器/API/联盟），保留官网MSRP兜底",
    )
    parser.add_argument(
        "--no-jd-browser",
        action="store_true",
        help="不打开浏览器抓京东价（仅 ZOL/官网）",
    )
    parser.add_argument(
        "--jd-cdp",
        nargs="?",
        const="http://127.0.0.1:9222",
        default="http://127.0.0.1:9222",
        help="CDP 挂真实 Chrome（默认 http://127.0.0.1:9222，需先登录京东）",
    )
    parser.add_argument(
        "--jd-profile",
        action="store_true",
        help="不用 CDP，改用 Playwright 持久化 Chrome Profile（易被封，不推荐）",
    )
    parser.add_argument("--jd-api-fallback", action="store_true", help="网页失败后尝试 p.3.cn API")
    parser.add_argument("--allow-union", action="store_true", help="允许使用京东联盟 API（默认关闭）")
    args = parser.parse_args()

    hints = _load_hints()
    cid = args.canonical_id or args.canonical_alt
    use_jd_browser = not args.no_jd_browser
    if args.zol_only:
        use_jd_browser = False
    cdp_url = None if args.jd_profile else args.jd_cdp

    if args.headphones:
        ids = _list_headphone_products(args.limit if args.limit else None)
        results = _enrich_batch(
            ids,
            hints,
            skip_zol=args.skip_zol,
            use_jd_browser=use_jd_browser,
            cdp_url=cdp_url,
            allow_jd_api_fallback=args.jd_api_fallback,
            no_union=not args.allow_union,
            zol_only=args.zol_only,
        )
        print(json.dumps({"count": len(results), "ids": ids}, ensure_ascii=False, indent=2))
        return

    if not cid:
        parser.error("请提供 canonical_id 或 --headphones")
    result = enrich_one(
        cid,
        hints,
        skip_zol=args.skip_zol,
        use_jd_browser=use_jd_browser,
        cdp_url=cdp_url,
        allow_jd_api_fallback=args.jd_api_fallback,
        no_union=not args.allow_union,
        zol_only=args.zol_only,
    )
    out = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
