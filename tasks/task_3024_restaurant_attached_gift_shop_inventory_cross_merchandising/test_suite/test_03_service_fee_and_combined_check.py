"""The combined dining check: its banded service fee, its total and its ceilings."""
import pytest

from test_helpers import api_client, validate_success, validate_error, ApiErrorId
from test_helpers import factories as f
from test_helpers.fixtures import (
    ADMIN, MANAGER, LEAD, PLANNER, CASHIER, cashier_for, server_for,
    create_item, setup_open_day, create_shift, create_check, create_receipt,
    reconcile_receipt, finalize_check, post_tip, start_shift, get_store_day, get_location,
)

BOAT, DECOR = "ITM-BOAT-6400", "ITM-DECOR-2400"


def _boat():
    return create_item(sku=BOAT, name="Hand-Carved Cedar Boat Shelf",
                       theme_code="SUMMER", unit_retail_cents=6400, unit_cost_cents=2400)


def _decor():
    return create_item(sku=DECOR, name="Harvest Wall Plaque",
                       theme_code="SUMMER", unit_retail_cents=2100, unit_cost_cents=900)


def _boot(brand_overrides=None):
    base = {"retail_recognition_policy": "FINAL_ONLY", "food_storage_corridor_units": 310}
    base.update(brand_overrides or {})
    return setup_open_day(brand_overrides=base)


# ==========================================================================
# Difficulty queue A — dual_variant_calc (combined check fee)
# ==========================================================================

def test_a_check_with_a_large_retail_block_uses_the_marginal_fee_bands(api):
    """PRD §3.2: "each percentage applies only to the portion of the basis that falls
    inside its own band. Band edges are inclusive at the lower edge and exclusive at the
    upper edge."
    PRD §3.2: "The basis for the fee is the sum of `restaurant_subtotal_cents` and
    `retail_subtotal_cents` - the tip is counted when deciding which tier the check has
    reached, but it never forms part of the amount the fee percentages multiply"

    Design: Difficulty/dual_variant_calc/combined_check_fee_flat_tier_versus_marginal_bands
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    boat = _boat()
    shift = create_shift(loc["id"], employee_id="E-331", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="12",
                         restaurant_subtotal_cents=11200)
    receipt = create_receipt(loc["id"], day["id"], [f.retail_line(boat["id"], 2, 6400, 0.0, "RETAIL")],
                             "R-1042-0004", guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])
    reconcile_receipt(receipt["id"])
    post_tip(check["id"], 2000, shift["id"])

    data = finalize_check(check["id"], shift["id"])

    assert data["retail_subtotal_cents"] == 12142, (
        "two retail lines of 6400 gross net to 12800 less round_half_up(4608 / 7) == 658"
    )
    assert data["service_fee_cents"] == 3588, (
        "round_half_up(4000*0.15) + round_half_up(4000*0.18) + round_half_up(11342*0.20)"
        " == 600 + 720 + 2268"
    )
    assert data["service_fee_cents"] != int(round(0.20 * (11200 + 12142))), (
        "the flat-tier reading would multiply the whole basis at the selected percent"
    )


def test_the_fee_basis_excludes_the_tip_while_the_tier_walk_includes_it(api):
    """PRD §3.2: "this provisional total exists only to establish which fee tier the check
    has reached"
    PRD §3.2: "Four bands cover the basis in ascending order: from 0 up to but not
    including 4000 cents, from 4000 up to but not including 8000 cents, from 8000 up to but
    not including 12000 cents, and from 12000 cents upward without an upper limit."

    Design: Difficulty/dual_variant_calc/combined_check_fee_flat_tier_versus_marginal_bands
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-332", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="13",
                         restaurant_subtotal_cents=11200)
    post_tip(check["id"], 2000, shift["id"])

    data = finalize_check(check["id"], shift["id"])

    assert data["total_cents"] == 11200 + 0 + 2000 + data["service_fee_cents"]
    assert data["service_fee_cents"] == 1176, (
        "PRD 3.2 marginal bands on a 11200 basis: "
        "round_half_up(4000*0.15) + round_half_up(4000*0.18) + round_half_up(3200*0.20)"
        " == 600 + 720 + 640"
    )


# ==========================================================================
# Difficulty queue A — combinatorial_formula (tier straddling)
# ==========================================================================

