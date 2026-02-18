from pathlib import Path

from shipping_agent.engine import ShippingRateEngine
from shipping_agent.models import Query, ShippingRate


def test_query_matches_fixed_and_third_party():
    rates = [
        ShippingRate(
            carrier="UPS",
            service="Saver",
            origin_country="PT",
            destination_country="ES",
            zone="2",
            weight_kg=1.0,
            price=10.0,
            currency="EUR",
            source_file=Path("ups.xlsx"),
            origin_type="fixed",
        ),
        ShippingRate(
            carrier="FEDEX",
            service="Priority",
            origin_country="*",
            destination_country="ES",
            zone="2",
            weight_kg=1.0,
            price=12.0,
            currency="EUR",
            source_file=Path("fedex.pdf"),
            origin_type="third_party",
        ),
    ]

    engine = ShippingRateEngine(rates)
    result = engine.query(Query(origin_country="PT", destination_country="ES", weight_kg=0.5))

    assert len(result) == 2
    assert set(result["carrier"].tolist()) == {"UPS", "FEDEX"}


def test_query_picks_smallest_weight_break_above_request():
    rates = [
        ShippingRate(
            carrier="UPS",
            service="Saver",
            origin_country="PT",
            destination_country="FR",
            zone="3",
            weight_kg=1.0,
            price=11.0,
            currency="EUR",
            source_file=Path("ups.xlsx"),
            origin_type="fixed",
        ),
        ShippingRate(
            carrier="UPS",
            service="Saver",
            origin_country="PT",
            destination_country="FR",
            zone="3",
            weight_kg=2.0,
            price=15.0,
            currency="EUR",
            source_file=Path("ups.xlsx"),
            origin_type="fixed",
        ),
    ]

    engine = ShippingRateEngine(rates)
    result = engine.query(Query(origin_country="PT", destination_country="FR", weight_kg=1.4))

    assert len(result) == 1
    assert result.iloc[0]["weight_kg"] == 2.0
