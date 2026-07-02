"""按品类生成竞品矩阵 JSON，供前端矩阵页使用。"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest import load_all_records, merge_price_into_record  # noqa: E402
from core.products import canonical_product_id, guess_brand_from_text, normalize_brand, normalize_model  # noqa: E402
from sources.audio52.lexicon import SELLING_POINT_KEYWORDS  # noqa: E402

MATRIX_DIR = ROOT / "data" / "matrix"
PRODUCTS_DIR = ROOT / "data" / "products"

MATRIX_FIELDS = ("price_cny", "launch_date", "codecs", "bluetooth", "major_chips", "selling_point_tags")


def _record_identity(record: dict) -> tuple[str, str, str]:
    brand = normalize_brand(record.get("brand") or record.get("views", {}).get("market", {}).get("brand", ""))
    model = record.get("model") or record.get("views", {}).get("market", {}).get("model", "")
    title = record.get("title") or record.get("product_title", "")
    if not brand:
        brand = guess_brand_from_text(title) or guess_brand_from_text(model)
    model = normalize_model(model, brand)
    category = (
        record.get("category")
        or record.get("views", {}).get("market", {}).get("category")
        or "其他音频设备"
    )
    return brand, model, category


def _selling_point_texts(selling_points: list) -> list[str]:
    texts = []
    for sp in selling_points:
        if isinstance(sp, str):
            texts.append(sp)
        elif isinstance(sp, dict):
            texts.append(sp.get("text", "") or "")
            if sp.get("tag"):
                texts.append(str(sp["tag"]))
    return [t for t in texts if t]


def _extract_selling_point_tags(selling_points: list) -> list[str]:
    tags = []
    for sp in selling_points:
        if isinstance(sp, dict) and sp.get("tag"):
            tags.append(sp["tag"])
    text = " ".join(_selling_point_texts(selling_points))
    for kw in SELLING_POINT_KEYWORDS:
        if kw in text and kw not in tags:
            tags.append(kw)
    return tags[:12]


def _merge_views(target: dict, record: dict) -> None:
    views = record.get("views", {})
    market = views.get("market", {})
    software = views.get("software", {})
    cost = views.get("cost", {})

    if market.get("price_cny") is not None and target["price_cny"] is None:
        target["price_cny"] = market["price_cny"]
    if market.get("launch_date") and not target["launch_date"]:
        target["launch_date"] = market["launch_date"]
    if not target["launch_date"] and record.get("published_at"):
        target["launch_date"] = record["published_at"]

    for codec in software.get("codecs", []):
        if codec and codec not in target["codecs"]:
            target["codecs"].append(codec)

    bt = software.get("bluetooth_version")
    if bt and not target["bluetooth"]:
        target["bluetooth"] = bt

    for chip in cost.get("chip_modules", []):
        model_name = chip.get("model") or chip.get("part", "")
        if model_name and model_name not in target["major_chips"]:
            target["major_chips"].append(model_name)

    tags = _extract_selling_point_tags(market.get("selling_points", []))
    for t in tags:
        if t not in target["selling_point_tags"]:
            target["selling_point_tags"].append(t)

    dc = record.get("data_completeness")
    if dc is not None:
        target["data_completeness"] = max(target.get("data_completeness") or 0, float(dc))


def _completeness(row: dict) -> float:
    filled = 0
    for field in MATRIX_FIELDS:
        val = row.get(field)
        if val is None:
            continue
        if isinstance(val, list) and not val:
            continue
        if isinstance(val, str) and not val.strip():
            continue
        filled += 1
    return round(filled / len(MATRIX_FIELDS), 2)


def _category_filename(category: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', "_", category.strip())
    return f"{safe}.json"


def build_matrix() -> dict:
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)

    # canonical_id -> merged row data
    rows_by_id: dict[str, dict] = {}
    category_map: dict[str, str] = {}

    if PRODUCTS_DIR.exists():
        for path in PRODUCTS_DIR.glob("*.json"):
            if path.name == "index.json":
                continue
            try:
                product = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            cid = product["canonical_id"]
            category_map[cid] = product.get("category", "其他音频设备")
            rows_by_id[cid] = {
                "canonical_id": cid,
                "brand": product.get("brand", ""),
                "model": product.get("model", ""),
                "price_cny": None,
                "launch_date": None,
                "codecs": [],
                "bluetooth": None,
                "major_chips": [],
                "selling_point_tags": [],
            }

    for kind in ("report", "video"):
        for record in load_all_records(kind):
            if kind == "report":
                record = merge_price_into_record(record)
            brand, model, category = _record_identity(record)
            cid = canonical_product_id(brand, model)
            if cid not in rows_by_id:
                rows_by_id[cid] = {
                    "canonical_id": cid,
                    "brand": brand,
                    "model": model,
                    "price_cny": None,
                    "launch_date": None,
                    "codecs": [],
                    "bluetooth": None,
                    "major_chips": [],
                    "selling_point_tags": [],
                }
                category_map[cid] = category
            # 报告数据优先
            if kind == "report" or not rows_by_id[cid].get("_has_report"):
                _merge_views(rows_by_id[cid], record)
                if kind == "report":
                    rows_by_id[cid]["_has_report"] = True

    by_category: dict[str, list[dict]] = defaultdict(list)
    for cid, row in rows_by_id.items():
        row.pop("_has_report", None)
        row["data_completeness"] = _completeness(row)
        by_category[category_map.get(cid, "其他音频设备")].append(row)

    written = []
    for category, rows in sorted(by_category.items()):
        rows.sort(key=lambda r: (r.get("brand", ""), r.get("model", "")))
        payload = {
            "category": category,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "columns": list(MATRIX_FIELDS) + ["data_completeness"],
            "rows": rows,
        }
        out_path = MATRIX_DIR / _category_filename(category)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append({"category": category, "rows": len(rows), "path": str(out_path)})

    return {"matrices": len(written), "files": written}


def main() -> None:
    stats = build_matrix()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
