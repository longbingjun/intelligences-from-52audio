"""Evidence-only pilot: infer official list/launch price from web-search text.

This script never writes product price fields. Its output is a review artifact only.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scratch_price_research" / "price_text_pilot_20.json"
MODEL = "deepseek-v4-flash"
PROMPT = (
    "You audit Chinese product-price evidence. Extract only a mainland-China official MSRP "
    "or an official launch price from the supplied search snippets. Reject transaction prices, "
    "discounts, subsidies, coupons, pre-sale prices, overseas prices, and mismatched models. "
    "If no reliable official-price evidence exists, price_cny must be null. Return JSON only: "
    '{"price_cny":number|null,"price_type":"official_msrp|official_launch_price|no_reliable_result",'
    '"evidence_index":number|null,"evidence_quote":string,"confidence":number,"reason":string}.'
)


def missing_price_products(limit: int = 20) -> list[dict]:
    products = []
    for path in sorted((ROOT / "data" / "products").glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            product = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        snapshot = product.get("cost_snapshot") or {}
        if (
            snapshot.get("price_cny") is None
            and product.get("brand")
            and product.get("model")
            and not product["canonical_id"].startswith("unknown--")
            and len(product["model"]) <= 48
        ):
            products.append(
                {"sku": product["canonical_id"], "brand": product["brand"], "model": product["model"]}
            )
    return products[:limit]


def search_web(product: dict) -> list[dict]:
    query = f"{product['brand']} {product['model']} 官方 首发价 建议零售价"
    response = requests.get(
        "https://www.bing.com/search?q=" + quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    hits = []
    for item in soup.select("li.b_algo")[:6]:
        anchor = item.select_one("h2 a")
        snippet = item.select_one(".b_caption p") or item.select_one("p")
        if anchor and snippet:
            hits.append(
                {
                    "title": anchor.get_text(" ", strip=True),
                    "url": anchor.get("href", ""),
                    "snippet": snippet.get_text(" ", strip=True),
                }
            )
    return hits


def extract_official_price(api_key: str, product: dict, hits: list[dict]) -> dict:
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": json.dumps({"product": product, "search_evidence": hits}, ensure_ascii=False)},
            ],
        },
        timeout=45,
    )
    response.raise_for_status()
    result = json.loads(response.json()["choices"][0]["message"]["content"])
    evidence_index = result.get("evidence_index")
    if not isinstance(evidence_index, int) or not 0 <= evidence_index < len(hits) or result.get("price_cny") is None:
        result.update(
            {
                "price_cny": None,
                "price_type": "no_reliable_result",
                "confidence": 0,
                "evidence_url": "",
            }
        )
    else:
        result["evidence_url"] = hits[evidence_index]["url"]
    return result


def main() -> None:
    api_key = os.environ["DEEPSEEK_API_KEY"]
    records = []
    for product in missing_price_products():
        try:
            evidence = search_web(product)
            extraction = (
                extract_official_price(api_key, product, evidence)
                if evidence
                else {"price_cny": None, "price_type": "no_reliable_result", "confidence": 0, "reason": "no search evidence", "evidence_url": ""}
            )
        except Exception as exc:
            evidence = []
            extraction = {"price_cny": None, "price_type": "no_reliable_result", "confidence": 0, "reason": str(exc), "evidence_url": ""}
        records.append(
            {
                **product,
                "query_time": datetime.now(timezone.utc).isoformat(),
                "search_evidence": evidence,
                "extraction": extraction,
            }
        )
        time.sleep(0.4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"generated_at": datetime.now(timezone.utc).isoformat(), "model": MODEL, "scope": "evidence-only; no price_cny overwritten", "records": records},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
