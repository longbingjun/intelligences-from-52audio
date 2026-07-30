"""Evidence-only pilot for traceable mainland-China official prices.

The pilot is deliberately separate from ``data/products``: it creates a review
artifact and never writes ``cost_snapshot.price_cny``.  A price is accepted only
when a known official brand domain supplies the quoted evidence.
"""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scratch_price_research" / "price_text_pilot_20.json"
MODEL = "deepseek-v4-flash"
MAX_PAGE_CHARS = 6_000

# These are intentionally a conservative allow-list.  Adding a brand means
# adding its real mainland/offical domain here; unrecognised domains cannot
# produce an accepted price in this pilot.
OFFICIAL_DOMAIN_HINTS = {
    "amazfit": ("amazfit.com", "zepp.com"),
    "anker": ("anker.com", "soundcore.com"),
    "baseus": ("baseus.com",),
    "bose": ("bose.cn", "bose.com"),
    "huawei": ("huawei.com", "vmall.com"),
    "honor": ("honor.com",),
    "jbl": ("jbl.com", "harman.com"),
    "xiaomi": ("mi.com", "xiaomi.com"),
    "oppo": ("oppo.com",),
    "oneplus": ("oneplus.com",),
    "samsung": ("samsung.com",),
    "sony": ("sony.com",),
    "apple": ("apple.com",),
    "beats": ("beatsbydre.com", "apple.com"),
    "sennheiser": ("sennheiser.com",),
    "shokz": ("shokz.com",),
    "nothing": ("nothing.tech",),
    "edifier": ("edifier.com",),
    "qcy": ("qcy.com",),
    "realme": ("realme.com",),
    "vivo": ("vivo.com",),
}

# Product records commonly use a Chinese distributor/manufacturer name together
# with the consumer brand (for example ``华米Amazfit``).  Match only explicit,
# unambiguous aliases so that a brand still has to resolve to a curated official
# domain before any price can be accepted.
BRAND_ALIASES = {
    "amazfit": ("amazfit", "华米"),
    "anker": ("anker", "安克"),
    "baseus": ("baseus", "倍思"),
    "bose": ("bose", "博士"),
    "huawei": ("huawei", "华为"),
    "honor": ("honor", "荣耀"),
    "jbl": ("jbl",),
    "xiaomi": ("xiaomi", "小米"),
    "oppo": ("oppo",),
    "oneplus": ("oneplus", "一加"),
    "samsung": ("samsung", "三星"),
    "sony": ("sony", "索尼"),
    "apple": ("apple", "苹果"),
    "beats": ("beats",),
    "sennheiser": ("sennheiser", "森海塞尔"),
    "shokz": ("shokz", "韶音"),
    "nothing": ("nothing",),
    "edifier": ("edifier", "漫步者"),
    "qcy": ("qcy",),
    "realme": ("realme", "真我"),
    "vivo": ("vivo",),
}

PROMPT = """You are a strict price-evidence auditor. The supplied pages were fetched
from a known official brand website or official store. Extract a price only if the
page itself explicitly states a mainland-China official MSRP, suggested retail price,
or official launch price for the exact product. Do not use transaction, promotion,
subsidy, coupon, pre-sale, used, overseas, or a different-configuration price.
If the evidence is insufficient, use null. Return JSON only:
{"price_cny":number|null,"price_type":"official_msrp|official_launch_price|no_reliable_result",
"evidence_index":number|null,"evidence_quote":string,"confidence":number,"reason":string}."""


def canonical_brand(brand: str) -> str:
    """Resolve mixed Chinese/English record labels to an allow-list brand key."""
    normalised = "".join(brand.lower().split())
    for brand_key, aliases in BRAND_ALIASES.items():
        if any(alias in normalised for alias in aliases):
            return brand_key
    return normalised


def official_domains(product: dict) -> tuple[str, ...]:
    return OFFICIAL_DOMAIN_HINTS.get(canonical_brand(product["brand"]), ())


def is_official_url(url: str, domains: tuple[str, ...]) -> bool:
    host = urlsplit(url).hostname or ""
    host = host.lower().removeprefix("www.")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


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
            products.append({"sku": product["canonical_id"], "brand": product["brand"], "model": product["model"]})
    return products[:limit]


