"""用 DeepSeek 在构建阶段为产品卖点生成可缓存的中文摘要。

密钥只从 DEEPSEEK_API_KEY 环境变量读取，绝不写入仓库。相同源文本会跳过请求，
因此可安全地放入日常构建流程。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.paths import products_dir

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash"
# 产品主数据会在 build_products 中重建，不能把增量判断只存在产品 JSON 内。
# 独立缓存会随 data/ 一起提交，因此每日 workflow 与本地构建都能复用。
CACHE_DIR = ROOT / "data" / "enrich" / "llm_summaries"
CACHE_FILE = CACHE_DIR / "index.json"
SYSTEM_PROMPT = """你是消费电子产品研究编辑。根据提供的中文卖点原文，生成不超过 6 条结构化摘要。
只可使用原文明确支持的事实，不能补充规格、结论或营销判断。合并重复点；每条 18-48 个中文字符，清晰具体。
必须只返回 JSON 对象，格式：{\"summary\":[{\"tag\":\"分类标签\",\"text\":\"精炼卖点\"}]}。"""


def source_hash(points: list[dict]) -> str:
    raw = [{"tag": p.get("tag", ""), "tags": p.get("tags", []), "text": p.get("text", "")} for p in points]
    return hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def summarize(api_key: str, points: list[dict]) -> list[dict]:
    source = [{"tag": p.get("tag", ""), "tags": p.get("tags", []), "text": p.get("text", "")} for p in points]
    response = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "thinking": {"type": "disabled"},
            "temperature": 0.2,
            "max_tokens": 700,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps({"selling_points": source}, ensure_ascii=False)},
            ],
        },
        timeout=45,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    rows = parsed.get("summary", [])
    if not isinstance(rows, list):
        raise ValueError("DeepSeek response missing summary list")
    result = []
    for row in rows[:6]:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text", "")).strip()
        if text:
            result.append({"tag": str(row.get("tag", "其他")).strip() or "其他", "text": text[:80]})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="最多处理的产品数，0 表示全部")
    args = parser.parse_args()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print(json.dumps({"skipped": True, "reason": "DEEPSEEK_API_KEY is not set"}, ensure_ascii=False))
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cache_index = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    except json.JSONDecodeError:
        cache_index = {}
    if not isinstance(cache_index, dict):
        cache_index = {}

    api_calls = cache_hits = failed = 0
    paths = [p for p in sorted(products_dir().glob("*.json")) if p.name != "index.json"]
    for path in paths:
        if args.limit and api_calls + cache_hits + failed >= args.limit:
            break
        product = json.loads(path.read_text(encoding="utf-8"))
        market = product.get("market") or {}
        points = [p for p in market.get("selling_points", []) if isinstance(p, dict) and str(p.get("text", "")).strip()]
        if not points:
            cache_hits += 1
            continue
        fingerprint = source_hash(points)
        canonical_id = product["canonical_id"]
        cached = cache_index.get(canonical_id, {})

        # 只有「源文本不变 + 已有摘要」才命中缓存。没有摘要的基线记录会在首次运行补齐，
        # 此后新增或文本变更的产品才会再次调用 API。
        if cached.get("source_hash") == fingerprint and cached.get("summary"):
            market["selling_points_summary"] = cached["summary"]
            market["selling_points_summary_meta"] = {"model": cached.get("model", MODEL), "source_hash": fingerprint}
            product["market"] = market
            path.write_text(json.dumps(product, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            cache_hits += 1
            continue
        try:
            summary = summarize(api_key, points)
            market["selling_points_summary"] = summary
            market["selling_points_summary_meta"] = {"model": MODEL, "source_hash": fingerprint}
            product["market"] = market
            path.write_text(json.dumps(product, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            cache_index[canonical_id] = {"model": MODEL, "source_hash": fingerprint, "summary": summary}
            api_calls += 1
        except Exception as exc:  # 单个产品失败不阻断整批构建
            failed += 1
            print(f"[warn] {path.stem}: {exc}")
    CACHE_FILE.write_text(json.dumps(cache_index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"api_calls": api_calls, "cache_hits": cache_hits, "failed": failed, "model": MODEL}, ensure_ascii=False))


if __name__ == "__main__":
    main()
