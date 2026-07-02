"""v2 静态站点：父级列表 + 子级五区块角色透镜（无原文 HTML 转载）。"""

from __future__ import annotations

import json
import sys
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
from scripts.site_common import SITE_TAGLINE, SITE_TITLE, category_tag, esc, page_shell, truncate  # noqa: E402

SITE_DIR = ROOT / "site"

ROLE_LENSES = {
    "pm": {"label": "产品经理", "sections": ["market", "cost", "structure", "hardware", "software"]},
    "cost": {"label": "成本工程师", "sections": ["cost", "structure", "hardware", "software"]},
    "structure": {"label": "结构工程师", "sections": ["structure"]},
    "hardware": {"label": "硬件工程师", "sections": ["hardware"]},
    "software": {"label": "软件工程师", "sections": ["software"]},
}


def _list(items: list[str], empty: str = "暂无") -> str:
    if not items:
        return f'<p class="empty-hint">{esc(empty)}</p>'
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def _specs_table(specs: list[dict]) -> str:
    if not specs:
        return '<p class="empty-hint">暂无</p>'
    rows = []
    for s in specs:
        val = s.get("value") or s.get("model") or ""
        unit = s.get("unit") or ""
        rows.append(
            f"<tr><td>{esc(s.get('part',''))}</td><td>{esc(str(val))} {esc(unit)}</td>"
            f"<td>{esc(s.get('source_ref',''))}</td></tr>"
        )
    return f'<table class="spec-table"><thead><tr><th>部件</th><th>参数</th><th>来源</th></tr></thead><tbody>{"".join(rows)}</tbody></table>'


def _chip_table(chips: list[dict]) -> str:
    if not chips:
        return '<p class="empty-hint">暂无</p>'
    rows = "".join(
        f"<tr><td>{esc(c.get('part',''))}</td><td>{esc(c.get('model',''))}</td></tr>" for c in chips
    )
    return f'<table class="spec-table"><thead><tr><th>类型</th><th>型号</th></tr></thead><tbody>{rows}</tbody></table>'


def _role_lens_html(default_role: str = "pm") -> str:
    buttons = []
    for key, meta in ROLE_LENSES.items():
        active = "active" if key == default_role else ""
        buttons.append(f'<button type="button" class="lens-btn {active}" data-lens="{key}">{esc(meta["label"])}</button>')
    return f'<div class="lens-bar" id="role-lens">{"".join(buttons)}</div>'


def _section(title: str, section_id: str, body: str) -> str:
    return f'<section class="view-section" id="section-{section_id}" data-section="{section_id}"><h2>{esc(title)}</h2>{body}</section>'


def report_card(r: dict, depth: int) -> str:
    href = f"reports/{r['id']}.html" if depth == 0 else f"{r['id']}.html"
    brand_model = f"{r.get('brand','')} {r.get('model','')}".strip() or r.get("title", "")
    return f"""<div class="card" data-category="{esc(r.get('category',''))}">
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
    return f"""<div class="card" data-category="{esc(v.get('category',''))}">
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


def build_report_detail(r: dict, out_dir: Path) -> None:
    v = r.get("views", {})
    m = v.get("market", {})
    price = m.get("price_cny")
    price_txt = f"¥{price}" if price is not None else "待补充"
    if m.get("price_note"):
        price_txt += f"（{m['price_note']}）"

    body = f"""
<div class="detail-header">
  <div>{category_tag(r.get('category',''))}</div>
  <h1>{esc(r.get('brand',''))} {esc(r.get('model',''))}</h1>
  <div class="meta-row">
    <span>发布：{esc(r.get('published_at',''))}</span>
    <span>作者：{esc(r.get('author','') or '未知')}</span>
    <span>售价：{esc(price_txt)}</span>
  </div>
  <p>{esc(r.get('summary',''))}</p>
  <div class="original-link"><a href="{esc(r['url'])}" target="_blank" rel="noopener">查看 52audio 原文</a></div>
</div>

{_role_lens_html()}

{_section('A · 产品与市场', 'market', f'''
<p><b>定位摘要：</b>{esc(m.get('positioning_summary') or '暂无')}</p>
<p><b>上市时间：</b>{esc(m.get('launch_date') or '未识别')}</p>
<div class="sub"><b>卖点</b>{_list(m.get('selling_points', []))}</div>
<div class="sub"><b>使用场景</b>{_list(m.get('scenarios', []))}</div>
''')}

{_section('B · 成本与 BOM', 'cost', f'''
<div class="sub"><b>主要部件</b>{_list(v.get('cost', {}).get('major_parts', []))}</div>
<div class="sub"><b>芯片/模组</b>{_chip_table(v.get('cost', {}).get('chip_modules', []))}</div>
<div class="sub"><b>包装/附件</b>{_list(v.get('cost', {}).get('packaging_notes', []))}</div>
<div class="sub"><b>工艺线索</b>{_list(v.get('cost', {}).get('process_hints', []))}</div>
''')}

{_section('C · 结构与材料', 'structure', f'''
<p><b>形态：</b>{esc(v.get('structure', {}).get('form_factor') or '')}</p>
<p><b>防护等级：</b>{esc(v.get('structure', {}).get('ip_rating') or '未识别')}</p>
<p><b>重量：</b>{esc(v.get('structure', {}).get('weight_g') or '未识别')}</p>
<div class="sub"><b>材料</b>{_list(v.get('structure', {}).get('materials', []))}</div>
<div class="sub"><b>佩戴/结构</b>{_list(v.get('structure', {}).get('wear_design', []))}</div>
<div class="sub"><b>拆装描述</b>{_list(v.get('structure', {}).get('assembly_notes', []))}</div>
''')}

{_section('D · 硬件规格', 'hardware', _specs_table(v.get('hardware', {}).get('specs', [])))}

{_section('E · 软件与连接', 'software', f'''
<p><b>蓝牙版本：</b>{esc(v.get('software', {}).get('bluetooth_version') or '未识别')}</p>
<div class="sub"><b>音频编码</b>{_list(v.get('software', {}).get('codecs', []))}</div>
<div class="sub"><b>多点连接</b>{_list(v.get('software', {}).get('multipoint', []))}</div>
<div class="sub"><b>App 功能</b>{_list(v.get('software', {}).get('app_features', []))}</div>
<div class="sub"><b>OTA/固件</b>{_list(v.get('software', {}).get('ota_support', []))}</div>
<div class="sub"><b>低延迟</b>{_list(v.get('software', {}).get('latency_notes', []))}</div>
''')}
"""
    name = f"{r.get('brand','')} {r.get('model','')}".strip()
    (out_dir / f"{r['id']}.html").write_text(
        page_shell(name, body, active_nav="reports", depth=1, extra_head='<script>window.ROLE_LENSES=' + json.dumps(ROLE_LENSES) + ";</script>"),
        encoding="utf-8",
    )


