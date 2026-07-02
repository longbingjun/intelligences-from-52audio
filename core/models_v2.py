"""v2 数据模型：按领域区块 views 存储，不含 content_html。"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Optional


def _as_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj):
        return {k: _as_dict(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, list):
        return [_as_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _as_dict(v) for k, v in obj.items()}
    return obj


@dataclass
class MarketView:
    brand: str = ""
    model: str = ""
    category: str = ""
    launch_date: Optional[str] = None
    price_cny: Optional[float] = None
    price_note: str = ""
    selling_points: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    positioning_summary: str = ""


@dataclass
class CostView:
    major_parts: list[str] = field(default_factory=list)
    chip_modules: list[dict] = field(default_factory=list)
    packaging_notes: list[str] = field(default_factory=list)
    process_hints: list[str] = field(default_factory=list)


@dataclass
class StructureView:
    form_factor: str = ""
    materials: list[str] = field(default_factory=list)
    ip_rating: Optional[str] = None
    weight_g: Optional[str] = None
    dimensions: list[str] = field(default_factory=list)
    wear_design: list[str] = field(default_factory=list)
    assembly_notes: list[str] = field(default_factory=list)


@dataclass
class HardwareView:
    specs: list[dict] = field(default_factory=list)


@dataclass
class SoftwareView:
    bluetooth_version: Optional[str] = None
    codecs: list[str] = field(default_factory=list)
    multipoint: list[str] = field(default_factory=list)
    app_name: str = ""
    app_features: list[str] = field(default_factory=list)
    ota_support: list[str] = field(default_factory=list)
    latency_notes: list[str] = field(default_factory=list)


@dataclass
class RoleViews:
    market: MarketView = field(default_factory=MarketView)
    cost: CostView = field(default_factory=CostView)
    structure: StructureView = field(default_factory=StructureView)
    hardware: HardwareView = field(default_factory=HardwareView)
    software: SoftwareView = field(default_factory=SoftwareView)

    def to_dict(self) -> dict:
        return _as_dict(self)


@dataclass
class ReportRecord:
    id: str
    type: str = "report"
    source_id: str = "audio52"
    url: str = ""
    title: str = ""
    brand: str = ""
    model: str = ""
    category: str = ""
    published_at: str = ""
    author: str = ""
    summary: str = ""
    captured_at: str = ""
    views: RoleViews = field(default_factory=RoleViews)

    def to_dict(self) -> dict:
        d = _as_dict(self)
        d["views"] = self.views.to_dict()
        return d


@dataclass
class VideoRecord:
    id: str
    type: str = "video"
    source_id: str = "audio52"
    url: str = ""
    title: str = ""
    product_title: str = ""
    brand: str = ""
    model: str = ""
    category: str = ""
    published_at: str = ""
    publisher: str = ""
    summary: str = ""
    source_site: str = ""
    video_embed_url: str = ""
    captured_at: str = ""
    asr_status: str = "pending"
    views: RoleViews = field(default_factory=RoleViews)

    def to_dict(self) -> dict:
        d = _as_dict(self)
        d["views"] = self.views.to_dict()
        return d
