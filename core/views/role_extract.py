"""从正文纯文本/HTML 抽取五区块 views（A–E），含证据链与完整度评分。"""

from __future__ import annotations

import re

from core.extract.components import extract_components
from core.extract.bom_from_prose import extract_bom_from_prose
from core.extract.key_images import extract_key_image_urls
from core.extract.selling_points import extract_selling_points
from core.extract.summary_section import locate_summary_section
from core.extract.tech_specs import extract_tech_specs, guess_charging_ports
from core.extract.text_utils import plain_text as html_plain_text, split_sentences
from core.models_v2 import CostView, HardwareView, MarketView, RoleViews, SoftwareView, StructureView
from sources.audio52 import lexicon

_LAUNCH_RE = re.compile(
    r"(20\d{2}[-年/]\d{1,2}[-月/]\d{1,2}日?|20\d{2}年\d{1,2}月)",
)
_PRICE_RE = re.compile(
    r"(?:售价|定价|价格|零售价|官方价)[：:\s]*[¥￥]?\s*(\d{1,5}(?:\.\d{1,2})?)\s*元?",
)
_PRICE_YEN_RE = re.compile(r"[¥￥]\s*(\d{1,5}(?:\.\d{1,2})?)")
_BT_RE = re.compile(r"蓝牙\s*([0-9]\.[0-9]+)|Bluetooth\s*([0-9]\.[0-9]+)", re.I)
# IP 等级：IPX5 / IPX4 / IP54 / IP67 / IP68。负向断言 `(?!\d)` 排除 IP5xxx / IPxxxx 这类
# 芯片型号（如 INJOINIC 英集芯 IP5528、IP5516）被误判为 IP 等级。
_IP_RE = re.compile(r"IP\s*X?\d(?!\d)", re.I)
_WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|克)")
_BATT_RE = re.compile(r"(\d+)\s*mAh", re.I)
_SIDE_RE = re.compile(r"(左耳|右耳|左腔|右腔|充电盒|耳机|仓体)")

_PACKAGING_COMPONENTS = {"包装盒", "说明书", "耳塞套"}


def make_evidence(
    value: str | float | None,
    source_text: str,
    *,
    source_type: str = "text",
    confidence: float = 0.7,
) -> dict:
    return {
        "value": value,
        "confidence": round(confidence, 2),
        "source_type": source_type,
        "source_text": source_text[:500] if source_text else "",
    }


def _is_tech_sentence(sent: str) -> bool:
    hits = sum(1 for kw in lexicon.TECH_SENTENCE_KEYWORDS if kw.lower() in sent.lower() or kw in sent)
    if hits >= 2:
        return True
    if hits == 1 and any(re.search(p, sent, re.I) for p in lexicon.CHIP_PATTERNS):
        return True
    if re.search(r"蓝牙\s*[0-9]\.[0-9]", sent):
        return True
    if re.search(r"(LDAC|aptX|LHDC|AAC|SBC)", sent, re.I) and not any(
        kw in sent for kw in ("认证", "支持", "获得", "体验", "带来")
    ):
        return True
    return False


def _is_packaging_sentence(sent: str) -> bool:
    return any(kw in sent for kw in lexicon.STRUCTURE_EXCLUDE_KEYWORDS)


def _tag_selling_point(sent: str) -> str:
    for tag, keywords in lexicon.SELLING_POINT_TAGS:
        if any(kw in sent or kw.lower() in sent.lower() for kw in keywords):
            return tag
    return "其他"


def _confidence_from_sentiment(sentiment: float | None, base: float = 0.65) -> float:
    if sentiment is None:
        return base
    return min(0.95, base + (sentiment - 0.5) * 0.2)


def extract_price_from_text(plain: str) -> tuple[float | None, str, dict | None]:
    m = _PRICE_RE.search(plain)
    if m:
        val = float(m.group(1))
        snippet = m.group(0)
        return val, "正文标注售价", make_evidence(val, snippet, confidence=0.9)
    for m in _PRICE_YEN_RE.finditer(plain):
        val = float(m.group(1))
        if 29 <= val <= 9999:
            return val, "正文出现价格数字（待人工确认）", make_evidence(val, m.group(0), confidence=0.55)
    return None, "", None


