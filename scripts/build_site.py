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
    return f"""<div class="card" {_card_data_attrs(v, "video")}>
  <div class="type-flag">拆解视频</div>
  <h4><a href="{href}">{esc(v.get('product_title', v.get('title','')))}</a></h4>
  <div class="meta">
    <span>{esc(v.get('published_at',''))}</span>
    <span>发布者：{esc(v.get('publisher','') or '未知')}</span>
    <span>平台：{esc(v.get('source_site','') or '未知')}</span>
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

{_section('A · 产品与市场', 'market', f'''
{field_with_badge("定位摘要", m.get('positioning_summary') or '', get_field_evidence(r, 'views.market.positioning_summary') or 'text')}
{field_with_badge("上市时间", m.get('launch_date') or '未识别', get_field_evidence(r, 'views.market.launch_date') or 'text')}
{collapsible_list("卖点", m.get('selling_points', []), r, 'market')}
{collapsible_list("使用场景", m.get('scenarios', []), r, 'market')}
''')}

{_section('B · 成本与 BOM', 'cost', f'''
{collapsible_list("主要部件", v.get('cost', {}).get('major_parts', []), r, 'cost')}
<div class="sub"><b>芯片/模组</b>{_chip_table(v.get('cost', {}).get('chip_modules', []), r)}</div>
{collapsible_list("包装/附件", v.get('cost', {}).get('packaging_notes', []), r, 'cost')}
{collapsible_list("工艺线索", v.get('cost', {}).get('process_hints', []), r, 'cost')}
''')}

{_section('C · 结构与材料', 'structure', f'''
{field_with_badge("形态", v.get('structure', {}).get('form_factor') or '', 'text')}
{field_with_badge("佩戴类型", v.get('structure', {}).get('earbud_type') or '未识别', 'text')}
{field_with_badge("防护等级", v.get('structure', {}).get('ip_rating') or '未识别', 'text')}
{field_with_badge("重量", v.get('structure', {}).get('weight_g') or '未识别', 'text')}
{collapsible_list("材料", v.get('structure', {}).get('materials', []), r, 'structure')}
{collapsible_list("内部结构", v.get('structure', {}).get('internal_structure', []), r, 'structure')}
{collapsible_list("佩戴/结构", v.get('structure', {}).get('wear_design', []), r, 'structure')}
{collapsible_list("关键图", [img.get('url','') for img in v.get('structure', {}).get('key_image_urls', []) if img.get('url')], r, 'structure')}
''')}

{_section('D · 硬件规格', 'hardware', _specs_table(v.get('hardware', {}).get('specs', []), r))}

{_section('E · 软件与连接', 'software', f'''
{field_with_badge("蓝牙版本", v.get('software', {}).get('bluetooth_version') or '未识别', 'text')}
{collapsible_list("音频编码", v.get('software', {}).get('codecs', []), r, 'software')}
{collapsible_list("多点连接", v.get('software', {}).get('multipoint', []), r, 'software')}
{collapsible_list("App 功能", v.get('software', {}).get('app_features', []), r, 'software')}
{collapsible_list("OTA/固件", v.get('software', {}).get('ota_support', []), r, 'software')}
{collapsible_list("低延迟", v.get('software', {}).get('latency_notes', []), r, 'software')}
''')}
"""
    export_json = json.dumps(export_data_json(r), ensure_ascii=False)
    extra = (
        f'<script>window.ROLE_LENSES={json.dumps(ROLE_LENSES, ensure_ascii=False)};'
        f"window.EXPORT_DATA={export_json};</script>"
        f'<script src="../assets/export.js"></script>'
    )
    name = f"{r.get('brand','')} {r.get('model','')}".strip()
    (out_dir / f"{r['id']}.html").write_text(
        page_shell(name, body, active_nav="reports", depth=1, extra_head=extra),
        encoding="utf-8",
    )


