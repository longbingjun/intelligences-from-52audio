"""静态站点生成脚本：读取 data/reports.json + data/videos.json，
预渲染出可以直接被 GitHub Pages（或本地双击打开）托管的纯静态 HTML 文件到 site/。

设计取舍：
- 不用任何前端构建工具（webpack/vite/node 等），纯 Python 字符串模板；
- 数据在构建时就"烤"进了 HTML 里（服务端渲染），双击打开 site/index.html
  即可看到真实内容，不依赖浏览器 fetch 本地 JSON（file:// 协议下会被
  Chrome 等浏览器的 CORS 策略拦截，这是纯静态站点在本地预览时的常见坑）；
- 客户端 JS（site/assets/app.js）只做"分类筛选"这种不需要网络请求的
  轻交互，进一步保证离线可用性。

用法：
    py -3 scripts/build_site.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.site_common import (  # noqa: E402
    SITE_TAGLINE,
    SITE_TITLE,
    category_tag,
    esc,
    ocr_status_badge,
    page_shell,
    sentiment_badge,
    truncate,
)

DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"


def load_data():
    reports = json.loads((DATA_DIR / "reports.json").read_text(encoding="utf-8")) if (DATA_DIR / "reports.json").exists() else {"items": []}
    videos = json.loads((DATA_DIR / "videos.json").read_text(encoding="utf-8")) if (DATA_DIR / "videos.json").exists() else {"items": []}
    queue = json.loads((DATA_DIR / "images_queue.json").read_text(encoding="utf-8")) if (DATA_DIR / "images_queue.json").exists() else {"items": []}
    return reports.get("items", []), videos.get("items", []), queue.get("items", [])


# ---------------------------------------------------------------------------
# 卡片渲染
# ---------------------------------------------------------------------------

def report_card(r: dict, depth: int) -> str:
    prefix = "../" * depth if depth else ""
    href = f"{prefix}reports/{r['id']}.html" if depth != 1 else f"{r['id']}.html"
    brand_model = f"{r.get('brand','')} {r.get('model','')}".strip() or r.get("title", "")
    return f"""<div class="card" data-category="{esc(r.get('category',''))}">
  <div class="type-flag">📄 拆解报告</div>
  <h4><a href="{href}">{esc(brand_model)}</a></h4>
  <div class="meta">
    <span>{esc(r.get('date',''))}</span>
    <span>作者：{esc(r.get('author','') or '未知')}</span>
  </div>
  <div>{category_tag(r.get('category',''))}</div>
  <div class="summary">{esc(truncate(r.get('summary',''), 90))}</div>
  <div class="card-footer">
    <a href="{href}">查看结构化详情 →</a>
  </div>
</div>"""


def video_card(v: dict, depth: int) -> str:
    prefix = "../" * depth if depth else ""
    href = f"{prefix}videos/{v['id']}.html" if depth != 1 else f"{v['id']}.html"
    return f"""<div class="card" data-category="{esc(v.get('category',''))}">
  <div class="type-flag">🎬 拆解视频</div>
  <h4><a href="{href}">{esc(v.get('product_title', v.get('title','')))}</a></h4>
  <div class="meta">
    <span>{esc(v.get('date',''))}</span>
    <span>发布者：{esc(v.get('publisher','') or '未知')}</span>
    <span>平台：{esc(v.get('source_site','') or '未知')}</span>
  </div>
  <div>{category_tag(v.get('category',''))}</div>
  <div class="card-footer">
    <a href="{href}">查看详情 →</a>
  </div>
</div>"""


def timeline_card(item: dict, depth: int) -> str:
    if item["type"] == "report":
        return report_card(item, depth)
    return video_card(item, depth)


# ---------------------------------------------------------------------------
# 首页
# ---------------------------------------------------------------------------

def build_index(reports: list[dict], videos: list[dict]):
    merged = sorted(reports + videos, key=lambda x: x.get("date", ""), reverse=True)[:12]
    timeline_html = "\n".join(timeline_card(item, depth=0) for item in merged) or '<p class="empty-hint">暂无数据</p>'

    body = f"""
<section class="hero">
  <h1>{esc(SITE_TITLE)}</h1>
  <p>{esc(SITE_TAGLINE)}</p>
  <div class="hero-stats">
    <div class="hero-stat"><div class="num">{len(reports)}</div><div class="label">拆解报告</div></div>
    <div class="hero-stat"><div class="num">{len(videos)}</div><div class="label">拆解视频</div></div>
    <div class="hero-stat"><div class="num">1</div><div class="label">已接入情报源</div></div>
  </div>
</section>

