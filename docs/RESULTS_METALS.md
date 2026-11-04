# Results — scalpers for XAGUSD, XPTUSD and XPDUSD

**Task:** using the XAUUSD scalper (`mql5/ScalperXG.mq5` + the Python research
framework in this repo) as the reference, build and optimise one scalper per
minor metal, choose the best signal timeframe between M1 and M30, and ship the
optimised parameters.

**Deliverables**

| Symbol | EA | Strategy Tester set | Final config | Timeframe | Family |
|---|---|---|---|---|---|
| XAGUSD | [`mql5/ScalperXAG.mq5`](../mql5/ScalperXAG.mq5) | [`mql5/sets/ScalperXAG.set`](../mql5/sets/ScalperXAG.set) | [`config/XAGUSD_final.json`](../config/XAGUSD_final.json) | **M5** | momentum (impulse continuation) |
| XPTUSD | [`mql5/ScalperXPT.mq5`](../mql5/ScalperXPT.mq5) | [`mql5/sets/ScalperXPT.set`](../mql5/sets/ScalperXPT.set) | [`config/XPTUSD_final.json`](../config/XPTUSD_final.json) | **M5** | momentum (impulse continuation) |
| XPDUSD | [`mql5/ScalperXPD.mq5`](../mql5/ScalperXPD.mq5) | [`mql5/sets/ScalperXPD.set`](../mql5/sets/ScalperXPD.set) | [`config/XPDUSD_final.json`](../config/XPDUSD_final.json) | **M5** | momentum (impulse continuation) |

**Verdict, up front.** Every number here comes from **real** OANDA M1 bars,
January 2019 to October 2026, with conservative retail costs. The XAUUSD study
could only use synthetic data. On that real data none of the three metals
supports a scalper with a statistically significant edge. The shipped
parameters are the best the search found, and that is not the same as being
profitable:

| | XAGUSD | XPTUSD | XPDUSD |
|---|---|---|---|
| Frozen holdout 2025-01 → 2026-10 (fit once on 2019–2024) | 61 tr, PF **1.20**, +0.044R, t 0.53 | 174 tr, PF 0.64, −0.067R, t −2.21 | 92 tr, PF 0.71, −0.075R, t −1.36 |
| Walk-forward 2021-01 → 2026-10 (17 refits) | 336 tr, PF 0.79, −0.056R, t −1.73 | 365 tr, PF 0.55, −0.072R, t −4.30 | 371 tr, PF 0.55, −0.075R, t −4.41 |
| Cost level at which the holdout breaks even | already ≥ 1 at 1.5× costs | 0.25× (≈7 bp round trip) | 0.5× (≈26 bp round trip) |
| Verdict | break-even; the holdout is positive but noise-level | loses reliably | loses reliably |

Silver is the only one that is not clearly negative, and its positive holdout
rests on 61 trades. With t = 0.53 it cannot be told apart from luck. **Do not
run any of the three live on these defaults.** Use them as a starting point for
re-optimising on your own broker's history and costs (section 7).

---

## 1. Data

`scripts/fetch_metals.py` downloads OANDA's M1 candles (mid prices, tick-count
volume) from the public `bunqii/OANDA_<SYM>_<Name>` archives on GitHub. Those
files are verified against the OANDA v20 API, and the download needs nothing
but `raw.githubusercontent.com`. The span is 2019-01 to 2026-10, about 2.1 to
2.6 million M1 bars per symbol, with XAUUSD fetched as well for the comparison.
None of these files are committed (`data/.gitignore`). Re-fetch them with
`python3 scripts/fetch_metals.py`.

Mid prices are fine for this engine. It charges the full modelled spread once
per round trip, which is the same total cost as trading on bid/ask bars.

## 2. Cost model: the decisive input

The minor metals cost far more to trade than gold. Their costs are also a share
of **price**: silver went from USD 15 to USD 60 and palladium from USD 3,000 to
USD 900 inside the sample. So these instruments carry a `ref_price` and their
costs scale with price (`instruments.py`, `strategy.cost_scale_series`,
`engine.cost_scale`):

