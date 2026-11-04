//+------------------------------------------------------------------+
//|  ScalperXAG.mq5
//|  Intraday scalper for XAGUSD. Generated from
//|  mql5/templates/ScalperMetal.mq5.tmpl by scripts/make_ea.py.
//|
//|  Same engine family as ScalperXG.mq5 (the XAUUSD scalper), plus
//|  what the minor metals need:
//|   * MODE_BANDS - fade back to a ROLLING mean (Bollinger z-score),
//|     because the metals' intraday variance ratio is below 1.
//|   * stop floor and spread cap in BASIS POINTS of price, because
//|     these symbols' costs are a share of price, not fixed points.
//|
//|  Indicators match the Python backtester (Wilder ATR / RSI / ADX,
//|  population std, closed bars only), so a Strategy Tester run should
//|  agree with it to within the fill model.
//|
//|  Defaults = validated parameters, see docs/RESULTS_METALS.md:
//|   XAGUSD MOMENTUM on M5, session ny (UTC)
//|   fit 2019-2024, frozen test 2025-01..2026-10 (real OANDA M1):
//|     61 trades  WR 47.5%  PF 1.20  +0.044R  t=0.53
//|   walk-forward 2021-2026 (17 refits, stitched OOS):
//|     336 trades  WR 48.5%  PF 0.79  -0.056R  t=-1.73
//|   NOT statistically significant - not an established edge
//|   see docs/RESULTS_METALS.md
//|
//|  Test on "Every tick based on real ticks" with YOUR broker's
//|  spreads before risking money. In the Strategy Tester set
//|  InpGmtOffsetHours to your broker's server offset (e.g. 2 or 3).
//+------------------------------------------------------------------+
#property copyright "ScalperXAG"
#property version   "1.00"
#property description "Intraday scalper for XAGUSD (signal TF M5)"

#include <Trade/Trade.mqh>

enum ENUM_SCALP_MODE
  {
   MODE_BREAKOUT = 0,   // Donchian break + trend + volatility expansion
   MODE_MOMENTUM = 1,   // net move over N bars, ER-gated
   MODE_PULLBACK = 2,   // trend continuation after a retracement
   MODE_FADE     = 3,   // mean reversion to session VWAP
   MODE_BANDS    = 4    // mean reversion to a rolling mean (Bollinger z)
  };

input group           "=== Strategy ==="
input ENUM_SCALP_MODE InpMode            = MODE_MOMENTUM;
input ENUM_TIMEFRAMES InpSignalTF        = PERIOD_M5;   // signal timeframe (chosen M1..M30)
input int             InpSessionStartUTC = 12;         // inclusive, UTC hour
input int             InpSessionEndUTC   = 18;         // exclusive, UTC hour
input int             InpGmtOffsetHours  = -99;        // server-UTC offset; -99 = auto (TimeCurrent-TimeGMT)

input group           "=== Regime filters ==="
input int             InpAtrPeriod       = 14;
input int             InpAtrRankLookback = 288;
input double          InpAtrRankMin      = 0.1;
input double          InpAtrRankMax      = 0.99;
input int             InpErPeriod        = 24;
input double          InpErMin           = 0.6;        // 0 disables
input double          InpErMax           = 1.0;        // <1 demands chop (fades)

input group           "=== Entry (fade / bands) ==="
input int             InpBbPeriod        = 48;       // bands: rolling-mean window
input double          InpBandK           = 2.0;      // entry at K sigmas from the mean
input int             InpRsiPeriod       = 7;
input double          InpRsiLo           = 28.0;
input double          InpRsiHi           = 72.0;
input int             InpAdxPeriod       = 14;
input double          InpAdxMax          = 30.0;      // 100 = off
input int             InpConfirmMode     = 2;        // 0 none 1 rejection 2 turn 3 strong turn

input group           "=== Entry (breakout / momentum / pullback) ==="
input int             InpDonPeriod       = 24;
input int             InpEmaFast         = 12;
input int             InpEmaSlow         = 48;
input double          InpAdxMin          = 20.0;
input double          InpExpansionMult   = 1.15;
input int             InpAtrAvgPeriod    = 48;
input int             InpMomPeriod       = 12;
input double          InpMomMinAtr       = 3.5;
input bool            InpMomConfirm      = true;
input int             InpPbSlopePeriod   = 30;
input double          InpPbRsiLo         = 40.0;
input double          InpPbRsiHi         = 60.0;
input double          InpPbDepthAtr      = 0.5;
input int             InpPbLookback      = 6;

