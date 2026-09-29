"""Payment authorization: the four pinned disbursement steps, the tier boundary the
overrun deduction moves the payment across, and the price a cure round leaves behind."""

from test_helpers import factories as f
from test_helpers.assertions import (
    assert_fields_equal,
    assert_ledger,
    assert_payment_components,
    assert_pct_equals,
)
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_2,
    DEFAULT_CRITERIA_3,
    accept_milestone,
    approve_invoice,
    authorize_payment,
    create_engagement,
    payment_of_milestone,
    record_accepted_review,
    record_conditional_review,
    read_agreement,
    read_milestone,
    setup_single_alpha,
    submit_build,
    submit_invoice,
)
from prd_bench_local_runner.testing import validate_success

ALPHA_PASSING = {
    "feature_completeness_pct": 75.00,
    "crash_free_sessions_pct": 96.00,
    "content_completeness_pct": 60.00,
    "known_blocker_count": 5,
}


def _tidewalker_payment(api):
    """A 2600000 scheduled payment whose contractor overrun of 140000 drags the gross
    back under the first holdback tier ceiling."""
    scenario = setup_single_alpha(
        api, title="Tidewalker", advance_total_cents=2600000,
        contractor_budget_cents=560000, acceptance_criteria=DEFAULT_CRITERIA_2,
        live_ops_quarterly_funding_cents=100000,
    )
    reg = scenario.reg
    engagement = create_engagement(
        reg, scenario.m1["id"], "AUDIO-KELP", 560000, "2026-08-05", "2026-09-15"
    )
    first = submit_invoice(reg, engagement["id"], "KELP-001", 560000, "2026-08-31")
    approve_invoice(reg, first["id"])
    second = submit_invoice(reg, engagement["id"], "KELP-002", 140000, "2026-09-15")
    approve_invoice(reg, second["id"])

    accept_milestone(reg, scenario.m1["id"], 1, ALPHA_PASSING)
    payment = payment_of_milestone(reg, scenario.m1["id"])
    assert payment["scheduled_amount_cents"] == 2600000
    assert payment["status"] == "PENDING_AUTHORIZATION"
    return scenario, payment


def test_the_holdback_tier_is_read_from_the_gross_not_the_scheduled_amount(api):
    """PRD §3.6: "`gross_amount_cents` is then `scheduled_amount_cents` less
    `contractor_overrun_cents`: the publisher recovers a contractor blowout out of
    the milestone payment itself"; and "A gross of at most 2500000 cents, that is
    25000 currency units, attracts a tier rate of 0 basis points". The scheduled
    2600000 sits above that ceiling, the gross of 2460000 does not.

    Design: Difficulty/combinatorial_formula/holdback_tier_selected_after_overrun_deduction_pinned_step_order
    """
    scenario, payment = _tidewalker_payment(api)

    authorized = authorize_payment(
        scenario.reg, payment["id"], "Alpha disbursement with overrun deduction"
    )
    assert_payment_components(
        authorized,
        scheduled=2600000,
        overrun=140000,
        gross=2460000,
        holdback_bps=0,
        holdback=0,
        net=2460000,
    )
    assert authorized["status"] == "AUTHORIZED"

    reread = validate_success(api.get_payment(payment["id"], scenario.reg.finance))
    assert reread["holdback_cents"] == 0
    assert reread["net_amount_cents"] == 2460000


def test_the_net_and_holdback_post_to_the_recoupment_ledger(api):
    """PRD §3.6: "Step one adds `net_amount_cents` to `advance_disbursed_cents` and
    `holdback_cents` to `holdback_reserve_cents`"; and it "moves `recoupment_state`
    from `PRE_RECOUP` to `RECOUPING` as soon as `advance_disbursed_cents` is greater
    than zero".

    Design: Difficulty/combinatorial_formula/holdback_tier_selected_after_overrun_deduction_pinned_step_order
    """
    scenario, payment = _tidewalker_payment(api)

    authorize_payment(scenario.reg, payment["id"], "Alpha disbursement")

    agreement = read_agreement(scenario.reg, scenario.agreement_id)
    assert_ledger(
        agreement,
        advance_disbursed_cents=2460000,
        holdback_reserve_cents=0,
        unrecouped_advance_cents=2460000,
        withheld_payment_cents=0,
    )
    assert agreement["recoupment_state"] == "RECOUPING"