def extract_launch_date(plain: str) -> tuple[str | None, dict | None]:
    for kw in ("上市", "开售", "发布", "将于", "正式上市"):
        idx = plain.find(kw)
        if idx == -1:
            continue
        snippet = plain[idx : idx + 40]
        m = _LAUNCH_RE.search(snippet)
        if m:
            val = m.group(1).replace("年", "-").replace("月", "-").replace("日", "").strip("-")
            return val, make_evidence(val, snippet, confidence=0.75)
    return None, None


def _match_scenarios(plain: str) -> list[str]:
    found = []
    for kw in lexicon.SCENARIO_KEYWORDS:
        if kw in plain and kw not in found:
            found.append(kw)
    return found


def _match_materials(plain: str) -> list[str]:
    found = []
    for kw in lexicon.MATERIAL_KEYWORDS:
        if kw in plain and kw not in found:
            found.append(kw)
    return found


def _match_codecs(plain: str) -> list[dict]:
    found: list[dict] = []
    seen: set[str] = set()
    for kw in lexicon.CODEC_KEYWORDS:
        if re.search(kw, plain, re.I):
            key = kw.upper()
            if key in seen:
                continue
            seen.add(key)
            for sent in split_sentences(plain):
                if re.search(kw, sent, re.I):
                    found.append(
                        {
                            "value": kw,
                            "evidence": make_evidence(kw, sent, confidence=0.8),
                        }
                    )
                    break
            else:
                found.append({"value": kw, "evidence": make_evidence(kw, kw, confidence=0.6)})
    return found


def _extract_bluetooth_version(plain: str) -> tuple[str | None, dict | None]:
    m = _BT_RE.search(plain)
    if not m:
        return None, None
    val = m.group(1) or m.group(2)
    return val, make_evidence(val, m.group(0), confidence=0.85)


def _extract_ip_rating(plain: str) -> tuple[str | None, dict | None]:
    m = _IP_RE.search(plain)
    if not m:
        return None, None
    val = m.group(0).upper()
    return val, make_evidence(val, m.group(0), confidence=0.8)


def _extract_weight(plain: str) -> tuple[str | None, dict | None]:
    m = _WEIGHT_RE.search(plain)
    if not m:
        return None, None
    return m.group(0), make_evidence(m.group(0), m.group(0), confidence=0.75)


def _guess_earbud_type(category: str, plain: str) -> str:
    cat = category or ""
    if "开放式" in cat or "开放佩戴" in cat:
        return "开放"
    if "耳夹" in cat:
        return "耳夹"
    if "头戴" in cat:
        return "头戴"
    if "颈挂" in cat or "颈戴" in cat:
        return "颈挂"
    if "骨传导" in cat:
        return "其他"
    text = f"{cat} {plain[:800]}"
    for earbud_type, keywords in lexicon.EARBUD_TYPE_RULES:
        if any(kw in text for kw in keywords):
            return earbud_type
    if "TWS" in cat or "真无线" in cat:
        return "入耳"
    return "其他"


def _chip_modules_from_text(plain: str) -> list[dict]:
    modules: list[dict] = []
    seen: set[str] = set()
    for pat in lexicon.CHIP_PATTERNS:
        for m in re.finditer(pat, plain, re.I):
            model = m.group(0).strip()
            key = re.sub(r"\s+", "", model).upper()
            if key in seen:
                continue
            seen.add(key)
            brand = ""
            if "Qualcomm" in model or "高通" in model:
                brand = "Qualcomm"
            elif "Actions" in model:
                brand = "Actions"
            elif "络达" in model:
                brand = "Airoha"
            elif "恒玄" in model:
                brand = "BES"
            modules.append(
                {
                    "component": "芯片/模组",
                    "brand": brand,
                    "model": model,
                    "qty_hint": "",
                    "side": "",
                    "role": "主控/蓝牙",
                    "evidence": make_evidence(model, m.group(0), confidence=0.82),
                }
            )
    return modules[:20]