<div class="entry-grid">
  <a class="entry-card" href="reports/index.html">
    <h3>📄 拆解报告</h3>
    <div class="count">{len(reports)}</div>
    <p>逐一拆开耳机/音箱等音频设备，抽取卖点、部件结构与技术参数</p>
    进入板块 →
  </a>
  <a class="entry-card" href="videos/index.html">
    <h3>🎬 拆解视频</h3>
    <div class="count">{len(videos)}</div>
    <p>B站/YouTube 等平台的拆解视频线索汇总（结构化程度较轻）</p>
    进入板块 →
  </a>
</div>

<div class="section-title">🕒 最近更新</div>
<div class="card-grid">
{timeline_html}
</div>
"""
    (SITE_DIR / "index.html").write_text(page_shell("首页", body, active_nav="home", depth=0), encoding="utf-8")


# ---------------------------------------------------------------------------
# 拆解报告：列表 + 详情
# ---------------------------------------------------------------------------

def build_reports(reports: list[dict], queue_by_article: dict[str, list[dict]]):
    out_dir = SITE_DIR / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    categories = sorted({r.get("category", "") for r in reports})
    filter_buttons = ['<button class="filter-btn active" data-filter="__all__">全部</button>']
    for c in categories:
        filter_buttons.append(f'<button class="filter-btn" data-filter="{esc(c)}">{esc(c)}</button>')

    cards_html = "\n".join(report_card(r, depth=1) for r in reports) or '<p class="empty-hint">暂无数据，请先运行 scripts/crawl.py 抓取</p>'

    body = f"""
<h1 class="section-title" style="margin-top:0">📄 拆解报告（共 {len(reports)} 条，按日期倒序）</h1>
<div class="filter-bar">{''.join(filter_buttons)}</div>
<div class="card-grid">
{cards_html}
</div>
"""
    (out_dir / "index.html").write_text(page_shell("拆解报告", body, active_nav="reports", depth=1), encoding="utf-8")

    for r in reports:
        build_report_detail(r, out_dir, queue_by_article.get(r["url"], []))


def _render_selling_points(points: list[dict]) -> str:
    if not points:
        return '<p class="empty-hint">未抽取到明显的卖点候选句（可能正文较短，或未命中关键词库）。</p>'
    blocks = []
    for p in points:
        kws = "".join(f"<span>{esc(k)}</span>" for k in p.get("matched_keywords", []))
        sentiment_txt = f"情感分：{p['sentiment']}　" if p.get("sentiment") is not None else ""
        blocks.append(
            f"""<div class="selling-point">
  {esc(p.get('text',''))}
  <div class="kw">{sentiment_badge(p.get('sentiment_label','neutral'))} {sentiment_txt}命中关键词：{kws}</div>
</div>"""
        )
    return "\n".join(blocks)


def _render_components(components: list[dict], images: list[dict], title: str) -> str:
    if not components:
        return f'<p class="empty-hint">未识别到{esc(title)}。</p>'
    image_by_index = {img["index"]: img for img in images}
    blocks = []
    for c in components:
        mention_html = []
        for m in c.get("mentions", [])[:6]:
            img_html = ""
            img_idx = m.get("image_index")
            if img_idx is not None and img_idx in image_by_index:
                img_html = f'<div style="margin-top:6px"><img src="{esc(image_by_index[img_idx]["url"])}" style="max-width:220px;border-radius:8px" loading="lazy"/></div>'
            heading = f'<span class="heading-tag">来自小节：{esc(m["heading"])}</span>' if m.get("heading") else ""
            mention_html.append(f'<div class="mention">{heading}{esc(m.get("text",""))}{img_html}</div>')
        blocks.append(
            f"""<div class="component-group">
  <div class="component-name">🔧 {esc(c['name'])}　<span style="color:#94a3b8;font-weight:400;font-size:12.5px">({len(c.get('mentions',[]))} 处相关描述)</span></div>
  {''.join(mention_html)}
</div>"""
        )
    return "\n".join(blocks)


def _render_spec_list(items: list[str], empty_text: str) -> str:
    if not items:
        return f'<p class="empty-hint">{esc(empty_text)}</p>'
    lis = "".join(f"<li>{esc(i)}</li>" for i in items)
    return f"<ul>{lis}</ul>"


def _render_ocr_queue(entries: list[dict]) -> str:
    if not entries:
        return '<p class="empty-hint">本文没有被判定为"文本密集型"的图片（或所有图片下载/分析失败）。</p>'
    blocks = []
    for e in entries:
        blocks.append(
            f"""<div class="ocr-queue-item">
  <img src="{esc(e['image_url'])}" loading="lazy" onerror="this.style.display='none'"/>
  <div>
    {ocr_status_badge('pending')}
    <div class="reason">判断依据：{esc(e.get('reason',''))}</div>
  </div>
</div>"""
        )
    return "\n".join(blocks)


def build_report_detail(r: dict, out_dir: Path, queue_entries: list[dict]):
    brand_model = f"{r.get('brand','')} {r.get('model','')}".strip() or r.get("title", "")
    tech = r.get("tech_specs", {})

    body = f"""
