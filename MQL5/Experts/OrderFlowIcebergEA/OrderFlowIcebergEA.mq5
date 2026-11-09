//+------------------------------------------------------------------+
//|                                          OrderFlowIcebergEA.mq5  |
//|                                                                  |
//|  MT5 implementation of the "Institutional Order Flow & Iceberg"  |
//|  futures strategy (Scott Pulcini, Chart Fanatics video           |
//|  https://www.youtube.com/watch?v=wym1NAroAuQ).                   |
//|                                                                  |
//|  Core mechanics (from the source):                               |
//|   - A significant iceberg / stop-run EVENT marks an event zone.   |
//|   - 5-minute Wilder's ATR measures movement away from the zone.  |
//|   - POSITION TRADE: price moves 1.0 ATR beyond the zone ->        |
//|     enter at 1.15 ATR beyond it, stop 1.15 ATR beyond the        |
//|     opposite side. No breakeven; trail stop on NEW events.       |
//|   - REVERSION TRADE: fade a 1/2/3 ATR extension back to the zone |
//|     (Aggressive, Back-in-Black, A+ Reversion).                   |
//|   - Filters: key price areas, gamma regime, program activity     |
//|     (relative volume / TICK), daily loss limit.                  |
//|                                                                  |
//|  See MQL5/Experts/OrderFlowIcebergEA/README.md for the rule map,  |
//|  what is exact, what is approximated and what MT5 cannot see.    |
//+------------------------------------------------------------------+
#property copyright   "TestRep1"
#property version     "1.00"
#property description "Event-zone order-flow strategy: iceberg / stop-run events, 5m Wilder ATR,"
#property description "1.0 ATR confirmation, 1.15 ATR entry & stop, ATR-extension reversions."

#include <Trade\Trade.mqh>

//--- enums ----------------------------------------------------------
enum ENUM_OF_SOURCE
  {
   OF_SOURCE_AUTO   = 0, // Auto: tick order flow if available, else bar proxy
   OF_SOURCE_TICKS  = 1, // Tick order flow (exchange futures, real ticks)
   OF_SOURCE_PROXY  = 2, // Bar proxy (CFD / forex, tick volume)
   OF_SOURCE_MANUAL = 3  // Manual zones only (rectangles you draw)
  };

enum ENUM_OF_KIND
  {
   KIND_MANUAL       = 0,
   KIND_BUY_ICEBERG  = 1,
   KIND_SELL_ICEBERG = 2,
   KIND_BUY_STOPS    = 3,
   KIND_SELL_STOPS   = 4
  };

enum ENUM_REV_MODE
  {
   REV_NONE          = 0, // Off
   REV_AGGRESSIVE    = 1, // Aggressive reversion (ATR extension only)
   REV_BACK_IN_BLACK = 2, // Back in Black (extension + key level / Bollinger)
   REV_A_PLUS        = 3  // A+ Reversion (extension at a previous event zone)
  };

enum ENUM_TGT_MODE
  {
   TGT_TRAIL_ONLY = 0, // No fixed target (exit by stop / trailing / session end)
   TGT_R_MULTIPLE = 1, // Fixed R multiple
   TGT_NEXT_LEVEL = 2  // Next key level (fallback: R multiple)
  };

enum ENUM_REV_TARGET
  {
   REVT_NEAR_EDGE = 0, // Near edge of the event zone
   REVT_MID       = 1, // Middle of the event zone
   REVT_FAR_EDGE  = 2  // Far edge of the event zone
  };

enum ENUM_GAMMA
  {
   GAMMA_UNKNOWN  = 0, // Unknown (no restriction)
   GAMMA_POSITIVE = 1, // Positive gamma (range-bound day)
   GAMMA_NEGATIVE = 2  // Negative gamma (trend day: no reversions)
  };

enum ENUM_RISK_MODE
  {
   RISK_PERCENT    = 0, // % of equity per trade
   RISK_MONEY      = 1, // Fixed money per trade
   RISK_FIXED_LOTS = 2  // Fixed lots / contracts
  };

//--- inputs ---------------------------------------------------------
input group "=== Event detection ==="
input ENUM_OF_SOURCE InpEventSource          = OF_SOURCE_AUTO; // Event source
input bool           InpReadManualZones      = true;    // Also read manual rectangles
input string         InpManualPrefix         = "EVT";   // Manual zone rectangle name prefix
input double         InpMinIcebergContracts  = 150;     // Min iceberg size (ES 700, NQ/CL/GC 150, bonds 500)
input double         InpMinStopRunContracts  = 150;     // Min stop-run size (ES 500, NQ/CL/GC 150)
input int            InpAbsorbWindowSec      = 60;      // Iceberg: window to accumulate volume at one price (s)
input int            InpAbsorbMaxThroughTicks= 1;       // Iceberg: max ticks price may trade through the level
input int            InpStopRunWindowSec     = 3;       // Stop run: burst window (s)
input int            InpSwingBars            = 20;      // Stop run / sweep: swing lookback (bars)
input int            InpZonePadTicks         = 2;       // Ticks added around a single-price event
input ENUM_TIMEFRAMES InpProxyTF             = PERIOD_M1; // Bar proxy: timeframe
input double         InpProxyVolMult         = 3.0;     // Bar proxy: volume >= mult x average
input int            InpProxyAvgBars         = 30;      // Bar proxy: average volume lookback
input double         InpProxyAbsorbMaxRangeATR = 0.35;  // Bar proxy: absorption bar max range (x ATR)
input int            InpZoneLifetimeMin      = 240;     // Event zone lifetime (minutes)
input int            InpDedupeMinutes        = 15;      // Ignore overlapping same-kind events within (min)
input int            InpMaxZones             = 40;      // Max zones kept in memory

input group "=== ATR (5-minute Wilder's) ==="
input ENUM_TIMEFRAMES InpATRTimeframe        = PERIOD_M5; // ATR timeframe
input int            InpATRPeriod            = 14;      // ATR period (Wilder smoothing)
input double         InpConfirmATR           = 1.00;    // Direction confirmation (x ATR beyond zone)
input double         InpEntryATR             = 1.15;    // Position entry (x ATR beyond zone)
input double         InpStopATR              = 1.15;    // Position stop (x ATR beyond opposite side)

input group "=== Step 1: important price areas ==="
input bool           InpRequireKeyLevel      = true;    // Position trades need an event at a key level
input double         InpKeyLevelTolATR       = 0.25;    // Key level tolerance (x ATR)
input bool           InpUseVWAP              = true;    // Session VWAP
input bool           InpUsePrevDay           = true;    // Previous day high / low / close
input bool           InpUseManualLevels      = true;    // Horizontal lines you draw
input string         InpLevelPrefix          = "LVL";   // Key level horizontal-line prefix
input string         InpGammaPrefix          = "GEX";   // Gamma level horizontal-line prefix

input group "=== Model 1: position trade ==="
input bool           InpEnablePosition       = true;    // Enable position trades
input bool           InpAllowBothDirections  = true;    // Allow both sides per zone (Broken Ice)
input int            InpPendingExpiryMin     = 30;      // Cancel unfilled entry after (min, 0 = never)
input bool           InpCancelIfBackInZone   = true;    // Cancel unfilled entry if price re-enters zone
input double         InpMaxChaseATR          = 0.10;    // Max distance past entry to still fill at market (x ATR)
input ENUM_TGT_MODE  InpTargetMode           = TGT_NEXT_LEVEL; // Profit target
input double         InpTargetR              = 3.0;     // R multiple (target / fallback)
input double         InpMinTargetR           = 1.0;     // Next-level target must be >= this many R
input bool           InpTrailOnNewEvents     = true;    // Trail stop to 1.15 ATR beyond new confirmed events
input double         InpPartialAtR           = 0.0;     // Partial profit at R (0 = off)
input double         InpPartialPercent       = 50.0;    // Partial size (% of position)
input bool           InpMoveToBreakeven      = false;   // Breakeven (source says NO; off by default)
input double         InpBreakevenR           = 1.0;     // Breakeven trigger (R)

