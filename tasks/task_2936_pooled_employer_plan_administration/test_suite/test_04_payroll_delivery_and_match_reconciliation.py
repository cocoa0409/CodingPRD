"""Payroll delivery, the elected match formula and pay-period geometry."""

from typing import Any, Dict, Optional

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_CORRECTION_INVALID_STATE,
    ERR_DUPLICATE_PAYROLL_REFERENCE,
    ERR_INVALID_PAY_PERIOD,
    ERR_INVALID_RECOVERY_DATE,
    ERR_MATCH_MISMATCH,
    ERR_NOT_PLAN_RECORDKEEPER,
    ERR_PAY_PERIOD_OVERLAP,
    ERR_WITHHOLDING_DATE_OUT_OF_PERIOD,
)
from test_helpers.assertions import (
    assert_fields,
    assert_null_fields,
    assert_resource_shape,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from prd_bench_local_runner.testing import validate_error

# The three employers deliver byte-identical payroll, so only the elected match
# formula can explain a difference in the computed match.
RIVERBEND_LEGAL_NAME = "Riverbend Tooling Inc"
RIVERBEND_EIN = "420000043"
RIDGEWAY_SIGNATORY = "K. Ridgeway"

PAY_PERIOD_CLOCK = "2026-08-14T09:00:00Z"
CORRECTION_WINDOW_CLOCK = "2026-08-25T09:00:00Z"

TIERED_100_AT_3_AND_25_AT_6 = {
    "match_formula_code": k.MATCH_DISCRETIONARY_TIERED,
    "match_tier_1_pct": 100.0,
    "match_tier_1_limit_pct": 3.0,
    "match_tier_2_pct": 25.0,
    "match_tier_2_limit_pct": 6.0,
}
TIERED_100_AT_5_AND_100_AT_10 = {
    "match_formula_code": k.MATCH_DISCRETIONARY_TIERED,
    "match_tier_1_pct": 100.0,
    "match_tier_1_limit_pct": 5.0,
    "match_tier_2_pct": 100.0,
    "match_tier_2_limit_pct": 10.0,
}


def _electing_employer(
    api: ApiClient,
    plan: PlanContext,
    signatory: str,
    employer_payload: Optional[Dict[str, Any]] = None,
    **election_overrides: Any,
) -> EmployerContext:
    """Admit an employer and approve an election carrying the named formula."""
    emp_ctx = fixtures.applied_employer(api, plan, employer_payload)
    fixtures.submitted_election(
        api, emp_ctx, signatory_name=signatory, **election_overrides
    )
    approved = validate_single(
        api.approve_design_election(emp_ctx.election_id, plan.provider_headers)
    )
    emp_ctx.elections[-1] = approved
    emp_ctx.refresh(api)
    return emp_ctx


def _riverbend_payload(plan: PlanContext) -> Dict[str, Any]:
    """A third 13-participant employer on the same plan."""
    return f.adopting_employer_payload(
        plan.plan_id, legal_name=RIVERBEND_LEGAL_NAME, ein=RIVERBEND_EIN
    )


def test_the_elected_formula_code_alone_selects_the_match_branch(
    api: ApiClient, plan
):
    """
    Three employers deliver identical payroll and the elected formula code is the
    only thing that can explain three different computed matches.

    "For `SAFE_HARBOR_BASIC` the raw match is the sum of two tiers. The first
    tier is the lesser of the deferrals and three percent of compensation,
    rounded half up to whole cents. The second tier is one half of the amount by
    which the lesser of the deferrals and five percent of compensation exceeds
    three percent of compensation — and if that excess is negative it is treated
    as zero — again rounded half up to whole cents."

    "Consider a period with compensation of 100000000 cents and deferrals of
    4500000 cents: `SAFE_HARBOR_BASIC` yields 3000000 plus 750000, for 3750000;
    `SAFE_HARBOR_ENHANCED` yields 4000000; a `DISCRETIONARY_TIERED` election at
    one hundred percent up to a 3.0 percent limit and twenty-five percent up to a
    6.0 percent limit yields 3000000 plus 375000, for 3375000; and `NONE` yields
    zero."

    "`batch_total_cents` is simply `total_deferral_cents` plus
    `total_match_cents` plus `total_loan_repayment_cents` — the whole amount the
    employer owes the trust for the period."

    Design: Difficulty/combinatorial_formula/match_formula_branch_selection_across_three_codes
    """
    fixtures.set_clock(api, k.PAYROLL_CLOCK)
    basic = _electing_employer(api, plan, k.PALISADE_SIGNATORY)
    enhanced = _electing_employer(
        api,
        plan,
        k.QUARRY_SIGNATORY,
        f.second_adopting_employer_payload(plan.plan_id),
        match_formula_code=k.MATCH_SAFE_HARBOR_ENHANCED,
    )
    tiered = _electing_employer(
        api,
        plan,
        RIDGEWAY_SIGNATORY,
        _riverbend_payload(plan),
        **TIERED_100_AT_3_AND_25_AT_6,
    )

    common = dict(
        total_eligible_compensation_cents=k.CANONICAL_COMPENSATION_CENTS,
        total_deferral_cents=k.CANONICAL_DEFERRAL_CENTS,
        total_loan_repayment_cents=0,
        participant_line_count=13,
    )

    basic_batch = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                basic.employer_id,
                payroll_provider_reference="PR-BAS-15",
                total_match_cents=3750000,
                **common,
            ),
            basic.headers,
        )
    )
    enhanced_batch = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                enhanced.employer_id,
                payroll_provider_reference="PR-ENH-15",
                total_match_cents=4000000,
                **common,
            ),
            enhanced.headers,
        )
    )
    tiered_batch = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                tiered.employer_id,
                payroll_provider_reference="PR-TIER-15",
                total_match_cents=3375000,
                **common,
            ),
            tiered.headers,
        )
    )

    assert_fields(
        basic_batch, expected_match_cents=3750000, batch_total_cents=8250000
    )
    assert_fields(
        enhanced_batch, expected_match_cents=4000000, batch_total_cents=8500000
    )
    assert_fields(
        tiered_batch, expected_match_cents=3375000, batch_total_cents=7875000
    )

    assert_fields(
        basic.elections[-1], nondiscrimination_track=k.TRACK_SAFE_HARBOR_EXEMPT
    )
    assert_fields(
        tiered.elections[-1], nondiscrimination_track=k.TRACK_ADP_ACP_TESTED
    )
    assert_fields(
        basic_batch,
        status=k.BATCH_RECEIVED,
        deposit_rule=k.DEPOSIT_RULE_SMALL_PLAN,
        deposit_due_date=k.DEPOSIT_DUE_DATE,
    )


