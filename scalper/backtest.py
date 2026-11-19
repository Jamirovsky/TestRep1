"""High-level backtest helpers: data prep, parameter space, metrics, objective."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd

from . import engine
from .data import load_1m, resample

# ----------------------------------------------------------------------------
# Broker cost profiles.  Default = Capital Point Trading (MT5) BTCUSD CFD.
# Exact values should be refreshed from the MT5 terminal with
# mt5/export_btcusd.py, which writes data/mt5_symbol_spec.json; that file, if
# present, overrides the defaults below automatically.
# ----------------------------------------------------------------------------
EURUSD = 1.16  # used to convert the 150 EUR account into USD
PROFILES = {
    "capital_point_mt5": {
        "spread": 30.0,         # USD per BTC (typical raw-pricing crypto spread; refresh from MT5)
        "slip": 5.0,            # extra USD/BTC slippage on stop fills
        "leverage": 20.0,       # assumed crypto leverage; refresh from MT5 (margin per lot)
        "margin_use": 0.8,      # never use more than 80% of max notional
        "min_size": 0.01,       # BTC (0.01 lot x contract size 1)
        "size_step": 0.01,
        "fee_long": 0.20 / 365,   # swap ~ -20%/yr on notional, charged nightly (both sides)
        "fee_short": 0.20 / 365,
        "fx_fee": 0.0,          # MT5 converts USD P&L to EUR at market, no extra fee assumed
        "equity0": 150.0 * EURUSD,
        "minlot_risk_cap": 0.05,  # min lot allowed while its stop risk <= 5% of equity
    },
    "capital_com": {  # kept for reference (first research round)
        "spread": 50.0, "slip": 5.0, "leverage": 2.0, "margin_use": 0.8, "min_size": 0.0001,
        "size_step": 0.0001, "fee_long": 0.0006164, "fee_short": 0.0, "fx_fee": 0.007,
        "equity0": 150.0 * EURUSD, "minlot_risk_cap": 0.0,
    },
}


def _load_profile():
    import json, os
    name = os.environ.get("AMS_BROKER", "capital_point_mt5")
    prof = dict(PROFILES[name])
    spec = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data",
                        "mt5_symbol_spec.json")
    if name == "capital_point_mt5" and os.path.exists(spec):
        prof.update(json.load(open(spec)).get("cost_profile", {}))
    return prof


COSTS = _load_profile()


def cost_array(c=None):
    c = {**COSTS, **(c or {})}
    return np.array([c["spread"], c["slip"], c["leverage"], c["margin_use"], c["min_size"],
                     c["size_step"], c["fee_long"], c["fee_short"], c["fx_fee"], c["equity0"],
                     c.get("minlot_risk_cap", 0.0)], dtype=np.float64)


# ----------------------------------------------------------------------------
# parameter space
# ----------------------------------------------------------------------------
SIG_KEYS = ["atr_n", "imp_n", "imp_thr", "don_n", "z_n", "z_in", "er_n", "er_thr", "htf_n",
            "vol_n", "fam_mask", "bucket", "mom_n", "trend_filter"]
EXE_KEYS = ["sl_k", "tp_k", "max_hold", "be_trig", "trail_k", "risk", "mem_alpha",
            "mem_thr", "mem_warm", "mem_k", "min_stop_spread", "dd_cut"]

DEFAULTS = dict(tf=5, atr_n=14, imp_n=3, imp_thr=3.0, don_n=48, z_n=20, z_in=2.0, er_n=20,
                er_thr=0.35, htf_n=96, vol_n=288, fam_mask=63, bucket=1, mom_n=672, trend_filter=0,
                sl_k=1.5, tp_k=2.0, max_hold=12, be_trig=1.0, trail_k=0.0, risk=0.01,
                mem_alpha=0.1, mem_thr=0.05, mem_warm=8, mem_k=0.5,
                min_stop_spread=3.0, dd_cut=0.1)


def suggest(trial):
    """Full Optuna search space (all six families on, memory picks among them)."""
    p = dict(DEFAULTS)
    p["tf"] = trial.suggest_categorical("tf", [1, 3, 5, 15])
    p["atr_n"] = trial.suggest_int("atr_n", 7, 40)
    p["imp_n"] = trial.suggest_int("imp_n", 1, 12)
    p["imp_thr"] = trial.suggest_float("imp_thr", 1.5, 5.0)
    p["don_n"] = trial.suggest_int("don_n", 10, 120)
    p["z_n"] = trial.suggest_int("z_n", 10, 80)
    p["z_in"] = trial.suggest_float("z_in", 1.0, 4.0)
    p["er_n"] = trial.suggest_int("er_n", 8, 40)
    p["er_thr"] = trial.suggest_float("er_thr", 0.2, 0.6)
    p["htf_n"] = trial.suggest_int("htf_n", 30, 400)
    p["vol_n"] = trial.suggest_int("vol_n", 50, 600)
    p["bucket"] = trial.suggest_categorical("bucket", [0, 1, 2])
    p["sl_k"] = trial.suggest_float("sl_k", 0.7, 4.0)
    p["tp_k"] = trial.suggest_float("tp_k", 0.7, 6.0)
    p["max_hold"] = trial.suggest_int("max_hold", 3, 60)
    p["be_trig"] = trial.suggest_categorical("be_trig", [0.0, 0.75, 1.0, 1.5, 2.0])
    p["trail_k"] = trial.suggest_categorical("trail_k", [0.0, 1.0, 1.5, 2.5])
    p["risk"] = trial.suggest_float("risk", 0.005, 0.03)
    p["mem_alpha"] = trial.suggest_float("mem_alpha", 0.03, 0.4)
    p["mem_thr"] = trial.suggest_float("mem_thr", 0.0, 0.3)
    p["mem_warm"] = trial.suggest_int("mem_warm", 3, 20)
    p["mem_k"] = trial.suggest_float("mem_k", 0.0, 1.0)
    p["min_stop_spread"] = trial.suggest_float("min_stop_spread", 1.5, 10.0)
    p["dd_cut"] = trial.suggest_float("dd_cut", 0.05, 0.3)
    return p


# ----------------------------------------------------------------------------
# data container
# ----------------------------------------------------------------------------
@dataclass
class Market:
    df1: pd.DataFrame
    o1: np.ndarray = field(init=False)
    tf_cache: dict = field(default_factory=dict)

    def __post_init__(self):
        d = self.df1
        self.o1 = d["open"].to_numpy()
        self.h1 = d["high"].to_numpy()
        self.l1 = d["low"].to_numpy()
        self.c1 = d["close"].to_numpy()
        idx = d.index
        self.mod = (idx.hour * 60 + idx.minute).to_numpy().astype(np.int64)
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        self.day = np.asarray((idx - epoch).days, dtype=np.int64)
        self.epoch = epoch

    def tf(self, minutes):
        if minutes not in self.tf_cache:
            r = resample(self.df1, minutes)
            # 1m index of the last minute inside each TF bar
            end_time = r.index + pd.Timedelta(minutes=minutes - 1)
            sig_idx = self.df1.index.get_indexer(end_time, method="pad").astype(np.int64)
            self.tf_cache[minutes] = (r["open"].to_numpy(), r["high"].to_numpy(),
                                      r["low"].to_numpy(), r["close"].to_numpy(),
                                      r["volume"].to_numpy(), sig_idx,
                                      np.asarray(end_time.hour, dtype=np.int64))
        return self.tf_cache[minutes]

    def i_of(self, ts):
        ts = pd.Timestamp(ts)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
        return int(self.df1.index.searchsorted(ts))


def sig_vec(p):
    return np.array([p[k] for k in SIG_KEYS], dtype=np.float64)


def exe_vec(p):
    return np.array([p[k] for k in EXE_KEYS], dtype=np.float64)


def signals(m: Market, p):
    o, h, l, c, v, sig_idx, hour = m.tf(int(p["tf"]))
    D, bucket, a = engine.tf_signals(o, h, l, c, v, sig_vec(p), hour)
    return sig_idx, D, bucket, a


def run_period(m: Market, p, start, end, cost=None, mem=None, sigs=None, warm_days=60):
    """Backtest [start, end).  Unless an explicit `mem` is given, the memory is first
    warmed on the `warm_days` before `start` (shadow trades only; that period's real
    trades are discarded), exactly like letting the bot run in paper mode first."""
    if sigs is None:
        sigs = signals(m, p)
    ca = cost_array(cost)
    e = exe_vec(p)
    i0, i1 = m.i_of(start), m.i_of(end)
    if mem is None:
        mem = np.zeros((engine.NCELL, 2))
        w0 = max(0, i0 - warm_days * 1440)
        if i0 - w0 > 1440:
            _, _, mem = _run_slice(m, w0, i0, sigs, e, ca, mem, int(p["tf"]))
    tr, deq, mem = _run_slice(m, i0, i1, sigs, e, ca, mem, int(p["tf"]))
    return tr, deq, mem, i0


def _run_slice(m, i0, i1, sigs, e, ca, mem, tf):
    sig_idx, D, bucket, a = sigs
    sel = (sig_idx >= i0) & (sig_idx < i1 - 1) & (D != 0).any(axis=1)
    return engine.run(m.o1[i0:i1], m.h1[i0:i1], m.l1[i0:i1], m.c1[i0:i1], m.mod[i0:i1],
                      m.day[i0:i1], sig_idx[sel] - i0, D[sel], bucket[sel], a[sel],
                      tf, e, ca, mem)


# ----------------------------------------------------------------------------
# metrics + objective
# ----------------------------------------------------------------------------
def metrics(trades, deq, equity0):
    eq = np.concatenate([[equity0], deq])
    rets = np.diff(eq) / np.where(eq[:-1] > 0, eq[:-1], np.nan)
    rets = np.nan_to_num(rets)
    pnl = trades[:, 6] if len(trades) else np.zeros(0)
    gp = pnl[pnl > 0].sum()
    gl = -pnl[pnl < 0].sum()
    pf = gp / gl if gl > 0 else (np.inf if gp > 0 else 0.0)
    sd = rets.std()
    sharpe = rets.mean() / sd * np.sqrt(365) if sd > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max()
    ndays = max(1, len(deq))
    final = eq[-1]
    cagr = (final / equity0) ** (365 / ndays) - 1 if final > 0 else -1
    return {
        "trades": int(len(pnl)), "net": float(final - equity0), "ret_pct": float(100 * (final / equity0 - 1)),
        "pf": float(pf), "sharpe": float(sharpe), "max_dd_pct": float(100 * dd),
        "win_rate": float(100 * (pnl > 0).mean()) if len(pnl) else 0.0,
        "avg_R": float(trades[:, 7].mean()) if len(pnl) else 0.0,
        "cagr_pct": float(100 * cagr), "final": float(final), "days": ndays,
        "trades_per_day": float(len(pnl) / ndays),
    }


def score(mt, min_trades_per_month=8):
    """Balanced objective between profit factor and Sharpe ratio.

    geometric mean of the *edge* in each metric:  sqrt((PF-1) * Sharpe)
    PF is capped at 4 so a handful of lucky trades cannot dominate, and the score is
    penalised for drawdowns above 20% and for too few trades.
    """
    months = mt["days"] / 30.4
    if mt["trades"] < min_trades_per_month * months or mt["sharpe"] <= 0 or mt["pf"] <= 1:
        # invalid: always negative, but still graded so the optimiser can climb out
        ratio = min(1.0, mt["trades"] / max(1.0, min_trades_per_month * months))
        return float(-1.0 + 0.5 * ratio + 0.25 * np.tanh(mt["sharpe"]))
    pf = min(mt["pf"], 4.0)
    s = np.sqrt((pf - 1.0) * mt["sharpe"])
    if mt["max_dd_pct"] > 20:
        s *= 20 / mt["max_dd_pct"]
    return float(s)



def robust_score(trades, deq, equity0, i0, day_split, minute_split):
    """Score that rewards parameter sets that work in BOTH halves of a window.

    0.5 * full-window score + 0.5 * worst-half score.
    """
    full = score(metrics(trades, deq, equity0))
    eq_mid = deq[day_split - 1]
    first = trades[trades[:, 1] < minute_split] if len(trades) else trades
    second = trades[trades[:, 1] >= minute_split] if len(trades) else trades
    s1 = score(metrics(first, deq[:day_split], equity0))
    s2 = score(metrics(second, deq[day_split:], eq_mid))
    return 0.5 * full + 0.5 * min(s1, s2)


def run_ensemble(m: Market, plist, start, end, equity0=None, cost=None):
    """Trade several parameter sets side by side, each on an equal slice of the account
    (separate 'sleeves').  Returns pooled trades and the summed daily equity curve."""
    equity0 = COSTS["equity0"] if equity0 is None else equity0
    k = len(plist)
    trs, deq_sum, i0 = [], None, None
    for p in plist:
        c = dict(cost or {})
        c["equity0"] = equity0 / k
        tr, deq, _, i0 = run_period(m, p, start, end, cost=c)
        trs.append(tr)
        deq_sum = deq if deq_sum is None else deq_sum + deq
    tr = np.vstack(trs) if trs else np.zeros((0, 11))
    tr = tr[np.argsort(tr[:, 1], kind="stable")] if len(tr) else tr
    return tr, deq_sum, i0
