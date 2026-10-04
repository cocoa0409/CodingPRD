"""Placement fee billing: the fee is strictly proportional to the window length.

PRD §3.7 builds `placement_fee_cents` in five pinned steps from the sponsoring
agreement's frozen tier, its committed supervision hours and the window length.
"""
from test_helpers import (
    TEST_DEFAULTS,
    acceptance_payload,
    assert_placement,
    make_student_headers,
    set_clock,
    setup_interviewed_placement,
    staff_headers,
    validate_success,
)


def test_placement_fee_at_offer_prorates_the_agreement_window(api):
    """PRD §3.7: "The fee is strictly proportional to the window length — it is not a
    two-step proration that pays the full tiered amount for any window of 168 days
    or more and half of it below that."
    PRD §3.7: "Fourth, the duration factor is the number of days from the window
    start to the window end, divided by the 180 days of a scheduled placement."

    A 211-day agreement window with 12 committed supervision hours at TIER_B
    stores 296572 cents; the rejected monthly-commitment reading of the same
    window would store the full tiered base of 253000.

    Design: Difficulty/dual_variant_calc/placement_fee_exact_days_versus_monthly_commitment
    """
    scenario = setup_interviewed_placement()

    data = validate_success(api.extend_offer(scenario.placement["id"], staff_headers()), 200)

    assert data["placement_fee_cents"] == 296572, (
        f"expected the 211/180 proration of the 253000 tiered base, got {data['placement_fee_cents']}"
    )
    assert data["state"] == "OFFERED", data["state"]
    assert_placement(data)


def test_placement_fee_at_acceptance_reprices_against_the_accepted_window(api):
    """PRD §3.7: "The window used depends on when the fee is computed: at offer time
    it is the sponsoring agreement's own `start_date` through `end_date`, and at
    acceptance time it is the placement's accepted `start_date` through `end_date`
    supplied in the request, so a placement shorter or longer than the agreement's
    nominal window is billed in proportion to its real length."
    PRD §3.7: "the placement moves `OFFERED → ACCEPTED` and `placement_fee_cents` is
    recomputed against the accepted `start_date` and `end_date` rather than the
    agreement's window, because the actual placement length now governs the fee"

    The same TIER_B placement reprices from 296572 to 136339 cents once it is
    accepted over a 97-day window.

    Design: Difficulty/dual_variant_calc/placement_fee_exact_days_versus_monthly_commitment
    """
    scenario = setup_interviewed_placement()
    offer = validate_success(api.extend_offer(scenario.placement["id"], staff_headers()), 200)
    assert offer["placement_fee_cents"] == 296572, offer["placement_fee_cents"]

    set_clock(TEST_DEFAULTS["ACCEPTANCE_CLOCK"])
    data = validate_success(
        api.accept_offer(
            scenario.placement["id"],
            acceptance_payload(),
            make_student_headers(scenario.student["id"]),
        ),
        200,
    )

    assert data["placement_fee_cents"] == 136339, (
        f"expected the 97/180 proration of the 253000 tiered base, got {data['placement_fee_cents']}"
    )
    assert data["placement_fee_cents"] != offer["placement_fee_cents"]
    assert_placement(data)