input group           "=== Risk and exits ==="
input double          InpRiskPct         = 0.005;  // fraction of equity per trade
input double          InpSlAtr           = 2.0;    // stop = InpSlAtr * ATR(signal TF)
input double          InpMinSlBp         = 192.0;   // stop floor, basis points of price
input double          InpTpR             = 1.5;    // target = InpTpR * stop
input double          InpBeTriggerR      = 0.0;    // 0 disables breakeven
input double          InpBeOffsetR       = 0.1;
input double          InpPartialR        = 0.0;    // 0 disables partial close
input double          InpPartialFrac     = 0.5;
input double          InpTrailStartR     = 1.0;    // 0 disables trailing
input double          InpTrailDistR      = 1.0;
input int             InpMaxHoldMinutes  = 240;
input int             InpCooldownMinutes = 240;
input int             InpMaxTradesPerDay = 2;
input double          InpDailyLossLimitR = 0.0;    // 0 = off (as in the backtest)
input int             InpForceExitHour   = 20;     // UTC
input int             InpForceExitMin    = 45;

input group           "=== Execution ==="
input double          InpMaxSpreadBp     = 33.3;   // skip entries above this spread (bp of price)
input int             InpSlippagePoints  = 16;
input bool            InpCheckSymbol     = true;   // refuse to run on a different symbol
input long            InpMagic           = 20261103;
input string          InpComment         = "ScalperXAG";

//--- globals
CTrade   g_trade;
int      h_rsi = INVALID_HANDLE, h_adx = INVALID_HANDLE;
int      h_ema_f = INVALID_HANDLE, h_ema_s = INVALID_HANDLE;
datetime g_last_bar_time = 0;
datetime g_cooldown_until = 0;
int      g_trades_today = 0;
double   g_day_r = 0.0;
int      g_current_day = -1;
bool     g_day_blocked = false;
double   g_entry_sl_dist = 0.0;
bool     g_partial_done = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpCheckSymbol && StringFind(_Symbol, "XAGUSD") < 0)
     {
      PrintFormat("ScalperXAG was optimised for XAGUSD; chart symbol is %s. "
                  "Set InpCheckSymbol=false to override.", _Symbol);
      return(INIT_PARAMETERS_INCORRECT);
     }
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   h_rsi   = iRSI(_Symbol, InpSignalTF, InpRsiPeriod, PRICE_CLOSE);      // Wilder, as in Python
   h_adx   = iADXWilder(_Symbol, InpSignalTF, InpAdxPeriod);             // Wilder ADX, as in Python
   h_ema_f = iMA(_Symbol, InpSignalTF, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
   h_ema_s = iMA(_Symbol, InpSignalTF, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
   if(h_rsi == INVALID_HANDLE || h_adx == INVALID_HANDLE
      || h_ema_f == INVALID_HANDLE || h_ema_s == INVALID_HANDLE)
     {
      Print("indicator handle creation failed: ", GetLastError());
      return(INIT_FAILED);
     }
   PrintFormat("ScalperXAG on %s  mode=%d  tf=%s  risk=%.2f%%  stop floor=%.0fbp",
               _Symbol, (int)InpMode, EnumToString(InpSignalTF), InpRiskPct * 100.0, InpMinSlBp);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   IndicatorRelease(h_rsi);   IndicatorRelease(h_adx);
   IndicatorRelease(h_ema_f); IndicatorRelease(h_ema_s);
  }

//+------------------------------------------------------------------+
//| helpers                                                          |
//+------------------------------------------------------------------+
double ValuePerPoint()
  {
   double tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tv <= 0.0)
      tv = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(ts <= 0.0)
      return(0.0);
   return(tv * (_Point / ts));
  }

double NormaliseLots(double lots)
  {
   double mn = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   if(st <= 0.0)
      st = 0.01;
   lots = MathFloor(lots / st + 1e-9) * st;
   if(lots < mn)
      lots = mn;
   if(lots > mx)
      lots = mx;
   int dg = (int)MathMax(0, MathCeil(-MathLog10(st) - 1e-9));
   return(NormalizeDouble(lots, dg));
  }

