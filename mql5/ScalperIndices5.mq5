//+------------------------------------------------------------------+
//|  ScalperIndices5.mq5
//|  Multi-symbol intraday scalper: 5 cash indices.
//|  Generated from mql5/templates/ScalperBasket.mq5.tmpl by
//|  scripts/make_basket_ea.py.
//|
//|  Same signal and trade-management code as ScalperXG / ScalperXAG,
//|  but ONE chart trades the whole basket with ONE shared parameter
//|  set (scale-free: ATR / R multiples, stop floor in bp of price,
//|  sessions relative to each symbol's home exchange).
//|
//|  Attach to any chart (e.g. US500 M15). The EA polls every
//|  symbol on a 1-second timer, acts once per closed signal bar, holds
//|  at most one position per symbol and InpMaxOpenPositions in total.
//|
//|  Defaults = loop-optimised parameters, see docs/RESULTS_V2.md:
//|   indices: US500, US100, US30, GER40, UK100
//|   BREAKOUT on M15, session 'cash_mid' (US 15-19 / EU 9-14 UTC)
//|   walk-forward 2023-01-04..2026-10-31 (12 monthly refits, stitched OOS):
//|     1079 trades WR 46.3% PF 1.10 +0.047R t=1.34
//|   defaults = parameters refitted on the most recent training window
//|
//|  Strategy Tester: "Every tick based on real ticks", and select all
//|  basket symbols in Market Watch first. Broker symbol names differ:
//|  edit InpSymbols / InpSymbolSuffix (e.g. "US500" vs "SPX500.cash").
//+------------------------------------------------------------------+
#property copyright "ScalperIndices5"
#property version   "1.00"
#property description "Multi-symbol scalper: 5 cash indices"

#include <Trade/Trade.mqh>

enum ENUM_SCALP_MODE
  {
   MODE_BREAKOUT = 0,   // Donchian break + trend + volatility expansion
   MODE_MOMENTUM = 1,   // net move over N bars, ER-gated
   MODE_PULLBACK = 2,   // trend continuation after a retracement
   MODE_FADE     = 3,   // mean reversion to session VWAP
   MODE_BANDS    = 4    // mean reversion to a rolling mean (Bollinger z)
  };

input group           "=== Basket ==="
input string          InpSymbols         = "US500,US100,US30,GER40,UK100";
input string          InpMarkets         = "US,US,US,EU,EU";   // US / EU per symbol (session clock)
input string          InpSymbolSuffix    = "";         // appended to every symbol, e.g. ".cash" or "#"
input int             InpMaxOpenPositions = 3;

input group           "=== Strategy ==="
input ENUM_SCALP_MODE InpMode            = MODE_BREAKOUT;
input ENUM_TIMEFRAMES InpSignalTF        = PERIOD_M15;
input int             InpUsStartUTC      = 15;   // US-market symbols: session, UTC hours
input int             InpUsEndUTC        = 19;
input int             InpEuStartUTC      = 9;   // EU-market symbols
input int             InpEuEndUTC        = 14;
input int             InpGmtOffsetHours  = -99;   // server-UTC offset; -99 = auto

input group           "=== Regime filters ==="
input int             InpAtrPeriod       = 14;
input int             InpAtrRankLookback = 288;
input double          InpAtrRankMin      = 0.1;
input double          InpAtrRankMax      = 0.99;
input int             InpErPeriod        = 24;
input double          InpErMin           = 0.45;
input double          InpErMax           = 1.0;

input group           "=== Entry (fade / bands) ==="
input int             InpBbPeriod        = 48;
input double          InpBandK           = 2.0;
input int             InpRsiPeriod       = 7;
input double          InpRsiLo           = 28.0;
input double          InpRsiHi           = 72.0;
input int             InpAdxPeriod       = 14;
input double          InpAdxMax          = 30.0;
input int             InpConfirmMode     = 2;

