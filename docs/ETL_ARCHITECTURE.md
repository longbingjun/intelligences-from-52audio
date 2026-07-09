# ETL 数据架构评估与迁移建议

> 面向小团队的务实三层方案，非重型 medallion 平台。  
> 评估日期：2026-07-09

---

## 1. 现状痛点（诚实评估）

### 1.1 数据散落、职责重叠

| 路径 | 实际内容 | 问题 |
|------|----------|------|
| `data/reports/`、`data/videos/` | 52audio 原始拆解/视频记录 | **Bronze 层**，设计合理 |
| `data/enrich/channel\|official\|unboxing\|prices\|videos/` | 各来源 enrich 补丁 | 与 `data/products/` 内嵌 `*_enrich` 字段**双写** |
| `data/products/` | 产品聚合主数据 + `cost_snapshot` + 内嵌 enrich | **Silver+Gold 混在一起**，单文件过大 |
| `data/matrix/`、`data/compare/` | 矩阵/对比视图 | 应由 products 派生，却独立维护 |
| `web/public/data/` | Astro 构建用副本 | `prepare_web_data.py` **整目录拷贝**，易 stale |
| `site/` | 旧版静态站 + `site/data/products/` | V3/V4 遗留，与 V5 Astro **三份产品 JSON** |

### 1.2 流水线不清晰

```
crawl_v2 → reports/videos
build_products → products/（读 reports，偶尔 merge enrich）
enrich_commerce → enrich/channel + enrich/official（不写回 products 除非再跑 build）
build_matrix → matrix/ + compare/（再读 products + enrich）
prepare_web_data → web/public/data/（拷贝 products + compare）
build_site → site/（另一套生成路径）
```

- **无单一「真相源」**：价格可能在 `enrich/channel`、`products.cost_snapshot`、`products.channel_enrich` 三处不一致（如 baseus MC2 曾出现 ZOL 错链 19 元 vs JD 349 元）。
- **脚本顺序靠人工记忆**，缺少 manifest / 依赖声明。
- **flat JSON sprawl**：百余产品 × 多目录 ≈ 上千文件，git diff 噪音大。

### 1.3 什么做得对

- `canonical_id` 稳定键设计良好。
- `source_layer`（technical / channel / official / review）概念清晰。
- `data/config/commerce_hints.json` 作为人工 override 层合理。
- `core/ingest.py` append-only 原始层符合审计需求。

---

## 2. 推荐架构：务实三层（小团队版）

不引入 Spark/DBT/数据湖；用**目录约定 + 单一构建入口**达到 medallion 80% 收益。

```
data/
├── raw/                    # Bronze — 只追加、不改造
│   ├── reports/{id}.json
│   ├── videos/{id}.json
│   └── cache/              # HTML 缓存（可选，从 data/cache 迁入）
│
├── staging/                # Silver — 按来源 enrich，可覆盖
│   ├── channel/{canonical_id}.json
│   ├── official/{canonical_id}.json
│   ├── unboxing/{id}.json
│   └── config/             # commerce_hints 等
│
├── curated/                # Gold — 面向消费的聚合
│   ├── products/{canonical_id}.json   # 瘦产品实体，无冗余 embed
│   ├── products/index.json
│   ├── matrix/{category}.json
│   └── compare/{category}.json
│
└── manifest.json           # 各层 generated_at、行数、脚本版本
```

**发布层（非 source of truth）**：

```
web/public/data/  ← 仅从 data/curated/ 同步，永不手改
```

**废弃/只读归档**：`site/`、`data/products/`（迁移期 symlink 或兼容读取）。

### 2.1 层间规则

| 层 | 写入者 | 读取者 | 可覆盖？ |
|----|--------|--------|----------|
| raw | `crawl_v2` | staging 脚本 | 否（append-only） |
| staging | `enrich_*` | `build_products` | 是 |
| curated | `build_products`, `build_matrix` | `prepare_web_data`, 分析脚本 | 是（可重建） |
| web/public | `prepare_web_data` | Astro | 否（生成物） |

