"""v2 爬虫入口：追加写入，支持 2026 backfill 与日更。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.ingest import append_record, load_index, save_index  # noqa: E402
from core.scope import is_headphone_record  # noqa: E402
from sources.audio52.source_v2 import Audio52SourceV2  # noqa: E402


def run_backfill_2026(source: Audio52SourceV2) -> dict:
    stats = {"mode": "backfill-2026", "new_reports": 0, "new_videos": 0, "skipped": 0, "errors": 0, "non_headphone": 0}
    for item in source.iter_feed_items(year=2026):
        try:
            record = source.parse_item(item)
            if record is None:
                continue
            rec_dict = record.to_dict()
            if not is_headphone_record(rec_dict):
                stats["non_headphone"] += 1
                continue
            kind = "report" if record.type == "report" else "video"
            if append_record(kind, rec_dict):
                if kind == "report":
                    stats["new_reports"] += 1
                else:
                    stats["new_videos"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            print(f"[crawl] 解析失败 {item.get('url')}: {e}")
            stats["errors"] += 1

    index = load_index()
    from datetime import datetime, timezone

    index["last_backfill_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_index(index)
    return stats


def run_daily(source: Audio52SourceV2) -> dict:
    stats = {"mode": "daily", "new_reports": 0, "new_videos": 0, "skipped": 0, "errors": 0, "non_headphone": 0}
    for item in source.iter_feed_items(max_pages=1):
        try:
            record = source.parse_item(item)
            if record is None:
                continue
            rec_dict = record.to_dict()
            if not is_headphone_record(rec_dict):
                stats["non_headphone"] += 1
                continue
            kind = "report" if record.type == "report" else "video"
            if append_record(kind, rec_dict):
                if kind == "report":
                    stats["new_reports"] += 1
                else:
                    stats["new_videos"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            print(f"[crawl] 解析失败 {item.get('url')}: {e}")
            stats["errors"] += 1

    index = load_index()
    from datetime import datetime, timezone

    index["last_daily_crawl_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_index(index)
    return stats


def rebuild_product_data() -> dict:
    """爬虫完成后重建产品主数据与竞品矩阵。"""
    from scripts.build_matrix import build_matrix  # noqa: E402
    from scripts.build_products import build_products  # noqa: E402

    products_stats = build_products()
    matrix_stats = build_matrix()
    return {"products": products_stats, "matrix": matrix_stats}


def main() -> None:
    parser = argparse.ArgumentParser(description="52audio v2 爬虫")
    parser.add_argument(
        "--mode",
        choices=["backfill-2026", "daily"],
        default="daily",
        help="backfill-2026=首次抓取2026年全部；daily=日更仅第1页",
    )
    parser.add_argument(
        "--skip-rebuild",
        action="store_true",
        help="跳过后续 build_products / build_matrix",
    )
    args = parser.parse_args()
    source = Audio52SourceV2()
    if args.mode == "backfill-2026":
        stats = run_backfill_2026(source)
    else:
        stats = run_daily(source)
    if not args.skip_rebuild:
        stats["rebuild"] = rebuild_product_data()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
