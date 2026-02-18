from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import pandas as pd
import pdfplumber
import yaml

from .models import ShippingRate


@dataclass(slots=True)
class FileTemplate:
    carrier: str
    currency: str = "EUR"
    service_hint: str | None = None
    origin_type: str = "fixed"
    fixed_origin: str | None = None


def load_templates(config_path: Path | None) -> dict[str, FileTemplate]:
    if config_path is None or not config_path.exists():
        return {}
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    out: dict[str, FileTemplate] = {}
    for filename, payload in raw.get("files", {}).items():
        out[filename] = FileTemplate(
            carrier=payload["carrier"],
            currency=payload.get("currency", "EUR"),
            service_hint=payload.get("service_hint"),
            origin_type=payload.get("origin_type", "fixed"),
            fixed_origin=payload.get("fixed_origin"),
        )
    return out


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    clone = df.copy()
    clone.columns = [str(c).strip().lower() for c in clone.columns]
    return clone


def _guess_col(columns: list[str], options: list[str]) -> str | None:
    for opt in options:
        for col in columns:
            if opt in col:
                return col
    return None


def _parse_price(value: object) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    txt = str(value).strip().replace("€", "").replace("$", "")
    txt = txt.replace(" ", "").replace(",", ".")
    matched = re.search(r"-?\d+(?:\.\d+)?", txt)
    if not matched:
        return None
    return float(matched.group(0))


def _extract_rows_from_df(df: pd.DataFrame, source_file: Path, template: FileTemplate) -> list[ShippingRate]:
    df = _normalize_columns(df)
    cols = list(df.columns)
    destination_col = _guess_col(cols, ["destination", "country", "destino"])
    zone_col = _guess_col(cols, ["zone", "zona"])
    weight_col = _guess_col(cols, ["weight", "peso", "kg"])
    price_col = _guess_col(cols, ["price", "cost", "rate", "tarifa", "preço", "preco"])
    service_col = _guess_col(cols, ["service", "produto", "serviço", "servico"])
    origin_col = _guess_col(cols, ["origin", "origem"])

    if not destination_col or not zone_col or not weight_col or not price_col:
        return []

    service = template.service_hint or source_file.stem
    rates: list[ShippingRate] = []

    for _, row in df.iterrows():
        destination = str(row.get(destination_col, "")).strip().upper()
        zone = str(row.get(zone_col, "")).strip().upper()
        weight = _parse_price(row.get(weight_col))
        price = _parse_price(row.get(price_col))
        if not destination or destination == "NAN" or not zone or zone == "NAN":
            continue
        if weight is None or price is None:
            continue

        if template.origin_type == "fixed":
            origin = template.fixed_origin or str(row.get(origin_col, "")).strip().upper()
        else:
            origin = str(row.get(origin_col, "")).strip().upper() or "*"

        if not origin:
            origin = "*"

        row_service = str(row.get(service_col, service)).strip() if service_col else service

        rates.append(
            ShippingRate(
                carrier=template.carrier,
                service=row_service,
                origin_country=origin,
                destination_country=destination,
                zone=zone,
                weight_kg=weight,
                price=price,
                currency=template.currency,
                source_file=source_file,
                origin_type="third_party" if template.origin_type == "third_party" else "fixed",
            )
        )

    return rates


def extract_from_excel(path: Path, template: FileTemplate) -> list[ShippingRate]:
    rates: list[ShippingRate] = []
    sheets = pd.read_excel(path, sheet_name=None)
    for df in sheets.values():
        rates.extend(_extract_rows_from_df(df, path, template))
    return rates


def _pdf_table_to_dataframe(table: list[list[str]]) -> pd.DataFrame:
    if not table or len(table) < 2:
        return pd.DataFrame()
    header = [str(h).strip() for h in table[0]]
    rows = table[1:]
    return pd.DataFrame(rows, columns=header)


def extract_from_pdf(path: Path, template: FileTemplate) -> list[ShippingRate]:
    rates: list[ShippingRate] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for table in tables:
                df = _pdf_table_to_dataframe(table)
                if df.empty:
                    continue
                rates.extend(_extract_rows_from_df(df, path, template))
    return rates


def detect_template(path: Path, templates: dict[str, FileTemplate]) -> FileTemplate:
    if path.name in templates:
        return templates[path.name]

    carrier = "UPS" if "ups" in path.name.lower() else "FEDEX" if "fedex" in path.name.lower() else "UNKNOWN"
    origin_type = "third_party" if "3rd" in path.name.lower() or "third" in path.name.lower() else "fixed"
    return FileTemplate(carrier=carrier, origin_type=origin_type, service_hint=path.stem)


def extract_rates_from_folder(folder: Path, config_path: Path | None = None) -> list[ShippingRate]:
    templates = load_templates(config_path)
    rates: list[ShippingRate] = []

    for path in sorted(folder.iterdir()):
        if path.is_dir():
            continue
        if path.suffix.lower() not in {".xlsx", ".xls", ".pdf"}:
            continue

        template = detect_template(path, templates)
        if path.suffix.lower() in {".xlsx", ".xls"}:
            rates.extend(extract_from_excel(path, template))
        else:
            rates.extend(extract_from_pdf(path, template))

    return rates