input group           "=== Entry (breakout / momentum / pullback) ==="
input int             InpDonPeriod       = 12;
input int             InpEmaFast         = 12;
input int             InpEmaSlow         = 48;
input double          InpAdxMin          = 12.0;
input double          InpExpansionMult   = 1.15;
input int             InpAtrAvgPeriod    = 48;
input int             InpMomPeriod       = 24;
input double          InpMomMinAtr       = 1.0;
input bool            InpMomConfirm      = true;
input int             InpPbSlopePeriod   = 30;
input double          InpPbRsiLo         = 40.0;
input double          InpPbRsiHi         = 60.0;
input double          InpPbDepthAtr      = 0.5;
input int             InpPbLookback      = 6;

input group           "=== Risk and exits ==="
input double          InpRiskPct         = 0.005;
input double          InpSlAtr           = 1.0;
input double          InpMinSlBp         = 20.0;
input double          InpTpR             = 2.0;
input double          InpBeTriggerR      = 0.0;
input double          InpBeOffsetR       = 0.1;
input double          InpPartialR        = 0.0;
input double          InpPartialFrac     = 0.5;
input double          InpTrailStartR     = 0.0;
input double          InpTrailDistR      = 1.0;
input int             InpMaxHoldMinutes  = 240;
input int             InpCooldownMinutes = 20;
input int             InpMaxTradesPerDay = 2;   // per symbol
input int             InpForceExitHour   = 19;   // UTC
input int             InpForceExitMin    = 55;

input group           "=== Execution ==="
input double          InpMaxSpreadBp     = 7.5;
input int             InpSlippagePoints  = 20;
input long            InpMagic           = 20261111;
input string          InpComment         = "ScalperIndices5";

//--- per-symbol state
CTrade   g_trade;
string   g_sym[];
bool     g_eu[];
int      h_rsi[], h_adx[], h_ema_f[], h_ema_s[];
datetime g_last_bar[], g_cooldown_until[];
int      g_trades_today[], g_day[];
double   g_entry_sl_dist[];
bool     g_partial_done[];
int      g_n = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   string syms[], mk[];
   int n = StringSplit(InpSymbols, ',', syms);
   int nm = StringSplit(InpMarkets, ',', mk);
   if(n <= 0)
      return(INIT_PARAMETERS_INCORRECT);
   g_n = n;
   ArrayResize(g_sym, n);        ArrayResize(g_eu, n);
   ArrayResize(h_rsi, n);        ArrayResize(h_adx, n);
   ArrayResize(h_ema_f, n);      ArrayResize(h_ema_s, n);
   ArrayResize(g_last_bar, n);   ArrayResize(g_cooldown_until, n);
   ArrayResize(g_trades_today, n); ArrayResize(g_day, n);
   ArrayResize(g_entry_sl_dist, n); ArrayResize(g_partial_done, n);
   for(int k = 0; k < n; k++)
     {
      string s = syms[k];
      StringTrimLeft(s); StringTrimRight(s);
      g_sym[k] = s + InpSymbolSuffix;
      string m = (k < nm) ? mk[k] : "US";
      StringTrimLeft(m); StringTrimRight(m);
      g_eu[k] = (m == "EU");
      if(!SymbolSelect(g_sym[k], true))
        {
         PrintFormat("symbol %s not available - fix InpSymbols / InpSymbolSuffix", g_sym[k]);
         return(INIT_PARAMETERS_INCORRECT);
        }
      h_rsi[k]   = iRSI(g_sym[k], InpSignalTF, InpRsiPeriod, PRICE_CLOSE);
      h_adx[k]   = iADXWilder(g_sym[k], InpSignalTF, InpAdxPeriod);
      h_ema_f[k] = iMA(g_sym[k], InpSignalTF, InpEmaFast, 0, MODE_EMA, PRICE_CLOSE);
      h_ema_s[k] = iMA(g_sym[k], InpSignalTF, InpEmaSlow, 0, MODE_EMA, PRICE_CLOSE);
      if(h_rsi[k] == INVALID_HANDLE || h_adx[k] == INVALID_HANDLE
         || h_ema_f[k] == INVALID_HANDLE || h_ema_s[k] == INVALID_HANDLE)
        {
         PrintFormat("indicator handles failed for %s: %d", g_sym[k], GetLastError());
         return(INIT_FAILED);
        }
      g_last_bar[k] = 0; g_cooldown_until[k] = 0; g_trades_today[k] = 0;
      g_day[k] = -1; g_entry_sl_dist[k] = 0.0; g_partial_done[k] = false;
     }
   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpSlippagePoints);
   EventSetTimer(1);
   PrintFormat("ScalperIndices5: %d symbols, mode=%d tf=%s risk=%.2f%%", n, (int)InpMode,
               EnumToString(InpSignalTF), InpRiskPct * 100.0);
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   for(int k = 0; k < g_n; k++)
     {
      IndicatorRelease(h_rsi[k]);   IndicatorRelease(h_adx[k]);
      IndicatorRelease(h_ema_f[k]); IndicatorRelease(h_ema_s[k]);
     }
  }

