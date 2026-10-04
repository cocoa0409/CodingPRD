"""Retail revenue recognition: the two-posting policy and its per-line arithmetic."""
import pytest

from test_helpers import api_client, validate_success, validate_error, ApiErrorId
from test_helpers import factories as f
from test_helpers.fixtures import (
    MANAGER, LEAD, ADMIN,
    create_item, setup_open_day, close_store_day, get_receipt, get_brand,
    reconcile_receipt, create_receipt, create_shift, create_check,
)

BOAT, DECOR, LANTERN = "ITM-BOAT-6400", "ITM-DECOR-2400", "ITM-LANTERN-1200"


def _attached_check(loc, day, restaurant_subtotal_cents=11200):
    """A PENDING dining check the ticket rides on.

    PRD §3.3: the divisor-7 provisional rule applies only "On a ticket that rides
    on a dining check"; a standalone ticket carries no staging block at all. Any
    expectation of the cleared-value deduction therefore requires the ticket to
    name a check.
    """
    shift = create_shift(loc["id"], employee_id="E-101",
                         start_utc="2026-09-01T09:00:00Z", end_utc="2026-09-01T13:00:00Z",
                         workcode="CASHIER")
    return create_check(loc["id"], day["id"], shift["id"],
                        restaurant_subtotal_cents=restaurant_subtotal_cents)


def _three_items():
    """Items whose effective prices match the line set: 6400, 2400, 1200."""
    boat = create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)
    decor = create_item(sku=DECOR, name="Harvest Wall Plaque",
                        theme_code="SUMMER", unit_retail_cents=2400, unit_cost_cents=900)
    lantern = create_item(sku=LANTERN, name="Tin Lantern Ornament",
                          theme_code="WINTER_HOLIDAY", unit_retail_cents=1200, unit_cost_cents=400)
    return boat, decor, lantern


def _three_line_set(boat, decor, lantern):
    """Gross per line: 6400, 2400, 1200 - 10%. Line kinds all enter the block."""
    return [
        f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL"),
        f.retail_line(decor["id"], 1, 2400, 0.0, "RETAIL"),
        f.retail_line(lantern["id"], 1, 1200, 0.10, "SEASONAL_DECOR"),
    ]


# ==========================================================================
# Difficulty queue A — dual_variant_calc
# ==========================================================================

def test_reconcile_posts_the_provisional_variant_of_the_retail_block(api):
    """PRD §3.3: "On a ticket that rides on a dining check the provisional figure is the
    base block minus the staging block divided by seven, that quotient rounded half-up to
    two decimal places."
    PRD §2.5: "whenever a calculation sums per-line or per-bucket values, each component
    is rounded first and the rounded components are then summed."

    Design: Difficulty/dual_variant_calc/revenue_recognition_provisional_versus_final
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "PROVISIONAL_THEN_FINAL",
                         "food_storage_corridor_units": 310}
    )
    boat, decor, lantern = _three_items()
    check = _attached_check(loc, day)
    receipt = create_receipt(loc["id"], day["id"], _three_line_set(boat, decor, lantern),
                             "R-1042-0001", guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])

    data = validate_success(api.reconcile_receipt(receipt["id"], LEAD))

    assert data["status"] == "RECONCILED"
    assert data["provisional_retail_cents"] == 9372, (
        "base block 9880 less round_half_up(3558 / 7) == 508"
    )


def test_store_day_close_overwrites_recognized_with_the_final_variant(api):
    """PRD §3.4: "the provisional figure is written at reconciliation, the final figure
    overwrites the recognized amount at store-day close"
    PRD §3.4: "minus the staging block divided by three, that quotient rounded half-up to two
    decimal places"

    Design: Difficulty/dual_variant_calc/revenue_recognition_provisional_versus_final
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "PROVISIONAL_THEN_FINAL",
                         "food_storage_corridor_units": 310}
    )
    boat, decor, lantern = _three_items()
    check = _attached_check(loc, day)
    receipt = create_receipt(loc["id"], day["id"], _three_line_set(boat, decor, lantern),
                             "R-1042-0001", guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])
    reconcile_receipt(receipt["id"])
    current = api.get_store_day(day["id"], MANAGER).json()["data"]

    validate_success(api.close_store_day(day["id"], {"expected_store_day_version": current["version"]}, MANAGER))
    data = get_receipt(receipt["id"])

    assert data["recognized_retail_cents"] == 8694, (
        "base block 9880 less round_half_up(3556.80 / 3) == 9880 - 1185.60 == 8694.40 -> 8694"
    )
    assert data["recognition_delta_cents"] == -678
    assert data["provisional_retail_cents"] == 9372


