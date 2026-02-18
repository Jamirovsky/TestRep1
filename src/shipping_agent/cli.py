from __future__ import annotations

import argparse
from pathlib import Path

from .engine import ShippingRateEngine
from .models import Query


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agente de tarifas UPS/FedEx")
    parser.add_argument("folder", type=Path, help="Pasta com ficheiros PDF/XLSX")
    parser.add_argument("--config", type=Path, default=None, help="Ficheiro YAML com templates por ficheiro")
    parser.add_argument("--export", type=Path, default=None, help="Exportar tabela normalizada para Excel")
    parser.add_argument("--origin", type=str, default=None)
    parser.add_argument("--destination", type=str, default=None)
    parser.add_argument("--weight", type=float, default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    engine = ShippingRateEngine.from_folder(folder=args.folder, config_path=args.config)

    if args.export:
        engine.to_excel(args.export)
        print(f"Exportado para {args.export}")

    if args.origin and args.destination and args.weight is not None:
        result = engine.query(
            Query(
                origin_country=args.origin,
                destination_country=args.destination,
                weight_kg=float(args.weight),
            )
        )
        if result.empty:
            print("Sem resultados")
        else:
            print(result.to_string(index=False))
    else:
        print(f"Tarifas lidas: {len(engine.rates)}")


if __name__ == "__main__":
    main()
