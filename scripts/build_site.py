"""v2 静态站点：父级列表 + 子级五区块角色透镜（无原文 HTML 转载）。"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.cost_extract import extract_cost_fields  # noqa: E402
from core.ingest import (  # noqa: E402
    load_all_records,
    load_index,
    load_price_enrich,
    load_video_asr,
    merge_price_into_record,
)
from scripts.site_common import (  # noqa: E402
    SITE_TAGLINE,
    SITE_TITLE,
    category_tag,
    esc,
    page_shell,
    search_toolbar_html,
    truncate,
)
from scripts.site_ux import (  # noqa: E402
    collapsible_list,
    completeness_bar_html,
    compute_completeness,
    empty_hint_html,
    evidence_badge,
    export_data_json,
    field_with_badge,
    get_field_evidence,
    internal_compare_html,
    pm_bullets_html,
    source_type_from_ref,
)

SITE_DIR = ROOT / "site"
DATA_DIR = ROOT / "data"
MATRIX_DIR = DATA_DIR / "matrix"
COMPARE_DATA_DIR = DATA_DIR / "compare"
PRODUCTS_DIR = DATA_DIR / "products"

ROLE_LENSES = {
    "pm": {"label": "产品经理", "sections": ["market", "cost", "structure", "hardware", "software"]},
    "cost": {"label": "成本工程师", "sections": ["cost", "structure", "hardware", "software"]},
    "structure": {"label": "结构工程师", "sections": ["structure"]},
    "hardware": {"label": "硬件工程师", "sections": ["hardware"]},
    "software": {"label": "软件工程师", "sections": ["software"]},
}

# ---- V3 Phase1: 矩阵角色透镜列 + 品类对比页 + 字段注释 ----

FIELD_ANNOTATIONS_PATH = DATA_DIR / "field_annotations.json"

# 角色 → 矩阵列 key（field_annotations.json 缺失时的降级默认）
DEFAULT_MATRIX_ROLE_COLUMNS: dict[str, list[str]] = {
    "cost": [
        "brand", "model", "price_cny", "main_chip", "pmic",
        "battery_ear", "battery_case", "speaker", "materials",
        "weight_g", "ip_rating", "bluetooth", "bom_rows",
        "layer_badges", "data_completeness",
    ],
    "pm": ["brand", "model", "category", "selling_point_tags", "scenarios",
           "launch_date", "price_cny", "data_completeness"],
    "structure": ["form_factor", "materials", "ip_rating", "weight_g", "dimensions", "earbud_type"],
    "hardware": ["bluetooth", "codecs", "battery_mah", "charge_interface", "certifications"],
    "software": ["bluetooth_version", "codecs_sw", "multipoint", "app", "ota", "latency"],
}

MATRIX_COLUMN_LABELS: dict[str, str] = {
    "brand": "品牌", "model": "型号", "category": "品类",
    "selling_point_tags": "卖点标签", "scenarios": "场景",
    "launch_date": "上市", "price_cny": "售价", "data_completeness": "数据完整度",
    "main_chip": "主控芯片", "battery": "电池", "battery_ear": "耳机电池",
    "battery_case": "仓电池", "pmic": "PMIC", "speaker": "喇叭规格",
    "case_charging": "仓充电", "bom_rows": "BOM行数", "packaging": "包装",
    "materials": "关键材料", "layer_badges": "信源层",
    "form_factor": "形态", "ip_rating": "IP", "weight_g": "重量",
    "dimensions": "尺寸", "earbud_type": "佩戴类型",
    "bluetooth": "蓝牙", "codecs": "编码", "battery_mah": "电池mAh",
    "charge_interface": "充电接口", "certifications": "认证",
    "bluetooth_version": "蓝牙版本", "codecs_sw": "编码",
    "multipoint": "多点", "app": "App", "ota": "OTA", "latency": "延迟",
}


def _load_field_annotations() -> dict:
    try:
        if FIELD_ANNOTATIONS_PATH.exists():
            data = json.loads(FIELD_ANNOTATIONS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _matrix_role_columns(annotations: dict) -> dict[str, list[str]]:
    mc = annotations.get("matrix_columns") if isinstance(annotations, dict) else None
    if isinstance(mc, dict) and mc:
        out = {}
        for k, v in mc.items():
            if isinstance(v, list):
                out[k] = [str(x) for x in v]
        if out:
            return out
    return {k: list(v) for k, v in DEFAULT_MATRIX_ROLE_COLUMNS.items()}


def _field_annotation(annotations: dict, field_key: str) -> str:
    if not isinstance(annotations, dict):
        return ""
    item = annotations.get(field_key)
    if isinstance(item, dict):
        why = item.get("why_care") or item.get("desc") or item.get("annotation") or ""
        label = item.get("label") or ""
        return f"{label}: {why}".strip(": ") if label and why else (why or label)
    fields = annotations.get("fields") or annotations
    if isinstance(fields, dict):
        item = fields.get(field_key)
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return item.get("why_care") or item.get("desc") or item.get("annotation") or item.get("label") or ""
    return ""


def _category_filename(category: str) -> str:
    import re
    safe = re.sub(r'[<>:"/\\|?*]', "_", (category or "").strip())
    return f"{safe}.html"


def _codec_values(codecs) -> list[str]:
    out: list[str] = []
    for c in codecs or []:
        if isinstance(c, dict):
            v = c.get("value") or c.get("text") or ""
            if v:
                out.append(str(v))
        elif isinstance(c, str) and c:
            out.append(c)
    return out


def _ev_text(item) -> str:
    if isinstance(item, dict):
        ev = item.get("evidence")
        if isinstance(ev, dict):
            return ev.get("source_text") or ev.get("value") or ""
        return item.get("source_text") or item.get("source_ref") or item.get("value") or ""
    return ""


def _load_reports_by_canonical_id() -> dict[str, dict]:
    from core.products import canonical_product_id
    out: dict[str, dict] = {}
    for r in load_all_records("report"):
        r = merge_price_into_record(r)
        brand = r.get("brand") or ""
        model = r.get("model") or ""
        cid = canonical_product_id(brand, model)
        prev = out.get(cid)
        if prev is None:
            out[cid] = r
        else:
            prev_dc = prev.get("data_completeness") or 0
            cur_dc = r.get("data_completeness") or 0
            if cur_dc > prev_dc:
                out[cid] = r
    return out


def _enrich_row_from_report(row: dict, report: dict | None, product: dict | None = None) -> dict[str, dict]:
    """返回 {col_key: {"value": str, "evidence": str, "source_layer": str}}。"""
    v = (report or {}).get("views") or {}
    market = v.get("market", {})
    enriched = extract_cost_fields(v, row_fallback=row) if report else {}

    # 产品级成本快照优先（build_products 离线融合）
    snap = (product or {}).get("cost_snapshot") or {}
    snap_map = {
        "main_chip": snap.get("main_chip"),
        "pmic": snap.get("pmic_case"),
        "battery_ear": snap.get("battery_ear"),
        "battery_case": snap.get("battery_case"),
        "speaker": snap.get("speaker"),
        "materials": snap.get("materials"),
        "weight_g": snap.get("weight_g"),
        "ip_rating": snap.get("ip_rating"),
        "bluetooth": snap.get("bluetooth"),
        "bom_rows": str(snap.get("bom_row_count") or "") if snap.get("bom_row_count") is not None else "",
    }
    for key, val in snap_map.items():
        if val:
            prev = enriched.get(key) or {}
            enriched[key] = {"value": str(val), "evidence": prev.get("evidence", ""), "source_layer": "technical"}

    def cell(val: str, ev: str = "", layer: str = "technical") -> dict:
        return {"value": val or "", "evidence": ev or "", "source_layer": layer}

    # PM 字段
    enriched["category"] = cell((report or {}).get("category") or row.get("category") or (product or {}).get("category") or "")
    scen = market.get("scenarios") or []
    enriched["scenarios"] = cell("、".join(str(s) for s in scen if s))
    enriched["selling_point_tags"] = cell("、".join(row.get("selling_point_tags") or []))
    enriched["launch_date"] = cell(row.get("launch_date") or market.get("launch_date") or "")

    price = snap.get("price_cny") if snap.get("price_cny") is not None else row.get("price_cny")
    price_layer = snap.get("price_layer") or row.get("price_layer") or ""
    if price is not None:
        price_txt = f"¥{price}"
        if price_layer == "channel":
            price_txt += " (渠道)"
        enriched["price_cny"] = cell(price_txt, layer=price_layer or "technical")
    else:
        enriched["price_cny"] = cell("")

    layer_refs = (product or {}).get("layer_refs") or {}
    badges = []
    for layer, refs in layer_refs.items():
        if refs:
            badges.append(layer)
    enriched["layer_badges"] = cell("、".join(badges))

    dc = snap.get("data_completeness") if snap else row.get("data_completeness")
    if isinstance(dc, float) and 0 < dc <= 1:
        enriched["data_completeness"] = cell(f"{int(dc * 100)}%")
    else:
        enriched["data_completeness"] = cell(str(dc) if dc is not None else "")

    return enriched


def _matrix_row_cells(row: dict, report: dict | None, role_columns: dict[str, list[str]],
                      annotations: dict, product: dict | None = None) -> dict[str, dict]:
    """合并 matrix row 基础字段 + 报告/产品富化字段。"""
    enriched = _enrich_row_from_report(row, report, product)
    base = {
        "brand": {"value": row.get("brand") or (product or {}).get("brand") or "", "evidence": ""},
        "model": {"value": row.get("model") or (product or {}).get("model") or "", "evidence": ""},
    }
    merged = dict(enriched)
    merged.update(base)
    return merged


def _list(items: list[str], empty: str = "暂无", record: dict | None = None, section: str = "") -> str:
    if not items:
        if record is not None:
            return empty_hint_html(record, section, False) or f'<p class="empty-hint">{esc(empty)}</p>'
        return f'<p class="empty-hint">{esc(empty)}</p>'
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def _specs_table(specs: list[dict], record: dict) -> str:
    if not specs:
        return empty_hint_html(record, "hardware", False) or '<p class="empty-hint">暂无</p>'
    rows = []
    for s in specs:
        val = s.get("value") or s.get("model") or ""
        unit = s.get("unit") or ""
        src = get_field_evidence(record, f"hardware.specs.{s.get('param','')}") or source_type_from_ref(
            s.get("source_ref", "")
        )
        badge = evidence_badge(src)
        param = s.get("param") or s.get("part", "")
        rows.append(
            f"<tr><td>{esc(param)}</td><td>{badge}{esc(str(val))} {esc(unit)}</td>"
            f"<td>{esc(s.get('source_ref',''))}</td></tr>"
        )
    return f'<table class="spec-table"><thead><tr><th>部件</th><th>参数</th><th>来源</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _chip_table(chips: list[dict], record: dict) -> str:
    if not chips:
        return empty_hint_html(record, "cost", False) or '<p class="empty-hint">暂无</p>'
    rows = []
    for c in chips:
        src = get_field_evidence(record, f"cost.chip.{c.get('model','')}") or "text"
        badge = evidence_badge(src)
        rows.append(
            f"<tr><td>{esc(c.get('component') or c.get('part',''))}</td>"
            f"<td>{badge}{esc(c.get('model',''))}</td></tr>"
        )
    return f'<table class="spec-table"><thead><tr><th>类型</th><th>型号</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _bom_table_html(bom: list[dict], record: dict) -> str:
    if not bom:
        return empty_hint_html(record, "cost", False) or '<p class="empty-hint">暂无 BOM 行（待从总结段/OCR 补充）</p>'
    rows = []
    for b in bom:
        ev = b.get("evidence") or {}
        src = ev.get("source_type", "text") if isinstance(ev, dict) else "text"
        badge = evidence_badge(src)
        rows.append(
            f"<tr><td>{esc(b.get('side') or '')}</td>"
            f"<td>{esc(b.get('component') or '')}</td>"
            f"<td>{esc(b.get('brand') or '')}</td>"
            f"<td>{badge}{esc(b.get('model') or '')}</td>"
            f"<td>{esc(b.get('qty_hint') or '')}</td>"
            f"<td>{esc(b.get('role') or '')}</td></tr>"
        )
    return (
        '<table class="spec-table bom-table"><thead><tr>'
        '<th>侧别</th><th>部件</th><th>厂商</th><th>型号</th><th>数量</th><th>角色</th>'
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def _summary_images_html(images: list[dict]) -> str:
    if not images:
        return ""
    items = []
    for img in images:
        url = img.get("url") or ""
        if not url:
            continue
        alt = img.get("alt") or img.get("caption") or "总结段物料图"
        items.append(
            f'<figure class="summary-img"><a href="{esc(url)}" target="_blank" rel="noopener">'
            f'<img src="{esc(url)}" alt="{esc(alt)}" loading="lazy" /></a>'
            f'<figcaption>{esc(alt)}</figcaption></figure>'
        )
    if not items:
        return ""
    return f'<div class="summary-images">{"".join(items)}</div>'


def _role_lens_html(default_role: str = "cost") -> str:
    buttons = []
    for key, meta in ROLE_LENSES.items():
        active = "active" if key == default_role else ""
        buttons.append(f'<button type="button" class="lens-btn {active}" data-lens="{key}">{esc(meta["label"])}</button>')
    export_btn = '<button type="button" class="export-btn" id="export-csv-btn">导出 CSV</button>'
    return f'<div class="lens-bar" id="role-lens">{"".join(buttons)}{export_btn}</div>'


def _section(title: str, section_id: str, body: str) -> str:
    return f'<section class="view-section" id="section-{section_id}" data-section="{section_id}"><h2>{esc(title)}</h2>{body}</section>'


def _card_data_attrs(item: dict, kind: str) -> str:
    title = item.get("title") or item.get("product_title") or ""
    return (
        f'data-id="{esc(item["id"])}" data-type="{esc(kind)}" '
        f'data-brand="{esc(item.get("brand",""))}" data-model="{esc(item.get("model",""))}" '
        f'data-title="{esc(title)}" data-published-at="{esc(item.get("published_at",""))}" '
        f'data-category="{esc(item.get("category",""))}"'
    )


def report_card(r: dict, depth: int) -> str:
    href = f"reports/{r['id']}.html" if depth == 0 else f"{r['id']}.html"
    brand_model = f"{r.get('brand','')} {r.get('model','')}".strip() or r.get("title", "")
    return f"""<div class="card" {_card_data_attrs(r, "report")}>
  <div class="type-flag">拆解报告</div>
  <h4><a href="{href}">{esc(brand_model)}</a></h4>
  <div class="meta">
    <span>{esc(r.get('published_at',''))}</span>
    <span>作者：{esc(r.get('author','') or '未知')}</span>
  </div>
  <div>{category_tag(r.get('category',''))}</div>
  <div class="summary">{esc(truncate(r.get('summary',''), 100))}</div>
  <div class="card-footer">
    <a href="{href}">查看角色视图</a>
    <a href="{esc(r['url'])}" target="_blank" rel="noopener">原文</a>
  </div>
