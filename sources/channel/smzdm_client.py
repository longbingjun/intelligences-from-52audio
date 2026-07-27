"""SMZDM (什么值得买) Open Platform API for channel reference prices.

Credentials in project root `.env`:
  SMZDM_APP_KEY, SMZDM_APP_SECRET, SMZDM_REQUEST_FROM (optional)

Apply for keys: group-content@zhidemai.com
Docs: https://openapi.zhidemai.com/
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import requests

_API_BASE = "https://openapi.smzdm.com"
_ROOT = Path(__file__).resolve().parents[2]

_JD_SKU_RE = re.compile(r"(?:item\.jd\.com/(\d+)|[?&]sku=(\d+))", re.I)
_PRICE_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")
_JD_MALL_NAMES = ("京东", "京东自营")


def _load_dotenv() -> None:
    env_path = _ROOT / ".env"
    if not env_path.exists():
        return
    raw = env_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    for line in raw.decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


def _credentials() -> tuple[str, str, str] | None:
    _load_dotenv()
    key = os.environ.get("SMZDM_APP_KEY", "").strip()
    secret = os.environ.get("SMZDM_APP_SECRET", "").strip()
    request_from = os.environ.get("SMZDM_REQUEST_FROM", "52audio-intel").strip()
    if key and secret:
        return key, secret, request_from
    return None


def smzdm_configured() -> bool:
    return _credentials() is not None


@dataclass
class SmzdmHit:
    title: str
    price_cny: float | None
    mall_name: str
    url: str
    sku_id: str | None = None
    source_api: str = ""
    prom_info: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "price_cny": self.price_cny,
            "mall_name": self.mall_name,
            "url": self.url,
            "sku_id": self.sku_id,
            "source_api": self.source_api,
            "prom_info": self.prom_info,
        }


@dataclass
class SmzdmPriceInfo:
    search_query: str = ""
    hits: list[SmzdmHit] = field(default_factory=list)
    best_hit: SmzdmHit | None = None
    fetch_error: str = ""

    def to_dict(self) -> dict:
        return {
            "search_query": self.search_query,
            "hits": [h.to_dict() for h in self.hits[:8]],
            "best_hit": self.best_hit.to_dict() if self.best_hit else None,
            "fetch_error": self.fetch_error,
        }


def _parse_price(raw) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        val = float(raw)
        return val if 10 <= val <= 99999 else None
    text = str(raw).replace(",", "")
    m = _PRICE_NUM_RE.search(text)
    if not m:
        return None
    val = float(m.group(1))
    return val if 10 <= val <= 99999 else None


def _extract_jd_sku(url: str) -> str | None:
    m = _JD_SKU_RE.search(url or "")
    if not m:
        return None
    return next((g for g in m.groups() if g), None)


def _sign(params: dict[str, str], secret: str) -> str:
    ordered = sorted((k, v) for k, v in params.items() if k != "sign" and v not in (None, ""))
    body = "".join(f"{k}{v}" for k, v in ordered)
    digest = hashlib.md5(f"{secret}{body}{secret}".encode()).hexdigest()
    return digest.upper()


class SmzdmClient:
    def __init__(self, app_key: str, app_secret: str, request_from: str) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.request_from = request_from
        self._last_call = 0.0

    def _throttle(self, min_interval: float = 0.4) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call = time.monotonic()

    def _signed_params(self, biz: dict[str, str]) -> dict[str, str]:
        params = {
            "app_key": self.app_key,
            "timestamp": str(int(time.time())),
            **{k: str(v) for k, v in biz.items() if v not in (None, "")},
        }
        params["sign"] = _sign(params, self.app_secret)
        return params

    def _get(self, path: str, biz: dict[str, str]) -> dict:
        self._throttle()
        params = self._signed_params(biz)
        url = f"{_API_BASE}{path}?{urlencode(params)}"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _post_json(self, path: str, biz: dict[str, str]) -> dict:
        self._throttle()
        params = self._signed_params(biz)
        resp = requests.post(f"{_API_BASE}{path}", json=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def search_haojia(self, keyword: str, *, size: int = 20) -> list[SmzdmHit]:
        payload = self._get(
            "/v1/searchapi/search/list",
            {
                "c": "new_home",
                "s": keyword,
                "size": str(size),
                "offset": "0",
                "request_from": self.request_from,
            },
        )
        if not payload.get("status"):
            msg = payload.get("msg") or "haojia_search_failed"
            raise RuntimeError(str(msg))
        rows = (payload.get("data") or {}).get("rows") or []
        hits: list[SmzdmHit] = []
        for row in rows:
            title = str(row.get("title") or "")
            mall = str(row.get("mall") or "")
            price = _parse_price(row.get("digital_price")) or _parse_price(row.get("title_price"))
            url = str(row.get("article_url") or "")
            tags = row.get("article_list_tags") or []
            hits.append(
                SmzdmHit(
                    title=title,
                    price_cny=price,
                    mall_name=mall,
                    url=url,
                    source_api="searchapi/search/list",
                    prom_info=[str(t) for t in tags][:5],
                )
            )
        return hits

    def search_products(self, keyword: str) -> list[SmzdmHit]:
        payload = self._post_json("/v1/agent/search/list", {"keyword": keyword})
        if payload.get("error_code") not in (0, "0", None):
            raise RuntimeError(payload.get("error_msg") or f"agent_search error {payload.get('error_code')}")
        hits: list[SmzdmHit] = []
        for group in payload.get("data") or []:
            if not isinstance(group, list):
                continue
            for item in group:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "")
                mall = str(item.get("mall_name") or "")
                price = _parse_price(item.get("price_1")) or _parse_price(item.get("price"))
                url = str(item.get("url") or "")
                prom = item.get("prom_info") or []
                hits.append(
                    SmzdmHit(
                        title=title,
                        price_cny=price,
                        mall_name=mall,
                        url=url,
                        sku_id=_extract_jd_sku(url),
                        source_api="agent/search/list",
                        prom_info=[str(p) for p in prom][:5],
                    )
                )
        return hits

    def compare_price(self, keyword: str) -> list[SmzdmHit]:
        payload = self._post_json(
            "/v1/agent/compare/price",
            {"keyword": keyword, "request_id": uuid.uuid4().hex},
        )
        if payload.get("error_code") not in (0, "0", None):
            raise RuntimeError(payload.get("error_msg") or f"compare_price error {payload.get('error_code')}")
        data = payload.get("data") or {}
        items = data.get("list") if isinstance(data, dict) else []
        hits: list[SmzdmHit] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            title = str(item.get("goods_name") or item.get("title") or "")
            mall = str(item.get("mall_name") or "")
            price = _parse_price(item.get("title_price"))
            url = str(item.get("url") or "")
            hits.append(
                SmzdmHit(
                    title=title,
                    price_cny=price,
                    mall_name=mall,
                    url=url,
                    sku_id=_extract_jd_sku(url),
                    source_api="agent/compare/price",
                )
            )
        return hits


def get_client() -> SmzdmClient | None:
    creds = _credentials()
    if not creds:
        return None
    return SmzdmClient(creds[0], creds[1], creds[2])


def _score_hit(hit: SmzdmHit, brand: str, model: str) -> float:
    from sources.channel.zol_client import score_product_title

    score = score_product_title(hit.title, brand, model)
    mall = hit.mall_name or ""
    if any(name in mall for name in _JD_MALL_NAMES):
        score += 2.0
    elif "天猫" in mall:
        score += 0.8
    if hit.price_cny is not None:
        score += 0.2
    if "自营" in hit.title or "自营" in " ".join(hit.prom_info):
        score += 0.5
    return score


def pick_best_smzdm_hit(hits: list[SmzdmHit], brand: str, model: str) -> SmzdmHit | None:
    if not hits:
        return None
    ranked = sorted(hits, key=lambda h: _score_hit(h, brand, model), reverse=True)
    best = ranked[0]
    if _score_hit(best, brand, model) < 1.5:
        return None
    return best


def best_smzdm_price(hits: list[SmzdmHit], brand: str, model: str) -> SmzdmHit | None:
    if not hits:
        return None
    jd_hits = [h for h in hits if any(n in (h.mall_name or "") for n in _JD_MALL_NAMES)]
    pool = jd_hits or hits
    return pick_best_smzdm_hit(pool, brand, model)


def fetch_smzdm_prices(*, brand: str, model: str, query: str | None = None) -> SmzdmPriceInfo:
    q = (query or f"{brand} {model}").strip()
    client = get_client()
    if not client:
        return SmzdmPriceInfo(search_query=q, fetch_error="smzdm_not_configured")

    merged: list[SmzdmHit] = []
    errors: list[str] = []
    for name, fn in (
        ("compare", lambda: client.compare_price(q)),
        ("products", lambda: client.search_products(q)),
        ("haojia", lambda: client.search_haojia(q)),
    ):
        try:
            merged.extend(fn())
        except Exception as exc:
            errors.append(f"{name}:{exc}")

    if not merged:
        return SmzdmPriceInfo(
            search_query=q,
            fetch_error="smzdm_no_hit" if not errors else "; ".join(errors),
        )

    best = best_smzdm_price(merged, brand, model)
    return SmzdmPriceInfo(
        search_query=q,
        hits=merged,
        best_hit=best,
        fetch_error="" if best else "smzdm_no_match",
    )