def build_video_detail(v: dict, out_dir: Path) -> None:
    asr = load_video_asr(v["id"])
    asr_block = '<p class="empty-hint">转写状态：待处理（见独立 video-enrich 流程）</p>'
    if asr:
        asr_block = f'<details><summary>视频转写摘要</summary><p>{esc(asr.get("summary",""))}</p></details>'

    embed = ""
    if v.get("video_embed_url"):
        embed = f'<div class="video-embed-wrap"><iframe src="{esc(v["video_embed_url"])}" allowfullscreen></iframe></div>'

    body = f"""
<div class="detail-header">
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


def build_index(reports: list[dict], videos: list[dict]) -> None:
    merged = sorted(
        [{"type": "report", **r} for r in reports] + [{"type": "video", **v} for v in videos],
        key=lambda x: x.get("published_at", ""),
        reverse=True,
    )[:12]
    timeline = "\n".join(
        report_card(x, 0) if x["type"] == "report" else video_card(x, 0) for x in merged
    ) or '<p class="empty-hint">暂无数据</p>'

    body = f"""
<section class="hero">
  <h1>{esc(SITE_TITLE)}</h1>
  <p>{esc(SITE_TAGLINE)}</p>
  <div class="hero-stats">
    <div class="hero-stat"><div class="num">{len(reports)}</div><div class="label">拆解报告</div></div>
    <div class="hero-stat"><div class="num">{len(videos)}</div><div class="label">拆解视频</div></div>
  </div>
</section>
<div class="entry-grid">
  <a class="entry-card" href="reports/index.html"><h3>拆解报告</h3><div class="count">{len(reports)}</div></a>
  <a class="entry-card" href="videos/index.html"><h3>拆解视频</h3><div class="count">{len(videos)}</div></a>
</div>
<div class="section-title">最近更新</div>
<div class="card-grid">{timeline}</div>
"""
    (SITE_DIR / "index.html").write_text(page_shell("首页", body, active_nav="home", depth=0), encoding="utf-8")


def build_list_page(kind: str, items: list[dict], title: str, nav: str) -> None:
    out = SITE_DIR / ("reports" if kind == "report" else "videos")
    out.mkdir(parents=True, exist_ok=True)
    cats = sorted({i.get("category", "") for i in items})
    filters = '<button class="filter-btn active" data-filter="__all__">全部</button>'
    filters += "".join(f'<button class="filter-btn" data-filter="{esc(c)}">{esc(c)}</button>' for c in cats)
    card_fn = report_card if kind == "report" else video_card
    cards = "\n".join(card_fn(i, 1) for i in items) or '<p class="empty-hint">暂无</p>'
    body = f'<h1 class="section-title">{esc(title)}（{len(items)} 条）</h1><div class="filter-bar">{filters}</div><div class="card-grid">{cards}</div>'
    (out / "index.html").write_text(page_shell(title, body, active_nav=nav, depth=1), encoding="utf-8")
    for i in items:
        if kind == "report":
            build_report_detail(i, out)
        else:
            build_video_detail(i, out)


def main() -> None:
    reports = [merge_price_into_record(r) for r in load_all_records("report")]
    videos = load_all_records("video")
    idx = load_index()
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    build_index(reports, videos)
    build_list_page("report", reports, "拆解报告", "reports")
    build_list_page("video", videos, "拆解视频", "videos")

    about = f"""
<div class="about-content">
<h1>关于本站 v2</h1>
<p>按职能角色透镜展示拆解情报：产品经理看全量技术事实+市场信息；成本工程师看 BOM 相关区块；结构/硬件/软件各看本域。</p>
<p>数据：报告 {len(reports)} 条，视频 {len(videos)} 条。最后日更：{esc(str(idx.get('last_daily_crawl_at') or '—'))}</p>
</div>
"""
    (SITE_DIR / "about.html").write_text(page_shell("关于本站", about, active_nav="about", depth=0), encoding="utf-8")
    print(f"[build_site] v2 完成：{len(reports)} 报告，{len(videos)} 视频")


if __name__ == "__main__":
    main()
