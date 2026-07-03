# 52audio 情报站架构改进方案 V3

> 基于用户补充文件《耳夹旗舰产品卖点总结与网站提取模板》及三项不满意点的改版设计。  
> 本文档为方案与爬取验证结论，**不要求立即改代码**。

---

## 0. 现状与差距

| 能力 | 现状 | 用户期望 |
|------|------|----------|
| 信息入口 | 首页 → 报告/视频列表 → 单条详情 | **先聚合矩阵/对比**，再下钻详情 |
| 角色视图 | 详情页内五区块 + 角色透镜切换 | 各角色在矩阵页就能看到「全产品关键参数」 |
| BOM/物料 | `role_extract` 仅从正文文本抽芯片名 | **「我爱音频网总结」段 PNG 物料表 + 总结段文字** |
| 视频 | B 站 embed + 极短导语；`asr_status=pending` | 与报告同构五区块 + 转写复用 `role_extract` |
| 矩阵页 | `site/matrix/index.html` 单页 7 列通用字段 | 角色透镜 × 品类 × 对比页 |

---

## 1. 用户 HTML 文件提取摘要

文件：`d:\成本管理\情报需要关注资料.html`  
标题：**耳夹旗舰产品卖点总结与网站提取模板**（OpenDots2/Being 立项 PPT 结构化）。

### 1.1 文档结构（7 节）

| 节 | 内容 |
|----|------|
| 1 核心结论 | 定位、目标价位（900–1399 元）、三大价值（音质+佩戴+外观） |
| 2 卖点总结 | 6 维：音质体验、佩戴体验、开放式安全、外观美学、通话办公、基础体验 |
| 3 目标人群 | 精致女性 / 科技潮男 / 职场新锐白领 + 场景 tag |
| 4 **网站卖点提取框架** | 12 字段模板（见下表） |
| 5 **卖点提取标签库** | 9 大类统一 tag，用于横向比较 |
| 6 示例填法 | 7 列对比表示例 |
| 7 判断标准 | 4 问 + 提取公式链 |

### 1.2 网站卖点提取框架（12 字段 + 注释）

| 字段 | 注释 / 为什么关注 |
|------|-------------------|
| 品牌/产品 | 品牌名、型号、上市价/当前价 — 锚定竞品身份 |
| 原文卖点 | 官网/详情页原句 — 保留证据、避免过度解读 |
| 卖点归类 | 音质、舒适、稳固、外观、通话、降噪、续航… — 可聚合统计 |
| 对应痛点 | 久戴不适、运动掉落、低音不足… — 判断是否为真差异化 |
| 使用场景 | 通勤、办公、会议、运动、穿搭… — 映射目标人群 |
| 目标人群 | 女性、潮男、白领、运动用户… — PM/市场透镜 |
| 功能/技术 | 喇叭、算法、麦克风、芯片、蓝牙、材质、结构 — 成本/硬件/结构透镜 |
| **量化参数** | dB、小时、克重、mm、Hz、IP、延迟、拉伸次数 — 矩阵列、对比页硬指标 |
| 用户利益 | 舒适不痛、稳固不掉、听得更清… — 卖点是否落到用户价值 |
| 可信背书 | 认证、奖项、实验室、KOL、销量 — 可信度权重 |
| 竞品对比 | 比谁更强、有无参数/评价支撑 — 对比页输入 |
| 可复用表达 | 内部分析标准句式 — 报告/矩阵展示文案 |

### 1.3 卖点标签库（9 类）

音质体验 · 佩戴体验 · 运动稳固 · 通话办公 · 外观美学 · 交互连接 · 续航充电 · 智能生态 · 价格与价值

### 1.4 示例表结构（7 列）

`品牌/产品 | 原文/提炼卖点 | 卖点归类 | 痛点 | 场景 | 功能/参数 | 用户利益`

### 1.5 与现有五角色透镜的映射

用户 HTML 偏 **市场/卖点**，与仓库 `ROLE_LENSES` 的对应关系：

| 用户 HTML 字段簇 | 情报站角色 | 矩阵/详情字段 |
|------------------|------------|---------------|
| 品牌/产品、卖点、场景、人群、竞品 | **产品经理 (pm)** | `views.market.*`, `selling_point_tags` |
| 功能/技术、芯片、电池、PMIC | **成本工程师 (cost)** | `views.cost.bom_table`, `chip_modules` |
| 材质、结构、IP、重量、佩戴 | **结构工程师 (structure)** | `views.structure.*` |
| 量化参数（电池、接口、认证） | **硬件工程师 (hardware)** | `views.hardware.specs` |
| 蓝牙、编码、多点、App、延迟 | **软件工程师 (software)** | `views.software.*` |