</div>"""


def video_card(v: dict, depth: int) -> str:
    href = f"videos/{v['id']}.html" if depth == 0 else f"{v['id']}.html"
    asr_status = v.get("asr_status", "pending")
    return f"""<div class="card" {_card_data_attrs(v, "video")} data-asr="{esc(asr_status)}">
  <div class="type-flag">拆解视频</div>
  <h4><a href="{href}">{esc(v.get('product_title', v.get('title','')))}</a></h4>
  <div class="meta">
    <span>{esc(v.get('published_at',''))}</span>
    <span>发布者：{esc(v.get('publisher','') or '未知')}</span>
    <span>平台：{esc(v.get('source_site','') or '未知')}</span>
    <span class="asr-tag asr-{esc(asr_status)}">转写：{esc(asr_status)}</span>
  </div>
  <div>{category_tag(v.get('category',''))}</div>
  <div class="card-footer">
    <a href="{href}">查看详情</a>
    <a href="{esc(v['url'])}" target="_blank" rel="noopener">原文</a>
  </div>
</div>"""


def _is_today(item: dict, today: str, idx: dict) -> bool:
    """今日新增：published_at 为今天，或 captured_at 为今天且为近期发布（日更/回填）。"""
    published = (item.get("published_at") or "")[:10]
    captured = (item.get("captured_at") or "")[:10]
    if published == today:
        return True
    if captured != today:
        return False
    ldc = (idx.get("last_daily_crawl_at") or "")[:10]
    if ldc == today:
        return True
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
        pub_d = datetime.strptime(published, "%Y-%m-%d").date() if published else None
        if pub_d and (today_d - pub_d).days <= 1:
            return True
    except ValueError:
        pass
    return False


def _render_five_sections(r: dict, v: dict) -> str:
    """渲染 A–E 五区块（报告与视频详情页共用）。"""
    m = v.get("market", {})
    return (
        _section(
            "A · 产品与市场",
            "market",
            f"""
{field_with_badge("定位摘要", m.get('positioning_summary') or '', get_field_evidence(r, 'views.market.positioning_summary') or 'text')}
{field_with_badge("上市时间", m.get('launch_date') or '未识别', get_field_evidence(r, 'views.market.launch_date') or 'text')}
{collapsible_list("卖点", m.get('selling_points', []), r, 'market')}
{collapsible_list("使用场景", m.get('scenarios', []), r, 'market')}
""",
        )
        + _section(
            "B · 成本与 BOM",
            "cost",
            f"""
{collapsible_list("主要部件", v.get('cost', {}).get('major_parts', []), r, 'cost')}
<div class="sub"><b>芯片/模组</b>{_chip_table(v.get('cost', {}).get('chip_modules', []), r)}</div>
<div class="sub"><b>物料清单（BOM）</b>{_bom_table_html(v.get('cost', {}).get('bom_table', []), r)}</div>
{_summary_images_html(v.get('cost', {}).get('summary_image_urls', []))}
{collapsible_list("包装/附件", v.get('cost', {}).get('packaging_notes', []), r, 'cost')}
{collapsible_list("工艺线索", v.get('cost', {}).get('process_hints', []), r, 'cost')}
""",
        )
        + _section(
            "C · 结构与材料",
            "structure",
            f"""
{field_with_badge("形态", v.get('structure', {}).get('form_factor') or '', 'text')}
{field_with_badge("佩戴类型", v.get('structure', {}).get('earbud_type') or '未识别', 'text')}
{field_with_badge("防护等级", v.get('structure', {}).get('ip_rating') or '未识别', 'text')}
{field_with_badge("重量", v.get('structure', {}).get('weight_g') or '未识别', 'text')}
{collapsible_list("材料", v.get('structure', {}).get('materials', []), r, 'structure')}
{collapsible_list("内部结构", v.get('structure', {}).get('internal_structure', []), r, 'structure')}
{collapsible_list("佩戴/结构", v.get('structure', {}).get('wear_design', []), r, 'structure')}
{collapsible_list("关键图", [img.get('url','') for img in v.get('structure', {}).get('key_image_urls', []) if img.get('url')], r, 'structure')}
""",
        )
        + _section(
            "D · 硬件规格",
            "hardware",
            _specs_table(v.get("hardware", {}).get("specs", []), r),
        )
        + _section(
            "E · 软件与连接",
            "software",
            f"""
{field_with_badge("蓝牙版本", v.get('software', {}).get('bluetooth_version') or '未识别', 'text')}
{collapsible_list("音频编码", v.get('software', {}).get('codecs', []), r, 'software')}
{collapsible_list("多点连接", v.get('software', {}).get('multipoint', []), r, 'software')}
{collapsible_list("App 功能", v.get('software', {}).get('app_features', []), r, 'software')}
{collapsible_list("OTA/固件", v.get('software', {}).get('ota_support', []), r, 'software')}
{collapsible_list("低延迟", v.get('software', {}).get('latency_notes', []), r, 'software')}
""",
        )
    )


def build_report_detail(r: dict, out_dir: Path) -> None:
    v = r.get("views", {})
    m = v.get("market", {})
    price = m.get("price_cny")
    price_txt = f"¥{price}" if price is not None else "待补充"
    if m.get("price_note"):
        price_txt += f"（{m['price_note']}）"

    pct = r.get("completeness", {}).get("score") if isinstance(r.get("completeness"), dict) else None
    if pct is None:
        pct = compute_completeness(r)

    price_src = get_field_evidence(r, "views.market.price_cny") or ("manual" if price is not None else "text")

    annotations = _load_field_annotations()
    ann_fields = annotations.get("fields") if isinstance(annotations, dict) else None
    ann_map: dict[str, str] = {}
    if isinstance(ann_fields, dict):
        for k, val in ann_fields.items():
            if isinstance(val, str):
                ann_map[k] = val
            elif isinstance(val, dict):
                txt = val.get("desc") or val.get("annotation") or val.get("label") or ""
                if txt:
                    ann_map[k] = txt

    body = f"""
