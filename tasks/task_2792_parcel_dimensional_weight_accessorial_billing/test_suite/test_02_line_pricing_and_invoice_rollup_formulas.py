"""The three multi-input pricing formulas, each pinned on its own ordering.

Transportation pricing combines a zone-and-weight-band lookup, a per-package
floor and a surcharge window in a fixed order; the dimensional pound count
rounds each dimension before multiplying; and the invoice tier discount reads
the pre-discount transportation subtotal and is then frozen.
"""

import pytest

from test_helpers import (
    BILLING_OPS_HEADERS,
    FULL_TIER_TABLE,
    OVERSIZE_DECLARED,
    RESIDENTIAL_OVERRIDE_540,
    ROUNDING_DECLARED,
    active_surcharge_window,
    apply_adjustment,
    assert_lbs,
    assert_money_equals,
    delivered_shipment,
    induct_shipment,
    issued_invoice,
    line_for_shipment,
    open_invoice,
    propose_adjustment,
    refresh_invoice,
    refresh_invoice_line,
    shipper_with_active_contract,
    shipper_with_multi_zone_contract,
    validate_success,
)


# ---------------------------------------------------------------------------
# The floored transportation charge plus a scoped demand window
# ---------------------------------------------------------------------------
@pytest.fixture
def floored_parcel_under_demand_window(api):
    """A 6 x 6 x 4 inch, 0.4 lb EXPRESS parcel inside an ACTIVE demand window.

    Two dimensional pounds at 380 cents is only 760 cents, so the 1195 cent
    per-package floor decides the transportation charge.
    """
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={"tier_discount_table": list(FULL_TIER_TABLE)},
        with_ground=False,
    )
    active_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-09-01",
        per_package_cents=150,
        oversize_add_cents=0,
        service_level_id=shipper.service_level_ids["EXPRESS"],
    )
    parcel = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-P5-0005",
        zone=2,
        declared_length_in=6,
        declared_width_in=6,
        declared_height_in=4,
        declared_weight_lbs=0.4,
    )
    return {"shipper": shipper, "parcel": parcel}


def test_minimum_charge_floor_replaces_the_rated_charge_without_absorbing_the_surcharge(
    api, floored_parcel_under_demand_window
):
    """PRD §3.6: "The per-package floor then applies **to the transportation charge alone, and before any surcharge**: `transportation_base_cents` is the greater of the uncapped charge and the governing contract's `min_charge_cents`."
    PRD §3.6: "This ordering matters — surcharges are never subject to the minimum-charge floor, and a floored parcel does not have its surcharges absorbed into the floor."
    PRD §3.6: "The candidate windows are every surcharge window whose `status` is `ACTIVE`, whose half-open range contains the shipment's `pickup_date` — meaning the date is on or after `start_date` and strictly before `end_date` — and whose scope matches, meaning either `service_level_id` is null or it equals the shipment's `service_level_id`."

    Design: Difficulty/combinatorial_formula/transportation_charge_zone_break_floor_and_window_mode_a
    """
    parcel = floored_parcel_under_demand_window["parcel"]
    shipment = parcel.shipment
    assert shipment["declared_cube_in3"] == 144, (
        f"6 x 6 x 4 inches must cube to 144 in3, got {shipment['declared_cube_in3']}"
    )
    assert_lbs(shipment["preliminary_dim_weight_lbs"], 2, "preliminary_dim_weight_lbs")
    assert_lbs(shipment["billable_weight_lbs"], 2, "billable_weight_lbs")
    assert shipment["preliminary_basis"] == "DIMENSIONAL"

    preview = validate_success(
        api.get_billing_preview(parcel.shipment_id, BILLING_OPS_HEADERS)
    )
    assert_money_equals(preview["rate_cents_per_lb"], 380, "rate_cents_per_lb")
    assert_money_equals(
        preview["transportation_base_cents"], 1195, "transportation_base_cents"
    )
    assert preview["transportation_base_cents"] != 760, (
        "the 1195 cent floor must replace the 760 cent rated charge"
    )
    assert_money_equals(preview["surcharge_cents"], 150, "surcharge_cents")
    assert_money_equals(preview["accessorial_total_cents"], 0, "accessorial_total_cents")
    assert_money_equals(preview["line_total_cents"], 1345, "line_total_cents")


