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

py scripts/build_products.py
py scripts/build_matrix.py
py scripts/prepare_web_data.py
cd web; npm install; npm run build
```

产物输出到 `site/`（GitHub Pages 根目录）。`prepare_web_data.py` 会同步 JSON 并清理旧版多角色静态页。

## 数据布局

```
data/
  index.json
  reports/{id}.json
  videos/{id}.json
  products/{canonical_id}.json
  compare/{品类}.json
  matrix/{品类}.json
  enrich/prices/
  enrich/ocr/
  enrich/channel/
```

## 售价 / 渠道价补录

```powershell
py scripts/import_prices.py data/enrich/channel/example.csv
py scripts/build_products.py
py scripts/build_matrix.py
```

## 部署

推送到 `master` 后 GitHub Actions 自动：预处理数据 → `npm run build` → 部署 Pages。

详见 `docs/ARCHITECTURE_V5_UI.md`。