int GmtOffsetSeconds()
  {
   if(InpGmtOffsetHours != -99)
      return(InpGmtOffsetHours * 3600);
   return((int)(TimeCurrent() - TimeGMT()));
  }

datetime ServerToUtc(datetime server_time) { return(server_time - GmtOffsetSeconds()); }

int UtcHour(datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return(s.hour);
  }

bool InSession(datetime utc)
  {
   int h = UtcHour(utc);
   if(h == 21)
      return(false);
   if(InpSessionStartUTC <= InpSessionEndUTC)
      return(h >= InpSessionStartUTC && h < InpSessionEndUTC);
   return(h >= InpSessionStartUTC || h < InpSessionEndUTC);
  }

bool PastForceExit(datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   return(s.hour > InpForceExitHour
          || (s.hour == InpForceExitHour && s.min >= InpForceExitMin));
  }

//--- Wilder ATR on series arrays (index 0 = most recent closed bar).
//--- Seeded with an SMA over the oldest `period` bars, exactly as the Python one.
void WilderAtr(const double &high[], const double &low[], const double &close[],
               int period, double &out[])
  {
   int n = ArraySize(close);
   ArrayResize(out, n);
   ArraySetAsSeries(out, true);
   ArrayInitialize(out, 0.0);
   if(n < period + 2)
      return;
   double acc = 0.0;
   int first = n - 2;                 // oldest bar with a previous close
   for(int k = 0; k < period; k++)
     {
      int i = first - k;
      acc += MathMax(high[i], close[i + 1]) - MathMin(low[i], close[i + 1]);
     }
   int seed = first - period + 1;
   out[seed] = acc / period;
   for(int i = seed - 1; i >= 0; i--)
     {
      double tr = MathMax(high[i], close[i + 1]) - MathMin(low[i], close[i + 1]);
      out[i] = (out[i + 1] * (period - 1) + tr) / period;
     }
  }

double EfficiencyRatio(const double &close[], int shift, int period)
  {
   if(ArraySize(close) < shift + period + 1)
      return(0.0);
   double path = 0.0;
   for(int i = shift; i < shift + period; i++)
      path += MathAbs(close[i] - close[i + 1]);
   if(path <= 0.0)
      return(0.0);
   return(MathAbs(close[shift] - close[shift + period]) / path);
  }

//--- share of the window (incl. the current bar) that the current ATR exceeds
double AtrRank(const double &atr[], int lookback)
  {
   int n = MathMin(lookback, ArraySize(atr));
   if(n < 5)
      return(0.5);
   int below = 0;
   for(int i = 0; i < n; i++)
      if(atr[i] < atr[0])
         below++;
   return((double)below / (double)n);
  }

double ArrayMean(const double &a[], int count)
  {
   int n = MathMin(count, ArraySize(a));
   if(n <= 0)
      return(0.0);
   double s = 0.0;
   for(int i = 0; i < n; i++)
      s += a[i];
   return(s / n);
  }

//--- rolling mean and population std of close over `period` bars ending at `shift`
bool RollingBand(const double &close[], int shift, int period, double &mean, double &sd)
  {
   if(ArraySize(close) < shift + period)
      return(false);
   double s = 0.0, s2 = 0.0;
   for(int i = shift; i < shift + period; i++)
     {
      s += close[i];
      s2 += close[i] * close[i];
     }
   mean = s / period;
   double v = s2 / period - mean * mean;
   sd = (v > 0.0) ? MathSqrt(v) : 0.0;
   return(sd > 0.0);
  }

//--- VWAP of the current UTC day from signal-timeframe bars, ending at `shift`
bool SessionVwap(const MqlRates &r[], int shift, double &vwap, double &sigma)
  {
   vwap = 0.0;
   sigma = 0.0;
   datetime utc0 = ServerToUtc(r[shift].time);
   int day0 = (int)(utc0 / 86400);
   double pv = 0.0, vv = 0.0, pv2 = 0.0;
   for(int i = shift; i < ArraySize(r); i++)
     {
      if((int)(ServerToUtc(r[i].time) / 86400) != day0)
         break;
      double tp = (r[i].high + r[i].low + r[i].close) / 3.0;
      double v  = (double)r[i].tick_volume;
      if(v <= 0.0)
         v = 1.0;
      pv  += tp * v;
      vv  += v;
      pv2 += tp * tp * v;
     }
   if(vv <= 0.0)
      return(false);
   vwap = pv / vv;
   double var = pv2 / vv - vwap * vwap;
   sigma = (var > 0.0) ? MathSqrt(var) : 0.0;
   return(sigma > 0.0);
  }

