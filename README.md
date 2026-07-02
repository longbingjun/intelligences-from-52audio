# 情报网站 MVP · 52audio 拆解情报雷达

一个可长期运行、可扩展的"情报网站"系统第一版。第一个接入的情报源是
[我爱音频网 52audio.com](https://www.52audio.com/) 的
[「拆解」分类](https://www.52audio.com/archives/category/teardowns)（拆解报告 + 拆解视频）。

抓取结果是结构化 JSON（`data/`），前端是纯静态 HTML/CSS/JS（`site/`），可以直接
用浏览器打开 `site/index.html` 查看，也可以直接部署到 GitHub Pages，不需要常驻服务器。

详细的设计思路（信息架构、分类体系、OCR 框架、ASR 调研、时间线方案）见
[`docs/DESIGN.md`](docs/DESIGN.md)。

## 快速开始

```powershell
# 1. 安装依赖
py -3 -m pip install -r requirements.txt

# 2. 跑爬虫，抓取 52audio「拆解」分类最近 N 条文章（默认 30）
py -3 scripts/crawl.py --limit 30
# 调试时可以跳过图片下载/分析，跑得更快：
py -3 scripts/crawl.py --limit 10 --no-images

# 3. 用抓到的数据生成静态站点
py -3 scripts/build_site.py

# 4. 直接用浏览器打开 site/index.html 查看效果
```

## 目录结构

```
core/                       与具体情报源无关的通用框架代码
├── models.py                统一数据模型（TeardownReport / VideoItem / ImageAsset / ...）
├── base_source.py            情报源抽象基类 BaseSource（fetch_list / parse_detail）
├── pipeline.py                抓取编排：跑所有 Source → 合并落盘 data/*.json
└── extract/                   详情页结构化抽取算法（通用算法 + 外部关键词表）
    ├── text_utils.py           从 WordPress 正文 HTML 里拆 Block（标题/段落/图片）
    ├── selling_points.py       卖点/特色候选句抽取（jieba 关键词 + snownlp 情感分）
    ├── components.py           产品结构理解（主要/次要部件识别）
    ├── tech_specs.py           技术参数抽取（充电方式/接口/说明书/产品标记）
    └── images.py                图片"文本密集/图像密集"判断 + OCR 待办队列（框架先行）

sources/                     具体情报源实现，新增网站只需要在这里加一个子模块
└── audio52/                  52audio.com 的实现
    ├── source.py               Audio52Source：消费分类 RSS Feed，含完整正文
    ├── parse_title.py          标题解析（类型/品牌/型号/分类）
    └── lexicon.py               可配置规则表：分类体系/品牌别名/卖点词库/部件词库/技术参数规则

scripts/
├── crawl.py                  爬虫主入口（CLI）
├── build_site.py              静态站点生成器（Python 字符串模板，无前端构建链）
└── site_common.py             页面骨架/卡片渲染的公共小工具

data/                         结构化数据落盘（爬虫的输出、前端的数据源）
├── reports.json                拆解报告全量数据（含卖点/部件/技术参数/图片分析结果）
├── videos.json                  拆解视频全量数据
└── images_queue.json            图片 OCR 待办队列（判定为文本密集型、等待接入真实 OCR 的图片）

site/                         纯静态站点产物，可直接被 GitHub Pages 托管
├── index.html                  首页：统计 + 板块入口 + 最近更新时间线
├── reports/                     拆解报告列表页 + 逐条详情页
├── videos/                      拆解视频列表页 + 逐条详情页
├── about.html                   关于本站（信息架构/分类体系/OCR/ASR 说明）
└── assets/                      style.css / app.js（纯前端分类筛选，无网络请求）

docs/
└── DESIGN.md                  设计说明文档（信息架构理由、分类体系调研、OCR 框架、
                                 ASR 技术选型调研、时间线/轻量数据库方案建议）

.github/workflows/
└── update-and-deploy.yml      定时爬虫更新数据 + 提交 + 构建站点 + 部署 GitHub Pages
```

## 新增一个情报源需要做什么

1. 在 `sources/` 下新建一个子模块（参考 `sources/audio52/`）；
2. 实现 `BaseSource` 的 `fetch_list()` 和 `parse_detail()`，返回
   `core.models.TeardownReport` 或 `VideoItem`；
3. 把新 Source 的实例加进 `scripts/crawl.py` 的 `build_sources()` 列表；
4. 其余流程（落盘、去重合并、静态站点生成）完全不用改。

## 视频 ASR 调研结论（简述，详见 DESIGN.md 第 6 节）

调研了 `yt-dlp`、`faster-whisper`、`whisper.cpp`、`WhisperX`，以及一个现成的 Cursor/
Claude Code Skill [`imlewc/video-to-subtitle-summary-skill`](https://github.com/imlewc/video-to-subtitle-summary-skill)
（yt-dlp 抓字幕/下载音频 → faster-whisper 转写 → 摘要，可直接参考）。建议后续接入路径：
`yt-dlp` 拿音频 → `faster-whisper` 转写成文本 → 复用本项目已有的
`core/extract/selling_points.py` 等抽取模块处理转写文本，无需为视频重新写一套逻辑。

## 后续需要人工 / 协调流程完成的事项

本次交付**不包含**以下内容，需要人工或另一个协调流程完成：

1. GitHub 远程仓库创建、`git remote add`、`git push`；
2. GitHub 仓库 Settings → Pages → Source 切换为 "GitHub Actions"（否则
   `.github/workflows/update-and-deploy.yml` 里的部署 job 不会生效）；
3. 首次云端定时任务跑起来之后的验证（本地已验证脚本可以正常跑通，但 GitHub Actions
   runner 的网络环境、IP 出口地区可能与本地不同，建议上线后跑一次
   `workflow_dispatch` 手动触发确认无误）；
4. 真实 OCR 引擎接入：本机未安装 Tesseract 可执行文件，`data/images_queue.json` 里
   250 条图片 OCR 队列目前都是 `pending` 状态；如果要真正跑通文字识别，需要
   `winget install UB-Mannheim.TesseractOCR`（或云端 OCR API Key / 多模态大模型
   API Key）；
5. 拆解视频 ASR 真正接入（`yt-dlp` + `faster-whisper`），需要额外安装依赖
   （`ffmpeg`、可能需要 GPU 才能达到理想速度），且 B站视频解析可能需要付费代理服务；
6. 如果未来要做"按产品查看时间线"功能，`docs/DESIGN.md` 第 7 节给了两个方案，
   方案 B（SQLite + 查询层）需要额外开发时间。