<div class="detail-header">
  {completeness_bar_html(int(pct))}
  {internal_compare_html(r)}
  <div>{category_tag(r.get('category',''))}</div>
  <h1>{esc(r.get('brand',''))} {esc(r.get('model',''))}</h1>
  <div class="meta-row">
    <span>发布：{esc(r.get('published_at',''))}</span>
    <span>作者：{esc(r.get('author','') or '未知')}</span>
    <span>售价：{evidence_badge(price_src)}{esc(price_txt)}</span>
  </div>
  <p>{esc(r.get('summary',''))}</p>
  <div class="original-link"><a href="{esc(r['url'])}" target="_blank" rel="noopener">查看 52audio 原文</a></div>
</div>

{_role_lens_html("cost")}
{pm_bullets_html(v)}
{_render_five_sections(r, v)}
"""
    export_json = json.dumps(export_data_json(r), ensure_ascii=False)
    ann_json = json.dumps(ann_map, ensure_ascii=False)
    extra = (
        f'<script>window.ROLE_LENSES={json.dumps(ROLE_LENSES, ensure_ascii=False)};'
        f"window.EXPORT_DATA={export_json};"
        f"window.FIELD_ANNOTATIONS={ann_json};</script>"
        f'<script src="../assets/export.js"></script>'
    )
    name = f"{r.get('brand','')} {r.get('model','')}".strip()
    (out_dir / f"{r['id']}.html").write_text(
        page_shell(name, body, active_nav="reports", depth=1, extra_head=extra),
        encoding="utf-8",
    )


def build_video_detail(v: dict, out_dir: Path) -> None:
    asr = load_video_asr(v["id"])
    asr_status = v.get("asr_status", "pending")

    # 有转写稿时跑 extract_role_views 填充 views；否则沿用 record 中由导语摘要生成的浅 views
    record_for_render = dict(v)
    asr_block = ""
    if asr and asr.get("transcript"):
        try:
            from core.views.role_extract import extract_role_views

            transcript_html = "".join(f"<p>{line}</p>" for line in asr["transcript"].splitlines() if line.strip())
            views_obj = extract_role_views(
                transcript_html,
                brand=v.get("brand", ""),
                model=v.get("model", "") or v.get("product_title", ""),
                category=v.get("category", ""),
            )
            views_dict, completeness = views_obj.to_dict(), None
            from core.views.role_extract import compute_data_completeness

            completeness = compute_data_completeness(views_obj)
            record_for_render["views"] = views_dict
            record_for_render["data_completeness"] = completeness
            asr_block = (
                f'<details open class="asr-transcript"><summary>视频转写稿（{esc(asr.get("method",""))}）</summary>'
                f'<pre class="asr-text">{esc(asr.get("transcript","")[:4000])}</pre></details>'
            )
        except Exception as e:
            asr_block = f'<p class="empty-hint empty-ocr">转写稿解析失败：{esc(str(e))}</p>'
    elif asr and asr.get("status") == "pending":
        reason = asr.get("degraded_reason") or asr.get("error", "")
        asr_block = (
            f'<p class="empty-hint empty-ocr">转写状态：pending'
            + (f"（{esc(reason)}）" if reason else "")
            + "——待 video-enrich 流程产出 asr.json 后再渲染完整五区块</p>"
        )
    elif asr and asr.get("status") in ("failed", "empty"):
        asr_block = f'<p class="empty-hint empty-missing">转写状态：{esc(asr.get("status",""))}（method={esc(asr.get("method",""))}）</p>'
    else:
        asr_block = '<p class="empty-hint empty-ocr">转写状态：pending——尚未运行 video-enrich 流程</p>'

    pct = compute_completeness(record_for_render)
    embed = ""
    if v.get("video_embed_url"):
        embed = f'<div class="video-embed-wrap"><iframe src="{esc(v["video_embed_url"])}" allowfullscreen></iframe></div>'

    views = record_for_render.get("views", {})
    title = v.get("product_title", v.get("title", ""))

    body = f"""
