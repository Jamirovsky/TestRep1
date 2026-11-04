"""One parameter set, many symbols: search and validation for basket EAs.

The stock and index EAs trade a whole basket (7 stocks / 5 indices) with ONE
shared parameter set.  That is a deliberate anti-overfitting choice: a set has
to work on several instruments at once, and the pooled trade count is several
times larger than any single symbol's, so the fit rests on more observations.

All parameters are scale-free (ATR multiples, R multiples, basis-point stop
floors, market-relative sessions), so the same numbers mean the same thing on
NVDA at USD 180 and on MSFT at USD 500, or on the S&P at 6,000 and the Dow at
45,000.

Pooled metrics treat every trade as a draw in R and compound them at the
configured risk in time order -- the same treatment walk-forward folds get in
``optimize._stitch_metrics``.
"""
from __future__ import annotations

import random
from dataclasses import replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import backtest as bt
from . import optimize as O
from .engine import ExecConfig
from .metrics import Metrics
from .strategy import StrategyParams


class Basket:
    """A list of prepared symbols that are always evaluated together."""

    def __init__(self, preps: Dict[str, bt.Prepared]):
        self.preps = preps

    def slice(self, start: Optional[str], end: Optional[str]) -> "Basket":
        return Basket({k: p.slice(start, end) for k, p in self.preps.items()})

    def run(self, s: StrategyParams, e_base: ExecConfig) -> Tuple[Metrics, pd.DataFrame]:
        frames = []
        for sym, prep in self.preps.items():
            e = replace(e_base, **exec_costs(prep.inst))
            _, tr, _ = bt.run(prep, s, e)
            if len(tr):
                tr = tr.assign(symbol=sym)
                frames.append(tr)
        if not frames:
            return Metrics(), pd.DataFrame()
        trades = pd.concat(frames).sort_values("entry_time").reset_index(drop=True)
        m = O._stitch_metrics(trades, e_base.initial_equity, e_base.risk_pct)
        return m, trades

    def span_days(self) -> float:
        idx = [p.exec_bars.index for p in self.preps.values() if len(p.exec_bars)]
        return (max(i[-1] for i in idx) - min(i[0] for i in idx)).days


def exec_costs(inst) -> Dict:
    """The per-instrument part of an ExecConfig (costs and contract)."""
    e = bt.exec_config_from(inst)
    keys = ("point", "value_per_point_per_lot", "min_lot", "lot_step", "max_lot",
            "commission_per_lot_rt", "slippage_points_entry", "slippage_points_stop",
            "swap_long_points", "swap_short_points", "max_spread_points")
    return {k: getattr(e, k) for k in keys}


def evaluate(basket: Basket, values: Dict, base_s, base_e) -> Tuple[Metrics, pd.DataFrame]:
    s, e = O.build(values, base_s, base_e)
    return basket.run(s, e)


def per_symbol(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sym, g in trades.groupby("symbol"):
        w, l = g.r[g.r > 0].sum(), -g.r[g.r <= 0].sum()
        rows.append({"symbol": sym, "trades": len(g), "win_rate": (g.r > 0).mean(),
                     "profit_factor": w / l if l > 0 else np.inf,
                     "expectancy_r": g.r.mean(), "total_r": g.r.sum()})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
_W: Dict[str, object] = {}


def _init(basket, base_s, base_e, targets):
    _W.update(b=basket, s=base_s, e=base_e, t=targets)


def _eval(values):
    m, tr = evaluate(_W["b"], values, _W["s"], _W["e"])
    frac = 0.0
    if len(tr):
        ps = per_symbol(tr)
        frac = float((ps.expectancy_r > 0).mean())
    return values, m, O.score(m, _W["t"]), frac


def search(basket: Basket, space: Dict[str, Sequence], base_s, base_e, targets,
           n_iter: int = 300, seed: int = 0, workers: int = 4, extra: Sequence[Dict] = ()):
    """Random search (plus any explicitly supplied candidates), pooled score."""
    import multiprocessing as mp

    rng = random.Random(seed)
    seen, batch = set(), []
    for v in list(extra):
        key = tuple(sorted(v.items()))
        if key not in seen:
            seen.add(key)
            batch.append(v)
    for _ in range(n_iter * 3):
        if len(batch) >= n_iter + len(extra):
            break
        v = {k: rng.choice(list(opts)) for k, opts in space.items()}
        key = tuple(sorted(v.items()))
        if key not in seen:
            seen.add(key)
            batch.append(v)
    batch.sort(key=lambda v: bt.direction_key(O.build(v, base_s, base_e)[0]))
    ctx = mp.get_context("fork")
    with ctx.Pool(workers, initializer=_init, initargs=(basket, base_s, base_e, targets)) as pool:
        out = list(pool.imap(_eval, batch, chunksize=max(1, len(batch) // (workers * 4))))
    out.sort(key=lambda x: x[2] if np.isfinite(x[2]) else -1e18, reverse=True)
    return out


def refine(basket: Basket, seed_values: Dict, space, base_s, base_e, targets, rounds: int = 2,
           workers: int = 4):
    """Coordinate descent: sweep each parameter's options in parallel, keep the best."""
    cur = dict(seed_values)
    best = search(basket, {}, base_s, base_e, targets, n_iter=0, extra=[cur], workers=1)[0]
    for _ in range(rounds):
        improved = False
        for key, opts in space.items():
            trials = [{**cur, key: o} for o in opts if o != cur.get(key)]
            if not trials:
                continue
            res = search(basket, {}, base_s, base_e, targets, n_iter=0, extra=trials,
                         workers=min(workers, len(trials)))
            if res and res[0][2] > best[2]:
                best, cur, improved = res[0], dict(res[0][0]), True
        if not improved:
            break
    return best


def robust_rank(basket: Basket, cands, base_s, base_e, targets, top_k: int = 20, n_sub: int = 3):
    """Re-rank the top candidates by their worst time-third, ties by symbol breadth."""
    idx = [p.exec_bars.index for p in basket.preps.values()]
    t0, t1 = min(i[0] for i in idx), max(i[-1] for i in idx)
    edges = [t0 + (t1 - t0) * k / n_sub for k in range(n_sub + 1)]
    subs = [basket.slice(str(edges[k].date()), str(edges[k + 1].date())) for k in range(n_sub)]
    st = replace(targets, trade_scale=targets.trade_scale / n_sub)
    ranked = []
    for v, m, sc, frac in [c for c in cands if np.isfinite(c[2])][:top_k]:
        sub_scores = [O.score(evaluate(b, v, base_s, base_e)[0], st) for b in subs]
        worst = min(sub_scores)
        ranked.append(((worst if np.isfinite(worst) else -1e18, frac, sc), v, m, sc, frac, sub_scores))
    ranked.sort(key=lambda x: x[0], reverse=True)
    return ranked
