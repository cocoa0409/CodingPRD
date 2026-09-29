"""Remittance settlement, the timeliness verdict and the reversal compensation."""

from typing import Any, Dict, Tuple

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import (
    ERR_DEPOSIT_AMOUNT_MISMATCH,
    ERR_DEPOSIT_DATE_OUT_OF_RANGE,
    ERR_DEPOSIT_INVALID_STATE,
    ERR_DEPOSIT_NOT_REVERSIBLE,
)
from test_helpers.assertions import (
    assert_fields,
    assert_null_fields,
    assert_plan_control_invariants,
    validate_collection,
    validate_created,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from prd_bench_local_runner.testing import validate_error

DEPOSIT_WINDOW_CLOCK = "2026-08-14T09:00:00Z"
LATE_DELIVERY_CLOCK = "2026-08-20T09:00:00Z"
REPLACEMENT_DEPOSIT_DATE = "2026-08-14"

# The five plan-level money aggregates that a reversal has to restore exactly.
PLAN_LEDGER_FIELDS = [
    "total_validated_contributions_cents",
    "aggregate_receivable_cents",
    "total_assets_cents",
    "total_corrections_funded_cents",
    "contribution_control_delta_cents",
]

IRONMILL_LEGAL_NAME = "Ironmill Forge Company"
IRONMILL_EIN = "420000044"
IRONMILL_SIGNATORY = "T. Ironmill"

WIRE_RECALLED = "Wire recalled by the originating bank."
DUPLICATE_WIRE = "Duplicate wire identified during the daily trust reconciliation."


def _remitting_pair(
    api: ApiClient, plan: PlanContext
) -> Tuple[EmployerContext, Dict[str, Any], EmployerContext, Dict[str, Any]]:
    """Two active employers of the same plan, each with one VALIDATED batch."""
    palisade = fixtures.active_employer(api, plan)
    quarry = fixtures.second_active_employer(api, plan)
    palisade_batch = fixtures.validated_batch(api, palisade)
    quarry_batch = fixtures.validated_batch(
        api, quarry, payroll_provider_reference=k.QUARRY_PAYROLL_REFERENCE
    )
    return palisade, palisade_batch, quarry, quarry_batch


def _post(api: ApiClient, plan: PlanContext, deposit_id: str, reference: str) -> dict:
    """Post a deposit to the trust as the plan's recordkeeper."""
    return validate_single(
        api.post_remittance_deposit(
            deposit_id, f.post_deposit_payload(reference), plan.recordkeeper_headers
        )
    )


def test_the_seventh_business_day_is_timely_and_the_eighth_is_late(
    api: ApiClient, plan
):
    """
    The safe-harbour boundary is one business day wide, it lands across a weekend,
    and only the employer that crosses it is suspended.

    "`business_days_elapsed` is the number of business days strictly after the
    batch's `withholding_date` through the `deposit_date` inclusive — the
    withholding date itself never counts and the deposit date counts whenever it
    is a business day."

    "The compliance dimension then advances from `UNDETERMINED` to `TIMELY` when
    the `deposit_date` is on or before the batch's `deposit_due_date`, and from
    `UNDETERMINED` to `LATE` when it is strictly after it."

    "At the third level the plan document's `suspended_employer_count` is
    recomputed and `compliance_posture` follows from it — one suspended employer
    makes the plan `RESTRICTED`, a second makes it `FROZEN` — along with
    `active_employer_count`."

    Design: Difficulty/boundary_precision_check/deposit_timeliness_seventh_versus_eighth_business_day
    """
    palisade, palisade_batch, quarry, quarry_batch = _remitting_pair(api, plan)
    assert_fields(
        palisade_batch,
        deposit_rule=k.DEPOSIT_RULE_SMALL_PLAN,
        deposit_due_date=k.DEPOSIT_DUE_DATE,
    )
    assert_fields(
        quarry_batch,
        deposit_rule=k.DEPOSIT_RULE_SMALL_PLAN,
        deposit_due_date=k.DEPOSIT_DUE_DATE,
    )

    fixtures.set_clock(api, DEPOSIT_WINDOW_CLOCK)
    on_time = fixtures.pending_deposit(
        api,
        palisade,
        palisade_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_SEVENTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-P812",
    )
    one_day_late = fixtures.pending_deposit(
        api,
        quarry,
        quarry_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-Q813",
    )

    timely = _post(api, plan, on_time["id"], "NG-POST-P001")
    late = _post(api, plan, one_day_late["id"], "NG-POST-Q001")

    assert_fields(
        timely,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_TIMELY,
        business_days_elapsed=7,
        late_by_business_days=0,
    )
    assert_fields(
        late,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_LATE,
        business_days_elapsed=8,
        late_by_business_days=1,
    )

    assert_fields(
        palisade.refresh(api),
        adoption_status=k.EMPLOYER_ACTIVE,
        contribution_hold=False,
        open_correction_count=0,
    )
    assert_fields(
        quarry.refresh(api),
        adoption_status=k.EMPLOYER_SUSPENDED,
        contribution_hold=True,
        open_correction_count=1,
    )
    assert_fields(
        plan.refresh(api),
        active_employer_count=1,
        suspended_employer_count=1,
        compliance_posture=k.POSTURE_RESTRICTED,
    )
    for batch_id in (palisade_batch["id"], quarry_batch["id"]):
        assert_fields(
            validate_single(api.get_payroll_batch(batch_id, plan.provider_headers)),
            status=k.BATCH_REMITTED,
        )


def test_the_settlement_and_compliance_dimensions_move_independently(
    api: ApiClient, plan
):
    """
    One row carries two state machines: the compliance dimension advances twice
    while the settlement dimension never leaves POSTED, and the middle state
    withdraws the reversal edge.

    "The two dimensions move on different triggers and are driven by different
    actors, so a deposit can legitimately be `POSTED` and `LATE`, `POSTED` and
    `CORRECTED`, or `REVERSED` and `UNDETERMINED`."

    "The deposit must be `POSTED` — otherwise `ERR_DEPOSIT_INVALID_STATE` — and
    its `timeliness_status` must be `TIMELY`, `LATE` or `UNDETERMINED`; once a
    correction has been computed or funded the posting is frozen and reversal is
    rejected with `ERR_DEPOSIT_NOT_REVERSIBLE`."

    "On success `timeliness_status` advances from `CORRECTION_COMPUTED` to
    `CORRECTED`, `funded_at` is stamped from the logical clock and the reference is
    stored; `restoration_cents` is added to the employer's
    `account_balance_cents`; the employer's `open_correction_count` is decremented
    and, when it reaches zero — that is, when no other deposit of that employer is
    `POSTED` with `timeliness_status` `LATE` or `CORRECTION_COMPUTED` — the
    employer returns from `SUSPENDED` to `ACTIVE` with `contribution_hold` set to
    false; and the plan document's `total_corrections_funded_cents`,
    `total_assets_cents`, `suspended_employer_count`, `compliance_posture` and
    `contribution_control_delta_cents` are all recomputed."

    Design: Difficulty/non_linear_state_machine/remittance_deposit_parallel_status_dimensions_diverge
    """
    emp_ctx = fixtures.active_employer(api, plan)
    batch = fixtures.validated_batch(api, emp_ctx)

    fixtures.set_clock(api, DEPOSIT_WINDOW_CLOCK)
    deposit = fixtures.pending_deposit(
        api,
        emp_ctx,
        batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-0813",
    )
    posted = _post(api, plan, deposit["id"], "NG-POST-0001")
    assert_fields(
        posted,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_LATE,
        business_days_elapsed=8,
        late_by_business_days=1,
    )
    assert_fields(
        validate_single(api.get_payroll_batch(batch["id"], emp_ctx.headers)),
        status=k.BATCH_REMITTED,
    )
    assert_fields(emp_ctx.refresh(api), adoption_status=k.EMPLOYER_SUSPENDED)

    computed = validate_single(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(
                k.CORRECTION_IRS_6621_UNDERPAYMENT, k.RECOVERY_DATE
            ),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        computed,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
        lost_earnings_cents=2096,
        restoration_cents=2096,
        excise_tax_cents=0,
    )

    validate_error(
        api.reverse_remittance_deposit(
            deposit["id"],
            f.reverse_deposit_payload(
                "Recordkeeper attempts to unwind a deposit already in correction."
            ),
            plan.recordkeeper_headers,
        ),
        ERR_DEPOSIT_NOT_REVERSIBLE,
        expected_status=409,
    )
    assert_fields(
        validate_single(api.get_remittance_deposit(deposit["id"], emp_ctx.headers)),
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
    )

    funded = validate_single(
        api.fund_deposit_correction(
            deposit["id"], emp_ctx.headers, f.fund_correction_payload()
        )
    )
    assert_fields(
        funded,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_CORRECTED,
    )
    assert_fields(
        emp_ctx.refresh(api),
        adoption_status=k.EMPLOYER_ACTIVE,
        open_correction_count=0,
        contribution_hold=False,
        account_balance_cents=8502096,
    )
    assert_fields(
        plan.refresh(api),
        total_corrections_funded_cents=2096,
        compliance_posture=k.POSTURE_OPEN,
        contribution_control_delta_cents=0,
    )


def test_reversing_both_postings_returns_every_plan_total_to_its_baseline(
    api: ApiClient, plan
):
    """
    Posting moves the same cents through four plan aggregates at once and reversal
    unwinds all four, so the control delta is zero at every step and the restored
    read matches the baseline field for field while the version still climbs.

    "From these, `contribution_control_delta_cents` is obtained by adding
    `total_assets_cents`, `aggregate_receivable_cents` and `transferred_out_cents`,
    then subtracting `total_corrections_funded_cents` and subtracting
    `total_validated_contributions_cents`."

    "The batch reverts from `REMITTED` to `VALIDATED`, the employer's
    `contribution_receivable_cents` is restored and its `account_balance_cents` is
    reduced by the reversed amount, and every plan control total is recomputed so
    that `contribution_control_delta_cents` returns to exactly zero."

    "If the reversed deposit had been `LATE`, the suspension it caused is unwound
    too: the employer's `open_correction_count` is decremented and, when it reaches
    zero, the employer returns from `SUSPENDED` to `ACTIVE` with
    `contribution_hold` cleared, after which the plan's `suspended_employer_count`
    and `compliance_posture` are recomputed."

    Design: Difficulty/compensating_invariant/deposit_reversal_restores_contribution_control_delta_to_zero
    """
    palisade, palisade_batch, quarry, quarry_batch = _remitting_pair(api, plan)

    baseline = plan.refresh(api)
    assert_fields(
        baseline,
        total_validated_contributions_cents=17000000,
        aggregate_receivable_cents=17000000,
        total_assets_cents=0,
        total_corrections_funded_cents=0,
        contribution_control_delta_cents=0,
    )
    assert_plan_control_invariants(baseline)
    baseline_ledger = {
        field: baseline[field] for field in PLAN_LEDGER_FIELDS
    }
    baseline_version = baseline["version"]

    fixtures.set_clock(api, DEPOSIT_WINDOW_CLOCK)
    deposit_p = fixtures.pending_deposit(
        api,
        palisade,
        palisade_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_SEVENTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-P812",
    )
    deposit_q = fixtures.pending_deposit(
        api,
        quarry,
        quarry_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-Q813",
    )

    posted_p = _post(api, plan, deposit_p["id"], "NG-POST-P812")
    assert_fields(
        posted_p,
        timeliness_status=k.TIMELINESS_TIMELY,
        business_days_elapsed=7,
    )
    assert_fields(
        plan.refresh(api),
        aggregate_receivable_cents=8500000,
        total_assets_cents=8500000,
        contribution_control_delta_cents=0,
    )

    posted_q = _post(api, plan, deposit_q["id"], "NG-POST-Q813")
    assert_fields(
        posted_q,
        timeliness_status=k.TIMELINESS_LATE,
        business_days_elapsed=8,
        late_by_business_days=1,
    )
    assert_fields(
        plan.refresh(api),
        aggregate_receivable_cents=0,
        total_assets_cents=17000000,
        contribution_control_delta_cents=0,
        suspended_employer_count=1,
        compliance_posture=k.POSTURE_RESTRICTED,
    )

    reversed_q = validate_single(
        api.reverse_remittance_deposit(
            deposit_q["id"],
            f.reverse_deposit_payload(WIRE_RECALLED),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        reversed_q,
        deposit_status=k.DEPOSIT_REVERSED,
        timeliness_status=k.TIMELINESS_UNDETERMINED,
        reversal_reason=WIRE_RECALLED,
    )
    assert_null_fields(reversed_q, "business_days_elapsed", "late_by_business_days")
    assert_fields(
        validate_single(
            api.get_payroll_batch(quarry_batch["id"], plan.recordkeeper_headers)
        ),
        status=k.BATCH_VALIDATED,
    )
    assert_fields(
        quarry.refresh(api),
        adoption_status=k.EMPLOYER_ACTIVE,
        account_balance_cents=0,
        contribution_receivable_cents=8500000,
        open_correction_count=0,
        contribution_hold=False,
    )
    assert_fields(plan.refresh(api), compliance_posture=k.POSTURE_OPEN)

    validate_single(
        api.reverse_remittance_deposit(
            deposit_p["id"],
            f.reverse_deposit_payload(DUPLICATE_WIRE),
            plan.recordkeeper_headers,
        )
    )
    restored = plan.refresh(api)
    assert_fields(restored, **baseline_ledger)
    assert_plan_control_invariants(restored)
    assert restored["version"] > baseline_version, (
        "the ledger is restored but the version counter is never rewound"
    )
    assert_fields(
        palisade.refresh(api),
        account_balance_cents=0,
        contribution_receivable_cents=8500000,
    )

    replacement = fixtures.pending_deposit(
        api,
        quarry,
        quarry_batch,
        clock=None,
        deposit_date=REPLACEMENT_DEPOSIT_DATE,
        deposit_reference="TRUST-WIRE-Q814",
    )
    posted_again = _post(api, plan, replacement["id"], "NG-POST-Q814")
    assert_fields(
        posted_again,
        timeliness_status=k.TIMELINESS_LATE,
        business_days_elapsed=9,
        late_by_business_days=2,
    )
    assert_fields(
        plan.refresh(api),
        aggregate_receivable_cents=8500000,
        total_assets_cents=8500000,
        contribution_control_delta_cents=0,
    )

    computed = validate_single(
        api.compute_deposit_correction(
            replacement["id"],
            f.compute_correction_payload(
                k.CORRECTION_IRS_6621_UNDERPAYMENT, REPLACEMENT_DEPOSIT_DATE
            ),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        computed,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
        restoration_cents=4192,
    )
    assert_fields(
        plan.refresh(api),
        total_corrections_funded_cents=0,
        contribution_control_delta_cents=0,
    )

    validate_error(
        api.reverse_remittance_deposit(
            replacement["id"],
            f.reverse_deposit_payload(
                "Recordkeeper attempts to unwind a deposit already in correction."
            ),
            plan.recordkeeper_headers,
        ),
        ERR_DEPOSIT_NOT_REVERSIBLE,
        expected_status=409,
    )


def test_a_large_employer_falls_under_the_fifteenth_business_day_rule(
    api: ApiClient, plan
):
    """
    The non-safe-harbour branch of the deadline is selected by the employer's own
    size flag and lands in the month after withholding, around a federal holiday.

    "`is_small_plan` is true when the employer's `participant_count` is below 100,
    which is what selects the seven-business-day deposit safe harbour for that
    employer's payroll, and `employer_audit_required` is true when
    `participant_count` is 100 or more, meaning the employer must supply audited
    employer-level financial data for the plan's return."

    "Under the general rule the due date is the fifteenth business day of the
    calendar month immediately following the month of the `withholding_date`; for a
    `withholding_date` of 2026-06-15 that lands on 2026-07-22."

    Design: Corner/calculations/corner_deposit_due_date_general_fifteenth_business_day_rule
    """
    ironmill = fixtures.active_employer(
        api,
        plan,
        payload=f.adopting_employer_payload(
            plan.plan_id,
            legal_name=IRONMILL_LEGAL_NAME,
            ein=IRONMILL_EIN,
            participant_count=120,
            hce_count=20,
            nhce_count=100,
            benefiting_hce_count=20,
            benefiting_nhce_count=95,
        ),
        signatory_name=IRONMILL_SIGNATORY,
    )

    batch = validate_created(
        api.create_payroll_batch(
            f.payroll_batch_payload(
                ironmill.employer_id,
                pay_period_start="2026-06-01",
                pay_period_end="2026-06-16",
                pay_date="2026-06-15",
                withholding_date="2026-06-15",
                payroll_provider_reference="PR-IRON-06A",
                total_loan_repayment_cents=0,
                participant_line_count=120,
            ),
            ironmill.headers,
        )
    )
    assert_fields(
        batch,
        deposit_rule=k.DEPOSIT_RULE_GENERAL,
        deposit_due_date="2026-07-22",
        batch_total_cents=8250000,
        expected_match_cents=k.CANONICAL_BASIC_MATCH_CENTS,
    )
    assert_fields(
        ironmill.refresh(api),
        is_small_plan=False,
        employer_audit_required=True,
    )


def test_the_deposit_window_is_closed_at_both_ends_and_answers_before_the_amount(
    api: ApiClient, plan
):
    """
    A partial remittance is refused outright, both ends of the deposit window are
    inclusive, and a request that breaks the window and the amount together reports
    the temporal reason.

    "the `deposit_date` must not be later than the logical-clock calendar date and
    must be on or after the batch's `withholding_date`, failing which the request is
    rejected with `ERR_DEPOSIT_DATE_OUT_OF_RANGE`; and `amount_cents` must equal the
    batch's `batch_total_cents` exactly, since partial remittances are not accepted
    and a mismatch is rejected with `ERR_DEPOSIT_AMOUNT_MISMATCH`."

    "Money and quota checks are deliberately last, so that a request which is
    structurally or procedurally wrong never reports a financial reason."

    Design: Corner/validations/corner_deposit_amount_must_match_and_date_must_be_in_window
    """
    emp_ctx = fixtures.active_employer(api, plan)
    batch = fixtures.validated_batch(api, emp_ctx)
    assert_fields(
        batch,
        withholding_date=k.WITHHOLDING_DATE,
        batch_total_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    fixtures.set_clock(api, DEPOSIT_WINDOW_CLOCK)

    validate_error(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                batch["id"],
                amount_cents=4000000,
                deposit_reference="TR-PARTIAL-1",
            ),
            emp_ctx.headers,
        ),
        ERR_DEPOSIT_AMOUNT_MISMATCH,
        expected_status=409,
    )
    validate_error(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                batch["id"],
                deposit_date="2026-08-02",
                deposit_reference="TR-EARLY-1",
            ),
            emp_ctx.headers,
        ),
        ERR_DEPOSIT_DATE_OUT_OF_RANGE,
        expected_status=422,
    )
    validate_error(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                batch["id"],
                deposit_date="2026-08-15",
                deposit_reference="TR-FUTURE-1",
            ),
            emp_ctx.headers,
        ),
        ERR_DEPOSIT_DATE_OUT_OF_RANGE,
        expected_status=422,
    )
    validate_error(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                batch["id"],
                deposit_date="2026-08-20",
                amount_cents=4000000,
                deposit_reference="TR-BOTH-WRONG-1",
            ),
            emp_ctx.headers,
        ),
        ERR_DEPOSIT_DATE_OUT_OF_RANGE,
        expected_status=422,
    )

    on_the_lower_bound = validate_created(
        api.create_remittance_deposit(
            f.remittance_deposit_payload(
                batch["id"],
                deposit_date=k.WITHHOLDING_DATE,
                deposit_reference="TR-EXACT-LOW",
            ),
            emp_ctx.headers,
        )
    )
    assert_fields(
        on_the_lower_bound,
        deposit_status=k.DEPOSIT_PENDING,
        timeliness_status=k.TIMELINESS_UNDETERMINED,
    )

    validate_collection(
        api.list_batch_remittance_deposits(
            batch["id"], plan.recordkeeper_headers, limit=10, offset=0
        ),
        expected_total=1,
        expected_len=1,
    )
    assert_fields(
        validate_single(
            api.get_payroll_batch(batch["id"], plan.recordkeeper_headers)
        ),
        status=k.BATCH_VALIDATED,
    )