<div class="detail-header">
  {completeness_bar_html(pct)}
  {internal_compare_html(v)}
  <div>{category_tag(v.get('category',''))}</div>
  <h1>{esc(title)}</h1>
  <div class="meta-row">
    <span>发布：{esc(v.get('published_at',''))}</span>
    <span>发布者：{esc(v.get('publisher','') or '未知')}</span>
    <span>平台：{esc(v.get('source_site','') or '未知')}</span>
    <span>ASR：{esc(asr_status)}</span>
  </div>
  <p>{esc(v.get('summary',''))}</p>
  <div class="original-link"><a href="{esc(v['url'])}" target="_blank" rel="noopener">查看 52audio 原文</a></div>
</div>
{embed}
<div class="panel">{asr_block}</div>

{_role_lens_html("cost")}
{pm_bullets_html(views)}
{_render_five_sections(record_for_render, views)}
"""
    export_json = json.dumps(export_data_json(record_for_render), ensure_ascii=False)
    extra = (
        f'<script>window.ROLE_LENSES={json.dumps(ROLE_LENSES, ensure_ascii=False)};'
        f"window.EXPORT_DATA={export_json};</script>"
        f'<script src="../assets/export.js"></script>'
    )
    (out_dir / f"{v['id']}.html").write_text(
        page_shell(title, body, active_nav="videos", depth=1, extra_head=extra),
        encoding="utf-8",
    )


def build_index(reports: list[dict], videos: list[dict], idx: dict) -> None:
    today = date.today().isoformat()
    all_items = [{"type": "report", **r} for r in reports] + [{"type": "video", **v} for v in videos]
    today_items = [x for x in all_items if _is_today(x, today, idx)]
    merged = sorted(all_items, key=lambda x: x.get("published_at", ""), reverse=True)[:12]

    today_html = ""
    if today_items:
        today_cards = "\n".join(
            report_card(x, 0) if x["type"] == "report" else video_card(x, 0) for x in today_items[:8]
        )
        today_html = f"""
