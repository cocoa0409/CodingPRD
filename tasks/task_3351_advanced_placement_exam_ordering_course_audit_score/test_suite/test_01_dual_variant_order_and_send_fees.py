"""Dual-variant arithmetic: the order fee and the score-send fee."""
from test_helpers import (
    ADMIN,
    MID_REGULAR_CLOCK_UTC,
    get_success_data,
    api_client,
    create_send,
    deliver_order,
    get_order,
    get_school,
    host_headers,
    setup_order_with_registrations,
    setup_released_score,
    ship_and_receive_materials,
    transition_order,
    validate_success,
)


# --------------------------------------------------------------------------
# The order fee: provisional variant charged at OPEN -> SUBMITTED
# --------------------------------------------------------------------------

def test_provisional_order_fee_charges_base_plus_tier_surcharges():
    """PRD §3.2: "The provisional variant charges every registered exam at the base fee of 18000 cents and adds a late surcharge of 4000 cents for each registration whose `registration_tier` is `LATE` and an emergency surcharge of 9000 cents for each registration whose tier is `EMERGENCY`; it ignores consolidation entirely."
    PRD §3.2: "The order fee is dual-variant, and both variants are readable on the same row: `provisional_order_fee_cents` always holds the provisional figure, while `order_fee_cents` holds the provisional figure while the order is `OPEN`, `SUBMITTED`, `MATERIALS_SHIPPED` or `MATERIALS_RECEIVED`"

    Design: Difficulty/dual_variant_calc/exam_order_fee_provisional_vs_consolidated_marginal_rebate
    """
    tiers = ["REGULAR"] * 7 + ["LATE"] * 2 + ["EMERGENCY"] * 1
    bundle = setup_order_with_registrations(tiers, confirm=False)
    order = transition_order(bundle["order"], "SUBMITTED", headers=host_headers(bundle["school"]))

    # 10 exams at 18000 + two LATE at 4000 + one EMERGENCY at 9000.
    assert order["order_fee_cents"] == 197000, (
        f"provisional order fee should be 197000, got {order['order_fee_cents']}"
    )
    assert order["provisional_order_fee_cents"] == 197000
    assert order["registration_count"] == 10


def test_consolidated_order_fee_replaces_provisional_only_after_delivery():
    """PRD §3.2: "The final fee is the single-rate base plus the late surcharge plus the emergency surcharge."
    PRD §3.2: "A single-rate base is also derived, using the rate of the slice that contains the delivered count"
    PRD §3.2: "`order_fee_cents` holds the provisional figure while the order is `OPEN`, `SUBMITTED`, `MATERIALS_SHIPPED` or `MATERIALS_RECEIVED` and the consolidated figure once the order is `DELIVERED`"

    Design: Difficulty/dual_variant_calc/exam_order_fee_provisional_vs_consolidated_marginal_rebate
    """
    tiers = ["REGULAR"] * 6 + ["LATE"] * 2
    bundle = setup_order_with_registrations(tiers)
    order = transition_order(bundle["order"], "SUBMITTED", headers=host_headers(bundle["school"]))
    assert order["provisional_order_fee_cents"] == 152000  # 8 * 18000 + 2 * 4000

    bundle["order"] = order
    ship_and_receive_materials(bundle)
    delivered = deliver_order(bundle)

    # Eight delivered exams sit in the third slice (rate 0.94): 8 * 18000 * 0.94.
    assert delivered["order_fee_cents"] == 143360, (
        f"consolidated fee should be 135360 + 8000 = 143360, got {delivered['order_fee_cents']}"
    )
    assert delivered["provisional_order_fee_cents"] == 152000, (
        "provisional_order_fee_cents must keep the provisional figure on the same row"
    )
    assert delivered["order_fee_cents"] != delivered["provisional_order_fee_cents"]


# --------------------------------------------------------------------------
# The order fee: the rounding order of the consolidation slices
# --------------------------------------------------------------------------