| | spread @ ref | entry slip | stop slip | round trip, liquid hours |
|---|---|---|---|---|
| XAUUSD (reference, fixed points) | 0.18 USD | 0.06 | 0.14 | **~2.4 bp** |
| XAGUSD | 0.025 @ 30 (8.3 bp) | 1.0 bp | 2.7 bp | **~12 bp** |
| XPTUSD | 2.00 @ 1000 (20 bp) | 2 bp | 5 bp | **~27 bp** |
| XPDUSD | 3.50 @ 1000 (35 bp) | 5 bp | 12 bp | **~52 bp** |

The spread also carries the reference model's session multiplier (×1.8 in the
Asian session) and its volatility coupling. On average that is ×1.4 at the bars
where signals actually fire.

## 3. Choosing the timeframe (M1 … M30)

`scripts/diagnose_tf.py` puts the friction against the ATR of each candidate
signal timeframe (London/NY hours, median 2019–2026,
`reports/metals_diagnose.json`):

| friction / ATR(14) | M1 | M5 | M15 | M30 |
|---|---|---|---|---|
| XAUUSD | 0.71 | 0.29 | 0.17 | 0.13 |
| XAGUSD | 1.98 | 0.78 | 0.46 | 0.34 |
| XPTUSD | 3.93 | 1.55 | 0.92 | 0.69 |
| XPDUSD | 6.25 | 2.46 | 1.44 | 1.05 |

On M1, a platinum trade starts four ATRs behind and a palladium trade six.
**M1 scalping is arithmetically closed on all three metals.** On M5/M15 only
silver has friction below one ATR. Palladium only reaches about 1 ATR on M30.

Variance ratios are well below 1 at 1–4 h for all three metals (z down to −9
on palladium). That looks like intraday mean reversion. Measured directly in
liquid hours, though, a 2σ stretch from a rolling mean reverts by only **0–2 bp**,
against a 12–52 bp toll, so most of the variance-ratio signal is off-hours quote
noise.

The timeframe was then picked empirically. Each metal × timeframe × family
(VWAP fade, rolling-band fade, momentum, breakout) was searched on 2019–2022,
re-ranked by its worst third (`robust_select`), and scored on the untouched
2023–2024 window (`scripts/explore_metals.py`). Round 1 used the base space at
M1/M5/M15/M30 (`reports/metals_explore_round1.json`). Round 2 used a
"selective" space with rarer, larger-move entries and wider stops at M5/M15/M30
(`reports/metals_explore_round2.json`), because round 1 showed that costs, not
signals, decide the outcome.

Validation-window expectancy (R per trade) of the robust winner of each cell:

**Round 1 (base space)**

| | M1 | M5 | M15 | M30 |
|---|---|---|---|---|
| XAG fade / bands / momentum / breakout | −0.10 / −0.08 / −0.11 / −0.18 | −0.10 / −0.27 / −0.12 / −0.15 | −0.13 / −0.10 / −0.11 / −0.10 | −0.14 / −0.12 / −0.08 / −0.08 |
| XPT | −0.12 / −0.14 / −0.22 / −0.11 | −0.10 / −0.10 / −0.11 / −0.11 | −0.19 / −0.11 / −0.18 / −0.23 | −0.10 / −0.12 / −0.18 / −0.18 |
| XPD | −0.23 / −0.25 / −0.18 / −0.36 | −0.18 / −0.13 / −0.15 / −0.19 | −0.13 / −0.17 / −0.27 / −0.25 | −0.17 / −0.16 / −0.21 / −0.18 |
| XAU (comparison) | −0.09 / −0.07 / **+0.02** / −0.01 | −0.01 / −0.05 / −0.04 / −0.03 | −0.04 / **+0.01** / −0.04 / −0.02 | −0.07 / −0.05 / −0.04 / −0.06 |

