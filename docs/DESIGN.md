# 设计说明文档

本项目是一个可长期运行、可扩展的"情报网站" MVP，第一个接入的情报源是
[我爱音频网 52audio.com](https://www.52audio.com/) 的
[「拆解」分类](https://www.52audio.com/archives/category/teardowns)（拆解报告 + 拆解视频）。

本文档记录：数据源侦察结论、信息架构设计与理由、产品分类体系、OCR 框架设计、
拆解视频 ASR 技术选型调研、以及面向未来"产品时间线/轻量数据库"的方案建议。

---

## 1. 数据源侦察结论

在写爬虫之前，先用 `WebFetch` 和 Python `requests` 实测了目标网站，结论如下：

- 目标分类页 `https://www.52audio.com/archives/category/teardowns` 是标准 WordPress
  分类页，支持 `/page/N/` 翻页浏览。
- 该分类同时提供 **RSS Feed**：`https://www.52audio.com/archives/category/teardowns/feed/`，
  且支持 `?paged=2`、`?paged=3` … 翻页拿到更早的历史文章（已用脚本实测确认，见
  `sources/audio52/source.py` 顶部注释）。
- Feed 里的每个 `<item>` 已经包含标题、原文链接、作者（`dc:creator`）、发布时间
  （`pubDate`）、原始分类标签（`category`）、摘要（`description`）、以及
  **完整正文 HTML**（`content:encoded`，含 H2-H4 标题层级、`<figure><img>` 图片、
  视频 `<iframe>` 嵌入）。
- 因此本项目**直接消费分类 Feed**，不需要再单独抓取每篇文章的详情页 HTML 做二次解析：
  请求量最小、字段最稳定、对目标网站最友好。
- 文章标题 100% 以「拆解报告：」或「拆解视频：」为前缀，这是区分"拆解报告"和
  "拆解视频"两个板块**最可靠**的信号；同时以正文里是否存在 `<iframe>`（B站/YouTube
  等嵌入播放器）作为**次要交叉验证信号**，用于极少数标题前缀缺失/不规范时的兜底判断
  （代码见 `sources/audio52/source.py` 的 `parse_detail`）。
- 图片实际存放在阿里云 OSS（`52audio-images.oss-cn-shenzhen.aliyuncs.com`），开启了
  防盗链（Referer 校验），下载图片时必须带上 `Referer: https://www.52audio.com/`，
  否则会收到 403（这是实测踩的一个坑，已在 `core/extract/images.py` 里修复）。

### 1.1 历史全量回溯（2026-07）

早期爬虫仅跑过 `--mode backfill-2026`（只抓 2026 年当年数据）与 `daily`（日更第 1 页），
导致 `data/reports/` + `data/videos/` 实际只覆盖 2026-01-05 ~ 2026-07-03，被误以为是数据源
本身的限制。实测分类 RSS Feed 翻页发现：

- Feed 支持一路翻页到 **第 106 页**（`?paged=106`），最早一条 pubDate 为 **2018-04-16**；
  第 107 页起稳定返回 404（非限流/封禁，是"翻到头了"的正常边界）。
- 因此不需要走独立的 `/page/N/` 列表页、sitemap.xml 或按日期的归档 URL 方案——RSS Feed
  分页本身即可覆盖该分类站点上线以来的全部拆解文章，且每条 `<item>` 自带完整正文
  `content:encoded`，回溯全程零额外单篇请求。
- 新增 `scripts/crawl_v2.py --mode backfill-historical --since 2018-01-01`，按
  `stop_before` 逐页翻到早于 `--since` 的日期或翻页 404 为止；单条记录仍走既有
  `append_record` 按 ID 去重立即落盘，中断后重跑天然可恢复。
- 2026-07-14 执行全量回溯：新增 1009 篇报告 + 122 条视频，日期范围由
  `2026-01-05 ~ 2026-07-03` 扩展到 **`2018-04-16 ~ 2026-07-13`**。**2018-04-16 是该
  「拆解」分类目前可回溯到的最早文章，未见早于此日期的内容**（即未能抓到严格意义上的
  2018-01-01，但已到达 Feed 翻页的真实边界，属于诚实上限而非人为截断）。

---

## 2. 信息架构与呈现形式设计

**使用场景**：情报网站要"每天都要看、定期推送"，用户关心的是"最近又拆了什么新品、
有什么新卖点/新方案"，同时偶尔需要深挖某一款产品的完整结构化信息。基于这个场景，
设计了以下信息架构（而不是照搬用户原话里的字段顺序）：

```
site/
├── index.html            首页：Hero 统计 + 两大板块入口 + "最近更新"时间线（报告+视频混排，按日期倒序）
├── reports/
│   ├── index.html        拆解报告列表：分类筛选 tab + 卡片网格（品牌+型号+分类+摘要片段）
│   └── <id>.html         拆解报告详情：结构化信息在前，原文完整正文在后
├── videos/
│   ├── index.html        拆解视频列表：分类筛选 tab + 卡片网格
│   └── <id>.html         拆解视频详情：发布者/日期/平台/产品标题 + 视频内嵌播放
├── about.html            关于本站：信息架构、分类体系、OCR/ASR 现状说明
└── assets/                style.css / app.js（纯前端筛选交互，不依赖网络请求）
```

**理由**：

1. **首页做"最近更新"而不是分别罗列两个板块** —— 每天打开时第一眼就能看到"今天/这几天
   又更新了什么"，报告和视频混合按时间倒序展示，符合"日常巡检"的使用习惯；两个板块的
   入口卡片放在时间线上方，方便"我今天只想看报告"这种场景快速切换。
2. **列表页用卡片 + 分类筛选 tab**，而不是表格 —— 卡片更适合"品牌 LOGO 感"的浏览体验，
   分类筛选用纯前端 JS（`data-category` 属性 + 显示/隐藏）实现，不需要重新请求数据，
   在 GitHub Pages 这种纯静态托管上完全够用。
3. **详情页"结构化信息在前、原文在后"** —— 结构化提取（卖点/部件/技术参数）是本系统
   相对原网站的增量价值，放在最上面；原文完整正文（含全部图片）放在最后，保留"可
   追溯溯源"的能力，避免抽取有误时用户没法核实原文。
4. **不做" fetch 本地 JSON 再用 JS 渲染"的方案** —— 纯静态 HTML 在 `file://` 协议下
   直接双击打开时，Chrome 等浏览器会因为 CORS 策略拦截 `fetch()` 读取本地 JSON 文件，
   导致本地预览"打开是空白页"。所以本项目采用**构建时把数据"烤"进 HTML**（服务端渲染
   思路，用 Python 字符串模板实现），保证不管是本地双击打开还是部署到 GitHub Pages
   都能正常显示内容，无需额外起本地 HTTP 服务器。

---

## 3. 产品分类体系

分类体系写在 `sources/audio52/lexicon.py` 的 `CATEGORY_RULES` 里（有序关键词规则表，
不写死在爬虫逻辑中，方便随时调整/扩展），基于对 2026-07 抓取到的真实文章标题的调研，
最终确定 9 个分类（按判断优先级从高到低排列，越具体的分类越靠前）：

| 分类 | 判断关键词（节选） | 真实样本 |
|---|---|---|
| 骨传导耳机 | 骨传导 | kaiboaudio KAIBO VERSE Plus骨传导耳机 |
| 开放式耳机 | 开放式、耳夹式、挂耳式 | Baseus倍思Bowie MC2开放式耳机、SHOKZ韶音OpenDots 2耳夹耳机 |
| 颈挂式蓝牙耳机 | 颈挂式、颈戴式 | （分类已预留，样本中暂未抓到，规则保留待后续数据验证） |
| 头戴式耳机 | 头戴式 | 荣耀亲选Codelear 2头戴式降噪耳机 |
| 真无线耳机TWS | 真无线、TWS | Soundcore声阔Liberty 4 NC真无线降噪耳机 |
| 有线耳机 | 有线耳机、入耳式耳机 | COLORFLY七彩虹SR入耳式耳机 |
| 智能手表 | 手表、Watch | Xiaomi小米Watch S5智能手表 |
| AI眼镜及穿戴设备 | AI眼镜、眼镜、Vision | 理想AI智能眼镜Livis、DPVR大朋Vision Ray AI眼镜 |
| 音箱及其他音频设备 | 音箱、音响、麦克风、录音 | JBL SPARK音乐火花装饰音箱、大疆DJI Mic Mini 2无线麦克风 |
| （兜底）其他音频设备 | 未命中以上任何规则 | — |

同一份文件里还配置了：

- `BRAND_ALIASES`：品牌别名表（中英文写法归一化，如 `Baseus`/`倍思` → `Baseus倍思`）；
- `PRODUCT_TYPE_SUFFIXES`：从标题里切掉"产品形态后缀词"来近似得到型号（启发式，
  详见 `sources/audio52/parse_title.py`）；
- `SELLING_POINT_KEYWORDS`：卖点/特色关键词库；
- `COMPONENT_LEXICON`：部件关键词库（含 major/minor 归类）；
- `TECH_SPEC_RULES`：技术参数抽取规则。

以上都是"数据"而非"代码"，运营层面后续调整分类/关键词，只需要改这一个文件。

---

## 4. 核心抽取算法说明（对应"核心功能一"的 a/b/c/d）

所有算法都在 `core/extract/` 下，采用"通用算法 + 外部关键词表"的解耦设计：

- **(a) 卖点特色**（`core/extract/selling_points.py`）：正文分句 → 用卖点关键词库
  做命中打分 → 用 `snownlp` 做情感分（0~1）辅助判断"强调型/中性/谨慎表述" → 取
  Top N 候选句，附带命中关键词和情感标签。这是启发式方法，量级上不追求精确匹配"真正
  的卖点"，而是把"像卖点的句子"筛出来交给人复核，实测效果上已经能比较准确地抓到
  "首发/专利/升级/认证"等强调性表述。
- **(b) 产品结构理解**（`core/extract/components.py`）：顺序扫描正文的 H2-H4 标题 /
  段落 / 图片，维护"当前小节标题"和"最近一张图片下标"，段落命中部件关键词库时记一条
  `ComponentMention`，同时把最近的小节标题和图片下标关联进去；部件按 major/minor
  两组呈现（喇叭单元/主板/电池/充电仓/天线/麦克风/降噪系统/骨传导振子 归为 major，
  耳塞套/耳挂/按键/指示灯/包装盒/说明书/外壳 归为 minor）。
- **(c) 部件详细信息**：即 (b) 里每个 `ComponentMention` 自带的正文片段 + 关联图片，
  在详情页里直接展示为"部件名 + 相关描述 + 缩略图"列表，不需要额外的抽取步骤。
- **(d) 技术数据**（`core/extract/tech_specs.py` + `core/extract/images.py`）：
  正文文字部分用关键词/正则规则抽取"充电方式/充电接口/说明书/产品标记"，同时把
  "形似参数罗列"（一句话里出现 ≥2 个冒号）但未命中规则的句子收进 `raw_candidates`
  供人工复核；图片里的表格/铭牌文字走"框架先行"的 OCR 管线（见下一节）。

---

## 5. OCR 框架设计与真实识别能力现状

按用户明确选定的"框架先行"方案实现，分两层：

### 5.1 已经跑通的部分（真实代码，非占位）

1. **图片下载**：对正文每张图片，带 `Referer` 头下载（绕过 OSS 防盗链）。
2. **"文本密集型 vs 图像密集型"启发式判断**（`core/extract/images.py`）：
   - `edge_density`：Canny 边缘检测后的边缘像素占比 —— 规格表/铭牌截图文字笔画密集，
     边缘占比明显更高；
   - `unique_color_ratio`：缩放到 64×64 后量化统计唯一颜色种类占比 —— 文字/表格类
     图片大多是"白底黑字"，颜色种类很少；实物照片色彩层次丰富，颜色种类多；
   - 阈值（`EDGE_DENSITY_THRESHOLD=0.045`、`UNIQUE_COLOR_RATIO_THRESHOLD=0.12`）是
     用真实抓到的图片做了小规模人工校准（实测：产品实物照片 edge_density 普遍在
     0.004~0.04，而规格表/BOM清单截图在 0.05~0.09），首版经验值，代码里标了 TODO，
     后续有更多标注样本后可以再调参，或替换成更准确的文本检测器（比如 OpenCV EAST/DB）。
3. **OCR 待办队列**：判定为 `text_dense` 的图片，记录 `image_url`/所在文章/判断依据，
   写入 `data/images_queue.json`（本次真实抓取产出了 **250 条**待办记录）。
4. **真实 OCR 引擎探测**：代码里用 `pytesseract.get_tesseract_version()` 惰性探测本机
   是否装了 Tesseract 可执行文件——**如果装了，会真的跑一遍 OCR** 把 `ocr_status`
   置为 `done` 并填充 `ocr_text`；如果没装，优雅降级为 `pending`，不影响其余流程。

### 5.2 当前真实识别能力现状

**本机环境未安装 Tesseract 可执行文件**（`pytesseract` 库本身已经装好，但缺可执行
二进制），所以本次交付的 250 条 OCR 队列全部处于 `pending` 状态，**属于"框架已经
搭好、真实文字识别能力尚未跑通"**。安装 Tesseract 需要用 `winget install
UB-Mannheim.TesseractOCR` 之类的方式往系统里装可执行程序，这类"改动系统环境"的操作
本次没有在未经确认的情况下执行，留给人工按需选择（见 README「后续人工事项」）。

### 5.3 后续接入建议

- **最快路径**：在本机或 CI 里装 Tesseract 可执行文件（`winget install
  UB-Mannheim.TesseractOCR` / `apt install tesseract-ocr tesseract-ocr-chi-sim`），
  代码不需要改，重新跑 `scripts/crawl.py` 时会自动检测到并跑真实 OCR。
- **更高精度路径**：接入云端 OCR（阿里云/腾讯云通用文字识别，或百度 OCR），
  对 `ocr_status="pending"` 的图片批量调用 API，回填 `ocr_text`；由于 GitHub Pages
  是纯静态托管，这类调用需要放在 GitHub Actions 里用 Secrets 存 API Key。
- **多模态大模型路径**：把 `pending` 图片交给多模态大模型（如 GPT-4o / Claude /
  Qwen-VL）做"看图问答"式的结构化抽取（不只是识别文字，还能直接回答"这张图的
  充电接口是什么"），精度和语义理解能力都会比传统 OCR 更好，但有调用成本。

---

## 6. 拆解视频板块与 ASR 技术选型调研

### 6.1 现状（本次交付范围）

`VideoItem` 数据模型只做轻量结构化：`publisher`（发布者）/ `date`（发布日期）/
`source_site` + `url`（发布网站及地址）/ `product_title`（涉及产品标题），
本次真实抓到 **12 条**拆解视频记录，全部来自 B站（哔哩哔哩）嵌入播放。

### 6.2 开源方案调研结论

调研了用户回忆里提到的几个方向，结论如下：

| 工具 | 定位 | 是否需要 GPU | 备注 |
|---|---|---|---|
| **yt-dlp** | 视频/音频下载 + 元数据/字幕抓取 | 否 | 支持 YouTube 官方字幕/自动字幕直接抓取；B站视频本身很少有官方字幕，通常只能下载音频再做 ASR |
| **faster-whisper**（SYSTRAN） | 本地语音转写 | 建议有（CPU 也可跑，慢一些） | 基于 CTranslate2，INT8/FP16 量化，速度是原版 Whisper 的 4~8 倍，是当前 Python 数据管线里做批量转写的主流首选 |
| **whisper.cpp**（ggml-org） | 本地语音转写（C/C++ 原生） | 否 | 无需 Python/PyTorch，编译成单一可执行文件，适合无 GPU / 边缘设备 / 想极简部署的场景 |
| **WhisperX** | faster-whisper 的增强版 | 建议有 | 提供更准的词级时间戳（做字幕/卡拉OK效果）和说话人分离（diarization） |
| [`imlewc/video-to-subtitle-summary-skill`](https://github.com/imlewc/video-to-subtitle-summary-skill) | 面向 Cursor/Claude Code 的现成 Skill | 否（默认本地 faster-whisper，也支持云端 ASR） | 覆盖了 "yt-dlp 抓 YouTube 字幕 / 下载音频 → faster-whisper 转写 → 摘要" 的完整流程，B站/抖音需要额外的解析代理（AI Douyin / TikHub）拿直链，是一个可以直接参考甚至复用的现成方案 |

### 6.3 接入建议（目标：用和拆解报告一样的结构化提取逻辑处理视频内容）

1. **抓取阶段**：`yt-dlp` 下载音频（B站视频需要走类似 `imlewc` 那个 skill 提到的
   解析代理拿到直链，或直接用 `yt-dlp` 的 B站 extractor）。
2. **转写阶段**：优先用 **faster-whisper**（Python 生态、和本项目其余代码栈一致，
   CPU 也能跑，只是慢一些）；如果未来要在资源受限的 CI runner 上跑，可以换成
   **whisper.cpp** 的预编译二进制。
3. **结构化阶段**：把转写出来的文本，喂给本项目已有的
   `core/extract/selling_points.py` / `components.py` / `tech_specs.py`
   —— 这几个模块的输入本来就是"纯文本"，天然可以复用，不需要为视频重新写一套抽取逻辑，
   这也是本项目"核心抽取算法与数据源解耦"的设计能直接兑现价值的地方。
4. **成本/合规提示**：B站/抖音等平台的解析代理（如 AI Douyin/TikHub）通常是收费服务，
   接入前需要评估调用量和费用；YouTube 官方字幕走 `yt-dlp` 免费且更省事，优先支持。

---

## 7. 面向未来的"产品时间线 / 轻量数据库"方案建议

用户提到后续想"针对某个产品，查看它在时间线上的变更"。给两个可行方案，建议分阶段推进：

### 方案 A（近期，成本最低）：继续用 JSON 文件 + git 提交历史当"免费时间线"

- `core/pipeline.py` 已经在每条记录里维护了 `first_seen_at`（首次抓到时间）和
  `crawled_at`（最近一次抓取/更新时间），且落盘策略是"按 id 合并覆盖"而不是每次
  全量重写，所以 `git log --follow -p -- data/reports.json` 或者针对某个 id 用
  `git log -p -S'"id": "281175"' -- data/reports.json` 就能翻出这条记录每次被更新时
  的 diff，天然形成一份"变更时间线"，不需要额外开发，GitHub 免费仓库自带无限期历史。
- 缺点：查询体验较差（要跑 git 命令/写脚本解析 diff），不适合做"可视化时间线"产品功能。

### 方案 B（未来，从 GitHub Pages 过渡到自建服务器时）：引入 SQLite + 一层很薄的查询层

- 把 `data/reports.json` / `data/videos.json` 的每次抓取结果，追加写入一张
  `report_snapshots(id, product_id, snapshot_at, field_name, old_value, new_value)`
  这样的"变更流水表"（可以用一个几十行的 Python 脚本在每次 `crawl.py` 跑完后做
  diff 并写入 SQLite，不需要额外的服务进程，SQLite 是单文件数据库）；
- 再加一层很薄的查询 API（比如 FastAPI + SQLite，或者干脆用 `datasette` 这种现成的
  "把 SQLite 变成可浏览网站"的工具）对外提供"某个产品的历次报道/规格变化"查询；
- 这一层可以先在本地跑起来验证效果，等真的要迁移到公司自建服务器时，SQLite 文件可以
  直接搬过去，或者平滑换成 PostgreSQL（表结构不需要大改）。

**建议**：现阶段（GitHub Pages 静态托管）先落地方案 A，成本几乎为零；如果"按产品看
时间线"变成高频需求，再投入实现方案 B。
