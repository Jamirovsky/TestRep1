#!/usr/bin/env python3
"""Download real OANDA M1 bars (metals, XAUJPY, cash indices) from public GitHub archives.

Market-data vendors are often unreachable from CI / sandboxed machines, but
``raw.githubusercontent.com`` usually is.  The ``bunqii/OANDA_<SYM>_<Name>``
repositories hold OANDA's M1 candles (mid prices, tick-count volume) as one
parquet file per month, verified against the OANDA v20 API.

    python3 scripts/fetch_metals.py                       # XAG, XPT, XPD, XAU 2019 -> last month
    python3 scripts/fetch_metals.py --symbols XPTUSD --start 2021-01

Files land in ``data/raw/<SYMBOL>/`` and ``dataset.load`` picks them up
automatically.  Prices are MID: the engine charges the full modelled spread on
every round trip, which is the same total cost as bid/ask bars.
"""
from __future__ import annotations

import argparse
import calendar
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOS = {
    "XAGUSD": "OANDA_XAGUSD_Silver",
    "XPTUSD": "OANDA_XPTUSD_Platinum",
    "XPDUSD": "OANDA_XPDUSD_Palladium",
    "XAUUSD": "OANDA_XAUUSD_Gold",
    "XAUJPY": "OANDA_XAUJPY_GoldJPY",
    "XBRUSD": "OANDA_BCOUSD_Brent-Crude-Oil",
    "XTIUSD": "OANDA_WTICOUSD_West-Texas-Oil",
    # cash indices (OANDA CFD names -> the usual MT5 names)
    "US100": "OANDA_NAS100USD_US-Nas-100",
    "US500": "OANDA_SPX500USD_US-SPX-500",
    "US30": "OANDA_US30USD_US-Wall-St-30",
    "GER40": "OANDA_DE30EUR_Germany-30",
    "UK100": "OANDA_UK100GBP_UK-100",
}
DEFAULT = ["XAGUSD", "XPTUSD", "XPDUSD", "XAUUSD"]
BASE = "https://raw.githubusercontent.com/bunqii/{repo}/main/1/{repo}_1_{y}-{m:02d}-01_to_{y}-{m:02d}-{d:02d}.parquet"


def months(start: str, end: str):
    y, m = map(int, start.split("-"))
    ye, me = map(int, end.split("-"))
    while (y, m) <= (ye, me):
        yield y, m
        m += 1
        if m > 12:
            y, m = y + 1, 1


def main() -> int:
    today = date.today()
    last = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+", default=DEFAULT,
                    help=f"any of {sorted(REPOS)}")
    ap.add_argument("--start", default="2019-01")
    ap.add_argument("--end", default=f"{last[0]}-{last[1]:02d}", help="last COMPLETE month")
    args = ap.parse_args()

    for sym in args.symbols:
        repo = REPOS[sym.upper()]
        out = ROOT / "data" / "raw" / sym.upper()
        out.mkdir(parents=True, exist_ok=True)
        got = 0
        for y, m in months(args.start, args.end):
            d = calendar.monthrange(y, m)[1]
            url = BASE.format(repo=repo, y=y, m=m, d=d)
            dest = out / url.rsplit("/", 1)[1]
            if dest.exists() and dest.stat().st_size > 0:
                got += 1
                continue
            for attempt in range(4):
                try:
                    with urllib.request.urlopen(url, timeout=120) as r:
                        dest.write_bytes(r.read())
                    got += 1
                    break
                except Exception as exc:  # noqa: BLE001 - report and retry
                    if attempt == 3:
                        print(f"  {sym} {y}-{m:02d}: {exc}", file=sys.stderr)
                    time.sleep(2 ** attempt)
        print(f"{sym}: {got} monthly files in {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
