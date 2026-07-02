"""P4 人工售价 CSV 导入 → data/enrich/prices/{id}.json

CSV 列：id,price_cny,price_source,price_url,price_note
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