def test_floored_line_rolls_up_into_the_invoice_transportation_subtotal(
    api, floored_parcel_under_demand_window
):
    """PRD §3.6: "The line's `base_line_total_cents` is `transportation_base_cents` plus `surcharge_cents` plus `accessorial_total_cents`."
    PRD §3.6: "`transportation_subtotal_cents` is the sum, over the invoice's lines, of `transportation_base_cents` plus `surcharge_cents`."
    PRD §3.6: "When no row qualifies, `tier_discount_bps` is 0."

    Design: Difficulty/combinatorial_formula/transportation_charge_zone_break_floor_and_window_mode_a
    """
    shipper = floored_parcel_under_demand_window["shipper"]
    parcel = floored_parcel_under_demand_window["parcel"]
    invoice = open_invoice(api, shipper, [parcel.shipment_id])
    line = line_for_shipment(api, invoice.invoice_id, parcel.shipment_id)

    assert_money_equals(line["transportation_base_cents"], 1195, "transportation_base_cents")
    assert_money_equals(line["surcharge_cents"], 150, "surcharge_cents")
    assert_money_equals(line["accessorial_total_cents"], 0, "accessorial_total_cents")
    assert_money_equals(line["base_line_total_cents"], 1345, "base_line_total_cents")

    body = invoice.invoice
    assert_money_equals(
        body["transportation_subtotal_cents"], 1345, "transportation_subtotal_cents"
    )
    assert_money_equals(
        body["accessorial_subtotal_cents"], 0, "accessorial_subtotal_cents"
    )
    assert_money_equals(body["gross_charges_cents"], 1345, "gross_charges_cents")
    assert body["tier_discount_bps"] == 0, (
        f"1345 cents qualifies for no tier, got {body['tier_discount_bps']} bps"
    )
    assert_money_equals(body["tier_discount_cents"], 0, "tier_discount_cents")
    assert_money_equals(body["net_amount_cents"], 1345, "net_amount_cents")


# ---------------------------------------------------------------------------
# Per-dimension rounding before the multiplication
# ---------------------------------------------------------------------------
@pytest.fixture
def per_dimension_rounding_parcel(api):
    """An 18.4 x 12.6 x 10.5 inch, 9.2 lb residential EXPRESS parcel."""
    shipper = shipper_with_active_contract(
        api,
        account_number="SH-1001",
        contract_kwargs={"accessorial_rate_overrides": dict(RESIDENTIAL_OVERRIDE_540)},
        with_ground=False,
    )
    parcel = induct_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-ROUND-1",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    return {"shipper": shipper, "parcel": parcel}


def test_each_dimension_rounds_before_the_cube_multiplication(
    api, per_dimension_rounding_parcel
):
    """PRD §2.6: "Each of the three dimensions of a measurement set is individually rounded half up to a whole number of inches *before* any multiplication."
    PRD §3.3: "The three whole-inch values are then multiplied together to give `declared_cube_in3`, an integer that is never rounded again."
    PRD §3.3: "The dimensional pound count is the cube divided by `divisor_used` as an exact rational division, and the quotient is then taken up to the next whole pound whenever any fraction remains."
    PRD §3.3: "Otherwise the basis is `DIMENSIONAL`."

    Design: Difficulty/combinatorial_formula/dim_weight_rounds_each_dimension_before_multiplying_mode_b
    """
    shipment = per_dimension_rounding_parcel["parcel"].shipment
    assert shipment["declared_cube_in3"] == 2574, (
        "18.4 x 12.6 x 10.5 must round to 18 x 13 x 11 = 2574 in3, got "
        f"{shipment['declared_cube_in3']}"
    )
    assert shipment["declared_cube_in3"] != 2434, (
        "rounding the product instead of the three operands is wrong"
    )
    assert shipment["divisor_used"] == 139
    assert_lbs(shipment["preliminary_dim_weight_lbs"], 19, "preliminary_dim_weight_lbs")
    assert shipment["preliminary_dim_weight_lbs"] != 18, (
        "18 dimensional pounds is the answer produced by the wrong rounding order"
    )
    assert_lbs(
        shipment["preliminary_billable_weight_lbs"], 19, "preliminary_billable_weight_lbs"
    )
    assert shipment["preliminary_basis"] == "DIMENSIONAL"
    assert_lbs(shipment["billable_weight_lbs"], 19, "billable_weight_lbs")


