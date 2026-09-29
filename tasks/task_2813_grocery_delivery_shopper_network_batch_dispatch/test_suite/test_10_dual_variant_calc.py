"""Difficulty rule dual_variant_calc.

Two named computations that share a formula family but read different inputs:
the ESTIMATE/FINAL authorization pair on one Order, and the ROLLING_5/LIFETIME
tier-scoring pair on one Shopper.
"""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_benefit_funds_conserved,
    assert_fields,
    assert_four_decimals,
    assert_money_is_integer,
    read_customer,
    read_line,
    read_order,
    read_shopper,
)
from test_helpers.constants import (
    CLOCK_0800,
    TIER_PLATINUM,
    TIER_STANDARD,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    make_customer_headers,
    make_shopper_headers,
)


def _split_tender_world(api):
    """Retailer/items/customer/shopper plus Order O1 placed and shopped.

    Mirrors the setup_api_calls of the design instance: three lines (I1 EACH x3,
    I2 PER_LB @ 2.0 lb, I3 EACH x1) on an EBT-requested order with a 500-cent
    tip, inside a batch the shopper has claimed and started, with L2 weighed at
    2.3 lb instead of the requested 2.0 lb.
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api,
        catalog_markup_pct=0.15,
        parity_disclosure_required=True,
        ebt_snap_enabled=True,
        concurrent_shopper_cap=2,
    )
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    i2 = fx.make_catalog_item_per_lb(
        api, r1, sku="SKU-LB-EBT", name="Ground Coffee Bulk",
        in_store_price_cents=599, is_ebt_eligible=True, estimated_weight_lb=2.0,
    )
    i3 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-NOEBT", name="Laundry Detergent",
        in_store_price_cents=1200, is_ebt_eligible=False, unit_weight_lb=2.5,
    )
    customer = fx.make_customer(api, ebt_snap_balance_cents=5000)
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
    c1 = customer["id"]
    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=12.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=True,
        tip_amount_cents=500,
    )
    l1 = fx.add_line_each(api, order["id"], c1, i1["id"], 3)
    l2 = fx.add_line_per_lb(api, order["id"], c1, i2["id"], 2.0)
    l3 = fx.add_line_each(api, order["id"], c1, i3["id"], 1)
    placed = fx.submit_order(api, order["id"], c1)
    return {
        "retailer": retailer,
        "items": (i1, i2, i3),
        "customer": customer,
        "shopper": shopper,
        "order": order,
        "placed": placed,
        "lines": (l1, l2, l3),
    }


def _shop_to_the_register(api, world):
    batch = fx.make_batch(
        api,
        service_area_code="SF-01",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, batch["id"], world["order"]["id"])
    fx.dispatch(api, batch["id"])
    shopper_id = world["shopper"]["id"]
    fx.claim(api, batch["id"], shopper_id)
    fx.start_shopping(api, batch["id"], shopper_id)
    l1, l2, l3 = world["lines"]
    fx.pick_each(api, l1["id"], shopper_id, 3)
    fx.pick_weighted(api, l2["id"], shopper_id, 2.3)
    fx.pick_each(api, l3["id"], shopper_id, 1)
    return batch


def test_estimate_variant_holds_a_buffered_ceiling_and_an_unbuffered_ebt_slice(api):
    """PRD 3.2: "`authorization_ceiling_cents` is built by multiplying
    `estimated_subtotal_cents` by 1.15 ... then adding the platform service fee
    of 399 cents and the order's current `tip_amount_cents`" and
    "`authorized_ebt_cents` is the smaller of the customer's current
    `ebt_snap_balance_cents` and that eligible estimate - the benefit slice is
    never buffered and never covers fees or tip."

    1380 + 1378 + 1380 = 4138; round(4138 * 1.15) = 4759, + 399 + 500 = 5658;
    eligible estimate 1380 + 1378 = 2758 < balance 5000; card = 5658 - 2758.

    Design: Difficulty/dual_variant_calc/order_authorization_estimate_vs_final_capture
    """
    world = _split_tender_world(api)
    placed = world["placed"]
    assert_money_is_integer(
        placed,
        "estimated_subtotal_cents",
        "authorization_ceiling_cents",
        "authorized_ebt_cents",
        "authorized_card_cents",
    )
    assert_fields(
        placed,
        estimated_subtotal_cents=4138,
        authorization_ceiling_cents=5658,
        authorized_ebt_cents=2758,
        authorized_card_cents=2900,
        payment_status="AUTHORIZED",
        fulfillment_status="PLACED",
    )


def test_final_variant_reprices_the_scale_and_caps_ebt_at_the_authorized_ceiling(api):
    """PRD 3.7: "`ebt_captured_cents` is the smallest of three numbers: the
    customer's live `ebt_snap_balance_cents` at this moment, that
    benefit-eligible cart money, and the order's `authorized_ebt_cents` ceiling
    fixed at placement" and "`card_captured_cents` is then the grand total minus
    `ebt_captured_cents`".

    L2 scans at 2.3 lb so its money is round(689 * 2.3) = 1585 and the captured
    subtotal becomes 4345; eligible cart money 1380 + 1585 = 2965, so the
    three-way minimum pins EBT at the authorized 2758 and the card carries
    4345 + 399 + 500 - 2758 = 2486, which is not the 2900 authorized.

    Design: Difficulty/dual_variant_calc/order_authorization_estimate_vs_final_capture
    """
    world = _split_tender_world(api)
    batch = _shop_to_the_register(api, world)
    shopper_headers = make_shopper_headers(world["shopper"]["id"])
    customer_headers = make_customer_headers(world["customer"]["id"])
    fx.checkout(api, batch["id"], world["shopper"]["id"])

    weighed = read_line(api, world["lines"][1]["id"], shopper_headers)
    assert_fields(weighed, final_price_cents=1585, final_weight_lb=2.3, status="PICKED")

    order = read_order(api, world["order"]["id"], customer_headers)
    assert_fields(
        order,
        captured_subtotal_cents=4345,
        ebt_captured_cents=2758,
        card_captured_cents=2486,
        estimated_subtotal_cents=4138,
        authorized_card_cents=2900,
        payment_status="CAPTURED",
    )
    assert order["card_captured_cents"] != order["authorized_card_cents"], (
        "the FINAL variant must not simply echo the ESTIMATE variant's card figure"
    )
    assert order["captured_subtotal_cents"] != order["estimated_subtotal_cents"], (
        "the scale reading must move the captured subtotal off the estimate"
    )

    customer = read_customer(api, world["customer"]["id"], customer_headers)
    assert_fields(
        customer, ebt_snap_balance_cents=2242, ebt_captured_total_cents=2758
    )
    assert_benefit_funds_conserved(customer, 5000)


def test_rolling_and_lifetime_averages_read_different_windows_of_one_history(api):
    """PRD 3.3: "The **ROLLING_5** variant looks only at the shopper's five most
    recent rating rows ... The mean of those rows' `stars`, rounded half up to
    four decimal places, is stored as `rolling_recent_avg`" while "The
    **LIFETIME** variant takes the mean of `stars` over every rating row the
    shopper has ever received".

    The history [1,1,1,1,5,5,5,5] gives a rolling mean over (1,5,5,5,5) of 4.2
    and a lifetime mean over all eight of 3.0.

    Design: Difficulty/dual_variant_calc/shopper_tier_rolling_vs_lifetime_divergence
    """
    fx.set_clock(api, CLOCK_0800)
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
    scored = fx.backfill_ratings(api, shopper["id"], [1, 1, 1, 1, 5, 5, 5, 5])

    assert_four_decimals(scored["rolling_recent_avg"], 4.2, "rolling_recent_avg")
    assert_four_decimals(scored["lifetime_rating_avg"], 3.0, "lifetime_rating_avg")
    assert scored["rolling_recent_avg"] != scored["lifetime_rating_avg"], (
        "the two variants must not collapse onto one average"
    )


def test_rolling_score_gates_dispatch_while_lifetime_score_only_reports(api):
    """PRD 3.3: "The **score** is 0.70 times the quality component plus 0.30
    times the reliability component, rounded half up to four decimal places.
    Applying that to `rolling_recent_avg` produces `rolling_tier_score`; applying
    it to `lifetime_rating_avg` produces `lifetime_tier_score`." and "A shopper
    can therefore be `PLATINUM` for batch access while reading only `STANDARD` on
    the lifetime books".

    0.70 * (4.2 - 1) / 4 + 0.30 * 1 = 0.8600 -> PLATINUM;
    0.70 * (3.0 - 1) / 4 + 0.30 * 1 = 0.6500 -> STANDARD.

    Design: Difficulty/dual_variant_calc/shopper_tier_rolling_vs_lifetime_divergence
    """
    fx.set_clock(api, CLOCK_0800)
    shopper = fx.make_shopper(api, service_area_code="SF-01", vehicle_capacity_units=10)
    fx.backfill_ratings(api, shopper["id"], [1, 1, 1, 1, 5, 5, 5, 5])

    stored = read_shopper(api, shopper["id"], ADMIN_HEADERS)
    assert_four_decimals(stored["rolling_tier_score"], 0.8600, "rolling_tier_score")
    assert_four_decimals(stored["lifetime_tier_score"], 0.6500, "lifetime_tier_score")
    assert_fields(stored, tier=TIER_PLATINUM, lifetime_tier=TIER_STANDARD)
    assert stored["tier"] != stored["lifetime_tier"], (
        "identical input data must still separate the gating tier from the display tier"
    )
