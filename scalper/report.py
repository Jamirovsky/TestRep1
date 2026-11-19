"""Build results/equity.png from the final configuration (dev + holdout)."""
from __future__ import annotations
import os
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .backtest import Market, COSTS, run_period, run_ensemble, metrics
from .data import load_1m
from .strategy import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    cfg = load_config()
    m = Market(load_1m())
    plist = [s["params"] for s in cfg["sleeves"]]
    start, split, end = "2024-11-15", "2026-08-01", "2026-11-19"
    if len(plist) == 1:
        tr, deq, _, i0 = run_period(m, plist[0], start, end)
    else:
        tr, deq, i0 = run_ensemble(m, plist, start, end)
    days = pd.date_range(start, periods=len(deq), freq="D", tz="UTC")
    eur = deq / 1.16
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=130)
    ax.plot(days, eur, color="#2563eb", lw=1.6)
    ax.axvspan(pd.Timestamp(split, tz="UTC"), days[-1], color="#f59e0b", alpha=0.12)
    ax.text(pd.Timestamp(split, tz="UTC"), eur.max(), "  holdout\n  (never optimised on)", va="top",
            fontsize=9, color="#92400e")
    ax.axhline(150, color="#9ca3af", lw=0.8, ls="--")
    ax.set_ylabel("Account equity (EUR)")
    ax.set_title(f"{cfg['name']} - 150 EUR account, broker costs included", fontsize=10)
    ax.grid(alpha=0.25)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    out = os.path.join(ROOT, "results", "equity.png")
    fig.savefig(out)
    mt = metrics(tr, deq, COSTS["equity0"])
    print("saved", out, {k: round(v, 3) if isinstance(v, float) else v for k, v in mt.items()})


if __name__ == "__main__":
    main()