<div class="section-title">今日新增 <span class="section-badge">{len(today_items)}</span></div>
<div class="card-grid">{today_cards}</div>
"""

    timeline = "\n".join(
        report_card(x, 0) if x["type"] == "report" else video_card(x, 0) for x in merged
    ) or '<p class="empty-hint">暂无数据</p>'

    matrix_count = len(list(MATRIX_DIR.glob("*.json"))) if MATRIX_DIR.exists() else 0

    body = f"""
<section class="hero">
  <h1>{esc(SITE_TITLE)}</h1>
  <p>{esc(SITE_TAGLINE)}</p>
  <div class="hero-stats">
    <div class="hero-stat"><div class="num">{len(reports)}</div><div class="label">拆解报告</div></div>
    <div class="hero-stat"><div class="num">{len(videos)}</div><div class="label">拆解视频</div></div>
    <div class="hero-stat"><div class="num">{len(today_items)}</div><div class="label">今日新增</div></div>
  </div>
</section>
<div class="entry-grid">
  <a class="entry-card entry-card-matrix" href="matrix/index.html?role=cost"><h3>成本竞品矩阵</h3><div class="count">{matrix_count or '—'}</div><p>按品类横向对比 BOM/芯片/电池等成本参数</p></a>
  <a class="entry-card" href="compare/开放式耳机.html?role=cost"><h3>同品类对比</h3><div class="count">大表</div><p>成本参数行 × 产品列，链入产品摘要</p></a>
  <a class="entry-card" href="reports/index.html"><h3>拆解报告</h3><div class="count">{len(reports)}</div></a>
  <a class="entry-card" href="videos/index.html"><h3>拆解视频</h3><div class="count">{len(videos)}</div></a>
