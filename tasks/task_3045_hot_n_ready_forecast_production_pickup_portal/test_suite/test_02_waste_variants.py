"""The two waste variants on a StoreDay: standard counts donations, net excludes them."""

import pytest

from test_helpers import (
    fixtures,
    make_shift_lead_headers,
    validate_success,
)


def _day_with_one_donated_discard(client, business_date="2026-09-11"):
    """3 produced, 1 discarded with donated=true."""
    bundle = fixtures.open_day_with_stock(
        client, business_date, active_at="10:35:00Z", run_quantity=3, batch_size=10
    )
    units = fixtures.holding_units(client, bundle.run["id"])
    assert len(units) == 3
    fixtures.get_success_data(
        client.discard_hold_unit(
            units[0]["id"], {"reason": "QUALITY", "donated": True},
            make_shift_lead_headers(),
        )
    )
    return bundle


def test_waste_standard_vs_net_diverge_on_donation(client):
    """Identical raw waste data, two variants: standard reports 33.33 while net
    subtracts the donation and reports 0.0.

    "The **standard** waste percentage counts every discarded unit, donated or
    not: it is the `discarded_units` divided by `produced_units`, multiplied by
    100, rounded half-up to 2 decimal places"
    "The **net** waste percentage subtracts `donated_units` from the numerator
    before the same division and rounding, so identical raw waste data yields a
    lower percentage than the standard variant whenever donations occurred."

    Design: Difficulty/dual_variant_calc/waste_pct_standard_vs_net_diverge_on_donation
    """
    bundle = _day_with_one_donated_discard(client)

    day = fixtures.read_store_day(client, bundle.store_day["id"])
    assert day["produced_units"] == 3
    assert day["discarded_units"] == 1
    assert day["donated_units"] == 1
    assert day["waste_pct_standard"] == pytest.approx(33.33, abs=0.005)
    assert day["waste_pct_net"] == pytest.approx(0.0, abs=0.005)
    assert day["waste_pct_standard"] != day["waste_pct_net"]


def test_waste_report_carries_both_variants(client):
    """The store-day waste report exposes both percentages and the 5.0 target.

    "At any point, a `StoreManager` or `ShiftLead` can read the day's waste
    report, which returns the `store_day_id`, the four counters `produced_units`,
    `sold_units`, `discarded_units`, and `donated_units`, both percentages
    `waste_pct_standard` and `waste_pct_net`, the applicable `waste_target_pct`
    (5.0)"

    Design: Difficulty/dual_variant_calc/waste_pct_standard_vs_net_diverge_on_donation
    """
    bundle = _day_with_one_donated_discard(client, business_date="2026-09-11")

    report = validate_success(
        client.get_waste_report(bundle.store_day["id"], make_shift_lead_headers()), 200
    )
    assert report["store_day_id"] == bundle.store_day["id"]
    assert report["produced_units"] == 3
    assert report["discarded_units"] == 1
    assert report["donated_units"] == 1
    assert report["waste_pct_standard"] == pytest.approx(33.33, abs=0.005)
    assert report["waste_pct_net"] == pytest.approx(0.0, abs=0.005)
    assert report["waste_target_pct"] == pytest.approx(5.0, abs=0.005)
    assert report["target_breached"] is True
