"""Build explainable research priority fields for the lightweight product index.

This intentionally does not change product prices or product-detail records.  It
only enriches ``data/products/index.json`` so the discovery UI and the official
price-research queue can focus on products that are both recent and traceable to
an official page.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

import sys

sys.path.insert(0, str(ROOT))

from core.paths import official_enrich_dir, products_index_path, write_products_index  # noqa: E402


RECENT_WINDOW_DAYS = 730


def parse_product_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def official_page_status(canonical_id: str) -> tuple[str, str]:
    """Return a conservative official-page state and its traceable URL."""
    path = official_enrich_dir() / f"{canonical_id}.json"
    if not path.exists():
        return "unknown", ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown", ""

    url = str(payload.get("official_url") or payload.get("vmall_url") or "").strip()
    error = str(payload.get("fetch_error") or "").lower()
    if not url:
        return "not_found", ""
    # A known 404 is not evidence that the product is still present.  Rate-limit
    # errors still retain the official URL, so they remain reviewable rather than
    # being incorrectly downgraded to not-found.
    if "404" in error or "not found" in error:
        return "not_found", url
    return "found", url


def priority_for(product: dict, *, cutoff: date) -> tuple[str, int, str, str]:
    first_seen = parse_product_date(product.get("first_seen"))
    canonical_id = str(product.get("canonical_id") or "")
    status, url = official_page_status(canonical_id)
    # Do not promote records whose entity resolution is still unknown: an
    # unrelated official URL must never make an ambiguous product top priority.
    identity_is_resolved = bool(product.get("brand")) and not canonical_id.startswith("unknown--")
    if first_seen is not None and first_seen >= cutoff and identity_is_resolved and status == "found":
        return "official_current", 1, status, url
    if first_seen is not None and first_seen >= cutoff:
        return "recent_pending_check", 2, status, url
    return "historical_reference", 3, status, url


def build_priority_index(today: date | None = None) -> dict:
    today = today or date.today()
    cutoff = today - timedelta(days=RECENT_WINDOW_DAYS)
    path = products_index_path()
    payload = json.loads(path.read_text(encoding="utf-8"))
    products = payload.get("products", [])
    if not isinstance(products, list):
        raise ValueError("products index must contain a products list")

    counts: dict[str, int] = {
        "official_current": 0,
        "recent_pending_check": 0,
        "historical_reference": 0,
    }
    for product in products:
        if not isinstance(product, dict):
            continue
        priority, rank, presence, url = priority_for(product, cutoff=cutoff)
        product["research_priority"] = priority
        product["priority_rank"] = rank
        product["official_page_status"] = presence
        product["official_page_url"] = url
        counts[priority] += 1

    payload["priority_generated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    payload["priority_policy"] = {
        "recent_window_days": RECENT_WINDOW_DAYS,
        "recent_since": cutoff.isoformat(),
        "rule": "official-current first; recent products pending official-page verification second; historical reference last",
    }
    payload["priority_counts"] = counts
    write_products_index(payload)
    return {"total": len(products), "counts": counts, "recent_since": cutoff.isoformat()}


def main() -> None:
    print(json.dumps(build_priority_index(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
