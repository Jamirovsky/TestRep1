from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


OriginType = Literal["fixed", "third_party"]


@dataclass(slots=True)
class ShippingRate:
    carrier: str
    service: str
    origin_country: str
    destination_country: str
    zone: str
    weight_kg: float
    price: float
    currency: str
    source_file: Path
    origin_type: OriginType


@dataclass(slots=True)
class ZoneEntry:
    carrier: str
    service: str
    destination_country: str
    zone: str
    origin_country: str | None = None


@dataclass(slots=True)
class Query:
    origin_country: str
    destination_country: str
    weight_kg: float
