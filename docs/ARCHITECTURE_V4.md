# 52audio 情报站架构 V4 — 成本工程师优先

> 主用户：成本工程师。技术层（52audio）已接入；渠道层 CSV 导入已接入；官方/评测层占位。

## 导航顺序

```
首页 → 成本矩阵（?role=cost） → 同品类对比大表 → 产品成本摘要 → 拆解报告深页 → 52audio 原文
```

## 四层信源

| 层 | source_layer | 状态 | 数据路径 |
|----|--------------|------|----------|
| 技术层 | technical | 已接入 | data/reports, data/videos |
| 渠道层 | channel | CSV 导入 | data/enrich/channel/{canonical_id}.json |
| 官方层 | official | 占位 | sources/official/ |
| 评测层 | review | 占位 | sources/review/ |

融合规则（build_products）：
- BOM/芯片/电池：技术层报告，`data_completeness` + `bom_table` 长度最高者
- 售价：渠道 enrich 优先，其次报告文本抽取

## 核心数据

- **产品实体** `data/products/{canonical_id}.json`：含 `cost_snapshot`、`bom_table`、`layer_refs`
- **矩阵** `data/matrix/{品类}.json`：成本列优先，`default_role=cost`
- **对比** `data/compare/{品类}.json`：行=成本参数，列=产品

## 成本矩阵列

brand, model, price_cny, main_chip, pmic, battery_ear, battery_case, speaker, materials, weight_g, ip_rating, bluetooth, bom_rows, layer_badges, data_completeness

列注释来源：`data/field_annotations.json`（含 `matrix_columns.cost`）

## BOM 图片 OCR 闭环

1. `enrichers/ocr.py` — 优先 `summary_image_urls`，`parse_bom_table_from_ocr()`
2. `data/enrich/ocr/{report_id}.json` — 含 `bom_rows_extracted`
3. `scripts/merge_ocr.py` — 合并进 `views.cost.bom_table`（不覆盖高置信度 summary_prose）
4. CI：`workflow_dispatch` + `run_merge_ocr=true` 可选触发

## 渠道层导入

```bash
python scripts/import_prices.py data/enrich/channel/example.csv
python scripts/build_products.py
python scripts/build_matrix.py
python scripts/build_site.py
```

CSV 列：`canonical_id,price_cny,price_source,channel_url,sales_hint,price_note`

## 构建流水线

```bash
python scripts/tag_source_layer.py      # 一次性：补 source_layer=technical
python scripts/build_search_index.py
python scripts/build_products.py        # 含 cost_snapshot
python scripts/build_matrix.py          # 含 compare JSON
python scripts/build_site.py            # 含 products/ 摘要页
```

## 站点页面

| 页面 | 路径 |
|------|------|
| 成本矩阵 | site/matrix/index.html |
| 同品类大表 | site/compare/{品类}.html |
| 产品成本摘要 | site/products/{canonical_id}.html |
| 报告深页 | site/reports/{id}.html?role=cost |

## 信源注册

`sources/registry.py` — 技术层 audio52 + 渠道/官方/评测描述符（`SourceDescriptor`）

与 v2 爬虫接口 `core/base_source.py` 并存，不破坏现有 `crawl_v2.py`。
