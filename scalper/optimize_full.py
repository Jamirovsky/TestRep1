"""Final-stage optimisation on the whole development period with a quarterly
consistency objective and plateau (neighbourhood) selection.

    python -m scalper.optimize_full --version v7 --trials 600 --seeds 1 2 3

Development period: 2024-11-15 .. 2026-08-01.  The holdout (2026-08-01 .. end)
is NOT used here; run `python -m scalper.holdout` afterwards.
"""
from __future__ import annotations
import argparse, json, os
from concurrent.futures import ProcessPoolExecutor
import numpy as np
import optuna

from .backtest import Market, COSTS, run_period, metrics, score, signals
from .data import load_1m
from . import spaces

DEV = ("2024-11-15", "2026-08-01")
QUARTERS = [("2024-11-15", "2025-02-01"), ("2025-02-01", "2025-05-01"), ("2025-05-01", "2025-08-01"),
            ("2025-08-01", "2025-11-01"), ("2025-11-01", "2026-02-01"), ("2026-02-01", "2026-05-01"),
            ("2026-05-01", "2026-08-01")]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TF_NEIGH = {10: [15], 15: [10, 20], 20: [15, 30], 30: [20]}

_M = None


def _market():
    global _M
    if _M is None:
        _M = Market(load_1m())
    return _M


def consistency_eval(p, sigs=None):
    """Run the whole dev period once; score = balanced(PF,Sharpe) x share of
    profitable quarters, with a penalty for any quarter losing more than 8%."""
    m = _market()
    eq0 = COSTS["equity0"]
    tr, deq, _, i0 = run_period(m, p, *DEV, sigs=sigs)
    full = metrics(tr, deq, eq0)
    s = score(full)
    epoch_day = m.day[i0]
    qret = []
    for a, b in QUARTERS:
        da = m.day[m.i_of(a)] - epoch_day
        db = m.day[min(m.i_of(b), len(m.day) - 1)] - epoch_day
        start = eq0 if da == 0 else deq[da - 1]
        qret.append(deq[db - 1] / start - 1)
    qret = np.array(qret)
    pos = (qret > 0).mean()
    obj = s * pos if s > 0 else s
    if qret.min() < -0.08:
        obj -= 0.5 * (-0.08 - qret.min()) * 10
    return obj, full, qret


def _neighbours(p0, rng, n=8):
    out = []
    for _ in range(n):
        p = dict(p0)
        for k in ["imp_thr", "sl_k", "tp_k", "max_hold"]:
            v = p[k] * rng.uniform(0.85, 1.15)
            p[k] = int(round(v)) if isinstance(p0[k], int) else v
        if rng.random() < 0.35:
            p["imp_n"] = int(max(1, p["imp_n"] + rng.choice([-1, 1])))
        if rng.random() < 0.35:
            days = p["mom_n"] * p["tf"] / 1440
            p["tf"] = int(rng.choice(TF_NEIGH[p["tf"]]))
            p["mom_n"] = max(1, int(round(days * 1440 / p["tf"])))
            p["max_hold"] = max(4, int(round(p0["max_hold"] * p0["tf"] / p["tf"])))
        out.append(p)
    return out


def run_seed(args):
    version, trials, seed = args
    space = spaces.get(version)

    def objective(trial):
        p = space(trial)
        obj, full, q = consistency_eval(p)
        trial.set_user_attr("params", p)
        return obj

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    st = optuna.create_study(direction="maximize", sampler=optuna.samplers.TPESampler(
        seed=seed, n_startup_trials=trials // 4, multivariate=True))
    st.optimize(objective, n_trials=trials)
    seen, top = set(), []
    for t in sorted([t for t in st.trials if t.value is not None], key=lambda t: -t.value):
        key = tuple(sorted(t.params.items()))
        if key not in seen:
            seen.add(key)
            top.append(t)
        if len(top) >= 15:
            break
    rng = np.random.default_rng(seed)
    ranked = []
    for t in top:
        p0 = t.user_attrs["params"]
        nb = [consistency_eval(p)[0] for p in _neighbours(p0, rng)]
        plateau = 0.4 * t.value + 0.6 * float(np.mean(nb))
        ranked.append({"plateau": plateau, "own": t.value, "neigh_mean": float(np.mean(nb)),
                       "neigh_min": float(np.min(nb)), "params": p0})
    ranked.sort(key=lambda r: -r["plateau"])
    return seed, ranked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v7")
    ap.add_argument("--trials", type=int, default=600)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4])
    a = ap.parse_args()
    with ProcessPoolExecutor(min(4, len(a.seeds))) as ex:
        res = list(ex.map(run_seed, [(a.version, a.trials, s) for s in a.seeds]))
    allr = sorted([r for _, rs in res for r in rs], key=lambda r: -r["plateau"])
    os.makedirs(os.path.join(ROOT, "results"), exist_ok=True)
    out = os.path.join(ROOT, "results", f"full_{a.version}.json")
    with open(out, "w") as f:
        json.dump({"version": a.version, "trials": a.trials, "seeds": a.seeds, "ranked": allr},
                  f, indent=1, default=float)
    for r in allr[:10]:
        p = r["params"]
        _, full, q = consistency_eval(p)
        print(f"plateau {r['plateau']:.3f} own {r['own']:.3f} neigh {r['neigh_mean']:.3f}/{r['neigh_min']:.3f} | "
              f"tf{p['tf']} n{p['imp_n']} thr{p['imp_thr']:.1f} sl{p['sl_k']:.2f} tp{p['tp_k']:.1f} mh{p['max_hold']} "
              f"mom{p['trend_filter']}:{p['mom_n'] * p['tf'] / 1440:.0f}d mem{int(p['bucket'] == 3)} | "
              f"PF {full['pf']:.2f} SR {full['sharpe']:.2f} ret {full['ret_pct']:+.1f}% DD {full['max_dd_pct']:.1f}% "
              f"n={full['trades']} q+={int((q > 0).sum())}/{len(q)}")


if __name__ == "__main__":
    main()
