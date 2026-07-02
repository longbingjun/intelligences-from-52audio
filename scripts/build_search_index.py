"""构建站点搜索索引与竞品矩阵数据（build_site 前调用）。"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest import load_all_records, merge_price_into_record  # noqa: E402

DATA_DIR = ROOT / "data"
MATRIX_DIR = DATA_DIR / "matrix"
SEARCH_INDEX_PATH = DATA_DIR / "search-index.json"


def _tags_from_record(record: dict) -> list[str]:
    tags: list[str] = []
    for key in ("category", "brand", "model"):
        val = (record.get(key) or "").strip()
        if val and val not in tags:
            tags.append(val)
    v = record.get("views") or {}
    for part in v.get("cost", {}).get("major_parts", [])[:5]:
        p = (part or "").strip()
        if p and p not in tags:
            tags.append(p)
    for chip in v.get("cost", {}).get("chip_modules", [])[:3]:
        model = (chip.get("model") or "").strip()
        if model and model not in tags:
            tags.append(model)
    return tags[:12]


def _search_entry(record: dict, kind: str) -> dict:
    title = record.get("title") or record.get("product_title") or ""
    return {
        "id": record["id"],
        "type": kind,
        "brand": record.get("brand") or "",
        "model": record.get("model") or "",
        "category": record.get("category") or "",
        "title": title,
        "published_at": record.get("published_at") or "",
        "tags": _tags_from_record(record),
    }


def build_search_index() -> list[dict]:
    entries: list[dict] = []
    for r in load_all_records("report"):
        entries.append(_search_entry(merge_price_into_record(r), "report"))
    for v in load_all_records("video"):
        entries.append(_search_entry(v, "video"))
    entries.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    SEARCH_INDEX_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return entries


def _matrix_row_from_report(r: dict) -> dict:
    v = r.get("views") or {}
    m = v.get("market", {})
    chips = v.get("cost", {}).get("chip_modules", [])
    chip_txt = "、".join((c.get("model") or c.get("part") or "") for c in chips[:3]).strip("、")
    price = m.get("price_cny")
    return {
        "id": r["id"],
        "品牌": r.get("brand") or "",
        "型号": r.get("model") or "",
        "发布时间": r.get("published_at") or "",
        "售价": f"¥{price}" if price is not None else "",
        "芯片": chip_txt,
        "品类": r.get("category") or "",
    }


def build_matrix_files(reports: list[dict]) -> None:
    """按品类生成 data/matrix/{slug}.json，已有文件不覆盖。"""
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)
    by_cat: dict[str, list[dict]] = {}
    for r in reports:
        cat = r.get("category") or "其他"
        by_cat.setdefault(cat, []).append(_matrix_row_from_report(r))

    for cat, rows in by_cat.items():
        safe = cat.replace("/", "-").replace("\\", "-")
        path = MATRIX_DIR / f"{safe}.json"
        if path.exists():
            continue
        payload = {
            "category": cat,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "columns": ["品牌", "型号", "发布时间", "售价", "芯片"],
            "rows": sorted(rows, key=lambda x: x.get("发布时间", ""), reverse=True),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    reports = [merge_price_into_record(r) for r in load_all_records("report")]
    entries = build_search_index()
    build_matrix_files(reports)
    print(f"[build_search_index] {len(entries)} 条索引，矩阵品类 {len(list(MATRIX_DIR.glob('*.json')))} 个")


if __name__ == "__main__":
    main()