<div class="detail-header">
  <div>{category_tag(r.get('category',''))}</div>
  <h1>{esc(brand_model)}</h1>
  <div class="meta-row">
    <span>📅 {esc(r.get('date',''))}</span>
    <span>✍️ 作者：{esc(r.get('author','') or '未知')}</span>
    <span>🏷️ 品牌：{esc(r.get('brand','') or '未知')}</span>
    <span>🔩 型号：{esc(r.get('model','') or '未知')}</span>
  </div>
  <p>{esc(r.get('summary',''))}</p>
  <div class="original-link"><a href="{esc(r['url'])}" target="_blank" rel="noopener">↗ 查看原文（52audio.com）</a></div>
</div>

<div class="panel">
  <h2><span class="idx">a</span>产品及卖点特色（关键词命中 + 情感倾向，启发式抽取）</h2>
  {_render_selling_points(r.get('selling_points', []))}
</div>

<div class="panel">
  <h2><span class="idx">b</span>产品结构理解 · 主要部件</h2>
  {_render_components(r.get('components_major', []), r.get('images', []), '主要部件')}
</div>

<div class="panel">
  <h2><span class="idx">b</span>产品结构理解 · 次要部件</h2>
  {_render_components(r.get('components_minor', []), r.get('images', []), '次要部件')}
</div>

<div class="panel">
  <h2><span class="idx">d</span>技术数据</h2>
  <div class="spec-block"><div class="spec-label">充电方式</div>{_render_spec_list(tech.get('charging_method', []), '未在正文中识别到充电方式描述')}</div>
  <div class="spec-block"><div class="spec-label">充电接口</div>{_render_spec_list(tech.get('charging_port', []), '未在正文中识别到充电接口描述')}</div>
  <div class="spec-block"><div class="spec-label">说明书 / 包装内容物</div>{_render_spec_list(tech.get('manual_notes', []), '未在正文中识别到说明书相关描述')}</div>
  <div class="spec-block"><div class="spec-label">产品标记 / 认证 / 参数铭牌</div>{_render_spec_list(tech.get('product_markings', []), '未在正文中识别到产品标记/认证描述')}</div>
  <div class="spec-block"><div class="spec-label">其他疑似规格句（未归类，供人工复核）</div>{_render_spec_list(tech.get('raw_candidates', []), '无')}</div>
</div>

<div class="panel">
  <h2><span class="idx">🖼</span>图片 OCR 待办队列（框架先行：已判定为文本/表格密集型，等待接入真实 OCR 引擎）</h2>
  {_render_ocr_queue(queue_entries)}
</div>

<div class="panel">
  <h2><span class="idx">📰</span>原文完整正文（含全部图片，来自 52audio.com）</h2>
  <div class="article-content">{r.get('content_html','')}</div>
</div>
"""
    (out_dir / f"{r['id']}.html").write_text(page_shell(brand_model, body, active_nav="reports", depth=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 拆解视频：列表 + 详情
# ---------------------------------------------------------------------------

def build_videos(videos: list[dict]):
    out_dir = SITE_DIR / "videos"
    out_dir.mkdir(parents=True, exist_ok=True)

    categories = sorted({v.get("category", "") for v in videos})
    filter_buttons = ['<button class="filter-btn active" data-filter="__all__">全部</button>']
    for c in categories:
        filter_buttons.append(f'<button class="filter-btn" data-filter="{esc(c)}">{esc(c)}</button>')

    cards_html = "\n".join(video_card(v, depth=1) for v in videos) or '<p class="empty-hint">暂无数据</p>'

    body = f"""
<h1 class="section-title" style="margin-top:0">🎬 拆解视频（共 {len(videos)} 条，按日期倒序）</h1>
<p class="empty-hint">今天先做范围较小的次级子页面：发布者 / 发布日期 / 发布网站及地址 / 涉及产品标题。后续可接入 ASR 字幕提取做深度结构化，详见 docs/DESIGN.md。</p>
<div class="filter-bar">{''.join(filter_buttons)}</div>
<div class="card-grid">
{cards_html}
</div>
"""
    (out_dir / "index.html").write_text(page_shell("拆解视频", body, active_nav="videos", depth=1), encoding="utf-8")

    for v in videos:
        build_video_detail(v, out_dir)


def build_video_detail(v: dict, out_dir: Path):
    embed_html = ""
    if v.get("video_embed_url"):
        embed_html = f"""<div class="video-embed-wrap"><iframe src="{esc(v['video_embed_url'])}" allowfullscreen></iframe></div>"""

    body = f"""
