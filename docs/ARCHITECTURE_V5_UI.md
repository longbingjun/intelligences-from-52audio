# V5 UI — 品类筛选 + 产品自选对比（成本工程师专用）

本站仅保留**成本工程师**视图，不再提供产品/结构/硬件/软件等多角色透镜。底层 `views` JSON 仍含完整抽取结果，供后续扩展；前端与矩阵只展示成本相关字段。

## 功能

- **工作台** `/`：按品类进入，展示各品类产品数量
- **品类对比画布** `/category/{品类名}`：
  - 品类 Tab 切换
  - 搜索品牌/型号、按品牌筛选、仅看有拆解报告
  - **勾选要对比的产品**（用户控制列数）
  - 对比表只显示已选产品
  - URL 分享：`?ids=canonical-id-1,canonical-id-2`
  - localStorage 记住每个品类的上次选择
- **产品档案** `/product/{canonical_id}`：成本快照 + 分组 BOM
- **拆解报告** `/report/{id}`：BOM 摘要 + 外链 52audio

## 本地构建

```bash
py scripts/build_products.py
py scripts/build_matrix.py
py scripts/prepare_web_data.py
cd web && npm install && npm run build
```

产物输出到 `site/`（GitHub Pages 根目录）。

## 技术栈

- Astro 5 + React islands（`CompareWorkbench`）
- Tailwind CSS 4
- 数据：`web/public/data/`（由 `prepare_web_data.py` 从 `data/` 同步）

## 对比参数配置

`data/compare_profiles.json` — 按品类定义 P0/P1 默认参数行。
