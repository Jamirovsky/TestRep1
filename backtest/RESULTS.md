# OrderFlowIcebergEA: backtest and optimisation results

Run 2026-11-09. Code: `backtest/` (engine checked by `python test_engine.py`, 11 hand-computed checks).

## Verdict

**No robust edge found, and optimisation did not create one.**

- **Defaults on CME futures, bar-proxy events:** about break-even. Pooled 1-minute result: 89 trades, +0.02R mean. Results are indistinguishable from the same rules fired on **random** events.
- **Optimisation:** the best of 144 settings scored *lower* in-sample than the typical best-of-144 on random events (15th percentile of that null). In-sample rank did not predict out-of-sample rank (r = −0.03).
- **The one consistent direction:** fewer, stronger events (`InpProxyVolMult` 4.0 instead of 3.0) was better than the default in every data slice, but never significantly. On 29 sessions the optimiser never saw, it made +2.4R over 37 trades, the 65th percentile of random.
- **Real tick order flow (BTC perpetual, aggressor-flagged trades):** the EA's actual iceberg and stop-run detector does *worse* than random events. Default: −17.9R over 30 trades, below all 200 random seeds. All 144 settings lose money in-sample.
- **Reversion models** (Aggressive, Back in Black) add trades but not edge. Back in Black lost −22R on ES over 50 sessions.

The rules as published, as far as they can be tested without CME Market-By-Order data, do not show an edge over this period. The proxy event detector is not the real signal. The real signal (Bookmap iceberg detection from CME MBO) could not be tested; see "What would settle it" below.

## Data

| Set | Instruments | Bars | Sessions | Notes |
|---|---|---|---|---|
| 1-minute futures | NQ, ES, GC, CL (Yahoo `=F`, front month, real exchange volume) | 1m | 21 (Oct 12 – Nov 9 2026) | EA default `InpProxyTF = M1` |
| 5-minute futures | same | 5m | 50 (Aug 31 – Nov 9 2026) | `InpProxyTF = M5`. The first 29 sessions are unseen by the optimiser. |
| BTC tick flow | BTCUSDT USD-M perpetual (Binance aggTrades, 30.9M trades with aggressor side) | events from ticks, execution on 10s bars | 20 weekdays (Oct 9 – Nov 7 2026) | The EA's `OnTradeTick` detector, run as written |

Session: 09:30–16:00 New York time, flat at the close, zones reset each session (EA defaults).

Costs:
- **Futures:** $2.25 commission per side per contract, plus 1 tick slippage on every stop or market fill.
- **BTC:** 0.05% taker and 0.02% maker fees, plus 1 tick.

## Method

The engine (`ofi_engine.py`) is a port of the EA's `OnTick` logic. Each bar is walked as open → low → high → close (or open → high → low → close for a down bar). A tick is emitted at every price the EA's state reacts to: confirmation levels, the pending entry, the cancel level, the stop, the target, and the reversion triggers. Order fills, stops and targets therefore resolve in path order.

Zones activate on the bar *after* the event (no lookahead). The ATR is a hand-computed Wilder ATR on closed 5-minute bars. Results are in R (planned risk), so sizing doesn't matter.

Controls (from the trading-brain lab rules):
- **Random-event null:** the same number of events per session and the same zone heights, placed at random in-session bars. 200 seeds. This asks whether event detection adds anything beyond the ATR breakout mechanics.
- **Max-statistic null for the grid:** the whole 144-setting grid is rerun on random events, 20 seeds. The real best-of-grid must beat the random best-of-grid.
- **In-sample / out-of-sample split** by session (first 60% / last 40%), plus a separate unseen 5-minute holdout.
- **Distribution measures:** p90, max, mean without the best 5% of trades, long/short split, and session drift. Per-instrument rows sit alongside every pooled number.

## 1. Baseline: EA defaults

1-minute futures (bar proxy) and BTC (real tick detector), 21 and 20 sessions:

| | Trades | Mean R | Total R | Win | PF | Mean R without top 5% | Random-event mean total R | Beats random |
|---|---|---|---|---|---|---|---|---|
| NQ | 20 | −0.16 | −3.2 | 25% | 0.74 | −0.33 | −3.0 | 49% |
| ES | 26 | +0.13 | +3.3 | 27% | 1.20 | −0.26 | −4.5 | 95% |
| GC | 26 | −0.04 | −1.0 | 35% | 0.91 | −0.16 | −1.5 | 52% |
| CL | 17 | +0.17 | +2.9 | 53% | 1.51 | +0.06 | +0.4 | 73% |
| **Futures pooled** | 89 | +0.02 | +2.0 | | | | | |
| **BTC (tick flow)** | 30 | **−0.60** | **−17.9** | 20% | 0.15 | −0.72 | −2.7 | **0%** |

