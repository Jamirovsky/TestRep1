"""Backtest engine for MQL5/Experts/OrderFlowIcebergEA.

A port of the EA's OnTick logic, run on an exact intrabar price path:

* Each bar is walked as O->L->H->C (up bar) or O->H->L->C (down bar).
* Along each leg the engine emits a "tick" at every price level the EA's state cares
  about: confirmation levels, pending entry, cancel level, stop, target, reversion
  trigger and chase bound. State changes can only happen at those prices, so the
  sequence of events is exact for that path, with no discretisation error.
* Broker-side fills (pending stop orders, SL, TP) run before the EA logic on each tick,
  as on a real server.

Costs: commission each side, plus slippage on every stop-type or market fill (entries,
stop-loss exits, session-end exits). Limit take-profits pay commission only.

Results are in R (planned risk = |planned entry - stop|), so sizing does not matter.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ----------------------------------------------------------------------------- specs


@dataclass(frozen=True)
class Instrument:
    name: str
    tick: float
    point_value: float          # $ per 1.0 price move per contract (informational)
    commission_pts: float       # commission per side, in price units
    slip_ticks: float = 1.0     # slippage on stop / market fills, in ticks
    taker_frac: float = 0.0     # proportional fee on taker fills (crypto)
    maker_frac: float = 0.0     # proportional fee on maker fills (crypto)

    def cost(self, price: float, kind: str) -> float:
        """Per-side cost in price units. kind: 'taker' (stop/market) or 'maker' (limit)."""
        if kind == "maker":
            return self.commission_pts + price * self.maker_frac
        return self.commission_pts + self.slip_ticks * self.tick + price * self.taker_frac


INSTRUMENTS = {
    # commission: ~$4.50 round turn per contract incl. exchange fees
    "NQ": Instrument("NQ", 0.25, 20.0, 2.25 / 20.0),
    "ES": Instrument("ES", 0.25, 50.0, 2.25 / 50.0),
    "GC": Instrument("GC", 0.10, 100.0, 2.25 / 100.0),
    "CL": Instrument("CL", 0.01, 1000.0, 2.25 / 1000.0),
    # Binance USD-M perp: 0.05% taker / 0.02% maker
    "BTC": Instrument("BTC", 0.10, 1.0, 0.0, 1.0, 0.0005, 0.0002),
}


@dataclass
class Params:
    # --- event detection: bar proxy (EA: ProcessProxyBar)
    proxy_vol_mult: float = 3.0         # the EA's original default (now ships 4.0, see RESULTS.md)
    proxy_avg_bars: int = 30
    swing_bars: int = 20
    absorb_max_range_atr: float = 0.35
    # --- event detection: tick order flow (EA: OnTradeTick)
    min_iceberg: float = 150.0
    min_stoprun: float = 150.0
    absorb_window_s: int = 60
    absorb_through_ticks: int = 1
    stoprun_window_s: int = 3
    zone_pad_ticks: int = 2
    # --- zones
    zone_lifetime_min: int = 240
    dedupe_min: int = 15
    # --- ATR
    atr_period: int = 14
    confirm_atr: float = 1.0
    entry_atr: float = 1.15
    stop_atr: float = 1.15
    # --- step 1
    require_key_level: bool = True
    key_tol_atr: float = 0.25
    # --- position trade
    enable_position: bool = True
    allow_both: bool = True
    pending_expiry_min: int = 30
    cancel_back_in_zone: bool = True
    max_chase_atr: float = 0.10
    target_mode: str = "next_level"      # 'trail' | 'r' | 'next_level'
    target_r: float = 3.0
    min_target_r: float = 1.0
    trail_on_events: bool = True
    # --- reversion
    rev_mode: str = "none"               # 'none' | 'aggressive' | 'bib' | 'aplus'
    rev_ext: int = 2
    rev_stop_atr: float = 0.5
    rev_target: str = "near"             # 'near' | 'mid' | 'far'
    rev_skip_if_confirmed: bool = True
    aplus_buffer_ticks: int = 4
    aplus_lookback_min: int = 480
    # --- filters / risk
    use_rvol: bool = True
    rvol_thr: float = 2.0
    max_trades_day: int = 6
    daily_loss_r: float = 4.0            # 2% limit / 0.5% risk


# ----------------------------------------------------------------------- data prep


def wilder_atr(df: pd.DataFrame, n: int) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    out = tr.copy() * np.nan
    if len(tr) <= n:
        return out
    seed = tr.iloc[1:n + 1].mean()
    vals = tr.to_numpy()
    res = np.full(len(vals), np.nan)
    res[n] = seed
    for i in range(n + 1, len(vals)):
        res[i] = (res[i - 1] * (n - 1) + vals[i]) / n
    return pd.Series(res, index=tr.index)


def prepare(bars: pd.DataFrame, prm: Params, bar_seconds: int = 60,
            session=("09:30", "16:00")) -> dict:
    """Per-bar arrays the engine needs. `bars` index: tz-aware America/New_York, bar open time."""
    df = bars.copy()
    idx = df.index
    # trading day rolls at 18:00 ET (CME convention) -> previous-day levels
    tday = (idx + pd.Timedelta(hours=6)).normalize().tz_localize(None)
    df["tday"] = tday
    daily = df.groupby("tday").agg(high=("high", "max"), low=("low", "min"), close=("close", "last"))
    prev = daily.shift(1)
    df["pdh"] = prev["high"].reindex(df["tday"]).to_numpy()
    df["pdl"] = prev["low"].reindex(df["tday"]).to_numpy()
    df["pdc"] = prev["close"].reindex(df["tday"]).to_numpy()

    # session mask and session id (session = calendar date of the 09:30 start)
    s_h, s_m = map(int, session[0].split(":"))
    e_h, e_m = map(int, session[1].split(":"))
    mins = idx.hour * 60 + idx.minute
    in_sess = (mins >= s_h * 60 + s_m) & (mins < e_h * 60 + e_m) & (idx.dayofweek < 5)
    df["in_sess"] = in_sess
    ymd = idx.year * 10000 + idx.month * 100 + idx.day
    df["sess_id"] = np.where(in_sess, ymd, -1)

    # 5-minute Wilder ATR, value of the last CLOSED 5m bar
    # resample / floor in UTC (DST-safe), then express in New York time
    b5 = df[["open", "high", "low", "close", "volume"]].tz_convert("UTC").resample(
        "5min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    b5.index = b5.index.tz_convert("America/New_York")
    floor5 = idx.tz_convert("UTC").floor("5min").tz_convert("America/New_York")
    atr5 = wilder_atr(b5, prm.atr_period)
    atr_closed = atr5.shift(1)
    df["atr"] = atr_closed.reindex(floor5).ffill().to_numpy()

    # Bollinger(20, 2) on 5m closes (last closed bar, no lookahead)
    mid = b5["close"].rolling(20).mean()
    sd = b5["close"].rolling(20).std(ddof=0)
    df["bbu"] = (mid + 2.0 * sd).shift(1).reindex(floor5).ffill().to_numpy()
    df["bbl"] = (mid - 2.0 * sd).shift(1).reindex(floor5).ffill().to_numpy()

    # relative volume of the last closed 5m bar vs the same slot over up to 30 prior days
    b5v = b5.copy()
    b5v["slot"] = b5v.index.hour * 60 + b5v.index.minute
    b5v["avg_prior"] = b5v.groupby("slot")["volume"].transform(lambda s: s.shift(1).rolling(30, min_periods=5).mean())
    b5v["rvol"] = b5v["volume"] / b5v["avg_prior"]
    b5v["dir"] = np.sign(b5v["close"] - b5v["open"])
    prog = np.where(b5v["rvol"] >= prm.rvol_thr, b5v["dir"], 0.0)
    prog = pd.Series(prog, index=b5v.index).shift(1)
    df["prog"] = prog.reindex(floor5).fillna(0).to_numpy()

    # session-anchored VWAP using bars up to the previous one (anchor = most recent session start)
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"].clip(lower=0)
    start_today = idx.normalize() + pd.Timedelta(hours=s_h, minutes=s_m)
    anchor = np.where(idx >= start_today, start_today, start_today - pd.Timedelta(days=1))
    grp = pd.Series(anchor, index=idx)
    pv = (tp * vol).groupby(grp.values).cumsum()
    vv = vol.groupby(grp.values).cumsum()
    vwap_incl = (pv / vv.replace(0, np.nan))
    df["vwap"] = vwap_incl.groupby(grp.values).shift(1).to_numpy()

    out = {k: df[k].to_numpy(dtype=float) for k in ["open", "high", "low", "close", "volume", "atr",
                                                    "bbu", "bbl", "prog", "vwap", "pdh", "pdl", "pdc"]}
    out["in_sess"] = df["in_sess"].to_numpy()
    out["sess_id"] = df["sess_id"].to_numpy()
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    out["t"] = ((idx.tz_convert("UTC") - epoch) // pd.Timedelta(seconds=1)).to_numpy().astype(np.int64)
    out["index"] = idx
    out["bar_seconds"] = bar_seconds
    return out


# ------------------------------------------------------------------ event sources


def proxy_events(P: dict, prm: Params) -> list[tuple]:
    """EA ProcessProxyBar on every closed bar -> (activation_bar, lo, hi, kind)."""
    o, h, l, c, v, atr = P["open"], P["high"], P["low"], P["close"], P["volume"], P["atr"]
    n = len(o)
    need = max(prm.proxy_avg_bars, prm.swing_bars) + 1
    vs = pd.Series(v)
    avg = vs.shift(1).rolling(prm.proxy_avg_bars).mean().to_numpy()
    swh = pd.Series(h).shift(1).rolling(prm.swing_bars).max().to_numpy()
    swl = pd.Series(l).shift(1).rolling(prm.swing_bars).min().to_numpy()
    ev = []
    for i in range(need, n - 1):
        if not (avg[i] > 0) or v[i] < prm.proxy_vol_mult * avg[i]:
            continue
        j = i + 1   # zone appears at the first tick of the next bar
        if not P["in_sess"][j]:
            continue
        hi_s, lo_s = swh[i], swl[i]
        up, dn = h[i] > hi_s, l[i] < lo_s
        mid = 0.5 * (h[i] + l[i])
        if up and dn:
            ev.append((j, l[i], h[i], "BS" if c[i] < mid else "SS"))
        elif up:
            ev.append((j, hi_s, h[i], "BS"))
        elif dn:
            ev.append((j, l[i], lo_s, "SS"))
        elif atr[j] > 0 and (h[i] - l[i]) <= prm.absorb_max_range_atr * atr[j]:
            ev.append((j, l[i], h[i], "BI" if c[i] >= o[i] else "SI"))
    return ev


def random_events(P: dict, real: list[tuple], rng: np.random.Generator) -> list[tuple]:
    """Null: same number of events per session and same zone heights, at random in-session
    bars, placed around that bar's open. Tests whether event detection adds anything."""
    by_sess = defaultdict(list)
    for e in real:
        if P["in_sess"][e[0]]:          # out-of-session events never trade
            by_sess[P["sess_id"][e[0]]].append(e)
    sess_bars = defaultdict(list)
    for j in np.flatnonzero(P["in_sess"]):
        sess_bars[P["sess_id"][j]].append(j)
    out = []
    for s, evs in by_sess.items():
        bars = sess_bars[s]
        picks = rng.choice(bars, size=len(evs), replace=len(evs) > len(bars))
        for j, e in zip(sorted(picks), evs):
            hgt = e[2] - e[1]
            p0 = P["open"][j]
            off = rng.uniform(0, hgt)
            out.append((int(j), p0 - off, p0 - off + hgt, e[3]))
    out.sort(key=lambda x: x[0])
    return out