def _dedupe_chips(chips: list[dict]) -> list[dict]:
    """按芯片型号 canonical 去重，保留描述最完整的版本（品牌前缀最长的）。

    扩展后的 CHIP_PATTERNS 会有重叠匹配，例如「INJOINIC英集芯IP5528」「英集芯IP5528」
    「IP5528」三个 pattern 都命中同一颗芯片，canonical 都是 IP5528。这里按 canonical
    去重，保留 model 字符串最长（带品牌前缀）的那一条。
    """
    by_canon: dict[str, dict] = {}
    order: list[str] = []
    for c in chips:
        model = (c.get("model") or "").strip()
        if not model:
            continue
        # canonical：取末尾的「字母+数字+字母数字」token 作为型号核心
        m = re.search(r"[A-Z]{1,4}\d+[A-Z0-9]*$", model, re.I)
        canon = m.group(0).upper() if m else re.sub(r"\s+", "", model).upper()
        if not canon:
            continue
        prev = by_canon.get(canon)
        if prev is None:
            by_canon[canon] = c
            order.append(canon)
        else:
            # 保留 model 字符串更长（更带品牌前缀）的那条
            if len(model) > len((prev.get("model") or "").strip()):
                by_canon[canon] = c
    return [by_canon[k] for k in order]


def _guess_side(text: str) -> str:
    m = _SIDE_RE.search(text)
    return m.group(1) if m else ""


def _build_bom_table(major, minor, plain: str) -> list[dict]:
    rows: list[dict] = []
    for comp in major + minor:
        if comp.name in _PACKAGING_COMPONENTS:
            continue
        mention = comp.mentions[0].text if comp.mentions else comp.name
        rows.append(
            {
                "component": comp.name,
                "brand": "",
                "model": "",
                "qty_hint": "",
                "side": _guess_side(mention),
                "role": "major" if comp.importance == "major" else "minor",
                "evidence": make_evidence(comp.name, mention, confidence=0.72),
            }
        )
    for sent in split_sentences(plain):
        for pat in lexicon.CHIP_PATTERNS:
            m = re.search(pat, sent, re.I)
            if not m:
                continue
            model = m.group(0)
            rows.append(
                {
                    "component": "芯片/模组",
                    "brand": "",
                    "model": model,
                    "qty_hint": "1",
                    "side": _guess_side(sent),
                    "role": "主控/蓝牙",
                    "evidence": make_evidence(model, sent, confidence=0.78),
                }
            )
    return rows[:30]


def _normalize_bom_row(row: dict) -> dict:
    """从 summary BOM 行剥离顶层多余字段，统一为 bom_table 标准 schema。"""
    return {
        "component": row.get("component", ""),
        "brand": row.get("brand", ""),
        "model": row.get("model", ""),
        "qty_hint": row.get("qty_hint", ""),
        "side": row.get("side", ""),
        "role": row.get("role", ""),
        "evidence": row.get("evidence") or make_evidence(
            row.get("model", "") or row.get("component", ""),
            row.get("evidence_text", ""),
            confidence=row.get("confidence", 0.78),
            source_type="summary_prose",
        ),
    }


def _bom_dedup_key(row: dict) -> tuple:
    """BOM 行去重 key：芯片类按型号 canonical，非芯片按 (component, side)。"""
    comp = row.get("component", "")
    model = (row.get("model") or "").strip()
    side = row.get("side", "")
    if comp == "芯片/模组" and model:
        # 取末尾的 字母+数字+字母数字 token 作为 canonical
        m = re.search(r"[A-Z]{1,4}\d+[A-Z0-9]*$", model, re.I)
        canon = m.group(0).upper() if m else re.sub(r"\s+", "", model).upper()
        return (comp, canon, side)
    return (comp, re.sub(r"\s+", "", model).upper(), side)


