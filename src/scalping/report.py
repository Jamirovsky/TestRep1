"""Report generation: markdown tables, equity curves, trade analytics."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .metrics import Metrics, breakdown

PALETTE = {
    "line": "#2563eb",
    "line2": "#dc2626",
    "fill": "#2563eb22",
    "grid": "#e5e7eb",
    "dd": "#dc262633",
    "text": "#111827",
}


def _fmt(v, nd=2):
    if isinstance(v, float):
        if not np.isfinite(v):
            return "n/a"
        return f"{v:.{nd}f}"
    return str(v)


def metrics_table(named: Dict[str, Metrics]) -> str:
    """Markdown table comparing several metric sets side by side."""
    rows = [
        ("Trades", "n_trades", 0), ("Win rate %", "win_rate", 1),
        ("Profit factor", "profit_factor", 2), ("Expectancy (R)", "expectancy_r", 3),
        ("Avg win (R)", "avg_win_r", 2), ("Avg loss (R)", "avg_loss_r", 2),
        ("Payoff", "payoff", 2), ("Total R", "total_r", 1),
        ("Return %", "return_pct", 1), ("Max DD %", "max_dd_pct", 1),
        ("Max DD (R)", "max_dd_r", 1), ("Sharpe", "sharpe", 2),
        ("Sortino", "sortino", 2), ("CAGR %", "cagr_pct", 1),
        ("Calmar", "calmar", 2), ("Trades/day", "trades_per_day", 2),
        ("Avg hold (min)", "avg_bars_held", 0), ("Max consec. losses", "max_consec_losses", 0),
        ("t-stat of mean R", "t_stat", 2), ("Cost / gross %", "cost_share_of_gross", 3),
    ]
    heads = list(named)
    out = ["| Metric | " + " | ".join(heads) + " |",
           "|---|" + "---|" * len(heads)]
    for label, attr, nd in rows:
        cells = []
        for h in heads:
            v = getattr(named[h], attr)
            if attr == "win_rate":
                v = v * 100.0
            if attr == "cost_share_of_gross":
                v = v * 100.0
            cells.append(_fmt(v, nd) if not isinstance(v, int) else str(v))
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def targets_table(m: Metrics, min_trades=100, min_pf=1.2, min_wr=0.50) -> str:
    checks = [
        ("Trades >= %d" % min_trades, m.n_trades, min_trades, m.n_trades >= min_trades, "%d"),
        ("Profit factor >= %.2f" % min_pf, m.profit_factor, min_pf, m.profit_factor >= min_pf, "%.2f"),
        ("Win rate >= %.0f%%" % (min_wr * 100), m.win_rate * 100, min_wr * 100, m.win_rate >= min_wr, "%.1f"),
    ]
    out = ["| Target | Required | Achieved | Result |", "|---|---|---|---|"]
    for label, got, need, ok, fmt in checks:
        out.append(f"| {label} | {fmt % need} | {fmt % got} | {'**PASS**' if ok else 'FAIL'} |")
    return "\n".join(out)


def equity_plot(
    trades: pd.DataFrame, path: Path, title: str, initial_equity: float = 10_000.0
) -> Path:
    """Cumulative-R curve with its drawdown underneath."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 6.5), sharex=True,
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
    )
    if len(trades) == 0:
        ax1.text(0.5, 0.5, "no trades", ha="center", va="center")
        fig.savefig(path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        return path

    t = trades.sort_values("exit_time")
    x = pd.DatetimeIndex(t["exit_time"])
    cum = t["r"].cumsum().to_numpy()
    peak = np.maximum.accumulate(cum)
    dd = cum - peak

    ax1.plot(x, cum, color=PALETTE["line"], lw=1.6)
    ax1.fill_between(x, 0, cum, color=PALETTE["fill"])
    ax1.axhline(0, color="#9ca3af", lw=0.8)
    ax1.set_ylabel("cumulative R")
    ax1.set_title(title, loc="left", fontsize=11, color=PALETTE["text"])
    ax1.grid(True, color=PALETTE["grid"], lw=0.6)
    ax1.spines[["top", "right"]].set_visible(False)

    ax2.fill_between(x, dd, 0, color=PALETTE["dd"])
    ax2.plot(x, dd, color=PALETTE["line2"], lw=1.0)
    ax2.set_ylabel("drawdown (R)")
    ax2.grid(True, color=PALETTE["grid"], lw=0.6)
    ax2.spines[["top", "right"]].set_visible(False)

    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def fold_plot(folds, path: Path, title: str) -> Path:
    """In-sample vs out-of-sample expectancy per walk-forward fold."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 4))
    n = len(folds)
    if n == 0:
        ax.text(0.5, 0.5, "no folds", ha="center", va="center")
        fig.savefig(path, dpi=130, bbox_inches="tight")
        plt.close(fig)
        return path
    idx = np.arange(n)
    w = 0.38
    ax.bar(idx - w / 2, [f.train_metrics.expectancy_r for f in folds], w,
           label="in-sample (fitted)", color="#93c5fd")
    ax.bar(idx + w / 2, [f.test_metrics.expectancy_r for f in folds], w,
           label="out-of-sample", color=PALETTE["line"])
    ax.axhline(0, color="#374151", lw=0.9)
    ax.set_xticks(idx, [f"fold {i+1}\n{f.test_start:%Y-%m}" for i, f in enumerate(folds)])
    ax.set_ylabel("expectancy (R / trade)")
    ax.set_title(title, loc="left", fontsize=11)
    ax.legend(frameon=False, fontsize=9)
    ax.grid(True, axis="y", color=PALETTE["grid"], lw=0.6)
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def breakdown_tables(trades: pd.DataFrame, which=("by_hour", "by_direction", "by_exit", "by_year")) -> str:
    b = breakdown(trades)
    out = []
    for key in which:
        if key not in b:
            continue
        df = b[key].copy()
        df["win_rate"] = (df["win_rate"] * 100).round(1)
        df["total_r"] = df["total_r"].round(1)
        df["exp_r"] = df["exp_r"].round(3)
        out.append(f"**{key.replace('_', ' ')}**\n")
        out.append(df.to_markdown())
        out.append("")
    return "\n".join(out)


def params_block(strategy_params, exec_config) -> str:
    s = asdict(strategy_params) if is_dataclass(strategy_params) else dict(strategy_params)
    e = asdict(exec_config) if is_dataclass(exec_config) else dict(exec_config)
    return (
        "```json\n"
        + json.dumps({"strategy": s, "execution": e}, indent=2, default=str)
        + "\n```"
    )