//+------------------------------------------------------------------+
int GmtOffsetSeconds()
  {
   if(InpGmtOffsetHours != -99)
      return(InpGmtOffsetHours * 3600);
   return((int)(TimeCurrent() - TimeGMT()));
  }

datetime ServerToUtc(datetime t) { return(t - GmtOffsetSeconds()); }

int UtcHour(datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return(s.hour);
  }

bool InSession(int k, datetime utc)
  {
   int h = UtcHour(utc);
   if(h == 21)
      return(false);
   int a = g_eu[k] ? InpEuStartUTC : InpUsStartUTC;
   int b = g_eu[k] ? InpEuEndUTC : InpUsEndUTC;
   return(h >= a && h < b);
  }

bool PastForceExit(datetime utc)
  {
   MqlDateTime s;
   TimeToStruct(utc, s);
   return(s.hour > InpForceExitHour || (s.hour == InpForceExitHour && s.min >= InpForceExitMin));
  }

double ValuePerPoint(string sym)
  {
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tv <= 0.0)
      tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double pt = SymbolInfoDouble(sym, SYMBOL_POINT);
   if(ts <= 0.0)
      return(0.0);
   return(tv * (pt / ts));
  }

double NormaliseLots(string sym, double lots)
  {
   double mn = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double mx = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   double st = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   if(st <= 0.0)
      st = 0.01;
   lots = MathFloor(lots / st + 1e-9) * st;
   if(lots < mn)
      return(0.0);                 // cannot size this risk: skip rather than over-risk
   if(lots > mx)
      lots = mx;
   int dg = (int)MathMax(0, MathCeil(-MathLog10(st) - 1e-9));
   return(NormalizeDouble(lots, dg));
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
int Signal(int k, double &atr_out, double &close_out)
  {
   string sym = g_sym[k];
   int need = InpAtrRankLookback + InpAtrPeriod + 200;
   need = (int)MathMax(need, InpEmaSlow * 4 + 50);
   need = (int)MathMax(need, InpBbPeriod + InpErPeriod + InpMomPeriod + InpDonPeriod + 50);

   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(sym, InpSignalTF, 1, need, r) < need)
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
   int kk = 64;
   int ks = (int)MathMax(kk, InpPbSlopePeriod + 2);
   if(CopyBuffer(h_rsi[k], 0, 1, kk, rsi)    < kk) return(0);
   if(CopyBuffer(h_adx[k], 0, 1, kk, adx)    < kk) return(0);
   if(CopyBuffer(h_ema_f[k], 0, 1, kk, emaf) < kk) return(0);
   if(CopyBuffer(h_ema_s[k], 0, 1, ks, emas) < ks) return(0);

   WilderAtr(high, low, close, InpAtrPeriod, atr);
   atr_out = atr[0];
   close_out = close[0];
   if(atr_out <= 0.0)
      return(0);
   double rank = AtrRank(atr, InpAtrRankLookback);
   if(rank < InpAtrRankMin || rank > InpAtrRankMax)
      return(0);
   if(InpErMin > 0.0 || InpErMax < 1.0)
     {
      double er = EfficiencyRatio(close, 0, InpErPeriod);
      if(er < InpErMin || er > InpErMax)
         return(0);
     }

   if(InpMode == MODE_BANDS || InpMode == MODE_FADE)
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
      double rng = MathMax(high[0] - low[0], SymbolInfoDouble(sym, SYMBOL_POINT));
      if(InpConfirmMode == 0)      { if(dn_now) return(+1); if(up_now) return(-1); }
      else if(InpConfirmMode == 1) { if(dn_now && close[0] >= low[0] + 0.5 * rng) return(+1);
                                     if(up_now && close[0] <= high[0] - 0.5 * rng) return(-1); }
      else if(InpConfirmMode == 2) { if(dn_prev && close[0] > close[1]) return(+1);
                                     if(up_prev && close[0] < close[1]) return(-1); }
      else                         { if(dn_prev && close[0] > high[1]) return(+1);
                                     if(up_prev && close[0] < low[1]) return(-1); }
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
      if(up && (emaf[0] - swing_lo) >= InpPbDepthAtr * atr[0] && rsi[1] <= InpPbRsiLo && close[0] > high[1]) return(+1);
      if(dn && (swing_hi - emaf[0]) >= InpPbDepthAtr * atr[0] && rsi[1] >= InpPbRsiHi && close[0] < low[1]) return(-1);
      return(0);
     }
   return(0);
  }

