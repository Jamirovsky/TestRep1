"""Export BTCUSD history + contract specification from your MT5 terminal
(Capital Point Trading) so the research pipeline runs on the broker's own data.

Run on the Windows PC where MetaTrader 5 is installed and logged in:

    pip install MetaTrader5 pandas
    python mt5/export_btcusd.py --symbol BTCUSD --start 2024-11-01

Before running: in MT5 set Tools > Options > Charts > "Max bars in chart" to
Unlimited (otherwise MT5 only returns the most recent bars), and open a BTCUSD M1
chart once so the terminal downloads the history.

Outputs (copy them into the repo's data/ folder):
    data/mt5_btcusd_m1.csv       time (UTC epoch s), open, high, low, close (BID), tick_volume, spread (points), real_volume
    data/mt5_symbol_spec.json    raw symbol spec + a derived cost profile used by the backtester
"""
from __future__ import annotations
import argparse, json, os, time
from datetime import datetime, timezone, timedelta

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError as e:  # pragma: no cover
    raise SystemExit("pip install MetaTrader5  (Windows only, MT5 terminal must be installed)") from e

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def server_utc_offset(symbol: str) -> int:
    """MT5 bar times are in *server* time.  Estimate the offset (whole hours)."""
    tick = mt5.symbol_info_tick(symbol)
    if tick is None or tick.time == 0:
        return 0
    diff = tick.time - int(time.time())
    return int(round(diff / 3600.0)) * 3600


def fetch_m1(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    parts = []
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=30), end)
        r = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, cur, nxt)
        if r is not None and len(r):
            parts.append(pd.DataFrame(r))
        else:
            print("  no data", cur.date(), "->", nxt.date(), mt5.last_error())
        cur = nxt
    if not parts:
        raise SystemExit("No M1 data returned. Open a BTCUSD M1 chart, scroll back, and retry.")
    df = pd.concat(parts).drop_duplicates("time").sort_values("time")
    return df


def swap_to_fraction(info, price: float):
    """Convert MT5 swap settings into 'fraction of notional per night' (positive = cost)."""
    mode = info.swap_mode
    sl, ss = info.swap_long, info.swap_short
    if mode in (mt5.SYMBOL_SWAP_MODE_INTEREST_CURRENT, mt5.SYMBOL_SWAP_MODE_INTEREST_OPEN):
        return -sl / 100 / 360, -ss / 100 / 360, "annual % interest"
    if mode == mt5.SYMBOL_SWAP_MODE_POINTS:
        return -sl * info.point / price, -ss * info.point / price, "points"
    if mode in (mt5.SYMBOL_SWAP_MODE_CURRENCY_SYMBOL, mt5.SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT,
                mt5.SYMBOL_SWAP_MODE_CURRENCY_MARGIN):
        notional = price * info.trade_contract_size
        return -sl / notional, -ss / notional, "money per lot (approx.)"
    return 0.0, 0.0, f"mode {mode} not converted"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSD")
    ap.add_argument("--start", default="2024-11-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--terminal", default=None, help="path to terminal64.exe if not the default")
    a = ap.parse_args()

    ok = mt5.initialize(path=a.terminal) if a.terminal else mt5.initialize()
    if not ok:
        raise SystemExit(f"MT5 initialize failed: {mt5.last_error()}")
    acc = mt5.account_info()
    print("Account:", acc.server, acc.currency, "leverage 1:%d" % acc.leverage,
          "margin mode", acc.margin_mode)
    if not mt5.symbol_select(a.symbol, True):
        raise SystemExit(f"Symbol {a.symbol} not found. Check the exact name in Market Watch.")
    info = mt5.symbol_info(a.symbol)
    tick = mt5.symbol_info_tick(a.symbol)
    off = server_utc_offset(a.symbol)
    print(f"Server time offset vs UTC: {off / 3600:+.0f}h")

    start = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    end = datetime.fromisoformat(a.end).replace(tzinfo=timezone.utc) if a.end else datetime.now(timezone.utc)
    df = fetch_m1(a.symbol, start + timedelta(seconds=off), end + timedelta(seconds=off))
    df["time"] = df["time"].astype("int64") - off            # -> UTC
    os.makedirs(DATA, exist_ok=True)
    out_csv = os.path.join(DATA, "mt5_btcusd_m1.csv")
    df[["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]].to_csv(out_csv, index=False)
    print("wrote", out_csv, len(df), "bars",
          pd.to_datetime(df.time.iloc[0], unit="s"), "->", pd.to_datetime(df.time.iloc[-1], unit="s"))

    price = (tick.bid + tick.ask) / 2
    contract = info.trade_contract_size
    spread_usd = df["spread"].astype(float) * info.point
    margin_1lot = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY, a.symbol, 1.0, tick.ask)
    # margin is in account currency; profit of 1 USD move on 1 lot gives the USD->account rate
    pnl_1usd = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, a.symbol, 1.0, tick.ask, tick.ask + 1.0)
    usd_to_acc = (pnl_1usd / contract) if pnl_1usd else 1.0
    lev = (price * contract * usd_to_acc / margin_1lot) if margin_1lot else float(acc.leverage)
    fl, fs, swap_desc = swap_to_fraction(info, price)
    equity_usd = acc.equity / usd_to_acc if usd_to_acc else acc.equity

    spec = {
        "exported_utc": datetime.now(timezone.utc).isoformat(),
        "server": acc.server, "account_currency": acc.currency, "account_leverage": acc.leverage,
        "margin_mode": acc.margin_mode,  # 2 = hedging (recommended), 0 = netting
        "symbol": a.symbol, "digits": info.digits, "point": info.point,
        "contract_size": contract, "volume_min": info.volume_min, "volume_step": info.volume_step,
        "volume_max": info.volume_max, "stops_level_points": info.trade_stops_level,
        "swap_mode": info.swap_mode, "swap_long": info.swap_long, "swap_short": info.swap_short,
        "swap_rollover3days": info.swap_rollover3days, "swap_conversion": swap_desc,
        "margin_1lot_account_ccy": margin_1lot, "effective_leverage": lev,
        "spread_usd_median": float(spread_usd.median()), "spread_usd_p90": float(spread_usd.quantile(0.9)),
        "server_utc_offset_s": off, "equity_account_ccy": acc.equity,
        "cost_profile": {
            "spread": round(float(spread_usd.median()), 2),
            "leverage": round(float(lev), 2),
            "min_size": info.volume_min * contract,
            "size_step": info.volume_step * contract,
            "fee_long": max(fl, 0.0), "fee_short": max(fs, 0.0),
            "fx_fee": 0.0,
        },
    }
    out_json = os.path.join(DATA, "mt5_symbol_spec.json")
    with open(out_json, "w") as f:
        json.dump(spec, f, indent=1)
    print("wrote", out_json)
    print(json.dumps(spec["cost_profile"], indent=1))
    mt5.shutdown()


if __name__ == "__main__":
    main()