def test_the_rounded_cube_carries_all_the_way_into_the_transportation_charge(
    api, per_dimension_rounding_parcel
):
    """PRD §3.6: "That row's `cents_per_lb` is recorded on the line as `rate_cents_per_lb`, and the uncapped charge is the billable pound count multiplied by that per-pound rate."
    PRD §3.3: "If the governing contract's `accessorial_rate_overrides` map contains a key for the code, that override amount is used."

    Design: Difficulty/combinatorial_formula/dim_weight_rounds_each_dimension_before_multiplying_mode_b
    """
    parcel = per_dimension_rounding_parcel["parcel"]
    preview = validate_success(
        api.get_billing_preview(parcel.shipment_id, BILLING_OPS_HEADERS)
    )
    assert_money_equals(preview["rate_cents_per_lb"], 380, "rate_cents_per_lb")
    assert_money_equals(
        preview["transportation_base_cents"], 7220, "transportation_base_cents"
    )
    assert preview["transportation_base_cents"] != 6840, (
        "6840 cents is the 18 pound answer produced by the wrong rounding order"
    )
    assert_money_equals(preview["accessorial_total_cents"], 540, "accessorial_total_cents")
    assert_money_equals(preview["line_total_cents"], 7760, "line_total_cents")


# ---------------------------------------------------------------------------
# The tier discount reads step one only, then freezes
# ---------------------------------------------------------------------------
@pytest.fixture
def two_line_invoice_over_the_first_tier(api):
    """A residential EXPRESS parcel and an oversize zone-5 GROUND parcel, issued.

    Their combined pre-discount transportation subtotal of 129770 cents clears
    the 50000 cent break and falls short of the 250000 cent one.
    """
    shipper = shipper_with_multi_zone_contract(api, account_number="SH-1001")
    active_surcharge_window(
        api,
        code="DEM-AUG",
        kind="DEMAND",
        start_date="2026-08-01",
        end_date="2026-09-01",
        per_package_cents=150,
        service_level_id=shipper.service_level_ids["EXPRESS"],
    )
    parcel_one = delivered_shipment(
        api,
        shipper,
        service_level="EXPRESS",
        tracking_number="1Z-P1-0001",
        zone=2,
        residential_declared=True,
        **ROUNDING_DECLARED,
    )
    parcel_two = delivered_shipment(
        api,
        shipper,
        service_level="GROUND",
        tracking_number="1Z-P2-0002",
        zone=5,
        **OVERSIZE_DECLARED,
    )
    invoice = issued_invoice(
        api, open_invoice(api, shipper, [parcel_one.shipment_id, parcel_two.shipment_id])
    )
    return {
        "shipper": shipper,
        "invoice": invoice,
        "parcel_one": parcel_one,
        "parcel_two": parcel_two,
        "line_one": line_for_shipment(api, invoice.invoice_id, parcel_one.shipment_id),
        "line_two": line_for_shipment(api, invoice.invoice_id, parcel_two.shipment_id),
    }