**Round 2 (selective space)**

| | M5 | M15 | M30 |
|---|---|---|---|
| XAG fade / bands / momentum / breakout | −0.10 / −0.22 / **−0.03** / −0.08 | −0.08 / −0.14 / −0.11 / −0.11 | −0.04 / −0.06 / −0.08 / −0.08 |
| XPT | −0.15 / −0.14 / **−0.02** / −0.03 | −0.09 / −0.12 / −0.09 / −0.11 | −0.12 / −0.23 / −0.08 / −0.07 |
| XPD | −0.08 / −0.08 / −0.08 / −0.19 | −0.11 / −0.12 / −0.12 / −0.16 | −0.07 / **−0.02** / −0.19 / −0.13 |

**Chosen by validation:** XAGUSD **M5 momentum**, XPTUSD **M5 momentum**,
XPDUSD **M30 bands**, each the best validation cell across both rounds.
Palladium's M30 bands then failed badly in the walk-forward, so a second
iteration ran the walk-forward for XPD **M5 momentum**, the family that was
least bad on the other two metals, and that one ships (section 4). Full matrices with
PF and trade counts: `python3 scripts/summarize_explore.py reports/metals_explore_round{1,2}.json`.

## 4. Optimisation and out-of-sample tests

`scripts/run_optimize.py` was run with the timeframe and family pinned and the
selective space:

* **walk-forward:** fit on 730 days, trade the next 120, step 120. That gives
  17 contiguous folds from 2021-01 to 2026-10, with 400 random configurations,
  coordinate-descent refinement and worst-third robust selection per fold;
* **fit-once holdout:** one search on 2019-01 → 2024-12, then trade 2025-01 →
  2026-10 with the parameters **frozen**.

**The EA defaults are the fit-once holdout parameters.** That makes the
2025–2026 column a genuine out-of-sample measurement of exactly what is
compiled into each EA.

### XAGUSD — M5 momentum, NY session

| | trades | WR | PF | exp R | t | max DD |
|---|---|---|---|---|---|---|
| Walk-forward OOS 2021–2026 | 336 | 48.5% | 0.79 | −0.056 | −1.73 | 10.9% |
| **Frozen holdout 2025–2026** | **61** | **47.5%** | **1.20** | **+0.044** | **0.53** | **2.5%** |

Parameters: NY session (12–18 UTC). Enter after a ≥ 3.5 ATR(M5), very straight
(ER ≥ 0.60) 1-hour move that closes beyond the prior bar. Stop = max(2 ATR,
1.92% of price), target 1.5R, trail from +1R, time stop 4 h, at most 2 trades
a day and 4 h cooldown. Friction is ~6% of R, so the result barely moves with
costs:

| cost × | 0 | 0.5 | 1.0 | 1.5 |
|---|---|---|---|---|
| holdout PF | 1.57 | 1.37 | 1.20 | 1.13 |

By year, with the same frozen parameters (2019–2024 in-sample, 2025–2026
out-of-sample):

| 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | **2025** | **2026** |
|---|---|---|---|---|---|---|---|
| +0.1R (35) | +0.3R (20) | −3.2R (21) | +3.5R (30) | −1.5R (34) | +1.6R (37) | **−1.6R (32)** | **+4.3R (29)** |

Read that table honestly. The holdout's +2.7R is one good 2026 against a losing
2025, and the in-sample years net about zero. That is a coin flip with a thin
positive tilt, not an edge.

### XPTUSD — M5 momentum, London+NY

| | trades | WR | PF | exp R | t | max DD |
|---|---|---|---|---|---|---|
| Walk-forward OOS 2021–2026 | 365 | 38.6% | 0.55 | −0.072 | −4.30 | 12.9% |
| **Frozen holdout 2025–2026** | **174** | **40.2%** | **0.64** | **−0.067** | **−2.21** | **8.4%** |

