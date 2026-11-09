# OrderFlowIcebergEA: the strategy from the video, rebuilt for MT5

**Source video:** [COPY This CRAZY SIMPLE 3-Step Futures Trading Strategy (LIVE Trading)](https://www.youtube.com/watch?v=wym1NAroAuQ) by Chart Fanatics.

**Trader:** Scott Pulcini. Strategy name: *Institutional Order Flow & Iceberg Trading Strategy*.

**How the rules were extracted:** YouTube blocks automated access from cloud servers with a bot check. Instead, the rules come from Chart Fanatics' official written breakdown at
<https://www.chartfanatics.com/strategies/institutional-order-flow-iceberg-trading-strategy>.
That page embeds this exact video (`wym1NAroAuQ`) as its header video. The live-trading commentary in the video itself was not reviewed.

---

## 1. The strategy in one picture

```
Important price area ──► Significant iceberg or stop-run EVENT ──► mark EVENT ZONE
                                                                      │
                        5-minute Wilder's ATR measured from the zone ◄┘
                                     │
          ┌──────────────────────────┴───────────────────────────┐
   MODEL 1: POSITION TRADE                              MODEL 2: REVERSION TRADE
   price moves 1.0 ATR beyond zone (confirmation)       price stretches 1 / 2 / 3 ATR away
   entry  = 1.15 ATR beyond zone                        fade it back to the event zone
   stop   = 1.15 ATR beyond the OPPOSITE side            - Aggressive: extension only
   target = gamma level / liquidity / key level          - Back in Black: extension + level
   no breakeven; trail stop only on NEW events           - A+: extension at a previous event zone
```

The three steps in the video's title match the core of Model 1:
**(1) key level, then (2) significant order-flow event, then (3) ATR confirmation and entry.**

## 2. Extracted rules

| # | Rule from the source | Values |
|---|---|---|
| 1 | Mark important areas first: S/R, gamma levels, VWAP, other plan levels. A level alone is **not** a trade. | — |
| 2 | Wait for a significant **iceberg** (hidden size absorbing aggression) or **stop run** at that area. Ignore anything below the size threshold. | ES 700 / 500, NQ 150 / 150, CL 150 / 150, Gold 150 / 150, Bonds 500 / n.a. (iceberg / stop run, contracts) |
| 3 | The event price area becomes the **event zone**. | — |
| 4 | Measure with the **5-minute Wilder's ATR**. | ATR(14) assumed; the source does not state the period |
| 5 | **Confirmation:** price moves **1 full ATR** beyond the zone. Direction comes from the price response, not the event type. A buy iceberg that fails is bearish ("Broken Ice"). | 1.00 ATR |
| 6 | **Entry** at **115% ATR** beyond the zone. | 1.15 ATR |
| 7 | **Stop** at **115% ATR beyond the opposite side** of the zone. | 1.15 ATR |
| 8 | **Size** from the entry-to-stop distance and the planned risk. | — |
| 9 | **Target:** no fixed target. Use gamma levels, resting liquidity or key levels, with partials at intermediate areas. | — |
| 10 | **Do not move to breakeven** on profit. **Trail the stop** to 115% ATR beyond a **new** qualifying event in the trade's direction. | — |
| 11 | **Reversion:** after an event, mark the 1 / 2 / 3 ATR extensions and fade back to the zone. **Aggressive** uses the extension only. **Back in Black** needs the extension to align with gamma / Fibonacci / Bollinger. **A+** needs the extension at a previous event zone, with the stop outside that zone. | — |
| 12 | **Gamma:** positive gamma tends to range, negative gamma tends to trend. | external data |
| 13 | **Do not fade program buying or selling.** Signs: TICK stuck at ±1000 (−1300/−1400), relative volume ≥ 200% versus the same 5-minute slot over 30 days, and no normal reversions. | RVol 200%, 30 days |
| 14 | **Daily loss limit.** Stop trading for the day when it is hit. | — |
| 15 | Extras: Double Whammy (stops plus an opposite iceberg at the same price), Failed Balance Breakout, HIRO divergence, Bookmap price-change scalps. | context only |

## 3. What maps exactly to MT5, and what cannot

The strategy's edge is reading **CME Market-By-Order data in Bookmap**. MT5 does not have that data. Everything that is pure price and risk logic is implemented exactly. The event detection is the part that depends on your data feed.

| Part | In this EA | Fidelity |
|---|---|---|
| 5-minute Wilder's ATR | Computed by hand with Wilder (RMA) smoothing. MT5's built-in `iATR` uses a simple average, so it is not used. | **Exact** |
| 1.0 ATR confirmation, 1.15 ATR entry and stop | Stop order at 1.15 ATR after a 1.0 ATR touch. The stop is placed beyond the opposite side. | **Exact** |
| Both directions per zone (Broken Ice) | `InpAllowBothDirections` | **Exact** |
| Risk-based position size | `OrderCalcProfit` on the entry-to-stop distance | **Exact** |
| No breakeven; trail on new events | Trails only when a newer zone confirms in the trade's direction | **Exact** |
| Targets at key or gamma levels | Next key level at least `InpMinTargetR` away, with an R-multiple fallback | Close |
| Reversion: Aggressive, Back in Black, A+ | All three. Back in Black uses key levels and Bollinger(20, 2); Fibonacci levels can be drawn as `LVL` lines. | Close |
| Reversion stop, Aggressive and Back in Black | **Not given in the source.** Defaults to 0.5 ATR beyond the extension (`InpRevStopATR`). | **Assumption** |
| Daily loss limit, session flat, max trades | Equity-based limit | **Exact** |
| Icebergs and stop runs, exchange futures feed (MT5 broker with real CME ticks carrying buy/sell aggressor flags) | **Iceberg:** at least N contracts traded aggressively into one price within `InpAbsorbWindowSec`, while price does not trade through it. That is hidden size being refilled. **Stop run:** at least N aggressive contracts within a few seconds that take out the swing high or low. The source's per-market contract thresholds apply directly. | **Approximation** of Bookmap's MBO iceberg detection (time and sales only, no MBO) |
| Icebergs and stop runs, CFD or forex feed (no exchange volume) | Bar proxy. **Stop run:** a high-tick-volume bar that sweeps the swing high or low. **Absorption:** a high-volume bar with a small range. | **Rough proxy.** Not the real signal. |
| You see the event in Bookmap or ATAS | Draw a rectangle named `EVT…` on the chart, optionally `EVT_BI`, `EVT_SI`, `EVT_BS` or `EVT_SS`. The EA handles everything else. | **Exact.** You supply the event. |
| Gamma levels | Draw horizontal lines named `GEX…` (from SpotGamma or MenthorQ). Set `InpGammaRegime` each day. | Manual input |
| HIRO, Bookmap price-change alerts | Not available in MT5 | Not implemented |
| NYSE/Nasdaq TICK | Set `InpTickSymbol` if your broker carries it | Optional |
| Relative volume ≥ 200% | Current 5-minute volume versus the same slot over the last 30 days | **Exact** with real volume; tick volume on CFDs |

**Bottom line:** for the real strategy, either run it on an exchange-connected futures account (event source `Ticks`), or use **manual mode**: you spot the iceberg or stop run in Bookmap, draw a box, and the EA does the ATR, entry, stop, sizing and trailing perfectly. On a CFD feed it is a *proxy* of the idea and should be tested as such.

## 4. Install

1. Copy `OrderFlowIcebergEA.mq5` to `<MT5 data folder>/MQL5/Experts/OrderFlowIcebergEA/`. Find the folder via **File → Open Data Folder**.
2. Open it in MetaEditor and press **Compile** (F7). The EA uses only the standard `Trade\Trade.mqh` library.
3. Attach it to a chart of the instrument. Any chart timeframe works; the EA reads M1 and M5 itself. Allow Algo Trading.

## 5. Settings that matter

**Session times are in broker server time.** The defaults `16:30`–`23:00` equal the NY cash session (09:30–16:00 ET) on the common GMT+2/+3 server clock. Adjust these to your broker.

Contract thresholds by market. These only matter for `Ticks` event detection.

| Market | `InpMinIcebergContracts` | `InpMinStopRunContracts` |
|---|---|---|
| ES (E-mini S&P) | 700 | 500 |
| NQ (Nasdaq) | 150 | 150 |
| CL (Crude) | 150 | 150 |
| GC (Gold) | 150 | 150 |
| Bonds (ZB) | 500 | — (not specified, set high) |

For micros (MES / MNQ), the thresholds still refer to the **E-mini** order flow. Detect events on the E-mini chart, or use manual zones, and trade the micro.

Other key inputs:

- `InpEventSource`: `Auto` uses ticks if the feed has aggressor flags, otherwise the bar proxy. `Manual` ignores automatic detection.
- `InpRequireKeyLevel`: Step 1. The event must sit within `InpKeyLevelTolATR` of VWAP, the previous day's high/low/close, or your `LVL` / `GEX` lines.
- `InpTargetMode`: `Next key level` is closest to the source. `Trail only` is the purest form of "no fixed target".
- `InpReversionMode`: off by default. If you enable it alongside position trades, use extension 2 or 3 so the two models don't fight over the same 1-ATR move.
- `InpGammaRegime = Negative` blocks reversion trades on trend days.
- Netting accounts (most futures accounts) hold at most one position or pending order at a time. Hedging accounts use `InpMaxOpenPositions`.

## 6. Testing it honestly

- In the Strategy Tester, use **"Every tick based on real ticks"**. The tick and proxy detectors need it. Tick mode needs a symbol whose history has `last` prices with buy/sell flags, meaning an exchange feed.
- Manual rectangles cannot be drawn during a backtest. Manual mode is for live and demo trading.
- **The published results in the video are claims, not evidence.** Before risking money, compare against:
  - a random-entry control (same zones and trade rate, random direction or timing);
  - per-instrument results, not only the pooled total;
  - the result with the best 5% of trades removed.
- The EA was written in a Linux environment with **no MetaEditor available**, so it has **not been compiled**. If MetaEditor reports an error, paste it back and it will be fixed.

## 7. Backtest results

Full report: [`backtest/RESULTS.md`](../../../backtest/RESULTS.md).

- **Data tested:** CME futures (NQ, ES, GC, CL) with bar-proxy events over 21 one-minute sessions and 50 five-minute sessions, plus the real tick order-flow detector on 30.9M aggressor-flagged BTC perpetual trades.
- **Result:** no robust edge over the same rules fired on random events. The 144-setting optimisation did not beat a random best-of-grid.
- **Change made:** the default `InpProxyVolMult` is now 4.0, the only change that helped in every slice, and only weakly. Everything else stays at the published rules. Reversions stay off by default.
- **Still untested:** the strategy's real signal needs CME Market-By-Order data. See "What would settle it" in the report.

## 8. Files

- `OrderFlowIcebergEA.mq5`: the Expert Advisor.
- `README.md`: this document, covering the rules, the mapping and usage.
- `../../../backtest/`: Python port of the EA logic, data fetchers, tests and the backtest report.