def _merge_bom_with_summary(text_bom: list[dict], summary_bom: list[dict]) -> list[dict]:
    """合并正文 BOM 与总结段 BOM，summary 优先（前置 + 去重时保留 summary 版本）。

    返回合并后的 bom_table（按 summary 在前、正文在后顺序，去重）。
    """
    out: list[dict] = []
    seen: set[tuple] = set()
    # 1) summary 行优先入列
    for row in summary_bom:
        norm = _normalize_bom_row(row)
        key = _bom_dedup_key(norm)
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    # 2) 正文行：与 summary 重复的跳过
    for row in text_bom:
        key = _bom_dedup_key(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out[:50]


def _summary_images_to_dicts(image_urls: list[str], section_html: str) -> list[dict]:
    """把总结段图 URL 列表转成与 structure.key_image_urls 同构的 dict 列表。"""
    if not image_urls:
        return []
    # 从 section html 里抓 alt 文本（如果存在）
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(section_html or "", "lxml")
    alt_map: dict[str, str] = {}
    for img in soup.find_all("img"):
        url = (img.get("src") or "").strip()
        alt = img.get("alt") or ""
        if url and alt:
            alt_map[url] = alt
    return [
        {"url": url, "alt": alt_map.get(url, ""), "caption": "", "section_hint": "summary_bom", "score": 10}
        for url in image_urls
    ]


def _supply_hints(plain: str) -> list[dict]:
    hints = []
    for sent in split_sentences(plain):
        if any(kw in sent for kw in lexicon.SUPPLY_HINT_KEYWORDS):
            hints.append({"value": sent, "evidence": make_evidence(sent, sent, confidence=0.6)})
    return hints[:5]


def _evidence_list(sentences: list[str], confidence: float = 0.7) -> list[dict]:
    return [{"value": s, "evidence": make_evidence(s, s, confidence=confidence)} for s in sentences]


def _hardware_specs(plain: str, tech) -> list[dict]:
    specs: list[dict] = []
    for sent in tech.charging_method:
        specs.append(
            {
                "param": "充电方式",
                "value": sent,
                "unit": "",
                "brand": "",
                "model": "",
                "confidence": 0.75,
                "source_ref": sent[:120],
            }
        )
    for sent in tech.charging_port:
        specs.append(
            {
                "param": "充电接口",
                "value": sent,
                "unit": "",
                "brand": "",
                "model": "",
                "confidence": 0.75,
                "source_ref": sent[:120],
            }
        )
    for port in guess_charging_ports(plain):
        specs.append(
            {
                "param": "充电接口",
                "value": port,
                "unit": "",
                "brand": "",
                "model": port,
                "confidence": 0.8,
                "source_ref": port,
            }
        )
    for sent in tech.product_markings:
        specs.append(
            {
                "param": "标记/认证",
                "value": sent,
                "unit": "",
                "brand": "",
                "model": "",
                "confidence": 0.7,
                "source_ref": sent[:120],
            }
        )
    batt = _BATT_RE.search(plain)
    if batt:
        specs.append(
            {
                "param": "电池容量",
                "value": batt.group(1),
                "unit": "mAh",
                "brand": "",
                "model": "",
                "confidence": 0.85,
                "source_ref": batt.group(0),
            }
        )
    return specs


def _internal_structure(major, minor, plain: str) -> list[dict]:
    items: list[dict] = []
    structural_names = {
        "外壳结构", "喇叭单元", "主板/PCBA", "电池", "天线", "麦克风", "降噪系统", "骨传导振子",
        "耳挂/挂钩", "触控/按键", "充电触点",
    }
    for comp in major + minor:
        if comp.name not in structural_names:
            continue
        for mention in comp.mentions[:2]:
            if _is_packaging_sentence(mention.text):
                continue
            items.append(
                {
                    "value": mention.text,
                    "evidence": make_evidence(mention.text, mention.text, confidence=0.74),
                }
            )
    for sent in split_sentences(plain):
        if _is_packaging_sentence(sent):
            continue
        if any(k in sent for k in ("内部", "腔体", "结构", "固定", "组装", "拆解", "焊接", "点胶")):
            if len(sent) > 12:
                items.append({"value": sent, "evidence": make_evidence(sent, sent, confidence=0.65)})
    seen: set[str] = set()
    deduped = []
    for item in items:
        key = item["value"][:60]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:8]


def _fastener_type(plain: str) -> list[dict]:
    out = []
    for sent in split_sentences(plain):
        if any(kw in sent for kw in lexicon.FASTENER_KEYWORDS):
            out.append({"value": sent, "evidence": make_evidence(sent, sent, confidence=0.68)})
    return out[:5]


def _sealing_method(plain: str) -> list[dict]:
    out = []
    for sent in split_sentences(plain):
        if any(kw in sent for kw in lexicon.SEALING_KEYWORDS) or _IP_RE.search(sent):
            out.append({"value": sent, "evidence": make_evidence(sent, sent, confidence=0.68)})
    return out[:5]


def _wear_design(plain: str) -> list[dict]:
    sents = [s for s in split_sentences(plain) if any(k in s for k in ("佩戴", "耳挂", "耳夹", "头梁", "耳塞", "舒适"))]
    return _evidence_list(sents[:4], confidence=0.7)


def _market_selling_points(selling_raw) -> list[dict]:
    points: list[dict] = []
    for sp in selling_raw:
        if _is_tech_sentence(sp.text):
            continue
        if _is_packaging_sentence(sp.text):
            continue
        conf = _confidence_from_sentiment(sp.sentiment)
        points.append(
            {
                "text": sp.text,
                "tag": _tag_selling_point(sp.text),
                "evidence": make_evidence(sp.text, sp.text, confidence=conf),
            }
        )
    return points[:6]