//+------------------------------------------------------------------+
//| signal: +1 long, -1 short, 0 nothing. CLOSED bars only.           |
//+------------------------------------------------------------------+
int Signal(double &atr_out, double &close_out)
  {
   int need = InpAtrRankLookback + InpAtrPeriod + 200;
   need = (int)MathMax(need, InpEmaSlow * 4 + 50);
   need = (int)MathMax(need, InpBbPeriod + InpErPeriod + InpMomPeriod + InpDonPeriod + 50);

   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, InpSignalTF, 1, need, r) < need)
      return(0);

   double close[], high[], low[], atr[], rsi[], adx[], emaf[], emas[];
   ArrayResize(close, need); ArrayResize(high, need); ArrayResize(low, need);
   ArraySetAsSeries(close, true); ArraySetAsSeries(high, true); ArraySetAsSeries(low, true);
   for(int i = 0; i < need; i++)
     {
      close[i] = r[i].close;
      high[i]  = r[i].high;
      low[i]   = r[i].low;
     }
   ArraySetAsSeries(rsi, true); ArraySetAsSeries(adx, true);
   ArraySetAsSeries(emaf, true); ArraySetAsSeries(emas, true);
   int k = 64;
   int ks = (int)MathMax(k, InpPbSlopePeriod + 2);
   if(CopyBuffer(h_rsi, 0, 1, k, rsi)     < k) return(0);
   if(CopyBuffer(h_adx, 0, 1, k, adx)     < k) return(0);
   if(CopyBuffer(h_ema_f, 0, 1, k, emaf)  < k) return(0);
   if(CopyBuffer(h_ema_s, 0, 1, ks, emas)  < ks) return(0);

   WilderAtr(high, low, close, InpAtrPeriod, atr);
   atr_out = atr[0];
   close_out = close[0];
   if(atr_out <= 0.0)
      return(0);

   // --- shared regime gates --------------------------------------
   double rank = AtrRank(atr, InpAtrRankLookback);
   if(rank < InpAtrRankMin || rank > InpAtrRankMax)
      return(0);
   if(InpErMin > 0.0 || InpErMax < 1.0)
     {
      double er = EfficiencyRatio(close, 0, InpErPeriod);
      if(er < InpErMin || er > InpErMax)
         return(0);
     }

   // --- mean reversion: session VWAP (FADE) or rolling mean (BANDS) --
   if(InpMode == MODE_FADE || InpMode == MODE_BANDS)
     {
      if(adx[0] > InpAdxMax)
         return(0);
      double m0 = 0.0, s0 = 0.0, m1 = 0.0, s1 = 0.0;
      if(InpMode == MODE_BANDS)
        {
         if(!RollingBand(close, 0, InpBbPeriod, m0, s0)) return(0);
         if(!RollingBand(close, 1, InpBbPeriod, m1, s1)) return(0);
        }
      else
        {
         if(!SessionVwap(r, 0, m0, s0)) return(0);
         if(!SessionVwap(r, 1, m1, s1)) { m1 = m0; s1 = s0; }
        }
      double z0 = (close[0] - m0) / s0;
      double z1 = (close[1] - m1) / s1;
      bool dn_now  = (z0 <= -InpBandK && rsi[0] <= InpRsiLo);
      bool up_now  = (z0 >=  InpBandK && rsi[0] >= InpRsiHi);
      bool dn_prev = (z1 <= -InpBandK && rsi[1] <= InpRsiLo);
      bool up_prev = (z1 >=  InpBandK && rsi[1] >= InpRsiHi);
      double rng = MathMax(high[0] - low[0], _Point);
      if(InpConfirmMode == 0)
        {
         if(dn_now) return(+1);
         if(up_now) return(-1);
        }
      else if(InpConfirmMode == 1)
        {
         if(dn_now && close[0] >= low[0] + 0.5 * rng)  return(+1);
         if(up_now && close[0] <= high[0] - 0.5 * rng) return(-1);
        }
      else if(InpConfirmMode == 2)
        {
         if(dn_prev && close[0] > close[1]) return(+1);
         if(up_prev && close[0] < close[1]) return(-1);
        }
      else
        {
         if(dn_prev && close[0] > high[1]) return(+1);
         if(up_prev && close[0] < low[1])  return(-1);
        }
      return(0);
     }

   if(InpMode == MODE_BREAKOUT)
     {
      double prior_hi = high[1], prior_lo = low[1];
      for(int i = 1; i <= InpDonPeriod; i++)
        {
         if(high[i] > prior_hi) prior_hi = high[i];
         if(low[i]  < prior_lo) prior_lo = low[i];
        }
      double atr_avg = ArrayMean(atr, InpAtrAvgPeriod);
      if(!(atr_avg > 0.0 && atr[0] / atr_avg >= InpExpansionMult) || adx[0] < InpAdxMin)
         return(0);
      if(close[0] > prior_hi && emaf[0] > emas[0]) return(+1);
      if(close[0] < prior_lo && emaf[0] < emas[0]) return(-1);
      return(0);
     }

   if(InpMode == MODE_MOMENTUM)
     {
      double net = close[0] - close[InpMomPeriod];
      if(MathAbs(net) < InpMomMinAtr * atr[0])
         return(0);
      bool up_ok = (!InpMomConfirm || close[0] > high[1]);
      bool dn_ok = (!InpMomConfirm || close[0] < low[1]);
      if(net > 0 && up_ok) return(+1);
      if(net < 0 && dn_ok) return(-1);
      return(0);
     }

   if(InpMode == MODE_PULLBACK)
     {
      if(adx[0] < InpAdxMin)
         return(0);
      double slope = emas[0] - emas[InpPbSlopePeriod];
      double swing_lo = low[0], swing_hi = high[0];
      for(int i = 0; i < InpPbLookback; i++)
        {
         if(low[i]  < swing_lo) swing_lo = low[i];
         if(high[i] > swing_hi) swing_hi = high[i];
        }
      bool up = (emaf[0] > emas[0] && slope > 0.0);
      bool dn = (emaf[0] < emas[0] && slope < 0.0);
      if(up && (emaf[0] - swing_lo) >= InpPbDepthAtr * atr[0] && rsi[1] <= InpPbRsiLo && close[0] > high[1])
         return(+1);
      if(dn && (swing_hi - emaf[0]) >= InpPbDepthAtr * atr[0] && rsi[1] >= InpPbRsiHi && close[0] < low[1])
         return(-1);
      return(0);
     }
   return(0);
  }

