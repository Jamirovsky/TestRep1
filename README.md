# AMS-BTCUSD: Adaptive Memory Scalper (Capital Point Trading, MT5)

A BTCUSD strategy for a 150 € account. It has memory (shadow-trade expectancy per market regime) and adapts to volatility. It was found with a backtest → forward-test → optimise loop.

**Results, full report and caveats:** [`results/REPORT.md`](results/REPORT.md)
**Install on MetaTrader 5:** [`mt5/README.md`](mt5/README.md)

| | PF | Sharpe | Return | Max DD |
|---|---|---|---|---|
| Holdout (Aug–Nov 2026, never optimised on) | 1.52 | 2.42 | +34.7% | 12.9% |
| Full 2 years | 1.51 | 2.28 | +311% | 11.7% |

## Layout

```
mt5/AMS_BTCUSD.mq5         Expert Advisor (final strategy, persistent memory)
mt5/export_btcusd.py       export broker BTCUSD M1 history + contract spec from MT5
config/final_strategy.json final parameters
scalper/engine.py          numba engine: signals, shadow-trade memory, 1-minute execution with bid/ask
scalper/backtest.py        cost profiles, parameter spaces, metrics, objective
scalper/optimize_full.py   final optimiser (quarterly consistency + plateau selection)
scalper/wfo.py             walk-forward optimiser (used in earlier rounds)
scalper/holdout.py         forward test on the untouched holdout + cost stress
scalper/strategy.py        live decision function (same engine, used by tests)
tests/                     live-vs-backtest consistency test
scripts/download_bitstamp.py  public BTC/USD 1-minute data
```

## Reproduce

```bash
pip install numpy pandas numba optuna pyarrow matplotlib
python scripts/download_bitstamp.py 2024-11-01 2026-11-19        # or export from MT5, then AMS_DATA=mt5
python -m scalper.optimize_full --version v7 --trials 600 --seeds 1 2 3 4
python -m scalper.holdout
python -m scalper.report
python tests/test_live_consistency.py
```