</div>
{today_html}
<div class="section-title">最近更新</div>
<div class="card-grid">{timeline}</div>
"""
    (SITE_DIR / "index.html").write_text(page_shell("首页", body, active_nav="home", depth=0), encoding="utf-8")


def build_list_page(kind: str, items: list[dict], title: str, nav: str) -> None:
    out = SITE_DIR / ("reports" if kind == "report" else "videos")
    out.mkdir(parents=True, exist_ok=True)
    cats = sorted({i.get("category", "") for i in items if i.get("category")})
    brands = sorted({i.get("brand", "") for i in items if i.get("brand")})
    filters = '<button class="filter-btn active" data-filter="__all__">全部</button>'
    filters += "".join(f'<button class="filter-btn" data-filter="{esc(c)}">{esc(c)}</button>' for c in cats)
    # 视频列表页：附加 ASR 状态筛选维度
    asr_filter_bar = ""
    if kind == "video":
        asr_filter_bar = (
            '<div class="filter-bar filter-bar-secondary" data-filter-dim="asr">'
            '<span class="filter-bar-label">转写状态：</span>'
            '<button class="filter-btn-asr active" data-asr-filter="__all__">全部</button>'
            '<button class="filter-btn-asr" data-asr-filter="done">已转写</button>'
            '<button class="filter-btn-asr" data-asr-filter="pending">待转写</button>'
            "</div>"
        )
    card_fn = report_card if kind == "report" else video_card
    cards = "\n".join(card_fn(i, 1) for i in sorted(items, key=lambda x: x.get("published_at", ""), reverse=True))
    cards = cards or '<p class="empty-hint">暂无</p>'
    index_rel = "../data/search-index.json"
    matrix_link = (
        '<p class="matrix-entry-link"><a href="../matrix/index.html?role=cost">进入成本矩阵 →</a>　'
        '<a href="../compare/开放式耳机.html?role=cost">同品类对比示例</a></p>'
        if kind == "report" else ""
    )
    body = (
        f'<h1 class="section-title">{esc(title)}（{len(items)} 条）</h1>'
        f"{matrix_link}"
        f"{search_toolbar_html(kind, brands, index_rel)}"
        f'<div class="filter-bar">{filters}</div>'
        f"{asr_filter_bar}"
        f'<div class="card-grid" id="card-grid">{cards}</div>'
        f'<p class="empty-hint search-empty" id="search-empty" style="display:none">无匹配结果，请调整搜索或筛选条件</p>'
    )
    (out / "index.html").write_text(page_shell(title, body, active_nav=nav, depth=1), encoding="utf-8")
    for i in items:
        if kind == "report":
            build_report_detail(i, out)
        else:
            build_video_detail(i, out)


def _matrix_cell(val) -> str:
    if val is None:
        return ""
    if isinstance(val, list):
        return "、".join(str(x) for x in val if x)
    if isinstance(val, float) and 0 < val <= 1:
        return f"{int(val * 100)}%"
    return str(val)


def _matrix_cell_html(cell_data: dict) -> str:
    val = (cell_data or {}).get("value") or ""
    if not val:
        return ""
    ev = (cell_data or {}).get("evidence") or ""
    if ev and ev != val:
        return (
            f'<details class="cell-ev"><summary>{esc(str(val))}</summary>'
            f'<p class="ev-text">{esc(str(ev))}</p></details>'
        )
    return esc(str(val))


def _load_products_by_canonical_id() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not PRODUCTS_DIR.exists():
        return out
    for path in PRODUCTS_DIR.glob("*.json"):
        if path.name == "index.json":
            continue
        try:
            product = json.loads(path.read_text(encoding="utf-8"))
            out[product["canonical_id"]] = product
        except Exception:
            continue
    return out


def _product_digest_href(cid: str, depth: int = 1) -> str:
    prefix = "../" * depth if depth else ""
    return f"{prefix}products/{cid}.html"


def _matrix_role_bar(role_columns: dict[str, list[str]], default_role: str = "cost") -> str:
    buttons = []
    # cost 角色排第一
    order = ["cost"] + [k for k in role_columns if k != "cost"]
    for key in order:
        if key not in role_columns:
            continue
        label = ROLE_LENSES.get(key, {}).get("label", key)
        active = "active" if key == default_role else ""
        buttons.append(
            f'<button type="button" class="lens-btn matrix-role-btn {active}" '
            f'data-matrix-role="{esc(key)}">{esc(label)}</button>'
        )
    return f'<div class="lens-bar matrix-role-bar" id="matrix-role-bar">{"".join(buttons)}</div>'


def build_matrix_pages() -> None:
    out = SITE_DIR / "matrix"
    out.mkdir(parents=True, exist_ok=True)
    if not MATRIX_DIR.exists():
        body = '<p class="empty-hint">竞品矩阵数据待生成，请先运行 build_search_index.py</p>'
        (out / "index.html").write_text(page_shell("竞品矩阵", body, active_nav="matrix", depth=1), encoding="utf-8")
        return

    matrices: list[dict] = []
    for path in sorted(MATRIX_DIR.glob("*.json")):
        try:
            matrices.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue

    if not matrices:
        body = '<p class="empty-hint">暂无矩阵数据</p>'
        (out / "index.html").write_text(page_shell("竞品矩阵", body, active_nav="matrix", depth=1), encoding="utf-8")
        return

    annotations = _load_field_annotations()
    role_columns = _matrix_role_columns(annotations)
    all_cols: list[str] = []
    for cols in role_columns.values():
        for c in cols:
            if c not in all_cols:
                all_cols.append(c)

    reports_by_cid = _load_reports_by_canonical_id()
    products_by_cid = _load_products_by_canonical_id()

    tabs = []
    panels = []
    for i, mat in enumerate(matrices):
        cat = mat.get("category", f"品类{i+1}")
        active = "active" if i == 0 else ""
        tabs.append(f'<button type="button" class="matrix-tab {active}" data-matrix-tab="{i}">{esc(cat)}</button>')
        rows = mat.get("rows", [])
        header = "".join(
            f'<th data-col="{esc(c)}" title="{esc(_field_annotation(annotations, c))}">'
            f'{esc(MATRIX_COLUMN_LABELS.get(c, c))}</th>'
            for c in all_cols
        ) + "<th>对比</th><th>摘要</th>"
        rows_html = []
        for row in rows:
            cid = row.get("canonical_id") or ""
            report = reports_by_cid.get(cid)
            product = products_by_cid.get(cid)
            cells_data = _matrix_row_cells(row, report, role_columns, annotations, product)
            cells = "".join(
                f'<td data-col="{esc(c)}">{_matrix_cell_html(cells_data.get(c, {}))}</td>'
                for c in all_cols
            )
            # 品牌列链摘要页
            brand_val = row.get("brand") or (product or {}).get("brand") or ""
            model_val = row.get("model") or (product or {}).get("model") or ""
            if cid:
                brand_link = f'<a href="{esc(_product_digest_href(cid, 1))}">{esc(brand_val)}</a>'
                model_link = f'<a href="{esc(_product_digest_href(cid, 1))}">{esc(model_val)}</a>'
                cells = cells.replace(
                    f'<td data-col="brand">{_matrix_cell_html(cells_data.get("brand", {}))}</td>',
                    f'<td data-col="brand">{brand_link}</td>',
                    1,
                )
                cells = cells.replace(
                    f'<td data-col="model">{_matrix_cell_html(cells_data.get("model", {}))}</td>',
                    f'<td data-col="model">{model_link}</td>',
                    1,
                )
            compare_href = f"../compare/{_category_filename(cat)}?role=cost"
            compare_link = f'<a href="{esc(compare_href)}">同品类对比</a>'
            digest_link = f'<a href="{esc(_product_digest_href(cid, 1))}">成本摘要</a>' if cid else ""
            rows_html.append(f"<tr>{cells}<td>{compare_link}</td><td>{digest_link}</td></tr>")
        table = (
            f'<table class="matrix-table matrix-role-table"><thead><tr>{header}</tr></thead>'
            f'<tbody>{"".join(rows_html)}</tbody></table>'
        )
        disp = "" if i == 0 else ' style="display:none"'
        panels.append(f'<div class="matrix-panel" data-matrix-panel="{i}"{disp}>{table}</div>')

    role_cfg_json = json.dumps(role_columns, ensure_ascii=False)
    body = f"""
