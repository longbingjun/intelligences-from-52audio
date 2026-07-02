# 售价人工补录（P4）

通过 CSV 批量导入产品售价，生成 `data/enrich/prices/{id}.json`，构建站点时合并进 `views.market`。

## CSV 格式

首行为表头，UTF-8（可带 BOM）。列名固定：

| 列名 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 报告或视频 ID，与 `data/reports/{id}.json` / `data/videos/{id}.json` 一致 |
| `price_cny` | 否 | 人民币售价（数字，可含小数） |
| `price_source` | 否 | 来源标识，默认 `manual_csv` |
| `price_url` | 否 | 标价页面链接（京东/天猫等） |
| `price_note` | 否 | 备注（如「京东自营标价」「首发价」） |

## 示例

```csv
id,price_cny,price_source,price_url,price_note
281175,299,manual_csv,https://item.jd.com/example,京东自营标价
265818,199,jd,https://item.jd.com/xxx,活动价
```

以 `#` 开头的行会被 `import_prices.py` 忽略（若写在文件里请确保 DictReader 能跳过——推荐用独立注释行仅作文档，实际数据行不要带 `#`）。

## 导入

```powershell
py -3 scripts/import_prices.py data/enrich/prices/your_batch.csv
py -3 scripts/build_site.py
```

每条记录写入独立 JSON，例如 `281175.json`：

```json
{
  "price_cny": 299.0,
  "price_source": "manual_csv",
  "price_url": "https://item.jd.com/example",
  "price_note": "京东自营标价",
  "price_captured_at": "2026-07-02"
}
```
