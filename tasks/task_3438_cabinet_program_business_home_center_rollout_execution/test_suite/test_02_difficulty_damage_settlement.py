"""Damage settlement: nested min cap, age tier, and the approval clock (PRD §3.6)."""

from test_helpers import WEEK_NEXT, order_line
from test_helpers import fixtures


def _delivered_qty2_world(api):
    """VOLUME dealer, 0% discount, F1 at 10000 (unit net 9500); one qty-2 order
    delivered at the default clock."""
    world = fixtures.setup_delivered_order(
        api,
        order_overrides={"lines": [order_line(quantity=2)]},
        slot_overrides={"week": WEEK_NEXT, "capacity_units": 10},
    )
    return world


def test_settlement_age_tier_three_days_full_ten_days_late(api):
    """The same line and quantity settle at 9500 on day 3 and 7600 on day 10.

    PRD §3.6: "The base amount is the lesser of two figures: the claimed quantity times the order line's `unit_invoiced_cents` — falling back to `unit_quoted_cents` when that line has not yet been invoiced — and the claimed quantity times the family's `standard_price_cents` from the line the order was priced against, scaled by 1.20 and rounded half-up; the cap keeps a settlement within 120 percent of list price."
    PRD §3.6: "the base stands at full value when that age is 7 days or fewer, and is scaled by 0.8 when it is older."
    Design: Difficulty/combinatorial_formula/damage_settlement_min_cap_and_age_tier
    """
    world = _delivered_qty2_world(api)

    fixtures.reset_clock(api, "2026-09-04T00:00:00Z")
    claim1 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    claim1 = fixtures.approve_claim(api, claim1["id"], "CREDIT")

    fixtures.reset_clock(api, "2026-09-11T00:00:00Z")
    claim2 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    claim2 = fixtures.approve_claim(api, claim2["id"], "CREDIT")

    # base = min(1x9500, round(1x10000x1.20)) = 9500; day 3 -> x1.0, day 10 -> x0.8.
    assert claim1["status"] == "APPROVED"
    assert claim1["settlement_cents"] == 9500
    assert claim2["settlement_cents"] == 7600
    assert claim1["settlement_cents"] != claim2["settlement_cents"]


def test_settlement_age_boundary_seven_days_full_eight_days_late(api):
    """Age 7 days exactly settles full; age 8 days crosses into the 0.8 factor.

    PRD §3.6: "An age factor then applies, based on the number of whole days between the shipment's `delivered_at` and the approval instant: the base stands at full value when that age is 7 days or fewer, and is scaled by 0.8 when it is older."
    PRD §3.6: "The final `settlement_cents` is the factored base rounded half-up to whole cents."
    Design: Difficulty/combinatorial_formula/damage_settlement_min_cap_and_age_tier
    """
    world = _delivered_qty2_world(api)

    fixtures.reset_clock(api, "2026-09-08T00:00:00Z")
    claim_day7 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    claim_day7 = fixtures.approve_claim(api, claim_day7["id"], "CREDIT")

    fixtures.reset_clock(api, "2026-09-09T00:00:00Z")
    claim_day8 = fixtures.file_claim(api, world["shipment"], world["order"], claimed_qty=1)
    claim_day8 = fixtures.approve_claim(api, claim_day8["id"], "CREDIT")

    assert claim_day7["settlement_cents"] == 9500
    assert claim_day8["settlement_cents"] == 7600
