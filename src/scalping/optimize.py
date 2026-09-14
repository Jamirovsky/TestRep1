"""Parameter search with out-of-sample and walk-forward validation.

The point of this module is not to find the best in-sample numbers -- that is
trivial and worthless.  It is to find parameters that *keep working on data they
were not fitted to*.  Three defences against overfitting:

1. **A t-stat-like objective.**  Ranking by ``expectancy x sqrt(n_trades)``
   rather than by total profit stops a handful of lucky trades from winning the
   search.
2. **Walk-forward.**  Fit on a rolling window, record results only on the
   untouched window that follows, then stitch the out-of-sample segments into
   one equity curve.  That curve is the only performance claim worth making.
3. **Neighbourhood stability.**  A parameter set whose neighbours all collapse
   sits on a spike in the fitness landscape and will not survive live trading,
   so ``stability`` re-scores the immediate neighbours and reports the median.
"""
from __future__ import annotations

import itertools
import math
import random
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import backtest as bt
from .engine import ExecConfig
from .metrics import Metrics
from .strategy import StrategyParams

# A search space maps "s.<field>" (StrategyParams) or "e.<field>" (ExecConfig)
# to the list of values that field may take.
Space = Dict[str, Sequence]


@dataclass
class Candidate:
    values: Dict[str, object]
    metrics: Metrics
    score: float
    robust_worst: float = float("-inf")
    robust_scores: Optional[List[float]] = None

    def split(self) -> Tuple[Dict, Dict]:
        s = {k[2:]: v for k, v in self.values.items() if k.startswith("s.")}
        e = {k[2:]: v for k, v in self.values.items() if k.startswith("e.")}
        return s, e


def build(values: Dict[str, object], base_s: StrategyParams, base_e: ExecConfig):
    from .spaces import apply_fixed

    s = {k[2:]: v for k, v in values.items() if k.startswith("s.")}
    e = {k[2:]: v for k, v in values.items() if k.startswith("e.")}
    return apply_fixed(replace(base_s, **s)), replace(base_e, **e)


# ---------------------------------------------------------------------------
# objective
# ---------------------------------------------------------------------------
@dataclass
class Targets:
    min_trades: int = 100
    min_pf: float = 1.2
    min_wr: float = 0.50
    # Scalping is a holding-time claim as much as a profit claim.  Without this
    # the search happily drifts into 6-hour position trades that satisfy the
    # profit constraints but are not what was asked for.
    max_avg_hold_bars: float = 180.0   # M1 bars == minutes
    # HARD feasibility gates.  The soft penalties below merely nudge the search;
    # when the win rate and profit factor are *requirements* rather than
    # preferences, they have to disqualify candidates outright -- otherwise the
    # search maximises expectancy, which it does by raising the target and
    # LOWERING the win rate, i.e. by walking away from the requirement.
    # Set these above the final targets: out-of-sample performance degrades, so
    # the in-sample bar must be higher than the one you actually need.
    hard_min_pf: float = 0.0           # 0 = disabled
    hard_min_wr: float = 0.0           # 0 = disabled
    # the targets are stated for the whole backtest; when scoring a shorter
    # window we pro-rate the trade count by its share of the full span
    trade_scale: float = 1.0


def score(m: Metrics, t: Targets) -> float:
    """Higher is better. Returns -inf for candidates that cannot be salvaged."""
    need = max(15, int(t.min_trades * t.trade_scale))
    if m.n_trades < need:
        return -np.inf
    if not np.isfinite(m.expectancy_r):
        return -np.inf
    if t.hard_min_pf > 0.0 and m.profit_factor < t.hard_min_pf:
        return -np.inf
    if t.hard_min_wr > 0.0 and m.win_rate < t.hard_min_wr:
        return -np.inf

    # core: t-stat of mean R (edge scaled by sample size)
    base = m.expectancy_r * math.sqrt(m.n_trades)

    # soft penalties pull the search toward the stated constraints without
    # discarding near-misses that might pass once neighbours are explored
    pen = 1.0
    if m.profit_factor < t.min_pf:
        pen *= max(0.05, 1.0 - 2.5 * (t.min_pf - m.profit_factor))
    if m.win_rate < t.min_wr:
        pen *= max(0.05, 1.0 - 4.0 * (t.min_wr - m.win_rate))
    if m.max_dd_pct > 40.0:
        pen *= max(0.10, 1.0 - (m.max_dd_pct - 40.0) / 60.0)
    if m.avg_bars_held > t.max_avg_hold_bars:
        over = m.avg_bars_held / t.max_avg_hold_bars
        pen *= max(0.05, 1.0 / over ** 2)

    return base * pen if base > 0 else base / max(pen, 1e-9)


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def _sample(space: Space, rng: random.Random) -> Dict[str, object]:
    return {k: rng.choice(list(v)) for k, v in space.items()}


