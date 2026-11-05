# XBRUSD - bands - walk-forward result

- data: **real** - data/raw/XBRUSD/*.parquet
- span: 2019-01-02 to 2026-10-30
- folds: 2 x (train 730d / test 120d), contiguous out-of-sample coverage 240 days
- configurations evaluated: 600

## Targets, measured on out-of-sample data only

| Target | Required | Achieved | Result |
|---|---|---|---|
| Trades >= 100 | 100 | 77 | FAIL |
| Profit factor >= 1.01 | 1.01 | 0.55 | FAIL |
| Win rate >= 57% | 57.0 | 41.6 | FAIL |

## Metrics

| Metric | Walk-forward OOS | Full sample (deployed params) |
|---|---|---|
| Trades | 77 | 1248 |
| Win rate % | 41.6 | 55.1 |
| Profit factor | 0.55 | 0.80 |
| Expectancy (R) | -0.130 | -0.035 |
| Avg win (R) | 0.38 | 0.25 |
| Avg loss (R) | -0.49 | -0.38 |
| Payoff | 0.77 | 0.65 |
| Total R | -10.0 | -44.0 |
| Return % | -4.6 | -17.0 |
| Max DD % | 5.9 | 18.4 |
| Max DD (R) | 12.0 | 46.8 |
| Sharpe | -4.44 | -1.03 |
| Sortino | -6.46 | -0.89 |
| CAGR % | -18.2 | -2.1 |
| Calmar | -3.11 | -0.11 |
| Trades/day | 1.22 | 0.56 |
| Avg hold (min) | 123 | 121 |
| Max consec. losses | 6 | 7 |
| t-stat of mean R | -2.15 | -3.20 |
| Friction / gross % | 18.1 | 14.1 |

- walk-forward efficiency (OOS / IS expectancy): **-4.98**
- bootstrap p-value for mean R > 0 (OOS): **0.9860**
- neighbourhood stability: 16 neighbours, median score 0.38, 100% positive

## Per-fold

```
walk-forward folds:
  1: train 2022-04-16..2024-04-15 IS  154tr +0.031R -> test 2024-04-15..2024-08-13 OOS   29tr -0.084R PF 0.76 WR 51.7%
  2: train 2022-12-12..2024-12-11 IS  328tr +0.021R -> test 2024-12-11..2025-04-10 OOS   48tr -0.157R PF 0.36 WR 35.4%
stitched OOS: trades    77 | WR  41.6% | PF  0.55 | exp -0.130R | payoff 0.77 | totR   -10.0 | ret    -4.6% | DD   5.9% | Sharpe -4.44 | t -2.15
walk-forward efficiency: -4.98
```

## Deployed parameters

```json
{
  "strategy": {
    "mode": "bands",
    "tf_minutes": 30,
    "session": "extended",
    "atr_period": 14,
    "atr_rank_lookback": 288,
    "atr_rank_min": 0.1,
    "atr_rank_max": 0.99,
    "sl_atr": 4.0,
    "tp_r": 0.3,
    "min_sl_points": 0.0,
    "min_sl_bp": 25,
    "allow_long": true,
    "allow_short": true,
    "er_period": 24,
    "er_min": 0.0,
    "er_max": 0.3,
    "vwap_anchor_hour": 0,
    "band_k": 1.5,
    "rsi_period": 7,
    "rsi_lo": 28,
    "rsi_hi": 72.0,
    "adx_period": 14,
    "adx_max": 30,
    "confirm_mode": 2,
    "min_dev_atr": 0.0,
    "bb_period": 48,
    "don_period": 24,
    "ema_fast": 12,
    "ema_slow": 48,
    "adx_min": 20.0,
    "expansion_mult": 1.15,
    "atr_avg_period": 48,
    "pb_slope_period": 30,
    "pb_rsi_lo": 40.0,
    "pb_rsi_hi": 60.0,
    "pb_depth_atr": 0.5,
    "pb_lookback": 6,
    "mom_period": 24,
    "mom_min_atr": 1.0,
    "mom_confirm": 1,
    "orb_hour": 7,
    "orb_bars": 4,
    "orb_buffer_atr": 0.0,
    "orb_fade": 0,
    "r2_period": 2,
    "r2_lo": 10.0,
    "trend_ema": 100,
    "sweep_lookback": 24,
    "sweep_wick_atr": 0.3
  },
  "execution": {
    "point": 0.001,
    "value_per_point_per_lot": 1.0,
    "min_lot": 0.01,
    "lot_step": 0.01,
    "max_lot": 50.0,
    "commission_per_lot_rt": 0.0,
    "slippage_points_entry": 5.0,
    "slippage_points_stop": 12.0,
    "swap_long_points": 0.0,
    "swap_short_points": 0.0,
    "initial_equity": 10000.0,
    "risk_pct": 0.005,
    "max_spread_points": 1000000000000.0,
    "be_trigger_r": 0.3,
    "be_offset_r": 0.1,
    "partial_r": 0.4,
    "partial_frac": 0.5,
    "trail_start_r": 0.8,
    "trail_dist_r": 1.0,
    "max_bars": 180,
    "cooldown_bars": 60,
    "max_trades_per_day": 4,
    "daily_loss_limit_r": 1000000000.0,
    "force_exit_hour": 20,
    "force_exit_min": 45,
    "compound": true
  }
}
```

## Out-of-sample breakdown

**by hour**

|   hour |   trades |   win_rate |   total_r |   exp_r |
|-------:|---------:|-----------:|----------:|--------:|
|      7 |        2 |      100   |       0.9 |   0.45  |
|      8 |        4 |        0   |      -2.1 |  -0.515 |
|      9 |        8 |       37.5 |      -1.9 |  -0.234 |
|     10 |        7 |       71.4 |       1.6 |   0.234 |
|     11 |        5 |       60   |       0.1 |   0.025 |
|     12 |        1 |        0   |      -1   |  -1.02  |
|     13 |       11 |       36.4 |      -4.2 |  -0.383 |
|     14 |        7 |       42.9 |      -1.8 |  -0.253 |
|     15 |        8 |       25   |      -0.7 |  -0.093 |
|     16 |        7 |       28.6 |      -1.1 |  -0.151 |
|     17 |        8 |       62.5 |       0.7 |   0.091 |
|     18 |        5 |       40   |      -0.5 |  -0.099 |
|     19 |        2 |        0   |      -0.1 |  -0.052 |
|     20 |        2 |       50   |      -0   |  -0.02  |

**by direction**

| direction   |   trades |   win_rate |   total_r |   exp_r |
|:------------|---------:|-----------:|----------:|--------:|
| long        |       39 |       43.6 |      -4.1 |  -0.104 |
| short       |       38 |       39.5 |      -5.9 |  -0.156 |

**by exit**

| exit_reason   |   trades |   win_rate |   total_r |   exp_r |
|:--------------|---------:|-----------:|----------:|--------:|
| session_close |        9 |       33.3 |      -0.6 |  -0.071 |
| stop_loss     |       12 |        0   |     -12.3 |  -1.021 |
| take_profit   |       25 |      100   |      11.1 |   0.444 |
| time_stop     |       31 |       12.9 |      -8.2 |  -0.264 |

**by year**

|   year |   trades |   win_rate |   total_r |   exp_r |
|-------:|---------:|-----------:|----------:|--------:|
|   2024 |       36 |       50   |      -2.4 |  -0.065 |
|   2025 |       41 |       34.1 |      -7.6 |  -0.186 |


![oos equity](XBRUSD_bands_wf_m30t_oos_equity.png)

![folds](XBRUSD_bands_wf_m30t_folds.png)