<div class="detail-header">
  <div>{category_tag(v.get('category',''))}</div>
  <h1>{esc(v.get('product_title', v.get('title','')))}</h1>
  <div class="meta-row">
    <span>📅 发布日期：{esc(v.get('date',''))}</span>
    <span>📣 发布者：{esc(v.get('publisher','') or '未知')}</span>
    <span>🌐 发布网站：{esc(v.get('source_site','') or '未知')}</span>
    <span>🏷️ 品牌：{esc(v.get('brand','') or '未知')}</span>
  </div>
  <p>{esc(v.get('summary',''))}</p>
  <div class="original-link"><a href="{esc(v['url'])}" target="_blank" rel="noopener">↗ 查看原文（52audio.com）</a></div>
</div>

{embed_html}

<div class="panel">
  <h2>说明</h2>
  <p class="empty-hint">拆解视频板块目前只做轻量结构化（发布者/日期/平台/产品标题），完整的"结构化提取"（卖点/部件/技术参数）依赖字幕/语音转写，技术选型与接入建议见 <a href="../about.html">关于本站</a> 页面的 ASR 调研结论。</p>
</div>
"""
    (out_dir / f"{v['id']}.html").write_text(page_shell(v.get("product_title", v.get("title", "")), body, active_nav="videos", depth=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# 关于页
# ---------------------------------------------------------------------------

def build_about(stats: dict):
    body = f"""
<div class="about-content">
<h1>关于本站</h1>
<p>{esc(SITE_TAGLINE)}。本站是一个可扩展的"情报网站" MVP，第一个接入的情报源是
<a href="https://www.52audio.com/archives/category/teardowns" target="_blank" rel="noopener">我爱音频网「拆解」分类</a>。</p>

<h2>信息架构设计</h2>
<ul>
  <li><b>首页</b>：最近更新时间线（报告+视频混排，按日期倒序）+ 两个板块入口卡片，适合"每天扫一眼"的场景。</li>
  <li><b>拆解报告 / 拆解视频列表页</b>：按分类筛选 + 卡片网格，卡片展示品牌+型号+分类+摘要片段。</li>
  <li><b>详情页</b>：结构化信息（卖点、部件、技术参数、OCR待办）在前，原文完整正文在后，兼顾"快速获取结论"和"可追溯原文"。</li>
</ul>

<h2>产品分类体系</h2>
<p>分类体系写在 <code>sources/audio52/lexicon.py</code> 的 <code>CATEGORY_RULES</code> 里，
基于对真实拆解文章标题的调研得出，包含：真无线耳机TWS、开放式耳机、颈挂式蓝牙耳机、头戴式耳机、
骨传导耳机、有线耳机、智能手表、AI眼镜及穿戴设备、音箱及其他音频设备。规则是有序关键词表，
后续新增/调整品类不需要碰爬虫代码。</p>

<h2>OCR 框架说明</h2>
<p>图片处理管线（<code>core/extract/images.py</code>）对每张图片做"文本密集型 vs 图像密集型"的启发式判断
（Canny 边缘密度 + 颜色种类丰富度），判定为文本密集型的图片会被记录进 <code>data/images_queue.json</code>
待接入真实 OCR。当前环境未安装 Tesseract 可执行文件，识别能力处于"框架已搭建，未真正跑通"的状态，
后续接入建议见 README。</p>

<h2>拆解视频 / ASR 技术选型调研结论</h2>
<p>调研了 whisper.cpp、faster-whisper、yt-dlp 等开源方案，结论与接入建议详见项目 README「视频ASR调研」一节。</p>

<h2>数据统计</h2>
<p>拆解报告 {stats.get('total_reports', 0)} 条，拆解视频 {stats.get('total_videos', 0)} 条，
图片 OCR 待办队列 {stats.get('total_images_queue', 0)} 条。数据生成时间：{esc(stats.get('generated_at',''))}。</p>
</div>
"""
    (SITE_DIR / "about.html").write_text(page_shell("关于本站", body, active_nav="about", depth=0), encoding="utf-8")


def main():
    reports, videos, queue = load_data()

    queue_by_article: dict[str, list[dict]] = {}
    for q in queue:
        queue_by_article.setdefault(q.get("article_url", ""), []).append(q)

    build_index(reports, videos)
    build_reports(reports, queue_by_article)
    build_videos(videos)

    stats_path = DATA_DIR / "reports.json"
    generated_at = ""
    if stats_path.exists():
        generated_at = json.loads(stats_path.read_text(encoding="utf-8")).get("generated_at", "")
    build_about(
        {
            "total_reports": len(reports),
            "total_videos": len(videos),
            "total_images_queue": len(queue),
            "generated_at": generated_at,
        }
    )

    print(f"[build_site] 生成完成：{len(reports)} 篇报告，{len(videos)} 条视频，输出目录 {SITE_DIR}")


if __name__ == "__main__":
    main()