<h1 class="section-title">成本竞品矩阵</h1>
<p class="sort-hint">默认成本工程师视角；切换角色查看不同列集；产品名链入成本摘要页。</p>
{_matrix_role_bar(role_columns, "cost")}
<div class="matrix-tabs">{"".join(tabs)}</div>
<div class="matrix-panels matrix-panels-role">{"".join(panels)}</div>
"""
    extra = f'<script>window.MATRIX_ROLE_COLUMNS={role_cfg_json};</script>'
    (out / "index.html").write_text(
        page_shell("竞品矩阵", body, active_nav="matrix", depth=1, extra_head=extra),
        encoding="utf-8",
    )


def build_compare_pages() -> None:
    """每品类一张成本对比大表：列=产品（链摘要页），行=成本参数。"""
    out = SITE_DIR / "compare"
    out.mkdir(parents=True, exist_ok=True)
    annotations = _load_field_annotations()

    compare_sources = []
    if COMPARE_DATA_DIR.exists():
        compare_sources = sorted(COMPARE_DATA_DIR.glob("*.json"))
    if not compare_sources and MATRIX_DIR.exists():
        compare_sources = sorted(MATRIX_DIR.glob("*.json"))

    for path in compare_sources:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cat = data.get("category", path.stem)
        param_rows = data.get("param_rows") or []
        products = data.get("products") or []
        if not products and data.get("rows"):
            # 降级：旧 matrix JSON
            continue
        if not products:
            continue

        head = "<th>参数</th>" + "".join(
            f'<th><a href="../products/{esc(p["canonical_id"])}.html?role=cost">'
            f'{esc((p.get("brand") or "") + " " + (p.get("model") or "")).strip() or p["canonical_id"]}</a></th>'
            for p in products
        )
        body_rows = []
        for param in param_rows:
            label = MATRIX_COLUMN_LABELS.get(param, param)
            ann = _field_annotation(annotations, param)
            label_html = f'<span class="annot-label" title="{esc(ann)}">{esc(label)}</span>' if ann else esc(label)
            tds = f"<td class='param-name'>{label_html}</td>"
            for p in products:
                cell = (p.get("cells") or {}).get(param, {})
                if not cell and data.get("rows"):
                    row_item = next((r for r in data["rows"] if r.get("param") == param), None)
                    if row_item:
                        cell = (row_item.get("cells") or {}).get(p["canonical_id"], {})
                val = (cell or {}).get("value") or ""
                if not val:
                    val_html = '<span class="matrix-hint">待补充</span>'
                else:
                    val_html = _matrix_cell_html(cell)
                tds += f"<td>{val_html}</td>"
            body_rows.append(f"<tr>{tds}</tr>")

        table = (
            f'<table class="compare-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table>'
        )
        matrix_href = "../matrix/index.html?role=cost"
        body = f"""
