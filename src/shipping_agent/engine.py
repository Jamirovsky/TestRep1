from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pandas as pd

from .extractors import extract_rates_from_folder
from .models import Query, ShippingRate


class ShippingRateEngine:
    def __init__(self, rates: list[ShippingRate]):
        self.rates = rates
        self.df = pd.DataFrame([asdict(r) for r in rates]) if rates else pd.DataFrame()

    @classmethod
    def from_folder(cls, folder: Path, config_path: Path | None = None) -> "ShippingRateEngine":
        rates = extract_rates_from_folder(folder, config_path=config_path)
        return cls(rates)

    def available_origins(self) -> list[str]:
        if self.df.empty:
            return []
        values = sorted(self.df["origin_country"].dropna().unique().tolist())
        return [v for v in values if v and v != "*"]

    def available_destinations(self) -> list[str]:
        if self.df.empty:
            return []
        values = sorted(self.df["destination_country"].dropna().unique().tolist())
        return [v for v in values if v]

    def query(self, q: Query) -> pd.DataFrame:
        if self.df.empty:
            return pd.DataFrame()

        working = self.df.copy()
        working = working[working["destination_country"].str.upper() == q.destination_country.upper()]

        matches_fixed = (
            (working["origin_type"] == "fixed")
            & (working["origin_country"].str.upper() == q.origin_country.upper())
        )
        matches_third_party = (working["origin_type"] == "third_party") & (
            (working["origin_country"] == "*")
            | (working["origin_country"].str.upper() == q.origin_country.upper())
        )
        working = working[matches_fixed | matches_third_party]

        working = working[working["weight_kg"] >= q.weight_kg]
        if working.empty:
            return working

        best_price_per_service = (
            working.sort_values("weight_kg")
            .groupby(["carrier", "service", "currency", "source_file"], as_index=False)
            .first()
            .sort_values(["price", "carrier", "service"])
            .reset_index(drop=True)
        )
        return best_price_per_service

    def to_excel(self, output_path: Path) -> None:
        if self.df.empty:
            pd.DataFrame(columns=[
                "carrier",
                "service",
                "origin_country",
                "destination_country",
                "zone",
                "weight_kg",
                "price",
                "currency",
                "source_file",
                "origin_type",
            ]).to_excel(output_path, index=False)
            return

        self.df.to_excel(output_path, index=False)