input group "=== Model 2: reversion trade ==="
input ENUM_REV_MODE  InpReversionMode        = REV_NONE; // Reversion entry method
input int            InpRevExtension         = 2;       // ATR extension to fade (1, 2 or 3)
input double         InpRevStopATR           = 0.50;    // Stop beyond the extension (x ATR) [not in source]
input ENUM_REV_TARGET InpRevTarget           = REVT_NEAR_EDGE; // Reversion target inside the zone
input bool           InpRevSkipIfConfirmed   = true;    // Do not fade a side where a position trade was taken
input bool           InpBiBUseBollinger      = true;    // Back in Black: Bollinger bands count as levels
input int            InpBBPeriod             = 20;      // Bollinger period (on ATR timeframe)
input double         InpBBDeviation          = 2.0;     // Bollinger deviation
input int            InpAPlusBufferTicks     = 4;       // A+: stop ticks outside the previous zone
input int            InpAPlusLookbackMin     = 480;     // A+: previous zones considered (minutes)

input group "=== Market condition filters ==="
input ENUM_GAMMA     InpGammaRegime          = GAMMA_UNKNOWN; // Today's gamma regime (from SpotGamma/MenthorQ)
input bool           InpUseRVolFilter        = true;    // Block fading program activity (relative volume)
input int            InpRVolDays             = 30;      // Relative volume lookback (days)
input double         InpRVolThreshold        = 2.0;     // Relative volume threshold (2.0 = 200%)
input string         InpTickSymbol           = "";      // NYSE/Nasdaq TICK symbol, if your broker has one
input double         InpTickExtreme          = 1000;    // TICK extreme level
input int            InpTickSustainBars      = 3;       // TICK must stay extreme for N M1 bars

input group "=== Risk ==="
input ENUM_RISK_MODE InpRiskMode             = RISK_PERCENT; // Position sizing
input double         InpRiskPercent          = 0.5;     // Risk % of equity per trade
input double         InpRiskMoney            = 100.0;   // Risk money per trade
input double         InpFixedLots            = 1.0;     // Fixed lots / contracts
input double         InpMaxLots              = 0.0;     // Max lots (0 = broker max)
input double         InpDailyLossPercent     = 2.0;     // Daily loss limit % of equity (0 = off)
input double         InpDailyLossMoney       = 0.0;     // Daily loss limit money (0 = off)
input bool           InpCloseOnDailyLimit    = true;    // Flatten when the daily limit is hit
input int            InpMaxTradesPerDay      = 6;       // Max entries per session
input int            InpMaxOpenPositions     = 2;       // Max open positions + pendings (hedging accounts)
input int            InpMaxSpreadPoints      = 0;       // Max spread in points (0 = off)

input group "=== Session (server time) ==="
input string         InpSessionStart         = "16:30"; // Session start HH:MM (server time)
input string         InpSessionEnd           = "23:00"; // Session end HH:MM (server time)
input bool           InpFlatAtSessionEnd     = true;    // Close everything at session end
input bool           InpResetZonesEachSession= true;    // Forget zones at a new session

input group "=== Misc ==="
input long           InpMagic                = 26110901; // Magic number
input int            InpSlippagePoints       = 20;      // Max deviation (points)
input bool           InpDraw                 = true;    // Draw zones and ATR levels
input bool           InpShowPanel            = true;    // Show status panel
input bool           InpVerbose              = true;    // Log decisions

//--- types ----------------------------------------------------------
struct EventZone
  {
   int      id;
   int      kind;
   datetime t;
   double   lo;
   double   hi;
   double   atr;
   bool     keyOK;
   bool     active;
   bool     longConf;
   bool     shortConf;
   bool     longDone;
   bool     shortDone;
   bool     revUpDone;
   bool     revDnDone;
   bool     longTraded;   // a position trade was actually placed on this side
   bool     shortTraded;
   ulong    longTicket;
   ulong    shortTicket;
   datetime longPlaced;
   datetime shortPlaced;
   string   src;
  };

struct LevelAcc
  {
   double price;
   long   startMsc;
   double buyVol;
   double sellVol;
   double minPx;
   double maxPx;
   bool   fired;
  };

//--- globals --------------------------------------------------------
CTrade    g_trade;
EventZone g_zones[];
LevelAcc  g_acc[];
int       g_nextZoneId = 1;

double    g_tickSize = 0.0;
double    g_point    = 0.0;
int       g_digits   = 0;
bool      g_netting  = false;
bool      g_useTicks = false;
bool      g_useProxy = false;
int       g_startSec = 0;
int       g_endSec   = 0;

double    g_atr      = 0.0;
double    g_vwap     = 0.0;
double    g_bbUpper  = 0.0;
double    g_bbLower  = 0.0;
int       g_bbHandle = INVALID_HANDLE;
double    g_levels[];
double    g_swingHi  = 0.0;
double    g_swingLo  = 0.0;
double    g_rvol     = 0.0;
int       g_programDir = 0;   // +1 program buying, -1 program selling

long      g_lastTickMsc = 0;
int       g_lastMscCount = 0;     // ticks already processed at g_lastTickMsc
long      g_bufMsc[];
double    g_bufPx[];
double    g_bufVol[];
int       g_bufSide[];
long      g_lastStopRunMsc = 0;

datetime  g_sessionStart   = 0;
double    g_dayStartEquity = 0.0;
bool      g_halted         = false;
datetime  g_lastM1         = 0;
datetime  g_lastATRBar     = 0;
datetime  g_lastProxyBar   = 0;
datetime  g_lastScan       = 0;
ulong     g_partialDone[];

//+------------------------------------------------------------------+
//| Helpers                                                          |
//+------------------------------------------------------------------+
void Log(const string msg)
  {
   if(InpVerbose)
      Print("[OFIceberg] ", msg);
  }

int ParseHHMM(const string s)
  {
   string parts[];
   if(StringSplit(s, (ushort)':', parts) < 2)
      return -1;
   int h = (int)StringToInteger(parts[0]);
   int m = (int)StringToInteger(parts[1]);
   if(h < 0 || h > 23 || m < 0 || m > 59)
      return -1;
   return h * 3600 + m * 60;
  }

datetime DayStart(const datetime t)
  {
   return (datetime)(t - (t % 86400));
  }

datetime SessionStartFor(const datetime now)
  {
   datetime s = DayStart(now) + g_startSec;
   if(now < s)
      s -= 86400;
   return s;
  }

int SessionLength()
  {
   int len = g_endSec - g_startSec;
   if(len <= 0)
      len += 86400;
   return len;
  }

bool InSession(const datetime now)
  {
   return (now - SessionStartFor(now)) < SessionLength();
  }

double RoundToTick(const double p)
  {
   if(g_tickSize <= 0.0)
      return NormalizeDouble(p, g_digits);
   return NormalizeDouble(MathRound(p / g_tickSize) * g_tickSize, g_digits);
  }

double BarVolume(const ENUM_TIMEFRAMES tf, const int shift)
  {
   long rv[];
   if(CopyRealVolume(_Symbol, tf, shift, 1, rv) == 1 && rv[0] > 0)
      return (double)rv[0];
   return (double)iVolume(_Symbol, tf, shift);
  }

double RatesVolume(const MqlRates &r)
  {
   if(r.real_volume > 0)
      return (double)r.real_volume;
   return (double)r.tick_volume;
  }

string KindName(const int kind)
  {
   switch(kind)
     {
      case KIND_BUY_ICEBERG:  return "BuyIceberg";
      case KIND_SELL_ICEBERG: return "SellIceberg";
      case KIND_BUY_STOPS:    return "BuyStops";
      case KIND_SELL_STOPS:   return "SellStops";
     }
   return "Manual";
  }

//+------------------------------------------------------------------+
//| 5-minute Wilder's ATR (MT5's built-in iATR uses a simple average)|
//+------------------------------------------------------------------+
double TrueRange(const MqlRates &r[], const int i)
  {
   double pc = r[i - 1].close;
   return MathMax(r[i].high, pc) - MathMin(r[i].low, pc);
  }

double ComputeWilderATR()
  {
   int need = InpATRPeriod * 10 + 2;
   MqlRates r[];
   ArraySetAsSeries(r, false);
   int got = CopyRates(_Symbol, InpATRTimeframe, 1, need, r);   // closed bars, oldest first
   if(got < InpATRPeriod + 2)
      return 0.0;
   double atr = 0.0;
   for(int i = 1; i <= InpATRPeriod; i++)
      atr += TrueRange(r, i);
   atr /= InpATRPeriod;
   for(int i = InpATRPeriod + 1; i < got; i++)
      atr = (atr * (InpATRPeriod - 1) + TrueRange(r, i)) / InpATRPeriod;
   return atr;
  }

//+------------------------------------------------------------------+
//| Key levels (Step 1: important price areas)                       |
//+------------------------------------------------------------------+
void AddLevel(const double p)
  {
   if(p <= 0.0)
      return;
   int n = ArraySize(g_levels);
   ArrayResize(g_levels, n + 1);
   g_levels[n] = p;
  }

