"""Walk-forward optimisation (backtest -> forward test -> re-optimise loop).

    python -m scalper.wfo --version v2 --trials 300

Folds: optimise on a rolling TRAIN window with Optuna (TPE), then trade the
following TEST window out-of-sample with the chosen parameters, carrying the
account equity from fold to fold.  The final HOLDOUT window (from 2026-08-01)
is never touched during development and is only run with --holdout.
"""
from __future__ import annotations
import argparse, json, os, time
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import pandas as pd
import optuna

from .backtest import (Market, COSTS, run_period, run_ensemble, metrics, robust_score, signals)
from .data import load_1m
from . import spaces

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")

FOLD_SETS = {
    # 6-month train / 3-month test
    "short": [("2024-11-15", "2025-05-01", "2025-08-01"),
              ("2025-02-01", "2025-08-01", "2025-11-01"),
              ("2025-05-01", "2025-11-01", "2026-02-01"),
              ("2025-08-01", "2026-02-01", "2026-05-01"),
              ("2025-11-01", "2026-05-01", "2026-08-01")],
    # 9-month train / 3-month test
    "long": [("2024-11-01", "2025-08-01", "2025-11-01"),
             ("2025-02-01", "2025-11-01", "2026-02-01"),
             ("2025-05-01", "2026-02-01", "2026-05-01"),
             ("2025-08-01", "2026-05-01", "2026-08-01")],
}
FOLD_SETS["expanding"] = [("2024-11-01", te0, te1) for _, te0, te1 in FOLD_SETS["long"]]
HOLDOUT = {"expanding": ("2024-11-01", "2026-08-01", "2026-11-19"),
           "short": ("2026-02-01", "2026-08-01", "2026-11-19"),
           "long": ("2025-11-01", "2026-08-01", "2026-11-19")}

_M = None


def _market():
    global _M
    if _M is None:
        _M = Market(load_1m())
    return _M


PERTURB = ["atr_n", "imp_thr", "z_n", "z_in", "htf_n", "sl_k", "tp_k", "max_hold",
           "mem_alpha", "er_thr", "don_n", "er_n"]


def optimise(version, train_start, train_end, trials, seed=7, top_k=1):
    m = _market()
    eq0 = COSTS["equity0"]
    t0, t1 = pd.Timestamp(train_start, tz="UTC"), pd.Timestamp(train_end, tz="UTC")
    mid = t0 + (t1 - t0) / 2
    day_split = (mid.normalize() - t0.normalize()).days
    minute_split = m.i_of(mid) - m.i_of(t0)
    space = spaces.get(version)
    sig_cache = {}

    def objective(trial):
        p = space(trial)
        key = tuple(sorted((k, p[k]) for k in p if k in spaces.SIG_KEYS_ALL))
        if key not in sig_cache:
            if len(sig_cache) > 64:
                sig_cache.clear()
            sig_cache[key] = signals(m, p)
        tr, deq, _, _ = run_period(m, p, train_start, train_end, sigs=sig_cache[key])
        s = robust_score(tr, deq, eq0, 0, day_split, minute_split)
        trial.set_user_attr("params", p)
        return s

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(direction="maximize",
                                sampler=optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(60, trials // 3),
                                                                   multivariate=True))
    study.optimize(objective, n_trials=trials)
    # plateau selection: re-score the top trials under +-15% parameter perturbations
    # and keep the one whose neighbourhood is best (avoids knife-edge optima)
    seen, top = set(), []
    for t in sorted([t for t in study.trials if t.value is not None], key=lambda t: -t.value):
        key = tuple(sorted(t.params.items()))
        if key not in seen:
            seen.add(key)
            top.append(t)
        if len(top) >= max(12, 3 * top_k):
            break
    rng = np.random.default_rng(seed)
    ranked = []
    for t in top:
        p0 = t.user_attrs["params"]
        vals = [t.value]
        for _ in range(6):
            p = dict(p0)
            for k in PERTURB:
                if k in p:
                    v = p[k] * rng.uniform(0.85, 1.15)
                    p[k] = int(round(v)) if isinstance(p0[k], int) else v
            tr, deq, _, _ = run_period(m, p, train_start, train_end)
            vals.append(robust_score(tr, deq, eq0, 0, day_split, minute_split))
        ranked.append((0.5 * t.value + 0.5 * float(np.mean(vals[1:])), p0))
    ranked.sort(key=lambda x: -x[0])
    if top_k == 1:
        return ranked[0][1], ranked[0][0]
    good = [r for r in ranked if r[0] > 0][:top_k] or ranked[:1]
    return [p for _, p in good], float(np.mean([s for s, _ in good]))


