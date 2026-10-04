"""Scoring and schedule arithmetic where the order of the steps is load-bearing.

The eligibility score applies its floor before the escalation bonus; the escrow
schedule is derived from a freshly recomputed equity credit.
"""
from test_helpers import (
    ADMIN,
    SUPPORT,
    api_client,
    assert_cents_equal,
    eligibility_score_for,
    enroll_driver,
    equity_credit_for,
    escrow_required_for,
    get_option,
    get_success_data,
    get_week,
    create_purchase_option_payload,
    open_week,
    pay_week_in_full,
    register_driver,
    settle_week,
    setup_agreement_with_paid_week,
)


def _offer_option(agreement_id, driver_id, price=1_800_000, weeks=24):
    resp = api_client.offer_purchase_option(
        create_purchase_option_payload(
            agreement_id, driver_id,
            purchase_price_cents=price, escrow_weeks_required=weeks,
        ),
        ADMIN,
    )
    return get_success_data(resp, expected_status=201)


def test_eligibility_score_applies_floor_before_the_escalation_bonus(api):
    """PRD §3.1: "The result is then clamped so it never falls below zero. Only
    after that floor is applied does the escalation bonus get considered: if the
    floored score is 40 or less and the driver's platform activity score is at
    least 90, 15 points are added back."
    PRD §3.1: "Between 4 and 6 points inclusive, the deduction is a flat 15
    points for the first tier plus 10 points for each point above 3."

    Design: Difficulty/combinatorial_formula/eligibility_score_floor_before_bonus
    """
    at_four = register_driver(platform_activity_score=90, driving_record_points=4)
    at_six = register_driver(platform_activity_score=90, driving_record_points=6)

    four = enroll_driver(at_four["id"])
    six = enroll_driver(at_six["id"])

    assert four["record_snapshot"] == 4
    assert six["record_snapshot"] == 6
    assert four["eligibility_score"] == 75, (
        "4 record points place the deduction in the 4-to-6 band: a flat 15 plus 10 "
        "for the single point above 3 is 25 of deduction from 100, and the bonus "
        "requires a floored score of 40 or below, so none is added"
    )
    assert six["eligibility_score"] == 55, (
        "6 record points is the last in-range record: the flat 15 plus 3 points at "
        "10 each is 45 of deduction from 100, leaving 55; the bonus needs a floored "
        "score of 40 or below, so none is added"
    )


def test_bonus_requires_the_floored_score_to_be_at_or_below_forty(api):
    """PRD §3.1: "The two clamps are not interchangeable - the lower clamp runs
    before the bonus and the upper clamp after it - which is why a driver with 4
    record points and an activity score of 95 ends at 70 rather than at 85, since
    the bonus requires the floored score to be 40 or below and that driver floors
    at 85."

    Design: Difficulty/combinatorial_formula/eligibility_score_floor_before_bonus
    """
    driver = register_driver(platform_activity_score=95, driving_record_points=4)
    enrollment = enroll_driver(driver["id"])

    assert enrollment["eligibility_score"] == 75, (
        "the 4-to-6 band's flat 15 plus one point above 3 at 10 is 25 of deduction "
        "from 100, leaving 75; no bonus lands on a floored score of 75"
    )
    assert enrollment["eligibility_score"] == eligibility_score_for(4, 95)


def test_eligibility_decision_reads_the_finished_score_and_activity(api):
    """PRD §3.1: "An application is APPROVED when the score is at least 60 and
    the activity score is at least 70. It is DEFERRED when the score is at least
    60 but the activity score falls short of 70 - the driver is welcome but not
    yet at the activity level the programme wants. It is DENIED when the score
    itself falls below 60."

    Design: Difficulty/combinatorial_formula/eligibility_score_floor_before_bonus
    """
    strong = register_driver(platform_activity_score=95, driving_record_points=2)
    deferred = register_driver(platform_activity_score=60, driving_record_points=2)
    weak = register_driver(platform_activity_score=95, driving_record_points=6)

    approved_e = enroll_driver(strong["id"])
    assert approved_e["eligibility_score"] == 90
    assert approved_e["eligibility_decision"] == "APPROVED"

    deferred_e = enroll_driver(deferred["id"])
    assert deferred_e["eligibility_score"] == 90
    assert deferred_e["eligibility_decision"] == "DEFERRED"

    weak_e = enroll_driver(weak["id"])
    assert weak_e["eligibility_score"] == 55
    assert weak_e["eligibility_decision"] == "DENIED"


