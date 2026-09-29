"""Employer exits: the settlement cascade, the single transfer slot and its guards."""

from typing import Any, Dict

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_BATCH_INVALID_STATE,
    ERR_BLACKOUT_NOT_ENDED,
    ERR_BLACKOUT_WINDOW_CONFLICT,
    ERR_EMPLOYER_INVALID_STATE,
    ERR_INVALID_BLACKOUT_WINDOW,
    ERR_PROVIDER_NOT_PENDING,
    ERR_TEST_INVALID_STATE,
    ERR_UNREMITTED_CONTRIBUTIONS,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_equals,
    assert_null_fields,
    assert_plan_control_invariants,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from test_helpers.test_users import regulator_headers
from prd_bench_local_runner.testing import validate_error

# A spin-off whose blackout opens the week after the payroll is remitted and
# closes three days before the settlement clock.
CASCADE_BLACKOUT_START_DATE = "2026-08-17"
CASCADE_BLACKOUT_END_DATE = "2026-08-21"
CASCADE_REQUESTED_EXIT_DATE = "2026-08-31"
CASCADE_SETTLEMENT_CLOCK = "2026-08-24T09:00:00Z"

# The day after a deposit lands one business day late, which is also the day
# the repeated-action walk runs.
MID_AUGUST_CLOCK = "2026-08-14T09:00:00Z"

# A window whose end precedes its start, and the same window well ordered.
REVERSED_BLACKOUT_START_DATE = "2026-08-28"
REVERSED_BLACKOUT_END_DATE = "2026-08-24"
ORDERED_BLACKOUT_START_DATE = "2026-08-24"
ORDERED_BLACKOUT_END_DATE = "2026-08-28"
LATE_SEPTEMBER_EXIT_DATE = "2026-08-31"

# The incumbent slot, a neighbour one calendar day away from it, and the day
# the incumbent's window closes.
SLOT_BLACKOUT_START_DATE = "2026-09-01"
SLOT_BLACKOUT_END_DATE = "2026-09-15"
NEIGHBOUR_BLACKOUT_START_DATE = "2026-09-16"
NEIGHBOUR_BLACKOUT_END_DATE = "2026-09-19"
SEPTEMBER_EXIT_DATE = "2026-09-30"
SLOT_CLOSE_CLOCK = "2026-09-16T00:00:00Z"

# Exactly five calendar days of gap, and exactly six.
FIVE_DAY_GAP_START_DATE = "2026-09-20"
FIVE_DAY_GAP_END_DATE = "2026-09-24"
SIX_DAY_GAP_START_DATE = "2026-09-21"
SIX_DAY_GAP_END_DATE = "2026-09-25"

SLOT_REVERSAL_REASON = "Successor trustee declined the transfer of assets."
CONTROL_REVERSAL_REASON = (
    "Successor plan's trustee declined the asset transfer; the employer stays "
    "in the pool."
)

# The census restatement that lifts the second employer from four to six.
RESTATED_PARTICIPANT_COUNT = 6

SECOND_REGISTRATION_EFFECTIVE_DATE = "2026-09-01"
EARLY_DEPOSIT_REFERENCE = "TR-TOO-EARLY-IN-LIFECYCLE"
ACCEPTED_DEPOSIT_REFERENCE = "TR-ON-TIME-1"
SECOND_RECONCILIATION_NOTE = "Second reconciliation attempt."


def _requested_exit(
    api: ApiClient,
    emp_ctx: EmployerContext,
    blackout_start_date: str,
    blackout_end_date: str,
    requested_exit_date: str = SEPTEMBER_EXIT_DATE,
    exit_type: str = k.EXIT_SPINOFF_TO_SINGLE_PLAN,
) -> Dict[str, Any]:
    """Request an exit over an explicitly stated blackout window."""
    return fixtures.requested_exit(
        api,
        emp_ctx,
        blackout_start_date=blackout_start_date,
        blackout_end_date=blackout_end_date,
        requested_exit_date=requested_exit_date,
        exit_type=exit_type,
    )


