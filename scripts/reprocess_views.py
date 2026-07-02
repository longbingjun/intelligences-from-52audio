"""批量刷新 views 与 data_completeness（结构化字段刷新例外，不改 id/url/captured_at）。

用法：
  py -3 scripts/reprocess_views.py
  py -3 scripts/reprocess_views.py --reports-only
  py -3 scripts/reprocess_views.py --videos-only
  py -3 scripts/reprocess_views.py --id 278349
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "data" / "cache" / "content_html"

from core.ingest import (  # noqa: E402
    REPORTS_DIR,
    VIDEOS_DIR,
    load_video_asr,
    refresh_views_fields,
    save_record_in_place,
)
from core.views.role_extract import extract_role_views, views_to_dict_with_completeness  # noqa: E402
from sources.audio52.source_v2 import Audio52SourceV2  # noqa: E402


def _text_items(items: list) -> list[str]:
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            t = item.get("text") or item.get("value") or ""
            if t:
                out.append(str(t))
        elif item:
            out.append(str(item))
    return out


def synthesize_content_html(record: dict) -> str:
    """无网络时从已有 views/summary 拼出伪 HTML，供二次抽取升级 schema。"""
    chunks: list[str] = []
    if record.get("summary"):
        chunks.append(f"<p>{record['summary']}</p>")
    v = record.get("views") or {}
    for sent in _text_items(v.get("market", {}).get("selling_points", [])):
        chunks.append(f"<p>{sent}</p>")
    for sent in v.get("structure", {}).get("assembly_notes", []) or []:
        chunks.append(f"<p>{sent}</p>")
    for sent in _text_items(v.get("structure", {}).get("internal_structure", [])):
        chunks.append(f"<p>{sent}</p>")
    for sent in v.get("cost", {}).get("packaging_notes", []) or []:
        chunks.append(f"<p>{sent}</p>")
    for spec in v.get("hardware", {}).get("specs", []) or []:
        param = spec.get("param") or spec.get("part", "")
        val = spec.get("value") or spec.get("model") or ""
        if val:
            chunks.append(f"<p>{param}：{val}</p>")
    for chip in v.get("cost", {}).get("chip_modules", []) or []:
        model = chip.get("model") or ""
        if model:
            chunks.append(f"<p>芯片 {model}</p>")
    return "\n".join(chunks)


def _cache_path(item_id: str) -> Path:
    return CACHE_DIR / f"{item_id}.html"


def resolve_content(source: Audio52SourceV2, record: dict, feed_index: dict[str, str]) -> tuple[str, str]:
    """返回 (content_html, source_label)。"""
    item_id = record["id"]
    cached = _cache_path(item_id)
    if cached.exists():
        html = cached.read_text(encoding="utf-8")
        if html.strip():
            return html, "cache"

    html = source.resolve_content_html(item_id, record.get("url", ""), feed_index)
    if html.strip():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(html, encoding="utf-8")
        return html, "rss_or_fetch"

    synth = synthesize_content_html(record)
    if synth.strip():
        return synth, "synthesized"
    return "", "none"


def _merge_views(base: dict, extra: dict) -> dict:
    """浅合并各区块列表字段（ASR/正文二次抽取补充）。"""
    out = json.loads(json.dumps(base))
    for section in ("market", "cost", "structure", "hardware", "software"):
        if section not in extra:
            continue
        b_sec = out.setdefault(section, {})
        e_sec = extra[section]
        for key, val in e_sec.items():
            if isinstance(val, list) and val:
                existing = b_sec.get(key) or []
                if not existing:
                    b_sec[key] = val
                elif key in ("codecs", "multipoint", "app_features", "ota_support", "latency_notes"):
                    seen = {json.dumps(x, ensure_ascii=False, sort_keys=True) for x in existing}
                    for item in val:
                        sig = json.dumps(item, ensure_ascii=False, sort_keys=True)
                        if sig not in seen:
                            existing.append(item)
                            seen.add(sig)
                    b_sec[key] = existing
            elif val and not b_sec.get(key):
                b_sec[key] = val
    return out


def reprocess_report(source: Audio52SourceV2, record: dict, feed_index: dict[str, str]) -> dict:
    item_id = record["id"]
    content_html, content_src = resolve_content(source, record, feed_index)
    if not content_html:
        return {"id": item_id, "status": "no_content", "completeness_before": record.get("data_completeness", 0)}

    views = extract_role_views(
        content_html,
        brand=record.get("brand", ""),
        model=record.get("model", ""),
        category=record.get("category", ""),
    )
    views_dict, completeness = views_to_dict_with_completeness(views)
    updated = refresh_views_fields(record, views_dict, completeness)
    save_record_in_place("report", updated)
    return {
        "id": item_id,
        "status": "ok",
        "content_src": content_src,
        "completeness_before": record.get("data_completeness", 0),
        "completeness_after": completeness,
        "selling_points": len(views_dict.get("market", {}).get("selling_points", [])),
        "chips": len(views_dict.get("cost", {}).get("chip_modules", [])),
        "key_images": len(views_dict.get("structure", {}).get("key_image_urls", [])),
    }


def reprocess_video(source: Audio52SourceV2, record: dict, feed_index: dict[str, str]) -> dict:
    item_id = record["id"]
    content_html, content_src = resolve_content(source, record, feed_index)
    asr = load_video_asr(item_id)
    asr_html = ""
    if asr and asr.get("transcript"):
        asr_html = f"<p>{asr['transcript']}</p>"

    if not content_html and not asr_html:
        return {"id": item_id, "status": "no_content", "completeness_before": record.get("data_completeness", 0)}

    views_dict: dict = {}
    completeness = 0.0

    if content_html:
        views = extract_role_views(
            content_html,
            brand=record.get("brand", ""),
            model=record.get("model", ""),
            category=record.get("category", ""),
        )
        views_dict, completeness = views_to_dict_with_completeness(views)

    if asr_html:
        asr_views = extract_role_views(
            asr_html,
            brand=record.get("brand", ""),
            model=record.get("model", ""),
            category=record.get("category", ""),
        )
        asr_dict, asr_comp = views_to_dict_with_completeness(asr_views)
        if views_dict:
            views_dict = _merge_views(views_dict, asr_dict)
            completeness = max(completeness, asr_comp)
        else:
            views_dict, completeness = asr_dict, asr_comp

    updated = refresh_views_fields(record, views_dict, completeness)
    save_record_in_place("video", updated)
    return {
        "id": item_id,
        "status": "ok",
        "content_src": content_src,
        "completeness_before": record.get("data_completeness", 0),
        "completeness_after": completeness,
        "has_embed": bool(record.get("video_embed_url")),
        "has_asr": bool(asr),
    }


def _load_json_dir(directory: Path) -> list[dict]:
    records = []
    for path in sorted(directory.glob("*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[skip] {path.name}: {e}")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="刷新全部 report/video 的 views 与 data_completeness")
    parser.add_argument("--reports-only", action="store_true")
    parser.add_argument("--videos-only", action="store_true")
    parser.add_argument("--id", help="仅处理指定 ID")
    parser.add_argument("--max-feed-pages", type=int, default=50)
    args = parser.parse_args()

    do_reports = not args.videos_only
    do_videos = not args.reports_only

    source = Audio52SourceV2(request_delay_sec=0.8, timeout=45)
    print("[reprocess] 构建 RSS 正文索引…")
    feed_index = source.build_feed_content_index(max_pages=args.max_feed_pages)
    print(f"[reprocess] RSS 索引 {len(feed_index)} 篇")

    stats = {
        "reports_ok": 0,
        "reports_no_content": 0,
        "reports_failed": 0,
        "videos_ok": 0,
        "videos_no_content": 0,
        "videos_failed": 0,
        "completeness_sum_before": 0.0,
        "completeness_sum_after": 0.0,
        "content_sources": {},
        "samples": [],
    }

    if do_reports:
        reports = _load_json_dir(REPORTS_DIR)
        if args.id:
            reports = [r for r in reports if r["id"] == args.id]
        print(f"[reprocess] 处理 {len(reports)} 条 report…")
        for i, rec in enumerate(reports, 1):
            try:
                result = reprocess_report(source, rec, feed_index)
                if result["status"] == "ok":
                    stats["reports_ok"] += 1
                    stats["completeness_sum_before"] += result.get("completeness_before", 0)
                    stats["completeness_sum_after"] += result.get("completeness_after", 0)
                    src = result.get("content_src", "unknown")
                    stats["content_sources"][src] = stats["content_sources"].get(src, 0) + 1
                    if len(stats["samples"]) < 3:
                        stats["samples"].append(result)
                    print(
                        f"  [{i}/{len(reports)}] {result['id']} "
                        f"完整度 {result.get('completeness_before', 0):.3f} → {result.get('completeness_after', 0):.3f}"
                    )
                else:
                    stats["reports_no_content"] += 1
                    print(f"  [{i}/{len(reports)}] {result['id']} 无正文")
                if result["id"] not in feed_index:
                    time.sleep(0.5)
            except Exception as e:
                stats["reports_failed"] += 1
                print(f"  [{i}/{len(reports)}] {rec['id']} 失败: {e}")

    if do_videos:
        videos = _load_json_dir(VIDEOS_DIR)
        if args.id:
            videos = [v for v in videos if v["id"] == args.id]
        print(f"[reprocess] 处理 {len(videos)} 条 video…")
        for i, rec in enumerate(videos, 1):
            try:
                result = reprocess_video(source, rec, feed_index)
                if result["status"] == "ok":
                    stats["videos_ok"] += 1
                    stats["completeness_sum_before"] += result.get("completeness_before", 0)
                    stats["completeness_sum_after"] += result.get("completeness_after", 0)
                    print(
                        f"  [{i}/{len(videos)}] {result['id']} "
                        f"完整度 {result.get('completeness_before', 0):.3f} → {result.get('completeness_after', 0):.3f}"
                    )
                else:
                    stats["videos_no_content"] += 1
                if result["id"] not in feed_index:
                    time.sleep(0.5)
            except Exception as e:
                stats["videos_failed"] += 1
                print(f"  [{i}/{len(videos)}] {rec['id']} 失败: {e}")

    total_ok = stats["reports_ok"] + stats["videos_ok"]
    if total_ok:
        stats["avg_completeness_before"] = round(stats["completeness_sum_before"] / total_ok, 3)
        stats["avg_completeness_after"] = round(stats["completeness_sum_after"] / total_ok, 3)

    print("\n=== reprocess 统计 ===")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
