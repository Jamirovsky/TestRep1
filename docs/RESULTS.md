# Results

**Targets requested:** at least 100 trades, profit factor ≥ 1.2, win rate ≥ 50%.

**Verdict on the data available here:** the trade count and the win rate are
reachable on XAUUSD; **the profit factor is not**. EURUSD fails on every measure
and loses money with high confidence. Details and evidence below.

> Every number on this page was produced on the **calibrated synthetic price
> process** in `src/scalping/synth.py`, because the machine this was built on
> could not reach any market-data vendor (see `data/README.md`). They validate
> the machinery and the method; they are not a claim about live XAUUSD or
> EURUSD. Drop real bars into `data/raw/` and every command below re-runs
> against them unchanged.

---

## 1. The structural finding (this part is data-independent)

`scripts/diagnose.py` answers the two questions that decide whether scalping is
possible before any strategy is written.

**Round-trip friction against instrument volatility:**

| | EURUSD | XAUUSD |
|---|---|---|
| Friction (spread + commission + slippage) | 1.55 pips | USD 0.45 |
| Median ATR(M5) | 2.3 pips | USD 1.19 |
| **friction / ATR(M5)** | **0.68** | **0.38** |

**What that costs you, by stop size:**

| Stop | EURUSD friction | breakeven WR at 1:1 | | Stop | XAUUSD friction | breakeven WR at 1:1 |
|---|---|---|---|---|---|---|
| 1×ATR (2.3 pips) | 67.9% of R | 84.0% | | 1×ATR (USD 1.19) | 37.8% of R | 68.9% |
| 2×ATR (4.6 pips) | 34.0% of R | 67.0% | | 2×ATR (USD 2.38) | 18.9% of R | 59.4% |
| 3×ATR (6.8 pips) | 22.6% of R | 61.3% | | 3×ATR (USD 3.57) | 12.6% of R | 56.3% |
| 5×ATR (11.4 pips) | 13.6% of R | 56.8% | | 5×ATR (USD 5.96) | 7.6% of R | 53.8% |
| 8×ATR (18.3 pips) | 8.5% of R | 54.2% | | 8×ATR (USD 9.53) | 4.7% of R | 52.4% |

A 5-pip stop on EURUSD needs a **67% strike rate at a 1:1 target just to break
even**. Micro-scalping is not difficult on these instruments, it is
arithmetically closed.

**Is there anything to trade at scalping horizons?** Variance ratio, where 1.0
is a random walk and |z| < 2 means the deviation is indistinguishable from noise
(the estimator is validated against a simulated random walk in
`research.variance_ratio`):

| Horizon | EURUSD VR | z | XAUUSD VR | z |
|---|---|---|---|---|
| 10 min | 1.001 | 0.67 | 0.996 | −1.81 |
| 20 min | 1.004 | 1.00 | 1.003 | 0.69 |
| **60 min** | 1.016 | **2.35** | 1.038 | **5.24** |
| 120 min | 1.042 | 4.30 | 1.053 | 5.19 |
| 240 min | 1.065 | 4.80 | 1.102 | 7.23 |
| 480 min | 1.080 | 4.33 | 1.144 | 7.56 |

**At 10–20 minutes — actual scalping horizons — both instruments are
statistically indistinguishable from a random walk.** Exploitable structure only
appears from about an hour, and gold has roughly twice EURUSD's. That single
table explains every result that follows: the strategies are trying to pay a
0.38–0.68 ATR toll out of an edge that does not exist until you hold for an
hour, and is thin even then.

---

## 2. Out-of-sample results

Two independent tests. **Walk-forward**: fit on 730 days, trade the next 120,
advance by 120 so test windows are contiguous, 15 folds, 400 configurations
searched per fold. **Fit-once holdout**: fit a single parameter set on
2019–2021, then trade 2021–2025 with it frozen — no re-selection at all, the
strictest test available.

| Symbol / setup | Test | Trades | Win rate | Profit factor | Expectancy | t-stat |
|---|---|---|---|---|---|---|
| **XAUUSD momentum** (unconstrained) | walk-forward | 1256 | 49.6% | 1.05 | +0.016R | 0.66 |
| **XAUUSD momentum** (unconstrained) | **fit-once holdout** | **1195** | **50.8%** | **1.10** | **+0.042R** | 1.47 |
| XAUUSD momentum (win-rate gated ≥53%) | walk-forward | 1262 | 52.5% | 0.96 | −0.016R | −0.70 |
| XAUUSD momentum (win-rate gated ≥53%) | fit-once holdout | 1226 | 52.7% | 0.96 | −0.015R | −0.58 |
| XAUUSD momentum (PF+WR gated) | walk-forward | 238 | 49.2% | 1.09 | +0.029R | 0.53 |
| XAUUSD momentum (PF+WR gated) | fit-once holdout | 958 | 45.0% | 0.94 | −0.030R | −0.82 |
| XAUUSD momentum (hold ≤ 300 min) | walk-forward | 296 | 48.6% | 1.02 | +0.006R | 0.12 |
| XAUUSD momentum (hold ≤ 300 min) | fit-once holdout | 1497 | 48.4% | 1.02 | +0.006R | 0.27 |
| EURUSD breakout | walk-forward | 1181 | 47.2% | 0.88 | −0.032R | −1.76 |
| EURUSD breakout | **fit-once holdout** | 2294 | 48.2% | **0.86** | −0.030R | **−3.01** |