def _emberfall_through_one_cure_round(api):
    """One ALPHA milestone that leaves UNDER_REVIEW for a cure round and comes back."""
    scenario = setup_single_alpha(
        api, title="Emberfall", advance_total_cents=3400000,
        contractor_budget_cents=0, acceptance_criteria=DEFAULT_CRITERIA_3,
        live_ops_quarterly_funding_cents=100000,
    )
    reg = scenario.reg
    build1 = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING)
    review = record_conditional_review(reg, build1["id"], [1], 14)
    return scenario, build1, review


def test_the_cure_round_carries_the_milestone_back_into_under_review(api):
    """PRD §3.5: a conditional verdict "moves the milestone `UNDER_REVIEW →
    CURE_PENDING`, increments the milestone's `cure_count` by one, and copies the
    submitted `conditions` into the milestone's `open_condition_indexes`". PRD §3.4
    then admits the resubmission against a content bar lifted by the cure uplift.

    Design: Difficulty/non_linear_state_machine/milestone_cure_cycle_returns_to_under_review_and_prices_the_cure_penalty
    """
    scenario, build1, review = _emberfall_through_one_cure_round(api)
    reg = scenario.reg

    assert review["cure_deadline_at"] == "2026-08-15T00:00:00.000Z"
    milestone = read_milestone(reg, scenario.m1["id"])
    assert_fields_equal(
        milestone,
        {"status": "CURE_PENDING", "cure_count": 1, "open_condition_indexes": [1],
         "cure_deadline_at": "2026-08-15T00:00:00.000Z"},
        "milestone",
    )

    build2 = validate_success(
        api.create_build(
            f.build_payload(scenario.m1["id"], 2, 75.00, 96.00, 55.00, 5, [1]), reg.dev
        ),
        201,
    )
    assert build2["gate_state"] == "PASSED"
    assert_pct_equals(build2["readiness_score"], 78.35, "readiness_score")

    milestone = read_milestone(reg, scenario.m1["id"])
    assert_fields_equal(
        milestone,
        {"status": "UNDER_REVIEW", "open_condition_indexes": [], "cure_deadline_at": None,
         "latest_build_number": 2, "cure_count": 1},
        "milestone",
    )
    assert validate_success(api.get_build(build1["id"], reg.dev))["gate_state"] == "SUPERSEDED"


def test_acceptance_after_the_cure_round_does_not_refund_the_cure_count(api):
    """PRD §3.5: "because `cure_count` is never decremented, the two rounds a
    milestone is granted are spent permanently."

    Design: Difficulty/non_linear_state_machine/milestone_cure_cycle_returns_to_under_review_and_prices_the_cure_penalty
    """
    scenario, _build1, _review = _emberfall_through_one_cure_round(api)
    reg = scenario.reg

    build2 = submit_build(reg, scenario.m1["id"], 2, dict(
        ALPHA_PASSING, content_completeness_pct=55.00), [1])
    record_accepted_review(reg, build2["id"], start_hour=13, end_hour=17)

    milestone = read_milestone(reg, scenario.m1["id"])
    assert_fields_equal(
        milestone, {"status": "ACCEPTED", "cure_count": 1}, "milestone"
    )


def test_each_cure_round_adds_two_hundred_fifty_basis_points_to_the_holdback(api):
    """PRD §3.6: "**Step three** adds the cure penalty to the rate *before* any
    rounding happens: the penalty is 250 basis points for each time the milestone
    entered a cure period, as counted by its `cure_count`, capped at 500 basis points
    however many rounds were consumed, and `holdback_bps` is the tier rate plus that
    capped penalty."

    Design: Difficulty/non_linear_state_machine/milestone_cure_cycle_returns_to_under_review_and_prices_the_cure_penalty
    """
    scenario, _build1, _review = _emberfall_through_one_cure_round(api)
    reg = scenario.reg

    build2 = submit_build(reg, scenario.m1["id"], 2, dict(
        ALPHA_PASSING, content_completeness_pct=55.00), [1])
    record_accepted_review(reg, build2["id"], start_hour=13, end_hour=17)

    payment = payment_of_milestone(reg, scenario.m1["id"])
    authorized = authorize_payment(
        reg, payment["id"], "Alpha disbursement after one cure round"
    )
    assert_payment_components(
        authorized,
        scheduled=3400000,
        overrun=0,
        gross=3400000,
        holdback_bps=750,
        holdback=255000,
        net=3145000,
    )

    agreement = read_agreement(reg, scenario.agreement_id)
    assert_ledger(
        agreement,
        advance_disbursed_cents=3145000,
        holdback_reserve_cents=255000,
    )