### 2.2 统一 enrich 输出 schema（staging）

所有 `staging/*/canonical_id.json` 共享外壳：

```json
{
  "canonical_id": "brand--model",
  "source_layer": "channel|official|unboxing",
  "captured_at": "2026-07-09",
  "payload": { }
}
```

`payload` 内为各层专有字段；`build_products` 合并时只读 `payload`，避免字段漂移。

---

## 3. 迁移路径（分阶段）

### Phase 0 — 文档与约定（当前，低成本）

- [x] 本文档确立目标布局
- [ ] 在 `README` 增加「数据流水线顺序」一节
- [ ] `products/*.json` 停止内嵌完整 `channel_enrich`/`official_enrich`（改为 `layer_refs` 指针，**已部分存在**）

### Phase 1 — 目录别名（1–2 天）

| 现路径 | 新路径 | 脚本改动 |
|--------|--------|----------|
| `data/reports` | `data/raw/reports` | `core/ingest.py` 路径常量 |
| `data/videos` | `data/raw/videos` | 同上 |
| `data/enrich/*` | `data/staging/*` | `enrich_commerce.py`, `core/products.py` |
| `data/products` | `data/curated/products` | `build_products.py` |

实现方式：**先 symlink 或 Path 兼容层**（`core/paths.py` 单点配置），避免一次性移动上千文件。

### Phase 2 — 构建链收敛（2–3 天）

1. 新增 `scripts/build_all.py`（或 `make data`）：
   ```
   crawl_v2 → enrich_commerce → build_products → build_matrix → prepare_web_data
   ```
2. `build_products`：**只**从 raw + staging 合并，写出 curated/products；不再把 enrich 嵌入产品 JSON。
3. `prepare_web_data`：只拷贝 `curated/`，写入 `manifest.json`。
4. 标记 `site/`、`scripts/build_site.py` 为 deprecated。

### Phase 3 — 清理（按需）

- 删除 `site/data/` 副本
- 合并 `data/enrich/prices` 入 `staging/channel` 或废弃
- 对 `unknown--*` 产品做品牌归一化减少文件数

---

## 4. 脚本 → 角色映射

| 脚本 | 现角色 | 目标角色 |
|------|--------|----------|
| `crawl_v2.py` | 抓取 52audio | **raw 写入器** |
| `enrich_commerce.py` | ZOL/JD/官网价 | **staging/channel + staging/official** |
| `enrich_video.py` | 视频 ASR 等 | **staging/review** |
| `extract_unboxing_sample.py` | 开箱结构化 | **staging/unboxing** |
| `build_products.py` | 产品聚合 | **curated/products 构建器** |
| `build_matrix.py` | 矩阵/对比 | **curated/matrix + compare** |
| `prepare_web_data.py` | 拷贝到 web | **发布同步器**（唯一出口） |
| `build_site.py` | 旧静态站 | **废弃** |
| `import_prices.py` | 手工价导入 | 合并入 `staging/config` 或 hints |

---

## 5. 原则（防止再次臃肿）

1. **raw 永不改** — 纠错走 staging override 或 `commerce_hints`。
2. **curated 可删可重建** — 任何 curated 文件不得手改。
3. **web/public 是镜像** — 不当作数据源。
4. **一个 canonical_id 一个产品文件** — enrich 分文件存放，合并时 join。
5. **manifest 记录每次构建** — 便于排查「页面价与 enrich 不一致」。

---

## 6. 与本次 commerce enrich 改动的关系

`enrich_commerce.py` 现已支持：ZOL 失败 / 错链 → `search_official_site()` → 官网 MSRP 兜底写入 `staging/official` 并可合并进 channel。

后续 `build_products` 应以 `staging/channel.price_cny` 为优先价源，避免再次从 ZOL 错链 report 级价格污染 `cost_snapshot`。