### Against the targets

| Target | XAUUSD best (fit-once holdout) | EURUSD best |
|---|---|---|
| Trades ≥ 100 | **1195 — PASS** | 2294 — PASS |
| Win rate ≥ 50% | **50.8% — PASS** | 48.2% — FAIL |
| Profit factor ≥ 1.2 | 1.10 — **FAIL** | 0.86 — FAIL |

### The trade-off that blocks the profit factor

The win rate and the profit factor pull against each other, and the edge is not
large enough to satisfy both:

- Optimise expectancy freely → **WR 49.6%, PF 1.05**
- Force the win rate to ≥53% → **WR 52.5% achieved, PF falls to 0.96**

Forcing more winners means taking them sooner, which cuts the payoff ratio from
1.06 to 0.86 and destroys more profit factor than the extra winners create.
The in-sample ceiling, measured directly over 900 configurations on a two-year
window (`scripts/explore.py` and the frontier scan), is **PF 1.28 at WR 54.0%**
— and in-sample numbers decay by roughly two-thirds out of sample here
(walk-forward efficiency 0.06–0.36 across runs). PF ≥ 1.2 out of sample would
need an in-sample PF around 1.6, which no configuration in the space reaches.

### EURUSD is not a near miss

The fit-once holdout gives t = **−3.01** on 2294 trades: EURUSD scalping loses
to costs reliably, not by chance. All four strategy families were tried
(breakout, momentum, pullback, VWAP fade); none produced a positive
out-of-sample expectancy. This follows directly from section 1 — friction is
0.68 ATR(M5) and there is no significant structure below an hour.

---

## 3. What was ruled out along the way

Recording these so the same ground is not covered twice:

| Tried | Result |
|---|---|
| Tight scalping stops (1–2 × ATR) | Friction 34–68% of R on EURUSD. Dead on arrival. |
| VWAP fade (mean reversion) | Forward returns **negative** at every horizon on both symbols — the stretch is a continuation signal here, not a reversion one. |
| Pullback continuation | Never produced enough trades to clear the search's trade floor. |
| Longer holds (≤300 min) | Out-of-sample PF 1.02. The extra edge at longer horizons is offset by fewer trades and wider stops. |
| Partial take-profit + breakeven | Raises win rate as intended, lowers payoff by more. Net negative for profit factor. |
| Hard in-sample gates PF ≥ 1.35 | No configuration in any of 15 folds cleared it — the in-sample ceiling is 1.28. |
| Peak-picking the best in-sample config | IS PF 1.35 → OOS PF 0.66. Replaced with worst-sub-period selection. |

---

## 4. Honest conclusion

On this data, with conservative retail costs:

1. **Micro-scalping (seconds to a few minutes) is not viable on either
   instrument**, and this is arithmetic rather than opinion — there is no
   statistically detectable structure below an hour, and friction is 0.38–0.68
   of an M5 ATR.
2. **XAUUSD carries a small, genuine intraday trend edge** that survives with
   parameters frozen for five years (1195 trades, WR 50.8%, PF 1.10). It meets
   the trade-count and win-rate targets but not PF ≥ 1.2. At t = 1.47 it is not
   statistically significant either.
3. **EURUSD carries no such edge** and loses to costs with high confidence.
4. **Gold is the better scalping instrument**, by roughly 2× on both the
   friction/volatility ratio and the strength of intraday trend structure.

The most useful lever available is not a better strategy, it is **cheaper
execution**: `scripts/run_backtest.py` reports profit factor at 1.0×, 1.25×,
1.5× and 2× friction, and the same arithmetic runs in reverse — cutting
round-trip cost on gold from USD 0.45 to USD 0.30 adds roughly 0.05R to every
trade's expectancy, which is larger than anything parameter tuning achieved.

## 5. Report files

| File | What it is |
|---|---|
| `reports/XAUUSD_momentum_base_walkforward.md` | headline XAUUSD run (unconstrained objective) |
| `reports/XAUUSD_momentum_full.md` | full-sample backtest + cost sensitivity + Monte Carlo |
| `reports/XAUUSD_momentum_wrgate_walkforward.md` | win-rate forced to >=53%, showing the trade-off |
| `reports/XAUUSD_momentum_gated_walkforward.md` | hard PF+WR gates, only 3 of 15 folds feasible |
| `reports/EURUSD_breakout_base_walkforward.md` | EURUSD, the documented failure |
| `reports/explore.json` | all four families x both symbols, raw search output |

Each has an out-of-sample equity curve, a fit-once holdout curve, a per-fold
in-sample vs out-of-sample chart, and the deployed parameters as JSON.

## 6. Reproducing, and re-running on real data

```bash
python3 scripts/diagnose.py                       # section 1
python3 scripts/explore.py --iters 600            # which family fits which symbol
python3 scripts/run_optimize.py --symbol XAUUSD --mode momentum --label base
python3 scripts/run_optimize.py --symbol EURUSD --mode breakout --label base
python3 scripts/run_backtest.py --config config/XAUUSD_momentum_base.json --report
```

Put broker CSVs in `data/raw/<SYMBOL>/` and all five commands switch to real
data with no other change. **Run `diagnose.py` first**: if the variance ratio on
your real data shows structure at shorter horizons than the synthetic series
does, the conclusions above can change, and that is exactly what the framework
exists to tell you.