def compute_data_completeness(views: RoleViews) -> float:
    scores: list[float] = []

    m = views.market
    m_score = 0.0
    if m.brand:
        m_score += 0.15
    if m.model:
        m_score += 0.1
    if m.selling_points:
        m_score += min(0.35, 0.07 * len(m.selling_points))
    if m.scenarios:
        m_score += 0.1
    if m.price_cny is not None:
        m_score += 0.15
    if m.launch_date:
        m_score += 0.15
    scores.append(min(1.0, m_score))

    c = views.cost
    c_score = 0.0
    if c.major_parts:
        c_score += min(0.35, 0.06 * len(c.major_parts))
    if c.chip_modules:
        c_score += min(0.25, 0.08 * len(c.chip_modules))
    if c.bom_table:
        c_score += min(0.25, 0.04 * len(c.bom_table))
    if c.process_hints:
        c_score += 0.15
    scores.append(min(1.0, c_score))

    s = views.structure
    s_score = 0.0
    if s.earbud_type and s.earbud_type != "其他":
        s_score += 0.15
    if s.materials:
        s_score += 0.15
    if s.ip_rating:
        s_score += 0.15
    if s.internal_structure:
        s_score += min(0.3, 0.06 * len(s.internal_structure))
    if s.key_image_urls:
        s_score += min(0.15, 0.03 * len(s.key_image_urls))
    if s.wear_design:
        s_score += 0.1
    scores.append(min(1.0, s_score))

    h = views.hardware
    h_score = min(1.0, 0.2 * len(h.specs)) if h.specs else 0.0
    scores.append(h_score)

    sw = views.software
    sw_score = 0.0
    if sw.bluetooth_version:
        sw_score += 0.25
    if sw.codecs:
        sw_score += min(0.25, 0.08 * len(sw.codecs))
    if sw.multipoint:
        sw_score += 0.15
    if sw.app_features:
        sw_score += 0.15
    if sw.ota_support:
        sw_score += 0.1
    if sw.latency_notes:
        sw_score += 0.1
    scores.append(min(1.0, sw_score))

    return round(sum(scores) / len(scores), 3) if scores else 0.0


