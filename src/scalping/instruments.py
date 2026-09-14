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
)

REGISTRY: Dict[str, Instrument] = {"EURUSD": EURUSD, "XAUUSD": XAUUSD}


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