double ComputeSessionVWAP()
  {
   MqlRates r[];
   int n = CopyRates(_Symbol, PERIOD_M1, g_sessionStart, TimeCurrent(), r);
   if(n <= 0)
      return 0.0;
   double pv = 0.0, v = 0.0;
   for(int i = 0; i < n; i++)
     {
      double vol = RatesVolume(r[i]);
      pv += (r[i].high + r[i].low + r[i].close) / 3.0 * vol;
      v  += vol;
     }
   return (v > 0.0) ? pv / v : 0.0;
  }

void RefreshKeyLevels()
  {
   ArrayResize(g_levels, 0);
   if(InpUseVWAP)
     {
      g_vwap = ComputeSessionVWAP();
      AddLevel(g_vwap);
     }
   if(InpUsePrevDay)
     {
      AddLevel(iHigh(_Symbol, PERIOD_D1, 1));
      AddLevel(iLow(_Symbol, PERIOD_D1, 1));
      AddLevel(iClose(_Symbol, PERIOD_D1, 1));
     }
   if(InpUseManualLevels)
     {
      int total = ObjectsTotal(0, 0, OBJ_HLINE);
      for(int k = 0; k < total; k++)
        {
         string nm = ObjectName(0, k, 0, OBJ_HLINE);
         if(StringFind(nm, InpLevelPrefix) == 0 || StringFind(nm, InpGammaPrefix) == 0)
            AddLevel(ObjectGetDouble(0, nm, OBJPROP_PRICE, 0));
        }
     }
  }

void RefreshBollinger()
  {
   if(g_bbHandle == INVALID_HANDLE)
      return;
   double b[];
   if(CopyBuffer(g_bbHandle, 1, 0, 1, b) == 1)
      g_bbUpper = b[0];
   if(CopyBuffer(g_bbHandle, 2, 0, 1, b) == 1)
      g_bbLower = b[0];
  }

// distance from the nearest key level to the [lo, hi] range (0 if inside)
double NearestLevelDistance(const double lo, const double hi)
  {
   double best = DBL_MAX;
   for(int i = 0; i < ArraySize(g_levels); i++)
     {
      double l = g_levels[i];
      double d = 0.0;
      if(l > hi)
         d = l - hi;
      else
         if(l < lo)
            d = lo - l;
      if(d < best)
         best = d;
     }
   return best;
  }

bool AlignedWithLevel(const double price, const double tol)
  {
   if(NearestLevelDistance(price, price) <= tol)
      return true;
   if(InpBiBUseBollinger)
     {
      if(g_bbUpper > 0.0 && MathAbs(g_bbUpper - price) <= tol)
         return true;
      if(g_bbLower > 0.0 && MathAbs(g_bbLower - price) <= tol)
         return true;
     }
   return false;
  }

double NextLevelTarget(const int dir, const double entry, const double minDist)
  {
   double best = 0.0;
   for(int i = 0; i < ArraySize(g_levels); i++)
     {
      double l = g_levels[i];
      if(dir > 0 && l >= entry + minDist && (best == 0.0 || l < best))
         best = l;
      if(dir < 0 && l <= entry - minDist && (best == 0.0 || l > best))
         best = l;
     }
   return best;
  }

//+------------------------------------------------------------------+
//| Program buying / selling (relative volume, optional TICK)         |
//+------------------------------------------------------------------+
void UpdateProgramActivity()
  {
   g_programDir = 0;
   g_rvol = 0.0;
   if(InpUseRVolFilter)
     {
      datetime t1 = iTime(_Symbol, PERIOD_M5, 1);
      double v1 = BarVolume(PERIOD_M5, 1);
      double sum = 0.0;
      int cnt = 0;
      for(int d = 1; d <= InpRVolDays + 20 && cnt < InpRVolDays; d++)
        {
         int sh = iBarShift(_Symbol, PERIOD_M5, (datetime)(t1 - d * 86400), true);
         if(sh < 0)
            continue;
         sum += BarVolume(PERIOD_M5, sh);
         cnt++;
        }
      if(cnt > 0 && sum > 0.0)
         g_rvol = v1 / (sum / cnt);
      if(g_rvol >= InpRVolThreshold)
        {
         double o = iOpen(_Symbol, PERIOD_M5, 1);
         double c = iClose(_Symbol, PERIOD_M5, 1);
         if(c > o)
            g_programDir = 1;
         else
            if(c < o)
               g_programDir = -1;
        }
     }
   if(InpTickSymbol != "" && InpTickSustainBars > 0)
     {
      bool allHigh = true, allLow = true;
      for(int i = 1; i <= InpTickSustainBars; i++)
        {
         double c = iClose(InpTickSymbol, PERIOD_M1, i);
         if(c == 0.0)
           {
            allHigh = false;
            allLow = false;
            break;
           }
         if(c < InpTickExtreme)
            allHigh = false;
         if(c > -InpTickExtreme)
            allLow = false;
        }
      if(allHigh)
         g_programDir = 1;
      if(allLow)
         g_programDir = -1;
     }
  }

// reversion entries must not fade sustained program activity / trend days
bool AllowReversion(const int dir)
  {
   if(InpGammaRegime == GAMMA_NEGATIVE)
      return false;
   if(dir > 0 && g_programDir < 0)
      return false;
   if(dir < 0 && g_programDir > 0)
      return false;
   return true;
  }

//+------------------------------------------------------------------+
//| Drawing                                                          |
//+------------------------------------------------------------------+
void DrawSeg(const string name, const datetime t1, const datetime t2, const double p,
             const color c, const ENUM_LINE_STYLE st)
  {
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, p, t2, p);
   ObjectSetInteger(0, name, OBJPROP_COLOR, c);
   ObjectSetInteger(0, name, OBJPROP_STYLE, st);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_BACK, true);
  }

void DrawZone(const int i)
  {
   if(!InpDraw)
      return;
   string base = "OFZ_" + IntegerToString(g_zones[i].id);
   datetime t1 = g_zones[i].t;
   datetime t2 = t1 + InpZoneLifetimeMin * 60;
   double lo = g_zones[i].lo, hi = g_zones[i].hi, a = g_zones[i].atr;
   color c = clrSilver;
   if(g_zones[i].keyOK || !InpRequireKeyLevel)
     {
      switch(g_zones[i].kind)
        {
         case KIND_BUY_ICEBERG:  c = clrDodgerBlue;  break;
         case KIND_SELL_ICEBERG: c = clrOrangeRed;   break;
         case KIND_BUY_STOPS:    c = clrMediumSeaGreen; break;
         case KIND_SELL_STOPS:   c = clrMagenta;     break;
         default:                c = clrGold;        break;
        }
     }
   string rn = base + "_zone";
   if(ObjectFind(0, rn) < 0)
      ObjectCreate(0, rn, OBJ_RECTANGLE, 0, t1, hi, t2, lo);
   ObjectSetInteger(0, rn, OBJPROP_COLOR, c);
   ObjectSetInteger(0, rn, OBJPROP_FILL, true);
   ObjectSetInteger(0, rn, OBJPROP_BACK, true);
   ObjectSetInteger(0, rn, OBJPROP_SELECTABLE, false);
   ObjectSetString(0, rn, OBJPROP_TOOLTIP, KindName(g_zones[i].kind) + " #" + IntegerToString(g_zones[i].id));

   DrawSeg(base + "_c+",  t1, t2, hi + InpConfirmATR * a, c, STYLE_DOT);
   DrawSeg(base + "_c-",  t1, t2, lo - InpConfirmATR * a, c, STYLE_DOT);
   DrawSeg(base + "_e+",  t1, t2, hi + InpEntryATR * a, c, STYLE_DASH);
   DrawSeg(base + "_e-",  t1, t2, lo - InpEntryATR * a, c, STYLE_DASH);
   if(InpReversionMode != REV_NONE)
     {
      DrawSeg(base + "_x2+", t1, t2, hi + 2.0 * a, clrGray, STYLE_DOT);
      DrawSeg(base + "_x2-", t1, t2, lo - 2.0 * a, clrGray, STYLE_DOT);
      DrawSeg(base + "_x3+", t1, t2, hi + 3.0 * a, clrGray, STYLE_DOT);
      DrawSeg(base + "_x3-", t1, t2, lo - 3.0 * a, clrGray, STYLE_DOT);
     }
  }