def test_tier_row_is_selected_from_the_pre_discount_transportation_subtotal(
    api, two_line_invoice_over_the_first_tier
):
    """PRD §3.6: "The tier row is selected by reading **step 1 only** — the pre-discount transportation subtotal."
    PRD §3.6: "The chosen row is the row of the contract's `tier_discount_table` with the greatest `min_transportation_subtotal_cents` that is less than or equal to `transportation_subtotal_cents`, so a subtotal landing exactly on a threshold qualifies for that threshold's tier."
    PRD §3.6: "`tier_discount_cents` is computed **once** on the summed subtotal: `transportation_subtotal_cents` multiplied by `tier_discount_bps`, divided by 10000, and rounded half up to a whole cent."
    PRD §3.6: "`net_amount_cents` is `gross_charges_cents` minus `tier_discount_cents` plus `adjustment_total_cents`."

    Design: Difficulty/combinatorial_formula/invoice_tier_reads_pre_discount_transportation_subtotal_mode_c
    """
    line_one = two_line_invoice_over_the_first_tier["line_one"]
    line_two = two_line_invoice_over_the_first_tier["line_two"]
    assert_money_equals(line_one["base_line_total_cents"], 7910, "line one total")
    assert_money_equals(line_two["base_line_total_cents"], 134900, "line two total")

    invoice = refresh_invoice(api, two_line_invoice_over_the_first_tier["invoice"].invoice_id)
    assert invoice["line_count"] == 2
    assert_money_equals(
        invoice["transportation_subtotal_cents"], 129770, "transportation_subtotal_cents"
    )
    assert_money_equals(
        invoice["accessorial_subtotal_cents"], 13040, "accessorial_subtotal_cents"
    )
    assert_money_equals(invoice["gross_charges_cents"], 142810, "gross_charges_cents")
    assert invoice["tier_discount_bps"] == 550, (
        "129770 cents sits in the 50000 cent tier, got "
        f"{invoice['tier_discount_bps']} bps"
    )
    assert_money_equals(invoice["tier_discount_cents"], 7137, "tier_discount_cents")
    assert invoice["tier_discount_cents"] != 7855, (
        "the discount must be computed on the transportation subtotal, not on "
        "gross_charges_cents"
    )
    assert_money_equals(invoice["net_amount_cents"], 135673, "net_amount_cents")


def test_an_applied_rebill_moves_net_without_reselecting_the_frozen_tier(
    api, two_line_invoice_over_the_first_tier
):
    """PRD §3.6: "The selection never reads `gross_charges_cents`, never reads `net_amount_cents`, and is never re-selected merely because an adjustment moved money later."
    PRD §3.8: "The frozen `gross_charges_cents` and `tier_discount_cents` are untouched."
    PRD §3.8: "*Hop 1* — the target line's `adjustment_total_cents` absorbs the `delta_cents` and its `line_total_cents` is recomputed."

    Design: Difficulty/combinatorial_formula/invoice_tier_reads_pre_discount_transportation_subtotal_mode_c
    """
    invoice_ctx = two_line_invoice_over_the_first_tier["invoice"]
    line_two_id = two_line_invoice_over_the_first_tier["line_two"]["id"]

    adjustment = propose_adjustment(
        api, invoice_ctx, line_two_id, 130000, reason="MANUAL", note="rebill the reweigh"
    )
    apply_adjustment(api, adjustment)

    line_two = refresh_invoice_line(api, line_two_id)
    assert_money_equals(line_two["adjustment_total_cents"], 130000, "adjustment_total_cents")
    assert_money_equals(line_two["line_total_cents"], 264900, "line_total_cents")
    assert_money_equals(
        line_two["base_line_total_cents"], 134900, "base_line_total_cents"
    )

    invoice = refresh_invoice(api, invoice_ctx.invoice_id)
    assert invoice["status"] == "ADJUSTED"
    assert_money_equals(invoice["adjustment_total_cents"], 130000, "adjustment_total_cents")
    assert_money_equals(invoice["gross_charges_cents"], 142810, "gross_charges_cents")
    assert invoice["tier_discount_bps"] == 550, (
        "a rebill never re-selects the tier row, got "
        f"{invoice['tier_discount_bps']} bps"
    )
    assert_money_equals(invoice["tier_discount_cents"], 7137, "tier_discount_cents")
    assert_money_equals(invoice["net_amount_cents"], 265673, "net_amount_cents")
    assert invoice["pending_adjustment_count"] == 0
    assert invoice["has_pending_adjustments"] is False
