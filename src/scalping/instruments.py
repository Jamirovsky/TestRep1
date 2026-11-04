"""Instrument specifications and transaction-cost models.

Every number here is a *broker-dependent* assumption.  They are deliberately
conservative (worse than a good ECN account) so that a strategy which survives
the backtest has headroom in live trading.  Override them from a JSON config
when you know your own broker's numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict


@dataclass(frozen=True)
class Instrument:
    """Contract specification plus the cost model used by the engine."""

    symbol: str
    # --- contract spec -------------------------------------------------
    point: float            # smallest price increment quoted by the broker
    pip: float              # 1 "pip" in price terms (10 points on 5-digit FX)
    contract_size: float    # units of base/ounces per 1.00 lot
    min_lot: float
    lot_step: float
    max_lot: float
    quote_ccy: str          # account currency conversion is 1.0 for USD quotes
    digits: int

    # --- cost model ----------------------------------------------------
    # Spread is modelled in *points* and varies by liquidity session; see
    # ``spread_points_for_hour``.  These are round-trip-relevant: the engine
    # charges the full spread once, on entry, and fills exits at the mid-derived
    # bid/ask consistently.
    spread_base_points: float          # typical spread, London/NY hours
    spread_asia_mult: float            # multiplier during Asian session
    spread_rollover_mult: float        # multiplier around the daily rollover
    spread_vol_coeff: float            # extra spread per unit of ATR z-score
    spread_max_points: float           # cap used by the "max spread" filter

    commission_per_lot_rt: float       # round-turn commission, account ccy
    slippage_points_entry: float       # adverse slippage on market entries
    slippage_points_stop: float        # extra adverse slippage on stop-loss exits

    swap_long_points: float = 0.0      # per night, points (negative = cost)
    swap_short_points: float = 0.0
    # How humans talk about distance on this instrument.  Calling 45 points of
    # gold "45 pips" is technically true and completely unreadable; traders say
    # "45 cents".
    display_unit: str = "pips"         # "pips" or "usd"
    # Price level at which the spread / slippage numbers above are quoted.
    # 0 = costs are fixed in points (the original XAUUSD/EURUSD behaviour).
    # > 0 = costs scale linearly with price, i.e. they are a constant number of
    # basis points.  Essential for the minor metals: silver went from USD 15 to
    # USD 60 and palladium from USD 3000 to USD 900 inside the test window, and
    # a broker's spread follows the price, not a fixed number of points.
    ref_price: float = 0.0
    # Home exchange for market-relative sessions ("cash_open", "cash", ...):
    # "US", "EU" or "FX" (= no cash session; the presets fall back to London/NY).
    market: str = "FX"

    def spread_points_for_hour(self, hour_utc: int, vol_z: float = 0.0) -> float:
        """Session- and volatility-aware spread in points."""
        mult = 1.0
        if 22 <= hour_utc or hour_utc < 6:       # Asia / pre-London
            mult = self.spread_asia_mult
        if hour_utc == 21:                        # daily rollover window
            mult = max(mult, self.spread_rollover_mult)
        spread = self.spread_base_points * mult
        if vol_z > 0.0:
            spread += self.spread_vol_coeff * vol_z * self.spread_base_points
        return min(spread, self.spread_max_points)

    # --- helpers -------------------------------------------------------
    def price_to_pips(self, price_delta: float) -> float:
        return price_delta / self.pip

    def fmt_distance(self, price_delta: float) -> str:
        """Render a price distance the way a trader of this symbol would say it."""
        if self.display_unit == "usd":
            return f"USD {price_delta:,.2f}"
        return f"{price_delta / self.pip:,.2f} pips"

    def pips_to_price(self, pips: float) -> float:
        return pips * self.pip

    def value_per_point_per_lot(self) -> float:
        """Account-currency value of one point of price movement on 1.00 lot."""
        return self.point * self.contract_size

    def round_lots(self, lots: float) -> float:
        if lots <= 0:
            return 0.0
        steps = int(lots / self.lot_step + 1e-9)
        lots = steps * self.lot_step
        return min(max(lots, 0.0), self.max_lot)

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Conservative retail-ECN presets.
#
# EURUSD: raw spread 0.1-0.3 pip in London/NY, commission ~USD 7 per round-turn
# lot (= 0.7 pip on 100k).  We model 0.4 pip spread + USD 7 => ~1.1 pip of
# friction per round trip, which is on the expensive side of a real ECN account.
#
# XAUUSD: raw spread 12-25 cents, commission frequently zero on "standard" gold
# but we charge USD 7/lot anyway (7 cents on 100oz).  Total friction ~0.30 USD
# per round trip.
# ---------------------------------------------------------------------------
EURUSD = Instrument(
    symbol="EURUSD",
    point=0.00001,
    pip=0.0001,
    contract_size=100_000.0,
    min_lot=0.01,
    lot_step=0.01,
    max_lot=50.0,
    quote_ccy="USD",
    digits=5,
    spread_base_points=4.0,        # 0.4 pip
    spread_asia_mult=2.2,
    spread_rollover_mult=6.0,
    spread_vol_coeff=0.5,
    spread_max_points=30.0,        # 3.0 pip hard cap
    commission_per_lot_rt=7.0,
    slippage_points_entry=1.5,     # 0.15 pip
    slippage_points_stop=3.0,      # 0.30 pip extra on stops
    swap_long_points=-8.0,
    swap_short_points=2.0,
)

XAUUSD = Instrument(
    symbol="XAUUSD",
    point=0.01,
    pip=0.01,                      # gold is quoted in cents; 1 pip == 1 point
    contract_size=100.0,           # 100 troy ounces per lot
    min_lot=0.01,
    lot_step=0.01,
    max_lot=20.0,
    quote_ccy="USD",
    digits=2,
    spread_base_points=18.0,       # 0.18 USD
    spread_asia_mult=1.8,
    spread_rollover_mult=5.0,
    spread_vol_coeff=0.6,
    spread_max_points=90.0,        # 0.90 USD hard cap
    commission_per_lot_rt=7.0,
    slippage_points_entry=6.0,     # 0.06 USD
    slippage_points_stop=14.0,     # 0.14 USD extra on stops
    swap_long_points=-40.0,
    swap_short_points=10.0,
    display_unit="usd",
)

# ---------------------------------------------------------------------------
# Minor metals.  Costs are quoted at ``ref_price`` and scale with price (see
# ``ref_price`` above), so they are effectively constant in basis points.
#
#                 spread @ref      round trip incl. entry slippage   vs gold
#   XAUUSD        0.18 @ 2000      ~1.3 bp                            1x
#   XAGUSD        0.025 @ 30       ~9.3 bp                            ~7x
#   XPTUSD        2.00 @ 1000      ~22 bp                             ~17x
#   XPDUSD        3.50 @ 1000      ~40 bp                             ~30x
#
# These are typical retail-ECN / CFD numbers (London/NY hours) on the
# conservative side.  Platinum and palladium are spread-only at most brokers,
# so commission is zero and the whole toll is in the spread.  Override from
# your own broker's contract specification if it is cheaper.
# ---------------------------------------------------------------------------
XAGUSD = Instrument(
    symbol="XAGUSD",
    point=0.001,
    pip=0.01,
    contract_size=5000.0,          # 5000 troy ounces per lot
    min_lot=0.01,
    lot_step=0.01,
    max_lot=50.0,
    quote_ccy="USD",
    digits=3,
    spread_base_points=25.0,       # USD 0.025 at USD 30 (8.3 bp)
    spread_asia_mult=1.8,
    spread_rollover_mult=5.0,
    spread_vol_coeff=0.6,
    spread_max_points=100.0,
    commission_per_lot_rt=0.0,     # folded into the spread
    slippage_points_entry=3.0,
    slippage_points_stop=8.0,
    swap_long_points=-15.0,
    swap_short_points=0.0,
    display_unit="usd",
    ref_price=30.0,
)

XPTUSD = Instrument(
    symbol="XPTUSD",
    point=0.01,
    pip=0.01,
    contract_size=100.0,
    min_lot=0.01,
    lot_step=0.01,
    max_lot=20.0,
    quote_ccy="USD",
    digits=2,
    spread_base_points=200.0,      # USD 2.00 at USD 1000 (20 bp)
    spread_asia_mult=1.8,
    spread_rollover_mult=4.0,
    spread_vol_coeff=0.6,
    spread_max_points=800.0,
    commission_per_lot_rt=0.0,
    slippage_points_entry=20.0,
    slippage_points_stop=50.0,
    swap_long_points=-200.0,
    swap_short_points=0.0,
    display_unit="usd",
    ref_price=1000.0,
)

XPDUSD = Instrument(
    symbol="XPDUSD",
    point=0.01,
    pip=0.01,
    contract_size=100.0,
    min_lot=0.01,
    lot_step=0.01,
    max_lot=20.0,
    quote_ccy="USD",
    digits=2,
    spread_base_points=350.0,      # USD 3.50 at USD 1000 (35 bp)
    spread_asia_mult=1.8,
    spread_rollover_mult=4.0,
    spread_vol_coeff=0.6,
    spread_max_points=1400.0,
    commission_per_lot_rt=0.0,
    slippage_points_entry=50.0,
    slippage_points_stop=120.0,
    swap_long_points=-300.0,
    swap_short_points=0.0,
    display_unit="usd",
    ref_price=1000.0,
)

# ---------------------------------------------------------------------------
# XAUJPY -- gold quoted in yen.  The same metal as XAUUSD, so the same scalper,
# but a cross: brokers quote it wider than XAUUSD (about 2 bp against 0.9 bp).
# Point = 1 JPY.  ``contract_size`` is expressed in USD-equivalent ounces
# (100 oz / ~150 JPY per USD) so that position sizing in a USD account is
# approximately right; every performance number is in R and does not depend
# on it.
# ---------------------------------------------------------------------------
XAUJPY = Instrument(
    symbol="XAUJPY",
    point=1.0,
    pip=1.0,
    contract_size=100.0 / 150.0,
    min_lot=0.01,
    lot_step=0.01,
    max_lot=20.0,
    quote_ccy="JPY",
    digits=0,
    spread_base_points=120.0,      # JPY 120 at JPY 600,000 (2.0 bp)
    spread_asia_mult=1.6,
    spread_rollover_mult=5.0,
    spread_vol_coeff=0.6,
    spread_max_points=600.0,
    commission_per_lot_rt=0.0,
    slippage_points_entry=18.0,    # 0.3 bp
    slippage_points_stop=42.0,     # 0.7 bp
    swap_long_points=-300.0,
    swap_short_points=0.0,
    display_unit="pips",
    ref_price=600_000.0,
)


# ---------------------------------------------------------------------------
# Cash indices (CFDs).  Costs in bp of the index level during the cash
# session; outside it the Asian multiplier applies.  ``market`` drives the
# market-relative session presets (``cash_open`` = first 3 h of the home
# exchange, etc.), so one parameter set can trade US and European indices.
# ---------------------------------------------------------------------------
def _index(symbol, spread_pts, ref, market, slip_e=0.2, slip_s=0.5):
    bp = ref * 1e-4
    return Instrument(
        symbol=symbol, point=0.1, pip=1.0, contract_size=1.0,
        min_lot=0.1, lot_step=0.1, max_lot=500.0, quote_ccy="USD", digits=1,
        spread_base_points=spread_pts / 0.1,
        spread_asia_mult=2.5, spread_rollover_mult=5.0, spread_vol_coeff=0.6,
        spread_max_points=spread_pts / 0.1 * 6,
        commission_per_lot_rt=0.0,
        slippage_points_entry=slip_e * bp / 0.1, slippage_points_stop=slip_s * bp / 0.1,
        swap_long_points=0.0, swap_short_points=0.0, display_unit="pips",
        ref_price=ref, market=market,
    )


US500 = _index("US500", 0.5, 5000.0, "US")      # 1.0 bp
US100 = _index("US100", 1.5, 18000.0, "US")     # 0.8 bp
US30 = _index("US30", 2.5, 40000.0, "US")       # 0.6 bp
GER40 = _index("GER40", 1.5, 18000.0, "EU")     # 0.8 bp
UK100 = _index("UK100", 1.0, 8000.0, "EU")      # 1.25 bp


# ---------------------------------------------------------------------------
# US single-stock CFDs: 1 lot = 1 share.  Spread 2 bp of price plus a
# commission of USD 0.02 per share per side (0.04 round turn, so 0.8-2.2 bp
# depending on the share price).  Only regular-session bars exist.
# ---------------------------------------------------------------------------
def _stock(symbol):
    return Instrument(
        symbol=symbol, point=0.01, pip=0.01, contract_size=1.0,
        min_lot=1.0, lot_step=1.0, max_lot=100_000.0, quote_ccy="USD", digits=2,
        spread_base_points=2.0,            # USD 0.02 at USD 100 (2 bp)
        spread_asia_mult=1.0, spread_rollover_mult=1.0, spread_vol_coeff=0.6,
        spread_max_points=10.0,
        commission_per_lot_rt=0.04,
        slippage_points_entry=0.5, slippage_points_stop=1.0,
        swap_long_points=0.0, swap_short_points=0.0, display_unit="usd",
        ref_price=100.0, market="US",
    )


STOCKS7 = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
INDICES5 = ["US500", "US100", "US30", "GER40", "UK100"]

REGISTRY: Dict[str, Instrument] = {
    "EURUSD": EURUSD, "XAUUSD": XAUUSD,
    "XAGUSD": XAGUSD, "XPTUSD": XPTUSD, "XPDUSD": XPDUSD,
    "XAUJPY": XAUJPY,
    "US500": US500, "US100": US100, "US30": US30, "GER40": GER40, "UK100": UK100,
    **{s: _stock(s) for s in STOCKS7},
}


def get_instrument(symbol: str) -> Instrument:
    key = symbol.upper().strip()
    for suffix in ("", ".RAW", "M", "#", "PRO", "ECN", "_SB"):
        if key.endswith(suffix) and suffix:
            probe = key[: -len(suffix)]
            if probe in REGISTRY:
                return REGISTRY[probe]
    if key not in REGISTRY:
        raise KeyError(
            f"Unknown symbol {symbol!r}. Known: {sorted(REGISTRY)}. "
            "Add an Instrument() entry in instruments.py for new symbols."
        )
    return REGISTRY[key]
