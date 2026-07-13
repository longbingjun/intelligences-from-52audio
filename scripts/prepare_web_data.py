"""将 data/ 下的 JSON 同步到 web/public/data，供 Astro 构建使用。"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

from core.ingest import load_all_records  # noqa: E402
from core.paths import compare_dir, products_dir, products_index_path, update_manifest, WEB_DATA
from core.scope import is_headphone_record  # noqa: E402
DATA = ROOT / "data"
SITE = ROOT / "site"

# V3/V4 多角色静态页目录（V5 Astro 不再生成，构建前清理避免 Pages 残留旧入口）
LEGACY_SITE_PATHS = (
    "reports",
    "videos",
    "compare",
    "matrix",
    "products",
    "_astro",  # Astro 旧默认资源目录
    "assets",  # 构建前清空，npm run build 会重新生成
    "about.html",
)


def _slug(category: str) -> str:
    return re.sub(r'[<>:"/\\|?*\s]+', "-", category.strip()).strip("-") or "other"


def clean_legacy_site() -> list[str]:
    """移除旧版多角色静态页，避免与 V5 成本工作台并存。"""
    removed: list[str] = []
    if not SITE.exists():
        return removed
    for rel in LEGACY_SITE_PATHS:
        target = SITE / rel
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        removed.append(rel)
    return removed


def _teardown_list_item(record: dict, *, kind: str) -> dict:
    title = record.get("title") or record.get("product_title") or ""
    publisher = record.get("publisher") or record.get("author") or record.get("source_site") or ""
    brand = record.get("brand") or (record.get("views") or {}).get("market", {}).get("brand", "")
    return {
        "id": record.get("id", ""),
        "kind": kind,
        "title": title,
        "publisher": publisher,
        "published_at": record.get("published_at", ""),
        "url": record.get("url", ""),
        "category": record.get("category", ""),
        "brand": brand,
    }


def _build_teardown_manifest() -> dict:
    reports = [
        _teardown_list_item(r, kind="report")
        for r in load_all_records("report")
        if is_headphone_record(r)
    ]
    videos = [
        _teardown_list_item(v, kind="video")
        for v in load_all_records("video")
        if is_headphone_record(v)
    ]
    reports.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    videos.sort(key=lambda x: x.get("published_at", ""), reverse=True)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "report_count": len(reports),
        "video_count": len(videos),
        "reports": reports,
        "videos": videos,
    }


def prepare() -> dict:
    legacy_removed = clean_legacy_site()
    if WEB_DATA.exists():
        shutil.rmtree(WEB_DATA)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    # 确保 GitHub Pages（Jekyll）不忽略 _astro 等目录
    (SITE / ".nojekyll").touch(exist_ok=True)

    # compare
    compare_src = compare_dir()
    compare_dst = WEB_DATA / "compare"
    compare_dst.mkdir(parents=True, exist_ok=True)
    categories = []
    if compare_src.exists():
        for path in sorted(compare_src.glob("*.json")):
            shutil.copy2(path, compare_dst / path.name)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                name = payload.get("category", path.stem)
            except Exception:
                name = path.stem
            products = payload.get("products", []) if isinstance(payload, dict) else []
            categories.append(
                {
                    "name": name,
                    "slug": _slug(name),
                    "file": path.name,
                    "product_count": len(products),
                }
            )

    # products index + files
    products_dst = WEB_DATA / "products"
    products_dst.mkdir(parents=True, exist_ok=True)
    products_src = products_dir()
    idx_src = products_index_path()
    if idx_src.exists():
        shutil.copy2(idx_src, products_dst / "index.json")
    n_products = 0
    if products_src.exists():
        for path in products_src.glob("*.json"):
            if path.name == "index.json":
                continue
            shutil.copy2(path, products_dst / path.name)
            n_products += 1

    # profiles + field annotations
    for name in ("compare_profiles.json", "field_annotations.json"):
        src = DATA / name
        if src.exists():
            shutil.copy2(src, WEB_DATA / name)

    manifest = {
        "generated_at": json.loads((idx_src.read_text(encoding="utf-8"))).get("generated_at", "")
        if idx_src.exists()
        else "",
        "categories": categories,
        "product_count": n_products,
    }
    (WEB_DATA / "categories.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    teardown = _build_teardown_manifest()
    (WEB_DATA / "teardown_details.json").write_text(
        json.dumps(teardown, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    update_manifest(
        step="prepare_web_data",
        stats={
            "categories": len(categories),
            "products": n_products,
            "teardown_reports": teardown["report_count"],
            "teardown_videos": teardown["video_count"],
        },
    )
    return {
        "categories": len(categories),
        "products": n_products,
        "teardown_reports": teardown["report_count"],
        "teardown_videos": teardown["video_count"],
        "legacy_site_removed": legacy_removed,
        "out": str(WEB_DATA),
    }


def main() -> None:
    stats = prepare()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