**参数注释**应写入 `data/schema/field_annotations.json`（新建），构建矩阵时作为列头 `title` 与详情页 tooltip 来源。

---

## 2. 聚合页 + 对比页改版方案

### 2.1 信息架构（IA）

```
site/
├── index.html                          # 首页：统计 + 「进入全产品矩阵」主 CTA
├── matrix/
│   ├── index.html                      # 聚合枢纽：角色透镜 + 品类 tab + 全产品矩阵
│   ├── pm.html                         # （可选独立 URL）产品经理透镜默认页
│   ├── cost.html                       # 成本透镜
│   └── ...
├── compare/
│   ├── index.html                      # 对比入口：选品类 → 跳转 compare/{品类}.html
│   ├── 开放式耳机.html                  # 同品类横向对比（列=产品，行=参数）
│   ├── 真无线耳机TWS.html
│   └── ...
├── reports/{id}.html                   # 详情：五区块 + 角色透镜（保持不变，矩阵链入）
└── videos/{id}.html                    # 详情：embed + 五区块（Phase 2 对齐报告）
```

**导航顺序**：首页 → **竞品矩阵（聚合）** → 对比页 → 报告/视频详情。

### 2.2 URL 规范

| 页面 | URL | 查询参数 |
|------|-----|----------|
| 聚合矩阵枢纽 | `/matrix/index.html` | `?role=pm&category=开放式耳机` |
| 角色默认页 | `/matrix/cost.html` | `?category=真无线耳机TWS` |
| 品类对比 | `/compare/开放式耳机.html` | `?ids=281175,280166` 预选行 |
| 报告详情 | `/reports/281175.html` | `?from=matrix&role=cost` 返回上下文 |
| 视频详情 | `/videos/281250.html` | 同上 |

品类 slug：与 `data/matrix/{品类}.json` 文件名一致（中文，如 `开放式耳机.json`）。

### 2.3 角色透镜 × 聚合矩阵列定义

#### 产品经理 (pm)

| 列 | 来源 | 注释（来自用户 HTML） |
|----|------|----------------------|
| 品牌 | `market.brand` | 竞品身份 |
| 型号 | `market.model` | |
| 售价 | `market.price_cny` | 上市价/当前价 |
| 上市 | `launch_date` / `published_at` | |
| 卖点标签 | `selling_point_tags` | 卖点归类，可横向统计 |
| 核心卖点 | `selling_points[0:3]` | 原文/提炼，带 evidence |
| 场景 | `market.scenarios` | 使用场景 |
| 完整度 | `data_completeness` | |
| 详情 | → `reports/{id}.html` | |

#### 成本工程师 (cost)

| 列 | 来源 |
|----|------|
| 品牌/型号 | market |
| 主控芯片 | `cost.chip_modules` |
| 充电仓 PMIC | summary 段 OCR / 文本 |
| 耳机电池 | summary 段 |
| 仓电池 | summary 段 |
| 喇叭规格 | structure + summary |
| BOM 行数 | `len(bom_table)` |
| 物料表图 | summary PNG 缩略图链接 |

#### 结构工程师 (structure)

| 列 | 来源 |
|----|------|
| 佩戴类型 | `earbud_type` |
| 形态/品类 | `category` |
| 材料 | `materials` |
| IP 等级 | `ip_rating` |
| 重量 | `weight_g` |
| 紧固/密封 | `fastener_type`, `sealing_method` |

#### 硬件工程师 (hardware)

| 列 | 来源 |
|----|------|
| 电池容量 | specs / summary |
| 充电接口 | specs |
| 认证/标记 | specs |
| 蓝牙 | software.bluetooth_version |

#### 软件工程师 (software)

| 列 | 来源 |
|----|------|
| 蓝牙版本 | `bluetooth_version` |
| 编码 | `codecs` |
| 多点 | `multipoint` |
| App/OTA | `app_features`, `ota_support` |
| 延迟 | `latency_notes` |

切换角色时：**同一批产品行、不同列集**；缺失单元格灰显 + tooltip「待从总结段/OCR 补充」。

### 2.4 对比页线框（`/compare/开放式耳机.html`）