def evaluate(
    prep: bt.Prepared, values: Dict, base_s: StrategyParams, base_e: ExecConfig
) -> Metrics:
    s, e = build(values, base_s, base_e)
    m, _, _ = bt.run(prep, s, e)
    return m


def random_search(
    prep: bt.Prepared,
    space: Space,
    base_s: StrategyParams,
    base_e: ExecConfig,
    targets: Targets,
    n_iter: int = 400,
    seed: int = 0,
    progress: Optional[Callable[[int, int, float], None]] = None,
) -> List[Candidate]:
    """Randomised search over ``space``; returns candidates ranked by score."""
    rng = random.Random(seed)
    seen: set = set()
    out: List[Candidate] = []
    for i in range(n_iter):
        vals = _sample(space, rng)
        key = tuple(sorted(vals.items()))
        if key in seen:
            continue
        seen.add(key)
        m = evaluate(prep, vals, base_s, base_e)
        sc = score(m, targets)
        out.append(Candidate(vals, m, sc))
        if progress and (i % 25 == 0):
            best = max((c.score for c in out if np.isfinite(c.score)), default=float("-inf"))
            progress(i, n_iter, best)
    out.sort(key=lambda c: (c.score if np.isfinite(c.score) else -1e18), reverse=True)
    return out


def refine(
    prep: bt.Prepared,
    seed_values: Dict,
    space: Space,
    base_s: StrategyParams,
    base_e: ExecConfig,
    targets: Targets,
    rounds: int = 2,
) -> List[Candidate]:
    """Coordinate descent around a seed: sweep one parameter at a time."""
    cur = dict(seed_values)
    best_m = evaluate(prep, cur, base_s, base_e)
    best = Candidate(dict(cur), best_m, score(best_m, targets))
    history = [best]
    for _ in range(rounds):
        improved = False
        for key, options in space.items():
            for val in options:
                if cur.get(key) == val:
                    continue
                trial = dict(cur)
                trial[key] = val
                m = evaluate(prep, trial, base_s, base_e)
                sc = score(m, targets)
                history.append(Candidate(dict(trial), m, sc))
                if sc > best.score:
                    best = Candidate(dict(trial), m, sc)
                    cur = trial
                    improved = True
        if not improved:
            break
    history.sort(key=lambda c: (c.score if np.isfinite(c.score) else -1e18), reverse=True)
    return history


def stability(
    prep: bt.Prepared,
    values: Dict,
    space: Space,
    base_s: StrategyParams,
    base_e: ExecConfig,
    targets: Targets,
) -> Dict[str, float]:
    """Re-score every immediate neighbour of ``values`` in the grid.

    A robust parameter set is surrounded by other workable ones.  The median
    neighbour score matters more than the peak.
    """
    scores = []
    for key, options in space.items():
        opts = list(options)
        if values.get(key) not in opts:
            continue
        i = opts.index(values[key])
        for j in (i - 1, i + 1):
            if 0 <= j < len(opts):
                trial = dict(values)
                trial[key] = opts[j]
                m = evaluate(prep, trial, base_s, base_e)
                scores.append(score(m, targets))
    scores = [s for s in scores if np.isfinite(s)]
    if not scores:
        return {"n": 0, "median": float("-inf"), "min": float("-inf"), "frac_positive": 0.0}
    arr = np.array(scores)
    return {
        "n": len(arr),
        "median": float(np.median(arr)),
        "min": float(arr.min()),
        "frac_positive": float((arr > 0).mean()),
    }


# ---------------------------------------------------------------------------
# robust selection
# ---------------------------------------------------------------------------
def robust_select(
    prep: bt.Prepared,
    candidates: List[Candidate],
    base_s: StrategyParams,
    base_e: ExecConfig,
    targets: Targets,
    top_k: int = 25,
    n_sub: int = 3,
) -> List[Candidate]:
    """Re-rank the best in-sample candidates by their WORST sub-period.

    Taking the single highest in-sample score is the standard way to lose money:
    with hundreds of draws, the winner is whichever configuration happened to
    catch the sample's luckiest stretch.  Splitting the training window into
    thirds and ranking by the weakest third demands that a configuration work
    in *every* part of the data it was fitted on, which is a far better
    predictor of surviving the data it was not.

    Candidates that cannot produce enough trades in every sub-period are
    dropped: a strategy that goes quiet for four months is not a scalper.
    """
    if not candidates:
        return []
    idx = prep.exec_bars.index
    span = idx[-1] - idx[0]
    edges = [idx[0] + span * i / n_sub for i in range(n_sub + 1)]
    subs = [
        prep.slice(str(edges[i].date()), str(edges[i + 1].date()))
        for i in range(n_sub)
    ]
    sub_targets = replace(targets, trade_scale=targets.trade_scale / n_sub)

    scored = []
    for c in candidates[:top_k]:
        subs_scores = [
            score(evaluate(sub, c.values, base_s, base_e), sub_targets) for sub in subs
        ]
        worst = min(subs_scores)
        mean = float(np.mean([x for x in subs_scores if np.isfinite(x)])) if any(
            np.isfinite(x) for x in subs_scores
        ) else -np.inf
        # worst sub-period decides; the mean only breaks ties
        rank = (worst if np.isfinite(worst) else -1e18, mean if np.isfinite(mean) else -1e18)
        scored.append((rank, c, subs_scores))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for rank, c, subs_scores in scored:
        c2 = Candidate(c.values, c.metrics, c.score)
        c2.robust_worst = rank[0]
        c2.robust_scores = subs_scores
        out.append(c2)
    return out


