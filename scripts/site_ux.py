"""站点 UX 辅助：完整度、证据徽章、空状态、PM 要点等。"""

from __future__ import annotations

from core.compare import find_internal_matches

SOURCE_LABELS = {
    "text": "正文",
    "article": "正文",
    "body": "正文",
    "正文": "正文",
    "migrated": "正文",
    "inferred": "推断",
    "推断": "推断",
    "ocr": "OCR",
    "OCR": "OCR",
    "manual": "人工",
    "人工": "人工",
    "price_csv": "人工",
}


def _esc(text: str) -> str:
    import html

    return html.escape(text or "", quote=True)


def source_type_from_ref(ref: str) -> str:
    ref = (ref or "").lower()
    if ref in ("text", "article", "body", "migrated", "正文"):
        return "text"
    if ref in ("inferred", "推断"):
        return "inferred"
    if ref in ("ocr",):
        return "ocr"
    if ref in ("manual", "price_csv", "人工"):
        return "manual"
    return "text"


def evidence_badge(source_type: str) -> str:
    label = SOURCE_LABELS.get(source_type, SOURCE_LABELS.get(source_type_from_ref(source_type), "正文"))
    cls = {
        "正文": "evidence-text",
        "推断": "evidence-inferred",
        "OCR": "evidence-ocr",
        "人工": "evidence-manual",
    }.get(label, "evidence-text")
    return f'<span class="evidence-badge {cls}" title="数据来源">{label}</span>'


def get_field_evidence(record: dict, field_path: str) -> str:
    ev = record.get("evidence") or {}
    if isinstance(ev, dict) and field_path in ev:
        item = ev[field_path]
        if isinstance(item, dict):
            return item.get("source_type") or "text"
        return str(item)
    return ""


def compute_completeness(record: dict) -> int:
    """根据 views 各区块填充率估算完整度 0–100；优先使用 data_completeness 字段。"""
    stored = record.get("data_completeness")
    if isinstance(stored, (int, float)) and stored > 0:
        return round(float(stored) * 100)
    v = record.get("views") or {}
    checks: list[bool] = []

    m = v.get("market", {})
    checks.append(bool(m.get("positioning_summary")))
    checks.append(m.get("price_cny") is not None or bool(m.get("price_note")))
    checks.append(bool(m.get("selling_points")))
    checks.append(bool(m.get("launch_date")))

    c = v.get("cost", {})
    checks.append(bool(c.get("major_parts")))
    checks.append(bool(c.get("chip_modules")))

    s = v.get("structure", {})
    checks.append(bool(s.get("form_factor")))
    checks.append(bool(s.get("materials") or s.get("weight_g") or s.get("ip_rating")))

    h = v.get("hardware", {})
    checks.append(bool(h.get("specs")))

    sw = v.get("software", {})
    checks.append(bool(sw.get("bluetooth_version") or sw.get("codecs")))

    if not checks:
        return 0
    return round(100 * sum(checks) / len(checks))


def empty_state_hint(record: dict, section: str, has_content: bool) -> str:
    if has_content:
        return ""
    comp = record.get("completeness") or {}
    ocr_pending = comp.get("ocr_pending") or record.get("ocr_status") == "pending"
    if section in ("hardware", "cost") and ocr_pending:
        return "待 OCR"
    if comp.get("needs_manual"):
        return "待人工补录"
    return "原文未提及"


def empty_hint_html(record: dict, section: str, has_content: bool) -> str:
    hint = empty_state_hint(record, section, has_content)
    if not hint:
        return ""
    cls = {
        "待 OCR": "empty-ocr",
        "原文未提及": "empty-missing",
        "待人工补录": "empty-manual",
    }.get(hint, "empty-missing")
    return f'<p class="empty-hint {cls}">{_esc(hint)}</p>'


def completeness_bar_html(pct: int) -> str:
    color = "#22c55e" if pct >= 70 else "#f59e0b" if pct >= 40 else "#ef4444"
    return (
        f'<div class="completeness-wrap">'
        f'<span class="completeness-label">数据完整度：{pct}%</span>'
        f'<div class="completeness-track"><div class="completeness-fill" style="width:{pct}%;background:{color}"></div></div>'
        f"</div>"
    )