def build_video_detail(v: dict, out_dir: Path) -> None:
    asr = load_video_asr(v["id"])
    asr_block = '<p class="empty-hint empty-ocr">转写状态：待 OCR（见独立 video-enrich 流程）</p>'
    if asr:
        asr_block = f'<details open><summary>视频转写摘要</summary><p>{esc(asr.get("summary",""))}</p></details>'

    pct = compute_completeness(v)
    embed = ""
    if v.get("video_embed_url"):
        embed = f'<div class="video-embed-wrap"><iframe src="{esc(v["video_embed_url"])}" allowfullscreen></iframe></div>'

    body = f"""
<div class="detail-header">
  {completeness_bar_html(pct)}
  {internal_compare_html(v)}
  <h1>{esc(v.get('product_title', v.get('title','')))}</h1>
  <div class="meta-row">
    <span>发布：{esc(v.get('published_at',''))}</span>
    <span>发布者：{esc(v.get('publisher','') or '未知')}</span>
    <span>平台：{esc(v.get('source_site','') or '未知')}</span>
    <span>ASR：{esc(v.get('asr_status','pending'))}</span>
  </div>
  <div class="original-link"><a href="{esc(v['url'])}" target="_blank" rel="noopener">查看 52audio 原文</a></div>
</div>
{embed}
<div class="panel">{asr_block}</div>
"""
    (out_dir / f"{v['id']}.html").write_text(page_shell(v.get("product_title", ""), body, active_nav="videos", depth=1), encoding="utf-8")


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
  <a class="entry-card" href="reports/index.html"><h3>拆解报告</h3><div class="count">{len(reports)}</div></a>
  <a class="entry-card" href="videos/index.html"><h3>拆解视频</h3><div class="count">{len(videos)}</div></a>
  <a class="entry-card entry-card-matrix" href="matrix/index.html"><h3>竞品矩阵</h3><div class="count">{matrix_count or '—'}</div><p>按品类横向对比关键参数</p></a>
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
    card_fn = report_card if kind == "report" else video_card
    cards = "\n".join(card_fn(i, 1) for i in sorted(items, key=lambda x: x.get("published_at", ""), reverse=True))
    cards = cards or '<p class="empty-hint">暂无</p>'
    index_rel = "../data/search-index.json"
    body = (
        f'<h1 class="section-title">{esc(title)}（{len(items)} 条）</h1>'
        f"{search_toolbar_html(kind, brands, index_rel)}"
        f'<div class="filter-bar">{filters}</div>'
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

    tabs = []
    panels = []
    col_labels = {
        "price_cny": "售价",
        "launch_date": "上市",
        "codecs": "编码",
        "bluetooth": "蓝牙",
        "major_chips": "芯片",
        "selling_point_tags": "卖点标签",
        "data_completeness": "完整度",
        "品牌": "品牌",
        "型号": "型号",
        "发布时间": "发布",
        "售价": "售价",
        "芯片": "芯片",
    }
    for i, mat in enumerate(matrices):
        cat = mat.get("category", f"品类{i+1}")
        active = "active" if i == 0 else ""
        tabs.append(f'<button type="button" class="matrix-tab {active}" data-matrix-tab="{i}">{esc(cat)}</button>')
        cols = mat.get("columns", [])
        display_cols = ["brand", "model"] + [c for c in cols if c not in ("brand", "model")]
        header = "".join(f"<th>{esc(col_labels.get(c, c))}</th>" for c in display_cols) + "<th>详情</th>"
        rows_html = []
        for row in mat.get("rows", []):
            cells = "".join(f"<td>{esc(_matrix_cell(row.get(c)))}</td>" for c in display_cols)
            rid = row.get("id") or row.get("report_id") or ""
            link = f'<a href="../reports/{esc(rid)}.html">报告</a>' if rid else ""
            rows_html.append(f"<tr>{cells}<td>{link}</td></tr>")
        table = (
            f'<table class="matrix-table"><thead><tr>{header}</tr></thead>'
            f'<tbody>{"".join(rows_html)}</tbody></table>'
        )
        disp = "" if i == 0 else ' style="display:none"'
        panels.append(f'<div class="matrix-panel" data-matrix-panel="{i}"{disp}>{table}</div>')

    body = f"""
<h1 class="section-title">竞品矩阵</h1>
<p class="sort-hint">按品类分 tab 横向对比；数据来源于已入库拆解报告关键字段摘要。</p>
<div class="matrix-tabs">{"".join(tabs)}</div>
<div class="matrix-panels">{"".join(panels)}</div>
"""
    (out / "index.html").write_text(page_shell("竞品矩阵", body, active_nav="matrix", depth=1), encoding="utf-8")


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
    _copy_search_index()
    build_index(reports, videos, idx)
    build_list_page("report", reports, "拆解报告", "reports")
    build_list_page("video", videos, "拆解视频", "videos")
    build_matrix_pages()

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
