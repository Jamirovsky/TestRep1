# Scalping research framework — XAUUSD & EURUSD

A backtesting and optimisation system for short-horizon intraday strategies on
gold and EURUSD, built to answer one question honestly: **is there a scalping
edge that survives real transaction costs?**

It contains a pessimistic execution engine, four parameterised strategy
families, a walk-forward optimiser with anti-overfitting defences, an MQL5 port
for MetaTrader 5, and a test suite pinning down the behaviours that make
backtests lie.

> **Read this first.** The network policy of the machine this was built on
> blocks every market-data vendor, so the numbers below were produced on a
> **calibrated synthetic price process**, not on real XAUUSD or EURUSD.
> They validate the machinery; they are not evidence of a live edge. Drop real
> bars into `data/raw/` and re-run — see [`data/README.md`](data/README.md).

---

## Results (synthetic data — see the warning above)

Against the requested targets of **≥100 trades, profit factor ≥1.2, win rate ≥50%**:

| | XAUUSD (momentum) | EURUSD (breakout) |
|---|---|---|
| Trades ≥ 100 | **1195 — PASS** | 2294 — PASS |
| Win rate ≥ 50% | **50.8% — PASS** | 48.2% — FAIL |
| Profit factor ≥ 1.2 | 1.10 — **FAIL** | 0.86 — FAIL |
| t-stat of mean R | 1.47 | **−3.01** |

Measured on the strictest test in the repo: one parameter set fitted on
2019–2021, then frozen and traded through 2021–2025. Rolling walk-forward over
15 contiguous folds agrees (XAUUSD PF 1.05, EURUSD PF 0.88).

**The short version.** At true scalping horizons (10–20 minutes) both
instruments are statistically **indistinguishable from a random walk**
(variance-ratio |z| < 1.1), while round-trip friction costs 0.38–0.68 of an M5
ATR. There is nothing there to pay the toll with. Tradeable structure only
becomes significant from about an hour out, and gold has roughly twice
EURUSD's. Gold ends up with a small, real, but statistically insignificant
intraday trend edge; EURUSD loses to costs reliably.

The win rate and the profit factor also pull against each other: forcing the win
rate to ≥53% does achieve 52.5% out of sample, but drags the profit factor down
to 0.96, because taking winners sooner costs more payoff than the extra winners
are worth. The in-sample ceiling is PF 1.28 at WR 54%, and in-sample results
decay by roughly two-thirds out of sample.

Full evidence, including everything that was tried and ruled out:
**[`docs/RESULTS.md`](docs/RESULTS.md)**.

---

## Quick start

```bash
pip install -r requirements.txt

# 0. is a scalping edge even possible here? run this FIRST on any instrument
python3 scripts/diagnose.py

# 1. which strategy family fits which symbol
python3 scripts/explore.py --iters 600

# 2. walk-forward optimisation (the only result worth quoting)
python3 scripts/run_optimize.py --symbol XAUUSD --mode momentum

# 3. full-sample report, cost sensitivity, Monte Carlo
python3 scripts/run_backtest.py --config config/XAUUSD_momentum.json --report

# tests
python3 -m pytest tests/ -q
```

Everything switches to real data automatically as soon as any `.csv` exists in
`data/raw/<SYMBOL>/`.

---

## The finding that shapes everything: friction vs. volatility

Round-trip friction, modelled conservatively (retail ECN, commission included):

| | EURUSD | XAUUSD |
|---|---|---|
| Spread (London/NY) | 0.4 pip | USD 0.18 |
| Commission (USD 7/lot round turn) | 0.7 pip | USD 0.07 |
| Entry + stop slippage | 0.45 pip | USD 0.20 |
| **Round trip** | **1.55 pip** | **USD 0.45** |
| ATR(M5) | ~2.9 pip | ~USD 1.56 |
| **friction / ATR(M5)** | **0.53** | **0.29** |

Two consequences drive every design decision in this repository:

**1. Textbook micro-scalping is arithmetically dead.** With a 5-pip stop on
EURUSD, friction is **31% of the risked amount**. At a 1:1 target you need a 57%
strike rate just to break even — before any edge at all. Stops must be large
enough that friction is ~10% of R, which on these instruments means 12–25 pips
on EURUSD and USD 3–6 on gold, and holding times of tens of minutes rather than
seconds.

**2. Gold is the better scalping instrument, and it is not close.** EURUSD's
famously tight spread stops being an advantage once you divide by how little it
moves. Gold's wider spread is more than paid for by its volatility.

---

## How the search avoids fooling itself

The first version of the optimiser searched 23 free parameters (~10¹¹
combinations) and picked the single best of 400 random draws. On EURUSD it
reported:

```
in-sample      PF 1.35   WR 53.3%   expectancy +0.063R
out-of-sample  PF 0.66   WR 37.5%   expectancy -0.085R
```

That is not a strategy — it is the luckiest of 400 noise draws. Two changes
fixed it, and neither was a better optimiser:

1. **Fewer knobs.** Every parameter that measurement showed was not decisive is
   now fixed rather than searched (`spaces.FIXED`). The space shrank from 10¹¹
   to ~10⁶.
2. **Robust selection instead of peak-picking.** `optimize.robust_select`
   splits the training window into thirds, scores each candidate on all three,
   and ranks by the **worst** third — a configuration must work everywhere in
   the data it was fitted on before it is trusted anywhere else.

The in-sample/out-of-sample gap on the same instrument fell from 0.148R to
0.019R. The strategy still lost money on EURUSD, but the backtester had stopped
lying about it, which is the prerequisite for everything else.

Further defences, all reported automatically: walk-forward efficiency,
neighbourhood stability, bootstrap p-value, cost sensitivity, Monte Carlo
trade-order reshuffling.

---

## Execution model

Every assumption is deliberately pessimistic, because the failure mode of a
backtest is always optimism.

| Assumption | Choice |
|---|---|
| Price series | bars are **bid**; longs fill at the ask and exit on the bid, so spread is paid once per round trip |
| Stop *and* target inside one bar | **stop wins** — OHLC cannot reveal the intrabar path |
| Gaps | fill at the **open**, not at the stop level |
| Entry slippage | always adverse |
| Stop slippage | extra, on top of entry slippage |
| Limit exits (target, partial) | no slippage — a resting limit fills at its price or not at all |
| Trailing stop | advanced only *after* exits are checked, so it cannot rescue the bar that set it |
| Swap | charged at every 21:00 UTC rollover, tripled on Wednesday |
| Rollover hour | never traded |
| Positions | one at a time, no pyramiding |

**The look-ahead barrier** lives in one place, `strategy.to_exec_signals`: a
signal-timeframe bar labelled `t` covers `[t, t+tf)` and is only knowable at
`t+tf`, so it is placed on the execution bar at `t+tf` and filled at that bar's
open. Signals stranded by a weekend or a data hole are discarded, not executed
late.

Full detail in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

---

## Strategy families

All four share a **Kaufman Efficiency Ratio** regime gate — net move divided by
the path walked, which is the cheapest reliable answer to "is there a trend here
worth paying the spread for". Raising that gate raised the edge monotonically in
testing, which is what first made any of this profitable.

| Mode | Idea | Wants |
|---|---|---|
| `breakout` | Donchian break + EMA trend + volatility expansion | trend |
| `momentum` | signed net move over N bars, ER-gated, entered on continuation | trend |
| `pullback` | trend continuation after a shallow retracement | trend |
| `fade` | mean reversion to session VWAP when stretched and exhausted | chop (ER *capped*) |

Stops are ATR-based with a per-symbol floor; targets are R multiples; trade
management (breakeven, partial close, trailing, time stop, session close, daily
loss limit) is shared and searched.

---

## Layout

```
src/scalping/
  instruments.py   contract specs + the cost model
  data.py          multi-format CSV loader, cleaning, resampling, epoch helpers
  dataset.py       real data if present, calibrated synthetic otherwise
  synth.py         synthetic generator (GARCH, fat tails, session seasonality)
  indicators.py    numba indicators, all causal, NaN-tolerant
  strategy.py      the four signal families + the look-ahead barrier
  engine.py        numba execution engine
  metrics.py       performance statistics, all in R
  research.py      forward returns + triple-barrier edge diagnostics
  optimize.py      random search, robust selection, walk-forward
  spaces.py        search spaces (deliberately small)
  report.py        markdown + charts
scripts/
  diagnose.py      stage 0: friction vs volatility, and variance ratio
  explore.py       stage 1: which mode fits which symbol
  run_optimize.py  stage 2: walk-forward optimisation
  run_backtest.py  stage 3: report, cost sensitivity, Monte Carlo
  ExportBars.mq5   MT5 script to export your broker's own M1 bars
mql5/ScalperXG.mq5 the Expert Advisor
tests/             16 tests covering costs, fills, gaps, look-ahead, causality
```

---

## Using the EA

`mql5/ScalperXG.mq5` is a direct port of `src/scalping/strategy.py` — same entry
logic, same ER gate, same ATR stop, same trade management. Copy it to
`MQL5/Experts/`, compile, and test it on **"Every tick based on real ticks"**.

It handles the server-time offset explicitly (`ServerToUtc`): every session
filter here is stated in UTC, and most MT5 brokers run UTC+2/+3. Getting this
wrong silently shifts every session by two or three hours.

**Do not run the shipped defaults on a live account.** They were fitted on
synthetic data. Re-optimise on your broker's own history first.

---

## Limitations

- Headline numbers come from synthetic data; see `data/README.md`.
- Bar data cannot model intrabar path, queue position or requotes.
- The spread model does not reproduce news-event spread spikes tick by tick —
  supplying MT5 exports with a real `spread` column replaces it with your
  broker's actual spreads.
- Swap rates are static.
- Results are per-symbol and per-broker. A different cost structure changes the
  conclusion, which is exactly why `run_backtest.py` reports cost sensitivity.
