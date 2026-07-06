"""v2 静态站点：父级列表 + 子级五区块角色透镜（无原文 HTML 转载）。"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
    "pm": ["brand", "model", "category", "selling_point_tags", "scenarios",
           "launch_date", "price_cny", "data_completeness"],
    "cost": ["main_chip", "battery", "pmic", "case_charging", "bom_rows", "packaging"],
    "structure": ["form_factor", "materials", "ip_rating", "weight_g", "dimensions", "earbud_type"],
    "hardware": ["bluetooth", "codecs", "battery_mah", "charge_interface", "certifications"],
    "software": ["bluetooth_version", "codecs_sw", "multipoint", "app", "ota", "latency"],
}

MATRIX_COLUMN_LABELS: dict[str, str] = {
    "brand": "品牌", "model": "型号", "category": "品类",
    "selling_point_tags": "卖点标签", "scenarios": "场景",
    "launch_date": "上市", "price_cny": "售价", "data_completeness": "数据完整度",
    "main_chip": "主控芯片", "battery": "电池", "pmic": "PMIC",
    "case_charging": "仓充电", "bom_rows": "BOM行数", "packaging": "包装",
    "form_factor": "形态", "materials": "材质", "ip_rating": "IP",
    "weight_g": "重量", "dimensions": "尺寸", "earbud_type": "earbud_type",
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
    fields = annotations.get("fields") or annotations
    if isinstance(fields, dict):
        item = fields.get(field_key)
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            return item.get("desc") or item.get("annotation") or item.get("label") or ""
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


def _enrich_row_from_report(row: dict, report: dict | None) -> dict[str, dict]:
    """返回 {col_key: {"value": str, "evidence": str}}，缺字段降级为空。"""
    v = (report or {}).get("views") or {}
    market = v.get("market", {})
    cost = v.get("cost", {})
    structure = v.get("structure", {})
    hardware = v.get("hardware", {})
    software = v.get("software", {})
    bom = cost.get("bom_table") or []
    specs = hardware.get("specs") or []

    def cell(val: str, ev: str = "") -> dict:
        return {"value": val or "", "evidence": ev or ""}

    enriched: dict[str, dict] = {}

    enriched["category"] = cell((report or {}).get("category") or row.get("category") or "")
    scen = market.get("scenarios") or []
    enriched["scenarios"] = cell("、".join(str(s) for s in scen if s))

    # 主控芯片：优先 chip_modules 中 component 含 主控/MCU/SoC/蓝牙音频
    chips = cost.get("chip_modules") or []
    main_chip, main_chip_ev = "", ""
    for c in chips:
        comp = (c.get("component") or c.get("part") or "")
        model = c.get("model") or ""
        if any(k in comp for k in ("主控", "MCU", "SoC", "蓝牙", "音频")):
            main_chip = model or comp
            main_chip_ev = _ev_text(c)
            break
    if not main_chip and chips:
        main_chip = chips[0].get("model") or chips[0].get("part") or ""
        main_chip_ev = _ev_text(chips[0])
    if not main_chip and row.get("major_chips"):
        main_chip = row["major_chips"][0]
    enriched["main_chip"] = cell(main_chip, main_chip_ev)

    # 电池：bom_table component 含 电池
    bat, bat_ev = "", ""
    for b in bom:
        if "电池" in (b.get("component") or ""):
            bat = f"{b.get('brand','')} {b.get('model','')}".strip() or b.get("component", "")
            bat_ev = _ev_text(b)
            break
    if not bat:
        for s in specs:
            if s.get("param") == "电池容量":
                bat = f"{s.get('value','')} {s.get('unit','')}".strip()
                bat_ev = s.get("source_ref") or ""
                break
    enriched["battery"] = cell(bat, bat_ev)

    # PMIC / 保护 IC
    pmic, pmic_ev = "", ""
    for b in bom:
        comp = b.get("component") or ""
        if any(k in comp for k in ("PMIC", "保护", "电源管理", "PMU", "PMC", "过压")):
            pmic = f"{b.get('brand','')} {b.get('model','')}".strip() or comp
            pmic_ev = _ev_text(b)
            break
    enriched["pmic"] = cell(pmic, pmic_ev)

    # 仓充电：specs 充电接口（取第一个）
    case_chg, case_chg_ev = "", ""
    for s in specs:
        if s.get("param") == "充电接口":
            case_chg = s.get("value") or s.get("model") or ""
            case_chg_ev = s.get("source_ref") or ""
            break
    enriched["case_charging"] = cell(case_chg, case_chg_ev)
    enriched["bom_rows"] = cell(str(len(bom)) if bom else "")
    pkg = cost.get("packaging_notes") or []
    pkg_first = pkg[0] if pkg else None
    enriched["packaging"] = cell(
        pkg_first if isinstance(pkg_first, str) else (pkg_first.get("value") if isinstance(pkg_first, dict) else ""),
        _ev_text(pkg_first) if pkg_first else "",
    )

    # structure
    enriched["form_factor"] = cell(structure.get("form_factor") or "")
    mats = structure.get("materials") or []
    enriched["materials"] = cell("、".join(
        m if isinstance(m, str) else (m.get("value") or "") for m in mats))
    ip_ev = structure.get("ip_rating_evidence") or {}
    enriched["ip_rating"] = cell(structure.get("ip_rating") or "",
                                 ip_ev.get("source_text", "") if isinstance(ip_ev, dict) else "")
    w_ev = structure.get("weight_evidence") or {}
    enriched["weight_g"] = cell(str(structure.get("weight_g") or ""),
                                w_ev.get("source_text", "") if isinstance(w_ev, dict) else "")
    dims = structure.get("dimensions") or []
    enriched["dimensions"] = cell("、".join(d for d in dims if isinstance(d, str))[:80])
    enriched["earbud_type"] = cell(structure.get("earbud_type") or "")

    # hardware / software
    bt_ev = software.get("bluetooth_evidence") or {}
    enriched["bluetooth"] = cell(
        software.get("bluetooth_version") or row.get("bluetooth") or "",
        bt_ev.get("source_text", "") if isinstance(bt_ev, dict) else "")
    codec_vals = _codec_values(software.get("codecs")) or _codec_values(row.get("codecs"))
    enriched["codecs"] = cell("、".join(codec_vals))
    bat_mah, bat_mah_ev = "", ""
    for s in specs:
        if s.get("param") == "电池容量":
            bat_mah = f"{s.get('value','')} {s.get('unit','')}".strip()
            bat_mah_ev = s.get("source_ref") or ""
            break
    enriched["battery_mah"] = cell(bat_mah, bat_mah_ev)
    enriched["charge_interface"] = cell(case_chg, case_chg_ev)
    certs = []
    for s in specs:
        if s.get("param") == "标记/认证":
            val = s.get("value") or ""
            if val and val not in certs:
                certs.append(val[:40])
    enriched["certifications"] = cell("、".join(certs)[:80])

    enriched["bluetooth_version"] = enriched["bluetooth"]
    enriched["codecs_sw"] = enriched["codecs"]

    def first_val(items):
        if not items:
            return "", ""
        f = items[0]
        if isinstance(f, str):
            return f, ""
        if isinstance(f, dict):
            return f.get("value") or f.get("text") or "", _ev_text(f)
        return "", ""
    mp_v, mp_e = first_val(software.get("multipoint"))
    enriched["multipoint"] = cell(mp_v, mp_e)
    app_v = software.get("app_name") or ""
    app_e = ""
    if not app_v:
        app_v, app_e = first_val(software.get("app_features"))
    enriched["app"] = cell(app_v, app_e)
    ota_v, ota_e = first_val(software.get("ota_support"))
    enriched["ota"] = cell(ota_v, ota_e)
    lat_v, lat_e = first_val(software.get("latency_notes"))
    enriched["latency"] = cell(lat_v, lat_e)

    return enriched


def _matrix_row_cells(row: dict, report: dict | None, role_columns: dict[str, list[str]],
                      annotations: dict) -> dict[str, dict]:
    """合并 matrix row 基础字段 + 报告富化字段，返回 {col_key: {value, evidence}}。"""
    enriched = _enrich_row_from_report(row, report)
    # 基础字段来自 matrix row
    dc = row.get("data_completeness")
    if isinstance(dc, float) and 0 < dc <= 1:
        dc_txt = f"{int(dc * 100)}%"
    else:
        dc_txt = str(dc) if dc is not None else ""
    base = {
        "brand": {"value": row.get("brand") or "", "evidence": ""},
        "model": {"value": row.get("model") or "", "evidence": ""},
        "selling_point_tags": {"value": "、".join(row.get("selling_point_tags") or []), "evidence": ""},
        "launch_date": {"value": row.get("launch_date") or "", "evidence": ""},
        "price_cny": {"value": f"¥{row['price_cny']}" if row.get("price_cny") is not None else "", "evidence": ""},
        "data_completeness": {"value": dc_txt, "evidence": ""},
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


def _role_lens_html(default_role: str = "pm") -> str:
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

{_role_lens_html()}
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

{_role_lens_html()}
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
  <a class="entry-card entry-card-matrix" href="matrix/index.html"><h3>竞品矩阵</h3><div class="count">{matrix_count or '—'}</div><p>按品类横向对比关键参数（角色透镜）</p></a>
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
        '<p class="matrix-entry-link"><a href="../matrix/index.html">查看聚合矩阵 →</a>　'
        '<a href="../compare/开放式耳机.html">同品类对比示例</a></p>'
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


def _matrix_role_bar(role_columns: dict[str, list[str]]) -> str:
    buttons = []
    for i, (key, cols) in enumerate(role_columns.items()):
        label = ROLE_LENSES.get(key, {}).get("label", key)
        active = "active" if i == 0 else ""
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
        ) + "<th>对比</th><th>详情</th>"
        rows_html = []
        for row in rows:
            cid = row.get("canonical_id") or ""
            report = reports_by_cid.get(cid)
            cells_data = _matrix_row_cells(row, report, role_columns, annotations)
            cells = "".join(
                f'<td data-col="{esc(c)}">{_matrix_cell_html(cells_data.get(c, {}))}</td>'
                for c in all_cols
            )
            compare_href = f"../compare/{_category_filename(cat)}"
            compare_link = f'<a href="{esc(compare_href)}">同品类对比</a>'
            rid = (report or {}).get("id") or row.get("id") or row.get("report_id") or ""
            source = row.get("source") or ""
            src_badge = (
                f'<span class="source-badge source-{esc(source)}" title="数据来源">{esc(source)}</span>'
                if source
                else ""
            )
            if rid:
                detail_link = f'<a href="../reports/{esc(rid)}.html">报告</a>'
            elif row.get("has_video"):
                detail_link = '<span class="matrix-hint">仅视频</span>'
            else:
                detail_link = ""
            rows_html.append(
                f"<tr>{cells}<td>{compare_link}</td><td>{src_badge}{detail_link}</td></tr>"
            )
        table = (
            f'<table class="matrix-table matrix-role-table"><thead><tr>{header}</tr></thead>'
            f'<tbody>{"".join(rows_html)}</tbody></table>'
        )
        disp = "" if i == 0 else ' style="display:none"'
        panels.append(f'<div class="matrix-panel" data-matrix-panel="{i}"{disp}>{table}</div>')

    role_cfg_json = json.dumps(role_columns, ensure_ascii=False)
    body = f"""