//+------------------------------------------------------------------+
bool SelectOwnPosition(string sym)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return(true);
     }
   return(false);
  }

int OwnPositionsTotal()
  {
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t != 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         c++;
     }
   return(c);
  }

void ManageOpenPosition(int k)
  {
   string sym = g_sym[k];
   if(!SelectOwnPosition(sym))
      return;
   long   type   = PositionGetInteger(POSITION_TYPE);
   double open   = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl     = PositionGetDouble(POSITION_SL);
   double tp     = PositionGetDouble(POSITION_TP);
   double vol    = PositionGetDouble(POSITION_VOLUME);
   ulong  ticket = PositionGetInteger(POSITION_TICKET);
   datetime opened = (datetime)PositionGetInteger(POSITION_TIME);
   int    digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double pt     = SymbolInfoDouble(sym, SYMBOL_POINT);

   int dir = (type == POSITION_TYPE_BUY) ? +1 : -1;
   double price = (dir > 0) ? SymbolInfoDouble(sym, SYMBOL_BID) : SymbolInfoDouble(sym, SYMBOL_ASK);
   if(g_entry_sl_dist[k] <= 0.0)
      g_entry_sl_dist[k] = MathAbs(open - sl);
   if(g_entry_sl_dist[k] <= 0.0)
      return;
   double one_r = g_entry_sl_dist[k];
   double run_r = dir * (price - open) / one_r;

   if(InpMaxHoldMinutes > 0 && (TimeCurrent() - opened) >= InpMaxHoldMinutes * 60)
     { g_trade.PositionClose(ticket); return; }
   if(PastForceExit(ServerToUtc(TimeCurrent())))
     { g_trade.PositionClose(ticket); return; }

   if(InpPartialR > 0.0 && !g_partial_done[k] && run_r >= InpPartialR)
     {
      double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
      double part = MathFloor(vol * InpPartialFrac / step + 1e-9) * step;
      double mn   = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
      g_partial_done[k] = true;
      if(part >= mn && part < vol && g_trade.PositionClosePartial(ticket, part))
        {
         double be = open + dir * InpBeOffsetR * one_r;
         if((dir > 0 && be > sl) || (dir < 0 && be < sl))
            g_trade.PositionModify(ticket, NormalizeDouble(be, digits), tp);
        }
      return;
     }
   double new_sl = sl;
   if(InpBeTriggerR > 0.0 && run_r >= InpBeTriggerR)
     {
      double be = open + dir * InpBeOffsetR * one_r;
      if((dir > 0 && be > new_sl) || (dir < 0 && be < new_sl))
         new_sl = be;
     }
   if(InpTrailStartR > 0.0 && run_r >= InpTrailStartR)
     {
      double trail = price - dir * InpTrailDistR * one_r;
      if((dir > 0 && trail > new_sl) || (dir < 0 && trail < new_sl))
         new_sl = trail;
     }
   if(MathAbs(new_sl - sl) > pt * 0.5)
      g_trade.PositionModify(ticket, NormalizeDouble(new_sl, digits), tp);
  }

