"""扫描 reports + videos，生成产品主数据索引与单产品 JSON。"""

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
    normalize_brand,
    normalize_model,
)

PRODUCTS_DIR = ROOT / "data" / "products"
INDEX_PATH = PRODUCTS_DIR / "index.json"


def _record_identity(record: dict) -> tuple[str, str, str]:
    brand = normalize_brand(record.get("brand") or record.get("views", {}).get("market", {}).get("brand", ""))
    model = record.get("model") or record.get("views", {}).get("market", {}).get("model", "")
    title = record.get("title") or record.get("product_title", "")

    if not brand:
        brand = guess_brand_from_text(title) or guess_brand_from_text(model)
    model = normalize_model(model, brand)
    if not model and title:
        model = normalize_model(title.replace(brand, "", 1) if brand else title, brand)

    category = (
        record.get("category")
        or record.get("views", {}).get("market", {}).get("category")
        or record.get("views", {}).get("structure", {}).get("form_factor", "")
        or "其他音频设备"
    )
    return brand, model, category


def _pick_category(categories: list[str]) -> str:
    if not categories:
        return "其他音频设备"
    counts: dict[str, int] = defaultdict(int)
    for c in categories:
        counts[c] += 1
    return max(counts, key=lambda k: (counts[k], k))


def build_products() -> dict:
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)

    aggregates: dict[str, dict] = {}

    for kind in ("report", "video"):
        for record in load_all_records(kind):
            if kind == "report":
                record = merge_price_into_record(record)
            brand, model, category = _record_identity(record)
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
        }
        (PRODUCTS_DIR / f"{cid}.json").write_text(
            json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
            }
        )

    index_items.sort(key=lambda x: x.get("latest_published", ""), reverse=True)
    index = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "count": len(index_items),
        "products": index_items,
    }
    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"products": len(index_items), "index_path": str(INDEX_PATH)}


def main() -> None:
    stats = build_products()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