<h1 class="section-title">竞品矩阵 · 角色透镜</h1>
<p class="sort-hint">切换角色查看不同列集；每行可进入同品类对比页；单元格可展开证据原文。</p>
{_matrix_role_bar(role_columns)}
<div class="matrix-tabs">{"".join(tabs)}</div>
<div class="matrix-panels matrix-panels-role">{"".join(panels)}</div>
"""
    extra = f'<script>window.MATRIX_ROLE_COLUMNS={role_cfg_json};</script>'
    (out / "index.html").write_text(
        page_shell("竞品矩阵", body, active_nav="matrix", depth=1, extra_head=extra),
        encoding="utf-8",
    )


def build_compare_pages() -> None:
    """每品类一张对比页：列=产品，行=参数，每格可展开 evidence。"""
    out = SITE_DIR / "compare"
    out.mkdir(parents=True, exist_ok=True)
    if not MATRIX_DIR.exists():
        return
    annotations = _load_field_annotations()
    role_columns = _matrix_role_columns(annotations)
    skip_cols = {"brand", "model", "data_completeness"}
    param_cols: list[str] = []
    for cols in role_columns.values():
        for c in cols:
            if c not in skip_cols and c not in param_cols:
                param_cols.append(c)

    reports_by_cid = _load_reports_by_canonical_id()

    for path in sorted(MATRIX_DIR.glob("*.json")):
        try:
            mat = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cat = mat.get("category", path.stem)
        rows = mat.get("rows", [])
        if not rows:
            continue
        products = []
        for row in rows:
            cid = row.get("canonical_id") or ""
            report = reports_by_cid.get(cid)
            cells_data = _matrix_row_cells(row, report, role_columns, annotations)
            rid = (report or {}).get("id") or row.get("id") or ""
            brand = row.get("brand") or ""
            model = row.get("model") or ""
            name = f"{brand} {model}".strip() or model or cid
            href = f"../reports/{esc(rid)}.html?role=pm" if rid else ""
            products.append({"name": name, "href": href, "cells": cells_data})

        head = "<th>参数</th>" + "".join(
            f'<th><a href="{esc(p["href"])}">{esc(p["name"])}</a></th>' if p["href"]
            else f'<th>{esc(p["name"])}</th>'
            for p in products
        )
        body_rows = []
        for col in param_cols:
            label = MATRIX_COLUMN_LABELS.get(col, col)
            ann = _field_annotation(annotations, col)
            label_html = f'<span class="annot-label" title="{esc(ann)}">{esc(label)}</span>' if ann else esc(label)
            tds = f"<td class='param-name'>{label_html}</td>"
            for p in products:
                cell = p["cells"].get(col, {})
                tds += f"<td>{_matrix_cell_html(cell)}</td>"
            body_rows.append(f"<tr>{tds}</tr>")

        table = (
            f'<table class="compare-table"><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody></table>'
        )
        matrix_href = "../matrix/index.html"
        body = f"""