def test_nested_tiers_are_clipped_by_the_plan_wide_six_percent_cap(
    api: ApiClient, plan
):
    """
    The two rounded tiers sum exactly to the deferrals and are then overridden by
    a cap that has nothing to do with the elected rates.

    "The plan-wide cap is six percent of compensation, rounded half up to whole
    cents, and `expected_match_cents` is the lesser of the raw match and that
    cap."

    "On success `validated_at` is stamped from the logical clock, the note is
    stored, the employer's `contribution_receivable_cents` is recomputed as the
    sum of `batch_total_cents` over that employer's batches still in `VALIDATED`
    status, the plan document's `total_validated_contributions_cents`,
    `aggregate_receivable_cents` and `contribution_control_delta_cents` are
    recomputed, and the batch's `version` is incremented by one."

    Design: Difficulty/combinatorial_formula/match_tier_nesting_capped_by_plan_wide_six_percent
    """
    fixtures.set_clock(api, k.PAYROLL_CLOCK)
    emp_ctx = _electing_employer(
        api, plan, k.PALISADE_SIGNATORY, **TIERED_100_AT_5_AND_100_AT_10
    )

    batch = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                emp_ctx.employer_id,
                payroll_provider_reference="PR-CAP-15",
                total_eligible_compensation_cents=k.CANONICAL_COMPENSATION_CENTS,
                total_deferral_cents=9000000,
                total_match_cents=6000000,
                total_loan_repayment_cents=0,
                participant_line_count=13,
            ),
            emp_ctx.headers,
        )
    )
    assert_resource_shape(batch, "PayrollBatch")
    assert_fields(
        batch,
        expected_match_cents=6000000,
        batch_total_cents=15000000,
        status=k.BATCH_RECEIVED,
        deposit_due_date=k.DEPOSIT_DUE_DATE,
    )

    validated = validate_single(
        api.validate_payroll_batch(
            batch["id"], f.validate_batch_payload(), plan.recordkeeper_headers
        )
    )
    assert_fields(
        validated,
        status=k.BATCH_VALIDATED,
        expected_match_cents=6000000,
        batch_total_cents=15000000,
        version=batch["version"] + 1,
    )
    assert_fields(emp_ctx.refresh(api), contribution_receivable_cents=15000000)
    assert_fields(
        plan.refresh(api),
        total_validated_contributions_cents=15000000,
        aggregate_receivable_cents=15000000,
        contribution_control_delta_cents=0,
    )