//+------------------------------------------------------------------+
//| Zone management                                                  |
//+------------------------------------------------------------------+
bool ZoneExistsBySrc(const string src)
  {
   for(int i = 0; i < ArraySize(g_zones); i++)
      if(g_zones[i].src == src)
         return true;
   return false;
  }

void RemoveZone(const int idx)
  {
   int n = ArraySize(g_zones);
   if(idx < 0 || idx >= n)
      return;
   if(g_zones[idx].longTicket > 0 && OrderSelect(g_zones[idx].longTicket))
      g_trade.OrderDelete(g_zones[idx].longTicket);
   if(g_zones[idx].shortTicket > 0 && OrderSelect(g_zones[idx].shortTicket))
      g_trade.OrderDelete(g_zones[idx].shortTicket);
   for(int i = idx; i < n - 1; i++)
      g_zones[i] = g_zones[i + 1];
   ArrayResize(g_zones, n - 1);
  }

int AddZone(double lo, double hi, const int kind, const datetime t, const string src)
  {
   if(g_atr <= 0.0)
      return -1;
   if(hi < lo)
     {
      double tmp = hi;
      hi = lo;
      lo = tmp;
     }
   if(kind != KIND_MANUAL)
     {
      for(int i = 0; i < ArraySize(g_zones); i++)
        {
         if(!g_zones[i].active || g_zones[i].kind != kind)
            continue;
         if(lo <= g_zones[i].hi && hi >= g_zones[i].lo && t - g_zones[i].t < InpDedupeMinutes * 60)
            return -1;
        }
     }
   // keep memory bounded: drop the oldest inactive zone first, else the oldest
   while(ArraySize(g_zones) >= MathMax(InpMaxZones, 2))
     {
      int drop = 0;
      for(int i = 0; i < ArraySize(g_zones); i++)
         if(!g_zones[i].active)
           {
            drop = i;
            break;
           }
      RemoveZone(drop);
     }
   int n = ArraySize(g_zones);
   ArrayResize(g_zones, n + 1);
   g_zones[n].id          = g_nextZoneId++;
   g_zones[n].kind        = kind;
   g_zones[n].t           = t;
   g_zones[n].lo          = RoundToTick(lo);
   g_zones[n].hi          = RoundToTick(hi);
   g_zones[n].atr         = g_atr;
   g_zones[n].keyOK       = NearestLevelDistance(lo, hi) <= InpKeyLevelTolATR * g_atr;
   g_zones[n].active      = true;
   g_zones[n].longConf    = false;
   g_zones[n].shortConf   = false;
   g_zones[n].longDone    = false;
   g_zones[n].shortDone   = false;
   g_zones[n].revUpDone   = false;
   g_zones[n].revDnDone   = false;
   g_zones[n].longTraded  = false;
   g_zones[n].shortTraded = false;
   g_zones[n].longTicket  = 0;
   g_zones[n].shortTicket = 0;
   g_zones[n].longPlaced  = 0;
   g_zones[n].shortPlaced = 0;
   g_zones[n].src         = src;
   Log(StringFormat("Event #%d %s zone %.5f-%.5f ATR=%.5f keyLevel=%s",
                    g_zones[n].id, KindName(kind), g_zones[n].lo, g_zones[n].hi, g_atr,
                    g_zones[n].keyOK ? "yes" : "no"));
   DrawZone(n);
   return n;
  }

void ExpireZone(const int i)
  {
   g_zones[i].active = false;
   if(g_zones[i].longTicket > 0 && OrderSelect(g_zones[i].longTicket))
      g_trade.OrderDelete(g_zones[i].longTicket);
   if(g_zones[i].shortTicket > 0 && OrderSelect(g_zones[i].shortTicket))
      g_trade.OrderDelete(g_zones[i].shortTicket);
   g_zones[i].longTicket = 0;
   g_zones[i].shortTicket = 0;
  }

//+------------------------------------------------------------------+
//| Event detection 1: manual rectangles                             |
//+------------------------------------------------------------------+
void ScanManualZones()
  {
   datetime now = TimeCurrent();
   int total = ObjectsTotal(0, 0, OBJ_RECTANGLE);
   for(int k = 0; k < total; k++)
     {
      string nm = ObjectName(0, k, 0, OBJ_RECTANGLE);
      if(StringFind(nm, InpManualPrefix) != 0 || ZoneExistsBySrc(nm))
         continue;
      double p1 = ObjectGetDouble(0, nm, OBJPROP_PRICE, 0);
      double p2 = ObjectGetDouble(0, nm, OBJPROP_PRICE, 1);
      datetime t1 = (datetime)ObjectGetInteger(0, nm, OBJPROP_TIME, 0);
      datetime t2 = (datetime)ObjectGetInteger(0, nm, OBJPROP_TIME, 1);
      datetime tLate = (t1 > t2) ? t1 : t2;
      if(now - tLate > InpZoneLifetimeMin * 60)
         continue;   // too old to trade
      int kind = KIND_MANUAL;
      if(StringFind(nm, "BI") > 0)
         kind = KIND_BUY_ICEBERG;
      else
         if(StringFind(nm, "SI") > 0)
            kind = KIND_SELL_ICEBERG;
         else
            if(StringFind(nm, "BS") > 0)
               kind = KIND_BUY_STOPS;
            else
               if(StringFind(nm, "SS") > 0)
                  kind = KIND_SELL_STOPS;
      int z = AddZone(MathMin(p1, p2), MathMax(p1, p2), KIND_MANUAL, now, nm);
      if(z >= 0)
        {
         g_zones[z].kind = kind;
         g_zones[z].keyOK = true;   // you chose the area yourself (Step 1 is your call)
         DrawZone(z);
        }
     }
  }

//+------------------------------------------------------------------+
//| Event detection 2: tick order flow (exchange instruments)        |
//|  - Iceberg / absorption: >= N contracts traded aggressively into |
//|    one price inside the window while price does not trade        |
//|    through it (hidden size refilled = iceberg behaviour).         |
//|  - Stop run: burst of >= N aggressive contracts in a few seconds |
//|    that takes out the recent swing high / low.                   |
//+------------------------------------------------------------------+
void BufferPush(const long msc, const double px, const double vol, const int side)
  {
   int n = ArraySize(g_bufMsc);
   ArrayResize(g_bufMsc, n + 1);
   ArrayResize(g_bufPx, n + 1);
   ArrayResize(g_bufVol, n + 1);
   ArrayResize(g_bufSide, n + 1);
   g_bufMsc[n] = msc;
   g_bufPx[n] = px;
   g_bufVol[n] = vol;
   g_bufSide[n] = side;
  }

void BufferEvict(const long minMsc)
  {
   int n = ArraySize(g_bufMsc);
   int k = 0;
   while(k < n && g_bufMsc[k] < minMsc)
      k++;
   if(k == 0)
      return;
   int m = n - k;
   for(int i = 0; i < m; i++)
     {
      g_bufMsc[i] = g_bufMsc[i + k];
      g_bufPx[i] = g_bufPx[i + k];
      g_bufVol[i] = g_bufVol[i + k];
      g_bufSide[i] = g_bufSide[i + k];
     }
   ArrayResize(g_bufMsc, m);
   ArrayResize(g_bufPx, m);
   ArrayResize(g_bufVol, m);
   ArrayResize(g_bufSide, m);
  }

void CheckStopRun(const long msc)
  {
   if(msc - g_lastStopRunMsc < (long)InpStopRunWindowSec * 1000)
      return;
   double buyVol = 0.0, sellVol = 0.0;
   double buyMin = DBL_MAX, buyMax = 0.0, sellMin = DBL_MAX, sellMax = 0.0;
   for(int i = 0; i < ArraySize(g_bufMsc); i++)
     {
      if(g_bufSide[i] > 0)
        {
         buyVol += g_bufVol[i];
         buyMin = MathMin(buyMin, g_bufPx[i]);
         buyMax = MathMax(buyMax, g_bufPx[i]);
        }
      else
        {
         sellVol += g_bufVol[i];
         sellMin = MathMin(sellMin, g_bufPx[i]);
         sellMax = MathMax(sellMax, g_bufPx[i]);
        }
     }
   datetime now = TimeCurrent();
   if(g_swingHi > 0.0 && buyVol >= InpMinStopRunContracts && buyMax > g_swingHi)
     {
      AddZone(buyMin, buyMax, KIND_BUY_STOPS, now, "ticks");
      g_lastStopRunMsc = msc;
     }
   else
      if(g_swingLo > 0.0 && sellVol >= InpMinStopRunContracts && sellMin < g_swingLo)
        {
         AddZone(sellMin, sellMax, KIND_SELL_STOPS, now, "ticks");
         g_lastStopRunMsc = msc;
        }
  }

