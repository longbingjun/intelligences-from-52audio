"""将 data/ 下的 JSON 同步到 web/public/data，供 Astro 构建使用。"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEB_DATA = ROOT / "web" / "public" / "data"
SITE = ROOT / "site"

# V3/V4 多角色静态页目录（V5 Astro 不再生成，构建前清理避免 Pages 残留旧入口）
LEGACY_SITE_PATHS = (
    "reports",
    "videos",
    "compare",
    "matrix",
    "products",
    "assets",
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


def prepare() -> dict:
    legacy_removed = clean_legacy_site()
    if WEB_DATA.exists():
        shutil.rmtree(WEB_DATA)
    WEB_DATA.mkdir(parents=True, exist_ok=True)

    # compare
    compare_src = DATA / "compare"
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
    idx_src = DATA / "products" / "index.json"
    if idx_src.exists():
        shutil.copy2(idx_src, products_dst / "index.json")
    products_src = DATA / "products"
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
    return {
        "categories": len(categories),
        "products": n_products,
        "legacy_site_removed": legacy_removed,
        "out": str(WEB_DATA),
    }


def main() -> None:
    stats = prepare()
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