def test_a_reversed_deposit_is_dead_on_both_dimensions(api: ApiClient, plan):
    """
    REVERSED is terminal on the settlement dimension even though the timeliness
    dimension was rewound to UNDETERMINED, so all three recordkeeper actions are
    refused while the freed batch stays re-remittable.

    "`deposit_status` is the settlement dimension, advanced only by the
    recordkeeper, and runs `PENDING → POSTED → REVERSED` with `REVERSED` terminal."

    "the deposit must be in `PENDING` — a deposit already `POSTED` or `REVERSED` is
    rejected with `ERR_DEPOSIT_INVALID_STATE`"

    "On success `deposit_status` moves from `POSTED` to `REVERSED` while
    `timeliness_status` returns from `TIMELY` or from `LATE` to `UNDETERMINED`, and
    `business_days_elapsed` and `late_by_business_days` are cleared."

    Design: Corner/state_machines/corner_reversed_deposit_cannot_be_posted_or_reversed_again
    """
    emp_ctx = fixtures.active_employer(api, plan)
    batch = fixtures.validated_batch(api, emp_ctx)
    deposit = fixtures.timely_deposit(api, emp_ctx, batch)
    original_posted_at = deposit["posted_at"]
    original_reference = deposit["posting_reference"]
    validate_single(
        api.reverse_remittance_deposit(
            deposit["id"],
            f.reverse_deposit_payload(WIRE_RECALLED),
            plan.recordkeeper_headers,
        )
    )

    validate_error(
        api.post_remittance_deposit(
            deposit["id"],
            f.post_deposit_payload("TRUST-POST-0001-RETRY"),
            plan.recordkeeper_headers,
        ),
        ERR_DEPOSIT_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.reverse_remittance_deposit(
            deposit["id"],
            f.reverse_deposit_payload("Second recall attempt."),
            plan.recordkeeper_headers,
        ),
        ERR_DEPOSIT_INVALID_STATE,
        expected_status=409,
    )
    validate_error(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(
                k.CORRECTION_IRS_6621_UNDERPAYMENT, REPLACEMENT_DEPOSIT_DATE
            ),
            plan.recordkeeper_headers,
        ),
        ERR_DEPOSIT_INVALID_STATE,
        expected_status=409,
    )

    read_back = validate_single(
        api.get_remittance_deposit(deposit["id"], plan.recordkeeper_headers)
    )
    assert_fields(
        read_back,
        deposit_status=k.DEPOSIT_REVERSED,
        timeliness_status=k.TIMELINESS_UNDETERMINED,
        posted_at=original_posted_at,
        posting_reference=original_reference,
        reversal_reason=WIRE_RECALLED,
    )
    assert_fields(
        validate_single(
            api.get_payroll_batch(batch["id"], plan.recordkeeper_headers)
        ),
        status=k.BATCH_VALIDATED,
    )
    assert_fields(
        emp_ctx.refresh(api),
        account_balance_cents=0,
        contribution_receivable_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    assert_plan_control_invariants(plan.refresh(api))


def test_plan_totals_see_validated_batches_and_ignore_delivered_ones(
    api: ApiClient, plan
):
    """
    Two batches of one employer sit in different statuses and the aggregate filters
    are exact, so the merely delivered one is invisible to every plan total even
    though its money is on the row.

    "On the money side, `total_validated_contributions_cents` is the sum of
    `batch_total_cents` over the plan's payroll batches in either `VALIDATED` or
    `REMITTED` status; `aggregate_receivable_cents` is the sum of
    `batch_total_cents` over the batches still in `VALIDATED` status"

    "The interval also may not overlap the interval of any other payroll batch of
    the same employer, and because the interval is half-open, exact adjacency is
    permitted: a batch ending on 2026-06-15 and the next starting on 2026-06-15 do
    not overlap, whereas any genuine overlap is rejected with
    `ERR_PAY_PERIOD_OVERLAP`."

    "A new batch opens in `status` `RECEIVED`, with `validated_at` and
    `reconciliation_note` null."

    Design: Corner/calculations/corner_plan_control_totals_exclude_received_batches
    """
    fixtures.set_clock(api, LATE_DELIVERY_CLOCK)
    emp_ctx = fixtures.active_employer(api, plan)

    first = fixtures.received_batch(api, emp_ctx)
    second = fixtures.received_batch(
        api,
        emp_ctx,
        pay_period_start=k.PAY_PERIOD_END,
        pay_period_end="2026-08-15",
        pay_date="2026-08-17",
        withholding_date="2026-08-17",
        payroll_provider_reference="PAL-2026-16",
    )
    assert_fields(first, batch_total_cents=k.CANONICAL_BATCH_TOTAL_CENTS)
    assert_fields(second, batch_total_cents=k.CANONICAL_BATCH_TOTAL_CENTS)
    assert_fields(
        first, pay_period_start=k.PAY_PERIOD_START, pay_period_end=k.PAY_PERIOD_END
    )
    assert_fields(
        second, pay_period_start=k.PAY_PERIOD_END, pay_period_end="2026-08-15"
    )

    validated = validate_single(
        api.validate_payroll_batch(
            first["id"], f.validate_batch_payload(), plan.recordkeeper_headers
        )
    )
    assert_fields(validated, status=k.BATCH_VALIDATED)

    read_back_second = validate_single(
        api.get_payroll_batch(second["id"], plan.recordkeeper_headers)
    )
    assert_fields(read_back_second, status=k.BATCH_RECEIVED)
    assert_null_fields(read_back_second, "validated_at", "reconciliation_note")

    assert_fields(
        plan.refresh(api),
        total_validated_contributions_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        aggregate_receivable_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        total_assets_cents=0,
        contribution_control_delta_cents=0,
    )
    assert_fields(
        emp_ctx.refresh(api),
        contribution_receivable_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
        account_balance_cents=0,
    )