void OnTradeTick(const long msc, const double px, const double vol, const int side)
  {
   // stop-run burst buffer
   BufferPush(msc, px, vol, side);
   BufferEvict(msc - (long)InpStopRunWindowSec * 1000);
   CheckStopRun(msc);

   // per-price absorption accumulators
   long minStart = msc - (long)InpAbsorbWindowSec * 1000;
   int n = ArraySize(g_acc);
   int w = 0;
   for(int i = 0; i < n; i++)   // evict old accumulators in place
     {
      if(g_acc[i].startMsc < minStart)
         continue;
      if(w != i)
         g_acc[w] = g_acc[i];
      w++;
     }
   if(w != n)
      ArrayResize(g_acc, w);
   n = w;

   int found = -1;
   double half = (g_tickSize > 0.0 ? g_tickSize : g_point) * 0.5;
   for(int i = 0; i < n; i++)
     {
      g_acc[i].minPx = MathMin(g_acc[i].minPx, px);
      g_acc[i].maxPx = MathMax(g_acc[i].maxPx, px);
      if(MathAbs(g_acc[i].price - px) < half)
         found = i;
     }
   if(found < 0)
     {
      ArrayResize(g_acc, n + 1);
      found = n;
      g_acc[found].price    = px;
      g_acc[found].startMsc = msc;
      g_acc[found].buyVol   = 0.0;
      g_acc[found].sellVol  = 0.0;
      g_acc[found].minPx    = px;
      g_acc[found].maxPx    = px;
      g_acc[found].fired    = false;
     }
   if(side > 0)
      g_acc[found].buyVol += vol;
   else
      g_acc[found].sellVol += vol;

   if(g_acc[found].fired)
      return;
   double ts = (g_tickSize > 0.0 ? g_tickSize : g_point);
   double through = InpAbsorbMaxThroughTicks * ts;
   double pad = InpZonePadTicks * ts;
   double lvl = g_acc[found].price;
   datetime now = TimeCurrent();
   // buy iceberg: aggressive sellers hit one price, price does not break below it
   if(g_acc[found].sellVol >= InpMinIcebergContracts && g_acc[found].minPx >= lvl - through - half)
     {
      g_acc[found].fired = true;
      AddZone(lvl - pad, lvl + pad, KIND_BUY_ICEBERG, now, "ticks");
     }
   else
      // sell iceberg: aggressive buyers lift one price, price does not break above it
      if(g_acc[found].buyVol >= InpMinIcebergContracts && g_acc[found].maxPx <= lvl + through + half)
        {
         g_acc[found].fired = true;
         AddZone(lvl - pad, lvl + pad, KIND_SELL_ICEBERG, now, "ticks");
        }
  }

void ProcessTicks()
  {
   MqlTick ticks[];
   // request from the last processed millisecond and skip what was already seen,
   // so several trades printed in the same millisecond are not lost
   int n = CopyTicks(_Symbol, ticks, COPY_TICKS_TRADE, (ulong)g_lastTickMsc, 5000);
   if(n <= 0)
      return;
   int skip = 0;
   while(skip < n && skip < g_lastMscCount && ticks[skip].time_msc == g_lastTickMsc)
      skip++;
   for(int i = skip; i < n; i++)
     {
      if(ticks[i].time_msc == g_lastTickMsc)
         g_lastMscCount++;
      else
        {
         g_lastTickMsc = ticks[i].time_msc;
         g_lastMscCount = 1;
        }
      double px = ticks[i].last;
      if(px <= 0.0)
         continue;
      int side = 0;
      if((ticks[i].flags & TICK_FLAG_BUY) == TICK_FLAG_BUY)
         side = 1;
      else
         if((ticks[i].flags & TICK_FLAG_SELL) == TICK_FLAG_SELL)
            side = -1;
      if(side == 0)
         continue;
      if(!g_useTicks && InpEventSource == OF_SOURCE_AUTO)
        {
         g_useTicks = true;
         g_useProxy = false;
         Log("Aggressor-flagged trade ticks found: using tick order-flow detection.");
        }
      if(!g_useTicks)
         return;
      double vol = (ticks[i].volume_real > 0.0) ? ticks[i].volume_real : (double)ticks[i].volume;
      OnTradeTick(ticks[i].time_msc, px, vol, side);
     }
  }

//+------------------------------------------------------------------+
//| Event detection 3: bar proxy (no exchange order flow available)  |
//|  - Stop run proxy: high-volume bar that sweeps the swing high/low |
//|  - Absorption proxy: high-volume bar with a small range          |
//+------------------------------------------------------------------+
void ProcessProxyBar()
  {
   int need = MathMax(InpProxyAvgBars, InpSwingBars) + 2;
   MqlRates r[];
   ArraySetAsSeries(r, true);
   if(CopyRates(_Symbol, InpProxyTF, 1, need, r) < need)
      return;
   double vol0 = RatesVolume(r[0]);
   double avg = 0.0;
   for(int i = 1; i <= InpProxyAvgBars; i++)
      avg += RatesVolume(r[i]);
   avg /= InpProxyAvgBars;
   if(avg <= 0.0 || vol0 < InpProxyVolMult * avg)
      return;
   double swHi = r[1].high, swLo = r[1].low;
   for(int i = 1; i <= InpSwingBars; i++)
     {
      swHi = MathMax(swHi, r[i].high);
      swLo = MathMin(swLo, r[i].low);
     }
   datetime t = TimeCurrent();
   bool sweptHi = r[0].high > swHi;
   bool sweptLo = r[0].low < swLo;
   double mid = (r[0].high + r[0].low) * 0.5;
   if(sweptHi && sweptLo)
     {
      AddZone(r[0].low, r[0].high, (r[0].close < mid) ? KIND_BUY_STOPS : KIND_SELL_STOPS, t, "proxy");
      return;
     }
   if(sweptHi)
     {
      AddZone(swHi, r[0].high, KIND_BUY_STOPS, t, "proxy");
      return;
     }
   if(sweptLo)
     {
      AddZone(r[0].low, swLo, KIND_SELL_STOPS, t, "proxy");
      return;
     }
   if(g_atr > 0.0 && (r[0].high - r[0].low) <= InpProxyAbsorbMaxRangeATR * g_atr)
      AddZone(r[0].low, r[0].high, (r[0].close >= r[0].open) ? KIND_BUY_ICEBERG : KIND_SELL_ICEBERG, t, "proxy");
  }

//+------------------------------------------------------------------+
//| Trading helpers                                                  |
//+------------------------------------------------------------------+
bool IsOwnPositionSelected()
  {
   return PositionGetString(POSITION_SYMBOL) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic;
  }

int CountOwnExposure()
  {
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk > 0 && IsOwnPositionSelected())
         c++;
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk > 0 && OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == InpMagic)
         c++;
     }
   return c;
  }

int TradesThisSession()
  {
   if(!HistorySelect(g_sessionStart, TimeCurrent() + 60))
      return 0;
   int c = 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0)
         continue;
      if(HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol || HistoryDealGetInteger(d, DEAL_MAGIC) != InpMagic)
         continue;
      if(HistoryDealGetInteger(d, DEAL_ENTRY) == DEAL_ENTRY_IN)
         c++;
     }
   return c;
  }

bool CanOpenNew()
  {
   datetime now = TimeCurrent();
   if(g_halted)
      return false;
   if(!InSession(now))
      return false;
   if(InpMaxSpreadPoints > 0 && SymbolInfoInteger(_Symbol, SYMBOL_SPREAD) > InpMaxSpreadPoints)
      return false;
   int maxExp = g_netting ? 1 : MathMax(InpMaxOpenPositions, 1);
   if(CountOwnExposure() >= maxExp)
      return false;
   if(InpMaxTradesPerDay > 0 && TradesThisSession() >= InpMaxTradesPerDay)
      return false;
   return true;
  }