def _delivery(
    emp_ctx: EmployerContext,
    pay_period_start: str,
    pay_period_end: str,
    withholding_date: str,
    reference: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """A payroll delivery over an explicit half-open period."""
    return f.payroll_batch_payload(
        emp_ctx.employer_id,
        pay_period_start=pay_period_start,
        pay_period_end=pay_period_end,
        pay_date=withholding_date,
        withholding_date=withholding_date,
        payroll_provider_reference=reference,
        **overrides,
    )


def test_pay_periods_may_touch_but_never_overlap_within_one_employer(
    api: ApiClient, plan
):
    """
    Sharing a single boundary date is adjacency, sharing any interior day is
    overlap, and the whole comparison is scoped to one employer.

    "The interval also may not overlap the interval of any other payroll batch of
    the same employer, and because the interval is half-open, exact adjacency is
    permitted: a batch ending on 2026-06-15 and the next starting on 2026-06-15
    do not overlap, whereas any genuine overlap is rejected with
    `ERR_PAY_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pay_period_half_open_adjacency_allowed_containment_rejected
    """
    fixtures.set_clock(api, PAY_PERIOD_CLOCK)
    palisade = _electing_employer(api, plan, k.PALISADE_SIGNATORY)
    quarry = _electing_employer(
        api,
        plan,
        k.QUARRY_SIGNATORY,
        f.second_adopting_employer_payload(plan.plan_id),
    )

    incumbent = validate_created(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-01", "2026-07-16", "2026-07-16", "PR-OVL-A"),
            palisade.headers,
        )
    )

    tail = validate_created(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-16", "2026-08-01", "2026-08-03", "PR-OVL-B"),
            palisade.headers,
        )
    )
    assert_fields(tail, status=k.BATCH_RECEIVED, pay_period_start="2026-07-16")

    head = validate_created(
        api.create_payroll_batch(
            _delivery(palisade, "2026-06-16", "2026-07-01", "2026-07-02", "PR-OVL-C"),
            palisade.headers,
        )
    )
    assert_fields(head, status=k.BATCH_RECEIVED, pay_period_end="2026-07-01")

    validate_error(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-15", "2026-07-20", "2026-07-21", "PR-OVL-D"),
            palisade.headers,
        ),
        ERR_PAY_PERIOD_OVERLAP,
        expected_status=409,
    )
    validate_error(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-02", "2026-07-10", "2026-07-11", "PR-OVL-E"),
            palisade.headers,
        ),
        ERR_PAY_PERIOD_OVERLAP,
        expected_status=409,
    )
    validate_error(
        api.create_payroll_batch(
            _delivery(palisade, "2026-06-20", "2026-07-25", "2026-07-26", "PR-OVL-F"),
            palisade.headers,
        ),
        ERR_PAY_PERIOD_OVERLAP,
        expected_status=409,
    )

    twin = validate_created(
        api.create_payroll_batch(
            _delivery(
                quarry,
                "2026-07-01",
                "2026-07-16",
                "2026-07-17",
                "PR-OVL-J",
                participant_line_count=4,
            ),
            quarry.headers,
        )
    )
    assert_fields(twin, status=k.BATCH_RECEIVED, adopting_employer_id=quarry.employer_id)

    kept, _ = validate_collection(
        api.list_employer_payroll_batches(palisade.employer_id, palisade.headers),
        expected_total=3,
    )
    assert sorted(row["payroll_provider_reference"] for row in kept) == [
        "PR-OVL-A",
        "PR-OVL-B",
        "PR-OVL-C",
    ], "No rejected candidate may be persisted"
    assert incumbent["id"] in [row["id"] for row in kept]


