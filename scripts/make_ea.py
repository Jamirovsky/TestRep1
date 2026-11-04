#!/usr/bin/env python3
"""Turn an optimised config JSON into a ready-to-compile MT5 Expert Advisor.

    python3 scripts/make_ea.py config/XAGUSD_final.json --name ScalperXAG

Fills ``mql5/templates/ScalperMetal.mq5.tmpl`` with the deployed strategy and
execution parameters and writes ``mql5/<name>.mq5`` plus a Strategy Tester
``mql5/sets/<name>.set`` whose optimisation ranges bracket the defaults.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scalping.instruments import get_instrument
from scalping.strategy import SESSION_PRESETS

MODES = {"breakout": "MODE_BREAKOUT", "momentum": "MODE_MOMENTUM", "pullback": "MODE_PULLBACK",
         "fade": "MODE_FADE", "bands": "MODE_BANDS"}
MODE_IDX = {"breakout": 0, "momentum": 1, "pullback": 2, "fade": 3, "bands": 4}
TFS = {1: "PERIOD_M1", 2: "PERIOD_M2", 3: "PERIOD_M3", 5: "PERIOD_M5", 10: "PERIOD_M10",
       15: "PERIOD_M15", 20: "PERIOD_M20", 30: "PERIOD_M30"}
MAGIC = {"XAGUSD": 20261103, "XPTUSD": 20261104, "XPDUSD": 20261105, "XAUUSD": 20261106}


def fmt(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".") if v != int(v) else f"{v:.1f}"
    return str(v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("config")
    ap.add_argument("--name", required=True)
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    sym = cfg["symbol"].upper()
    s, e = cfg["strategy"], cfg["execution"]
    inst = get_instrument(sym)
    lo, hi = SESSION_PRESETS[s["session"]]
    max_spread_bp = inst.spread_max_points * inst.point / (inst.ref_price or 1.0) * 1e4
    v = cfg.get("validation", {})

    notes = cfg.get("notes", [])
    header = "\n".join(f"//|   {n}" for n in notes) or "//|   (see docs)"

    rep = {
        "EA_NAME": args.name, "SYMBOL": sym, "SYMBOL_ROOT": sym[:6],
        "MODE": MODES[s["mode"]], "TF": TFS[int(s["tf_minutes"])], "TF_NAME": f"M{int(s['tf_minutes'])}",
        "SESS_START": str(lo), "SESS_END": str(hi),
        "MAX_SPREAD_BP": f"{max_spread_bp:.1f}",
        "SLIPPAGE_POINTS": str(int(round(inst.slippage_points_stop * 2))),
        "MAGIC": str(MAGIC.get(sym, 20261100)), "HEADER_NOTES": header,
        "risk_pct": fmt(float(e["risk_pct"])),
    }
    for k in ("atr_period", "atr_rank_lookback", "atr_rank_min", "atr_rank_max", "er_period",
              "er_min", "er_max", "bb_period", "band_k", "rsi_period", "rsi_lo", "rsi_hi",
              "adx_period", "adx_max", "confirm_mode", "don_period", "ema_fast", "ema_slow",
              "adx_min", "expansion_mult", "atr_avg_period", "mom_period", "mom_min_atr",
              "mom_confirm", "pb_slope_period", "pb_rsi_lo", "pb_rsi_hi", "pb_depth_atr",
              "pb_lookback", "sl_atr", "min_sl_bp", "tp_r"):
        val = s[k]
        if k == "mom_confirm":
            val = bool(val)
        elif k in ("atr_period", "atr_rank_lookback", "er_period", "bb_period", "rsi_period",
                   "adx_period", "confirm_mode", "don_period", "ema_fast", "ema_slow",
                   "atr_avg_period", "mom_period", "pb_slope_period", "pb_lookback"):
            val = int(val)
        else:
            val = float(val)
        rep[k] = fmt(val)
    for k in ("be_trigger_r", "be_offset_r", "partial_r", "partial_frac", "trail_start_r",
              "trail_dist_r"):
        rep[k] = fmt(float(e[k]))
    for k in ("max_bars", "cooldown_bars", "max_trades_per_day", "force_exit_hour", "force_exit_min"):
        rep[k] = str(int(e[k]))

    src = (ROOT / "mql5" / "templates" / "ScalperMetal.mq5.tmpl").read_text()
    for k, val in rep.items():
        src = src.replace("{{" + k + "}}", val)
    if "{{" in src:
        raise SystemExit("unfilled placeholder: " + src[src.index("{{"):src.index("{{") + 40])
    out = ROOT / "mql5" / f"{args.name}.mq5"
    out.write_text(src)

    # Strategy Tester .set: name=value||start||step||stop||Y/N
    def rng(name, val, step, lo_, hi_, opt=True):
        return f"{name}={val}||{lo_}||{step}||{hi_}||{'Y' if opt else 'N'}"

    sl, tp, bp = float(s["sl_atr"]), float(s["tp_r"]), float(s["min_sl_bp"])
    lines = [
        f"; {args.name} - optimised defaults for {sym} (signal TF M{int(s['tf_minutes'])})",
        "; Y = suggested re-optimisation range on your broker's own history",
        f"InpMode={MODE_IDX[s['mode']]}",
        f"InpSessionStartUTC={lo}", f"InpSessionEndUTC={hi}", "InpGmtOffsetHours=-99",
        rng("InpSlAtr", fmt(sl), 0.5, max(0.5, sl - 1.0), sl + 1.0),
        rng("InpTpR", fmt(tp), 0.1, max(0.3, round(tp - 0.3, 2)), round(tp + 0.4, 2)),
        rng("InpMinSlBp", fmt(bp), round(bp * 0.25, 1), round(bp * 0.5, 1), round(bp * 1.5, 1)),
        rng("InpBandK", rep["band_k"], 0.25, max(0.5, float(s["band_k"]) - 0.5), float(s["band_k"]) + 0.5,
            s["mode"] in ("fade", "bands")),
        rng("InpBbPeriod", rep["bb_period"], 12, max(12, int(s["bb_period"]) - 24), int(s["bb_period"]) + 24,
            s["mode"] == "bands"),
        rng("InpRsiLo", rep["rsi_lo"], 4, max(10, float(s["rsi_lo"]) - 8), float(s["rsi_lo"]) + 8,
            s["mode"] in ("fade", "bands")),
        f"InpRsiHi={rep['rsi_hi']}",
        f"InpAdxMax={rep['adx_max']}",
        rng("InpErMin", rep["er_min"], 0.1, max(0.0, round(float(s["er_min"]) - 0.2, 2)),
            min(0.9, round(float(s["er_min"]) + 0.2, 2)), s["mode"] in ("momentum", "breakout")),
        rng("InpErMax", rep["er_max"], 0.1, max(0.2, round(float(s["er_max"]) - 0.3, 2)),
            min(1.0, round(float(s["er_max"]) + 0.2, 2)), s["mode"] in ("fade", "bands")),
        f"InpConfirmMode={rep['confirm_mode']}",
        rng("InpMomPeriod", rep["mom_period"], 6, max(6, int(s["mom_period"]) - 12),
            int(s["mom_period"]) + 24, s["mode"] == "momentum"),
        rng("InpMomMinAtr", rep["mom_min_atr"], 0.5, max(0.5, float(s["mom_min_atr"]) - 1.0),
            float(s["mom_min_atr"]) + 1.0, s["mode"] == "momentum"),
        f"InpMomConfirm={rep['mom_confirm']}", f"InpDonPeriod={rep['don_period']}",
        f"InpAdxMin={rep['adx_min']}", f"InpExpansionMult={rep['expansion_mult']}",
        f"InpRiskPct={rep['risk_pct']}",
        f"InpBeTriggerR={rep['be_trigger_r']}", f"InpBeOffsetR={rep['be_offset_r']}",
        f"InpPartialR={rep['partial_r']}", f"InpPartialFrac={rep['partial_frac']}",
        f"InpTrailStartR={rep['trail_start_r']}", f"InpTrailDistR={rep['trail_dist_r']}",
        rng("InpMaxHoldMinutes", rep["max_bars"], 60, max(60, int(e["max_bars"]) - 120), int(e["max_bars"]) + 120),
        f"InpCooldownMinutes={rep['cooldown_bars']}", f"InpMaxTradesPerDay={rep['max_trades_per_day']}",
        f"InpForceExitHour={rep['force_exit_hour']}", f"InpForceExitMin={rep['force_exit_min']}",
        f"InpMaxSpreadBp={rep['MAX_SPREAD_BP']}",
    ]
    setdir = ROOT / "mql5" / "sets"
    setdir.mkdir(parents=True, exist_ok=True)
    (setdir / f"{args.name}.set").write_text("\n".join(lines) + "\n")
    print(f"wrote {out.relative_to(ROOT)} and mql5/sets/{args.name}.set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
