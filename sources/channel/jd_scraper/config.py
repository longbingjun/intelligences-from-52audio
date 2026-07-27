"""JD scraper configuration."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = ROOT / "data" / "jd_browser_profile"
OUTPUT_DIR = ROOT / "data" / "enrich" / "channel"
PROBE_OUTPUT = OUTPUT_DIR / "jd_probe_results.json"

DEFAULT_PROBE_SKUS = [
    {"label": "HUAWEI FreeBuds Pro 3", "sku_id": "10192266796615"},
    {"label": "Apple AirPods Pro 2 USB-C", "sku_id": "100280446426"},
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

DEFAULT_CDP_URL = "http://127.0.0.1:9222"
MIN_DELAY_SEC = 3.0
MAX_DELAY_SEC = 6.0

PRICE_SELECTORS = [
    ".summary-price .p-price .price",
    ".p-price .price",
    "#J_FinalPrice",
    ".finalPrice",
]

FREQ403_MARKERS = ("pc-frequent-pro.pf.jd.com", "reason=403")
LOGIN_MARKERS = ("passport.jd.com/new/login", "login")