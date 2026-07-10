# 52 情报站 — 竞品成本工作台

我爱音频网拆解分类情报站：面向**成本工程师**，按品类勾选产品、横向对比 BOM / 芯片 / 电池等成本参数。

## 功能

- **品类对比画布** `/category/{品类}`：搜索、筛选、勾选产品，动态生成对比表
- **产品档案** `/product/{id}`：成本快照 + 分组 BOM
- **拆解报告** `/report/{id}`：BOM 摘要 + 外链 52audio 原文
- **数据层**：按 ID 分文件存储，支持 OCR / 渠道价 enrich

## 本地构建（V5 Astro）

```powershell
py -3 -m pip install -r requirements.txt

# 推荐：耳机专用 ETL（产品 → 开箱 → 矩阵 → Web）
py -3 scripts/build_all.py

# 或分步
py -3 scripts/build_products.py
py -3 scripts/enrich_unboxing.py --headphones
py -3 scripts/build_products.py
py -3 scripts/build_matrix.py
py -3 scripts/prepare_web_data.py
cd web; npm install; npm run build
```

**数据范围**：仅保留耳机品类（TWS / 开放式 / 头戴 / 有线 / 骨传导 / 颈挂）。爬虫与新入库会自动跳过音箱、手表、眼镜等。

产物输出到 `site/`（GitHub Pages 根目录）。`prepare_web_data.py` 会同步 JSON 并清理旧版多角色静态页。

## 拆解视频 ASR（B 站）

```powershell
# 批量转写（yt-dlp 拉音频 + faster-whisper，B 站字幕需登录故走 ASR）
py -3 scripts/enrich_video.py --pending

# 合并转写稿到 views，刷新芯片/BOM 抽取
py -3 scripts/reprocess_views.py --videos-only

py -3 scripts/build_products.py
py -3 scripts/report_video_asr_impact.py
```

依赖：`yt-dlp`、`faster-whisper`（已写入 requirements.txt）。首条会下载 Whisper 模型，约 10 分钟/视频。

```powershell
# 单产品
py -3 scripts/enrich_commerce.py huawei--freebuds-pro-5

# 批量耳机（全部）
py -3 scripts/enrich_commerce.py --headphones

# 重建产品主数据（价格写入 cost_snapshot，enrich 独立存 staging）
py -3 scripts/build_products.py
py -3 scripts/list_commerce_unresolved.py
```

## 数据布局（ETL Phase 1）

路径由 `core/paths.py` 统一管理；迁移期**双写** `curated/` + 遗留目录。

```
data/
  raw/reports/          # 目标：拆解报告（当前仍可用 reports/）
  staging/channel/      # 渠道价 enrich（镜像 enrich/channel/）
  staging/official/     # 官网 enrich
  curated/products/     # 产品主数据（镜像 products/）
  compare/              # 品类对比 JSON
  matrix/               # 成本矩阵 JSON
  manifest.json         # 构建步骤记录
```

产品 JSON **不再内嵌** `channel_enrich` / `official_enrich`，仅保留 `layer_refs` 与 `cost_snapshot` 中的价格字段。

## 售价 / 渠道价补录

```powershell
py -3 scripts/import_prices.py data/enrich/channel/example.csv
py -3 scripts/build_products.py
py -3 scripts/build_matrix.py
```

## 部署

推送到 `master` 后 GitHub Actions 自动：预处理数据 → `npm run build` → 部署 Pages。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md) | 项目目标、五层开发框架、现状与路线图 |
| [docs/ARCHITECTURE_V5_UI.md](docs/ARCHITECTURE_V5_UI.md) | 当前 UI 与构建说明 |
| [docs/ARCHITECTURE_V4.md](docs/ARCHITECTURE_V4.md) | 四层信源与成本矩阵 |
| [docs/DESIGN.md](docs/DESIGN.md) | 数据源与抽取设计 |
| [docs/README.md](docs/README.md) | 完整文档索引 |

开发新功能前请先阅读 [PROJECT_ROADMAP.md](docs/PROJECT_ROADMAP.md) 中的开发宪章与 Gate 规则。  
规划任务可在 GitHub **Issues → New issue** 选择 V6 模板或「迭代工作单」。