```
┌─────────────────────────────────────────────────────────────┐
│ [◀ 返回矩阵]  开放式耳机 · 参数对比    角色: [PM ▼]          │
│ 已选产品: [Baseus MC2 ×] [OpenDots 2 ×] [+ 添加产品]        │
├─────────────────────────────────────────────────────────────┤
│ 参数 \ 产品    │ Baseus Bowie MC2 │ SHOKZ OpenDots 2 │ ...  │
│───────────────┼────────────────┼──────────────────┼──────│
│ 主控芯片       │ BT8912F        │ BES2700iH        │      │
│ 仓 PMIC       │ IP5528         │ SY8805           │      │
│ 仓电池        │ 600mAh         │ 590mAh           │      │
│ 耳机电池      │ 55mAh          │ 60mAh            │      │
│ 喇叭          │ 10.8mm 三磁    │ 11.8mm 双单元    │      │
│ 蓝牙/编码     │ BT6.0 LDAC     │ — / 杜比         │      │
│ 卖点标签      │ tag chips      │ tag chips        │      │
└─────────────────────────────────────────────────────────────┘
│ 每格可展开 evidence + 链到 reports/{id}.html#section-cost    │
└─────────────────────────────────────────────────────────────┘
```

对比页数据：`data/compare/{品类}.json`，由 `build_matrix.py` 扩展生成，行=参数键，列=产品 `canonical_id`。

### 2.5 与 `site/reports/{id}.html` 的关系

```
矩阵/对比页（宽表，多产品）
        │ 点击「详情」/ 参数格 evidence
        ▼
reports/{id}.html（深页，单产品五区块）
        │ 角色透镜预选中（URL ?role=cost）
        │ 面包屑：矩阵 > 开放式耳机 > Baseus MC2
        ▼
52audio 原文（外链）
```

详情页**不删减**；矩阵是详情 `views` 的 **透视汇总**，不是替代。

---

## 3. 「我爱音频网总结」段落验证

### 3.1 实测样本

| ID | 原文 URL | 标题 |
|----|----------|------|
| 281175 | https://www.52audio.com/archives/281175.html | Baseus倍思Bowie MC2开放式耳机 |
| 280166 | https://www.52audio.com/archives/280166.html | SHOKZ韶音OpenDots 2耳夹耳机 |

验证方式：RSS `content_html` 缓存 + **WebFetch 访问 live 页面**（2026-07-03）。

### 3.2 标题命名结论

| 模式 | 出现情况 |
|------|----------|
| **`三、我爱音频网总结`** | **主流**：`<h4 class="wp-block-heading"><strong>三、我爱音频网总结</strong></h4>` |
| `三、我爱音频网总结`（无 strong） | 少数 |
| `三、智研所总结` | 个别稿件（如 279485），需 fallback |
| `爱音频网总结` / `52audio总结` 单独出现 | **未发现** |

**建议锚点正则**（优先级序）：

```python
SUMMARY_HEADING_RE = [
    r"我爱音频网总结",
    r"智研所总结",
    r"总结",  # 仅在前两者失败且位于「拆解全家福」之后时使用
]
```

### 3.3 Section HTML 结构特征

```html
<h4 class="wp-block-heading"><strong>三、我爱音频网总结</strong></h4>
<figure class="wp-block-image">
  <img src="https://52audio-images.oss-cn-shenzhen.aliyuncs.com/.../....png"
       alt="拆解报告：...-我爱音频网" width="1517" height="886" />
</figure>
<p>最后附上...已知核心物料清单，方便大家查阅。</p>
<p>...外观方面...</p>
<p>内部主要配置方面，充电盒搭载了...；耳机内部搭载...</p>
```

| 特征 | 281175 | 280166 |
|------|--------|--------|
| 总结段 H 层级 | H4 | H4 |
| 段内图片数 | **1**（PNG 物料表） | **1**（PNG 物料表） |
| 图尺寸 | 1517×886 | 1517×1022 |
| alt | `拆解报告：...-我爱音频网` | 同左 |
| 是否表格图 | **是**（PNG 排版表格，非 HTML `<table>`） | 是 |
| 段内文字列表 | **有**（2–3 段结构化 prose，含芯片/电池/喇叭） | 有 |
| 「物料清单」关键词 | 有 | 有 |

### 3.4 样例 BOM 图 URL

- 281175: `https://52audio-images.oss-cn-shenzhen.aliyuncs.com/wp-content/uploads/2026/07/2026070102232238.png`
- 280166: `https://52audio-images.oss-cn-shenzhen.aliyuncs.com/wp-content/uploads/2026/06/2026062301394322.png`

### 3.5 OCR 必要性评估