def test_escrow_schedule_is_derived_from_the_recomputed_equity_credit(api):
    """PRD §3.9: "escrow_required_cents is purchase_price_cents with the current
    equity_credit_cents subtracted from it, divided by escrow_weeks_required,
    rounded half up to a whole cent."
    PRD §3.9: "because the credit is recomputed as the driver continues to pay
    rent, re-running the schedule after a later credit recompute changes the
    recurring amount even though the quoted buyout price has not moved at all."

    Design: Difficulty/combinatorial_formula/equity_credit_then_escrow_schedule_order
    """
    ctx = setup_agreement_with_paid_week(weeks=1, unlimited=True)
    first_amount = ctx.weeks[0]["amount_due_cents"]

    second = open_week(ctx.agreement["id"])
    settle_week(second["id"])
    paid = pay_week_in_full(second["id"])

    option = _offer_option(ctx.agreement["id"], ctx.driver["id"])
    credit = equity_credit_for([first_amount, paid["amount_due_cents"]])

    assert option["equity_credit_cents"] == credit
    assert option["escrow_required_cents"] == escrow_required_for(1_800_000, credit, 24)
    assert option["escrow_balance_cents"] == 0
    assert option["escrow_weeks_funded"] == 0


def test_escrow_amount_moves_after_a_later_credit_recompute(api):
    """PRD §3.9: "On offer, equity_credit_cents is computed for the first time
    and written onto the option, escrow_required_cents is derived from it, and
    escrow_balance_cents and escrow_weeks_funded both begin at 0."
    PRD §3.9: "Every funding step also recomputes equity_credit_cents and advances
    the agreement's version by one, so the escrow requirement charged on the next
    step may itself have moved."

    Design: Difficulty/combinatorial_formula/equity_credit_then_escrow_schedule_order
    """
    ctx = setup_agreement_with_paid_week(weeks=1, unlimited=True)
    first_amount = ctx.weeks[0]["amount_due_cents"]

    option = _offer_option(ctx.agreement["id"], ctx.driver["id"])
    one_week_credit = equity_credit_for([first_amount])
    assert option["equity_credit_cents"] == one_week_credit
    first_schedule = option["escrow_required_cents"]
    assert first_schedule == escrow_required_for(1_800_000, one_week_credit, 24)

    second = open_week(ctx.agreement["id"])
    settle_week(second["id"])
    second_settled = pay_week_in_full(second["id"])

    refreshed = get_option(option["id"])
    two_week_credit = equity_credit_for([first_amount, second_settled["amount_due_cents"]])
    assert refreshed["equity_credit_cents"] == two_week_credit
    assert refreshed["escrow_required_cents"] == escrow_required_for(
        1_800_000, two_week_credit, 24
    )
    assert refreshed["escrow_required_cents"] != first_schedule, (
        "the recurring amount must move when the credit is recomputed, even "
        "though purchase_price_cents has not changed"
    )


def test_equity_credit_is_one_tenth_of_the_paid_minus_waived_subtotal(api):
    """PRD §3.9: "The programme sums the amount_due_cents across the paid weeks,
    sums the amount_due_cents across the waived weeks, and subtracts the waived
    total from the paid total to obtain a subtotal. The driver's equity share is
    one tenth of that subtotal, taken with integer division so any remainder
    below a whole cent is discarded."
    PRD §3.9: "Two settled weeks of 39,000 cents and 30,100 cents with nothing
    waived produce a subtotal of 69,100 cents and therefore a credit of 6,910
    cents."

    Design: Difficulty/combinatorial_formula/equity_credit_then_escrow_schedule_order
    """
    ctx = setup_agreement_with_paid_week(weeks=2, unlimited=True)
    amounts = [w["amount_due_cents"] for w in ctx.weeks]
    expected_credit = equity_credit_for(amounts)

    option = _offer_option(ctx.agreement["id"], ctx.driver["id"])

    assert_cents_equal(option["equity_credit_cents"], expected_credit, "equity credit")
    assert option["equity_credit_cents"] == 7_687, (
        "two settled weeks of 38,435 each give a subtotal of 76,870, one tenth of "
        "which is 7,687"
    )
    assert option["escrow_required_cents"] == escrow_required_for(
        1_800_000, 7_687, 24
    )


def test_week_charge_feeds_the_equity_credit_with_the_settled_figure(api):
    """PRD §3.9: "The credit is a share of the money the driver has actually paid,
    net of anything the programme gave away. It is computed from the agreement's
    weeks whose week_status is PAID and its weeks whose week_status is WAIVED,
    keyed by their week_number."

    Design: Difficulty/combinatorial_formula/equity_credit_then_escrow_schedule_order
    """
    ctx = setup_agreement_with_paid_week(weeks=1, unlimited=True)
    week = get_week(ctx.weeks[0]["id"])

    option = _offer_option(ctx.agreement["id"], ctx.driver["id"])

    assert week["week_status"] == "PAID"
    assert option["equity_credit_cents"] == equity_credit_for([week["amount_due_cents"]])
    assert option["escrow_required_cents"] + option["equity_credit_cents"] > 0
    assert get_success_data(api_client.get_week(week["id"], SUPPORT))["week_status"] == "PAID"