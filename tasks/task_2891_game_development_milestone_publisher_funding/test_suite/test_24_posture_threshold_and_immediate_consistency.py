"""The cumulative posture trigger measured one milestone below and exactly at the
thirty-percent boundary, and the immediate-consistency guarantee of the acceptance
cascade.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_client import original_data
from test_helpers.assertions import assert_fields_equal, assert_instant_format, assert_ledger
from test_helpers.constants import ALPHA_PASSING_METRICS, CLOCK_START
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    activate,
    add_milestone,
    draft_agreement,
    record_accepted_review,
    setup_registry,
    setup_twinpeak,
    submit_build,
)


def test_corner_funding_posture_threshold_flips_exactly_at_thirty_percent_of_the_pool(api):
    """Accepted value at twenty-five percent of the pool leaves the posture `OPEN`;
    the next acceptance lands exactly on the threshold and flips it to `RESTRICTED`,
    which closes new milestones and leaves the change-order channel open.

    PRD §2.6 says the posture "is `RESTRICTED` when `accepted_value_cents` has
    reached or passed thirty percent of `funding_pool_cents`, where the threshold
    is computed by multiplying `funding_pool_cents` by 3000 basis points, dividing
    by 10000 and rounding half up to whole cents; the comparison is inclusive, so
    hitting the threshold exactly is enough to restrict", and that "The posture is
    `FROZEN` whenever the agreement's `status` is `SUSPENDED` or `TERMINATED`".
    PRD §2.10 rule 30 makes the consequence behavioural: "`funding_posture` is not
    `RESTRICTED`, on milestone creation — `ERR_FUNDING_POSTURE_RESTRICTED`", and
    PRD §3.2 explains that "at that point additional scope is a renegotiation and
    must arrive as a change order rather than as a new line in the original
    schedule". PRD §5 prices that error at 409.

    Design: Corner/cross_cutting_complexity_layers/corner_funding_posture_threshold_flips_exactly_at_thirty_percent_of_the_pool
    """
    reg = setup_registry(api)
    agreement = draft_agreement(
        reg, "Aurora Drift", 12000000, 2500, "2027-09-30", 2000, 3000, 100000
    )
    agreement_id = agreement["id"]
    m1 = add_milestone(reg, agreement_id, 1, "Alpha", "ALPHA", 3000000, 0,
                       DEFAULT_CRITERIA_1)
    m2 = add_milestone(reg, agreement_id, 2, "Alpha polish", "ALPHA", 600000, 0,
                       ["Tutorial pass"], m1["id"])
    m3 = add_milestone(reg, agreement_id, 3, "Gold", "GOLD", 8400000, 0,
                       ["Ship candidate"], m2["id"])
    activate(reg, agreement_id)

    build_1 = submit_build(reg, m1["id"], 1, ALPHA_PASSING_METRICS)
    record_accepted_review(reg, build_1["id"], "2026-08-01", 9, 10)

    # 3000000 of a 12000000 pool is 25 percent, short of the 3600000 trigger.
    open_read = validate_success(api.get_agreement(agreement_id, reg.finance))
    assert_fields_equal(
        open_read,
        {"accepted_value_cents": 3000000, "funding_posture": "OPEN"},
        "agreement below the trigger",
    )

    build_2 = validate_success(
        api.create_build(
            f.build_payload(m2["id"], 1, 76.00, 96.50, 61.00, 4, None,
                            "Polish candidate"),
            reg.dev,
        ),
        expected_status=201,
    )
    record_accepted_review(reg, build_2["id"], "2026-08-01", 11, 12)
    assert validate_success(api.get_milestone(m2["id"], reg.dev))["status"] == "ACCEPTED"

    # 3000000 + 600000 == round_half_up(12000000 * 3000 / 10000), and the
    # comparison is inclusive.
    restricted_read = validate_success(api.get_agreement(agreement_id, reg.finance))
    assert_fields_equal(
        restricted_read,
        {"accepted_value_cents": 3600000, "funding_posture": "RESTRICTED"},
        "agreement at the trigger",
    )
    assert_ledger(restricted_read, funding_pool_cents=12000000, committed_cents=12000000,
                  available_funding_cents=0)
    v_restricted = restricted_read["version"]

    validate_error(
        api.create_milestone(
            f.milestone_payload(agreement_id, 4, "Bonus scope", "BETA", 10000, 0,
                                ["Added after the trigger"]),
            reg.dev,
        ),
        "ERR_FUNDING_POSTURE_RESTRICTED",
        409,
    )
    assert validate_success(api.get_agreement(agreement_id, reg.finance))[
        "committed_cents"
    ] == 12000000, "the refused milestone changed the commitment"

    # The restricted posture redirects new scope, it does not freeze the agreement.
    order = validate_success(
        api.create_change_order(
            f.change_order_payload(
                agreement_id, m3["id"], "FUNDING_UPLIFT", v_restricted,
                "New scope arriving the only legal way",
                requested_amount_cents=200000, ship_date_delta_days=0,
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert order["state"] == "PROPOSED", order

    # The posture is derived, so both surfaces report it identically.
    individual = validate_success(api.get_agreement(agreement_id, reg.finance))
    listed = get_success_data(api.list_agreements(reg.finance, {"studio_id": reg.studio_id}))
    row = next(r for r in listed if r["id"] == agreement_id)
    assert row["funding_posture"] == individual["funding_posture"], (individual, row)
    assert row["accepted_value_cents"] == individual["accepted_value_cents"], (individual, row)


def test_corner_immediate_consistency_every_cascade_is_final_in_the_first_read(api):
    """One accepting verdict leaves nothing for a later pass: the accepted
    milestone, the unlocked dependent, the new payment row and the agreement
    ledger are all final on the very first read, and a second read repeats it.

    PRD §2.8 says "Cascades are applied immediately and synchronously within the
    triggering request; there is no deferred reconciliation and no eventual
    consistency window", and that "Any cascade that changes a field on the
    `DevelopmentAgreement` refreshes that agreement's `updated_at` and increments
    its `version` by one, exactly once per request, no matter how many rows the
    cascade touched." PRD §3.5 fixes what the acceptance writes: it "sets the
    milestone's `status` to `ACCEPTED`, stamps `accepted_at` from the logical
    clock", then "Step one creates exactly one milestone payment in
    `PENDING_AUTHORIZATION` whose `scheduled_amount_cents` is the milestone's
    `funded_amount_cents` plus its `uplift_cents` frozen at the instant of
    acceptance. Step two ... promotes every milestone whose
    `depends_on_milestone_id` points at it and whose `status` is still `DEFINED`
    from `DEFINED → IN_DEVELOPMENT` ... Step three ... the posture flips
    `OPEN → RESTRICTED` as soon as `accepted_value_cents` reaches the
    thirty-percent-of-pool threshold". PRD §3.5 also stamps the review itself:
    "The server stamps `reviewer_user_id` from the acting `X-User-ID` and
    `decided_at` from the logical clock."

    Design: Corner/consistency_model/corner_immediate_consistency_every_cascade_is_final_in_the_first_read
    """
    scenario = setup_twinpeak(api)
    reg = scenario.reg
    v_before = scenario.agreement["version"]

    build_1 = submit_build(reg, scenario.m1["id"], 1, ALPHA_PASSING_METRICS)
    assert build_1["gate_state"] == "PASSED", build_1
    assert scenario.read_milestone(scenario.m1["id"])["status"] == "UNDER_REVIEW"

    review = validate_success(
        api.create_review(
            f.accepted_review_payload(build_1["id"], "2026-08-01", 9, 10), reg.reviewer
        ),
        expected_status=201,
    )
    assert_fields_equal(
        review,
        {
            "verdict": "ACCEPTED",
            "reviewer_user_id": reg.reviewer_id,
            "decided_at": CLOCK_START,
        },
        "review",
    )
    assert_instant_format(review["decided_at"], "review.decided_at")

    accepted = scenario.read_milestone(scenario.m1["id"])
    assert accepted["status"] == "ACCEPTED", accepted
    assert_instant_format(accepted["accepted_at"], "milestone.accepted_at")

    unlocked = scenario.read_milestone(scenario.m2["id"])
    assert unlocked["status"] == "IN_DEVELOPMENT", unlocked

    payments = get_success_data(
        api.list_payments(reg.finance, {"milestone_id": scenario.m1["id"]})
    )
    assert len(payments) == 1, payments
    assert_fields_equal(
        payments[0],
        {"status": "PENDING_AUTHORIZATION", "scheduled_amount_cents": 3600000},
        "payment created by the cascade",
    )

    first_response = api.get_agreement(scenario.agreement_id, reg.finance)
    first_read = validate_success(first_response)
    assert_fields_equal(
        first_read,
        {
            "accepted_value_cents": 3600000,
            "funding_posture": "RESTRICTED",
            "version": v_before + 1,
        },
        "agreement after the cascade",
    )

    second_response = api.get_agreement(scenario.agreement_id, reg.finance)
    assert original_data(second_response) == original_data(first_response), (
        "a second read of the same aggregate returned a different body"
    )
