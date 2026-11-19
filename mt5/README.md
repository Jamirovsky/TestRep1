# AMS-BTCUSD on MetaTrader 5 (Capital Point Trading)

Two files:

| File | What it does |
|---|---|
| `AMS_BTCUSD.mq5` | The Expert Advisor. Trades BTCUSD with the strategy found in the research loop, with persistent memory. |
| `export_btcusd.py` | Exports Capital Point Trading's own BTCUSD M1 history and contract spec, so the research pipeline can be re-run on the broker's exact feed and costs. |

## 1. Install the Expert Advisor

1. In MT5 (logged in to `CapitalPointTrading-MT5-…`): **File → Open Data Folder** → `MQL5\Experts\`.
2. Copy `AMS_BTCUSD.mq5` there, open it in **MetaEditor** (F4) and press **Compile** (F7).
   It was written without access to MetaEditor, so if the compiler reports anything, send me the message.
3. The final strategy uses one sleeve (A). Sleeve B is off by default because 150 € is too small to split. If you enable B, use a **hedging** account.
4. Open a BTCUSD chart (any timeframe) and drag the EA onto it. Enable **Algo Trading**.
5. On start-up the **Experts** tab shows the rebuilt memory, for example `A memory cell 3 (long, mom up): ewR=0.374 n=110`.

## 2. Test it before trading real money

1. **Strategy Tester** (Ctrl+R): Expert `AMS_BTCUSD`, Symbol `BTCUSD`, Modelling **Every tick based on real ticks**, period 2025-01-01 → today, deposit **150 EUR**, leverage = your account's.
2. Compare with the Python results in `results/REPORT.md`. Small differences are expected, because the broker feed and spread differ from the research data.
3. Then run it on a **demo** account for at least 4–6 weeks before going live.

## Shortcut: one command does export + both tester runs

```bash
pip install MetaTrader5 pandas
python mt5/run_all.py
```

It exports the data, asks you to close MT5, runs the Strategy Tester for 2025-01-01 → today and 2026-08-01 → today, copies the reports to `results/mt5/` and prints the key numbers.

## 3. Re-run the research on the broker's own data (recommended)

```bash
pip install MetaTrader5 pandas numpy numba optuna pyarrow
python mt5/export_btcusd.py --symbol BTCUSD --start 2024-11-01
# -> data/mt5_btcusd_m1.csv.gz + data/mt5_symbol_spec.json  (spread, lot size, leverage, swap)
set AMS_DATA=mt5                      # PowerShell: $env:AMS_DATA="mt5"
python -m scalper.optimize_full --version v7 --trials 600
python -m scalper.holdout
```

`mt5_symbol_spec.json` automatically replaces the assumed costs (spread, minimum lot, leverage, swap).

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `InpRiskPerTrade` | 0.02 | Risk per trade as a fraction of the sleeve's equity |
| `InpMinLotRiskCap` | 0.05 | If the risk-based size is below the broker minimum (0.01 lot), trade the minimum lot only if its stop risk is at most 5% of the sleeve's equity; otherwise skip |
| `InpMinStopSpread` | 2.0 | Skip signals whose stop is shorter than 2× the current spread |
| `InpMemoryDays` | 60 | Days of M1 history replayed to rebuild the memory at start-up |
| `A_*` / `B_*` | see file | Per-sleeve signal, exit and memory settings (do not change them without re-running the research) |

## How the memory works

Every signal opens a **shadow trade** (paper trade, no money), whether or not it is traded for real. When a shadow trade closes, its result in R (risk units, after spread) updates an exponentially-weighted average for its **cell**:

```
cell = direction (long/short) × 7-day momentum state (up/down)
memR = 0.9 · memR + 0.1 · R
```

Once a cell has 5 shadow results, it is vetoed while its `memR < -0.3` (R units), and re-enabled automatically when its shadow trades recover. The memory is written to `MQL5\Files\AMS_BTCUSD_<sleeve>.mem` (CSV, readable in Excel) on every update and rebuilt from history on restart, so it survives restarts.
