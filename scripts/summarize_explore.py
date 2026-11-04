#!/usr/bin/env python3
"""Render explore_metals.py output as markdown tables (one per symbol).

    python3 scripts/summarize_explore.py reports/metals_explore_round1.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    data = json.loads(Path(sys.argv[1]).read_text())
    for sym, d in data.items():
        tfs = sorted({int(k.split("_")[0][1:]) for k in d})
        modes = list(dict.fromkeys(k.split("_", 1)[1] for k in d))
        print(f"\n**{sym}** - robust winner of the fit window (2019-2022), "
              "scored on the validation window (2023-2024): expectancy R / PF / trades\n")
        print("| family | " + " | ".join(f"M{t}" for t in tfs) + " |")
        print("|---|" + "---|" * len(tfs))
        for m in modes:
            cells = []
            for t in tfs:
                v = d.get(f"M{t}_{m}")
                if not v or not v["rows"]:
                    cells.append("-")
                    continue
                val = v["rows"][0]["val"]
                cells.append(f"{val['expectancy_r']:+.3f} / {val['profit_factor']:.2f} / {val['n_trades']}")
            print(f"| {m} | " + " | ".join(cells) + " |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