def test_a_degenerate_period_is_caught_before_the_overlap_rule(api: ApiClient, plan):
    """
    The ordering rule sits above the overlap rule, so a reversed period that
    would also overlap is reported as an invalid period rather than a collision.

    "`pay_period_end` must be strictly after `pay_period_start`, and `pay_date`
    must be on or after `pay_period_start`; either failure is rejected with
    `ERR_INVALID_PAY_PERIOD`."

    "Priorities 40 through 51 are the temporal rules, in this order:
    `ERR_INVALID_PAY_PERIOD`, `ERR_PAY_PERIOD_OVERLAP`,
    `ERR_WITHHOLDING_DATE_OUT_OF_PERIOD`, `ERR_DEPOSIT_DATE_OUT_OF_RANGE`,
    `ERR_INVALID_RECOVERY_DATE`, `ERR_INVALID_ALLOCATION_WINDOW`,
    `ERR_ALLOCATION_WINDOW_OVERLAP`, `ERR_INVALID_BLACKOUT_WINDOW`,
    `ERR_BLACKOUT_WINDOW_CONFLICT`, `ERR_ELECTION_WINDOW_CLOSED`,
    `ERR_BLACKOUT_NOT_ENDED`, `ERR_INVALID_DISCLOSURE_PERIOD`."

    Design: Difficulty/resource_temporal_overlap/pay_period_half_open_adjacency_allowed_containment_rejected
    """
    fixtures.set_clock(api, PAY_PERIOD_CLOCK)
    palisade = _electing_employer(api, plan, k.PALISADE_SIGNATORY)
    validate_created(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-01", "2026-07-16", "2026-07-16", "PR-OVL-A"),
            palisade.headers,
        )
    )

    validate_error(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-10", "2026-07-05", "2026-07-11", "PR-OVL-G"),
            palisade.headers,
        ),
        ERR_INVALID_PAY_PERIOD,
        expected_status=422,
    )
    validate_error(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-20", "2026-07-20", "2026-07-21", "PR-OVL-H"),
            palisade.headers,
        ),
        ERR_INVALID_PAY_PERIOD,
        expected_status=422,
    )
    validate_error(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                palisade.employer_id,
                pay_period_start="2026-07-16",
                pay_period_end="2026-07-31",
                pay_date="2026-07-15",
                withholding_date="2026-07-20",
                payroll_provider_reference="PR-OVL-K",
            ),
            palisade.headers,
        ),
        ERR_INVALID_PAY_PERIOD,
        expected_status=422,
    )

    validate_collection(
        api.list_employer_payroll_batches(palisade.employer_id, palisade.headers),
        expected_total=1,
    )