# ==========================================================================
# Difficulty queue A — combinatorial_formula
# ==========================================================================

def test_per_line_rounding_order_sets_the_provisional_deduction(api):
    """PRD §2.5: "whenever a calculation sums per-line or per-bucket values, each
    component is rounded first and the rounded components are then summed."
    PRD §3.3: "A sale-staging block is then formed by taking each net amount, multiplying
    it by the staging factor of 0.36, and rounding that product half-up to two decimal
    places, and summing the rounded results."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_flips_the_receipt_clearing_deduction
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    )
    boat = create_item(sku="ITM-BOAT-9600", name="Large Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=9600, unit_cost_cents=2400)
    decor = create_item(sku=DECOR, name="Harvest Wall Plaque",
                        theme_code="SUMMER", unit_retail_cents=2400, unit_cost_cents=900)
    lantern = create_item(sku=LANTERN, name="Tin Lantern Ornament",
                          theme_code="WINTER_HOLIDAY", unit_retail_cents=1200, unit_cost_cents=400)
    lines = [
        f.retail_line(boat["id"], 1, 9600, 0.0, "RETAIL"),
        f.retail_line(decor["id"], 1, 2400, 0.0, "RETAIL"),
        f.retail_line(lantern["id"], 1, 1200, 0.10, "RETAIL"),
    ]
    check = _attached_check(loc, day)
    receipt = create_receipt(loc["id"], day["id"], lines, "R-1042-0003",
                             guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])

    data = validate_success(api.reconcile_receipt(receipt["id"], LEAD))

    assert data["provisional_retail_cents"] == 12407, (
        "base block 13080 less round_half_up(4709 / 7) == 673"
    )


def test_final_only_policy_writes_the_final_variant_with_a_zero_delta(api):
    """PRD §3.4: "Under `FINAL_ONLY` the provisional posting is skipped and the final
    figure is written straight to `recognized_retail_cents`, with the difference figure
    `recognition_delta_cents` left at zero because there is only ever one posting."
    PRD §3.4: "the final recognized amount is the base block ... minus the staging block
    divided by three"

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_flips_the_receipt_clearing_deduction
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    )
    boat = create_item(sku="ITM-BOAT-9600", name="Large Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=9600, unit_cost_cents=2400)
    decor = create_item(sku=DECOR, name="Harvest Wall Plaque",
                        theme_code="SUMMER", unit_retail_cents=2400, unit_cost_cents=900)
    lantern = create_item(sku=LANTERN, name="Tin Lantern Ornament",
                          theme_code="WINTER_HOLIDAY", unit_retail_cents=1200, unit_cost_cents=400)
    lines = [
        f.retail_line(boat["id"], 1, 9600, 0.0, "RETAIL"),
        f.retail_line(decor["id"], 1, 2400, 0.0, "RETAIL"),
        f.retail_line(lantern["id"], 1, 1200, 0.10, "RETAIL"),
    ]
    check = _attached_check(loc, day)
    receipt = create_receipt(loc["id"], day["id"], lines, "R-1042-0003",
                             guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])

    data = validate_success(api.reconcile_receipt(receipt["id"], LEAD))

    assert data["recognized_retail_cents"] == 11510, (
        "base block 13080 less round_half_up(4709 / 3) == 1570"
    )
    assert data["recognition_delta_cents"] == 0


# ==========================================================================
# Corner queue B — entities
# ==========================================================================

