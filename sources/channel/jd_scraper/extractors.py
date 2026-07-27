"""Price extraction from JD item pages (DOM + p.3.cn API)."""

from __future__ import annotations

import json
import re
from typing import Any

from playwright.sync_api import Page

from sources.channel.jd_scraper.config import PRICE_SELECTORS

_PRICE_NUM_RE = re.compile(r"(\d+(?:\.\d+)?)")


def parse_price_text(text: str | None) -> float | None:
    if not text:
        return None
    m = _PRICE_NUM_RE.search(str(text).replace(",", ""))
    if not m:
        return None
    val = float(m.group(1))
    return val if 10 <= val <= 99999 else None


def extract_dom_prices(page: Page) -> dict[str, Any]:
    out: dict[str, Any] = {"selectors": {}, "page_text_hits": []}
    for sel in PRICE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible(timeout=500):
                txt = (loc.inner_text(timeout=1000) or "").strip()
                if txt:
                    out["selectors"][sel] = txt
        except Exception:
            pass
    try:
        body = page.locator("body").inner_text(timeout=3000)
        m = re.search(r"[\d,.]+", body)
        if m and ("jdPrice" in body or "price" in body.lower()):
            out["page_text_hits"].append(m.group(0)[:60])
    except Exception:
        pass
    return out


def fetch_p3_price(page: Page, sku_id: str) -> dict[str, Any]:
    url = f"https://p.3.cn/prices/mgets?skuIds=J_{sku_id}"
    try:
        resp = page.request.get(url, timeout=15000)
        raw = resp.text() or "[]"
        data = json.loads(raw)
        row = data[0] if isinstance(data, list) and data else {}
        return {
            "status": resp.status,
            "ok": resp.ok,
            "price_cny": float(row["p"]) if row.get("p") else None,
            "msrp_cny": float(row["m"]) if row.get("m") else None,
            "raw": row,
            "error": None,
        }
    except Exception as exc:
        return {
            "status": None,
            "ok": False,
            "price_cny": None,
            "msrp_cny": None,
            "raw": None,
            "error": str(exc),
        }


def fetch_ware_business(page: Page, sku_id: str) -> dict[str, Any]:
    js = """async (sku) => {
      const body = JSON.stringify({skuId: sku, cat: '842', area: '19-1607-4773-62123'});
      const u = 'https://api.m.jd.com/?functionId=pc_detailpage_wareBusiness'
        + '&appid=pc-item-soa&client=pc&clientVersion=1.0.0'
        + '&t=' + Date.now() + '&body=' + encodeURIComponent(body);
      const r = await fetch(u, {credentials: 'include'});
      const t = await r.text();
      return {status: r.status, sample: t.slice(0, 1200)};
    }"""
    try:
        result = page.evaluate(js, sku_id)
        sample = result.get("sample") or ""
        price = None
        m = re.search(r'"p"\s*:\s*"?([\d.]+)"?', sample)
        if m:
            price = float(m.group(1))
        return {"status": result.get("status"), "price_cny": price, "sample_len": len(sample), "error": None}
    except Exception as exc:
        return {"status": None, "price_cny": None, "sample_len": 0, "error": str(exc)}


def classify_page(url: str, title: str, body_snip: str) -> list[str]:
    blob = f"{url}\n{title}\n{body_snip}".lower()
    flags: list[str] = []
    if "pf.jd.com" in blob or "reason=403" in blob:
        flags.append("freq403")
    if "passport.jd.com" in blob:
        flags.append("login_redirect")
    if "login" in blob and "jd.com" in blob:
        flags.append("login_wall")
    if "captcha" in blob or "verify.jd.com" in blob:
        flags.append("captcha")
    if "暂时无法展示该商品" in body_snip or "暂时无法展示该商品" in title:
        flags.append("soft_block")
    return sorted(set(flags))


def best_price(dom: dict, p3: dict, ware: dict) -> tuple[float | None, float | None, str | None]:
    if p3.get("price_cny") is not None:
        return p3["price_cny"], p3.get("msrp_cny"), "p3_api"
    if ware.get("price_cny") is not None:
        return ware["price_cny"], None, "ware_business"
    for txt in dom.get("selectors", {}).values():
        val = parse_price_text(txt)
        if val is not None:
            return val, None, "dom_selector"
    for hit in dom.get("page_text_hits") or []:
        val = parse_price_text(hit)
        if val is not None:
            return val, None, "dom_text"
    return None, None, None