#!/usr/bin/env python3
"""Test JD Union API credentials from .env."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources.channel.jd_union_client import get_client, union_configured  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sku", help="JD SKU id, e.g. 10192266796615")
    parser.add_argument("--keyword", help="Search keyword")
    args = parser.parse_args()

    if not union_configured():
        print("Missing JD_UNION_APP_KEY / JD_UNION_APP_SECRET in .env")
        print("Copy .env.example to .env and fill in AppKey + AppSecret.")
        sys.exit(1)

    client = get_client()
    assert client is not None

    try:
        if args.sku:
            hits = client.get_goods_detail([args.sku])
            print(json.dumps({"mode": "detail", "hits": [h.to_dict() for h in hits]}, ensure_ascii=False, indent=2))
            return

        keyword = args.keyword or "HUAWEI FreeBuds Pro 3"
        hits = client.search_goods(keyword)
        print(
            json.dumps(
                {"mode": "search", "keyword": keyword, "hits": [h.to_dict() for h in hits[:5]]},
                ensure_ascii=False,
                indent=2,
            )
        )
    except RuntimeError as e:
        print(f"API error: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
