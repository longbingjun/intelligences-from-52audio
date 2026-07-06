"""产品实体层：品牌/型号归一化与 canonical ID 生成。"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from core.cost_extract import compute_cost_completeness, extract_cost_fields, pick_best_report
from sources.audio52.lexicon import BRAND_ALIASES

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CHANNEL_ENRICH_DIR = DATA_DIR / "enrich" / "channel"

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def normalize_brand(brand: str) -> str:
    """将品牌名归一化为 BRAND_ALIASES 中的展示名。"""
    text = (brand or "").strip()
    if not text:
        return ""

    lower = text.lower()
    best: tuple[int, int, str] | None = None  # (start, -len(alias), display)
    for display, aliases in BRAND_ALIASES:
        for alias in aliases:
            idx = lower.find(alias.lower())
            if idx == -1:
                continue
            candidate = (idx, -len(alias), display)
            if best is None or candidate < best:
                best = candidate
    return best[2] if best else text


def normalize_model(model: str, brand: str = "") -> str:
    """型号归一化：去空白、去掉重复品牌前缀。"""
    text = re.sub(r"\s+", " ", (model or "").strip())
    if not text:
        return ""

    norm_brand = normalize_brand(brand) if brand else ""
    if norm_brand:
        for alias in [norm_brand, *next((a for d, a in BRAND_ALIASES if d == norm_brand), [])]:
            if alias and text.lower().startswith(alias.lower()):
                text = text[len(alias) :].strip(" -·、，,")
                break
    return text or (model or "").strip()


def _slug_part(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    asciiish = normalized.encode("ascii", "ignore").decode("ascii").lower()
    if not asciiish:
        asciiish = re.sub(r"\s+", "-", text.strip().lower())
    slug = _SLUG_RE.sub("-", asciiish).strip("-")
    return slug or "unknown"


def canonical_product_id(brand: str, model: str) -> str:
    """生成稳定的 canonical 产品 ID，格式 `{brand_slug}--{model_slug}`。"""
    norm_brand = normalize_brand(brand)
    norm_model = normalize_model(model, norm_brand)
    brand_slug = _slug_part(norm_brand or "unknown")
    model_slug = _slug_part(norm_model or "unknown")
    return f"{brand_slug}--{model_slug}"


def guess_brand_from_text(text: str) -> str:
    """从标题/型号文本中猜测品牌（用于 video 缺 brand 字段时）。"""
    lower = (text or "").lower()
    best: tuple[int, int, str] | None = None
    for display, aliases in BRAND_ALIASES:
        for alias in aliases:
            idx = lower.find(alias.lower())
            if idx == -1:
                continue
            candidate = (idx, -len(alias), display)
            if best is None or candidate < best:
                best = candidate
    return best[2] if best else ""


def load_channel_enrich(canonical_id: str) -> dict | None:
    """读取渠道层 enrich（按 canonical_id）。"""
    path = CHANNEL_ENRICH_DIR / f"{canonical_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def merge_cost_snapshot(
    *,
    canonical_id: str,
    report_ids: list[str],
    video_ids: list[str],
    reports_by_id: dict[str, dict],
    market_price: float | None = None,
) -> dict:
    """从产品关联报告中融合成本快照与 BOM。"""
    reports = [reports_by_id[rid] for rid in report_ids if rid in reports_by_id]
    best = pick_best_report(reports)
    views = (best or {}).get("views") or {}
    cost = views.get("cost") or {}
    bom_table = list(cost.get("bom_table") or [])
    summary_image_urls = list(cost.get("summary_image_urls") or [])
    summary_text = cost.get("summary_text") or ""

    row_fallback: dict = {}
    if best:
        chips = cost.get("chip_modules") or []
        row_fallback["major_chips"] = [c.get("model") for c in chips if c.get("model")]
        sw = views.get("software") or {}
        row_fallback["bluetooth"] = sw.get("bluetooth_version")

    fields = extract_cost_fields(views, row_fallback=row_fallback) if best else {}

    channel = load_channel_enrich(canonical_id)
    price_cny = None
    price_layer = None
    if channel and channel.get("price_cny") is not None:
        price_cny = channel.get("price_cny")
        price_layer = "channel"
    elif market_price is not None:
        price_cny = market_price
        price_layer = "technical"

    layer_refs: dict[str, list[str]] = {
        "technical": [f"report:{r['id']}" for r in reports] + [f"video:{vid}" for vid in video_ids],
        "channel": [f"channel:{canonical_id}"] if channel else [],
        "official": [],
        "review": [],
    }

    cost_snapshot = {
        "main_chip": (fields.get("main_chip") or {}).get("value"),
        "pmic_case": (fields.get("pmic") or {}).get("value"),
        "battery_ear": (fields.get("battery_ear") or {}).get("value"),
        "battery_case": (fields.get("battery_case") or {}).get("value"),
        "speaker": (fields.get("speaker") or {}).get("value"),
        "materials": (fields.get("materials") or {}).get("value"),
        "weight_g": (fields.get("weight_g") or {}).get("value"),
        "ip_rating": (fields.get("ip_rating") or {}).get("value"),
        "bluetooth": (fields.get("bluetooth") or {}).get("value"),
        "bom_row_count": len(bom_table),
        "price_cny": price_cny,
        "price_layer": price_layer,
        "channel_url": (channel or {}).get("channel_url"),
        "sales_hint": (channel or {}).get("sales_hint"),
        "data_completeness": compute_cost_completeness(fields) if fields else 0.0,
        "best_report_id": (best or {}).get("id"),
    }

    return {
        "cost_snapshot": cost_snapshot,
        "cost_fields": fields,
        "bom_table": bom_table,
        "summary_image_urls": summary_image_urls,
        "summary_text": summary_text,
        "layer_refs": layer_refs,
        "channel_enrich": channel,
    }
