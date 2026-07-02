"""从正文纯文本/HTML 抽取五区块 views（A–E）。"""

from __future__ import annotations

import re

from core.extract.components import extract_components
from core.extract.selling_points import extract_selling_points
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


def extract_price_from_text(plain: str) -> tuple[float | None, str]:
    m = _PRICE_RE.search(plain)
    if m:
        return float(m.group(1)), "正文标注售价"
    for m in _PRICE_YEN_RE.finditer(plain):
        val = float(m.group(1))
        if 29 <= val <= 9999:
            return val, "正文出现价格数字（待人工确认）"
    return None, ""


def extract_launch_date(plain: str) -> str | None:
    for kw in ("上市", "开售", "发布", "将于", "正式上市"):
        idx = plain.find(kw)
        if idx == -1:
            continue
        snippet = plain[idx : idx + 40]
        m = _LAUNCH_RE.search(snippet)
        if m:
            return m.group(1).replace("年", "-").replace("月", "-").replace("日", "").strip("-")
    return None


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


def _match_codecs(plain: str) -> list[str]:
    found = []
    for kw in lexicon.CODEC_KEYWORDS:
        if re.search(kw, plain, re.I) and kw.upper() not in [c.upper() for c in found]:
            found.append(kw)
    return found


def _extract_bluetooth_version(plain: str) -> str | None:
    m = re.search(r"蓝牙\s*([0-9]\.[0-9]+)", plain)
    if m:
        return m.group(1)
    m = re.search(r"Bluetooth\s*([0-9]\.[0-9]+)", plain, re.I)
    return m.group(1) if m else None


def _extract_ip_rating(plain: str) -> str | None:
    m = re.search(r"IP\s*X?\d", plain, re.I)
    return m.group(0).upper() if m else None


def _extract_weight(plain: str) -> str | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|克)", plain)
    return m.group(0) if m else None


def _chip_modules_from_text(plain: str) -> list[dict]:
    modules = []
    for pat in lexicon.CHIP_PATTERNS:
        for m in re.finditer(pat, plain, re.I):
            modules.append({"part": "芯片/模组", "brand": "", "model": m.group(0), "qty_hint": ""})
    return modules[:20]


def _hardware_specs(plain: str, tech) -> list[dict]:
    specs = []
    for sent in tech.charging_method:
        specs.append({"part": "充电", "brand": "", "model": "", "value": sent, "unit": "", "source_ref": "text"})
    for sent in tech.charging_port:
        specs.append({"part": "充电接口", "brand": "", "model": "", "value": sent, "unit": "", "source_ref": "text"})
    for port in guess_charging_ports(plain):
        specs.append({"part": "充电接口", "brand": "", "model": port, "value": port, "unit": "", "source_ref": "text"})
    for sent in tech.product_markings:
        specs.append({"part": "标记/认证", "brand": "", "model": "", "value": sent, "unit": "", "source_ref": "text"})
    batt = re.search(r"(\d+)\s*mAh", plain, re.I)
    if batt:
        specs.append({"part": "电池", "brand": "", "model": "", "value": batt.group(1), "unit": "mAh", "source_ref": "text"})
    return specs


def extract_role_views(
    content_html: str,
    *,
    brand: str,
    model: str,
    category: str,
) -> RoleViews:
    plain = html_plain_text(content_html)
    selling = extract_selling_points(plain, lexicon.SELLING_POINT_KEYWORDS)
    major, minor = extract_components(content_html, lexicon.COMPONENT_LEXICON)
    tech = extract_tech_specs(plain, lexicon.TECH_SPEC_RULES)
    price, price_note = extract_price_from_text(plain)
    launch = extract_launch_date(plain)

    market = MarketView(
        brand=brand,
        model=model,
        category=category,
        launch_date=launch,
        price_cny=price,
        price_note=price_note,
        selling_points=[sp.text for sp in selling[:6]],
        scenarios=_match_scenarios(plain),
        positioning_summary=selling[0].text if selling else "",
    )

    major_names = [c.name for c in major]
    minor_names = [c.name for c in minor]
    cost = CostView(
        major_parts=major_names,
        chip_modules=_chip_modules_from_text(plain),
        packaging_notes=tech.manual_notes[:5],
        process_hints=[s for s in split_sentences(plain) if any(k in s for k in ("焊接", "点胶", "一体化", "注塑", "CNC"))][:5],
    )

    structure = StructureView(
        form_factor=category,
        materials=_match_materials(plain),
        ip_rating=_extract_ip_rating(plain),
        weight_g=_extract_weight(plain),
        dimensions=[s for s in split_sentences(plain) if "尺寸" in s or "mm" in s][:3],
        wear_design=[s for s in split_sentences(plain) if any(k in s for k in ("佩戴", "耳挂", "耳夹", "头梁", "耳塞"))][:4],
        assembly_notes=[m.text for c in major + minor for m in c.mentions[:1]][:6],
    )

    hardware = HardwareView(specs=_hardware_specs(plain, tech))

    software = SoftwareView(
        bluetooth_version=_extract_bluetooth_version(plain),
        codecs=_match_codecs(plain),
        multipoint=[s for s in split_sentences(plain) if any(k in s for k in ("多点", "多设备", "双设备", "一拖二"))][:3],
        app_name="",
        app_features=[s for s in split_sentences(plain) if "APP" in s or "App" in s or "应用" in s][:4],
        ota_support=[s for s in split_sentences(plain) if "OTA" in s or "固件" in s or "升级" in s][:3],
        latency_notes=[s for s in split_sentences(plain) if any(k in s for k in ("延迟", "低延迟", "游戏模式"))][:3],
    )

    return RoleViews(market=market, cost=cost, structure=structure, hardware=hardware, software=software)