def test_overlapping_period_outranks_the_repeated_payroll_reference(
    api: ApiClient, plan
):
    """
    A delivery that both collides temporally and repeats its reference is
    reported as the temporal failure, because the temporal rules sit above the
    uniqueness rules.

    "The payload names the employer through `adopting_employer_id` and describes
    the period with `pay_period_start`, `pay_period_end`, `pay_date`,
    `withholding_date` and a `payroll_provider_reference` of 1 to 64 characters
    issued by the employer's payroll system, which must be unique among that
    employer's batches — a repeat is rejected with
    `ERR_DUPLICATE_PAYROLL_REFERENCE`."

    "Priorities 52 through 65 are uniqueness and constraint-satisfaction rules, in
    this order: `ERR_DUPLICATE_PROVIDER_EIN`, `ERR_DUPLICATE_PLAN_NUMBER`,
    `ERR_DUPLICATE_EMPLOYER_EIN`, `ERR_DUPLICATE_PAYROLL_REFERENCE`,
    `ERR_DUPLICATE_FILING_YEAR`, `ERR_DUPLICATE_COMPLIANCE_TEST`,
    `ERR_TIER_FIELDS_MISMATCH`, `ERR_TIER_LIMITS_OUT_OF_ORDER`,
    `ERR_SIGNATORY_REQUIRED`, `ERR_ELIGIBILITY_MORE_RESTRICTIVE`,
    `ERR_VESTING_MORE_RESTRICTIVE`, `ERR_CENSUS_INCONSISTENT`,
    `ERR_NO_APPROVED_ELECTION`, `ERR_MATCH_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_pay_period_overlap_beats_duplicate_payroll_reference
    """
    fixtures.set_clock(api, PAY_PERIOD_CLOCK)
    palisade = _electing_employer(api, plan, k.PALISADE_SIGNATORY)
    incumbent = validate_created(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-01", "2026-07-16", "2026-07-16", "PR-DUP-13"),
            palisade.headers,
        )
    )

    validate_error(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-10", "2026-07-25", "2026-07-25", "PR-DUP-13"),
            palisade.headers,
        ),
        ERR_PAY_PERIOD_OVERLAP,
        expected_status=409,
    )
    validate_collection(
        api.list_employer_payroll_batches(palisade.employer_id, palisade.headers),
        expected_total=1,
    )
    assert_fields(
        validate_single(api.get_payroll_batch(incumbent["id"], palisade.headers)),
        status=k.BATCH_RECEIVED,
        payroll_provider_reference="PR-DUP-13",
        version=incumbent["version"],
    )

    validate_error(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-16", "2026-07-31", "2026-07-31", "PR-DUP-13"),
            palisade.headers,
        ),
        ERR_DUPLICATE_PAYROLL_REFERENCE,
        expected_status=409,
    )

    accepted = validate_created(
        api.create_payroll_batch(
            _delivery(palisade, "2026-07-16", "2026-07-31", "2026-07-31", "PR-DUP-14"),
            palisade.headers,
        )
    )
    assert_fields(accepted, status=k.BATCH_RECEIVED)
    validate_collection(
        api.list_employer_payroll_batches(palisade.employer_id, palisade.headers),
        expected_total=2,
    )


def test_computed_batch_fields_ignore_whatever_the_client_sends(api: ApiClient, plan):
    """
    Four fields on a delivered batch are computed, and a body that tries to
    dictate them cannot move any of them; the delivery alone moves no plan total.

    "And the deposit deadline is fixed: `deposit_rule` is
    `SMALL_PLAN_7_BUSINESS_DAY` when the employer's `is_small_plan` flag was true
    at the moment the batch was created and `GENERAL_15TH_BUSINESS_DAY`
    otherwise, and `deposit_due_date` follows from it."

    "Under the safe harbour the due date is the seventh business day after the
    `withholding_date`, counting forward from the day after withholding and
    skipping weekends and the federal holidays listed in §2.5; for a
    `withholding_date` of 2026-08-03 that lands on 2026-08-12."

    "A new batch opens in `status` `RECEIVED`, with `validated_at` and
    `reconciliation_note` null."

    Design: Corner/entities/corner_batch_total_and_due_date_are_computed_client_input_ignored
    """
    fixtures.set_clock(api, PAY_PERIOD_CLOCK)
    emp_ctx = _electing_employer(api, plan, k.PALISADE_SIGNATORY)
    assert_fields(emp_ctx.employer, is_small_plan=True)

    delivered = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                emp_ctx.employer_id,
                payroll_provider_reference="PR-CMP-13",
                batch_total_cents=1,
                deposit_due_date="2026-12-31",
                deposit_rule=k.DEPOSIT_RULE_GENERAL,
                expected_match_cents=1,
            ),
            emp_ctx.headers,
        )
    )

    assert_fields(
        delivered,
        batch_total_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        expected_match_cents=k.CANONICAL_BASIC_MATCH_CENTS,
        deposit_rule=k.DEPOSIT_RULE_SMALL_PLAN,
        deposit_due_date=k.DEPOSIT_DUE_DATE,
        status=k.BATCH_RECEIVED,
    )
    assert_null_fields(delivered, "validated_at", "reconciliation_note")

    assert_fields(emp_ctx.refresh(api), contribution_receivable_cents=0)
    assert_fields(
        plan.refresh(api),
        aggregate_receivable_cents=0,
        total_validated_contributions_cents=0,
    )