# ------------------------------------------------------------------------ engine


@dataclass
class Trade:
    tag: str
    zone: int
    dir: int
    entry_bar: int
    exit_bar: int
    entry: float
    exit: float
    sl0: float
    r: float
    reason: str


@dataclass
class _Zone:
    id: int
    kind: str
    t: int
    bar: int
    lo: float
    hi: float
    atr: float
    key_ok: bool
    active: bool = True
    long_conf: bool = False
    short_conf: bool = False
    long_done: bool = False
    short_done: bool = False
    rev_up: bool = False
    rev_dn: bool = False
    long_traded: bool = False     # a position trade was actually placed on this side
    short_traded: bool = False


class Sim:
    def __init__(self, P: dict, events: list[tuple], prm: Params, inst: Instrument, seed: int = 0):
        self.P, self.prm, self.inst = P, prm, inst
        self.ev = defaultdict(list)
        for e in events:
            self.ev[e[0]].append(e)
        self.rng = np.random.default_rng(seed)
        self.trades: list[Trade] = []
        self.bars_in_market = 0

    # ---- helpers
    def rt(self, p):
        tk = self.inst.tick
        return round(round(p / tk) * tk, 10)

    def levels(self, j):
        P = self.P
        return [x for x in (P["vwap"][j], P["pdh"][j], P["pdl"][j], P["pdc"][j]) if x == x and x > 0]

    def near_level_dist(self, lo, hi, j):
        best = math.inf
        for l in self.levels(j):
            d = l - hi if l > hi else (lo - l if l < lo else 0.0)
            best = min(best, d)
        return best

    def aligned(self, price, tol, j):
        if self.near_level_dist(price, price, j) <= tol:
            return True
        P = self.P
        for b in (P["bbu"][j], P["bbl"][j]):
            if b == b and abs(b - price) <= tol:
                return True
        return False

    def can_open(self):
        return (not self.halted and self.pos is None and self.pend is None
                and self.trades_today < self.prm.max_trades_day)

    # ---- trade bookkeeping
    def _open(self, d, fill, sl, tp, tag, z, kind_cost):
        self.pos = dict(dir=d, entry=fill, sl=sl, tp=tp, sl0=sl, tag=tag, zone=z.id, t=self.now,
                        bar=self.j, cost_in=self.inst.cost(fill, kind_cost),
                        risk=abs(fill - sl) if tag == "R" else None)
        self.trades_today += 1

    def _close(self, px, reason, maker=False):
        p = self.pos
        cost_out = self.inst.cost(px, "maker" if maker else "taker")
        risk = p["risk"] if p["risk"] else abs(p["planned"] - p["sl0"])
        r = (p["dir"] * (px - p["entry"]) - p["cost_in"] - cost_out) / risk
        self.trades.append(Trade(p["tag"], p["zone"], p["dir"], p["bar"], self.j, p["entry"], px, p["sl0"], r, reason))
        self.day_r += r
        self.pos = None
        if self.prm.daily_loss_r > 0 and self.day_r <= -self.prm.daily_loss_r:
            self.halted = True
            self.pend = None

    # ---- EA: position trade
    def try_position(self, z: _Zone, d: int, p: float):
        prm = self.prm
        if d > 0:
            if z.long_done:
                return
            z.long_done = True
        else:
            if z.short_done:
                return
            z.short_done = True
        if not prm.enable_position or (prm.require_key_level and not z.key_ok) or not self.can_open():
            return
        a = z.atr
        if d > 0:
            entry, sl = self.rt(z.hi + prm.entry_atr * a), self.rt(z.lo - prm.stop_atr * a)
        else:
            entry, sl = self.rt(z.lo - prm.entry_atr * a), self.rt(z.hi + prm.stop_atr * a)
        risk = abs(entry - sl)
        tp = self.target(d, entry, risk)
        if (d > 0 and entry > p) or (d < 0 and entry < p):
            self.pend = dict(dir=d, price=entry, sl=sl, tp=tp, zone=z, placed=self.now)
        elif abs(p - entry) <= prm.max_chase_atr * a:
            self._open(d, p, sl, tp, "P", z, "taker")
            self.pos["planned"] = entry
        else:
            return
        if d > 0:
            z.long_traded = True
        else:
            z.short_traded = True

    def target(self, d, entry, risk):
        prm = self.prm
        if prm.target_mode == "trail":
            return 0.0
        rt = self.rt(entry + d * prm.target_r * risk)
        if prm.target_mode == "next_level":
            best = None
            for l in self.levels(self.j):
                if d > 0 and l >= entry + prm.min_target_r * risk and (best is None or l < best):
                    best = l
                if d < 0 and l <= entry - prm.min_target_r * risk and (best is None or l > best):
                    best = l
            if best is not None:
                return self.rt(best)
        return rt

    def trail(self, z: _Zone, d: int, p: float):
        pos = self.pos
        if pos is None or pos["tag"] != "P" or pos["dir"] != d or pos["t"] >= z.t:
            return
        a = z.atr
        if d > 0:
            nsl = self.rt(z.lo - self.prm.stop_atr * a)
            if nsl > pos["sl"] + self.inst.tick and nsl < p:
                pos["sl"] = nsl
        else:
            nsl = self.rt(z.hi + self.prm.stop_atr * a)
            if nsl < pos["sl"] - self.inst.tick and nsl > p:
                pos["sl"] = nsl

    # ---- EA: reversion
    def rev_setup(self, z: _Zone, side: int):
        prm = self.prm
        a = z.atr
        k = max(1, min(3, prm.rev_ext))
        ext = z.hi + k * a if side > 0 else z.lo - k * a
        tol = prm.key_tol_atr * a
        if prm.rev_mode in ("aggressive", "bib"):
            if prm.rev_mode == "bib" and not self.aligned(ext, tol, self.j):
                return None
            sl = ext + prm.rev_stop_atr * a if side > 0 else ext - prm.rev_stop_atr * a
            chase = ext + prm.max_chase_atr * a if side > 0 else ext - prm.max_chase_atr * a
            return ext, sl, chase
        if prm.rev_mode == "aplus":
            buf = prm.aplus_buffer_ticks * self.inst.tick
            for y in reversed(self.zones):
                if y is z or y.t >= z.t or z.t - y.t > prm.aplus_lookback_min * 60:
                    continue
                if side > 0 and y.lo > z.hi and y.lo - tol <= ext <= y.hi + tol:
                    return y.lo - tol, y.hi + buf, y.hi
                if side < 0 and y.hi < z.lo and y.lo - tol <= ext <= y.hi + tol:
                    return y.hi + tol, y.lo - buf, y.lo
        return None

    def rev_target(self, z: _Zone, d: int):
        m = self.prm.rev_target
        if m == "mid":
            return self.rt(0.5 * (z.hi + z.lo))
        if d < 0:
            return z.lo if m == "far" else z.hi
        return z.hi if m == "far" else z.lo

    def allow_rev(self, d):
        prog = self.P["prog"][self.j] if self.prm.use_rvol else 0.0
        if d > 0 and prog < 0:
            return False
        if d < 0 and prog > 0:
            return False
        return True

    def check_rev(self, z: _Zone, p: float):
        prm = self.prm
        if not z.rev_up and p > z.hi and not (prm.rev_skip_if_confirmed and z.long_traded):
            s = self.rev_setup(z, +1)
            if s and s[0] <= p <= s[2]:
                z.rev_up = True
                if self.allow_rev(-1) and self.can_open():
                    self.place_rev(z, -1, p, s[1])
        if not z.rev_dn and p < z.lo and not (prm.rev_skip_if_confirmed and z.short_traded):
            s = self.rev_setup(z, -1)
            if s and s[2] <= p <= s[0]:
                z.rev_dn = True
                if self.allow_rev(+1) and self.can_open():
                    self.place_rev(z, +1, p, s[1])

    def place_rev(self, z, d, p, sl):
        sl = self.rt(sl)
        tp = self.rev_target(z, d)
        if (d > 0 and (sl >= p or tp <= p)) or (d < 0 and (sl <= p or tp >= p)):
            return
        self._open(d, p, sl, tp, "R", z, "taker")

    # ---- interesting price levels for the exact path walk
    def watch_levels(self):
        out = []
        pd_ = self.pend
        if pd_ is not None:
            out.append(pd_["price"])
            if self.prm.cancel_back_in_zone:
                out.append(pd_["zone"].hi if pd_["dir"] > 0 else pd_["zone"].lo)
        if self.pos is not None:
            out.append(self.pos["sl"])
            if self.pos["tp"]:
                out.append(self.pos["tp"])
        if self.halted:
            return out
        prm = self.prm
        for z in self.zones:
            if not z.active:
                continue
            a = z.atr
            if not z.long_conf:
                out.append(z.hi + prm.confirm_atr * a)
            if not z.short_conf:
                out.append(z.lo - prm.confirm_atr * a)
            if prm.rev_mode != "none":
                if not z.rev_up:
                    s = self.rev_setup(z, +1)
                    if s:
                        out += [s[0], s[2]]
                if not z.rev_dn:
                    s = self.rev_setup(z, -1)
                    if s:
                        out += [s[0], s[2]]
        return out

    # ---- one tick: broker first, then EA
    def tick(self, p: float):
        prm = self.prm
        # broker: pending stop entry
        pd_ = self.pend
        if pd_ is not None:
            if pd_["dir"] > 0 and p >= pd_["price"]:
                fill = max(p, pd_["price"])
                self.pend = None
                self._open(1, fill, pd_["sl"], pd_["tp"], "P", pd_["zone"], "taker")
                self.pos["planned"] = pd_["price"]
            elif pd_["dir"] < 0 and p <= pd_["price"]:
                fill = min(p, pd_["price"])
                self.pend = None
                self._open(-1, fill, pd_["sl"], pd_["tp"], "P", pd_["zone"], "taker")
                self.pos["planned"] = pd_["price"]
        # broker: SL / TP
        pos = self.pos
        if pos is not None:
            if pos["dir"] > 0:
                if p <= pos["sl"]:
                    self._close(min(p, pos["sl"]), "sl")
                elif pos["tp"] and p >= pos["tp"]:
                    self._close(max(p, pos["tp"]), "tp", maker=True)
            else:
                if p >= pos["sl"]:
                    self._close(max(p, pos["sl"]), "sl")
                elif pos["tp"] and p <= pos["tp"]:
                    self._close(min(p, pos["tp"]), "tp", maker=True)
        if self.halted:
            return
        # EA: ProcessZones
        for z in self.zones:
            if not z.active:
                continue
            a = z.atr
            if self.pend is not None and self.pend["zone"] is z:
                expired = prm.pending_expiry_min > 0 and self.now - self.pend["placed"] > prm.pending_expiry_min * 60
                back = prm.cancel_back_in_zone and ((self.pend["dir"] > 0 and p <= z.hi) or
                                                    (self.pend["dir"] < 0 and p >= z.lo))
                if expired or back:
                    self.pend = None
            if not z.long_conf and p >= z.hi + prm.confirm_atr * a and (prm.allow_both or not z.short_conf):
                z.long_conf = True
                if prm.trail_on_events:
                    self.trail(z, +1, p)
                self.try_position(z, +1, p)
            if not z.short_conf and p <= z.lo - prm.confirm_atr * a and (prm.allow_both or not z.long_conf):
                z.short_conf = True
                if prm.trail_on_events:
                    self.trail(z, -1, p)
                self.try_position(z, -1, p)
            if prm.rev_mode != "none":
                self.check_rev(z, p)

    def walk(self, a: float, b: float):
        """Move price from a to b, stopping at every watched level in path order."""
        cur = a
        guard = 0
        while cur != b and guard < 64:
            guard += 1
            up = b > cur
            nxt = b
            for lv in self.watch_levels():
                if up and cur < lv < nxt:
                    nxt = lv
                elif not up and nxt < lv < cur:
                    nxt = lv
            self.tick(nxt)
            cur = nxt

    # ---- main loop
    def run(self) -> list[Trade]:
        P, prm = self.P, self.prm
        n = len(P["open"])
        self.zones: list[_Zone] = []
        self.pos = None
        self.pend = None
        self.halted = False
        self.day_r = 0.0
        self.trades_today = 0
        cur_sess = None
        zid = 0
        bar_s = P["bar_seconds"]
        for j in range(n):
            self.j = j
            self.now = int(P["t"][j])
            if not P["in_sess"][j]:
                if self.pos is not None:
                    self._close(P["open"][j], "session")
                self.pend = None
                continue
            s = P["sess_id"][j]
            if s != cur_sess:
                cur_sess = s
                self.zones = []
                self.halted = False
                self.day_r = 0.0
                self.trades_today = 0
            # zone expiry (time based)
            for z in self.zones:
                if z.active and self.now - z.t > prm.zone_lifetime_min * 60:
                    z.active = False
                    if self.pend is not None and self.pend["zone"] is z:
                        self.pend = None
            # new events at the first tick of this bar
            atr = P["atr"][j]
            if atr == atr and atr > 0:
                for (_, lo, hi, kind) in self.ev.get(j, []):
                    if hi < lo:
                        lo, hi = hi, lo
                    dup = any(z.active and z.kind == kind and lo <= z.hi and hi >= z.lo
                              and self.now - z.t < prm.dedupe_min * 60 for z in self.zones)
                    if dup:
                        continue
                    zid += 1
                    lo_r, hi_r = self.rt(lo), self.rt(hi)
                    key_ok = self.near_level_dist(lo_r, hi_r, j) <= prm.key_tol_atr * atr
                    self.zones.append(_Zone(zid, kind, self.now, j, lo_r, hi_r, atr, key_ok))
            if not self.zones and self.pos is None and self.pend is None:
                continue
            o, h, l, c = P["open"][j], P["high"][j], P["low"][j], P["close"][j]
            self.tick(o)
            path = (o, l, h, c) if c >= o else (o, h, l, c)
            for a, b in zip(path, path[1:]):
                self.walk(a, b)
            if self.pos is not None:
                self.bars_in_market += 1
        if self.pos is not None:
            self.j = n - 1
            self._close(P["close"][n - 1], "end")
        return self.trades


# --------------------------------------------------------------------- reporting


def summarise(trades: list[Trade], bars_in_market: int = 0, label: str = "") -> dict:
    r = np.array([t.r for t in trades], dtype=float)
    n = len(r)
    if n == 0:
        return dict(label=label, n=0, mean_r=np.nan, total_r=0.0, win=np.nan, pf=np.nan, sqn=np.nan,
                    p90=np.nan, max=np.nan, mean_ex_top5=np.nan, r_per_bar=np.nan)
    srt = np.sort(r)
    k = max(1, int(round(0.05 * n)))
    ex = srt[:-k] if n > k else srt[:0]
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    sd = r.std(ddof=1) if n > 1 else np.nan
    return dict(
        label=label, n=n, mean_r=r.mean(), total_r=r.sum(), win=(r > 0).mean(),
        pf=gains / losses if losses > 0 else np.inf,
        sqn=(r.mean() / sd * math.sqrt(n)) if sd and sd > 0 else np.nan,
        p90=np.percentile(r, 90), max=r.max(),
        mean_ex_top5=ex.mean() if len(ex) else np.nan,
        r_per_bar=r.sum() / bars_in_market if bars_in_market else np.nan,
    )