//+------------------------------------------------------------------+
//| position management                                              |
//+------------------------------------------------------------------+
bool SelectOwnPosition()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == _Symbol
         && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return(true);
     }
   return(false);
  }

void ManageOpenPosition()
  {
   if(!SelectOwnPosition())
      return;
   long   type   = PositionGetInteger(POSITION_TYPE);
   double open   = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl     = PositionGetDouble(POSITION_SL);
   double tp     = PositionGetDouble(POSITION_TP);
   double vol    = PositionGetDouble(POSITION_VOLUME);
   ulong  ticket = PositionGetInteger(POSITION_TICKET);
   datetime opened = (datetime)PositionGetInteger(POSITION_TIME);

   int dir = (type == POSITION_TYPE_BUY) ? +1 : -1;
   double price = (dir > 0) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                            : SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   if(g_entry_sl_dist <= 0.0)
      g_entry_sl_dist = MathAbs(open - sl);
   if(g_entry_sl_dist <= 0.0)
      return;
   double run_r = dir * (price - open) / g_entry_sl_dist;

   if(InpMaxHoldMinutes > 0 && (TimeCurrent() - opened) >= InpMaxHoldMinutes * 60)
     {
      g_trade.PositionClose(ticket);
      return;
     }
   if(PastForceExit(ServerToUtc(TimeCurrent())))
     {
      g_trade.PositionClose(ticket);
      return;
     }

   if(InpPartialR > 0.0 && !g_partial_done && run_r >= InpPartialR)
     {
      double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
      double part = MathFloor(vol * InpPartialFrac / step + 1e-9) * step;
      double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
      g_partial_done = true;            // one attempt, as in the backtest
      if(part >= mn && part < vol && g_trade.PositionClosePartial(ticket, part))
        {
         double be = open + dir * InpBeOffsetR * g_entry_sl_dist;
         if((dir > 0 && be > sl) || (dir < 0 && be < sl))
            g_trade.PositionModify(ticket, NormalizeDouble(be, _Digits), tp);
        }
      return;
     }

   double new_sl = sl;
   if(InpBeTriggerR > 0.0 && run_r >= InpBeTriggerR)
     {
      double be = open + dir * InpBeOffsetR * g_entry_sl_dist;
      if((dir > 0 && be > new_sl) || (dir < 0 && be < new_sl))
         new_sl = be;
     }
   if(InpTrailStartR > 0.0 && run_r >= InpTrailStartR)
     {
      double trail = price - dir * InpTrailDistR * g_entry_sl_dist;
      if((dir > 0 && trail > new_sl) || (dir < 0 && trail < new_sl))
         new_sl = trail;
     }
   if(MathAbs(new_sl - sl) > _Point * 0.5)
      g_trade.PositionModify(ticket, NormalizeDouble(new_sl, _Digits), tp);
  }

