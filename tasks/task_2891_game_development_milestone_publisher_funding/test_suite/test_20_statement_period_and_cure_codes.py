"""The three royalty-period codes, and the two codes that bound the cure loop."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers.assertions import assert_fields_equal, assert_gate_bars_cleared
from test_helpers.constants import ALPHA_PASSING_METRICS
from test_helpers.fixtures import (
    DEFAULT_CRITERIA_1,
    DEFAULT_CRITERIA_2,
    accept_milestone,
    authorize_payment,
    payment_of_milestone,
    record_conditional_review,
    setup_single_alpha,
    submit_build,
)


def test_corner_royalty_statement_period_codes_are_all_reachable(api):
    """Re-finalizing, re-reporting a finalized period and reporting a backwards
    period each answer with their own code, while a later period is accepted.

    PRD §3.9 says "The statement must still be `DRAFT` — a `FINALIZED` or
    `SUPERSEDED` statement answers `ERR_STATEMENT_NOT_DRAFT`", and of creation:
    "a period that already has a `FINALIZED` statement cannot be reported again,
    which is `ERR_PERIOD_ALREADY_FINALIZED`; a `period_label` that sorts strictly
    before the `period_label` of the agreement's most recently finalized
    statement is a regression and earns `ERR_PERIOD_OUT_OF_ORDER`". The accepted
    later period follows the provisional waterfall of PRD §3.9: distributable is
    6000000 less the 3000 bps platform fee, 4200000; "the period's cap is
    `distributable_total_cents` multiplied by the agreement's
    `recoupable_cost_cap_bps`, divided by 10000 and rounded half up, and
    `cost_deduction_cents` is the smaller of the claimed
    `recoupable_cost_cents` and that cap", so 840000 of the 1000000 claim;
    `recoupment_base_cents` 3360000; `recoup_applied_cents` "the smaller of the
    agreement's `unrecouped_advance_cents` as observed at creation time and
    `recoupment_base_cents`", 2720000; `royalty_base_cents` 640000 and the
    provisional royalty 2500 bps of it, 160000.

    Design: Corner/errors/corner_royalty_statement_period_codes_are_all_reachable
    """
    scenario = setup_single_alpha(
        api, contractor_budget_cents=0, acceptance_criteria=DEFAULT_CRITERIA_1
    )
    reg = scenario.reg
    accept_milestone(reg, scenario.m1["id"])
    payment = payment_of_milestone(reg, scenario.m1["id"])
    authorize_payment(reg, payment["id"])

    first = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", scenario.version(),
                [f.revenue_line("PC-GLOBAL", 1000000, 0)], 0,
            ),
            reg.finance,
        ),
        expected_status=201,
    )
    finalized = validate_success(
        api.finalize_royalty_statement(first["id"], reg.finance)
    )
    assert_fields_equal(
        finalized,
        {
            "state": "FINALIZED",
            "distributable_total_cents": 700000,
            "final_royalty_payable_cents": 0,
        },
        "finalized statement",
    )
    finalized_at = finalized["finalized_at"]
    assert finalized_at is not None

    validate_error(
        api.finalize_royalty_statement(first["id"], reg.finance),
        "ERR_STATEMENT_NOT_DRAFT",
        409,
    )
    unchanged = validate_success(api.get_royalty_statement(first["id"], reg.finance))
    assert unchanged["finalized_at"] == finalized_at, unchanged
    assert scenario.read_agreement()["royalties_paid_to_date_cents"] == 0

    validate_error(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q1", scenario.version(),
                [f.revenue_line("PC-GLOBAL", 500000, 0)], 0,
            ),
            reg.finance,
        ),
        "ERR_PERIOD_ALREADY_FINALIZED",
        409,
    )
    validate_error(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2026-Q4", scenario.version(),
                [f.revenue_line("PC-GLOBAL", 500000, 0)], 0,
            ),
            reg.finance,
        ),
        "ERR_PERIOD_OUT_OF_ORDER",
        422,
    )
    rows = get_success_data(
        api.list_agreement_royalty_statements(scenario.agreement_id, reg.finance)
    )
    assert len(rows) == 1 and rows[0]["id"] == first["id"], rows

    later = validate_success(
        api.create_royalty_statement(
            f.royalty_statement_payload(
                scenario.agreement_id, "2027-Q2", scenario.version(),
                [f.revenue_line("PC-GLOBAL", 6000000, 0)], 1000000,
            ),
            reg.finance,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        later,
        {
            "period_label": "2027-Q2",
            "state": "DRAFT",
            "distributable_total_cents": 4200000,
            "cost_deduction_cents": 840000,
            "recoupment_base_cents": 3360000,
            "recoup_applied_cents": 2720000,
            "royalty_base_cents": 640000,
            "provisional_royalty_payable_cents": 160000,
        },
        "later statement",
    )

    # Only finalization posts to the ledger, so the draft moved nothing.
    summary = validate_success(
        api.get_recoupment_summary(scenario.agreement_id, reg.finance)
    )
    assert_fields_equal(
        summary,
        {
            "advance_recouped_cents": 700000,
            "unrecouped_advance_cents": 2720000,
            "royalties_paid_to_date_cents": 0,
        },
        "recoupment summary",
    )


def test_corner_cure_round_codes_are_reachable_and_bounded(api):
    """A partial cure is refused, and once two cure rounds are spent a third
    conditional verdict is refused while a rejection on the same build stands.

    PRD §3.4 says "On a cure resubmission, `addressed_condition_indexes` must
    cover every entry of the milestone's `open_condition_indexes` — it may cover
    more, but it may not omit one — and a shortfall is
    `ERR_CONDITIONS_NOT_ADDRESSED`", and the resubmission is measured against the
    cure-adjusted bar: "then, and only when the milestone's `status` is
    `CURE_PENDING`, add back 5.00 percentage points". PRD §3.5 bounds the loop:
    "Cure rounds are also finite: a milestone whose `cure_count` has already
    reached two refuses a third conditional verdict with
    `ERR_CURE_LIMIT_EXCEEDED`, and because `cure_count` is never decremented, the
    two rounds a milestone is granted are spent permanently." A rejection is
    governed only by the verdict rules of PRD §3.5, so it still moves the
    milestone "`UNDER_REVIEW → IN_DEVELOPMENT`".

    Design: Corner/errors/corner_cure_round_codes_are_reachable_and_bounded
    """
    scenario = setup_single_alpha(
        api, contractor_budget_cents=0, acceptance_criteria=DEFAULT_CRITERIA_2
    )
    reg = scenario.reg
    milestone_id = scenario.m1["id"]
    build_1 = submit_build(reg, milestone_id, 1, ALPHA_PASSING_METRICS)
    record_conditional_review(reg, build_1["id"], [0, 1], 14, "2026-08-01", 9, 10)
    curing = scenario.read_milestone(milestone_id)
    assert_fields_equal(
        curing,
        {"status": "CURE_PENDING", "cure_count": 1, "open_condition_indexes": [0, 1]},
        "milestone in cure",
    )

    validate_error(
        api.create_build(
            f.build_payload(milestone_id, 2, 78.00, 97.00, 62.00, 4, [0], "Only the save fix"),
            reg.dev,
        ),
        "ERR_CONDITIONS_NOT_ADDRESSED",
        422,
    )
    builds = get_success_data(api.list_milestone_builds(milestone_id, reg.dev))
    assert len(builds) == 1, f"the refused resubmission was written: {builds}"
    still_curing = scenario.read_milestone(milestone_id)
    assert_fields_equal(
        still_curing,
        {
            "status": "CURE_PENDING",
            "latest_build_number": 1,
            "open_condition_indexes": [0, 1],
        },
        "milestone after the partial cure",
    )

    assert_gate_bars_cleared("ALPHA", 78.00, 97.00, 62.00, 4, cure_pending=True)
    build_2 = validate_success(
        api.create_build(
            f.build_payload(
                milestone_id, 2, 78.00, 97.00, 62.00, 4, [0, 1], "Both conditions"
            ),
            reg.dev,
        ),
        expected_status=201,
    )
    assert build_2["gate_state"] == "PASSED", build_2
    cured = scenario.read_milestone(milestone_id)
    assert_fields_equal(
        cured,
        {"status": "UNDER_REVIEW", "open_condition_indexes": []},
        "milestone after the full cure",
    )

    record_conditional_review(reg, build_2["id"], [0], 10, "2026-08-01", 11, 12)
    second_round = scenario.read_milestone(milestone_id)
    assert_fields_equal(
        second_round,
        {"status": "CURE_PENDING", "cure_count": 2, "open_condition_indexes": [0]},
        "milestone in the second cure round",
    )

    assert_gate_bars_cleared("ALPHA", 80.00, 98.00, 64.00, 3, cure_pending=True)
    build_3 = validate_success(
        api.create_build(
            f.build_payload(
                milestone_id, 3, 80.00, 98.00, 64.00, 3, [0], "Cold load fixed"
            ),
            reg.dev,
        ),
        expected_status=201,
    )

    validate_error(
        api.create_review(
            f.conditional_review_payload(build_3["id"], [0], 7, "2026-08-01", 13, 14),
            reg.reviewer,
        ),
        "ERR_CURE_LIMIT_EXCEEDED",
        409,
    )
    assert scenario.read_milestone(milestone_id)["cure_count"] == 2

    rejected = validate_success(
        api.create_review(
            f.rejected_review_payload(build_3["id"], "2026-08-01", 15, 16), reg.reviewer
        ),
        expected_status=201,
    )
    assert rejected["verdict"] == "REJECTED", rejected
    after = scenario.read_milestone(milestone_id)
    assert_fields_equal(
        after, {"status": "IN_DEVELOPMENT", "cure_count": 2}, "milestone after rejection"
    )

    reviews = get_success_data(api.list_reviews(reg.reviewer))
    assert len(reviews) == 3, f"expected exactly three reviews, got {reviews}"
