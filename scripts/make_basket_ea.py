#!/usr/bin/env python3
"""Build the multi-symbol basket EA from optimize_basket.py's report.

    python3 scripts/make_basket_ea.py reports/basket_stocks.json --name ScalperStocks7
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from make_ea import MODES, MODE_IDX, TFS, fmt  # noqa: E402
from scalping.instruments import get_instrument  # noqa: E402
from scalping.strategy import session_hours  # noqa: E402

INT_KEYS = ("atr_period", "atr_rank_lookback", "er_period", "bb_period", "rsi_period",
            "adx_period", "confirm_mode", "don_period", "ema_fast", "ema_slow",
            "atr_avg_period", "mom_period", "pb_slope_period", "pb_lookback")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--name", required=True)
    ap.add_argument("--max-open", type=int, default=3)
    args = ap.parse_args()
    rep = json.loads(Path(args.report).read_text())
    fin = rep["final"]
    s, e = fin["strategy"], fin["execution"]
    syms = rep["symbols"]
    markets = [get_instrument(x).market for x in syms]
    us, eu = session_hours(s["session"], "US"), session_hours(s["session"], "EU")
    insts = [get_instrument(x) for x in syms]
    max_spread_bp = max(i.spread_max_points * i.point / i.ref_price * 1e4 for i in insts)
    if "walk_forward_oos" in fin:                      # basket_walkforward.py report
        o = fin["walk_forward_oos"]
        f = rep["folds"]
        notes = [
            f"{rep['basket']}: {', '.join(syms)}",
            f"{s['mode'].upper()} on M{int(s['tf_minutes'])}, session '{s['session']}' "
            f"(US {us[0]}-{us[1]} / EU {eu[0]}-{eu[1]} UTC)",
            f"walk-forward {f[0][1]}..{f[-1][2]} ({len(f)} monthly refits, stitched OOS):",
            f"  {o['n_trades']} trades WR {o['win_rate']*100:.1f}% PF {o['profit_factor']:.2f} "
            f"{o['expectancy_r']:+.3f}R t={o['t_stat']:.2f}",
            "defaults = parameters refitted on the most recent training window",
        ]
    else:
        hold = fin["results"]["holdout"]["pooled"]
        fv = fin["results"]["fit+validation"]["pooled"]
        w = rep["windows"]
        notes = [
            f"{rep['basket']}: {', '.join(syms)}",
            f"{s['mode'].upper()} on M{int(s['tf_minutes'])}, session '{s['session']}' "
            f"(US {us[0]}-{us[1]} / EU {eu[0]}-{eu[1]} UTC)",
            f"fit+validation {w['fit'][0]}..{w['validation'][1]}: {fv['n_trades']} trades "
            f"WR {fv['win_rate']*100:.1f}% PF {fv['profit_factor']:.2f} {fv['expectancy_r']:+.3f}R",
            f"HOLDOUT {w['holdout'][0]}..{w['holdout'][1]} (untouched): {hold['n_trades']} trades "
            f"WR {hold['win_rate']*100:.1f}% PF {hold['profit_factor']:.2f} {hold['expectancy_r']:+.3f}R "
            f"t={hold['t_stat']:.2f}",
        ]
    rep_vals = {
        "EA_NAME": args.name,
        "BASKET_DESC": f"{len(syms)} {'US stocks' if rep['basket'] == 'stocks' else 'cash indices'}",
        "FIRST_SYMBOL": syms[0], "SYMBOLS": ",".join(syms), "MARKETS": ",".join(markets),
        "MAX_OPEN": str(args.max_open), "MODE": MODES[s["mode"]], "TF": TFS[int(s["tf_minutes"])],
        "TF_NAME": f"M{int(s['tf_minutes'])}",
        "US_START": str(us[0]), "US_END": str(us[1]), "EU_START": str(eu[0]), "EU_END": str(eu[1]),
        "MAX_SPREAD_BP": f"{max_spread_bp:.1f}", "SLIPPAGE_POINTS": "20",
        "MAGIC": "20261110" if rep["basket"] == "stocks" else "20261111",
        "HEADER_NOTES": "\n".join(f"//|   {n}" for n in notes),
        "risk_pct": fmt(float(e["risk_pct"])),
    }
    for k in ("atr_period", "atr_rank_lookback", "atr_rank_min", "atr_rank_max", "er_period",
              "er_min", "er_max", "bb_period", "band_k", "rsi_period", "rsi_lo", "rsi_hi",
              "adx_period", "adx_max", "confirm_mode", "don_period", "ema_fast", "ema_slow",
              "adx_min", "expansion_mult", "atr_avg_period", "mom_period", "mom_min_atr",
              "mom_confirm", "pb_slope_period", "pb_rsi_lo", "pb_rsi_hi", "pb_depth_atr",
              "pb_lookback", "sl_atr", "min_sl_bp", "tp_r"):
        v = s[k]
        v = bool(v) if k == "mom_confirm" else int(v) if k in INT_KEYS else float(v)
        rep_vals[k] = fmt(v)
    for k in ("be_trigger_r", "be_offset_r", "partial_r", "partial_frac", "trail_start_r", "trail_dist_r"):
        rep_vals[k] = fmt(float(e[k]))
    for k in ("max_bars", "cooldown_bars", "max_trades_per_day", "force_exit_hour", "force_exit_min"):
        rep_vals[k] = str(int(e[k]))
    src = (ROOT / "mql5" / "templates" / "ScalperBasket.mq5.tmpl").read_text()
    for k, v in rep_vals.items():
        src = src.replace("{{" + k + "}}", v)
    if "{{" in src:
        raise SystemExit("unfilled: " + src[src.index("{{"):src.index("{{") + 30])
    (ROOT / "mql5" / f"{args.name}.mq5").write_text(src)

    def rng(name, val, step, lo, hi, opt=True):
        return f"{name}={val}||{lo}||{step}||{hi}||{'Y' if opt else 'N'}"

    sl, tp, bp = float(s["sl_atr"]), float(s["tp_r"]), float(s["min_sl_bp"])
    mode = s["mode"]
    lines = [
        f"; {args.name} - loop-optimised shared parameters for {', '.join(syms)}",
        "; Y = range for the MT5 genetic optimiser (Strategy Tester > Optimization)",
        f"InpSymbols={rep_vals['SYMBOLS']}", f"InpMarkets={rep_vals['MARKETS']}",
        "InpSymbolSuffix=", f"InpMaxOpenPositions={args.max_open}",
        f"InpMode={MODE_IDX[mode]}",
        f"InpUsStartUTC={us[0]}", f"InpUsEndUTC={us[1]}", f"InpEuStartUTC={eu[0]}", f"InpEuEndUTC={eu[1]}",
        "InpGmtOffsetHours=-99",
        rng("InpSlAtr", fmt(sl), 0.5, max(0.5, sl - 1.0), sl + 1.0),
        rng("InpTpR", fmt(tp), 0.2, max(0.4, round(tp - 0.4, 2)), round(tp + 0.6, 2)),
        rng("InpMinSlBp", fmt(bp), max(2.0, round(bp / 4, 1)), max(4.0, round(bp / 2, 1)), round(bp * 2, 1)),
        rng("InpMomMinAtr", rep_vals["mom_min_atr"], 0.5, max(0.5, float(s["mom_min_atr"]) - 1),
            float(s["mom_min_atr"]) + 1, mode == "momentum"),
        rng("InpMomPeriod", rep_vals["mom_period"], 6, max(6, int(s["mom_period"]) - 12),
            int(s["mom_period"]) + 24, mode == "momentum"),
        rng("InpErMin", rep_vals["er_min"], 0.1, max(0.0, round(float(s["er_min"]) - 0.2, 2)),
            min(0.9, round(float(s["er_min"]) + 0.2, 2)), mode in ("momentum", "breakout")),
        rng("InpDonPeriod", rep_vals["don_period"], 12, max(12, int(s["don_period"]) - 12),
            int(s["don_period"]) + 36, mode == "breakout"),
        rng("InpBandK", rep_vals["band_k"], 0.25, max(0.5, float(s["band_k"]) - 0.5),
            float(s["band_k"]) + 0.5, mode in ("fade", "bands")),
        rng("InpBbPeriod", rep_vals["bb_period"], 12, max(12, int(s["bb_period"]) - 24),
            int(s["bb_period"]) + 48, mode == "bands"),
        rng("InpMaxHoldMinutes", rep_vals["max_bars"], 30, max(30, int(e["max_bars"]) - 60),
            int(e["max_bars"]) + 120),
        *[f"{n}={rep_vals[k]}" for n, k in (
            ("InpErMax", "er_max"), ("InpRsiLo", "rsi_lo"), ("InpRsiHi", "rsi_hi"),
            ("InpAdxMax", "adx_max"), ("InpConfirmMode", "confirm_mode"), ("InpAdxMin", "adx_min"),
            ("InpExpansionMult", "expansion_mult"), ("InpMomConfirm", "mom_confirm"),
            ("InpRiskPct", "risk_pct"), ("InpBeTriggerR", "be_trigger_r"),
            ("InpBeOffsetR", "be_offset_r"), ("InpPartialR", "partial_r"),
            ("InpPartialFrac", "partial_frac"), ("InpTrailStartR", "trail_start_r"),
            ("InpTrailDistR", "trail_dist_r"), ("InpCooldownMinutes", "cooldown_bars"),
            ("InpMaxTradesPerDay", "max_trades_per_day"), ("InpForceExitHour", "force_exit_hour"),
            ("InpForceExitMin", "force_exit_min"), ("InpMaxSpreadBp", "MAX_SPREAD_BP"))],
    ]
    (ROOT / "mql5" / "sets").mkdir(exist_ok=True)
    (ROOT / "mql5" / "sets" / f"{args.name}.set").write_text("\n".join(lines) + "\n")
    print(f"wrote mql5/{args.name}.mq5 and mql5/sets/{args.name}.set")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
