# Data

## Why there is no real history in this repository

The sandbox this project was built in blocks every market-data provider at the
network policy (Dukascopy, HistData, Yahoo, OANDA, Alpha Vantage, Binance,
Investing.com, Kaggle, Hugging Face — all refused with `connect_rejected`), and
the GitHub integration refuses to attach repositories owned by anyone else, so
public dataset repos were unreachable too. Only PyPI and this repository's own
GitHub org were routable.

Everything therefore runs on a **calibrated synthetic generator**
(`src/scalping/synth.py`) until you supply real bars. Results on synthetic data
validate the *machinery*; they are not evidence of an edge on real XAUUSD or
EURUSD. See the top of `synth.py`.

## Drop real data here

Put CSV files in `data/raw/<SYMBOL>/` — for example
`data/raw/EURUSD/EURUSD_2019.csv`. Every script switches to real data
automatically as soon as any `.csv` exists there; nothing else needs changing.

```
data/raw/
├── EURUSD/
│   └── *.csv
└── XAUUSD/
    └── *.csv
```

Then re-run:

```bash
python3 scripts/explore.py                 # which mode fits which symbol
python3 scripts/run_optimize.py            # walk-forward optimisation
python3 scripts/run_backtest.py --report   # final report
```

## Accepted formats (auto-detected, no configuration)

| Source | Header / first line | Notes |
|---|---|---|
| **MetaTrader 5** | `<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>` | Best option — includes the broker's real spread, which the engine will use instead of its model |
| **HistData.com** | `20190102 000000;1.14612;1.14620;1.14602;1.14611;0` | Free M1 ASCII, one zip per month |
| **Dukascopy** | `Gmt time,Open,High,Low,Close,Volume` | Export from the web JForex historical data feed |
| **generic** | `datetime,open,high,low,close[,volume,spread]` | Anything else you can produce |

Timestamps are assumed UTC unless the file carries a timezone. **Check your
broker's server timezone** — most MT5 brokers use UTC+2/+3, which shifts every
session filter by two or three hours and will quietly wreck the results. Convert
to UTC on export, or pass `tz=` to `scalping.data.load_csv`.

## Getting M1 bars out of MetaTrader 5

Fastest path, and it uses your own broker's prices and spreads — the ones you
will actually trade against:

1. Copy `scripts/ExportBars.mq5` to
   `MQL5/Scripts/` in your terminal's data folder (File → Open Data Folder).
2. Compile it in MetaEditor (F7).
3. In MT5 open a chart for the symbol, press F2 and download the M1 history
   you want (Tools → Options → Charts → set "Max bars in chart" to Unlimited
   first).
4. Drag the script onto the chart, set `InpYearsBack` and run it.
5. It writes `MQL5/Files/<SYMBOL>_M1.csv`. Copy that into
   `data/raw/<SYMBOL>/`.

Alternatively, from Python with the `MetaTrader5` package on Windows:

```python
import MetaTrader5 as mt5, pandas as pd
mt5.initialize()
rates = mt5.copy_rates_range(
    "EURUSD", mt5.TIMEFRAME_M1,
    pd.Timestamp("2019-01-01"), pd.Timestamp("2026-01-01"),
)
df = pd.DataFrame(rates)
df["time"] = pd.to_datetime(df["time"], unit="s")
df.rename(columns={"tick_volume": "volume"}, inplace=True)
df[["time", "open", "high", "low", "close", "volume", "spread"]].to_csv(
    "data/raw/EURUSD/EURUSD_M1.csv", index=False
)
```

`spread` from MT5 is in points and the loader will use it directly, which is
strictly better than the modelled spread.

## How much history do you need

The walk-forward defaults are a 365-day training window and a 120-day test
window over 5 folds, so **at least 3 years** — 5 or more is better. Less than
that and the out-of-sample segments are too short for their statistics to mean
anything.