# ---------------------------------------------------------------------------
# walk-forward
# ---------------------------------------------------------------------------
@dataclass
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_values: Dict
    train_metrics: Metrics
    test_metrics: Metrics
    test_trades: pd.DataFrame


@dataclass
class WalkForward:
    folds: List[Fold]
    oos_trades: pd.DataFrame
    oos_metrics: Metrics
    efficiency: float          # OOS expectancy / IS expectancy

    def summary(self) -> str:
        lines = ["walk-forward folds:"]
        for i, f in enumerate(self.folds, 1):
            lines.append(
                f"  {i}: train {f.train_start:%Y-%m-%d}..{f.train_end:%Y-%m-%d} "
                f"IS {f.train_metrics.n_trades:4d}tr {f.train_metrics.expectancy_r:+.3f}R"
                f" -> test {f.test_start:%Y-%m-%d}..{f.test_end:%Y-%m-%d} "
                f"OOS {f.test_metrics.n_trades:4d}tr {f.test_metrics.expectancy_r:+.3f}R "
                f"PF {f.test_metrics.profit_factor:.2f} WR {f.test_metrics.win_rate*100:.1f}%"
            )
        lines.append(f"stitched OOS: {self.oos_metrics.summary()}")
        lines.append(f"walk-forward efficiency: {self.efficiency:.2f}")
        return "\n".join(lines)


