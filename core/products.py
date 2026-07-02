"""产品实体层：品牌/型号归一化与 canonical ID 生成。"""

from __future__ import annotations

import re
import unicodedata

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
