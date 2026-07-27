#!/usr/bin/env python3
"""Test SMZDM OpenAPI credentials from .env."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources.channel.smzdm_client import fetch_smzdm_prices, smzdm_configured  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brand", default="华为")
    parser.add_argument("--model", default="FreeBuds Pro 3")
    parser.add_argument("--keyword", help="override search keyword")
    args = parser.parse_args()

    if not smzdm_configured():
        print("Missing SMZDM_APP_KEY / SMZDM_APP_SECRET in .env")
        print("Apply via group-content@zhidemai.com")
        sys.exit(1)

    info = fetch_smzdm_prices(brand=args.brand, model=args.model, query=args.keyword)
    print(json.dumps(info.to_dict(), ensure_ascii=False, indent=2))
    if info.fetch_error and not info.best_hit:
        sys.exit(2)


if __name__ == "__main__":
    main()