double CalcLots(const int dir, const double entry, const double sl)
  {
   double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double mn   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double mx   = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0.0)
      step = mn;
   double lots = 0.0;
   if(InpRiskMode == RISK_FIXED_LOTS)
      lots = InpFixedLots;
   else
     {
      double riskMoney = (InpRiskMode == RISK_PERCENT)
                         ? AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPercent / 100.0
                         : InpRiskMoney;
      double pl = 0.0;
      ENUM_ORDER_TYPE ot = (dir > 0) ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      if(!OrderCalcProfit(ot, _Symbol, 1.0, entry, sl, pl) || pl >= 0.0)
         return 0.0;
      lots = riskMoney / (-pl);
     }
   lots = MathFloor(lots / step + 1e-9) * step;
   if(InpMaxLots > 0.0)
      lots = MathMin(lots, InpMaxLots);
   lots = MathMin(lots, mx);
   if(lots < mn)
      return 0.0;
   int vd = 0;
   double s = step;
   while(s < 1.0 - 1e-9 && vd < 8)
     {
      s *= 10.0;
      vd++;
     }
   return NormalizeDouble(lots, vd);
  }

bool RetcodeOK()
  {
   uint rc = g_trade.ResultRetcode();
   return rc == TRADE_RETCODE_DONE || rc == TRADE_RETCODE_PLACED || rc == TRADE_RETCODE_DONE_PARTIAL;
  }

string MakeComment(const string tag, const int zoneId, const double entry, const double sl)
  {
   long riskPts = (long)MathRound(MathAbs(entry - sl) / g_point);
   return StringFormat("%s|%d|%I64d", tag, zoneId, riskPts);
  }

// returns risk in price units parsed from our comment, 0 if not ours
double CommentRisk(const string cmt, string &tag)
  {
   string parts[];
   if(StringSplit(cmt, (ushort)'|', parts) < 3)
      return 0.0;
   tag = parts[0];
   return (double)StringToInteger(parts[2]) * g_point;
  }

double PositionTarget(const int dir, const double entry, const double risk)
  {
   if(InpTargetMode == TGT_TRAIL_ONLY)
      return 0.0;
   double rTarget = entry + dir * InpTargetR * risk;
   if(InpTargetMode == TGT_NEXT_LEVEL)
     {
      double lvl = NextLevelTarget(dir, entry, InpMinTargetR * risk);
      if(lvl > 0.0)
         return RoundToTick(lvl);
     }
   return RoundToTick(rTarget);
  }

//+------------------------------------------------------------------+
//| Model 1: position trade                                          |
//+------------------------------------------------------------------+
void TryPositionTrade(const int i, const int dir)
  {
   if(dir > 0 && g_zones[i].longDone)
      return;
   if(dir < 0 && g_zones[i].shortDone)
      return;
   if(dir > 0)
      g_zones[i].longDone = true;
   else
      g_zones[i].shortDone = true;

   if(!InpEnablePosition)
      return;
   if(InpRequireKeyLevel && !g_zones[i].keyOK)
     {
      Log(StringFormat("Zone #%d confirmed %s but is not at a key level: skipped.",
                       g_zones[i].id, dir > 0 ? "long" : "short"));
      return;
     }
   if(!CanOpenNew())
     {
      Log(StringFormat("Zone #%d confirmed but trading is blocked (session/limits/exposure).", g_zones[i].id));
      return;
     }

   double a = g_zones[i].atr;
   double entry, sl;
   if(dir > 0)
     {
      entry = RoundToTick(g_zones[i].hi + InpEntryATR * a);
      sl    = RoundToTick(g_zones[i].lo - InpStopATR * a);
     }
   else
     {
      entry = RoundToTick(g_zones[i].lo - InpEntryATR * a);
      sl    = RoundToTick(g_zones[i].hi + InpStopATR * a);
     }
   double risk = MathAbs(entry - sl);
   double tp = PositionTarget(dir, entry, risk);
   double lots = CalcLots(dir, entry, sl);
   if(lots <= 0.0)
     {
      Log(StringFormat("Zone #%d: position size below broker minimum for the risk setting.", g_zones[i].id));
      return;
     }
   string cmt = MakeComment("P", g_zones[i].id, entry, sl);

   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double stopsLvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
   double chase = InpMaxChaseATR * a;
   bool attempted = false;
   bool sent = false;
   bool pending = false;
   if(dir > 0)
     {
      if(entry > tk.ask + stopsLvl)
        {
         attempted = true;
         pending = true;
         sent = g_trade.BuyStop(lots, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, cmt);
        }
      else
         if(tk.ask - entry <= chase)
           {
            attempted = true;
            sent = g_trade.Buy(lots, _Symbol, 0.0, sl, tp, cmt);
           }
     }
   else
     {
      if(entry < tk.bid - stopsLvl)
        {
         attempted = true;
         pending = true;
         sent = g_trade.SellStop(lots, entry, _Symbol, sl, tp, ORDER_TIME_GTC, 0, cmt);
        }
      else
         if(entry - tk.bid <= chase)
           {
            attempted = true;
            sent = g_trade.Sell(lots, _Symbol, 0.0, sl, tp, cmt);
           }
     }
   if(!attempted)
     {
      Log(StringFormat("Zone #%d: price already beyond entry + chase, setup missed.", g_zones[i].id));
      return;
     }
   if(!sent || !RetcodeOK())
     {
      Log(StringFormat("Zone #%d: order failed, retcode %u (%s)", g_zones[i].id,
                       g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription()));
      return;
     }
   if(pending)
     {
      if(dir > 0)
        {
         g_zones[i].longTicket = g_trade.ResultOrder();
         g_zones[i].longPlaced = TimeCurrent();
        }
      else
        {
         g_zones[i].shortTicket = g_trade.ResultOrder();
         g_zones[i].shortPlaced = TimeCurrent();
        }
     }
   if(dir > 0)
      g_zones[i].longTraded = true;
   else
      g_zones[i].shortTraded = true;
   Log(StringFormat("Position trade %s zone #%d: %s entry %.5f SL %.5f TP %.5f lots %.2f",
                    dir > 0 ? "LONG" : "SHORT", g_zones[i].id, pending ? "stop order" : "market",
                    entry, sl, tp, lots));
  }

// Step 8: trail stops using new confirmed events (never on profit alone)
void TrailOnEvent(const int zi, const int dir)
  {
   double a = g_zones[zi].atr;
   double newSL = (dir > 0) ? RoundToTick(g_zones[zi].lo - InpStopATR * a)
                            : RoundToTick(g_zones[zi].hi + InpStopATR * a);
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double stopsLvl = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * g_point;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tkt = PositionGetTicket(i);
      if(tkt == 0 || !IsOwnPositionSelected())
         continue;
      string tag = "";
      if(CommentRisk(PositionGetString(POSITION_COMMENT), tag) <= 0.0 || tag != "P")
         continue;
      if((datetime)PositionGetInteger(POSITION_TIME) >= g_zones[zi].t)
         continue;   // only events that appear after entry
      long type = PositionGetInteger(POSITION_TYPE);
      double curSL = PositionGetDouble(POSITION_SL);
      double curTP = PositionGetDouble(POSITION_TP);
      if(dir > 0 && type == POSITION_TYPE_BUY && newSL > curSL + g_tickSize && newSL < tk.bid - stopsLvl)
        {
         if(g_trade.PositionModify(tkt, newSL, curTP))
            Log(StringFormat("Trailed LONG #%I64u stop to %.5f on new event #%d", tkt, newSL, g_zones[zi].id));
        }
      if(dir < 0 && type == POSITION_TYPE_SELL && (curSL == 0.0 || newSL < curSL - g_tickSize) && newSL > tk.ask + stopsLvl)
        {
         if(g_trade.PositionModify(tkt, newSL, curTP))
            Log(StringFormat("Trailed SHORT #%I64u stop to %.5f on new event #%d", tkt, newSL, g_zones[zi].id));
        }
     }
  }

void OnZoneConfirmed(const int i, const int dir)
  {
   Log(StringFormat("Zone #%d: %s confirmed (1 ATR beyond zone).", g_zones[i].id, dir > 0 ? "bullish" : "bearish"));
   if(InpTrailOnNewEvents)
      TrailOnEvent(i, dir);
   TryPositionTrade(i, dir);
  }