def _second_active_plan(api: ApiClient, plan: PlanContext) -> PlanContext:
    """Bring a second plan document of the same sponsor all the way to ACTIVE."""
    second = fixtures.second_plan(api, plan)
    recordkeeper = fixtures.engage_provider(
        api, plan.provider_id, f.recordkeeper_payload(second["id"])
    )
    trustee = fixtures.engage_provider(
        api, plan.provider_id, f.trustee_payload(second["id"])
    )
    second_ctx = PlanContext(
        provider=plan.provider,
        plan=second,
        recordkeeper=recordkeeper,
        trustee=trustee,
    )
    second_ctx.named_fiduciary_allocation = fixtures.acknowledge_role(
        api,
        fixtures.allocate_role(
            api, second_ctx, recordkeeper["id"], k.FIDUCIARY_NAMED_FIDUCIARY_3_16
        ),
        k.NAMED_FIDUCIARY_ACKNOWLEDGMENT,
    )
    second_ctx.trustee_allocation = fixtures.acknowledge_role(
        api,
        fixtures.allocate_role(
            api, second_ctx, trustee["id"], k.FIDUCIARY_TRUSTEE_403A
        ),
        k.TRUSTEE_ACKNOWLEDGMENT,
    )
    second_ctx.plan = validate_single(
        api.activate_plan_document(second_ctx.plan_id, second_ctx.provider_headers)
    )
    return second_ctx


