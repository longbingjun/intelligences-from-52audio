"""数据目录单点配置（ETL Phase 1：兼容旧路径 + 双写新布局）。

目标布局见 docs/ETL_ARCHITECTURE.md
  raw/      ← reports, videos
  staging/  ← channel, official, unboxing enrich
  curated/  ← products, matrix, compare
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WEB_DATA = ROOT / "web" / "public" / "data"

# --- 目标布局 ---
RAW = DATA / "raw"
STAGING = DATA / "staging"
CURATED = DATA / "curated"

# --- 遗留布局（迁移期仍可读）---
LEGACY_REPORTS = DATA / "reports"
LEGACY_VIDEOS = DATA / "videos"
LEGACY_PRODUCTS = DATA / "products"
LEGACY_ENRICH = DATA / "enrich"
LEGACY_COMPARE = DATA / "compare"
LEGACY_MATRIX = DATA / "matrix"
LEGACY_CONFIG = DATA / "config"

MANIFEST_PATH = DATA / "manifest.json"


def reports_dir() -> Path:
    if LEGACY_REPORTS.exists() and any(LEGACY_REPORTS.glob("*.json")):
        return LEGACY_REPORTS
    return RAW / "reports"


def videos_dir() -> Path:
    if LEGACY_VIDEOS.exists() and any(LEGACY_VIDEOS.glob("*.json")):
        return LEGACY_VIDEOS
    return RAW / "videos"


def channel_enrich_dir(*, for_write: bool = False) -> Path:
    primary = STAGING / "channel"
    if for_write:
        primary.mkdir(parents=True, exist_ok=True)
        (LEGACY_ENRICH / "channel").mkdir(parents=True, exist_ok=True)
        return primary
    if primary.exists() and any(primary.glob("*.json")):
        return primary
    return LEGACY_ENRICH / "channel"


def official_enrich_dir(*, for_write: bool = False) -> Path:
    primary = STAGING / "official"
    if for_write:
        primary.mkdir(parents=True, exist_ok=True)
        (LEGACY_ENRICH / "official").mkdir(parents=True, exist_ok=True)
        return primary
    if primary.exists() and any(primary.glob("*.json")):
        return primary
    return LEGACY_ENRICH / "official"


def unboxing_enrich_dir(*, for_write: bool = False) -> Path:
    primary = STAGING / "unboxing"
    legacy = LEGACY_ENRICH / "unboxing"
    if for_write:
        primary.mkdir(parents=True, exist_ok=True)
        legacy.mkdir(parents=True, exist_ok=True)
        return primary
    if primary.exists() and any(primary.glob("*.json")):
        return primary
    return legacy


def commerce_hints_path() -> Path:
    staged = STAGING / "config" / "commerce_hints.json"
    legacy = LEGACY_CONFIG / "commerce_hints.json"
    if staged.exists():
        return staged
    return legacy


def products_dir(*, for_write: bool = False) -> Path:
    primary = CURATED / "products"
    if for_write:
        primary.mkdir(parents=True, exist_ok=True)
        LEGACY_PRODUCTS.mkdir(parents=True, exist_ok=True)
        return primary
    if primary.exists() and (primary / "index.json").exists():
        return primary
    return LEGACY_PRODUCTS


def products_index_path(*, for_write: bool = False) -> Path:
    return products_dir(for_write=for_write) / "index.json"


def compare_dir() -> Path:
    staged = CURATED / "compare"
    if staged.exists() and any(staged.glob("*.json")):
        return staged
    return LEGACY_COMPARE


def matrix_dir() -> Path:
    staged = CURATED / "matrix"
    if staged.exists() and any(staged.glob("*.json")):
        return staged
    return LEGACY_MATRIX


def write_json_dual(primary: Path, mirror: Path, payload: dict) -> None:
    """写入主路径并镜像到遗留路径（迁移期）。"""
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    primary.parent.mkdir(parents=True, exist_ok=True)
    primary.write_text(text, encoding="utf-8")
    if mirror != primary:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(text, encoding="utf-8")


def write_product_json(canonical_id: str, product: dict) -> None:
    """写出 curated + legacy 双份产品 JSON。"""
    primary = products_dir(for_write=True) / f"{canonical_id}.json"
    mirror = LEGACY_PRODUCTS / f"{canonical_id}.json"
    write_json_dual(primary, mirror, product)


def write_products_index(index: dict) -> None:
    primary = products_index_path(for_write=True)
    mirror = LEGACY_PRODUCTS / "index.json"
    write_json_dual(primary, mirror, index)


def write_channel_enrich(canonical_id: str, payload: dict) -> None:
    primary = channel_enrich_dir(for_write=True) / f"{canonical_id}.json"
    mirror = LEGACY_ENRICH / "channel" / f"{canonical_id}.json"
    write_json_dual(primary, mirror, payload)


def write_official_enrich(canonical_id: str, payload: dict) -> None:
    primary = official_enrich_dir(for_write=True) / f"{canonical_id}.json"
    mirror = LEGACY_ENRICH / "official" / f"{canonical_id}.json"
    write_json_dual(primary, mirror, payload)


def write_unboxing_enrich(report_id: str, payload: dict) -> None:
    primary = unboxing_enrich_dir(for_write=True) / f"{report_id}.json"
    mirror = LEGACY_ENRICH / "unboxing" / f"{report_id}.json"
    write_json_dual(primary, mirror, payload)


def last_step_stats(step: str) -> dict | None:
    """读取 data/manifest.json 中指定 step 最近一次记录的 stats（用于构建前后对比校验）。"""
    if not MANIFEST_PATH.exists():
        return None
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    for entry in reversed(manifest.get("steps", [])):
        if entry.get("step") == step:
            return entry.get("stats")
    return None


def update_manifest(*, step: str, stats: dict) -> None:
    """追加构建步骤到 data/manifest.json。"""
    manifest: dict = {}
    if MANIFEST_PATH.exists():
        try:
            manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except Exception:
            manifest = {}
    steps: list = manifest.setdefault("steps", [])
    steps.append(
        {
            "step": step,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stats": stats,
        }
    )
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