void ManagePending(const int i, const double px, const datetime now)
  {
   if(g_zones[i].longTicket > 0)
     {
      if(!OrderSelect(g_zones[i].longTicket))
         g_zones[i].longTicket = 0;   // filled or removed
      else
        {
         bool expired = InpPendingExpiryMin > 0 && now - g_zones[i].longPlaced > InpPendingExpiryMin * 60;
         bool back = InpCancelIfBackInZone && px <= g_zones[i].hi;
         if(expired || back)
           {
            g_trade.OrderDelete(g_zones[i].longTicket);
            g_zones[i].longTicket = 0;
            Log(StringFormat("Zone #%d: long entry cancelled (%s).", g_zones[i].id, expired ? "expired" : "back in zone"));
           }
        }
     }
   if(g_zones[i].shortTicket > 0)
     {
      if(!OrderSelect(g_zones[i].shortTicket))
         g_zones[i].shortTicket = 0;
      else
        {
         bool expired = InpPendingExpiryMin > 0 && now - g_zones[i].shortPlaced > InpPendingExpiryMin * 60;
         bool back = InpCancelIfBackInZone && px >= g_zones[i].lo;
         if(expired || back)
           {
            g_trade.OrderDelete(g_zones[i].shortTicket);
            g_zones[i].shortTicket = 0;
            Log(StringFormat("Zone #%d: short entry cancelled (%s).", g_zones[i].id, expired ? "expired" : "back in zone"));
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| Model 2: reversion trade                                         |
//|  side = +1: price extended ABOVE the zone -> short back to it    |
//|  side = -1: price extended BELOW the zone -> long back to it     |
//+------------------------------------------------------------------+
bool ReversionSetup(const int i, const int side, double &trig, double &sl, double &chaseLimit)
  {
   double a = g_zones[i].atr;
   double hi = g_zones[i].hi, lo = g_zones[i].lo;
   int k = MathMax(1, MathMin(3, InpRevExtension));
   double ext = (side > 0) ? hi + k * a : lo - k * a;
   double tol = InpKeyLevelTolATR * a;

   if(InpReversionMode == REV_AGGRESSIVE || InpReversionMode == REV_BACK_IN_BLACK)
     {
      if(InpReversionMode == REV_BACK_IN_BLACK && !AlignedWithLevel(ext, tol))
         return false;
      trig = ext;
      sl = (side > 0) ? ext + InpRevStopATR * a : ext - InpRevStopATR * a;
      chaseLimit = (side > 0) ? ext + InpMaxChaseATR * a : ext - InpMaxChaseATR * a;
      return true;
     }

   if(InpReversionMode == REV_A_PLUS)
     {
      double buf = InpAPlusBufferTicks * (g_tickSize > 0.0 ? g_tickSize : g_point);
      for(int j = ArraySize(g_zones) - 1; j >= 0; j--)
        {
         if(j == i || g_zones[j].t >= g_zones[i].t)
            continue;
         if(g_zones[i].t - g_zones[j].t > InpAPlusLookbackMin * 60)
            continue;
         if(side > 0 && g_zones[j].lo > hi && ext >= g_zones[j].lo - tol && ext <= g_zones[j].hi + tol)
           {
            trig = g_zones[j].lo - tol;          // just before / inside the previous zone
            chaseLimit = g_zones[j].hi;
            sl = g_zones[j].hi + buf;            // stop outside the previous zone
            return true;
           }
         if(side < 0 && g_zones[j].hi < lo && ext <= g_zones[j].hi + tol && ext >= g_zones[j].lo - tol)
           {
            trig = g_zones[j].hi + tol;
            chaseLimit = g_zones[j].lo;
            sl = g_zones[j].lo - buf;
            return true;
           }
        }
     }
   return false;
  }

double ReversionTarget(const int i, const int dir)
  {
   double hi = g_zones[i].hi, lo = g_zones[i].lo;
   if(InpRevTarget == REVT_MID)
      return RoundToTick((hi + lo) * 0.5);
   if(dir < 0)   // short from above
      return (InpRevTarget == REVT_FAR_EDGE) ? lo : hi;
   return (InpRevTarget == REVT_FAR_EDGE) ? hi : lo;
  }

void PlaceReversion(const int i, const int dir, double sl, double tp)
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double entry = (dir > 0) ? tk.ask : tk.bid;
   sl = RoundToTick(sl);
   tp = RoundToTick(tp);
   if((dir > 0 && (sl >= entry || tp <= entry)) || (dir < 0 && (sl <= entry || tp >= entry)))
     {
      Log(StringFormat("Zone #%d: reversion geometry invalid at current price, skipped.", g_zones[i].id));
      return;
     }
   double lots = CalcLots(dir, entry, sl);
   if(lots <= 0.0)
      return;
   string cmt = MakeComment("R", g_zones[i].id, entry, sl);
   bool ok = (dir > 0) ? g_trade.Buy(lots, _Symbol, 0.0, sl, tp, cmt)
                       : g_trade.Sell(lots, _Symbol, 0.0, sl, tp, cmt);
   if(ok && RetcodeOK())
      Log(StringFormat("Reversion %s zone #%d: entry %.5f SL %.5f TP %.5f lots %.2f",
                       dir > 0 ? "LONG" : "SHORT", g_zones[i].id, entry, sl, tp, lots));
   else
      Log(StringFormat("Zone #%d: reversion order failed, retcode %u", g_zones[i].id, g_trade.ResultRetcode()));
  }

void CheckReversion(const int i, const double px)
  {
   double trig = 0.0, sl = 0.0, chase = 0.0;
   // extended above -> short
   if(!g_zones[i].revUpDone && px > g_zones[i].hi && !(InpRevSkipIfConfirmed && g_zones[i].longTraded))
     {
      if(ReversionSetup(i, +1, trig, sl, chase) && px >= trig && px <= chase)
        {
         g_zones[i].revUpDone = true;
         if(AllowReversion(-1) && CanOpenNew())
            PlaceReversion(i, -1, sl, ReversionTarget(i, -1));
         else
            Log(StringFormat("Zone #%d: short reversion blocked by filters.", g_zones[i].id));
        }
     }
   // extended below -> long
   if(!g_zones[i].revDnDone && px < g_zones[i].lo && !(InpRevSkipIfConfirmed && g_zones[i].shortTraded))
     {
      if(ReversionSetup(i, -1, trig, sl, chase) && px <= trig && px >= chase)
        {
         g_zones[i].revDnDone = true;
         if(AllowReversion(+1) && CanOpenNew())
            PlaceReversion(i, +1, sl, ReversionTarget(i, +1));
         else
            Log(StringFormat("Zone #%d: long reversion blocked by filters.", g_zones[i].id));
        }
     }
  }

//+------------------------------------------------------------------+
//| Zone loop                                                        |
//+------------------------------------------------------------------+
void ProcessZones()
  {
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   double px = (g_useTicks && tk.last > 0.0) ? tk.last : tk.bid;
   datetime now = TimeCurrent();
   for(int i = 0; i < ArraySize(g_zones); i++)
     {
      if(!g_zones[i].active)
         continue;
      if(now - g_zones[i].t > InpZoneLifetimeMin * 60)
        {
         ExpireZone(i);
         continue;
        }
      double a = g_zones[i].atr;
      if(a <= 0.0)
         continue;
      ManagePending(i, px, now);

      if(!g_zones[i].longConf && px >= g_zones[i].hi + InpConfirmATR * a
         && (InpAllowBothDirections || !g_zones[i].shortConf))
        {
         g_zones[i].longConf = true;
         OnZoneConfirmed(i, +1);
        }
      if(!g_zones[i].shortConf && px <= g_zones[i].lo - InpConfirmATR * a
         && (InpAllowBothDirections || !g_zones[i].longConf))
        {
         g_zones[i].shortConf = true;
         OnZoneConfirmed(i, -1);
        }
      if(InpReversionMode != REV_NONE)
         CheckReversion(i, px);
     }
  }

//+------------------------------------------------------------------+
//| Position management: optional partial / breakeven                |
//+------------------------------------------------------------------+
bool PartialDone(const ulong t)
  {
   for(int i = 0; i < ArraySize(g_partialDone); i++)
      if(g_partialDone[i] == t)
         return true;
   return false;
  }

void ManagePositions()
  {
   if(InpPartialAtR <= 0.0 && !InpMoveToBreakeven)
      return;
   MqlTick tk;
   if(!SymbolInfoTick(_Symbol, tk))
      return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tkt = PositionGetTicket(i);
      if(tkt == 0 || !IsOwnPositionSelected())
         continue;
      string tag = "";
      double risk = CommentRisk(PositionGetString(POSITION_COMMENT), tag);
      if(risk <= 0.0)
         continue;
      long type = PositionGetInteger(POSITION_TYPE);
      double open = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      double vol = PositionGetDouble(POSITION_VOLUME);
      double profit = (type == POSITION_TYPE_BUY) ? tk.bid - open : open - tk.ask;

      if(InpPartialAtR > 0.0 && !PartialDone(tkt) && profit >= InpPartialAtR * risk)
        {
         double step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
         double part = MathFloor(vol * InpPartialPercent / 100.0 / step) * step;
         if(part >= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN) && part < vol)
            g_trade.PositionClosePartial(tkt, part);
         int n = ArraySize(g_partialDone);
         ArrayResize(g_partialDone, n + 1);
         g_partialDone[n] = tkt;
        }
      if(InpMoveToBreakeven && profit >= InpBreakevenR * risk)
        {
         if(type == POSITION_TYPE_BUY && sl < open)
            g_trade.PositionModify(tkt, open, tp);
         if(type == POSITION_TYPE_SELL && (sl > open || sl == 0.0))
            g_trade.PositionModify(tkt, open, tp);
        }
     }
  }

void DeleteAllPending()
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong tk = OrderGetTicket(i);
      if(tk > 0 && OrderGetString(ORDER_SYMBOL) == _Symbol && OrderGetInteger(ORDER_MAGIC) == InpMagic)
         g_trade.OrderDelete(tk);
     }
  }

