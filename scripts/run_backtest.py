#!/usr/bin/env python3
"""Run a saved configuration and produce its report.

    python3 scripts/run_backtest.py --config config/XAUUSD_momentum.json --report

Use this to re-check a parameter set after dropping new data into data/raw/, or
to run the cost-sensitivity and Monte-Carlo checks on an existing config.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping import backtest as bt
from scalping import dataset, metrics as M, report as R, research
from scalping.engine import ExecConfig
from scalping.strategy import StrategyParams


def load_config(path: Path):
    cfg = json.loads(path.read_text())
    s_fields = {f for f in StrategyParams().__dataclass_fields__}
    e_fields = {f for f in ExecConfig.__dataclass_fields__}
    s = StrategyParams(**{k: v for k, v in cfg["strategy"].items() if k in s_fields})
    e = ExecConfig(**{k: v for k, v in cfg["execution"].items() if k in e_fields})
    return cfg, s, e


def cost_sensitivity(prep, s, e, multipliers=(1.0, 1.25, 1.5, 2.0)) -> pd.DataFrame:
    """How much worse do costs have to get before the edge dies?

    A strategy whose profit factor falls below 1 at 1.25x costs is not an edge,
    it is a bet on your broker.
    """
    rows = []
    inst = prep.inst
    for k in multipliers:
        e2 = replace(
            e,
            commission_per_lot_rt=inst.commission_per_lot_rt * k,
            slippage_points_entry=inst.slippage_points_entry * k,
            slippage_points_stop=inst.slippage_points_stop * k,
        )
        p2 = bt.Prepared(
            symbol=prep.symbol, inst=prep.inst, exec_bars=prep.exec_bars,
            spread_points=prep.spread_points * k, sig_cache=prep.sig_cache,
            dir_cache=prep.dir_cache,
        )
        m, _, _ = bt.run(p2, s, e2)
        rows.append({
            "cost_multiple": k, "trades": m.n_trades,
            "win_rate_%": round(m.win_rate * 100, 1),
            "profit_factor": round(m.profit_factor, 3),
            "expectancy_R": round(m.expectancy_r, 4),
        })
    return pd.DataFrame(rows)


def monte_carlo(trades: pd.DataFrame, n: int = 5000, seed: int = 0) -> dict:
    """Two different questions, two different resamplings.

    **Permutation** (shuffle without replacement) keeps the same trades and only
    changes their order.  It answers "how bad could the drawdown path have been
    with this exact set of results?"  It cannot say anything about the final
    total, which is invariant under reordering -- a reshuffle-only Monte Carlo
    that reports a distribution of final equity is reporting a constant.

    **Bootstrap** (resample with replacement) draws a different sample of trades
    each time and does answer "what else could this edge have produced?"
    """
    if len(trades) < 20:
        return {}
    r = trades["r"].to_numpy()
    m = len(r)
    rng = np.random.default_rng(seed)

    dds = np.empty(n)
    for i in range(n):
        cum = np.cumsum(rng.permutation(r))
        dds[i] = np.max(np.maximum.accumulate(cum) - cum)

    boot_final = np.empty(n)
    boot_dd = np.empty(n)
    for i in range(n):
        sample = r[rng.integers(0, m, m)]
        cum = np.cumsum(sample)
        boot_final[i] = cum[-1]
        boot_dd[i] = np.max(np.maximum.accumulate(cum) - cum)

    return {
        "actual_total_R": float(r.sum()),
        "perm_median_max_dd_R": float(np.median(dds)),
        "perm_p95_max_dd_R": float(np.percentile(dds, 95)),
        "boot_p05_total_R": float(np.percentile(boot_final, 5)),
        "boot_median_total_R": float(np.median(boot_final)),
        "boot_p95_total_R": float(np.percentile(boot_final, 95)),
        "boot_prob_total_negative": float((boot_final < 0).mean()),
        "boot_p95_max_dd_R": float(np.percentile(boot_dd, 95)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--min-trades", type=int, default=100)
    ap.add_argument("--min-pf", type=float, default=1.2)
    ap.add_argument("--min-wr", type=float, default=0.50)
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    cfg, s, e = load_config(cfg_path)
    symbol = cfg["symbol"]

    ds = dataset.load(
        symbol,
        start=args.start or "2019-01-02",
        end=args.end or "2025-12-31",
    )
    print(ds.banner(), flush=True)
    prep = bt.prepare(ds.bars, symbol)

    m, trades, res = bt.run(prep, s, e)
    print("\nfull sample:", m.summary())

    cost_df = cost_sensitivity(prep, s, e)
    print("\ncost sensitivity:")
    print(cost_df.to_string(index=False))

    mc = monte_carlo(trades)
    if mc:
        print("\nmonte carlo:")
        for k, v in mc.items():
            print(f"  {k:24s} {v:.3f}")

    friction = research.round_trip_cost_points(prep.inst)
    print(f"\nround-trip friction: {friction:.1f} points = "
          f"{prep.inst.fmt_distance(friction * prep.inst.point)}")

    if args.report:
        outdir = ROOT / "reports"
        tag = f"{symbol}_{cfg['mode']}_full"
        R.equity_plot(trades, outdir / f"{tag}_equity.png",
                      f"{symbol} {cfg['mode']} - full sample "
                      f"({'SYNTHETIC' if ds.is_synthetic else 'real'} data)")
        md = [
            f"# {symbol} - {cfg['mode']} - full-sample backtest",
            "",
            f"- data: **{'SYNTHETIC (engine validation only)' if ds.is_synthetic else 'real'}** - {ds.source}",
            f"- span: {ds.bars.index[0]:%Y-%m-%d} to {ds.bars.index[-1]:%Y-%m-%d}",
            "",
            "> Full-sample numbers include the windows the parameters were fitted on.",
            "> The honest estimate is the walk-forward out-of-sample report.",
            "",
            R.targets_table(m, args.min_trades, args.min_pf, args.min_wr),
            "",
            R.metrics_table({"Full sample": m}),
            "",
            "## Cost sensitivity",
            "",
            cost_df.to_markdown(index=False),
            "",
            "## Monte Carlo",
            "",
            "_Permutation answers 'how bad could the path have been'; bootstrap "
            "answers 'what else could this edge have produced'. Reordering cannot "
            "change the total, so only the bootstrap rows speak to the outcome._",
            "",
            "\n".join(f"- {k}: {v:.3f}" for k, v in mc.items()) if mc else "_too few trades_",
            "",
            "## Breakdown",
            "",
            R.breakdown_tables(trades) if len(trades) else "_no trades_",
            "",
            "## Parameters",
            "",
            R.params_block(s, e),
            "",
            f"![equity]({tag}_equity.png)",
        ]
        (outdir / f"{tag}.md").write_text("\n".join(md))
        if len(trades):
            trades.to_csv(outdir / f"{tag}_trades.csv", index=False)
        print(f"\nwrote reports/{tag}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
