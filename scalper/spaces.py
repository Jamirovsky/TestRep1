"""Search spaces for each strategy version tried in the optimisation loop."""
from __future__ import annotations
from .backtest import DEFAULTS, SIG_KEYS, suggest as full_space

SIG_KEYS_ALL = set(SIG_KEYS) | {"tf"}


def v3(trial):
    """AMS: all six families always on, memory chooses which one trades."""
    return full_space(trial)


def v4(trial):
    """AMS with the optimiser also allowed to switch families off (bitmask)."""
    p = full_space(trial)
    p["fam_mask"] = trial.suggest_int("fam_mask", 1, 63)
    return p


def v5(trial):
    """Focused AMS: impulse-continuation core (+ optional trend pullback), memory gating
    by direction x regime, volatility-scaled exits.  Sizing is margin-capped on a
    150 EUR account so risk is fixed at 2%."""
    p = dict(DEFAULTS)
    p["tf"] = trial.suggest_categorical("tf", [10, 15, 20, 30])
    p["atr_n"] = trial.suggest_int("atr_n", 10, 40)
    p["imp_n"] = trial.suggest_int("imp_n", 1, 6)
    p["imp_thr"] = trial.suggest_float("imp_thr", 1.8, 3.5)
    p["fam_mask"] = trial.suggest_categorical("fam_mask", [1, 33])
    p["z_n"] = trial.suggest_int("z_n", 10, 60)
    p["z_in"] = trial.suggest_float("z_in", 1.0, 4.0)
    p["er_thr"] = trial.suggest_float("er_thr", 0.2, 0.5)
    p["htf_n"] = trial.suggest_int("htf_n", 30, 300)
    p["bucket"] = trial.suggest_categorical("bucket", [0, 1, 2])
    p["vol_n"] = 300
    p["sl_k"] = trial.suggest_float("sl_k", 1.5, 4.0)
    p["tp_k"] = trial.suggest_float("tp_k", 2.0, 8.0)
    p["max_hold"] = trial.suggest_int("max_hold", 8, 64)
    p["be_trig"] = trial.suggest_categorical("be_trig", [0.0, 1.0, 1.5, 2.0])
    p["trail_k"] = trial.suggest_categorical("trail_k", [0.0, 1.5, 2.5])
    p["risk"] = 0.02
    p["mem_alpha"] = trial.suggest_float("mem_alpha", 0.05, 0.3)
    p["mem_thr"] = trial.suggest_float("mem_thr", -0.15, 0.1)
    p["mem_warm"] = trial.suggest_int("mem_warm", 2, 8)
    p["mem_k"] = trial.suggest_float("mem_k", 0.0, 1.0)
    p["min_stop_spread"] = 2.0
    p["dd_cut"] = trial.suggest_float("dd_cut", 0.05, 0.25)
    return p


def v5_nomem(trial):
    """Ablation: v5 without memory (every signal is traded)."""
    p = v5(trial)
    p["mem_warm"], p["mem_thr"], p["mem_k"] = 0, -1e9, 0.0
    return p


MEM_FIXED = dict(mem_warm=3, mem_thr=-0.05, mem_alpha=0.1, mem_k=0.0, bucket=0)


def v6(trial):
    """Small space (6 free params): impulse continuation only, fixed memory settings."""
    p = dict(DEFAULTS)
    p.update(MEM_FIXED)
    p["fam_mask"] = 1
    p["tf"] = trial.suggest_categorical("tf", [10, 15, 20, 30])
    p["imp_n"] = trial.suggest_int("imp_n", 1, 4)
    p["imp_thr"] = trial.suggest_float("imp_thr", 2.0, 3.2, step=0.1)
    p["sl_k"] = trial.suggest_float("sl_k", 1.5, 3.5, step=0.25)
    p["tp_k"] = trial.suggest_float("tp_k", 2.0, 8.0, step=0.5)
    p["max_hold"] = trial.suggest_int("max_hold", 12, 64, step=4)
    p.update(atr_n=14, be_trig=0.0, trail_k=0.0, risk=0.02, min_stop_spread=2.0, dd_cut=1.0)
    return p


def v6_nomem(trial):
    p = v6(trial)
    p["mem_warm"], p["mem_thr"] = 0, -1e9
    return p


def _v6_mem(**mem):
    def f(trial):
        p = v6(trial)
        p.update(mem)
        return p
    return f


# memory variants explored in the loop
V6_MEM_VARIANTS = {
    "v6_slowmem": dict(mem_warm=5, mem_thr=0.0, mem_alpha=0.03, bucket=0),
    "v6_vetomem": dict(mem_warm=5, mem_thr=-0.3, mem_alpha=0.1, bucket=0),
    "v6_volmem": dict(mem_warm=5, mem_thr=-0.1, mem_alpha=0.05, bucket=1),
    "v6_sessmem": dict(mem_warm=5, mem_thr=-0.1, mem_alpha=0.05, bucket=2),
}


def v7(trial):
    """Impulse continuation + multi-day momentum filter (market memory) + optional
    learned memory keyed on momentum state.  8 free parameters."""
    p = dict(DEFAULTS)
    p["fam_mask"] = 1
    p["tf"] = trial.suggest_categorical("tf", [10, 15, 20, 30])
    p["imp_n"] = trial.suggest_int("imp_n", 1, 5)
    p["imp_thr"] = trial.suggest_float("imp_thr", 1.8, 3.2, step=0.1)
    p["sl_k"] = trial.suggest_float("sl_k", 1.5, 3.5, step=0.25)
    p["tp_k"] = trial.suggest_float("tp_k", 2.0, 8.0, step=0.5)
    p["max_hold"] = trial.suggest_int("max_hold", 12, 64, step=4)
    mom_days = trial.suggest_categorical("mom_days", [0, 4, 5, 6, 7, 8, 10])
    p["trend_filter"] = 1 if mom_days > 0 else 0
    p["mom_n"] = max(1, (mom_days or 7) * 1440 // p["tf"])
    use_mem = trial.suggest_categorical("use_mem", [0, 1])
    if use_mem:
        p.update(bucket=3, mem_warm=5, mem_thr=0.0, mem_alpha=0.1, mem_k=0.0)
    else:
        p.update(bucket=0, mem_warm=0, mem_thr=-1e9, mem_k=0.0)
    p.update(atr_n=14, be_trig=0.0, trail_k=0.0, risk=0.02, min_stop_spread=2.0, dd_cut=1.0)
    return p


VERSIONS = {"v3": v3, "v4": v4, "v5": v5, "v5_nomem": v5_nomem, "v6": v6, "v6_nomem": v6_nomem, "v7": v7,
            **{k: _v6_mem(**v) for k, v in V6_MEM_VARIANTS.items()}}


def get(name):
    return VERSIONS[name]
