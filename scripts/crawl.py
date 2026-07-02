"""爬虫主入口：跑一遍所有已注册的情报源，把结果落盘到 data/。

用法：
    py -3 scripts/crawl.py                       # 默认抓 52audio 最近 30 条
    py -3 scripts/crawl.py --limit 20             # 只抓 20 条
    py -3 scripts/crawl.py --no-images            # 跳过图片下载/分析（调试时更快）

新增情报源时，只需要在 SOURCES 里 append 一个新的 Source 实例。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pipeline import run_sources  # noqa: E402
from sources.audio52.source import Audio52Source  # noqa: E402


def build_sources(fetch_images: bool) -> list:
    return [
        Audio52Source(fetch_images=fetch_images),
        # 未来新增情报源示例：
        # OtherSiteSource(),
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="情报网站爬虫 - 抓取并落盘结构化数据")
    parser.add_argument("--limit", type=int, default=30, help="每个情报源最多抓取的条目数")
    parser.add_argument("--no-images", action="store_true", help="跳过图片下载与图片分类/OCR 分析")
    args = parser.parse_args()

    sources = build_sources(fetch_images=not args.no_images)
    stats = run_sources(sources, limit_per_source=args.limit)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