ES's result is driven by one +9.7R short. Without the top 5% of trades, every futures market except CL is negative.

On BTC, 26 of 30 trades ended at the stop and none reached a target. Breakouts confirmed 1 ATR away from absorption zones reversed more often than breakouts from random zones. That points the opposite way from the strategy's premise.

5-minute futures, 50 sessions, defaults: 84 trades, +0.02R mean, +1.9R total. Mean without the top 5% is −0.13R.

## 2. Optimisation

The grid has 144 settings:
- event threshold: `InpProxyVolMult` 2.5 / 3 / 4, or BTC iceberg/stop-run thresholds 50/100, 100/200, 200/400 BTC;
- `InpRequireKeyLevel` on or off;
- target: next key level, 2R, 3R, or trail only;
- stop: 0.75 or 1.15 ATR;
- reversion: off, Aggressive (2 ATR), or Back in Black (2 ATR).

The objective was in-sample SQN, pooled across the four futures.

| | Best in-sample setting | In-sample SQN / R | Random best-of-grid SQN (median / p95) | Real best vs random | Out-of-sample R |
|---|---|---|---|---|---|
| Futures | vol_mult 4, key level on, next-level target, stop 1.15, no reversion | 0.15 / +1.4R (47 trades) | 0.77 / 1.63 | **15th percentile** | +7.4R (27 trades) |
| BTC | 50/100 BTC, key level off, 3R target, stop 0.75, Back in Black | −0.23 / −2.5R (60 trades) | −0.13 / 0.49 | 45th percentile | −1.2R (39 trades) |

- On futures, in-sample and out-of-sample results are uncorrelated across the grid (r = −0.03).
- On BTC they are correlated (r = 0.50), but consistently negative.
- The out-of-sample window (late Oct – early Nov) was kind to most futures settings. Mean out-of-sample R across the grid was positive while mean in-sample R was negative. That is a period effect, not a parameter effect.

## 3. Final checks on the leading futures settings

| Check | EA defaults | `vol_mult=4` | `vol_mult=4` + trail only |
|---|---|---|---|
| **Unseen 5m holdout** (29 sessions, Aug 31 – Oct 9) | 53 trades, −2.8R, 44th pct | 37 trades, **+2.4R, 65th pct** | 36 trades, +0.2R, 46th pct |
| 1m out-of-sample (8 sessions) | 32 trades, +6.5R, 89th pct | 27 trades, +7.4R, 93rd pct | 26 trades, +21.7R, 100th pct* |
| All 50 5m sessions | 84 trades, +1.9R | 64 trades, +11.1R | 63 trades, +11.6R |

\* The trail variant was examined *because* of its out-of-sample number, so that percentile is biased upward. It does not hold on the unseen holdout.

"Pct" is the share of 200 random-event runs, pooled across the four futures, that the real result beats.

## Recommended settings

- **Keep the published rules:** 1.0 ATR confirmation, 1.15 ATR entry and stop, no breakeven, key-level filter on. Nothing in the grid beat them robustly.
- **`InpProxyVolMult` = 4.0** in bar-proxy mode. It is the only change that pointed the same way in every slice. The evidence is weak, so treat it as a tilt, not a finding.
- **Leave reversions off.** They did not help on any data set and lost heavily on ES.
- **Don't run the position model on crypto tick flow.** It tested significantly worse than random.

## What would settle it

1. **CME Market-By-Order or trades with aggressor side for NQ/ES/GC/CL.** Databento's `mbo` or `trades` schema, for example (paid; free starter credits). With that, the EA's `Ticks` mode can run on the actual instrument. That is the strategy's real signal, and this backtest could not test it.
2. **Your broker's MT5 tick history** in the Strategy Tester with "Every tick based on real ticks", if the broker is exchange-connected (aggressor flags present).
3. **More sessions.** 21–50 sessions with 20–90 trades cannot detect an edge smaller than roughly 0.3R per trade.

## Reproduce

```bash
cd backtest
python fetch_data.py futures && python fetch_data.py btc 30
python test_engine.py
python run_backtest.py all      # baseline + optimisation (about 1.5 h on 4 cores)
python run_m5.py '{"proxy_vol_mult": 4.0}'
python final_checks.py
```

(Yahoo serves only the most recent 30 days of 1-minute bars, so a later refetch reproduces the method, not these exact numbers.)