def test_a_wrong_match_is_a_reconciliation_failure_not_a_delivery_failure(
    api: ApiClient, plan
):
    """
    The match comparison is bound to reconciliation, not to delivery, and the
    actor check answers before it.

    "Note that `expected_match_cents` is computed and returned on the delivered
    batch even when it disagrees with the employer's submitted
    `total_match_cents` — the disagreement is not a delivery failure."

    "The acting service provider must be engaged on the batch's plan with
    `provider_type` `RECORDKEEPER`; any other firm, including a `TPA` or `TRUSTEE`
    on the same plan, is rejected with `ERR_NOT_PLAN_RECORDKEEPER`."

    "And the employer's submitted `total_match_cents` must equal the computed
    `expected_match_cents` exactly; a discrepancy is rejected with
    `ERR_MATCH_MISMATCH`."

    Design: Corner/validations/corner_match_mismatch_surfaces_at_validate_not_at_create
    """
    fixtures.set_clock(api, PAY_PERIOD_CLOCK)
    emp_ctx = _electing_employer(api, plan, k.PALISADE_SIGNATORY)

    wrong = validate_created(
        api.create_payroll_batch(
            _delivery(
                emp_ctx,
                "2026-08-01",
                "2026-08-16",
                "2026-08-03",
                "PR-2026-08-A",
                total_match_cents=3000000,
            ),
            emp_ctx.headers,
        )
    )
    read_back = validate_single(api.get_payroll_batch(wrong["id"], emp_ctx.headers))
    assert_fields(
        read_back,
        status=k.BATCH_RECEIVED,
        expected_match_cents=3750000,
        total_match_cents=3000000,
        batch_total_cents=7750000,
        version=1,
    )

    validate_error(
        api.validate_payroll_batch(
            wrong["id"],
            f.validate_batch_payload("Trustee attempts the recordkeeper reconciliation."),
            plan.trustee_headers,
        ),
        ERR_NOT_PLAN_RECORDKEEPER,
        expected_status=409,
    )
    validate_error(
        api.validate_payroll_batch(
            wrong["id"], f.validate_batch_payload(), plan.recordkeeper_headers
        ),
        ERR_MATCH_MISMATCH,
        expected_status=409,
    )
    assert_fields(
        validate_single(api.get_payroll_batch(wrong["id"], emp_ctx.headers)),
        status=k.BATCH_RECEIVED,
        version=1,
    )

    right = validate_created(
        api.create_payroll_batch(
            _delivery(emp_ctx, "2026-08-16", "2026-08-31", "2026-08-17", "PR-2026-08-B"),
            emp_ctx.headers,
        )
    )
    validated = validate_single(
        api.validate_payroll_batch(
            right["id"], f.validate_batch_payload(), plan.recordkeeper_headers
        )
    )
    assert_fields(
        validated,
        status=k.BATCH_VALIDATED,
        batch_total_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        reconciliation_note=k.RECONCILIATION_NOTE,
    )
    assert_fields(
        emp_ctx.refresh(api),
        contribution_receivable_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )


def test_withholding_and_recovery_windows_are_pinned_at_both_ends(
    api: ApiClient, plan
):
    """
    Both date windows are closed at both ends, the 31-day withholding boundary is
    inclusive, and a computed correction cannot be recomputed.

    "The `withholding_date`, the date elective deferrals were actually withheld
    from wages, must be on or after `pay_period_start` and no later than 31
    calendar days after `pay_period_end`; outside that range it is rejected with
    `ERR_WITHHOLDING_DATE_OUT_OF_PERIOD`."

    "The `recovery_date` must be on or after the deposit's `deposit_date` and must
    not be later than the logical-clock calendar date; outside that range it is
    rejected with `ERR_INVALID_RECOVERY_DATE`."

    "The deposit must be `POSTED`, its `timeliness_status` must be `LATE` — a
    deposit that is `TIMELY`, already `CORRECTION_COMPUTED` or `CORRECTED` is
    rejected with `ERR_CORRECTION_INVALID_STATE` — and the acting firm must be the
    plan's `RECORDKEEPER`."

    Design: Corner/errors/corner_withholding_and_recovery_date_windows_rejected
    """
    fixtures.set_clock(api, CORRECTION_WINDOW_CLOCK)
    emp_ctx = _electing_employer(api, plan, k.PALISADE_SIGNATORY)

    # The pay period itself is well formed and `pay_date` is inside it, so the
    # only defect left is a `withholding_date` earlier than `pay_period_start`.
    # Reusing `_delivery` here would set `pay_date` to the withholding date too
    # and trip the higher-priority `ERR_INVALID_PAY_PERIOD` instead.
    validate_error(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                emp_ctx.employer_id,
                pay_period_start="2026-08-01",
                pay_period_end="2026-08-16",
                pay_date="2026-08-03",
                withholding_date="2026-07-31",
                payroll_provider_reference="PR-EARLY-WH",
            ),
            emp_ctx.headers,
        ),
        ERR_WITHHOLDING_DATE_OUT_OF_PERIOD,
        expected_status=422,
    )
    validate_error(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                emp_ctx.employer_id,
                pay_period_start="2026-08-01",
                pay_period_end="2026-08-16",
                pay_date="2026-08-03",
                withholding_date="2026-09-17",
                payroll_provider_reference="PR-LATE-WH",
            ),
            emp_ctx.headers,
        ),
        ERR_WITHHOLDING_DATE_OUT_OF_PERIOD,
        expected_status=422,
    )

    boundary = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                emp_ctx.employer_id,
                pay_period_start="2026-06-01",
                pay_period_end="2026-06-16",
                pay_date="2026-06-03",
                withholding_date="2026-07-17",
                payroll_provider_reference="PR-BOUNDARY-31D",
            ),
            emp_ctx.headers,
        )
    )
    assert_fields(boundary, withholding_date="2026-07-17", status=k.BATCH_RECEIVED)

    batch = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                emp_ctx.employer_id,
                pay_period_start="2026-08-01",
                pay_period_end="2026-08-16",
                pay_date="2026-08-03",
                withholding_date="2026-08-03",
                payroll_provider_reference="PR-2026-08-A",
            ),
            emp_ctx.headers,
        )
    )
    validate_single(
        api.validate_payroll_batch(
            batch["id"], f.validate_batch_payload(), plan.recordkeeper_headers
        )
    )
    deposit = validate_created(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                batch["id"],
                deposit_date="2026-08-20",
                amount_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
                deposit_reference="TR-LATE-1",
            ),
            emp_ctx.headers,
        )
    )
    posted = validate_single(
        api.post_remittance_deposit(
            deposit["id"],
            f.post_deposit_payload("TRUST-POST-0001"),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        posted,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_LATE,
        late_by_business_days=6,
    )
    assert_fields(
        validate_single(api.get_payroll_batch(batch["id"], emp_ctx.headers)),
        deposit_due_date=k.DEPOSIT_DUE_DATE,
    )

    validate_error(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(k.CORRECTION_VFCP_RECOVERY_DATE, "2026-08-19"),
            plan.recordkeeper_headers,
        ),
        ERR_INVALID_RECOVERY_DATE,
        expected_status=422,
    )
    validate_error(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(k.CORRECTION_VFCP_RECOVERY_DATE, "2026-08-26"),
            plan.recordkeeper_headers,
        ),
        ERR_INVALID_RECOVERY_DATE,
        expected_status=422,
    )

    computed = validate_single(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(k.CORRECTION_VFCP_RECOVERY_DATE, "2026-08-25"),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        computed,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
        correction_method=k.CORRECTION_VFCP_RECOVERY_DATE,
        recovery_date="2026-08-25",
        lost_earnings_cents=27247,
        restoration_cents=27247,
        excise_tax_cents=4087,
    )

    validate_error(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(
                k.CORRECTION_IRS_6621_UNDERPAYMENT, "2026-08-25"
            ),
            plan.recordkeeper_headers,
        ),
        ERR_CORRECTION_INVALID_STATE,
        expected_status=409,
    )