def test_receipt_computed_revenue_fields_ignore_client_supplied_values(api):
    """PRD §3.4: "Reconciliation recomputes both `provisional_retail_cents` and
    `recognized_retail_cents`"
    PRD §3.3: "The new ticket begins in `DRAFT` status, and its `provisional_retail_cents`
    is computed immediately."

    Design: Corner/entities/receipt_computed_fields_input_ignored
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    )
    boat = create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)
    check = _attached_check(loc, day)
    payload = f.create_receipt_payload(
        loc["id"], day["id"], "R-1042-0040",
        [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
        guest_check_id=check["id"], expected_guest_check_version=check["version"],
    )
    payload.update({"provisional_retail_cents": 1, "recognized_retail_cents": 1,
                    "recognition_delta_cents": 1, "status": "RECONCILED"})

    data = validate_success(api.create_receipt(payload, LEAD), 201)

    assert data["status"] == "DRAFT"
    assert data["provisional_retail_cents"] == 6071, (
        "base block 6400 less round_half_up(2304 / 7) == 329"
    )
    assert data["provisional_retail_cents"] != 1


def test_receipt_system_fields_are_server_stamped(api):
    """PRD §2.4: "This `id` is a server-minted UUID string with no type prefix, no entity
    name embedded in it, and no human-readable component"
    PRD §2.4: "`version` is an integer that begins at its initial value and increments by
    one on every mutation of the resource"

    Design: Corner/entities/receipt_system_fields_input_ignored
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    )
    boat = create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)
    payload = f.create_receipt_payload(
        loc["id"], day["id"], "R-1042-0041",
        [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
    )
    payload.update({"id": "11111111-1111-4111-8111-111111111111", "version": 99})

    data = validate_success(api.create_receipt(payload, LEAD), 201)

    assert data["id"] != "11111111-1111-4111-8111-111111111111"
    assert data["version"] == 1


# ==========================================================================
# Corner queue B — cross_cutting_layers
# ==========================================================================

def test_revenue_attribution_reports_both_variants_and_their_delta(api):
    """PRD §3.9: "The day's revenue attribution is exposed as a single computed read that
    takes a required `store_day_id` and an optional `variant`, and reports the day's
    `provisional_retail_cents`, its `recognized_retail_cents`, its
    `recognition_delta_cents`"

    Design: Corner/cross_cutting_layers/dual_variant_revenue_diverges_on_the_same_receipt
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "PROVISIONAL_THEN_FINAL",
                         "food_storage_corridor_units": 310}
    )
    boat = create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)
    check = _attached_check(loc, day)
    receipt = create_receipt(loc["id"], day["id"],
                             [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                             "R-1042-0001", guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])
    reconcile_receipt(receipt["id"])

    resp = api.get_revenue_attribution(MANAGER, {"store_day_id": day["id"], "variant": "provisional"})
    data = validate_success(resp)

    assert data["provisional_retail_cents"] == 6071
    assert data["provisional_retail_cents"] != data["recognized_retail_cents"], (
        "the two variants must not collapse to one value"
    )
    assert data["recognized_retail_cents"] == 5632
    assert data["receipt_count"] == 1


def test_brand_recognition_policy_flag_changes_the_posted_receipt_behaviour(api):
    """PRD §3.4: "Under `PROVISIONAL_THEN_FINAL` the provisional figure is written at
    reconciliation, the final figure overwrites the recognized amount at store-day close"
    PRD §3.7: "A `PlatformAdmin` later updates the brand to change any of those
    configuration values"

    Design: Corner/cross_cutting_layers/brand_recognition_policy_flag_changes_receipt_behaviour
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    )
    boat = create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)
    check = _attached_check(loc, day)
    receipt = create_receipt(loc["id"], day["id"],
                             [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                             "R-1042-0001", guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])
    reconciled = reconcile_receipt(receipt["id"])
    assert reconciled["recognition_delta_cents"] == 0

    data = validate_success(
        api.update_brand(brand["id"], {"retail_recognition_policy": "PROVISIONAL_THEN_FINAL"}, ADMIN)
    )
    assert data["retail_recognition_policy"] == "PROVISIONAL_THEN_FINAL"


# ==========================================================================
# Corner queue B — endpoints
# ==========================================================================

def test_recognizing_revenue_is_gated_on_the_open_fiscal_period(api):
    """PRD §3.4: "Once the period has been closed, recognition is refused with
    `ERR_FISCAL_PERIOD_CLOSED` (HTTP 422), a check that sits at priority 5"
    PRD §3.7: "the `fiscal_period_status`, which is how a reporting period is opened or
    closed"

    Design: Corner/endpoints/brand_close_and_reopen_the_fiscal_period_gates_revenue_recognition
    """
    brand, loc, day = setup_open_day(
        brand_overrides={"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    )
    boat = create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)
    receipt = create_receipt(loc["id"], day["id"],
                             [f.retail_line(boat["id"], 1, 6400, 0.0, "RETAIL")],
                             "R-1042-0081")
    validate_success(api.update_brand(brand["id"], {"fiscal_period_status": "CLOSED"}, ADMIN))

    validate_error(api.reconcile_receipt(receipt["id"], LEAD),
                   ApiErrorId.ERR_FISCAL_PERIOD_CLOSED.value)

    validate_success(api.update_brand(brand["id"], {"fiscal_period_status": "OPEN"}, ADMIN))
    data = validate_success(api.reconcile_receipt(receipt["id"], LEAD))
    assert data["status"] == "RECONCILED"