def make_folds(
    index: pd.DatetimeIndex,
    n_folds: int,
    train_days: int,
    test_days: int,
    step_days: Optional[int] = None,
) -> List[Tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    """Rolling windows.

    The window advances by ``step_days``, which defaults to ``test_days`` so the
    test windows are **contiguous and non-overlapping**: every out-of-sample day
    is used exactly once and the stitched equity curve has no holes.  Spreading
    a fixed number of folds across the sample instead would leave most of the
    history untested and let the stitched curve skip the awkward stretches.

    ``n_folds`` is a cap, not a target: pass 0 to use every window that fits.
    """
    start, end = index[0].normalize(), index[-1].normalize()
    total = (end - start).days
    span = train_days + test_days
    if total < span:
        raise ValueError(f"need >= {span} days of data, have {total}")
    step = step_days if step_days and step_days > 0 else test_days

    folds = []
    k = 0
    while True:
        ts = start + pd.Timedelta(days=k * step)
        te = ts + pd.Timedelta(days=train_days)
        ve = te + pd.Timedelta(days=test_days)
        if ve > end + pd.Timedelta(days=1):
            break
        folds.append((ts, te, te, ve))
        k += 1
        if n_folds and len(folds) >= n_folds:
            break
    return folds


def walk_forward(
    prep: bt.Prepared,
    space: Space,
    base_s: StrategyParams,
    base_e: ExecConfig,
    targets: Targets,
    n_folds: int = 0,
    train_days: int = 365,
    test_days: int = 120,
    step_days: Optional[int] = None,
    n_iter: int = 250,
    seed: int = 0,
    refine_rounds: int = 1,
    workers: int = 4,
    robust_top_k: int = 25,
    verbose: bool = True,
) -> WalkForward:
    """Fit on each training window, measure on the untouched window after it."""
    windows = make_folds(prep.exec_bars.index, n_folds, train_days, test_days, step_days)
    folds: List[Fold] = []
    oos_frames: List[pd.DataFrame] = []

    for k, (ts, te, vs, ve) in enumerate(windows, 1):
        train = prep.slice(str(ts.date()), str(te.date()))
        test = prep.slice(str(vs.date()), str(ve.date()))
        if len(train.exec_bars) < 5000 or len(test.exec_bars) < 1000:
            continue

        tt = replace(targets, trade_scale=train_days / 365.0)
        cands = parallel_search(
            train, space, base_s, base_e, tt,
            n_iter=n_iter, seed=seed + k, workers=workers,
        )
        viable = [c for c in cands if np.isfinite(c.score)]
        if not viable:
            continue
        if refine_rounds:
            hist = refine(train, viable[0].values, space, base_s, base_e, tt, rounds=refine_rounds)
            viable = sorted(
                [c for c in hist + viable if np.isfinite(c.score)],
                key=lambda c: c.score, reverse=True,
            )
        # pick by sub-period robustness, not by the in-sample peak
        ranked = robust_select(train, viable, base_s, base_e, tt, top_k=robust_top_k)
        best = ranked[0] if ranked else viable[0]

        s_p, e_p = build(best.values, base_s, base_e)
        m_test, tr_test, _ = bt.run(test, s_p, e_p)
        folds.append(Fold(ts, te, vs, ve, best.values, best.metrics, m_test, tr_test))
        if len(tr_test):
            oos_frames.append(tr_test)
        if verbose:
            print(
                f"  fold {k}: IS {best.metrics.n_trades:4d}tr {best.metrics.expectancy_r:+.3f}R"
                f" | OOS {m_test.n_trades:4d}tr {m_test.expectancy_r:+.3f}R"
                f" PF {m_test.profit_factor:.2f} WR {m_test.win_rate*100:.1f}%",
                flush=True,
            )

    oos = pd.concat(oos_frames).sort_values("entry_time") if oos_frames else pd.DataFrame()
    oos_metrics = _stitch_metrics(oos, base_e.initial_equity, base_e.risk_pct)
    is_exp = np.mean([f.train_metrics.expectancy_r for f in folds]) if folds else 0.0
    oos_exp = oos_metrics.expectancy_r
    eff = float(oos_exp / is_exp) if is_exp > 1e-9 else 0.0
    return WalkForward(folds=folds, oos_trades=oos, oos_metrics=oos_metrics, efficiency=eff)


def _stitch_metrics(
    trades: pd.DataFrame, initial_equity: float, risk_pct: float = 0.005
) -> Metrics:
    """Metrics over concatenated out-of-sample folds, compounding R sequentially.

    Each fold's trades were produced by a different parameter set, so the fold
    equity curves cannot simply be glued together.  Instead the R sequence is
    replayed at the configured fractional risk, which is what a trader following
    the walk-forward procedure would actually have experienced.
    """
    from . import metrics as M

    if len(trades) == 0:
        return Metrics()
    t = trades.sort_values("entry_time").reset_index(drop=True)
    idx = pd.DatetimeIndex(t["exit_time"])
    eq = initial_equity * np.cumprod(1.0 + risk_pct * t["r"].to_numpy())
    m = M.compute(t, eq, idx, initial_equity)
    return m


# ---------------------------------------------------------------------------
# parallel search
# ---------------------------------------------------------------------------
_WORKER: Dict[str, object] = {}


def _worker_init(prep, base_s, base_e, targets):
    _WORKER["prep"] = prep
    _WORKER["s"] = base_s
    _WORKER["e"] = base_e
    _WORKER["t"] = targets


def _worker_eval(values):
    m = evaluate(_WORKER["prep"], values, _WORKER["s"], _WORKER["e"])
    return values, m, score(m, _WORKER["t"])


def parallel_search(
    prep: bt.Prepared,
    space: Space,
    base_s: StrategyParams,
    base_e: ExecConfig,
    targets: Targets,
    n_iter: int = 600,
    seed: int = 0,
    workers: int = 4,
    verbose: bool = False,
) -> List[Candidate]:
    """Random search spread over processes.

    Candidates are sorted by their *signal shape* before dispatch so each worker
    receives a contiguous run of parameter sets that share an indicator pass and
    can reuse its direction cache.
    """
    import multiprocessing as mp

    rng = random.Random(seed)
    seen: set = set()
    batch: List[Dict] = []
    for _ in range(n_iter * 3):
        if len(batch) >= n_iter:
            break
        vals = _sample(space, rng)
        key = tuple(sorted(vals.items()))
        if key in seen:
            continue
        seen.add(key)
        batch.append(vals)

    # group by signal shape to make the per-worker direction cache pay off
    def shape(v):
        s_p, _ = build(v, base_s, base_e)
        return bt.direction_key(s_p)

    batch.sort(key=shape)

    if workers <= 1:
        out = []
        for v in batch:
            m = evaluate(prep, v, base_s, base_e)
            out.append(Candidate(v, m, score(m, targets)))
    else:
        ctx = mp.get_context("fork")
        chunk = max(1, len(batch) // (workers * 4))
        with ctx.Pool(
            processes=workers, initializer=_worker_init,
            initargs=(prep, base_s, base_e, targets),
        ) as pool:
            out = [
                Candidate(v, m, sc)
                for v, m, sc in pool.imap(_worker_eval, batch, chunksize=chunk)
            ]

    out.sort(key=lambda c: (c.score if np.isfinite(c.score) else -1e18), reverse=True)
    if verbose and out:
        print(f"    searched {len(out)} configs, best score {out[0].score:.2f}", flush=True)
    return out