| cost × | 0 | 0.25 | 0.5 | 1.0 |
|---|---|---|---|---|
| holdout PF | 1.13 | 0.99 | 0.86 | 0.64 |

Parameters: London+NY session (07–18 UTC). Enter after a ≥ 3.5 ATR(M5), very
straight (ER ≥ 0.60) 2-hour move. Stop = max(3 ATR, 3.5% of price), target
2.5R, breakeven at +0.7R, trail from +1R, time stop 8 h, at most 2 trades a
day.

The best configuration loses in **every** year, including the six it was fitted
on. Platinum would need a round trip near 7 bp (a ~0.5 USD spread at USD 1,000)
just to break even.

### XPDUSD — M30 bands, then M5 momentum

**Iteration 1: M30 bands, the validation winner.** It failed.

| | trades | WR | PF | exp R | t |
|---|---|---|---|---|---|
| Walk-forward OOS 2021–2026 | 239 | 28.9% | 0.39 | −0.092 | −5.13 |
| Frozen holdout 2025–2026 | 170 | 28.8% | 0.27 | −0.111 | −6.71 |

Even at **zero** cost the frozen holdout has PF 0.87, so there is no signal to
pay the toll with. Report: `reports/XPDUSD_bands_wf_walkforward.md`.

**Iteration 2: M5 momentum, London session (shipped).**

| | trades | WR | PF | exp R | t | max DD |
|---|---|---|---|---|---|---|
| Walk-forward OOS 2021–2026 | 371 | 38.8% | 0.55 | −0.075 | −4.41 | 13.5% |
| **Frozen holdout 2025–2026** | **92** | **48.9%** | **0.71** | **−0.075** | **−1.36** | **4.3%** |

| cost × | 0 | 0.25 | 0.5 | 0.75 | 1.0 |
|---|---|---|---|---|---|
| holdout PF | 1.32 | 1.15 | 1.00 | 0.80 | 0.71 |

It beats iteration 1 on both tests (walk-forward −0.075R vs −0.092R, holdout
−0.075R vs −0.111R), so it is the one compiled into `ScalperXPD.mq5`. Choosing
between the two used the walk-forward and holdout windows, so its numbers are
slightly optimistic. They are still negative.

Parameters: London session (07–12 UTC). Enter after a ≥ 3.5 ATR(M5), very
straight (ER ≥ 0.60) 4-hour move. Stop = max(3 ATR, 3.5% of price), target
0.6R, breakeven at +0.7R, time stop 8 h, one trade a day. Before costs the
holdout makes +0.06R a trade, so palladium does have some impulse
continuation. The ~52 bp toll is roughly twice what it can pay. It breaks even
at half the modelled costs (a ~1.7 USD spread at USD 1,000), and it lost in
every in-sample year.

## 5. Comparison with the XAUUSD scalper

The reference study ran on synthetic data. Two things change on real data:

1. **The original XAUUSD EA defaults** (`config/XAUUSD_momentum_base.json`,
   M15 momentum, NY) traded on real gold 2019-01 → 2026-10 give **1,860 trades,
   WR 44.5%, PF 0.86, −0.050R, t −2.81**. They lost in 2019–2022 (PF 0.82) and
   in 2023–2024 (PF 0.74), and roughly broke even in 2025–2026 (PF 1.08). The
   synthetic-data PF 1.10 did not carry over to real gold.
2. **Gold is still by far the best of the four to scalp.** Its friction/ATR on
   M5 (0.29) beats silver's on M30 (0.34). It is also the only metal where some
   validation cells came out at or above zero (M1 momentum +0.016R, M15 bands
   +0.010R). The minor metals pay 5× (silver) to 20× (palladium) gold's toll in
   basis points, and their intraday moves are not proportionally larger.

| | XAUUSD | XAGUSD | XPTUSD | XPDUSD |
|---|---|---|---|---|
| round trip (bp) | 2.4 | 12 | 27 | 52 |
| best TF by friction/ATR ≤ 0.35 | M5 | M30 | none | none |
| chosen signal TF | M15 (reference) | M5 | M5 | M5 |
| average hold of the shipped config | ~1.5 h | ~3.5 h | ~7 h | ~7 h |

