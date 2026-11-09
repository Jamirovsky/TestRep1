"""Self-checks for ofi_engine: hand-computed trades on synthetic bars.

Run:  python test_engine.py
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ofi_engine import Instrument, Params, Sim

FREE = Instrument("X", 0.25, 1.0, 0.0, 0.0)          # no costs, to check geometry
COSTLY = Instrument("Y", 0.25, 1.0, 0.10, 1.0)        # 0.10 commission + 1 tick slip per side


def make_P(bars: list[tuple], atr: float = 10.0) -> dict:
    """bars: (o, h, l, c). All bars in one session, 1 minute apart, constant ATR."""
    n = len(bars)
    o, h, l, c = (np.array(x, dtype=float) for x in zip(*bars))
    t0 = 1_700_000_000
    nan = np.full(n, np.nan)
    return dict(open=o, high=h, low=l, close=c, volume=np.ones(n), atr=np.full(n, atr),
                bbu=nan, bbl=nan, prog=np.zeros(n), vwap=nan, pdh=nan, pdl=nan, pdc=nan,
                in_sess=np.ones(n, dtype=bool), sess_id=np.ones(n, dtype=int),
                t=t0 + 60 * np.arange(n), index=pd.RangeIndex(n), bar_seconds=60)


def base_params(**kw) -> Params:
    p = Params(require_key_level=False, target_mode="r", target_r=2.0, use_rvol=False)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def test_long_entry_stop_geometry():
    # zone 100-102, ATR 10: confirm at 112, entry 113.5, stop = lo - 11.5 = 88.5
    bars = [(101, 101, 101, 101),       # zone appears at this bar's first tick
            (101, 114, 101, 114),       # up bar: O->L->H->C passes 112 (confirm) then 113.5 (fill)
            (114, 114, 80, 80)]         # falls through the stop at 88.5
    P = make_P(bars)
    sim = Sim(P, [(0, 100.0, 102.0, "BI")], base_params(), FREE)
    tr = sim.run()
    assert len(tr) == 1, tr
    t = tr[0]
    assert t.dir == 1 and abs(t.entry - 113.5) < 1e-9 and abs(t.sl0 - 88.5) < 1e-9, t
    assert t.reason == "sl" and abs(t.r + 1.0) < 1e-9, t


def test_costs_reduce_r():
    bars = [(101, 101, 101, 101), (101, 114, 101, 114), (114, 114, 80, 80)]
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BI")], base_params(), COSTLY).run()
    # risk 25; costs 2 x (0.10 + 0.25) = 0.70 -> R = -1 - 0.028
    assert abs(tr[0].r - (-1.0 - 0.70 / 25.0)) < 1e-9, tr[0]


def test_target_hit_is_2r():
    bars = [(101, 101, 101, 101), (101, 114, 101, 114), (114, 170, 114, 170)]
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BI")], base_params(), FREE).run()
    assert tr[0].reason == "tp" and abs(tr[0].r - 2.0) < 1e-9, tr[0]


def test_stop_before_target_on_down_bar():
    # one bar spans both stop and target: down bar walks O->H->L->C, so target first
    bars = [(101, 101, 101, 101), (101, 114, 101, 114), (114, 170, 50, 60)]
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BI")], base_params(), FREE).run()
    assert tr[0].reason == "tp", tr[0]
    # up bar walks O->L->H->C, so the stop comes first
    bars = [(101, 101, 101, 101), (101, 114, 101, 114), (114, 170, 50, 160)]
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BI")], base_params(), FREE).run()
    assert tr[0].reason == "sl", tr[0]


def test_cancel_when_back_in_zone():
    # confirms at 112 but turns back into the zone before reaching the 113.5 entry
    bars = [(101, 101, 101, 101), (101, 112.5, 101, 112.5), (112.5, 112.5, 101, 101),
            (101, 130, 101, 130)]
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BI")], base_params(), FREE).run()
    assert tr == [], tr


def test_no_lookahead_zone_activation():
    # the move happens in bar 0, zone only activates at bar 1 -> no trade from bar 0's move
    bars = [(101, 130, 101, 130), (130, 130, 129, 129)]
    tr = Sim(make_P(bars), [(1, 100.0, 102.0, "BI")], base_params(), FREE).run()
    assert tr == [], tr


def test_trailing_on_new_event():
    bars = [(101, 101, 101, 101), (101, 114, 101, 114), (114, 125, 114, 125),
            (125, 125, 125, 125), (125, 137, 125, 137), (137, 137, 100, 100)]
    ev = [(0, 100.0, 102.0, "BI"), (3, 124.0, 125.0, "BI")]
    tr = Sim(make_P(bars), ev, base_params(target_mode="trail"), FREE).run()
    # second zone confirms at 135 -> stop trails to 124 - 11.5 = 112.5; exit there
    assert len(tr) == 1 and abs(tr[0].exit - 112.5) < 1e-9, tr


def test_short_side():
    bars = [(101, 101, 101, 101), (101, 101, 88, 88), (88, 120, 88, 120)]
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "SI")], base_params(), FREE).run()
    t = tr[0]
    assert t.dir == -1 and abs(t.entry - 88.5) < 1e-9 and abs(t.sl0 - 113.5) < 1e-9 and t.reason == "sl", t


def test_aggressive_reversion():
    # extension 2 ATR above zone hi (102) = 122 -> short, stop 127, target 102
    bars = [(101, 101, 101, 101), (101, 101, 101, 101), (101, 101, 101, 101),
            (101, 122, 101, 122), (122, 122, 100, 100)]
    prm = base_params(enable_position=False, rev_mode="aggressive", rev_ext=2, rev_skip_if_confirmed=False)
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BS")], prm, FREE).run()
    assert len(tr) == 1, tr
    t = tr[0]
    assert t.tag == "R" and t.dir == -1 and abs(t.entry - 122) < 1e-9 and t.reason == "tp", t
    assert abs(t.r - 20.0 / 5.0) < 1e-9, t


def test_reversion_fires_with_skip_flag_when_no_position_trade():
    # regression: reaching +2 ATR always passes the +1 ATR confirmation; with position
    # trades off, the default skip flag must not block the reversion
    bars = [(101, 101, 101, 101), (101, 101, 101, 101), (101, 101, 101, 101),
            (101, 122, 101, 122), (122, 122, 100, 100)]
    prm = base_params(enable_position=False, rev_mode="aggressive", rev_ext=2)
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BS")], prm, FREE).run()
    assert len(tr) == 1 and tr[0].tag == "R", tr


def test_reversion_skipped_after_position_trade_on_that_side():
    # long position trade taken (and stopped), then the +2 ATR fade must be skipped
    bars = [(101, 101, 101, 101), (101, 114, 101, 114), (114, 114, 88, 88),
            (88, 125, 88, 125), (125, 125, 100, 100)]
    prm = base_params(rev_mode="aggressive", rev_ext=2, allow_both=False)
    tr = Sim(make_P(bars), [(0, 100.0, 102.0, "BS")], prm, FREE).run()
    assert [t.tag for t in tr] == ["P"], tr


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("ok ", f.__name__)
    print(f"{len(fns)} checks passed")