def test_the_fee_tier_is_read_from_the_provisional_total_before_the_fee_is_added(api):
    """PRD §3.2: "The freshly computed `service_fee_cents` must not be fed back into the
    tier walk to select a higher tier - the walk is performed once, against the provisional
    total above, and the resulting fee is added afterwards."
    PRD §3.2: "a provisional total is formed by adding the check's `restaurant_subtotal_cents`,
    its `retail_subtotal_cents` and its `tip_cents`"

    Design: Difficulty/combinatorial_formula/conditional_branch_on_gate_and_tier_straddling_bands
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    boat = _boat()
    decor = _decor()
    shift = create_shift(loc["id"], employee_id="E-402", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="3",
                         restaurant_subtotal_cents=5897)
    receipt = create_receipt(loc["id"], day["id"],
                             [f.retail_line(decor["id"], 1, 2100, 0.0, "RETAIL")],
                             "R-1042-0006", guest_check_id=check["id"],
                             expected_guest_check_version=check["version"])
    reconcile_receipt(receipt["id"])
    post_tip(check["id"], 2100, shift["id"])

    data = finalize_check(check["id"], shift["id"])

    assert data["retail_subtotal_cents"] == 1992, (
        "the raw base 2100 less round_half_up(756 / 7) == 108"
    )
    assert data["service_fee_cents"] == 583, (
        "the basis 7889 sits below the 8000 edge, so the fee is banded marginally"
    )
    assert data["total_cents"] == 5897 + 1992 + 2100 + data["service_fee_cents"]


def test_the_fee_bands_straddle_their_edges_rather_than_jumping_the_whole_basis(api):
    """PRD §3.2: "Because the fee is banded, a check whose basis crosses a band edge does
    not jump its whole basis to the higher percentage; only the portion above the edge is
    charged at the higher rate."
    PRD §2.5: "each component is rounded first and the rounded components are then summed"

    Design: Difficulty/combinatorial_formula/conditional_branch_on_gate_and_tier_straddling_bands
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-403", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="4",
                         restaurant_subtotal_cents=10800)

    data = finalize_check(check["id"], shift["id"])

    assert data["service_fee_cents"] == 1104, (
        "round_half_up(4000*0.15) + round_half_up(2800*0.18) == 600 + 504"
    )
    assert data["total_cents"] == 10800 + 0 + 0 + 1104


# ==========================================================================
# Corner queue B — calculations
# ==========================================================================

def test_the_marginal_fee_at_the_exact_tier_boundary(api):
    """PRD §3.2: "Four bands cover the basis in ascending order: from 0 up to but not including
    4000 cents, from 4000 up to but not including 8000 cents, from 8000 up to but not
    including 12000 cents, and from 12000 cents upward without an upper limit."
    PRD §3.2: "Each band's contribution is computed by multiplying the portion of the basis
    inside that band by the band's percentage and rounding the product half-up to a whole cent"

    Design: Corner/calculations/service_fee_marginal_bands_at_the_exact_tier_boundary
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-311", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="5",
                         restaurant_subtotal_cents=10800)
    post_tip(check["id"], 1200, shift["id"])

    data = finalize_check(check["id"], shift["id"])

    assert data["service_fee_cents"] == 1104
    assert data["total_cents"] == 10800 + 0 + 1200 + 1104


def test_a_small_check_that_stops_before_the_second_band_pays_no_fee(api):
    """PRD §3.2: "A basis that stops before the second band produces a fee of zero."
    PRD §3.2: "Four bands cover the basis in ascending order: from 0 up to but not
    including 4000 cents"

    Design: Corner/calculations/service_fee_marginal_bands_at_the_exact_tier_boundary
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-313", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="8",
                         restaurant_subtotal_cents=1000)

    data = finalize_check(check["id"], shift["id"])

    assert data["service_fee_cents"] == 0
    assert data["total_cents"] == 1000


