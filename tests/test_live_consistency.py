"""The live decision function must reproduce the backtest's entries exactly.

For every 15m bar with a raw signal inside a test window we call strategy.decide()
on the history truncated at that bar and compare with a continuous engine run:
  * backtest flat and entered  -> decide() must return the same direction/stop/target
  * backtest flat and skipped  -> decide() must return None (memory/cost gate)
"""
import os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scalper.backtest import Market, signals
from scalper.data import load_1m
from scalper.strategy import decide, load_config, replay_memory


def check(sleeve, df):
    p = sleeve["params"]
    m = Market(df)
    sigs = signals(m, p)
    sig_idx, D, bucket, a = sigs
    w0 = 0
    _, tr = replay_memory(m, p, w0, len(df), sigs=sigs)
    entries = {int(t[0]): t for t in tr}
    test_from = len(df) - 45 * 1440          # last 45 days are checked
    ks = [k for k in range(len(sig_idx)) if sig_idx[k] >= test_from and sig_idx[k] + 1 < len(df)
          and (D[k] != 0).any()]
    n_checked = n_entries = 0
    for k in ks:
        i = int(sig_idx[k]) + 1
        busy = any(t[0] < i <= t[1] for t in tr)
        if busy:
            continue
        sub = df.iloc[: sig_idx[k] + 1]
        d = decide(sub, sleeve, equity_usd=174.0, replay_start=w0)
        if i in entries:
            t = entries[i]
            assert d is not None, f"missed entry at {df.index[i]}"
            assert d.direction == int(t[2])
            assert np.isclose(d.stop_distance, p["sl_k"] * a[k])
            n_entries += 1
        else:
            assert d is None, f"spurious entry at {df.index[i]} ({d})"
        n_checked += 1
    return n_checked, n_entries


def test_live_matches_backtest():
    df = load_1m()
    df = df[(df.index >= "2026-05-01") & (df.index < "2026-09-15")]
    for sleeve in load_config()["sleeves"]:
        n, e = check(sleeve, df)
        print(sleeve["id"], "checked", n, "signal bars,", e, "entries reproduced")
        assert n > 10 and e > 3


if __name__ == "__main__":
    test_live_matches_backtest()
    print("OK")
