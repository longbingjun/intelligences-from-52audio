#!/usr/bin/env python3
"""一键跑通 ETL 主链路：产品主数据 → 开箱 enrich → 矩阵/对比 → Web 发布数据。

用法:
  py -3 scripts/build_all.py
  py -3 scripts/build_all.py --skip-unboxing
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(script: str, *args: str) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout, file=sys.stderr)
        raise SystemExit(proc.returncode)
    try:
        return json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"stdout": proc.stdout.strip()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-matrix", action="store_true")
    parser.add_argument("--skip-unboxing", action="store_true")
    parser.add_argument("--skip-prune", action="store_true")
    args = parser.parse_args()

    stats: dict = {}
    stats["build_products"] = _run("build_products.py")
    if not args.skip_prune:
        stats["prune_non_headphones"] = _run("prune_non_headphones.py")
    if not args.skip_unboxing:
        stats["enrich_unboxing"] = _run("enrich_unboxing.py", "--headphones")
        stats["build_products_after_unboxing"] = _run("build_products.py")
    if not args.skip_matrix:
        stats["build_matrix"] = _run("build_matrix.py")
    stats["prepare_web_data"] = _run("prepare_web_data.py")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