def test_eight_delivered_exams_use_the_single_rate_base_not_the_marginal_sum():
    """PRD §3.2: "As a worked reference, an order with eight delivered exams yields a marginal accumulator of 139140 cents against a single-rate base of 135360 cents, a difference of 3780 cents."
    PRD §3.2: "each slice's contribution is that count multiplied by 18000 and by the slice rate, rounded half-up to a whole cent before being added to the accumulator, and the accumulator starts at zero"

    Design: Difficulty/combinatorial_formula/consolidation_slices_round_before_summing
    """
    tiers = ["REGULAR"] * 8
    bundle = setup_order_with_registrations(tiers)
    bundle["order"] = transition_order(
        bundle["order"], "SUBMITTED", headers=host_headers(bundle["school"])
    )
    ship_and_receive_materials(bundle)
    delivered = deliver_order(bundle)

    assert delivered["order_fee_cents"] == 135360, (
        f"the fee must use the single-rate base 135360, got {delivered['order_fee_cents']}"
    )
    assert delivered["order_fee_cents"] != 139140, (
        "the marginal slice accumulator 139140 is not the final fee"
    )


def test_two_delivered_exams_take_the_second_slice_rate():
    """PRD §3.2: "the first slice covers counts from 0 up to but excluding 2 at a rate of 1.00, the second covers 2 up to but excluding 5 at 0.97"
    PRD §3.2: "A single-rate base is also derived, using the rate of the slice that contains the delivered count"

    Design: Difficulty/combinatorial_formula/consolidation_slices_round_before_summing
    """
    tiers = ["REGULAR"] * 2
    bundle = setup_order_with_registrations(tiers)
    bundle["order"] = transition_order(
        bundle["order"], "SUBMITTED", headers=host_headers(bundle["school"])
    )
    ship_and_receive_materials(bundle)
    delivered = deliver_order(bundle)

    # Two delivered exams select the 0.97 slice: 2 * 18000 * 0.97 = 34920.
    assert delivered["order_fee_cents"] == 34920, (
        f"two delivered exams should use the 0.97 slice, got {delivered['order_fee_cents']}"
    )
    assert delivered["order_fee_cents"] != 36000


# --------------------------------------------------------------------------
# The score-send fee: the include-set decides the allowance
# --------------------------------------------------------------------------

def test_school_send_fee_counts_school_sends_against_the_shared_allowance():
    """PRD §3.8: "The all-inclusive variant counts every send of that score whose recipient type is `COLLEGE` plus every send whose recipient type is `SCHOOL`, subtracts the free allowance of 2, floors the result at zero and multiplies by the per-send fee of 2500 cents."
    PRD §3.8: "A student with two college sends and one school send therefore reports a 2500-cent fee for the school send under the all-inclusive view"

    Design: Difficulty/dual_variant_calc/score_send_fee_all_include_vs_college_only_exclude
    """
    bundle = setup_released_score()
    score, school = bundle["score"], bundle["school"]

    create_send(score, school, recipient_type="COLLEGE", recipient_code="C1001")
    create_send(score, school, recipient_type="COLLEGE", recipient_code="C1002")
    school_send = create_send(
        score, school, recipient_type="SCHOOL", recipient_code=school["school_code"]
    )

    # 2 college sends + 1 school send = 3, minus the allowance of 2 -> 1 * 2500.
    assert school_send["fee_cents"] == 2500, (
        f"the school send should report 2500 under the all-inclusive view, "
        f"got {school_send['fee_cents']}"
    )


def test_school_send_fee_is_zero_while_the_combined_count_fits_the_allowance():
    """PRD §3.8: "The all-inclusive variant counts every send of that score whose recipient type is `COLLEGE` plus every send whose recipient type is `SCHOOL`, subtracts the free allowance of 2, floors the result at zero and multiplies by the per-send fee of 2500 cents."
    PRD §3.8: "Both variants count only sends in `PENDING`, `SENT` or `ACKNOWLEDGED` status; cancelled and failed sends are excluded from every count."

    Design: Difficulty/dual_variant_calc/score_send_fee_all_include_vs_college_only_exclude
    """
    bundle = setup_released_score()
    score, school = bundle["score"], bundle["school"]

    create_send(score, school, recipient_type="COLLEGE", recipient_code="C1101")
    school_send = create_send(
        score, school, recipient_type="SCHOOL", recipient_code=school["school_code"]
    )

    # 1 college send + 1 school send = 2, which the allowance of 2 absorbs.
    assert school_send["fee_cents"] == 0, (
        f"a combined count of 2 is within the free allowance, got {school_send['fee_cents']}"
    )
