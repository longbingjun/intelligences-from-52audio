#!/usr/bin/env python3
"""Probe JD Union APIs for price data availability."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sources.channel.jd_union_client import get_client, union_configured  # noqa: E402

SKU = 10192266796615

TESTS = [
    ("jd.union.open.goods.query", {"goodsReqDTO": {"keyword": "FreeBuds", "pageIndex": 1, "pageSize": 3, "sceneId": 1}}),
    ("jd.union.open.goods.query", {"goodsReqDTO": {"skuIds": [SKU], "sceneId": 2}}),
    ("jd.union.open.goods.detail.query", {"goodsReqDTO": {"skuIds": [SKU], "sceneId": 1}}),
    ("jd.union.open.goods.bigfield.query", {"goodsReq": {"skuIds": [SKU], "sceneId": 2}}),
    ("jd.union.open.goods.promotiongoodsinfo.query", {"skuIds": str(SKU)}),
    ("jd.union.open.goods.jingfen.query", {"goodsReq": {"eliteId": 1, "pageIndex": 1, "pageSize": 2}}),
    ("jd.union.open.goods.material.query", {"goodsReq": {"eliteId": 1, "pageIndex": 1, "pageSize": 2}}),
]


def summarize(method: str, raw: dict) -> dict:
    if "error_response" in raw:
        err = raw["error_response"]
        return {"status": "error", "code": err.get("code"), "msg": err.get("zh_desc") or err.get("en_desc")}
    outer = next(iter(raw.values()), {})
    qr = outer.get("queryResult") if isinstance(outer, dict) else None
    if isinstance(qr, str):
        try:
            inner = json.loads(qr)
        except json.JSONDecodeError:
            return {"status": "raw", "body": qr[:200]}
    else:
        inner = qr or outer
    if not isinstance(inner, dict):
        return {"status": "raw", "body": str(inner)[:200]}
    code = inner.get("code")
    out = {"status": "ok" if code in (200, "200", 0, "0") else "biz_error", "code": code, "msg": inner.get("message")}
    data = inner.get("data")
    if isinstance(data, list) and data:
        item = data[0]
        pi = item.get("priceInfo") if isinstance(item.get("priceInfo"), dict) else item
        out["price_fields"] = {k: pi.get(k) for k in (
            "price", "lowestPrice", "lowestCouponPrice", "originPrice", "purchasePrice",
            "discountPrice", "originalPrice", "skuName", "skuId", "title",
        ) if isinstance(pi, dict) and pi.get(k) is not None}
    return out


def main() -> None:
    if not union_configured():
        print("No .env credentials")
        sys.exit(1)
    client = get_client()
    assert client
    for method, biz in TESTS:
        try:
            raw = client._request(method, biz)
            print(json.dumps({"method": method, **summarize(method, raw)}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"method": method, "status": "exception", "msg": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
