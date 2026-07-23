"""产品实体层：品牌/型号归一化与 canonical ID 生成。"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from core.cost_extract import compute_cost_completeness, extract_cost_fields, pick_best_report
from core.paths import channel_enrich_dir, official_enrich_dir, unboxing_enrich_dir
from sources.audio52.lexicon import BRAND_ALIASES

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


def load_official_enrich(canonical_id: str) -> dict | None:
    path = official_enrich_dir() / f"{canonical_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_channel_enrich(canonical_id: str) -> dict | None:
    """读取渠道层 enrich（按 canonical_id）。"""
    path = channel_enrich_dir() / f"{canonical_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_unboxing_enrich(report_id: str) -> dict | None:
    path = unboxing_enrich_dir() / f"{report_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _slim_unboxing_module(mod: dict | None, *, max_images: int = 8) -> dict:
    mod = mod or {}
    images = mod.get("appearance_images") or mod.get("images") or []
    if isinstance(images, list) and len(images) > max_images:
        images = images[:max_images]
    return {
        "description": mod.get("description") or "",
        "accessories": mod.get("accessories") or [],
        "appearance_images": images,
        "image_count": len(mod.get("images") or []),
        "teardown_image_count": mod.get("teardown_image_count") or 0,
    }


def merge_unboxing_snapshot(report_ids: list[str]) -> dict | None:
    """从最佳报告的 unboxing enrich 生成产品页摘要。"""
    best: tuple[int, dict] | None = None
    for rid in report_ids:
        raw = load_unboxing_enrich(rid)
        if not raw:
            continue
        pkg = raw.get("packaging") or {}
        score = len(pkg.get("images") or []) + len(pkg.get("accessories") or [])
        if best is None or score > best[0]:
            best = (score, raw)
    if not best:
        return None
    raw = best[1]
    gaps = raw.get("gaps") or []
    modules = {
        "packaging": _slim_unboxing_module(raw.get("packaging")),
        "charging_case": _slim_unboxing_module(raw.get("charging_case")),
        "earbuds": _slim_unboxing_module(raw.get("earbuds")),
    }
    filled = sum(1 for m in modules.values() if m.get("appearance_images"))
    return {
        "report_id": raw.get("report_id"),
        "packaging": modules["packaging"],
        "charging_case": modules["charging_case"],
        "earbuds": modules["earbuds"],
        "gaps": gaps,
        "completeness": round(filled / 3, 2),
    }


def _views_cost_score(views: dict) -> int:
    cost = views.get("cost") or {}
    return len(cost.get("bom_table") or []) + 2 * len(cost.get("chip_modules") or [])


def _views_market_score(views: dict) -> int:
    market = views.get("market") or {}
    return len(market.get("selling_points") or []) + len(market.get("scenarios") or [])


def merge_market_snapshot(
    *,
    report_ids: list[str],
    video_ids: list[str],
    reports_by_id: dict[str, dict],
    videos_by_id: dict[str, dict] | None = None,
) -> dict | None:
    """从产品关联报告/视频中选出市场信息（卖点/场景/定位）最丰富的一条，生成产品页市场快照。

    与 merge_cost_snapshot 类似地"择优"而非机械拼接：卖点句多来自同一篇文章的连续表述，
    跨源合并容易产生重复或语义割裂，因此选单一最佳信源更稳妥。
    """
    candidates: list[tuple[int, dict, str, str]] = []  # (score, views, source_type, source_id)
    for rid in report_ids:
        r = reports_by_id.get(rid)
        if not r:
            continue
        views = r.get("views") or {}
        score = _views_market_score(views)
        if score:
            candidates.append((score, views, "report", rid))

    if videos_by_id:
        for vid in video_ids:
            v = videos_by_id.get(vid)
            if not v:
                continue
            views = v.get("views") or {}
            score = _views_market_score(views)
            if score:
                candidates.append((score, views, "video", vid))

    if not candidates:
        return None

    candidates.sort(key=lambda c: c[0], reverse=True)
    _, views, source_type, source_id = candidates[0]
    market = views.get("market") or {}
    selling_points = list(market.get("selling_points") or [])[:8]
    scenarios = list(market.get("scenarios") or [])
    positioning_summary = market.get("positioning_summary") or ""

    if not (selling_points or scenarios or positioning_summary):
        return None

    return {
        "selling_points": selling_points,
        "scenarios": scenarios,
        "positioning_summary": positioning_summary,
        "launch_date": market.get("launch_date"),
        "best_report_id": source_id if source_type == "report" else None,
        "best_video_id": source_id if source_type == "video" else None,
    }


def merge_cost_snapshot(
    *,
    canonical_id: str,
    report_ids: list[str],
    video_ids: list[str],
    reports_by_id: dict[str, dict],
    videos_by_id: dict[str, dict] | None = None,
    market_price: float | None = None,
) -> dict:
    """从产品关联报告/视频中融合成本快照与 BOM。"""
    reports = [reports_by_id[rid] for rid in report_ids if rid in reports_by_id]
    best = pick_best_report(reports)
    views = (best or {}).get("views") or {}
    best_video_id = ""

    if videos_by_id:
        videos = [videos_by_id[vid] for vid in video_ids if vid in videos_by_id]
        if videos:
            best_video = max(videos, key=lambda v: _views_cost_score(v.get("views") or {}))
            vviews = best_video.get("views") or {}
            if _views_cost_score(vviews) > _views_cost_score(views):
                views = vviews
                best_video_id = best_video.get("id", "")
                best = None  # 成本主信源切到视频

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
    official = load_official_enrich(canonical_id)
    price_cny = None
    price_layer = None
    if channel and channel.get("price_cny") is not None:
        price_cny = channel.get("price_cny")
        price_layer = "channel"
    elif official and official.get("msrp_cny") is not None:
        price_cny = official.get("msrp_cny")
        price_layer = "official"
    elif market_price is not None:
        price_cny = market_price
        price_layer = "technical"

    layer_refs: dict[str, list[str]] = {
        "technical": [f"report:{r['id']}" for r in reports] + [f"video:{vid}" for vid in video_ids],
        "channel": [f"channel:{canonical_id}"] if channel else [],
        "official": [f"official:{canonical_id}"] if official else [],
        "unboxing": [f"unboxing:{rid}" for rid in report_ids if load_unboxing_enrich(rid)],
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
        "weight_case_g": (fields.get("weight_case_g") or {}).get("value"),
        "weight_earbud_g": (fields.get("weight_earbud_g") or {}).get("value"),
        "ip_rating": (fields.get("ip_rating") or {}).get("value"),
        "bluetooth": (fields.get("bluetooth") or {}).get("value"),
        "bom_row_count": len(bom_table),
        "price_cny": price_cny,
        "price_layer": price_layer,
        "channel_url": (channel or {}).get("channel_url"),
        "sales_hint": (channel or {}).get("sales_hint"),
        "data_completeness": compute_cost_completeness(fields) if fields else 0.0,
        "best_report_id": (best or {}).get("id") if best else None,
        "best_video_id": best_video_id or None,
    }

    return {
        "cost_snapshot": cost_snapshot,
        "cost_fields": fields,
        "bom_table": bom_table,
        "summary_image_urls": summary_image_urls,
        "summary_text": summary_text,
        "layer_refs": layer_refs,
    }