void CloseAllOwn()
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong tk = PositionGetTicket(i);
      if(tk > 0 && IsOwnPositionSelected())
         g_trade.PositionClose(tk);
     }
   DeleteAllPending();
  }

//+------------------------------------------------------------------+
//| Session / risk housekeeping                                      |
//+------------------------------------------------------------------+
void CheckSessionRoll()
  {
   datetime now = TimeCurrent();
   datetime ss = SessionStartFor(now);
   if(ss == g_sessionStart)
      return;
   g_sessionStart = ss;
   g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
   g_halted = false;
   ArrayResize(g_partialDone, 0);
   if(InpResetZonesEachSession)
     {
      while(ArraySize(g_zones) > 0)
         RemoveZone(0);
      ArrayResize(g_acc, 0);
     }
   Log(StringFormat("New session %s, start equity %.2f", TimeToString(ss), g_dayStartEquity));
  }

void CheckDailyLoss()
  {
   if(g_halted || g_dayStartEquity <= 0.0)
      return;
   double loss = g_dayStartEquity - AccountInfoDouble(ACCOUNT_EQUITY);
   bool hit = false;
   if(InpDailyLossPercent > 0.0 && loss >= g_dayStartEquity * InpDailyLossPercent / 100.0)
      hit = true;
   if(InpDailyLossMoney > 0.0 && loss >= InpDailyLossMoney)
      hit = true;
   if(!hit)
      return;
   g_halted = true;
   Log(StringFormat("Daily loss limit reached (%.2f). Trading halted for the session.", loss));
   if(InpCloseOnDailyLimit)
      CloseAllOwn();
   else
      DeleteAllPending();
  }

void UpdatePanel()
  {
   if(!InpShowPanel)
      return;
   int active = 0;
   for(int i = 0; i < ArraySize(g_zones); i++)
      if(g_zones[i].active)
         active++;
   string mode = g_useTicks ? "tick order flow" : (g_useProxy ? "bar proxy" : "manual zones");
   Comment(StringFormat("OrderFlow Iceberg EA\nEvents: %s\nWilder ATR(%d,%s): %.5f\nVWAP: %.5f  Key levels: %d\n"
                        "RVol: %.0f%%  Program: %s  Gamma: %s\nActive zones: %d  In session: %s  Halted: %s",
                        mode, InpATRPeriod, EnumToString(InpATRTimeframe), g_atr, g_vwap, ArraySize(g_levels),
                        g_rvol * 100.0, g_programDir > 0 ? "BUYING" : (g_programDir < 0 ? "SELLING" : "-"),
                        EnumToString(InpGammaRegime), active, InSession(TimeCurrent()) ? "yes" : "no",
                        g_halted ? "YES" : "no"));
  }

//+------------------------------------------------------------------+
//| Expert lifecycle                                                 |
//+------------------------------------------------------------------+
int OnInit()
  {
   g_startSec = ParseHHMM(InpSessionStart);
   g_endSec   = ParseHHMM(InpSessionEnd);
   if(g_startSec < 0 || g_endSec < 0)
     {
      Print("Invalid session time. Use HH:MM.");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpATRPeriod < 1 || InpEntryATR < InpConfirmATR)
     {
      Print("ATR period must be >= 1 and entry ATR must be >= confirmation ATR.");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   g_point    = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   g_digits   = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(g_tickSize <= 0.0)
      g_tickSize = g_point;
   g_netting = (AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING);

   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints((ulong)InpSlippagePoints);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   if(InpBiBUseBollinger)
      g_bbHandle = iBands(_Symbol, InpATRTimeframe, InpBBPeriod, 0, InpBBDeviation, PRICE_CLOSE);

   if(InpTickSymbol != "")
      SymbolSelect(InpTickSymbol, true);

   // event source selection
   g_useTicks = (InpEventSource == OF_SOURCE_TICKS);
   g_useProxy = (InpEventSource == OF_SOURCE_PROXY || InpEventSource == OF_SOURCE_AUTO);
   if(InpEventSource == OF_SOURCE_AUTO)
     {
      MqlTick hist[];
      int n = CopyTicks(_Symbol, hist, COPY_TICKS_TRADE, 0, 2000);
      for(int i = 0; i < n; i++)
         if((hist[i].flags & (TICK_FLAG_BUY | TICK_FLAG_SELL)) != 0 && hist[i].last > 0.0)
           {
            g_useTicks = true;
            g_useProxy = false;
            break;
           }
     }
   MqlTick last;
   if(SymbolInfoTick(_Symbol, last))
      g_lastTickMsc = last.time_msc + 1;   // start with the next tick
   g_lastMscCount = 0;

   g_sessionStart = 0;
   CheckSessionRoll();
   g_atr = ComputeWilderATR();
   RefreshKeyLevels();
   RefreshBollinger();
   UpdateProgramActivity();

   Log(StringFormat("Init: %s, %s account, events from %s, ATR %.5f",
                    _Symbol, g_netting ? "netting" : "hedging",
                    g_useTicks ? "tick order flow" : (g_useProxy ? "bar proxy" : "manual zones"), g_atr));
   if(!g_useTicks && InpEventSource != OF_SOURCE_MANUAL)
      Log("No aggressor-flagged exchange ticks: icebergs/stop runs are APPROXIMATED from bars. "
          "Use an exchange-connected futures feed for the real thing.");
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   if(g_bbHandle != INVALID_HANDLE)
      IndicatorRelease(g_bbHandle);
   ObjectsDeleteAll(0, "OFZ_");
   Comment("");
  }

void OnTick()
  {
   CheckSessionRoll();
   datetime now = TimeCurrent();

   // ATR on each new ATR-timeframe bar (also refreshes program activity)
   datetime atrBar = iTime(_Symbol, InpATRTimeframe, 0);
   if(atrBar != g_lastATRBar)
     {
      g_lastATRBar = atrBar;
      double a = ComputeWilderATR();
      if(a > 0.0)
         g_atr = a;
      UpdateProgramActivity();
     }

   // key levels, swing points once per minute
   datetime m1 = iTime(_Symbol, PERIOD_M1, 0);
   if(m1 != g_lastM1)
     {
      g_lastM1 = m1;
      RefreshKeyLevels();
      RefreshBollinger();
      int hiIdx = iHighest(_Symbol, PERIOD_M1, MODE_HIGH, InpSwingBars, 1);
      int loIdx = iLowest(_Symbol, PERIOD_M1, MODE_LOW, InpSwingBars, 1);
      if(hiIdx >= 0)
         g_swingHi = iHigh(_Symbol, PERIOD_M1, hiIdx);
      if(loIdx >= 0)
         g_swingLo = iLow(_Symbol, PERIOD_M1, loIdx);
     }

   // event detection
   if(InpReadManualZones && now != g_lastScan)
     {
      g_lastScan = now;
      ScanManualZones();
     }
   if(g_useTicks || InpEventSource == OF_SOURCE_AUTO)
      ProcessTicks();
   if(g_useProxy)
     {
      datetime pb = iTime(_Symbol, InpProxyTF, 0);
      if(pb != g_lastProxyBar)
        {
         g_lastProxyBar = pb;
         ProcessProxyBar();
        }
     }

   // risk / session
   CheckDailyLoss();
   if(!InSession(now))
     {
      if(InpFlatAtSessionEnd && CountOwnExposure() > 0)
         CloseAllOwn();
     }
   else
      if(!g_halted)
        {
         ProcessZones();
         ManagePositions();
        }
   UpdatePanel();
  }
//+------------------------------------------------------------------+