def _fold_job(args):
    version, fold, trials, seed, top_k = args
    tr0, tr1, te1 = fold
    t = time.time()
    p, s = optimise(version, tr0, tr1, trials, seed, top_k)
    return fold, p, s, time.time() - t


def run_wfo(version, trials, holdout=False, workers=4, seed=7, folds="short", top_k=1):
    m = _market()
    folds = [HOLDOUT[folds]] if holdout else FOLD_SETS[folds]
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_fold_job, [(version, f, trials, seed, top_k) for f in folds]))
    eq = COSTS["equity0"]
    all_tr, all_deq, rows = [], [], []
    for fold, p, s, dt in res:
        tr0, tr1, te1 = fold
        if top_k == 1:
            tr, deq, mem, i0 = run_period(m, p, tr1, te1, cost={"equity0": eq})
            tr_in, deq_in, _, _ = run_period(m, p, tr0, tr1)
        else:
            tr, deq, i0 = run_ensemble(m, p, tr1, te1, equity0=eq)
            tr_in, deq_in, _ = run_ensemble(m, p, tr0, tr1)
        mt_test = metrics(tr, deq, eq)
        mt_train = metrics(tr_in, deq_in, COSTS["equity0"])
        rows.append({"train_window": f"{tr0}..{tr1}", "test_window": f"{tr1}..{te1}", "train_score": s,
                     "train": mt_train, "test": mt_test, "params": p, "opt_sec": dt})
        tr = tr.copy()
        tr[:, 0] += i0
        tr[:, 1] += i0
        all_tr.append(tr)
        all_deq.append(deq)
        eq = deq[-1]
    tr = np.vstack(all_tr) if all_tr else np.zeros((0, 11))
    deq = np.concatenate(all_deq)
    oos = metrics(tr, deq, COSTS["equity0"])
    from .backtest import score
    oos["score"] = score(oos)
    return oos, rows, tr, deq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v2")
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--holdout", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--folds", default="short", choices=list(FOLD_SETS))
    ap.add_argument("--top_k", type=int, default=1, help=">1 = trade an ensemble of the top-k plateau-robust sets")
    a = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    t = time.time()
    oos, rows, tr, deq = run_wfo(a.version, a.trials, a.holdout, a.workers, a.seed, a.folds, a.top_k)
    tag = f"{a.version}_k{a.top_k}_{a.folds}_{'holdout' if a.holdout else 'wfo'}_s{a.seed}"
    out = {"version": a.version, "folds_set": a.folds, "trials": a.trials, "seed": a.seed, "oos": oos, "folds": rows}
    with open(os.path.join(RESULTS, tag + ".json"), "w") as f:
        json.dump(out, f, indent=1, default=float)
    np.save(os.path.join(RESULTS, tag + "_trades.npy"), tr)
    np.save(os.path.join(RESULTS, tag + "_equity.npy"), deq)
    print(f"== {tag}  ({time.time() - t:.0f}s)")
    for r in rows:
        te, trn = r["test"], r["train"]
        print(f"  test {r['test_window']}"
              f" tf={(r['params'] if isinstance(r['params'], dict) else r['params'][0])['tf']:>2} | train PF {trn['pf']:.2f} SR {trn['sharpe']:.2f} n={trn['trades']}"
              f" | TEST PF {te['pf']:.2f} SR {te['sharpe']:.2f} ret {te['ret_pct']:+.1f}% DD {te['max_dd_pct']:.1f}% n={te['trades']}")
    print("  OOS:", {k: round(v, 3) if isinstance(v, float) else v for k, v in oos.items()})


if __name__ == "__main__":
    main()