def extract_role_views(
    content_html: str,
    *,
    brand: str,
    model: str,
    category: str,
) -> RoleViews:
    plain = html_plain_text(content_html)
    selling_raw = extract_selling_points(plain, lexicon.SELLING_POINT_KEYWORDS)
    major, minor = extract_components(content_html, lexicon.COMPONENT_LEXICON)
    tech = extract_tech_specs(plain, lexicon.TECH_SPEC_RULES)
    price, price_note, price_ev = extract_price_from_text(plain)
    launch, launch_ev = extract_launch_date(plain)
    bt_ver, bt_ev = _extract_bluetooth_version(plain)
    ip_rating, ip_ev = _extract_ip_rating(plain)
    weight, weight_ev = _extract_weight(plain)

    market_points = _market_selling_points(selling_raw)
    positioning = market_points[0]["text"] if market_points else ""

    market = MarketView(
        brand=brand,
        model=model,
        category=category,
        launch_date=launch,
        launch_date_evidence=launch_ev,
        price_cny=price,
        price_note=price_note,
        price_evidence=price_ev,
        selling_points=market_points,
        scenarios=_match_scenarios(plain),
        positioning_summary=positioning,
    )

    chips = _dedupe_chips(_chip_modules_from_text(plain))
    major_names = [c.name for c in major if c.name not in _PACKAGING_COMPONENTS]
    process_sents = [
        s for s in split_sentences(plain) if any(k in s for k in ("焊接", "点胶", "一体化", "注塑", "CNC", "超声"))
    ][:5]

    # V3 Phase1：定位「我爱音频网总结」段，从 prose 抽 BOM 行（priority 高于正文片段）
    summary_section = locate_summary_section(content_html)
    summary_bom_rows: list[dict] = []
    summary_image_urls: list[str] = []
    summary_text = ""
    summary_section_html = ""
    summary_heading = ""
    if summary_section:
        summary_text = summary_section.get("text", "")
        summary_section_html = summary_section.get("html", "")
        summary_heading = summary_section.get("heading", "")
        summary_image_urls = summary_section.get("image_urls", []) or []
        summary_bom_rows = extract_bom_from_prose(summary_text)

    text_bom = _build_bom_table(major, minor, plain)
    merged_bom = _merge_bom_with_summary(text_bom, summary_bom_rows)

    # 把 summary 里的芯片也并入 chip_modules（summary 优先，正文 chip 仅补未覆盖的型号）
    summary_chip_rows = [r for r in summary_bom_rows if r.get("component") == "芯片/模组"]
    # 用 canonical（型号核心数字字母 token）做去重 key，避免「思远半导体SY8805」与「SY8805」重复
    def _chip_canon(model: str) -> str:
        m = re.search(r"[A-Z]{1,4}\d+[A-Z0-9]*$", model or "", re.I)
        return m.group(0).upper() if m else re.sub(r"\s+", "", model or "").upper()

    enriched_chips: list[dict] = []
    seen_canon: set[str] = set()
    for r in summary_chip_rows:
        norm = _normalize_bom_row(r)
        canon = _chip_canon(norm.get("model", ""))
        if canon and canon not in seen_canon:
            seen_canon.add(canon)
            enriched_chips.append(norm)
    for c in chips:  # 正文 chip_modules（已 canonical-deduped）
        canon = _chip_canon(c.get("model", ""))
        if canon and canon not in seen_canon:
            seen_canon.add(canon)
            enriched_chips.append(c)

    cost = CostView(
        major_parts=major_names,
        chip_modules=enriched_chips,
        bom_table=merged_bom,
        supply_hints=_supply_hints(plain),
        packaging_notes=[s for s in tech.manual_notes[:5] if _is_packaging_sentence(s) or "包装" in s or "配件" in s],
        process_hints=_evidence_list(process_sents, confidence=0.68),
        summary_image_urls=_summary_images_to_dicts(summary_image_urls, summary_section_html),
        summary_text=summary_text,
    )

    key_images = extract_key_image_urls(content_html)
    internal = _internal_structure(major, minor, plain)

    # 把总结段 PNG 物料表 URL 加入 structure.key_image_urls（priority 高，前置 + 去重）
    summary_img_dicts = _summary_images_to_dicts(summary_image_urls, summary_section_html)
    if summary_img_dicts:
        existing_urls = {k.get("url") for k in key_images}
        merged_images = list(summary_img_dicts)
        for k in key_images:
            if k.get("url") not in {m.get("url") for m in merged_images}:
                merged_images.append(k)
        key_images = merged_images

    structure = StructureView(
        form_factor=category,
        earbud_type=_guess_earbud_type(category, plain),
        materials=_match_materials(plain),
        ip_rating=ip_rating,
        ip_rating_evidence=ip_ev,
        weight_g=weight,
        weight_evidence=weight_ev,
        dimensions=[s for s in split_sentences(plain) if "尺寸" in s or "mm" in s][:3],
        internal_structure=internal,
        fastener_type=_fastener_type(plain),
        sealing_method=_sealing_method(plain),
        wear_design=_wear_design(plain),
        key_image_urls=key_images,
        assembly_notes=[item["value"] for item in internal[:4]],
    )

    hardware = HardwareView(specs=_hardware_specs(plain, tech))

    software = SoftwareView(
        bluetooth_version=bt_ver,
        bluetooth_evidence=bt_ev,
        codecs=_match_codecs(plain),
        multipoint=_evidence_list(
            [s for s in split_sentences(plain) if any(k in s for k in ("多点", "多设备", "双设备", "一拖二"))][:3],
            confidence=0.72,
        ),
        app_name="",
        app_features=_evidence_list(
            [s for s in split_sentences(plain) if "APP" in s or "App" in s or "应用" in s][:4],
            confidence=0.7,
        ),
        ota_support=_evidence_list(
            [s for s in split_sentences(plain) if "OTA" in s or "固件" in s or "升级" in s][:3],
            confidence=0.68,
        ),
        latency_notes=_evidence_list(
            [s for s in split_sentences(plain) if any(k in s for k in ("延迟", "低延迟", "游戏模式"))][:3],
            confidence=0.72,
        ),
    )

    views = RoleViews(market=market, cost=cost, structure=structure, hardware=hardware, software=software)
    return views


def views_to_dict_with_completeness(views: RoleViews) -> tuple[dict, float]:
    completeness = compute_data_completeness(views)
    return views.to_dict(), completeness
