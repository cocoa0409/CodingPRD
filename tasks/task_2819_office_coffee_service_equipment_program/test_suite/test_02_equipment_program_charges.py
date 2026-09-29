"""Minimum-purchase compliance: the two terms types' divergent charges, and the
warn-bill-recover cycle a placement walks around.
"""

from test_helpers.fixtures import (
    ANCHOR_MONDAY,
    complete_stop,
    create_asset,
    evaluate_compliance,
    place_asset_at_site,
    read_placement,
    schedule_stop_with_lines,
    set_clock,
    setup_placed_site,
    setup_planned_site,
    setup_second_site,
)
from test_helpers.assertions import assert_placement


def _two_placements_at_one_commitment(minimum_purchase_cents=100000):
    """One account, two planned break rooms, one LOAN and one RENTAL brewer.

    Both placements declare the same commitment and neither site has taken any
    delivery, so the measured trailing purchase and the unmet commitment are
    identical on both and only the terms type differs.
    """
    base = setup_planned_site(clock=ANCHOR_MONDAY)
    site_two = setup_second_site(base)

    loan_asset = create_asset(base["model"]["id"], serial_number="SN-LOAN-1")
    rental_asset = create_asset(base["model"]["id"], serial_number="SN-RENT-1")

    loan = place_asset_at_site(
        base["site"],
        loan_asset["id"],
        terms_type="LOAN",
        minimum_purchase_cents=minimum_purchase_cents,
    )
    rental = place_asset_at_site(
        site_two,
        rental_asset["id"],
        terms_type="RENTAL",
        minimum_purchase_cents=minimum_purchase_cents,
    )
    base["loan"] = loan
    base["rental"] = rental
    base["site_two"] = site_two
    return base


def test_loan_and_rental_shortfall_fees_diverge_on_identical_figures():
    """Two brewers with the same commitment and the same zero trailing purchase
    accrue completely different shortfall fees, and neither accrues rent.

    "Under **`LOAN`** terms there is no rent whatsoever — `rent_charge_cents`
    stays 0 and a loan placement never produces a `RENT` invoice line — and the
    shortfall fee is 3500 basis points, thirty-five percent, of the unmet
    commitment: the unmet commitment multiplied by 3500, divided by 10000,
    rounded half up."

    "The shortfall component under rental terms is 0 when the unmet commitment
    is exactly 0; otherwise it is a flat surcharge of 2500 basis points,
    twenty-five percent, of the **full** monthly rent — the model's
    `monthly_rent_cents` multiplied by 2500, divided by 10000, rounded half up."

    "Identical commitment and trailing-purchase figures therefore yield a
    completely different shortfall fee under the two terms types."

    Design: Difficulty/dual_variant_calc/equipment_program_charge_loan_recovery_vs_rental_surcharge_divergence
    """
    base = _two_placements_at_one_commitment()

    # First evaluation warns, second bills.
    for _ in range(2):
        evaluate_compliance(base["loan"]["id"])
        evaluate_compliance(base["rental"]["id"])

    loan = read_placement(base["loan"]["id"])
    rental = read_placement(base["rental"]["id"])
    assert_placement(loan)
    assert_placement(rental)

    assert loan["terms_type"] == "LOAN"
    assert rental["terms_type"] == "RENTAL"
    assert loan["minimum_purchase_cents"] == rental["minimum_purchase_cents"] == 100000
    assert loan["trailing_purchase_cents"] == 0
    assert rental["trailing_purchase_cents"] == 0

    assert loan["compliance_status"] == "SHORTFALL_BILLED"
    assert rental["compliance_status"] == "SHORTFALL_BILLED"

    # Loan recovery chases the gap: 100000 unmet at 3500 basis points.
    assert loan["shortfall_fee_cents"] == 35000
    # The rental surcharge is keyed on the full monthly rent of 4500 cents.
    assert rental["shortfall_fee_cents"] == 1125
    assert loan["shortfall_fee_cents"] != rental["shortfall_fee_cents"]

    # Rent is an invoice-period figure and no invoice has been assembled.
    assert loan["rent_charge_cents"] == 0
    assert rental["rent_charge_cents"] == 0

    assert loan["placement_status"] == "ACTIVE"
    assert rental["placement_status"] == "ACTIVE"
    # Creation, then two evaluations.
    assert loan["version"] == 3
    assert rental["version"] == 3


def test_first_miss_warns_both_terms_types_without_accruing_anything():
    """The first evaluation of either terms type moves the brewer to the warned
    state and accrues no money at all, so the divergence only appears on the
    second miss.

    "When the measured trailing purchase is strictly below the placement's
    `minimum_purchase_cents`, a placement in `MEETING_MINIMUM` moves to
    `SHORTFALL_WARNED` and **no fee at all is accrued on the first miss** — the
    first shortfall is a warning."

    "That total is written to the placement's `trailing_purchase_cents` on every
    evaluation, whichever way the compliance state moves."

    Design: Difficulty/dual_variant_calc/equipment_program_charge_loan_recovery_vs_rental_surcharge_divergence
    """
    base = _two_placements_at_one_commitment()

    loan = evaluate_compliance(base["loan"]["id"])
    rental = evaluate_compliance(base["rental"]["id"])
    assert_placement(loan)
    assert_placement(rental)

    for placement in (loan, rental):
        assert placement["compliance_status"] == "SHORTFALL_WARNED"
        assert placement["shortfall_fee_cents"] == 0
        assert placement["rent_charge_cents"] == 0
        assert placement["trailing_purchase_cents"] == 0
        assert placement["placement_status"] == "ACTIVE"
        assert placement["version"] == 2


