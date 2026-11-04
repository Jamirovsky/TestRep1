#!/usr/bin/env python3
"""Cumulative-R chart of a trades CSV (one line overall, one per symbol).

    python3 scripts/plot_r_curve.py reports/basket_stocks_wf_base_M5_momentum.csv \
        reports/stocks_wf_equity.png "7 stocks - walk-forward OOS"
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

src, dst, title = sys.argv[1], sys.argv[2], sys.argv[3]
t = pd.read_csv(src, parse_dates=["entry_time", "exit_time"]).sort_values("exit_time")
fig, ax = plt.subplots(figsize=(10, 4.5), dpi=110)
if "symbol" in t:
    for sym, g in t.groupby("symbol"):
        ax.plot(g["exit_time"], g["r"].cumsum(), lw=0.9, alpha=0.55, label=sym)
ax.plot(t["exit_time"], t["r"].cumsum(), lw=2.2, color="black", label="total")
ax.axhline(0, color="grey", lw=0.6)
ax.set_title(title)
ax.set_ylabel("cumulative R")
ax.legend(ncol=4, fontsize=8, frameon=False)
ax.grid(alpha=0.25)
fig.tight_layout()
fig.savefig(dst)
print("wrote", dst)