def test_two_checks_on_the_same_tier_pay_the_same_fee_despite_different_tips(api):
    """PRD §3.2: "the tip is counted when deciding which tier the check has reached, but it
    never forms part of the amount the fee percentages multiply, so fee is transparent to
    the tip while the total is not."
    PRD §3.2: "The percentages are 0.00, 0.15, 0.18 and 0.20 respectively, and each
    percentage applies only to the portion of the basis that falls inside its own band."

    Design: Corner/calculations/service_fee_basis_excludes_the_tip
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-312", workcode="CASHIER",
                         tip_eligible_claim=True)
    check_a = create_check(loc["id"], day["id"], shift["id"], table_number="6",
                           restaurant_subtotal_cents=9000)
    check_b = create_check(loc["id"], day["id"], shift["id"], table_number="7",
                           restaurant_subtotal_cents=9000)
    post_tip(check_b["id"], 4000, shift["id"])

    data_a = finalize_check(check_a["id"], shift["id"])
    data_b = finalize_check(check_b["id"], shift["id"])

    assert data_a["service_fee_cents"] == data_b["service_fee_cents"] == 780, (
        "round_half_up(4000*0.15) + round_half_up(1000*0.18) == 600 + 180"
    )
    assert data_b["total_cents"] == 9000 + 4000 + 780


# ==========================================================================
# Corner queue B — validations
# ==========================================================================

def test_an_invalid_recognition_policy_is_a_malformed_body(api):
    """PRD §2.12: "A malformed request - a body that will not parse, a missing required
    field, a violated numeric bound ... or a failed generic type constraint - is rejected
    with `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.4: "A `Brand` carries `retail_recognition_policy`, one of `FINAL_ONLY` or
    `PROVISIONAL_THEN_FINAL`"

    Design: Corner/validations/brand_invalid_recognition_policy_returns_invalid_request
    """
    validate_success(api.set_clock("2026-09-21T00:00:00Z", ADMIN))
    payload = f.create_brand_payload_minimal(brand_code="BR-9001",
                                             legal_name="Bad Policy Co",
                                             retail_recognition_policy="MAYBE_LATER")
    validate_error(api.create_brand(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value)


def test_an_out_of_range_variance_tolerance_is_refused(api):
    """PRD §2.12: "A malformed request - a body that will not parse, a missing required field, a
    violated numeric bound such as a `facings` below one or a `declared_units` at or
    below zero, or a failed generic type constraint - is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.7: "The remaining brand inputs all carry defaults and may be omitted"

    Design: Corner/validations/brand_invalid_recognition_policy_returns_invalid_request
    """
    validate_success(api.set_clock("2026-09-21T00:00:00Z", ADMIN))
    payload = f.create_brand_payload_minimal(brand_code="BR-9002",
                                             transfer_variance_tolerance_bps=20000)
    validate_error(api.create_brand(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST.value)


# ==========================================================================
# Corner queue B — endpoints
# ==========================================================================

def test_a_finalized_check_refuses_a_second_finalize(api):
    """PRD §3.2: "A check is finalized by a `Cashier`. Finalization recomputes
    `retail_subtotal_cents` once more from the receipts then attached ... and moves
    `check_status` to `FINALIZED`."
    PRD §3.2: "A check that has already reached `FINALIZED` or `VOIDED` will not accept a
    further retail line"

    Design: Corner/endpoints/finalize_is_refused_on_an_already_finalized_check
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-601", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="14",
                         restaurant_subtotal_cents=9000)
    first = finalize_check(check["id"], shift["id"])
    assert first["check_status"] == "FINALIZED"

    validate_error(
        api.finalize_guest_check(check["id"], cashier_for(shift["id"])),
        ApiErrorId.ERR_CHECK_ALREADY_FINALIZED.value,
    )


def test_a_finalized_check_keeps_its_original_fee(api):
    """PRD §3.2: "Finalization recomputes `retail_subtotal_cents` once more from the
    receipts then attached, recomputes `service_fee_cents` through the banded fee function
    described above, recomputes `total_cents`"
    PRD §3.2: "the four rounded contributions are then summed"

    Design: Corner/endpoints/finalize_is_refused_on_an_already_finalized_check
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-602", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="15",
                         restaurant_subtotal_cents=9000)
    first = finalize_check(check["id"], shift["id"])
    api.finalize_guest_check(check["id"], cashier_for(shift["id"]))

    assert first["service_fee_cents"] == 780
    assert first["total_cents"] == 9000 + 780


def test_a_tip_that_pushes_the_check_over_the_brand_cap_is_refused(api):
    """PRD §3.2: "the combined check is capped in aggregate: a receipt that would push a
    check's `total_cents` above the brand's `max_check_total_cents` is refused with
    `ERR_CHECK_TOTAL_EXCEEDED` (HTTP 422)"
    PRD §3.2: "`total_cents` is the check's `restaurant_subtotal_cents` plus its
    `retail_subtotal_cents` plus its `tip_cents` plus its `service_fee_cents`."

    Design: Corner/errors/posting_a_tip_above_the_check_cap_returns_check_total_exceeded
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-703", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="16",
                         restaurant_subtotal_cents=40000)

    validate_error(api.post_tip(check["id"], {"tip_cents": 8000}, cashier_for(shift["id"])),
                   ApiErrorId.ERR_CHECK_TOTAL_EXCEEDED.value)


def test_a_tip_within_the_brand_cap_is_accepted(api):
    """PRD §3.2: "A gratuity is posted by a `Cashier` or a `Server` and is supplied as
    non-negative `tip_cents`."
    PRD §3.2: "`total_cents` is the check's `restaurant_subtotal_cents` plus its
    `retail_subtotal_cents` plus its `tip_cents` plus its `service_fee_cents`."

    Design: Corner/errors/posting_a_tip_above_the_check_cap_returns_check_total_exceeded
    """
    brand, loc, day = _boot({"max_check_total_cents": 50000})
    shift = create_shift(loc["id"], employee_id="E-704", workcode="CASHIER",
                         tip_eligible_claim=True)
    check = create_check(loc["id"], day["id"], shift["id"], table_number="17",
                         restaurant_subtotal_cents=40000)

    data = validate_success(api.post_tip(check["id"], {"tip_cents": 2000}, cashier_for(shift["id"])))

    assert data["tip_cents"] == 2000
    assert data["total_cents"] == 40000 + 0 + 2000 + data["service_fee_cents"]