def _loan_placement_at_one_hundred_thousand():
    """A planned break room with one brewer on loan against a 100000-cent
    commitment and no delivery history at all."""
    return setup_placed_site(
        clock=ANCHOR_MONDAY,
        terms_type="LOAN",
        minimum_purchase_cents=100000,
    )


def test_compliance_cycles_warned_then_billed_then_back_to_meeting_minimum():
    """A loan brewer misses twice, is billed, then a large delivery carries the
    trailing purchase over the commitment and the accrual is cleared.

    "A second consecutive miss moves `SHORTFALL_WARNED` → `SHORTFALL_BILLED`
    and accrues the fee into `shortfall_fee_cents`."

    "When the measured trailing purchase is at or above the commitment, the
    placement returns to `MEETING_MINIMUM` from either `SHORTFALL_WARNED` or
    `SHORTFALL_BILLED`, closing the cycle so it can run again."

    "Returning from `SHORTFALL_BILLED` clears `shortfall_fee_cents` back to 0
    **only if** no `SHORTFALL` invoice line has yet been emitted for that
    accrual; once the fee has reached an invoice it is the invoice's business,
    not the placement's."

    "Each evaluation increments the placement's `version` by 1, and an
    evaluation on a placement already `MEETING_MINIMUM` and still above its
    commitment is an idempotent no-op that only refreshes
    `trailing_purchase_cents`."

    Design: Difficulty/non_linear_state_machine/placement_compliance_cycles_warned_billed_then_back_to_meeting_minimum
    """
    base = _loan_placement_at_one_hundred_thousand()
    placement_id = base["placement"]["id"]
    assert base["placement"]["compliance_status"] == "MEETING_MINIMUM"
    assert base["placement"]["version"] == 1

    warned = evaluate_compliance(placement_id)
    assert warned["compliance_status"] == "SHORTFALL_WARNED"
    assert warned["shortfall_fee_cents"] == 0
    assert warned["trailing_purchase_cents"] == 0
    assert warned["version"] == 2

    billed = evaluate_compliance(placement_id)
    assert billed["compliance_status"] == "SHORTFALL_BILLED"
    assert billed["shortfall_fee_cents"] == 35000
    assert billed["trailing_purchase_cents"] == 0
    assert billed["version"] == 3

    # 250 units of green-linked coffee at 4500000 micro-dollars each is
    # 112500 cents of trailing purchase, comfortably over the commitment.
    visit = schedule_stop_with_lines(base, {"COFFEE": 250})
    completed = complete_stop(base, visit, {"COFFEE": 250}, complete_at="2026-08-03T09:30:00Z")
    assert completed["visit_status"] == "COMPLETED"

    recovered = evaluate_compliance(placement_id)
    assert_placement(recovered)
    assert recovered["trailing_purchase_cents"] == 112500
    assert recovered["compliance_status"] == "MEETING_MINIMUM"
    # No invoice has claimed the accrual, so the placement may clear it.
    assert recovered["shortfall_fee_cents"] == 0
    assert recovered["rent_charge_cents"] == 0
    # The compliance dimension never touched the installation dimension.
    assert recovered["placement_status"] == "ACTIVE"
    assert recovered["version"] == 4


def test_the_compliance_cycle_runs_again_once_the_window_ages_out():
    """Having recovered, the same brewer misses again as soon as its only
    delivery falls out of the trailing window, so the cycle is genuinely a cycle
    rather than a one-way ratchet.

    "**The trailing purchase measure** looks back 90 days from the current
    instant, over a window that is left-exclusive and right-inclusive: a visit
    exactly 90 days old is outside the window, a visit at the current instant is
    inside it."

    "`compliance_status` takes the values `MEETING_MINIMUM`,
    `SHORTFALL_WARNED` and `SHORTFALL_BILLED`, with no terminal state, and it
    evolves entirely independently of the installation dimension."

    Design: Difficulty/non_linear_state_machine/placement_compliance_cycles_warned_billed_then_back_to_meeting_minimum
    """
    base = _loan_placement_at_one_hundred_thousand()
    placement_id = base["placement"]["id"]

    evaluate_compliance(placement_id)
    evaluate_compliance(placement_id)
    visit = schedule_stop_with_lines(base, {"COFFEE": 250})
    complete_stop(base, visit, {"COFFEE": 250}, complete_at="2026-08-03T09:30:00Z")
    recovered = evaluate_compliance(placement_id)
    assert recovered["compliance_status"] == "MEETING_MINIMUM"
    assert recovered["trailing_purchase_cents"] == 112500

    # Exactly 90 days after the service window opened: the stop is now on the
    # excluded edge of the window and contributes nothing.
    set_clock("2026-11-01T09:00:00Z")

    warned_again = evaluate_compliance(placement_id)
    assert warned_again["trailing_purchase_cents"] == 0
    assert warned_again["compliance_status"] == "SHORTFALL_WARNED"
    assert warned_again["shortfall_fee_cents"] == 0
    assert warned_again["version"] == 5

    billed_again = evaluate_compliance(placement_id)
    assert_placement(billed_again)
    assert billed_again["compliance_status"] == "SHORTFALL_BILLED"
    assert billed_again["shortfall_fee_cents"] == 35000
    assert billed_again["placement_status"] == "ACTIVE"
    assert billed_again["version"] == 6
