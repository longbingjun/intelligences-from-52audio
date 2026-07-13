"""扫描 reports + videos，生成产品主数据索引与单产品 JSON（含成本快照）。"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.compare import suggest_internal_match  # noqa: E402
from core.ingest import load_all_records, merge_price_into_record  # noqa: E402
from core.products import (  # noqa: E402
    canonical_product_id,
    guess_brand_from_text,
    merge_cost_snapshot,
    merge_market_snapshot,
    merge_unboxing_snapshot,
    normalize_brand,
    normalize_model,
)
from core.scope import HEADPHONE_CATEGORIES, is_headphone_record, normalize_headphone_category  # noqa: E402

from core.paths import (
    LEGACY_PRODUCTS,
    products_dir,
    products_index_path,
    update_manifest,
    write_product_json,
    write_products_index,
)


def _record_identity(record: dict) -> tuple[str, str, str]:
    brand = normalize_brand(record.get("brand") or record.get("views", {}).get("market", {}).get("brand", ""))
    model = record.get("model") or record.get("views", {}).get("market", {}).get("model", "")
    title = record.get("title") or record.get("product_title", "")

    if not brand:
        brand = guess_brand_from_text(title) or guess_brand_from_text(model)
    model = normalize_model(model, brand)
    if not model and title:
        model = normalize_model(title.replace(brand, "", 1) if brand else title, brand)

    text = title or f"{brand} {model}".strip()
    existing = (
        record.get("category")
        or record.get("views", {}).get("market", {}).get("category")
        or record.get("views", {}).get("structure", {}).get("form_factor", "")
        or ""
    )
    category = normalize_headphone_category(text, existing)
    return brand, model, category


def _pick_category(categories: list[str]) -> str:
    if not categories:
        return "真无线耳机TWS"
    hp = [c for c in categories if c in HEADPHONE_CATEGORIES]
    pool = hp or categories
    counts: dict[str, int] = defaultdict(int)
    for c in pool:
        counts[c] += 1
    return max(counts, key=lambda k: (counts[k], k))


def build_products() -> dict:
    products_dir(for_write=True)

    reports_by_id: dict[str, dict] = {}
    for r in load_all_records("report"):
        reports_by_id[r["id"]] = merge_price_into_record(r)

    videos_by_id: dict[str, dict] = {}
    for v in load_all_records("video"):
        videos_by_id[v["id"]] = v

    aggregates: dict[str, dict] = {}

    for kind in ("report", "video"):
        for record in load_all_records(kind):
            if not is_headphone_record(record):
                continue
            if kind == "report":
                record = reports_by_id.get(record["id"], record)
            brand, model, category = _record_identity(record)
            if category not in HEADPHONE_CATEGORIES:
                continue
            cid = canonical_product_id(brand, model)
            published = record.get("published_at", "")

            if cid not in aggregates:
                aggregates[cid] = {
                    "canonical_id": cid,
                    "brand": brand,
                    "model": model,
                    "categories": [],
                    "report_ids": [],
                    "video_ids": [],
                    "published_dates": [],
                    "market_prices": [],
                }

            agg = aggregates[cid]
            if brand and not agg["brand"]:
                agg["brand"] = brand
            if model and (not agg["model"] or agg["model"] == "unknown"):
                agg["model"] = model
            agg["categories"].append(category)
            agg["published_dates"].append(published)
            if kind == "report":
                agg["report_ids"].append(record["id"])
                mkt = (record.get("views") or {}).get("market") or {}
                if mkt.get("price_cny") is not None:
                    agg["market_prices"].append(mkt["price_cny"])
            else:
                agg["video_ids"].append(record["id"])

    index_items: list[dict] = []
    for cid, agg in sorted(aggregates.items()):
        report_ids = sorted(set(agg["report_ids"]))
        video_ids = sorted(set(agg["video_ids"]))
        dates = sorted(d for d in agg["published_dates"] if d)
        category = _pick_category(agg["categories"])
        brand = agg["brand"]
        model = agg["model"]
        market_price = agg["market_prices"][0] if agg["market_prices"] else None

        cost_data = merge_cost_snapshot(
            canonical_id=cid,
            report_ids=report_ids,
            video_ids=video_ids,
            reports_by_id=reports_by_id,
            videos_by_id=videos_by_id,
            market_price=market_price,
        )

        unboxing = merge_unboxing_snapshot(report_ids)
        market = merge_market_snapshot(
            report_ids=report_ids,
            video_ids=video_ids,
            reports_by_id=reports_by_id,
            videos_by_id=videos_by_id,
        )

        product = {
            "canonical_id": cid,
            "brand": brand,
            "model": model,
            "category": category,
            "report_ids": report_ids,
            "video_ids": video_ids,
            "related_report_ids": report_ids,
            "related_video_ids": video_ids,
            "first_seen": dates[0] if dates else "",
            "latest_published": dates[-1] if dates else "",
            "internal_match_suggestions": suggest_internal_match(brand, model, category),
            "cost_snapshot": cost_data["cost_snapshot"],
            "bom_table": cost_data["bom_table"],
            "summary_image_urls": cost_data["summary_image_urls"],
            "summary_text": cost_data["summary_text"],
            "layer_refs": cost_data["layer_refs"],
            "unboxing": unboxing,
            "market": market,
        }
        write_product_json(cid, product)
        index_items.append(
            {
                "canonical_id": cid,
                "brand": brand,
                "model": model,
                "category": category,
                "report_count": len(report_ids),
                "video_count": len(video_ids),
                "first_seen": product["first_seen"],
                "latest_published": product["latest_published"],
                "cost_completeness": cost_data["cost_snapshot"].get("data_completeness"),
                "bom_row_count": cost_data["cost_snapshot"].get("bom_row_count"),
            }
        )

    index_items.sort(key=lambda x: x.get("latest_published", ""), reverse=True)
    index = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(index_items),
        "products": index_items,
    }
    write_products_index(index)
    update_manifest(step="build_products", stats={"products": len(index_items)})

    # 移除不再生成的产品 JSON（非耳机等）
    keep_ids = set(aggregates.keys())
    for base in (products_dir(), LEGACY_PRODUCTS):
        if not base.exists():
            continue
        for path in base.glob("*.json"):
            if path.name == "index.json" or path.stem in keep_ids:
                continue
            path.unlink()

    idx_path = products_index_path()
    return {"products": len(index_items), "index_path": str(idx_path)}


def main() -> None:
    stats = build_products()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