| 数据源 | 信息密度 | 建议 |
|--------|----------|------|
| 总结段 **文字段落** | 高：主控、PMIC、电池容量、喇叭、麦克风已结构化 | **优先解析**，可直达 `bom_table` / `chip_modules` |
| 总结段 **PNG 物料表** | 更高：分左耳/右耳/充电仓行列、型号更全 | **必须 OCR**，作为文字段的校验与补全 |
| 正文拆解小节 | 中：分散在 H4 子节 | 现有 `role_extract` 继续用 |

**结论**：OCR **必要但非唯一路径**；Phase 1 可先吃总结段 prose 显著提升 BOM 完整度，PNG OCR 作为 Phase 1b。

### 3.6 缓存覆盖度（grep 统计）

`data/cache/content_html/` 中 **90+ 篇报告** HTML 含 `我爱音频网总结`；与 `data/reports/` 98 篇规模基本一致 → **可视为拆解报告标准结尾段**。

---

## 4. BOM / 物料清单提取 Pipeline

```
content_html (RSS)
       │
       ▼
┌──────────────────┐
│ 1. locate_summary │  H4 匹配「我爱音频网总结」→ 切分到下一 H4 或文末
└────────┬─────────┘
         ▼
┌──────────────────┐
│ 2. extract_assets │  section 内 <img src> → summary_images[]
│                   │  section 内 <p> 文本 → summary_prose
└────────┬─────────┘
         ├─────────────────────────────┐
         ▼                             ▼
┌──────────────────┐         ┌──────────────────┐
│ 3a. prose_parser │         │ 3b. image_pipeline│
│ 正则 + 句式模板   │         │ 下载 PNG (Referer)│
│ 「采用了X SoC」   │         │ text_dense 判定   │
│ 「搭载Y 电池」    │         │ OCR (Tesseract/   │
└────────┬─────────┘         │  Paddle 可选)     │
         │                   └────────┬─────────┘
         │                            │
         └──────────┬─────────────────┘
                    ▼
         ┌──────────────────┐
         │ 4. normalize_bom │  映射 COMPONENT_LEXICON + 侧别(左/右/仓)
         │ merge + dedupe   │  输出 cost.bom_table[] + evidence
         └────────┬─────────┘
                  ▼
         ┌──────────────────┐
         │ 5. annotate      │  合并 field_annotations.json 注释
         │ 6. role_extract  │  与全文 views 合并，summary 源 priority 更高
         └──────────────────┘
```

**新增模块建议**（小改，不动现有主流程）：

- `core/extract/summary_section.py` — 定位 + 切 section
- `core/extract/bom_from_prose.py` — 总结段文本 → BOM 行
- 扩展 `core/extract/images.py` — 仅对 `summary_images` 强制 OCR（跳过 text_dense 启发式）

**BOM 行 schema**（与现 `cost.bom_table` 一致）：

```json
{
  "component": "主控/蓝牙",
  "brand": "Bluetrum中科蓝讯",
  "model": "BT8912F",
  "qty_hint": "1",
  "side": "耳机",
  "role": "major",
  "evidence": {
    "value": "BT8912F",
    "source_type": "summary_prose|summary_ocr|text",
    "source_text": "...",
    "confidence": 0.85
  }
}
```

**字段注释注入**：构建站点时，参数名旁展示用户 HTML 中「量化参数」「功能/技术」说明。

---

## 5. 拆解视频模块

### 5.1 现状验证（281250、280554）

| 字段 | 281250 Card20 Pro | 280554 Sound Move |
|------|-------------------|-------------------|
| 原文 | https://www.52audio.com/archives/281250.html | https://www.52audio.com/archives/280554.html |
| B 站 embed | `//player.bilibili.com/player.html?bvid=BV185Tv6KE58` | `bvid=BV1D57G6AEsP` |
| 正文结构 | iframe + **1 段导语**（约 100 字） | iframe + 1 段导语 |
| 「总结」段 | **无** | **无** |
| `views` 五区块 | 有（来自导语 `role_extract`） | 有，但稀疏 |
| `asr_status` | pending | pending |

视频稿 **不能依赖「我爱音频网总结」**；必须走 ASR/字幕。

### 5.2 展示规划（与报告对齐）

详情页结构（目标）：

```
┌─ 视频 embed ─────────────────────────┐
│  [Bilibili iframe]                    │
├─ 转写摘要（可折叠）───────────────────┤
│  yt-dlp 字幕 / faster-whisper 输出    │
├─ 角色透镜 [PM|成本|结构|硬件|软件] ───┤
│  A 产品与市场  （同 reports）          │
│  B 成本与 BOM  （ASR 命中芯片/部件）   │
│  C 结构与材料                          │
│  D 硬件规格                            │
│  E 软件与连接                          │
├─ 时间轴要点（视频专属，Phase 2）───────┤
│  mm:ss — 拆充电盒 / 主板特写 ...       │
└─ 链到 matrix / compare ──────────────┘
```

