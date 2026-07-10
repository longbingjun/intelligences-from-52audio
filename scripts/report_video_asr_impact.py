#!/usr/bin/env python3
"""对比视频 ASR 前后 BOM/芯片/完整度变化。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest import load_all_records  # noqa: E402


def _bom_stats(views: dict) -> dict:
    cost = views.get("cost") or {}
    bom = cost.get("bom_table") or []
    chips = cost.get("chip_modules") or []
    models = [c.get("model") for c in chips if c.get("model")]
    bom_models = [r.get("model") for r in bom if r.get("model")]
    return {
        "bom_rows": len(bom),
        "chip_modules": len(chips),
        "chip_models": models,
        "bom_models": bom_models,
        "selling_points": len((views.get("market") or {}).get("selling_points") or []),
    }


def main() -> None:
    videos = load_all_records("video")
    rows = []
    for v in videos:
        views = v.get("views") or {}
        stats = _bom_stats(views)
        rows.append(
            {
                "id": v["id"],
                "brand": v.get("brand"),
                "model": v.get("model"),
                "asr_status": v.get("asr_status"),
                "completeness": v.get("data_completeness"),
                **stats,
            }
        )
    done = [r for r in rows if r["asr_status"] == "done"]
    summary = {
        "videos": len(rows),
        "asr_done": len(done),
        "avg_completeness": round(sum(r["completeness"] or 0 for r in rows) / max(len(rows), 1), 3),
        "avg_bom_rows": round(sum(r["bom_rows"] for r in rows) / max(len(rows), 1), 2),
        "with_chip_model": sum(1 for r in rows if r["chip_models"]),
        "samples": sorted(done, key=lambda x: x["bom_rows"], reverse=True)[:5],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