<h1 class="section-title">{esc(cat)} · 成本参数对比</h1>
<p class="sort-hint">列=产品（链成本摘要页），行=成本关注参数；点击单元格展开证据。</p>
<p><a href="{esc(matrix_href)}">← 返回成本矩阵</a></p>
<div class="compare-wrap">{table}</div>
"""
        (out / _category_filename(cat)).write_text(
            page_shell(f"{cat} 对比", body, active_nav="matrix", depth=2),
            encoding="utf-8",
        )


def build_product_digest_pages() -> None:
    """产品成本摘要页：BOM 全表 + 信源层 + 链报告深页。"""
    out = SITE_DIR / "products"
    out.mkdir(parents=True, exist_ok=True)
    if not PRODUCTS_DIR.exists():
        return

    for path in sorted(PRODUCTS_DIR.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            product = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cid = product["canonical_id"]
        brand = product.get("brand", "")
        model = product.get("model", "")
        snap = product.get("cost_snapshot") or {}
        bom = product.get("bom_table") or []
        layer_refs = product.get("layer_refs") or {}

        # 伪造 record 供 BOM 渲染
        fake_record = {
            "id": snap.get("best_report_id") or "",
            "views": {"cost": {"bom_table": bom, "summary_image_urls": product.get("summary_image_urls") or []}},
        }

        layer_badges = "".join(
            f'<span class="source-badge source-{esc(layer)}">{esc(layer)}</span>'
            for layer, refs in layer_refs.items() if refs
        )
        price_txt = "待补充"
        if snap.get("price_cny") is not None:
            price_txt = f"¥{snap['price_cny']}"
            if snap.get("price_layer") == "channel":
                price_txt += " (渠道)"
        channel_url = snap.get("channel_url") or ""
        channel_link = (
            f' <a href="{esc(channel_url)}" target="_blank" rel="noopener">渠道页</a>'
            if channel_url else ""
        )

        report_links = []
        for rid in product.get("report_ids") or []:
            report_links.append(f'<a href="../reports/{esc(rid)}.html?role=cost&from=product">拆解报告 {esc(rid)}</a>')
        for vid in product.get("video_ids") or []:
            report_links.append(f'<a href="../videos/{esc(vid)}.html?role=cost">拆解视频 {esc(vid)}</a>')

        compare_href = f"../compare/{_category_filename(product.get('category', ''))}?role=cost"
        matrix_href = "../matrix/index.html?role=cost"

        cost_rows = [
            ("主控芯片", snap.get("main_chip")),
            ("PMIC", snap.get("pmic_case")),
            ("耳机电池", snap.get("battery_ear")),
            ("仓电池", snap.get("battery_case")),
            ("喇叭", snap.get("speaker")),
            ("材料", snap.get("materials")),
            ("重量", snap.get("weight_g")),
            ("IP", snap.get("ip_rating")),
            ("蓝牙", snap.get("bluetooth")),
            ("BOM行数", snap.get("bom_row_count")),
            ("售价", price_txt),
        ]
        snapshot_table = "<table class='spec-table'><tbody>" + "".join(
            f"<tr><td>{esc(k)}</td><td>{esc(str(v) if v is not None else '—')}</td></tr>"
            for k, v in cost_rows
        ) + "</tbody></table>"

        body = f"""
<div class="detail-header">
  <div>{category_tag(product.get('category',''))}</div>
  <h1>{esc(brand)} {esc(model)}</h1>
  <div class="meta-row">
    <span>品类：{esc(product.get('category',''))}</span>
    <span>信源：{layer_badges or '技术层'}</span>
    <span>成本完整度：{int((snap.get('data_completeness') or 0) * 100)}%</span>
  </div>
  <p class="sort-hint">产品成本摘要 · 数据融合自拆解报告（技术层）{channel_link}</p>
  <p>
    <a href="{esc(matrix_href)}">← 成本矩阵</a> ·
    <a href="{esc(compare_href)}">同品类对比</a>
  </p>
</div>

<section class="view-section" id="section-cost" data-section="cost">
  <h2>成本快照</h2>
  {snapshot_table}
</section>

<section class="view-section" id="section-bom" data-section="cost">
  <h2>物料清单（BOM）</h2>
  {_bom_table_html(bom, fake_record)}
  {_summary_images_html(product.get("summary_image_urls") or [])}
</section>

<section class="view-section">
  <h2>关联情报</h2>
  <p>{' · '.join(report_links) or '暂无关联报告'}</p>
</section>

<details class="pm-fold">
  <summary>市场信息（折叠）</summary>
  <p class="sort-hint">PM 透镜字段见拆解报告详情页。</p>
</details>
"""
        title = f"{brand} {model}".strip() or cid
        (out / f"{cid}.html").write_text(
            page_shell(title, body, active_nav="matrix", depth=1),
            encoding="utf-8",
        )


def _run_search_index() -> None:
    script = ROOT / "scripts" / "build_search_index.py"
    subprocess.run([sys.executable, str(script)], check=True, cwd=str(ROOT))


def _copy_search_index() -> None:
    src = DATA_DIR / "search-index.json"
    if not src.exists():
        return
    dest_dir = SITE_DIR / "data"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "search-index.json"
    dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> None:
    _run_search_index()
    reports = [merge_price_into_record(r) for r in load_all_records("report")]
    videos = load_all_records("video")
    idx = load_index()
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    (SITE_DIR / ".nojekyll").touch()
    _copy_search_index()
    build_index(reports, videos, idx)
    build_list_page("report", reports, "拆解报告", "reports")
    build_list_page("video", videos, "拆解视频", "videos")
    build_matrix_pages()
    build_compare_pages()
    build_product_digest_pages()

    about = f"""
<div class="about-content">
<h1>关于本站 V4</h1>
<p><strong>主用户：成本工程师。</strong>默认视角为成本透镜，优先展示 BOM/芯片/电池/PMIC 等同品类对比参数。</p>
<p>信息架构：首页 → <a href="matrix/index.html?role=cost">成本矩阵</a> → <a href="compare/开放式耳机.html">同品类大表</a> → 产品成本摘要 → 拆解报告深页 → 52audio 原文。</p>
<p>四层信源：技术层（52audio 拆解，已接入）· 渠道层（电商现价，CSV 导入）· 官方层 · 评测层（预留）。</p>
<p>数据：报告 {len(reports)} 条，视频 {len(videos)} 条。最后日更：{esc(str(idx.get('last_daily_crawl_at') or idx.get('last_backfill_at') or '—'))}</p>
</div>
"""
    (SITE_DIR / "about.html").write_text(page_shell("关于本站", about, active_nav="about", depth=0), encoding="utf-8")
    print(f"[build_site] V4 完成：{len(reports)} 报告，{len(videos)} 视频，产品摘要页已生成")


if __name__ == "__main__":
    main()
