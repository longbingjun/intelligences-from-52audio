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
import argparse
import base64
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlsplit

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
    "soundcore": ("cn.soundcore.com", "soundcore.com"),
    "baseus": ("baseus.com",),
    "bose": ("bose.cn", "bose.com"),
    "huawei": ("huawei.com", "vmall.com"),
    "honor": ("honor.com",),
    "jbl": ("jbl.com", "harman.com"),
    "xiaomi": ("mi.com", "xiaomi.com"),
    "oppo": ("oppo.com",),
    "oneplus": ("oneplus.com",),
    "philips": ("philips.com.cn", "philips.com"),
    "samsung": ("samsung.com",),
    "sony": ("sony.com",),
    "apple": ("apple.com",),
    "beats": ("beatsbydre.com", "apple.com"),
    "sennheiser": ("sennheiser.com",),
    "shokz": ("shokz.com",),
    "nothing": ("nothing.tech",),
    "edifier": ("edifier.com",),
    "qcy": ("qcy.com.cn", "qcy.com"),
    "realme": ("realme.com",),
    "vivo": ("vivo.com.cn", "vivo.com"),
}

# Mainland-China pages should be considered before generic global domains when
# both are owned by the same brand.
OFFICIAL_DOMAIN_HINTS["sony"] = ("sony.com.cn", "sonystyle.com.cn", "sony.com")

# Product records commonly use a Chinese distributor/manufacturer name together
# with the consumer brand (for example ``华米Amazfit``).  Match only explicit,
# unambiguous aliases so that a brand still has to resolve to a curated official
# domain before any price can be accepted.
BRAND_ALIASES = {
    "amazfit": ("amazfit", "华米"),
    "anker": ("anker", "安克"),
    "soundcore": ("soundcore", "声阔"),
    "baseus": ("baseus", "倍思"),
    "bose": ("bose", "博士"),
    "huawei": ("huawei", "华为"),
    "honor": ("honor", "荣耀"),
    "jbl": ("jbl",),
    "xiaomi": ("xiaomi", "小米"),
    "oppo": ("oppo",),
    "oneplus": ("oneplus", "一加"),
    "philips": ("philips", "飞利浦"),
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


def resolve_bing_result_url(url: str) -> str:
    """Decode Bing's ``ck/a`` outbound-link wrapper when it is present."""
    parsed = urlsplit(url)
    if not parsed.hostname or not parsed.hostname.lower().endswith("bing.com"):
        return url
    token = parse_qs(parsed.query).get("u", [""])[0]
    if not token.startswith("a1"):
        return url
    try:
        encoded = token[2:] + "=" * (-len(token[2:]) % 4)
        decoded = base64.urlsafe_b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return url
    return decoded if decoded.startswith(("https://", "http://")) else url


def _recent_priority(product: dict) -> int:
    """Use the persisted UI priority when present, with a safe date fallback."""
    rank = product.get("priority_rank")
    if isinstance(rank, int):
        return rank
    first_seen = str(product.get("first_seen") or "")[:10]
    try:
        observed = datetime.strptime(first_seen, "%Y-%m-%d").date()
    except ValueError:
        return 3
    return 2 if observed >= date.today() - timedelta(days=730) else 3


def missing_price_products(limit: int = 20) -> list[dict]:
    priority_by_id: dict[str, dict] = {}
    index_path = ROOT / "data" / "products" / "index.json"
    try:
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        priority_by_id = {
            str(item.get("canonical_id")): item
            for item in index_payload.get("products", [])
            if isinstance(item, dict) and item.get("canonical_id")
        }
    except (OSError, json.JSONDecodeError):
        # The date fallback keeps research safe even before the priority builder
        # has produced an index for the first time.
        pass

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
            priority = priority_by_id.get(product["canonical_id"], {})
            products.append({
                "sku": product["canonical_id"],
                "brand": product["brand"],
                "model": product["model"],
                "first_seen": priority.get("first_seen", product.get("first_seen", "")),
                "priority_rank": priority.get("priority_rank"),
                "research_priority": priority.get("research_priority", ""),
            })

    # Official-price research deliberately spends its limited request budget on
    # recent products first.  Historical products remain in the data set, but do
    # not displace current candidates unless the user asks for them explicitly.
    products.sort(key=lambda item: item.get("first_seen", ""), reverse=True)
    products.sort(key=_recent_priority)
    return [item for item in products if _recent_priority(item) <= 2][:limit]


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


def model_queries(product: dict) -> list[str]:
    """Generate safe exact-model alternatives without relying on CJK query text."""
    model = str(product.get("model") or "").strip()
    canonical = str(product.get("sku") or "").partition("--")[2].replace("-", " ")
    ascii_model = re.sub(r"[^A-Za-z0-9 .+_-]+", " ", model)
    queries = [model, ascii_model.strip(), canonical.strip()]
    seen: set[str] = set()
    return [query for query in queries if len(query) >= 3 and not (query.lower() in seen or seen.add(query.lower()))]


def official_evidence(product: dict) -> tuple[list[dict], list[str]]:
    domains = official_domains(product)
    if not domains:
        return [], ["brand has no curated official-domain allow-list entry"]

    # Use ASCII-only query terms here.  The product model remains quoted, while
    # avoiding Windows-console encoding changes that previously made the Bing
    # query unreadable in Actions.
    query_suffix = "official product store launch price MSRP China"
    raw_hits: list[dict] = []
    for domain in domains:
        for model in model_queries(product):
            raw_hits.extend(bing_search(f'site:{domain} "{model}" {query_suffix}'))

    seen, evidence, notes = set(), [], []
    for hit in raw_hits:
        url = resolve_bing_result_url(hit["url"])
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
        notes.append(f"no fetchable official-site result for model; search_hits={len(raw_hits)}")
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
    parser = argparse.ArgumentParser(description="Research recent products with traceable official-price evidence")
    parser.add_argument("--limit", type=int, default=20, help="maximum recent products to research")
    args = parser.parse_args()
    api_key = os.environ["DEEPSEEK_API_KEY"]
    records = []
    for product in missing_price_products(args.limit):
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
