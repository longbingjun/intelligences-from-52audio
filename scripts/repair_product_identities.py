#!/usr/bin/env python3
"""Resolve ambiguous product identities from the original 52audio article.

This creates an auditable staging layer rather than changing raw reports.  It
may split a roundup/comparison article into several headphones, but only when
the model returns quoted source evidence and a high-confidence, exact identity.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.ingest import load_all_records  # noqa: E402
from core.paths import identity_overrides_path  # noqa: E402
from core.products import identity_review_reason, normalize_brand, normalize_model  # noqa: E402

MODEL = "deepseek-v4-flash"
MAX_ARTICLE_CHARS = 14_000
PROMPT = """You are resolving product identities from an original 52audio article.
Return JSON only. Decide whether the article is about one headphone product,
multiple distinct headphone products, or not a headphone product. Do not infer
names not supported by the supplied article text. For each product, return the
consumer brand, the exact sellable model (without teardown/review wording), a
headphone category, confidence from 0 to 1, and a short exact evidence quote.
Use decision one of: single_headphone, multi_headphone, not_headphone, needs_review.
For an article comparing or summarising several products, use multi_headphone
and list each identifiable product. A generic term such as Buds/Earbuds without
a distinguishing model must be needs_review. JSON schema:
{"decision":"...","reason":"...","products":[{"brand":"","model":"","category":"","confidence":0,"evidence_quote":""}]}"""


def article_text(url: str) -> str:
    response = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; 52audio-identity-repair/1.0)"}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup.select("script, style, noscript, svg, nav, footer"):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)[:MAX_ARTICLE_CHARS]


def is_candidate(record: dict) -> bool:
    brand = normalize_brand(str(record.get("brand") or ""))
    model = normalize_model(str(record.get("model") or ""), brand)
    title = str(record.get("title") or "")
    return bool(
        not brand
        or len(model) > 48
        or identity_review_reason(brand, model, title)
        or any(marker in title.lower() for marker in ("对比", "汇总", "盘点", "top", "合集"))
    )


def deepseek_identity(api_key: str, record: dict, text: str) -> dict:
    payload = {
        "source": {"url": record.get("url"), "title": record.get("title"), "existing_brand": record.get("brand"), "existing_model": record.get("model")},
        "article_text": text,
    }
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": MODEL, "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": 900,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": PROMPT}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]},
        timeout=60,
    )
    response.raise_for_status()
    return json.loads(response.json()["choices"][0]["message"]["content"])


def validate(result: dict) -> dict:
    decision = str(result.get("decision") or "needs_review")
    if decision not in {"single_headphone", "multi_headphone", "not_headphone", "needs_review"}:
        decision = "needs_review"
    products = []
    for item in result.get("products") or []:
        brand = normalize_brand(str(item.get("brand") or ""))
        model = normalize_model(str(item.get("model") or ""), brand)
        confidence = float(item.get("confidence") or 0)
        quote = str(item.get("evidence_quote") or "").strip()[:500]
        if not brand or not model or confidence < 0.9 or not quote or identity_review_reason(brand, model):
            continue
        products.append({"brand": brand, "model": model, "category": str(item.get("category") or ""), "confidence": confidence, "evidence_quote": quote})
    if decision == "single_headphone" and len(products) != 1:
        decision = "needs_review"
    if decision == "multi_headphone" and len(products) < 2:
        decision = "needs_review"
    if decision == "needs_review":
        products = []
    return {"decision": decision, "reason": str(result.get("reason") or "")[:500], "products": products}


def resolve_one(api_key: str, record: dict) -> dict:
    base = {"report_id": str(record.get("id")), "source_url": record.get("url") or "", "title": record.get("title") or ""}
    try:
        text = article_text(base["source_url"])
        if not text:
            return {**base, "decision": "needs_review", "reason": "original article had no extractable text", "products": []}
        return {**base, **validate(deepseek_identity(api_key, record, text))}
    except requests.RequestException as exc:
        return {**base, "decision": "needs_review", "reason": f"source fetch failed: {exc.__class__.__name__}", "products": []}
    except Exception as exc:
        return {**base, "decision": "needs_review", "reason": f"identity extraction failed: {exc.__class__.__name__}", "products": []}


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve ambiguous 52audio report identities from original articles")
    parser.add_argument("--all", action="store_true", help="review every candidate, not just the initial limit")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--write-overrides", action="store_true")
    args = parser.parse_args()
    api_key = os.environ["DEEPSEEK_API_KEY"]
    candidates = [record for record in load_all_records("report") if is_candidate(record)]
    if not args.all:
        candidates = candidates[:max(1, args.limit)]
    results = []
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, 3))) as executor:
        futures = [executor.submit(resolve_one, api_key, record) for record in candidates]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda item: item["report_id"])
    accepted = {item["report_id"]: item for item in results if item["decision"] in {"single_headphone", "multi_headphone", "not_headphone"}}
    review = [item for item in results if item["decision"] in {"needs_review", "not_headphone"}]
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), "policy": "Raw articles remain unchanged; only evidence-backed >=0.9 identities are consumed by the product builder.", "items": accepted}
    out_dir = ROOT / "scratch_price_research"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "identity_repair_review.json").write_text(json.dumps({"summary": {"processed": len(results), "accepted": len(accepted), "needs_review": sum(item["decision"] == "needs_review" for item in results), "not_headphone": sum(item["decision"] == "not_headphone" for item in results)}, "items": review}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.write_overrides:
        identity_overrides_path(for_write=True).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"processed": len(results), "accepted": len(accepted), "needs_review": sum(item["decision"] == "needs_review" for item in results), "not_headphone": sum(item["decision"] == "not_headphone" for item in results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