**视频专属字段**（不入报告 schema）：

- `video_meta`: `bvid`, `duration`, `publisher`
- `asr`: `transcript`, `method`, `segments[]`（带时间戳）
- `timeline_highlights[]`: 可选，从 segment 关键词切分

### 5.3 加工路径

```
video JSON
    │
    ├─► enrich_video.py（已有）
    │     1. yt-dlp --write-auto-sub (zh-Hans, zh, en)
    │     2. fallback: yt-dlp -x + faster-whisper base
    │     → data/enrich/videos/{id}.asr.json
    │
    └─► ingest 扩展（Phase 2）
          transcript + 页面导语 → extract_role_views()
          merge 进 views，标记 source_type=asr|intro
          build_site.build_video_detail() 复用 build_report_detail 区块模板
```

**yt-dlp vs faster-whisper**：

| 路径 | 优点 | 风险 |
|------|------|------|
| yt-dlp 字幕 | 快、免费、B 站常有人工/自动字幕 | 部分视频无字幕 → empty |
| faster-whisper | 不依赖平台字幕 | CPU 慢、需 ffmpeg；专有名词（芯片型号）错误率较高 |

**建议**：字幕优先；empty 时 whisper **small** 模型 + 热词表（`CHIP_PATTERNS` 品牌名）后处理。

### 5.4 矩阵中的视频

- 视频产品 **合并进同品类矩阵行**（已有 `build_matrix` 逻辑，报告优先）。
- 矩阵行标注 `source: report|video|both`；仅视频行完整度通常较低，对比页默认隐藏或灰显。

---

## 6. 分阶段实施建议

### Phase 1 — 聚合可见（2–3 周，小改 build）

1. 扩展 `build_matrix.py`：按角色输出列集；写入 `report_id` / `canonical_id` 供详情链接。
2. `build_site.build_matrix_pages()`：角色透镜 UI（复用 `ROLE_LENSES`）；修复矩阵「详情」空链。
3. 新增 `site/compare/{品类}.html` 静态生成（先 PM + cost 两组参数行）。
4. 新建 `data/schema/field_annotations.json`（来自用户 HTML 注释）。
5. **`core/extract/summary_section.py` + `bom_from_prose.py`**：只吃总结段文字，验证 281175/280166 BOM 完整度提升。

**验收**：打开 `/matrix/index.html?role=cost&category=开放式耳机` 可见 ≥10 列成本相关字段；对比页可并排 MC2 vs OpenDots2。

### Phase 2 — 图片 BOM + 视频同构（3–4 周）

1. 总结段 PNG 强制 OCR → 合并 BOM；写入 `images_queue` 优先级队列。
2. 跑通 `enrich_video.py --pending`；转写后重跑 ingest 填 `views`。
3. `build_video_detail` 对齐报告五区块 + 角色透镜。
4. 对比页支持 `?ids=` 预选；详情页面包屑返回矩阵。

**验收**：cost 透镜 BOM 行数平均提升 50%+；至少 10 条视频有 ASR + 五区块展示。

### Phase 3 — 智能化与运营（持续）

1. 卖点 tag 与用户 HTML **9 类标签库**对齐（替换现有 loose keywords）。
2. 参数注释 tooltip、CSV 导出按角色列集。
3. 内部对标（`internal_compare`）在对比页高亮 Shokz 自有 SKU。
4. OCR 模型升级（PaddleOCR 表格模式）；视频 timeline 自动分段。
5. 可选：RSS webhook / 日更后自动 rebuild matrix。

---

## 7. 风险与约束

- OSS 图片 **Referer 防盗链**：OCR 下载必须带 `Referer: https://www.52audio.com/`。
- 个别稿件「智研所总结」需 fallback，避免 section 定位失败。
- 视频 ASR 芯片名误识别：需与 `lexicon.CHIP_PATTERNS` 交叉校正。
- 矩阵列过多：默认按角色折叠「高级列」，避免单表超 20 列不可用。

---

## 8. 参考文件

- 用户模板：`d:\成本管理\情报需要关注资料.html`
- 角色抽取：`core/views/role_extract.py`
- 矩阵构建：`scripts/build_matrix.py`、`scripts/build_site.py`
- 视频 enrich：`scripts/enrich_video.py`
- 设计基线：`docs/DESIGN.md`

---

*文档版本：V3 · 2026-07-03*
