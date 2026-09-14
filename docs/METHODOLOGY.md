# Methodology

This document explains what the backtester does and, more usefully, the
assumptions that would make its numbers wrong.

## 1. The cost model is the strategy

Before any indicator, the arithmetic that decides whether short-horizon trading
is possible at all:

```
round-trip friction = spread + commission + entry slippage + stop slippage
```

| | EURUSD | XAUUSD |
|---|---|---|
| Typical spread (London/NY) | 0.4 pip (4 pts) | USD 0.18 (18 pts) |
| Commission (USD 7 / lot round turn) | 0.7 pip (7 pts) | USD 0.07 (7 pts) |
| Entry slippage | 0.15 pip | USD 0.06 |
| Extra slippage on a stop exit | 0.30 pip | USD 0.14 |
| **Total (stopped-out trade)** | **1.55 pip (15.5 pts)** | **USD 0.45 (45 pts)** |

Expressed as a fraction of the risked amount, friction is
`cost / stop_distance`:

| Stop distance | EURUSD drag | | Stop distance | XAUUSD drag |
|---|---|---|---|---|
| 5 pips | **31% of R** | | USD 1.00 | **45% of R** |
| 10 pips | 15.5% of R | | USD 2.50 | 18% of R |
| 15 pips | 10.3% of R | | USD 4.00 | 11% of R |
| 25 pips | 6.2% of R | | USD 7.00 | 6.4% of R |

**This kills textbook micro-scalping.** With a 5-pip stop on EURUSD you start
every trade 0.31R in the hole; at a 1:1 target you need a 57% strike rate just
to break even, before any edge. That is why `MIN_SL_POINTS` in `spaces.py`
starts at 8 pips for EURUSD and USD 2.00 for gold, and why the strategies that
survive hold positions for tens of minutes rather than seconds.

It also explains the ranking between the two instruments. What matters is not
the spread but the spread *relative to how far price moves*:

| | friction | ATR(M5) | friction / ATR(M5) |
|---|---|---|---|
| EURUSD | 1.55 pip | ~2.9 pip | **0.53** |
| XAUUSD | USD 0.45 | ~USD 1.56 | **0.29** |

Gold's wider spread is more than paid for by its volatility. EURUSD's famously
tight spread is not an advantage once you divide by how little it moves.

## 2. Execution assumptions

Every one of these is chosen to make the backtest pessimistic, because the
failure mode of a backtest is always optimism.

| Assumption | Choice | Why |
|---|---|---|
| Price series | bars are **bid**; longs fill at ask, exit on bid | matches MT5, charges the spread exactly once per round trip |
| Stop vs target in one bar | **stop wins** | OHLC cannot reveal the intrabar path; assuming the good one is the commonest way to inflate a curve |
| Gaps | fill at the **open**, not at the stop level | a gap through your stop does not fill at your stop |
| Entry slippage | always adverse | market orders do not slip in your favour |
| Stop slippage | extra, on top of entry slippage | stops fill into a thinning book |
| Limit exits (target, partial) | **no** slippage | a resting limit fills at its price or not at all |
| Trailing stop | advanced only *after* exits are checked | a trail cannot rescue the bar that set it |
| Swap | charged at each 21:00 UTC rollover, tripled Wednesday | |
| Rollover hour | never traded | spreads blow out |
| Position count | one at a time | no pyramiding to smooth the curve |

## 3. The look-ahead barrier

A signal-timeframe bar labelled `t` covers `[t, t+tf)` and is only knowable at
`t+tf`. `strategy.to_exec_signals` therefore places the signal on the execution
bar at `t+tf`, and the engine fills it at that bar's **open**. Signals stranded
by a weekend or a data hole are discarded rather than executed late.

`tests/test_engine.py::TestLookAhead` pins this down, and
`TestIndicators::test_indicators_are_causal` verifies that changing a future bar
cannot alter any past indicator value.

## 4. Why the first optimiser was thrown away

The first search covered 23 free parameters, about 10^11 combinations. Taking
the single best of 400 random draws gave, on EURUSD:

```
in-sample   PF 1.35   WR 53.3%   expectancy +0.063R
out-of-sample PF 0.66   WR 37.5%   expectancy -0.085R
```

That is not a strategy, it is the luckiest of 400 noise draws. Two changes fixed
it, and neither was a better optimiser:

1. **Fewer parameters.** Anything measurement showed was not decisive is now
   fixed rather than searched (`spaces.FIXED`). The space went from 10^11 to
   ~10^6.
2. **Robust selection instead of peak-picking.** `optimize.robust_select` splits
   the training window into thirds, scores each candidate on all three, and
   ranks by the **worst** third. A configuration has to work everywhere in the
   data it was fitted on before it is trusted anywhere else.

After both changes the in-sample/out-of-sample gap on the same instrument fell
from 0.148R to 0.019R. The strategy still did not make money on EURUSD — but
the backtester stopped lying about it, which is the prerequisite for everything
else.

## 5. What counts as a result

Only the **stitched out-of-sample curve** from `walk_forward`. Parameters are
fitted on a 365-day training window; performance is recorded on the 120 days
that follow, which the fit never saw; the window advances by 120 days so test
windows are contiguous and every out-of-sample day is used exactly once.

Supporting checks, all in the reports:

- **walk-forward efficiency** — OOS expectancy / IS expectancy. Below ~0.5 means
  the fit is not transferring.
- **bootstrap p-value** — probability of the observed mean R arising from a
  zero-edge trade distribution.
- **neighbourhood stability** — re-scores every immediate parameter neighbour. A
  peak surrounded by losses is a fitting artefact.
- **cost sensitivity** — re-runs at 1.25x, 1.5x and 2x friction. An edge that
  dies at 1.25x is a bet on your broker, not on the market.
- **Monte Carlo** — reshuffles trade order to show what luck could do to the
  drawdown path.

## 6. Known limitations

- **The headline results were produced on synthetic data** (see
  `data/README.md`). They validate the machinery, not the edge.
- Bar data cannot model true intrabar path, queue position, or requotes.
- The spread model is session- and volatility-dependent but does not reproduce
  news-event spread spikes tick by tick. Supplying MT5 exports with a real
  `spread` column replaces the model with your broker's actual spreads.
- Swap rates are static; real ones drift with rate differentials.
- No slippage asymmetry between liquid and illiquid days beyond the ATR term.
