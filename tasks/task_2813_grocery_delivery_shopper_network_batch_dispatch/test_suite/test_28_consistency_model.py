"""Corner section consistency_model.

One walk that checks the write responses themselves rather than what a later read
eventually settles on: nothing in this API needs a second call to converge.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_fields,
    assert_instant_field,
    assert_one_decimal,
    read_batch,
    read_line,
    read_order,
)
from test_helpers.constants import (
    CLOCK_0800,
    LINE_REPLACED,
    PAYMENT_AUTHORIZED,
    REPLACEMENT_APPROVED,
    REPLACEMENT_RESOLUTION_LINE_REPLACED,
    TIER_PROBATION,
)
from test_helpers.test_users import ADMIN_HEADERS, make_customer_headers


def test_every_write_response_already_carries_its_derived_effects(api):
    """PRD 2.6: "Whenever any input to a derived field changes, the field is recomputed
    from its definition in the same operation, and the recomputation is a mutation of
    the owning row - it refreshes that row's `updated_at` and increases its
    `version`."

    So the submit response already carries the authorization it just computed
    (rhu(1035 * 1.15) = 1190, + 399 + 0 = 1589), the attachment response already
    carries its frozen `units` of 2, the first read after the attachment already shows
    the re-derived aggregates (2 units, 1.0 + 2.0 = 3.0 lb, the member's 11:00
    deadline), and the approval response already reports the resolution it applied.
    Every follow-up read here is asserted to add nothing.

    Design: Corner/consistency_model/every_write_response_already_carries_its_derived_effects
    """
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    ordered_item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    substitute_item = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-SUB", name="Bagged Rice",
        in_store_price_cents=500, is_ebt_eligible=True, unit_weight_lb=2.0,
    )
    assert_fields(ordered_item, catalog_price_cents=460)
    assert_fields(substitute_item, catalog_price_cents=575)

    customer = fx.make_customer(api, display_name="Dana Ortiz", card_last4="4242")
    c1 = customer["id"]
    customer_headers = make_customer_headers(c1)
    shopper = fx.make_shopper(
        api, display_name="Sam Reyes", service_area_code="SF-42",
        vehicle_capacity_units=10,
    )
    s1 = shopper["id"]

    order = fx.make_draft_order(
        api, c1, r1,
        delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False,
        tip_amount_cents=0,
    )
    replaced_line = fx.add_line_each(
        api, order["id"], c1, ordered_item["id"], 1
    )
    fx.add_line_each(api, order["id"], c1, substitute_item["id"], 1)

    submitted = validate_success(api.submit_order(order["id"], customer_headers), 200)
    assert_fields(
        submitted,
        estimated_subtotal_cents=1035,
        authorization_ceiling_cents=1589,
        authorized_ebt_cents=0,
        authorized_card_cents=1589,
        payment_status=PAYMENT_AUTHORIZED,
    )
    reread = read_order(api, order["id"], customer_headers)
    assert_fields(
        reread,
        estimated_subtotal_cents=submitted["estimated_subtotal_cents"],
        authorization_ceiling_cents=submitted["authorization_ceiling_cents"],
        authorized_ebt_cents=submitted["authorized_ebt_cents"],
        authorized_card_cents=submitted["authorized_card_cents"],
        payment_status=submitted["payment_status"],
        version=submitted["version"],
    )

    batch = fx.make_batch(
        api, service_area_code="SF-42",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    membership = validate_success(
        api.add_order_to_batch(
            batch["id"],
            f.batch_order_payload(order["id"], batch["version"]),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(membership, sequence_no=1, units=2, order_id=order["id"])

    composed = read_batch(api, batch["id"], ADMIN_HEADERS)
    assert_fields(composed, total_units=2)
    assert_one_decimal(composed["total_weight_lb"], 3.0, "total_weight_lb")
    assert_one_decimal(composed["total_distance_mi"], 3.0, "total_distance_mi")
    assert_instant_field(composed, "delivery_deadline", "2026-08-01T11:00:00Z")

    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s1)
    fx.start_shopping(api, batch["id"], s1)
    proposal = fx.propose_replacement(
        api, batch["id"], replaced_line["id"], substitute_item["id"], s1
    )
    approved = validate_success(
        api.approve_replacement_request(proposal["id"], customer_headers), 200
    )
    assert_fields(
        approved,
        status=REPLACEMENT_APPROVED,
        resolution_effect=REPLACEMENT_RESOLUTION_LINE_REPLACED,
    )

    assert_fields(
        read_line(api, replaced_line["id"], customer_headers),
        catalog_item_id=substitute_item["id"],
        status=LINE_REPLACED,
        unit_price_cents_snapshot=575,
        final_price_cents=575,
    )
