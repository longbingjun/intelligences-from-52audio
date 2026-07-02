"""静态站点生成的公共小工具：HTML 转义、卡片/页面骨架模板。

刻意不引入 Jinja2 等模板引擎——页面结构简单，用 f-string 拼字符串完全够用，
减少一个依赖，也方便直接读代码就能看懂页面长什么样。
"""

from __future__ import annotations

import html
from datetime import datetime

SITE_TITLE = "52 情报站 · 音频拆解雷达"
SITE_TAGLINE = "每天追踪「我爱音频网」拆解报告与拆解视频，结构化呈现品牌卖点、部件与技术参数"


def esc(text: str) -> str:
    return html.escape(text or "", quote=True)


def fmt_date(d: str) -> str:
    return d if d else "日期未知"


def truncate(text: str, length: int = 80) -> str:
    text = (text or "").strip()
    if len(text) <= length:
        return text
    return text[:length].rstrip() + "…"


def sentiment_badge(label: str) -> str:
    mapping = {
        "positive": ("正向 / 强调型", "badge-positive"),
        "negative": ("负向 / 谨慎表述", "badge-negative"),
        "neutral": ("中性", "badge-neutral"),
    }
    text, cls = mapping.get(label, ("中性", "badge-neutral"))
    return f'<span class="badge {cls}">{text}</span>'


def ocr_status_badge(status: str) -> str:
    mapping = {
        "pending": ("待接入OCR", "badge-pending"),
        "done": ("已识别", "badge-done"),
        "done_empty": ("已识别(空)", "badge-neutral"),
        "failed": ("识别失败", "badge-negative"),
        "not_applicable": ("无需OCR", "badge-neutral"),
        "skipped": ("已跳过", "badge-neutral"),
    }
    text, cls = mapping.get(status, (status, "badge-neutral"))
    return f'<span class="badge {cls}">{text}</span>'


def page_shell(title: str, body: str, active_nav: str = "", extra_head: str = "", depth: int = 0) -> str:
    """depth: 相对 site/ 根目录的层级深度，用于计算 assets 相对路径（0=site/，1=site/reports/ 等）。"""

    prefix = "../" * depth

    def nav_item(href: str, label: str, key: str) -> str:
        cls = "nav-link active" if key == active_nav else "nav-link"
        return f'<a class="{cls}" href="{href}">{label}</a>'

    nav_html = "".join(
        [
            nav_item(f"{prefix}index.html", "首页", "home"),
            nav_item(f"{prefix}reports/index.html", "拆解报告", "reports"),
            nav_item(f"{prefix}videos/index.html", "拆解视频", "videos"),
            nav_item(f"{prefix}about.html", "关于本站", "about"),
        ]
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>{esc(title)} · {esc(SITE_TITLE)}</title>
<link rel="stylesheet" href="{prefix}assets/style.css" />
{extra_head}
</head>
<body>
<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="{prefix}index.html">📡 {esc(SITE_TITLE)}</a>
    <nav class="site-nav">{nav_html}</nav>
  </div>
</header>
<main class="site-main">
{body}
</main>
<footer class="site-footer">
  <p>数据来源：<a href="https://www.52audio.com/archives/category/teardowns" target="_blank" rel="noopener">我爱音频网 52audio.com「拆解」分类</a>，内容版权归原网站及作者所有，本站仅做结构化整理与内部研究用途。</p>
  <p>静态页面构建时间：{now}　|　情报网站 MVP · sources/audio52</p>
</footer>
<script src="{prefix}assets/app.js"></script>
</body>
</html>
"""


CATEGORY_COLORS = {
    "真无线耳机TWS": "#2563eb",
    "开放式耳机": "#0891b2",
    "颈挂式蓝牙耳机": "#7c3aed",
    "头戴式耳机": "#c2410c",
    "骨传导耳机": "#059669",
    "有线耳机": "#4338ca",
    "智能手表": "#b45309",
    "AI眼镜及穿戴设备": "#be185d",
    "音箱及其他音频设备": "#475569",
    "其他音频设备": "#64748b",
}


def category_tag(category: str) -> str:
    color = CATEGORY_COLORS.get(category, "#64748b")
    return f'<span class="tag" style="--tag-color:{color}">{esc(category)}</span>'
