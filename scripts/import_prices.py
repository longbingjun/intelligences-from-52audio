"""P4 人工售价 CSV 导入 → data/enrich/prices/{id}.json

将运营补录的售价批量写入 enrich 层，与爬虫主数据解耦；`scripts/build_site.py` 构建时
通过 `core.ingest.merge_price_into_record` 合并进 `views.market`。

CSV 格式（UTF-8，首行表头）：
  id,price_cny,price_source,price_url,price_note

字段说明：
  - id          报告/视频 ID（必填），对应 data/reports|videos/{id}.json
  - price_cny   人民币售价，数字或留空
  - price_source 来源标识，默认 manual_csv（如 jd / tmall / official）
  - price_url   标价页 URL
  - price_note  备注（活动价、首发价等）

示例见 data/enrich/prices/README.md 与 example.csv。

用法：
  python scripts/import_prices.py data/enrich/prices/example.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "data" / "enrich" / "prices"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", help="售价 CSV 文件路径")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(args.csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            item_id = row.get("id", "").strip()
            if not item_id:
                continue
            payload = {
                "price_cny": float(row["price_cny"]) if row.get("price_cny") else None,
                "price_source": row.get("price_source", "manual_csv"),
                "price_url": row.get("price_url", ""),
                "price_note": row.get("price_note", ""),
                "price_captured_at": datetime.now(timezone.utc).date().isoformat(),
            }
            (OUT_DIR / f"{item_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            n += 1
    print(f"Imported {n} price records")


if __name__ == "__main__":
    main()