<h1 class="section-title">{esc(cat)} · 同品类对比</h1>
<p class="sort-hint">列=产品，行=参数；点击单元格展开证据原文；产品名链入对应拆解报告。</p>
<p><a href="{esc(matrix_href)}">← 返回竞品矩阵</a></p>
<div class="compare-wrap">{table}</div>
"""
        (out / _category_filename(cat)).write_text(
            page_shell(f"{cat} 对比", body, active_nav="matrix", depth=2),
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

    about = f"""
<div class="about-content">
<h1>关于本站 v2</h1>
<p>按职能角色透镜展示拆解情报：产品经理看全量技术事实+市场信息；成本工程师看 BOM 相关区块；结构/硬件/软件各看本域。</p>
<p>数据：报告 {len(reports)} 条，视频 {len(videos)} 条。最后日更：{esc(str(idx.get('last_daily_crawl_at') or idx.get('last_backfill_at') or '—'))}</p>
<p>支持关键词搜索、品牌筛选、竞品矩阵、CSV 导出与数据完整度展示。</p>
</div>
"""
    (SITE_DIR / "about.html").write_text(page_shell("关于本站", about, active_nav="about", depth=0), encoding="utf-8")
    print(f"[build_site] v2 完成：{len(reports)} 报告，{len(videos)} 视频")


if __name__ == "__main__":
    main()