def test_one_settlement_supersedes_an_election_closes_a_test_and_retotals_the_plan(
    api: ApiClient, plan, employer
):
    """
    A settle request that names only the transfer rewrites the employer, its
    election, one of its two compliance tests and nine plan control totals, and the
    money splits between the plan and the successor without either side drifting.

    "`gross_account_balance_cents` is the employer's `account_balance_cents` as it
    stands then, and `transferred_participant_count` is its `participant_count` as it
    stands then."

    "Two worked cases: a gross balance of 8500000 cents for 13 participants under
    `SPINOFF_TO_SINGLE_PLAN` applies 16250 and 250000, leaves nothing unrecovered, and
    transfers 8233750; a gross balance of 100000 cents for 4 participants under the
    same exit type applies 5000 and then only 95000 of the flat fee, leaves 155000
    unrecovered, and transfers nothing at all."

    "The ledger routing is deliberate: `deductions_applied_cents` stays inside the
    plan and accumulates into the plan document's `expense_recovered_cents`,
    `transfer_amount_cents` leaves the plan and accumulates into
    `transferred_out_cents`, and the employer's own `account_balance_cents` is zeroed —
    which is exactly why `contribution_control_delta_cents` remains at zero across a
    settlement."

    "The employer's `APPROVED` plan design election moves to `SUPERSEDED` with its own
    `version` incremented."

    "Every `EMPLOYER_LEVEL` compliance test naming that employer moves to `CLOSED`
    with `closed_reason` `EMPLOYER_EXITED`."

    "`cumulative_enrolled_participant_count` is a monotone control total: it increases
    by the admitted headcount on every employer admission and by every positive census
    delta, decreases by every negative census delta, and is *never* reduced by an
    exit."

    Design: Difficulty/transitive_cascade/exit_settlement_supersedes_election_closes_tests_and_retotals_plan
    """
    batch = fixtures.validated_batch(api, employer)
    fixtures.timely_deposit(api, employer, batch)
    employer_level = fixtures.completed_test(
        api, plan, f.employer_level_test_payload(plan.plan_id, employer.employer_id)
    )
    plan_level = fixtures.completed_test(api, plan)
    assert_fields(employer_level, scope=k.SCOPE_EMPLOYER_LEVEL, status=k.TEST_PASSED)
    assert_fields(plan_level, scope=k.SCOPE_PLAN_LEVEL, status=k.TEST_PASSED)

    settled = fixtures.settled_exit(
        api,
        employer,
        settle_clock=CASCADE_SETTLEMENT_CLOCK,
        blackout_start_date=CASCADE_BLACKOUT_START_DATE,
        blackout_end_date=CASCADE_BLACKOUT_END_DATE,
        requested_exit_date=CASCADE_REQUESTED_EXIT_DATE,
    )
    assert_fields(
        settled,
        status=k.TRANSFER_SETTLED,
        exit_type=k.EXIT_SPINOFF_TO_SINGLE_PLAN,
        transferred_participant_count=13,
        gross_account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        admin_recovery_cents=16250,
        flat_exit_fee_cents=250000,
        deductions_applied_cents=266250,
        unrecovered_deduction_cents=0,
        transfer_amount_cents=8233750,
        settled_amount_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    assert_instant_equals(settled["settled_at"], CASCADE_SETTLEMENT_CLOCK, "settled_at")

    departed = employer.refresh(api)
    assert_fields(
        departed, adoption_status=k.EMPLOYER_EXITED, account_balance_cents=0
    )
    assert_instant_equals(
        departed["exited_at"], CASCADE_SETTLEMENT_CLOCK, "exited_at"
    )
    assert_fields(
        validate_single(
            api.get_design_election(employer.election_id, plan.provider_headers)
        ),
        status=k.ELECTION_SUPERSEDED,
    )
    assert_fields(
        validate_single(
            api.get_compliance_test(employer_level["id"], plan.provider_headers)
        ),
        status=k.TEST_CLOSED,
        closed_reason=k.CLOSED_EMPLOYER_EXITED,
    )
    survivor = validate_single(
        api.get_compliance_test(plan_level["id"], plan.provider_headers)
    )
    assert_fields(survivor, status=k.TEST_PASSED)
    assert_null_fields(survivor, "closed_reason")

    retotalled = plan.refresh(api)
    assert_fields(
        retotalled,
        participant_count=0,
        transferred_out_participant_count=13,
        cumulative_enrolled_participant_count=13,
        expense_recovered_cents=266250,
        transferred_out_cents=8233750,
        total_assets_cents=266250,
        active_employer_count=0,
        aggregate_receivable_cents=0,
        total_validated_contributions_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    assert_plan_control_invariants(retotalled)


def test_a_suspended_employer_is_refused_before_its_own_window_is_even_read(
    api: ApiClient, plan, employer, batch
):
    """
    One exit request breaks three separate rules at once — the employer's state, the
    order of its blackout dates and an unfunded late-deposit correction — and only the
    state refusal may surface; clearing that one alone exposes the next.

    "Three checks apply in order: the employer's `adoption_status` must be `ACTIVE`,
    so a `SUSPENDED` employer may not request an exit and is rejected with
    `ERR_EMPLOYER_INVALID_STATE`; the dates must be well ordered, with
    `blackout_end_date` on or after `blackout_start_date` and `requested_exit_date` on
    or after `blackout_end_date`, failing which the request is rejected with
    `ERR_INVALID_BLACKOUT_WINDOW`; and the employer must carry no remittance deposit
    that is `POSTED` with a `timeliness_status` of `LATE` or `CORRECTION_COMPUTED`,
    failing which it is rejected with `ERR_OPEN_LATE_DEPOSIT_CORRECTION`."

    "Priorities 10 through 23 are state preconditions, in this order:
    `ERR_PROVIDER_NOT_PENDING`, `ERR_PLAN_ALREADY_ACTIVE`, `ERR_PLAN_NOT_ACTIVE`,
    `ERR_ALLOCATION_ALREADY_ACKNOWLEDGED`, `ERR_ELECTION_INVALID_STATE`,
    `ERR_EMPLOYER_INVALID_STATE`, `ERR_BATCH_INVALID_STATE`,
    `ERR_DEPOSIT_INVALID_STATE`, `ERR_DEPOSIT_NOT_REVERSIBLE`,
    `ERR_CORRECTION_INVALID_STATE`, `ERR_TEST_INVALID_STATE`,
    `ERR_FILING_INVALID_STATE`, `ERR_AUDIT_NOT_REQUIRED`,
    `ERR_TRANSFER_INVALID_STATE`."

    "Money and quota checks are deliberately last, so that a request which is
    structurally or procedurally wrong never reports a financial reason."

    "A new transfer opens in `REQUESTED` with `approved_at`, `settled_at`,
    `reversal_reason` and every waterfall figure null, and the employer advances from
    `ACTIVE` to `EXIT_REQUESTED` with its `version` incremented by one."

    Design: Difficulty/priority_pair_validation_conflict/priority_conflict_employer_state_beats_blackout_window_on_exit_request
    """
    deposit = fixtures.late_deposit(api, employer, batch)
    assert_fields(deposit, timeliness_status=k.TIMELINESS_LATE, late_by_business_days=1)
    assert_fields(employer.refresh(api), adoption_status=k.EMPLOYER_SUSPENDED)
    fixtures.set_clock(api, MID_AUGUST_CLOCK)

    ill_ordered = f.exit_transfer_payload(
        employer.employer_id,
        blackout_start_date=REVERSED_BLACKOUT_START_DATE,
        blackout_end_date=REVERSED_BLACKOUT_END_DATE,
        requested_exit_date=LATE_SEPTEMBER_EXIT_DATE,
    )
    validate_error(
        api.create_exit_transfer(ill_ordered, employer.headers),
        ERR_EMPLOYER_INVALID_STATE,
        expected_status=409,
    )
    validate_collection(
        api.list_employer_exit_transfers(employer.employer_id, employer.headers),
        expected_total=0,
        expected_len=0,
    )
    assert_fields(employer.refresh(api), adoption_status=k.EMPLOYER_SUSPENDED)

    computed = fixtures.corrected_computation(api, employer, deposit)
    assert_fields(computed, lost_earnings_cents=2096, excise_tax_cents=0)
    funded = fixtures.funded_correction(api, employer, deposit)
    assert_fields(funded, timeliness_status=k.TIMELINESS_CORRECTED)
    assert_fields(employer.refresh(api), adoption_status=k.EMPLOYER_ACTIVE)

    validate_error(
        api.create_exit_transfer(ill_ordered, employer.headers),
        ERR_INVALID_BLACKOUT_WINDOW,
        expected_status=422,
    )
    accepted = validate_created(
        api.create_exit_transfer(
            f.exit_transfer_payload(
                employer.employer_id,
                blackout_start_date=ORDERED_BLACKOUT_START_DATE,
                blackout_end_date=ORDERED_BLACKOUT_END_DATE,
                requested_exit_date=LATE_SEPTEMBER_EXIT_DATE,
            ),
            employer.headers,
        )
    )
    assert_fields(
        accepted,
        status=k.TRANSFER_REQUESTED,
        blackout_start_date=ORDERED_BLACKOUT_START_DATE,
        blackout_end_date=ORDERED_BLACKOUT_END_DATE,
        version=1,
    )
    assert_null_fields(
        accepted,
        "approved_at",
        "settled_at",
        "reversal_reason",
        "gross_account_balance_cents",
        "transfer_amount_cents",
    )
    assert_fields(
        employer.refresh(api), adoption_status=k.EMPLOYER_EXIT_REQUESTED
    )


def test_the_transfer_slot_is_released_by_a_reversal_and_not_by_the_calendar(
    api: ApiClient, plan, employer, second_employer
):
    """
    A second employer's window sits one day outside the incumbent's and is refused
    three times over: while the incumbent is merely approved, after its blackout has
    closed, and after it has settled — and it is admitted the moment the incumbent is
    reversed.

    "On success `approved_at` is stamped from the logical clock, the transfer moves to
    `APPROVED`, the employer advances from `EXIT_REQUESTED` to `SPINOFF_IN_PROGRESS`,
    and both `version` values are incremented by one."

    "Collision is generous: the new window may neither overlap nor come within five
    calendar days of the blackout window of any other exit transfer of the same plan
    whose `status` is not `REVERSED`."

    "A `SETTLED` transfer still holds the slot, and only a `REVERSED` one releases
    it."

    "The deductions are then satisfied out of the gross balance as ordered buckets:
    administrative recovery is satisfied first, taking the lesser of
    `admin_recovery_cents` and the gross balance; the flat fee is satisfied second out
    of whatever remains, taking the lesser of `flat_exit_fee_cents` and that
    remainder."

    "On success the transfer moves to `REVERSED`, the employer returns from `EXITED` to
    `SPINOFF_IN_PROGRESS`, its `account_balance_cents` is restored to the
    pre-settlement gross and its `exited_at` is cleared, and every plan control total
    is recomputed so that both `headcount_control_delta` and
    `contribution_control_delta_cents` return to exactly zero with no drift."

    Design: Difficulty/resource_temporal_overlap/exit_blackout_window_slot_held_until_reversal
    """
    incumbent = _requested_exit(
        api, employer, SLOT_BLACKOUT_START_DATE, SLOT_BLACKOUT_END_DATE
    )
    approved = validate_single(
        api.approve_exit_transfer(incumbent["id"], plan.provider_headers)
    )
    assert_fields(approved, status=k.TRANSFER_APPROVED, version=2)
    assert_instant_equals(approved["approved_at"], k.DEFAULT_CLOCK, "approved_at")
    assert_fields(
        employer.refresh(api), adoption_status=k.EMPLOYER_SPINOFF_IN_PROGRESS
    )

    neighbour = _requested_exit(
        api,
        second_employer,
        NEIGHBOUR_BLACKOUT_START_DATE,
        NEIGHBOUR_BLACKOUT_END_DATE,
        exit_type=k.EXIT_TRANSFER_TO_OTHER_PEP,
    )
    validate_error(
        api.approve_exit_transfer(neighbour["id"], plan.provider_headers),
        ERR_BLACKOUT_WINDOW_CONFLICT,
        expected_status=409,
    )

    fixtures.set_clock(api, SLOT_CLOSE_CLOCK)
    settled = validate_single(
        api.settle_exit_transfer(incumbent["id"], plan.provider_headers)
    )
    assert_fields(
        settled,
        status=k.TRANSFER_SETTLED,
        gross_account_balance_cents=0,
        transferred_participant_count=13,
        admin_recovery_cents=16250,
        flat_exit_fee_cents=250000,
        deductions_applied_cents=0,
        unrecovered_deduction_cents=266250,
        transfer_amount_cents=0,
        settled_amount_cents=0,
    )
    validate_error(
        api.approve_exit_transfer(neighbour["id"], plan.provider_headers),
        ERR_BLACKOUT_WINDOW_CONFLICT,
        expected_status=409,
    )
    unmoved = validate_single(
        api.get_exit_transfer(neighbour["id"], second_employer.headers)
    )
    assert_fields(unmoved, status=k.TRANSFER_REQUESTED, version=1)
    assert_null_fields(unmoved, "approved_at")

    unwound = validate_single(
        api.reverse_exit_transfer(
            incumbent["id"],
            f.reverse_transfer_payload(SLOT_REVERSAL_REASON),
            plan.provider_headers,
        )
    )
    assert_fields(
        unwound, status=k.TRANSFER_REVERSED, reversal_reason=SLOT_REVERSAL_REASON
    )
    restored = employer.refresh(api)
    assert_fields(
        restored,
        adoption_status=k.EMPLOYER_SPINOFF_IN_PROGRESS,
        account_balance_cents=0,
    )
    assert_null_fields(restored, "exited_at")

    freed = validate_single(
        api.approve_exit_transfer(neighbour["id"], plan.provider_headers)
    )
    assert_fields(freed, status=k.TRANSFER_APPROVED, version=2)
    assert_instant_equals(freed["approved_at"], SLOT_CLOSE_CLOCK, "approved_at")
    assert_plan_control_invariants(plan.refresh(api))


def test_five_calendar_days_of_gap_conflict_where_six_are_admitted(
    api: ApiClient, plan, employer, second_employer
):
    """
    The buffer is measured, not intersected: a window that begins five days after the
    incumbent's closes is refused, and the very same window one day later is approved
    on an identical arrangement of the sponsor's other plan.

    "The gap between two non-overlapping windows is the whole number of calendar days
    from the earlier window's `blackout_end_date` to the later window's
    `blackout_start_date`; a gap of five days or fewer conflicts and a gap of six days
    or more is accepted."

    "Collision is generous: the new window may neither overlap nor come within five
    calendar days of the blackout window of any other exit transfer of the same plan
    whose `status` is not `REVERSED`."

    "A conflict is rejected with `ERR_BLACKOUT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/exit_blackout_window_slot_held_until_reversal
    """
    incumbent = _requested_exit(
        api, employer, SLOT_BLACKOUT_START_DATE, SLOT_BLACKOUT_END_DATE
    )
    validate_single(api.approve_exit_transfer(incumbent["id"], plan.provider_headers))
    five_days_out = _requested_exit(
        api, second_employer, FIVE_DAY_GAP_START_DATE, FIVE_DAY_GAP_END_DATE
    )
    validate_error(
        api.approve_exit_transfer(five_days_out["id"], plan.provider_headers),
        ERR_BLACKOUT_WINDOW_CONFLICT,
        expected_status=409,
    )

    other_plan = _second_active_plan(api, plan)
    other_incumbent = _requested_exit(
        api,
        fixtures.active_employer(api, other_plan),
        SLOT_BLACKOUT_START_DATE,
        SLOT_BLACKOUT_END_DATE,
    )
    validate_single(
        api.approve_exit_transfer(
            other_incumbent["id"], other_plan.provider_headers
        )
    )
    six_days_out = _requested_exit(
        api,
        fixtures.second_active_employer(api, other_plan),
        SIX_DAY_GAP_START_DATE,
        SIX_DAY_GAP_END_DATE,
    )
    admitted = validate_single(
        api.approve_exit_transfer(six_days_out["id"], other_plan.provider_headers)
    )
    assert_fields(
        admitted,
        status=k.TRANSFER_APPROVED,
        blackout_start_date=SIX_DAY_GAP_START_DATE,
        blackout_end_date=SIX_DAY_GAP_END_DATE,
        version=2,
    )
    assert_fields(
        validate_single(
            api.get_exit_transfer(five_days_out["id"], second_employer.headers)
        ),
        status=k.TRANSFER_REQUESTED,
        version=1,
    )


def test_a_reversal_puts_both_control_equations_back_where_it_found_them(
    api: ApiClient, plan, employer
):
    """
    A settlement moves headcount and money into three different accumulators and
    zeroes the employer's balance destructively; the reversal has to reconstruct all
    of it, including a census restatement made before the exit, and it must leave the
    monotone enrolment accumulator alone in both directions.

    "`cumulative_enrolled_participant_count` is a monotone control total: it increases
    by the admitted headcount on every employer admission and by every positive census
    delta, decreases by every negative census delta, and is *never* reduced by an
    exit."

    "`headcount_control_delta` is `participant_count` plus
    `transferred_out_participant_count` minus `cumulative_enrolled_participant_count`,
    and it too must be exactly zero after every trigger above."

    "And the plan document's `participant_count`, `transferred_out_participant_count`,
    `active_employer_count`, `audit_required`, `total_assets_cents`,
    `transferred_out_cents`, `expense_recovered_cents` and both control deltas are all
    recomputed — with `cumulative_enrolled_participant_count` deliberately left alone,
    since an exit never reduces the monotone enrolment total, which is precisely why
    `headcount_control_delta` stays at zero once `transferred_out_participant_count`
    absorbs the departed headcount."

    "Compensating operations must return the ledger to where it was, with no drift."

    "On success the transfer moves to `REVERSED`, the employer returns from `EXITED` to
    `SPINOFF_IN_PROGRESS`, its `account_balance_cents` is restored to the
    pre-settlement gross and its `exited_at` is cleared, and every plan control total
    is recomputed so that both `headcount_control_delta` and
    `contribution_control_delta_cents` return to exactly zero with no drift."

    Design: Difficulty/compensating_invariant/exit_reversal_restores_headcount_control_delta_to_zero
    """
    small = fixtures.second_active_employer(
        api,
        plan,
        participant_count=4,
        hce_count=1,
        nhce_count=3,
        benefiting_hce_count=1,
        benefiting_nhce_count=3,
    )
    batch = fixtures.validated_batch(api, employer)
    fixtures.timely_deposit(api, employer, batch)
    closed_test = fixtures.completed_test(
        api, plan, f.employer_level_test_payload(plan.plan_id, employer.employer_id)
    )
    assert_fields(
        validate_single(
            api.update_adopting_employer_census(
                small.employer_id,
                f.census_payload(
                    participant_count=RESTATED_PARTICIPANT_COUNT,
                    hce_count=2,
                    nhce_count=4,
                    benefiting_hce_count=2,
                    benefiting_nhce_count=4,
                ),
                small.headers,
            )
        ),
        participant_count=RESTATED_PARTICIPANT_COUNT,
    )

    baseline = plan.refresh(api)
    assert_fields(
        baseline,
        participant_count=19,
        cumulative_enrolled_participant_count=19,
        transferred_out_participant_count=0,
        total_assets_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        transferred_out_cents=0,
        expense_recovered_cents=0,
    )
    assert_plan_control_invariants(baseline)

    transfer = fixtures.settled_exit(
        api,
        employer,
        settle_clock=SLOT_CLOSE_CLOCK,
        blackout_start_date=SLOT_BLACKOUT_START_DATE,
        blackout_end_date=SLOT_BLACKOUT_END_DATE,
        requested_exit_date=SEPTEMBER_EXIT_DATE,
    )
    assert_fields(
        transfer,
        status=k.TRANSFER_SETTLED,
        admin_recovery_cents=16250,
        flat_exit_fee_cents=250000,
        deductions_applied_cents=266250,
        unrecovered_deduction_cents=0,
        transfer_amount_cents=8233750,
        settled_amount_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    emptied = employer.refresh(api)
    assert_fields(
        emptied, adoption_status=k.EMPLOYER_EXITED, account_balance_cents=0
    )
    assert_instant_equals(emptied["exited_at"], SLOT_CLOSE_CLOCK, "exited_at")
    after_settlement = plan.refresh(api)
    assert_fields(
        after_settlement,
        participant_count=RESTATED_PARTICIPANT_COUNT,
        transferred_out_participant_count=13,
        cumulative_enrolled_participant_count=19,
        total_assets_cents=266250,
        transferred_out_cents=8233750,
        expense_recovered_cents=266250,
        total_validated_contributions_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        active_employer_count=1,
        audit_required=False,
    )
    assert_plan_control_invariants(after_settlement)

    unwound = fixtures.reversed_exit(
        api, employer, transfer, CONTROL_REVERSAL_REASON
    )
    assert_fields(
        unwound, status=k.TRANSFER_REVERSED, reversal_reason=CONTROL_REVERSAL_REASON
    )
    returned = employer.refresh(api)
    assert_fields(
        returned,
        adoption_status=k.EMPLOYER_SPINOFF_IN_PROGRESS,
        account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    assert_null_fields(returned, "exited_at")

    final = plan.refresh(api)
    assert_fields(
        final,
        participant_count=19,
        transferred_out_participant_count=0,
        cumulative_enrolled_participant_count=19,
        total_assets_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        transferred_out_cents=0,
        expense_recovered_cents=0,
    )
    assert_plan_control_invariants(final)
    assert final["version"] > baseline["version"], (
        "the settlement and its reversal both recompute the plan, so the document "
        "cannot come back on the version it started from"
    )
    assert_fields(
        validate_single(
            api.get_design_election(employer.election_id, plan.provider_headers)
        ),
        status=k.ELECTION_SUPERSEDED,
    )
    assert_fields(
        validate_single(
            api.get_compliance_test(closed_test["id"], plan.provider_headers)
        ),
        status=k.TEST_CLOSED,
        closed_reason=k.CLOSED_EMPLOYER_EXITED,
    )


def test_the_settlement_reads_the_calendar_before_it_reads_the_ledger(
    api: ApiClient, plan: PlanContext, employer: EmployerContext, batch: Dict[str, Any]
):
    """
    A settlement attempted while the blackout is open and a reconciled batch is
    still unremitted is refused on the calendar alone; only once the window has
    closed does the outstanding money surface as the reason.

    "the logical-clock calendar date must be strictly after `blackout_end_date`,
    since assets cannot move while the blackout is still open, and a settlement on
    or before that date is rejected with `ERR_BLACKOUT_NOT_ENDED`"

    "the employer must have no payroll batch left in `VALIDATED` status awaiting
    remittance, failing which it is rejected with `ERR_UNREMITTED_CONTRIBUTIONS`"

    "The settlement figures are captured at the settlement instant, not at request
    time."

    "a gross balance of 8500000 cents for 13 participants under
    `SPINOFF_TO_SINGLE_PLAN` applies 16250 and 250000, leaves nothing unrecovered,
    and transfers 8233750"

    Design: Corner/errors/corner_exit_settlement_guards_rejected
    """
    transfer = fixtures.approved_exit(api, employer)
    assert_fields(
        transfer,
        status=k.TRANSFER_APPROVED,
        exit_type=k.EXIT_SPINOFF_TO_SINGLE_PLAN,
        blackout_start_date=k.BLACKOUT_START_DATE,
        blackout_end_date=k.BLACKOUT_END_DATE,
    )
    assert_fields(batch, status=k.BATCH_VALIDATED, deposit_due_date=k.DEPOSIT_DATE_SEVENTH_BUSINESS_DAY)

    fixtures.set_clock(api, MID_AUGUST_CLOCK)
    validate_error(
        api.settle_exit_transfer(transfer["id"], plan.provider_headers),
        ERR_BLACKOUT_NOT_ENDED,
        expected_status=409,
    )

    fixtures.set_clock(api, k.POST_BLACKOUT_CLOCK)
    validate_error(
        api.settle_exit_transfer(transfer["id"], plan.provider_headers),
        ERR_UNREMITTED_CONTRIBUTIONS,
        expected_status=409,
    )
    still_approved = validate_single(
        api.get_exit_transfer(transfer["id"], plan.provider_headers)
    )
    assert_fields(still_approved, status=k.TRANSFER_APPROVED)
    assert_null_fields(
        still_approved,
        "settled_at",
        "gross_account_balance_cents",
        "transfer_amount_cents",
    )

    deposit = fixtures.pending_deposit(
        api,
        employer,
        batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE,
        deposit_reference=k.DEPOSIT_REFERENCE,
    )
    posted = validate_single(
        api.post_remittance_deposit(
            deposit["id"],
            f.post_deposit_payload(k.POSTING_REFERENCE),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        posted,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_TIMELY,
        late_by_business_days=0,
    )
    assert_fields(
        validate_single(api.get_payroll_batch(batch["id"], plan.recordkeeper_headers)),
        status=k.BATCH_REMITTED,
    )

    settled = validate_single(
        api.settle_exit_transfer(transfer["id"], plan.provider_headers)
    )
    assert_fields(
        settled,
        status=k.TRANSFER_SETTLED,
        transferred_participant_count=13,
        gross_account_balance_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        admin_recovery_cents=16250,
        flat_exit_fee_cents=250000,
        deductions_applied_cents=266250,
        unrecovered_deduction_cents=0,
        transfer_amount_cents=8233750,
        settled_amount_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    assert_instant_equals(settled["settled_at"], k.POST_BLACKOUT_CLOCK, "settled_at")
    assert_fields(
        employer.refresh(api),
        adoption_status=k.EMPLOYER_EXITED,
        account_balance_cents=0,
    )


def test_repeating_an_action_that_already_succeeded_is_refused_three_ways(
    api: ApiClient, plan: PlanContext, employer: EmployerContext
):
    """
    Three unrelated families answer the same way when an action is replayed, and the
    batch guard is shown to be two-sided: one error id covers a deposit filed too
    early and a reconciliation filed too late.

    "Attempting to grant a registration that has already been granted is rejected
    with `ERR_PROVIDER_NOT_PENDING`, and this state check is evaluated before the
    money check that follows it."

    "the test must still be `SCHEDULED`, and a test already `PASSED`, `FAILED` or
    `CLOSED` is rejected with `ERR_TEST_INVALID_STATE`"

    "`exemption_applied` is true when every employer in the tested population holds
    an `APPROVED` election whose `nondiscrimination_track` is `SAFE_HARBOR_EXEMPT`;
    when it is true the test passes without computing any averages, and
    `hce_avg_deferral_pct`, `nhce_avg_deferral_pct` and `adp_limit_pct` are all left
    null."

    "The batch must be in `RECEIVED`; a batch already `VALIDATED` or `REMITTED` is
    rejected with `ERR_BATCH_INVALID_STATE`."

    "the named batch must be in `VALIDATED` status, and a batch still `RECEIVED` or
    already `REMITTED` is rejected with `ERR_BATCH_INVALID_STATE`"

    Design: Corner/errors/corner_repeat_actions_on_settled_rows_rejected
    """
    fixtures.set_clock(api, MID_AUGUST_CLOCK)
    delivered = fixtures.received_batch(api, employer)
    assert_fields(delivered, status=k.BATCH_RECEIVED)
    adp = fixtures.scheduled_test(
        api,
        plan,
        f.employer_level_test_payload(
            plan.plan_id, employer.employer_id, test_type=k.TEST_TYPE_ADP
        ),
    )

    validate_error(
        api.register_plan_provider(
            plan.provider_id,
            f.register_provider_payload(
                registration_effective_date=SECOND_REGISTRATION_EFFECTIVE_DATE
            ),
            regulator_headers(),
        ),
        ERR_PROVIDER_NOT_PENDING,
        expected_status=409,
    )
    assert_fields(
        validate_single(api.get_plan_provider(plan.provider_id, regulator_headers())),
        registration_status=k.PROVIDER_REGISTERED,
        registration_effective_date=k.REGISTRATION_EFFECTIVE_DATE,
    )

    ran = fixtures.run_test(api, plan, adp)
    assert_fields(ran, status=k.TEST_PASSED, exemption_applied=True)
    assert_null_fields(
        ran, "hce_avg_deferral_pct", "nhce_avg_deferral_pct", "adp_limit_pct"
    )
    assert_instant_equals(ran["run_at"], MID_AUGUST_CLOCK, "run_at")
    validate_error(
        api.run_compliance_test(adp["id"], plan.recordkeeper_headers),
        ERR_TEST_INVALID_STATE,
        expected_status=409,
    )
    unchanged = validate_single(
        api.get_compliance_test(adp["id"], plan.provider_headers)
    )
    assert_fields(unchanged, status=k.TEST_PASSED)
    assert_instant_equals(unchanged["run_at"], MID_AUGUST_CLOCK, "run_at")

    validate_error(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                delivered["id"], deposit_reference=EARLY_DEPOSIT_REFERENCE
            ),
            employer.headers,
        ),
        ERR_BATCH_INVALID_STATE,
        expected_status=409,
    )

    reconciled = validate_single(
        api.validate_payroll_batch(
            delivered["id"], f.validate_batch_payload(), plan.recordkeeper_headers
        )
    )
    assert_fields(reconciled, status=k.BATCH_VALIDATED)
    validate_error(
        api.validate_payroll_batch(
            delivered["id"],
            f.validate_batch_payload(SECOND_RECONCILIATION_NOTE),
            plan.recordkeeper_headers,
        ),
        ERR_BATCH_INVALID_STATE,
        expected_status=409,
    )
    assert_fields(
        validate_single(
            api.get_payroll_batch(delivered["id"], plan.recordkeeper_headers)
        ),
        status=k.BATCH_VALIDATED,
        reconciliation_note=k.RECONCILIATION_NOTE,
    )

    accepted = validate_created(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                delivered["id"], deposit_reference=ACCEPTED_DEPOSIT_REFERENCE
            ),
            employer.headers,
        )
    )
    assert_fields(
        accepted,
        deposit_status=k.DEPOSIT_PENDING,
        timeliness_status=k.TIMELINESS_UNDETERMINED,
        deposit_reference=ACCEPTED_DEPOSIT_REFERENCE,
        amount_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
