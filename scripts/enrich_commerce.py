#!/usr/bin/env python3
"""渠道（ZOL / 京东）+ 官方页 enrich：补售价与电商溯源。

用法:
  python scripts/enrich_commerce.py huawei--freebuds-pro-5
  python scripts/enrich_commerce.py --headphones --limit 20

价格优先级：ZOL 京东价 > ZOL 天猫价 > ZOL 参考报价 > 京东 API > commerce_hints > 官网 MSRP（ZOL 失败时）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.products import canonical_product_id, normalize_brand, normalize_model  # noqa: E402
import re

from sources.channel.jd_client import fetch_jd_price, pick_best_hit, search_jd  # noqa: E402
from sources.channel.zol_client import (  # noqa: E402
    _commerce_search_query,
    best_channel_price,
    fetch_zol_prices,
    score_product_title,
)
from sources.official.fetcher import (  # noqa: E402
    fetch_official_page,
    resolve_official_url,
    search_official_site,
)

from core.paths import (
    commerce_hints_path,
    products_dir,
    products_index_path,
    write_channel_enrich,
    write_official_enrich,
)
from core.scope import HEADPHONE_CATEGORIES  # noqa: E402

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


def enrich_channel(canonical_id: str, brand: str, model: str, hints: dict) -> dict:
    product_hint = hints.get(canonical_id) or {}
    zol_hint = product_hint.get("zol") or {}
    jd_hint = product_hint.get("jd") or {}
    query = _commerce_search_query(brand, model) or f"{brand} {model}".strip()

    zol_info = fetch_zol_prices(
        brand=brand,
        model=model,
        query=query,
        product_id=zol_hint.get("product_id"),
        product_url=zol_hint.get("product_url"),
    )
    # ZOL 详情页产品名与目标型号不一致时，丢弃 ZOL 结果（避免错链到牧士 MC2 等）
    if zol_info.product_name and score_product_title(zol_info.product_name, brand, model) < 1.5:
        zol_info.fetch_error = "zol_product_mismatch"
        zol_info.reference_price_cny = None
        zol_info.channel_quotes = []

    price_cny, price_platform, channel_url = best_channel_price(zol_info)

    sku_id = None
    msrp_cny = zol_info.reference_price_cny
    shop_hint = ""
    live_error = zol_info.fetch_error or ""
    price_source = ""

    if price_cny is not None:
        price_source = "zol_reference" if price_platform == "zol_reference" else f"zol_{price_platform}"
        for q in zol_info.channel_quotes:
            if q.platform == "jd" and q.sku_id:
                sku_id = q.sku_id
            if q.platform == "jd":
                shop_hint = "京东（ZOL 溯源）"
    else:
        live_error = live_error or "zol_no_price"

    # 直连京东 API 补价 / 补 SKU（ZOL 失败时）
    jd_hit = None
    if price_cny is None or not sku_id:
        jd_hits = search_jd(query)
        if jd_hits:
            jd_hit = pick_best_hit(jd_hits, brand, model)
        elif not live_error:
            live_error = "jd_search_unreachable"

    if jd_hit:
        if price_cny is None and jd_hit.price_cny is not None:
            price_cny = jd_hit.price_cny
            price_source = "jd"
        sku_id = sku_id or jd_hit.sku_id
        channel_url = channel_url or jd_hit.channel_url
        shop_hint = shop_hint or jd_hit.shop_hint

    if price_cny is None:
        sku_id = sku_id or jd_hint.get("sku_id")
        channel_url = channel_url or jd_hint.get("channel_url", "")
        price_cny = jd_hint.get("price_cny")
        msrp_cny = msrp_cny or jd_hint.get("msrp_cny")
        if price_cny is not None:
            price_source = "jd_hint"
        else:
            price_source = "unresolved"

    if sku_id and price_cny is None:
        live_price = fetch_jd_price(str(sku_id))
        if live_price:
            price_cny = live_price.get("price_cny")
            msrp_cny = msrp_cny or live_price.get("msrp_cny")
            price_source = "jd_api"

    return {
        "canonical_id": canonical_id,
        "price_cny": price_cny,
        "msrp_cny": msrp_cny,
        "reference_price_cny": zol_info.reference_price_cny,
        "price_source": price_source,
        "channel_url": channel_url,
        "sku_id": sku_id,
        "shop_hint": shop_hint or jd_hint.get("shop_hint", ""),
        "search_query": query,
        "price_note": jd_hint.get("price_note", ""),
        "live_error": live_error if price_cny is None else "",
        "zol": zol_info.to_dict(),
        "captured_at": datetime.now(timezone.utc).date().isoformat(),
        "source_layer": "channel",
    }


def _zol_needs_official_fallback(zol_info) -> bool:
    if isinstance(zol_info, dict):
        err = zol_info.get("fetch_error") or ""
        product_id = zol_info.get("product_id") or ""
    else:
        err = zol_info.fetch_error or ""
        product_id = zol_info.product_id or ""
    return err in ("zol_product_mismatch", "zol_search_no_hit") or (
        err == "zol_no_price" and not product_id
    )


def _merge_official_into_channel(channel: dict, official_page) -> dict:
    """渠道层无 ZOL/JD 价时，用官网 MSRP 兜底。"""
    if channel.get("price_cny") is not None:
        return channel
    msrp = official_page.msrp_cny if official_page else None
    if msrp is None:
        return channel
    channel = dict(channel)
    channel["price_cny"] = msrp
    channel["msrp_cny"] = channel.get("msrp_cny") or msrp
    channel["price_source"] = "official_msrp"
    channel["live_error"] = ""
    if official_page.official_url and not channel.get("channel_url"):
        channel["channel_url"] = official_page.official_url
        channel["shop_hint"] = channel.get("shop_hint") or "品牌官网"
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


def enrich_one(canonical_id: str, hints: dict) -> dict:
    product = _load_product(canonical_id)
    if product:
        brand = product.get("brand", "")
        model = product.get("model", "")
    else:
        h = hints.get(canonical_id) or {}
        brand = h.get("brand", "")
        model = h.get("model", "")

    channel = enrich_channel(canonical_id, brand, model, hints)

    zol_info = channel.get("zol") or {}
    needs_official_search = _zol_needs_official_fallback(zol_info) or channel.get("price_source") == "unresolved"

    official_page = None
    if needs_official_search:
        official_page = search_official_site(brand, model)
        channel = _merge_official_into_channel(channel, official_page)

    official = enrich_official(
        canonical_id,
        brand,
        model,
        hints,
        official_page=official_page,
        force_search=needs_official_search and official_page is None,
    )
    write_enrich(canonical_id, channel, official)
    return {"canonical_id": canonical_id, "channel": channel, "official": official}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("canonical_id", nargs="?", help="产品 canonical_id")
    parser.add_argument("--canonical", dest="canonical_alt", help="同上")
    parser.add_argument("--headphones", action="store_true", help="批量处理耳机品类")
    parser.add_argument("--limit", type=int, default=None, help="批量上限（默认全部）")
    args = parser.parse_args()

    hints = _load_hints()
    cid = args.canonical_id or args.canonical_alt

    if args.headphones:
        ids = _list_headphone_products(args.limit if args.limit else None)
        results = [enrich_one(i, hints) for i in ids]
        print(json.dumps({"count": len(results), "ids": ids}, ensure_ascii=False, indent=2))
        return

    if not cid:
        parser.error("请提供 canonical_id 或 --headphones")
    result = enrich_one(cid, hints)
    out = json.dumps(result, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")


if __name__ == "__main__":
    main()