def pm_tech_bullets(views: dict, limit: int = 5) -> list[str]:
    bullets: list[str] = []
    cost = views.get("cost", {})
    for part in cost.get("major_parts", [])[:2]:
        if part:
            bullets.append(f"主要部件：{part}")
    for chip in cost.get("chip_modules", [])[:2]:
        model = chip.get("model") or chip.get("part")
        if model:
            bullets.append(f"芯片/模组：{model}")

    struct = views.get("structure", {})
    if struct.get("form_factor"):
        bullets.append(f"形态：{struct['form_factor']}")
    if struct.get("ip_rating"):
        bullets.append(f"防护：{struct['ip_rating']}")
    if struct.get("weight_g"):
        bullets.append(f"重量：{struct['weight_g']}")

    for spec in views.get("hardware", {}).get("specs", [])[:2]:
        part = spec.get("param") or spec.get("part", "")
        val = spec.get("value") or spec.get("model") or ""
        if part and val:
            bullets.append(f"{part}：{val[:60]}")

    sw = views.get("software", {})
    if sw.get("bluetooth_version"):
        bullets.append(f"蓝牙 {sw['bluetooth_version']}")
    for codec in sw.get("codecs", [])[:1]:
        label = codec.get("value") if isinstance(codec, dict) else codec
        if label:
            bullets.append(f"编码：{label}")

    seen: set[str] = set()
    out: list[str] = []
    for b in bullets:
        if b not in seen:
            seen.add(b)
            out.append(b)
        if len(out) >= limit:
            break
    return out


def pm_bullets_html(views: dict) -> str:
    bullets = pm_tech_bullets(views)
    if not bullets:
        return ""
    items = "".join(f"<li>{_esc(b)}</li>" for b in bullets)
    return f'<div class="pm-bullets"><div class="pm-bullets-title">技术要点</div><ul>{items}</ul></div>'


def internal_compare_html(record: dict) -> str:
    matches = find_internal_matches(record)
    if not matches:
        return ""
    rows = []
    for m in matches:
        name = m.get("name") or m.get("model") or m.get("sku", "")
        sku = m.get("sku", "")
        note = m.get("notes", "")
        rows.append(f"<li><b>{_esc(name)}</b>（{_esc(sku)}）{_esc(note)}</li>")
    return (
        '<div class="internal-compare">'
        '<div class="internal-compare-title">内部对标提示</div>'
        f"<ul>{''.join(rows)}</ul></div>"
    )


def _fmt_list_item(i) -> str:
    if isinstance(i, dict):
        tag = i.get("tag", "")
        text = i.get("text") or i.get("value") or ""
        if tag and text:
            return f"[{tag}] {text}"
        return text or str(i)
    return str(i)


def collapsible_list(title: str, items: list, record: dict, section: str, threshold: int = 4) -> str:
    has = bool(items)
    if not has:
        return f'<div class="sub"><b>{_esc(title)}</b>{empty_hint_html(record, section, False)}</div>'
    if len(items) <= threshold:
        body = "<ul>" + "".join(f"<li>{_esc(_fmt_list_item(i))}</li>" for i in items) + "</ul>"
        return f'<div class="sub"><b>{_esc(title)}</b>{body}</div>'
    preview = items[:threshold]
    rest = items[threshold:]
    body = "<ul>" + "".join(f"<li>{_esc(_fmt_list_item(i))}</li>" for i in preview) + "</ul>"
    body += (
        f'<details class="collapsible-list"><summary>展开其余 {len(rest)} 条</summary><ul>'
        + "".join(f"<li>{_esc(_fmt_list_item(i))}</li>" for i in rest)
        + "</ul></details>"
    )
    return f'<div class="sub"><b>{_esc(title)}</b>{body}</div>'


def field_with_badge(label: str, value: str, source_type: str = "") -> str:
    val = value or "未识别"
    badge = evidence_badge(source_type or "text") if value else ""
    return f"<p><b>{_esc(label)}：</b>{badge}{_esc(val)}</p>"


def export_data_json(record: dict) -> dict:
    v = record.get("views") or {}
    return {
        "id": record.get("id"),
        "brand": record.get("brand"),
        "model": record.get("model"),
        "cost": v.get("cost", {}),
        "hardware": v.get("hardware", {}),
    }