def bing_search(query: str) -> list[dict]:
    response = requests.get(
        "https://www.bing.com/search?q=" + quote_plus(query),
        headers={"User-Agent": "Mozilla/5.0 (compatible; official-price-research/1.0)"},
        timeout=20,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    hits = []
    for item in soup.select("li.b_algo")[:8]:
        anchor = item.select_one("h2 a")
        snippet = item.select_one(".b_caption p") or item.select_one("p")
        if anchor and anchor.get("href"):
            hits.append({
                "title": anchor.get_text(" ", strip=True),
                "url": anchor["href"],
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            })
    return hits


def extract_page_text(url: str) -> tuple[str, str]:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; official-price-research/1.0)"},
        timeout=20,
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "noscript", "svg"]):
        node.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    return title, soup.get_text(" ", strip=True)[:MAX_PAGE_CHARS]


def official_evidence(product: dict) -> tuple[list[dict], list[str]]:
    domains = official_domains(product)
    if not domains:
        return [], ["brand has no curated official-domain allow-list entry"]

    # Official site / official store / official newsroom are searched first.
    query_suffix = "官网 官方商城 新品发布 首发价 建议零售价 售价"
    raw_hits: list[dict] = []
    for domain in domains:
        raw_hits.extend(bing_search(f'site:{domain} "{product["model"]}" {query_suffix}'))

    seen, evidence, notes = set(), [], []
    for hit in raw_hits:
        url = hit["url"]
        if url in seen or not is_official_url(url, domains):
            continue
        seen.add(url)
        try:
            title, page_text = extract_page_text(url)
        except requests.RequestException as exc:
            notes.append(f"could not fetch official result: {urlsplit(url).hostname} ({exc.__class__.__name__})")
            continue
        if page_text:
            evidence.append({
                "source_type": "official_site_or_store_or_newsroom",
                "title": title or hit["title"],
                "url": url,
                "search_snippet": hit["snippet"],
                "page_text": page_text,
            })
        if len(evidence) >= 5:
            break
    if not evidence and not notes:
        notes.append("no fetchable official-site result for exact model")
    return evidence, notes


def finite_number(value: object, default: float = 0) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def normalise_extraction(result: dict, evidence: list[dict]) -> dict:
    index = result.get("evidence_index")
    price = finite_number(result.get("price_cny"), default=-1)
    valid = (
        isinstance(index, int)
        and 0 <= index < len(evidence)
        and price > 0
        and result.get("price_type") in {"official_msrp", "official_launch_price"}
        and bool(str(result.get("evidence_quote", "")).strip())
    )
    if not valid:
        return {"price_cny": None, "price_type": "no_reliable_result", "confidence": 0,
                "evidence_url": "", "evidence_quote": "", "reason": str(result.get("reason", "insufficient official evidence"))}
    return {
        "price_cny": int(price) if price.is_integer() else price,
        "price_type": result["price_type"],
        "confidence": min(1, max(0, finite_number(result.get("confidence")))),
        "evidence_url": evidence[index]["url"],
        "evidence_quote": str(result["evidence_quote"]).strip()[:600],
        "reason": str(result.get("reason", "")).strip()[:500],
    }


def extract_official_price(api_key: str, product: dict, evidence: list[dict]) -> dict:
    response = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": MODEL, "thinking": {"type": "disabled"}, "temperature": 0, "max_tokens": 350,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": PROMPT},
                           {"role": "user", "content": json.dumps({"product": product, "official_page_evidence": evidence}, ensure_ascii=False)}]},
        timeout=45,
    )
    response.raise_for_status()
    return normalise_extraction(json.loads(response.json()["choices"][0]["message"]["content"]), evidence)


def main() -> None:
    api_key = os.environ["DEEPSEEK_API_KEY"]
    records = []
    for product in missing_price_products():
        try:
            evidence, notes = official_evidence(product)
            extraction = extract_official_price(api_key, product, evidence) if evidence else {
                "price_cny": None, "price_type": "no_reliable_result", "confidence": 0,
                "evidence_url": "", "evidence_quote": "", "reason": "; ".join(notes),
            }
        except Exception as exc:
            evidence, extraction = [], {"price_cny": None, "price_type": "no_reliable_result", "confidence": 0,
                                         "evidence_url": "", "evidence_quote": "", "reason": f"research error: {exc.__class__.__name__}"}
        records.append({**product, "query_time": datetime.now(timezone.utc).isoformat(),
                        "official_page_evidence": evidence, "extraction": extraction})
        time.sleep(0.4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "model": MODEL,
        "scope": "evidence-only; official-domain pages only; no price_cny overwritten", "records": records},
        ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
