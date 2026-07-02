# 52 情报站 v2

我爱音频网拆解分类情报站：按 ID 追加存储、五区块角色透镜、日更增量抓取。

## v2 优化要点

- **按 ID 分文件**：`data/reports/{id}.json`、`data/videos/{id}.json`，追加写入、不覆盖历史。
- **无 `content_html` 转载**：详情页只展示结构化 `views`（市场/成本/结构/硬件/软件五区块），原文链接跳转源站。
- **角色透镜**：子级详情页按职能过滤区块（产品经理 / 成本 / 结构 / 硬件 / 软件）。
- **解耦 enrich**：售价、OCR、视频 ASR 各自写入 `data/enrich/`，构建站点或合并脚本再汇入主记录。
- **CI 构建链**：部署前依次尝试 `build_search_index` → `build_products` → `build_matrix`（脚本存在才执行）→ `build_site`。

## 快速开始

```powershell
py -3 -m pip install -r requirements.txt

# 首次：迁移旧数据（如有）+ 2026 年全量 backfill
py -3 scripts/migrate_v1_to_v2.py
py -3 scripts/crawl_v2.py --mode backfill-2026

# 日常日更（仅 RSS 第 1 页新 ID）
py -3 scripts/crawl_v2.py --mode daily

# 构建静态站
py -3 scripts/build_site.py
```

## 数据布局

```
data/
  index.json           # 已入库 ID 索引
  reports/{id}.json    # 拆解报告（无 content_html）
  videos/{id}.json     # 拆解视频元数据
  enrich/prices/       # 人工售价 CSV 导入
  enrich/ocr/          # 报告图片 OCR 结果（解耦）
  enrich/videos/       # 视频 ASR 结果（解耦）
```

## 角色透镜

子级详情页按职能过滤区块：产品经理(A–E)、成本工程师(B–E)、结构/硬件/软件各看本域。

## 售价补录

```powershell
py -3 scripts/import_prices.py data/enrich/prices/example.csv
py -3 scripts/build_site.py
```

## 视频 ASR（解耦）

```powershell
py -3 scripts/enrich_video.py --id 281250
# 或 GitHub Actions: video-enrich.yml workflow_dispatch
```

## OCR enrich（解耦）

对文本密集图（规格表/铭牌）跑 tesseract；本机未装 Tesseract 时标记 `pending`。

```powershell
py -3 -m enrichers.ocr --id 265818
py -3 scripts/merge_ocr.py --id 265818
# 或 GitHub Actions: ocr-enrich.yml workflow_dispatch
```

售价 CSV 格式说明见 [data/enrich/prices/README.md](data/enrich/prices/README.md)。

站点：https://longbingjun.github.io/intelligences-from-52audio/
