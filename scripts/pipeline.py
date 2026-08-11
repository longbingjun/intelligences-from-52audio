#!/usr/bin/env python3
"""Single entry point for ETL derivation and static-site builds.

Examples:
  python scripts/pipeline.py derive
  python scripts/pipeline.py derive --with-ai
  python scripts/pipeline.py site
  python scripts/pipeline.py all --with-ai
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
WEB = ROOT / "web"


def run_script(name: str, *args: str, env: dict[str, str] | None = None) -> dict:
    command = [sys.executable, str(SCRIPTS / name), *args]
    child_env = dict(os.environ)
    child_env.update(env or {})
    child_env.setdefault("PYTHONIOENCODING", "utf-8")
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        sys.stderr.write(completed.stderr or completed.stdout)
        raise SystemExit(completed.returncode)
    output = completed.stdout.strip()
    try:
        return json.loads(output or "{}")
    except json.JSONDecodeError:
        return {"stdout": output}


def derive(*, with_ai: bool, with_unboxing: bool, prune: bool) -> dict:
    stats: dict[str, object] = {}
    stats["search_index"] = run_script("build_search_index.py")
    stats["products"] = run_script("build_products.py")
    if prune:
        stats["prune"] = run_script("prune_non_headphones.py")
    if with_unboxing:
        stats["unboxing"] = run_script("enrich_unboxing.py", "--headphones")
        stats["products_after_unboxing"] = run_script("build_products.py")
    stats["identity_review"] = run_script("build_identity_review.py")
    stats["priority"] = run_script("build_product_priority.py")
    if with_ai:
        stats["selling_point_summaries"] = run_script("summarize_selling_points.py")
        stats["roundup_summaries"] = run_script("summarize_roundup_insights.py")
    stats["matrix"] = run_script("build_matrix.py")
    stats["source_layers"] = run_script("tag_source_layer.py")
    return stats


def build_site(*, prepare: bool = True) -> dict:
    stats: dict[str, object] = {}
    if prepare:
        stats["web_data"] = run_script("prepare_web_data.py")
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise SystemExit("npm was not found; install Node.js before building the site")
    completed = subprocess.run([npm, "run", "build"], cwd=WEB)
    if completed.returncode:
        raise SystemExit(completed.returncode)
    stats["legacy_redirects"] = run_script("generate_legacy_redirects.py")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="52audio ETL and site pipeline")
    parser.add_argument("stage", choices=("derive", "site", "all"))
    parser.add_argument("--with-ai", action="store_true", help="refresh incremental DeepSeek caches")
    parser.add_argument("--with-unboxing", action="store_true", help="refresh source article unboxing extraction")
    parser.add_argument("--prune", action="store_true", help="remove out-of-scope derived records")
    args = parser.parse_args()

    stats: dict[str, object] = {}
    if args.stage in {"derive", "all"}:
        stats["derive"] = derive(
            with_ai=args.with_ai,
            with_unboxing=args.with_unboxing,
            prune=args.prune,
        )
    if args.stage in {"site", "all"}:
        stats["site"] = build_site(prepare=True)
    # ASCII escaping keeps the orchestration command portable on Windows GBK
    # terminals while every underlying data file remains UTF-8.
    print(json.dumps(stats, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