//+------------------------------------------------------------------+
void TryEntry()
  {
   datetime utc = ServerToUtc(TimeCurrent());
   // the session is judged on the OPEN time of the signal bar that just
   // closed, exactly as the backtester labels it
   datetime sig_open = iTime(_Symbol, InpSignalTF, 1);
   if(sig_open == 0 || !InSession(ServerToUtc(sig_open)) || PastForceExit(utc))
      return;
   if(g_day_blocked || g_trades_today >= InpMaxTradesPerDay)
      return;
   if(TimeCurrent() < g_cooldown_until)
      return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   if(bid <= 0.0)
      return;
   if((ask - bid) / bid * 1e4 > InpMaxSpreadBp)
      return;

   double atr = 0.0, last_close = 0.0;
   int dir = Signal(atr, last_close);
   if(dir == 0)
      return;

   double sl_dist = MathMax(InpSlAtr * atr, InpMinSlBp * 1e-4 * last_close);
   double vpp = ValuePerPoint();
   if(vpp <= 0.0 || sl_dist <= 0.0)
      return;
   long stops_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   if(stops_level > 0 && sl_dist < stops_level * _Point)
      return;

   double risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPct;
   double lots = NormaliseLots(risk_money / ((sl_dist / _Point) * vpp));
   double entry = (dir > 0) ? ask : bid;
   double sl = NormalizeDouble((dir > 0) ? entry - sl_dist : entry + sl_dist, _Digits);
   double tp = (InpTpR > 0.0)
               ? NormalizeDouble((dir > 0) ? entry + InpTpR * sl_dist : entry - InpTpR * sl_dist, _Digits)
               : 0.0;

   bool ok = (dir > 0) ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, InpComment)
                       : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, InpComment);
   if(ok && (g_trade.ResultRetcode() == TRADE_RETCODE_DONE || g_trade.ResultRetcode() == TRADE_RETCODE_PLACED))
     {
      g_trades_today++;
      g_entry_sl_dist = sl_dist;
      g_partial_done = false;
     }
   else
      PrintFormat("entry rejected: %d %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
  }

void ResetDailyCounters()
  {
   // trading day rolls at 21:00 UTC, matching the backtester
   datetime utc = ServerToUtc(TimeCurrent());
   int day = (int)((utc + 3 * 3600) / 86400);
   if(day != g_current_day)
     {
      g_current_day = day;
      g_trades_today = 0;
      g_day_r = 0.0;
      g_day_blocked = false;
     }
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   ResetDailyCounters();
   ManageOpenPosition();

   datetime bt = iTime(_Symbol, InpSignalTF, 0);
   if(bt == 0 || bt == g_last_bar_time)
      return;
   g_last_bar_time = bt;

   if(SelectOwnPosition())
      return;                      // one position at a time
   TryEntry();
  }

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD)
      return;
   if(!HistoryDealSelect(trans.deal))
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic)
      return;
   if(HistoryDealGetString(trans.deal, DEAL_SYMBOL) != _Symbol)
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
      return;
   double profit = HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
                 + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                 + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   double risk_money = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPct;
   if(risk_money > 0.0)
      g_day_r += profit / risk_money;
   if(InpDailyLossLimitR > 0.0 && g_day_r <= -InpDailyLossLimitR)
      g_day_blocked = true;
   if(SelectOwnPosition())
      return;                      // partial close: position still open
   g_cooldown_until = TimeCurrent() + InpCooldownMinutes * 60;
   g_entry_sl_dist = 0.0;
   g_partial_done = false;
  }
//+------------------------------------------------------------------+