Note the holding times. To get friction down to a small share of R, every
optimised configuration on the minor metals uses wide stops and holds for hours.
These are intraday trades on a fast chart, not scalps measured in minutes.
**Minute-scale scalping of XAG/XPT/XPD at retail costs is not viable on this
evidence.**

## 6. What was tried and ruled out

| Idea | Result |
|---|---|
| M1 signals, any family | friction 2–6 ATR(M1); every cell negative in-sample *and* out-of-sample |
| VWAP fade / Bollinger fade (variance ratio < 1) | real reversion after 2σ in liquid hours is 0–2 bp, below the toll |
| Gold → minor-metal lead-lag (idiosyncratic residual follow / fade) | looked like +20 bp with full-sample normalisation; with a causal rolling beta and de-overlapped signals, t < 1 and the sign flips by year. Dropped. |
| Time-of-day seasonality | strongest effect: palladium −6.7 bp at 08:00 UTC, negative in 8/8 years, but against a 42–52 bp toll |
| Frequent entries (round 1) | the zero-cost expectancy of the round-1 winners is 0 to +0.04R; costs subtract 0.08–0.18R |
| Rare, large-move entries (round 2) | best validation cells reach −0.02R; only silver's frozen holdout turned positive |

## 7. Using the EAs

1. Copy `mql5/ScalperXAG.mq5`, `ScalperXPT.mq5` and `ScalperXPD.mq5` to
   `MQL5/Experts/` and compile. Each one refuses to start on another symbol
   unless `InpCheckSymbol=false`, which you need if your broker calls silver
   `SILVER`.
2. In the Strategy Tester use **Every tick based on real ticks**. Set
   `InpGmtOffsetHours` to the broker's server offset (2 or 3 for most), because
   every session hour is in UTC and `TimeGMT()` is unreliable in the tester.
3. Load the matching `.set` from `mql5/sets/`. The `Y` rows bracket the shipped
   values, so the MT5 optimiser can re-fit them on your broker's own ticks and
   costs.
4. Re-run the Python pipeline with your broker's numbers. Edit the instrument
   in `src/scalping/instruments.py` (`spread_base_points`, `ref_price`,
   slippage), then:

```bash
python3 scripts/fetch_metals.py
python3 scripts/diagnose_tf.py
python3 scripts/explore_metals.py --symbols XAGUSD --variant selective --tfs 5 15 30
python3 scripts/run_optimize.py --symbol XAGUSD --mode momentum --tf 5 --variant selective \
    --label wf --end 2026-10-31 --fit-trades-per-year 25 --fit-min-pf 0 --fit-min-wr 0 \
    --max-hold 300 --holdout-start 2025-01-01
python3 scripts/finalize_metals.py XAGUSD:momentum:ScalperXAG
```

The cost tables above are the most useful thing to check against your broker.
Silver's configuration keeps PF above 1.1 even at 1.5× the modelled costs.
Platinum needs a quarter of the modelled cost to break even and palladium
half. Neither is a realistic retail price for those spreads.

## 8. Report files

| File | Contents |
|---|---|
| `reports/metals_diagnose.json` | friction, ATR and variance ratio per symbol × timeframe |
| `reports/metals_explore_round1.json`, `_round2.json` | every symbol × timeframe × family search, fit and validation metrics |
| `reports/<SYM>_<mode>_wf_walkforward.md` | walk-forward folds, holdout, cost sensitivity, deployed-fold parameters |
| `reports/<SYM>_<mode>_wf_*.png` | stitched OOS equity, holdout equity, per-fold IS vs OOS |
| `config/<SYM>_<mode>_wf.json` | raw optimiser output (walk-forward + holdout) |
| `config/<SYM>_final.json` | the shipped parameters, validation summary and by-year table |