void TryEntry(int k)
  {
   string sym = g_sym[k];
   datetime utc = ServerToUtc(TimeCurrent());
   datetime sig_open = iTime(sym, InpSignalTF, 1);
   if(sig_open == 0 || !InSession(k, ServerToUtc(sig_open)) || PastForceExit(utc))
      return;
   if(g_trades_today[k] >= InpMaxTradesPerDay || TimeCurrent() < g_cooldown_until[k])
      return;
   if(OwnPositionsTotal() >= InpMaxOpenPositions)
      return;
   if(!SymbolInfoInteger(sym, SYMBOL_TRADE_MODE) || SymbolInfoInteger(sym, SYMBOL_TRADE_MODE) == SYMBOL_TRADE_MODE_DISABLED)
      return;
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   if(bid <= 0.0 || (ask - bid) / bid * 1e4 > InpMaxSpreadBp)
      return;

   double atr = 0.0, last_close = 0.0;
   int dir = Signal(k, atr, last_close);
   if(dir == 0)
      return;
   double pt = SymbolInfoDouble(sym, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   double sl_dist = MathMax(InpSlAtr * atr, InpMinSlBp * 1e-4 * last_close);
   double vpp = ValuePerPoint(sym);
   if(vpp <= 0.0 || sl_dist <= 0.0)
      return;
   long stops_level = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   if(stops_level > 0 && sl_dist < stops_level * pt)
      return;
   double lots = NormaliseLots(sym, AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPct / ((sl_dist / pt) * vpp));
   if(lots <= 0.0)
      return;
   double entry = (dir > 0) ? ask : bid;
   double sl = NormalizeDouble((dir > 0) ? entry - sl_dist : entry + sl_dist, digits);
   double tp = (InpTpR > 0.0) ? NormalizeDouble((dir > 0) ? entry + InpTpR * sl_dist
                                                          : entry - InpTpR * sl_dist, digits) : 0.0;
   g_trade.SetTypeFillingBySymbol(sym);
   bool ok = (dir > 0) ? g_trade.Buy(lots, sym, 0.0, sl, tp, InpComment)
                       : g_trade.Sell(lots, sym, 0.0, sl, tp, InpComment);
   if(ok && (g_trade.ResultRetcode() == TRADE_RETCODE_DONE || g_trade.ResultRetcode() == TRADE_RETCODE_PLACED))
     {
      g_trades_today[k]++;
      g_entry_sl_dist[k] = sl_dist;
      g_partial_done[k] = false;
     }
   else
      PrintFormat("%s entry rejected: %d %s", sym, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
  }

void Step()
  {
   int day = (int)((ServerToUtc(TimeCurrent()) + 3 * 3600) / 86400);
   for(int k = 0; k < g_n; k++)
     {
      if(day != g_day[k])
        { g_day[k] = day; g_trades_today[k] = 0; }
      ManageOpenPosition(k);
      datetime bt = iTime(g_sym[k], InpSignalTF, 0);
      if(bt == 0 || bt == g_last_bar[k])
         continue;
      g_last_bar[k] = bt;
      if(SelectOwnPosition(g_sym[k]))
         continue;
      TryEntry(k);
     }
  }

void OnTimer() { Step(); }
void OnTick()  { Step(); }

void OnTradeTransaction(const MqlTradeTransaction &trans, const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || !HistoryDealSelect(trans.deal))
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != InpMagic
      || HistoryDealGetInteger(trans.deal, DEAL_ENTRY) != DEAL_ENTRY_OUT)
      return;
   string sym = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   for(int k = 0; k < g_n; k++)
      if(g_sym[k] == sym)
        {
         if(SelectOwnPosition(sym))
            return;                    // partial close
         g_cooldown_until[k] = TimeCurrent() + InpCooldownMinutes * 60;
         g_entry_sl_dist[k] = 0.0;
         g_partial_done[k] = false;
        }
  }
//+------------------------------------------------------------------+
