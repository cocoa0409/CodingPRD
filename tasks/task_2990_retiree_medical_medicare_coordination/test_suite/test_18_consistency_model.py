"""Immediate consistency: nothing derived is allowed to arrive late.

The single test here approves one election and one reimbursement account and reads
everything the two writes were supposed to derive, without a sweep anywhere in the
recipe — so no observed value can be attributed to a later batch pass.
"""
from test_helpers import (
    assert_hra_buckets,
    assert_instant_equals,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ANALYST_1,
    ANALYST_2,
    COUNSELOR_1,
    COUNSELOR_2,
    make_enrollment_counselor_headers,
)


def test_an_approval_and_a_funding_are_complete_in_their_own_responses(api):
    """Every derived figure is already there on the next read, with no sweep run.

    PRD 3.5 packs the whole cascade into the approval itself: "A surviving approval
    moves `status` from `UNDER_REVIEW` to `APPROVED` and materialises exactly one
    enrollment.", that enrollment carrying "`election_event_id` pointing back at the
    election that produced it", and "Its `coverage_status` is `ACTIVE` when the
    logical clock has already reached that `coverage_effective_date` and `PENDING`
    when it has not, its `billing_status` is `CURRENT`, and its `coverage_end_date`
    and `termination_reason` are null." Two derivations are named as part of the same
    breath rather than deferred: "The Medicare secondary-payer determination runs
    immediately to write `payer_order` and `msp_basis_code`. The premium waterfall
    runs through its first six steps, with no reimbursement offset applied, to write
    `monthly_retiree_premium_cents`." — and PRD 3.6 branch 1 fixes the answer for a
    retiree who is not enrolled in Medicare: "If the retiree's `medicare_status` is
    anything other than `MEDICARE_ENROLLED`, then `payer_order` is `GROUP_PRIMARY`
    with `msp_basis_code` `NO_OTHER_COVERAGE`." The counter moves in the same
    instant, "The requested option's `enrolled_count` increments by 1 and that
    option's `version` increments.", which PRD 2.10 requires to hold at rest:
    "`enrolled_count` equals the number of enrollments referencing that option whose
    `coverage_status` is `PENDING`, `ACTIVE` or `SUSPENDED`". Funding is likewise
    final in the creation response, PRD 3.7 computing it there — "That full-year
    figure is then divided by 12 and truncated down to whole cents to give a monthly
    credit, and only then multiplied by `covered_months` to give
    `annual_credit_cents`." with "`carryover_in_cents` is the
    `available_balance_cents` of the account named by `prior_year_account_id`, or 0
    when no prior account was supplied." and "`available_balance_cents` opens equal
    to `funded_cents`" — so 185000 divided by 12 is 15416 a month and 184992 for
    twelve months. Nothing here is a batch product: PRD 3.9 gives the sweep its own
    operator endpoint, which "ages the whole programme forward against the current
    logical clock", and it is never called.

    Design: Corner/consistency_model/election_approval_side_effects_visible_in_the_same_response
    """
    fx.set_clock(api, "2026-10-20T00:00:00Z")
    plan_year = fx.make_open_plan_year(api)
    option = fx.make_pre65_core(api, plan_year["id"])
    assert option["enrolled_count"] == 0

    certified = fx.make_certified_retiree(
        api,
        plan_year["id"],
        f.retiree_r1_payload(),
        creator_user_id=ANALYST_1,
        certifier_user_id=ANALYST_2,
    )
    retiree = certified["retiree"]
    assert retiree["medicare_status"] == "PRE_MEDICARE"

    election = fx.make_election_event(
        api,
        retiree["id"],
        plan_year["id"],
        option["id"],
        review=True,
        creator_user_id=COUNSELOR_1,
        reviewer_user_id=COUNSELOR_2,
    )
    assert election["status"] == "UNDER_REVIEW"

    counselor = make_enrollment_counselor_headers(COUNSELOR_2)
    approval = validate_success(
        api.decide_election_event(
            election["id"], f.election_decision_payload("APPROVE"), counselor
        )
    )
    assert approval["status"] == "APPROVED"
    assert approval["resulting_enrollment_id"] is not None

    enrollment = validate_success(
        api.get_enrollment(approval["resulting_enrollment_id"], counselor)
    )
    assert enrollment["coverage_status"] == "PENDING"
    assert enrollment["billing_status"] == "CURRENT"
    assert_instant_equals(
        enrollment["coverage_effective_date"], "2027-01-01T00:00:00.000Z"
    )
    assert enrollment["monthly_retiree_premium_cents"] == 15422
    assert enrollment["election_event_id"] == election["id"]
    assert enrollment["payer_order"] == "GROUP_PRIMARY"
    assert enrollment["msp_basis_code"] == "NO_OTHER_COVERAGE"
    assert enrollment["coverage_end_date"] is None
    assert enrollment["termination_reason"] is None

    counted = validate_success(api.get_plan_option(option["id"], counselor))
    assert counted["enrolled_count"] == 1

    account = fx.make_hra_account(api, retiree["id"], plan_year["id"], covered_months=12)
    assert account["status"] == "OPEN"
    assert_hra_buckets(
        account,
        annual_credit_cents=184992,
        carryover_in_cents=0,
        funded_cents=184992,
        available_balance_cents=184992,
        pending_hold_cents=0,
        substantiated_paid_cents=0,
        premium_offset_cents=0,
        forfeited_cents=0,
    )
