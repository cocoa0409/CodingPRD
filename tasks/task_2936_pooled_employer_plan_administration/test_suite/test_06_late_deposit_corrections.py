"""The two lost-earnings variants, the excise-tax threshold and the late cascade."""

from typing import Any, Dict, Tuple

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures
from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ERR_FORM_5330_REFERENCE_REQUIRED
from test_helpers.assertions import (
    assert_fields,
    assert_null_fields,
    assert_plan_control_invariants,
    validate_single,
)
from test_helpers.fixtures import EmployerContext, PlanContext
from prd_bench_local_runner.testing import validate_error

# A June payroll whose deposit slips a month: withheld 2026-06-15, therefore due
# on the seventh business day 2026-06-25, actually deposited 2026-07-20.
JUNE_PERIOD_START = "2026-06-01"
JUNE_PERIOD_END = "2026-06-16"
JUNE_PAY_DATE = "2026-06-15"
JUNE_WITHHOLDING_DATE = "2026-06-15"
JUNE_PAYROLL_REFERENCE = "PR-SABLE-06A"
JUNE_DEPOSIT_DUE_DATE = "2026-06-25"
DELINQUENT_DEPOSIT_DATE = "2026-07-20"
DELINQUENT_DEPOSIT_REFERENCE = "TRUST-WIRE-0720"

# One day after the delinquent deposit, and a month later once the recovery date
# the VFCP correction reaches for has itself passed.
POSTING_CLOCK = "2026-07-21T09:00:00Z"
CORRECTION_CLOCK = "2026-09-01T09:00:00Z"
VFCP_RECOVERY_DATE = "2026-08-31"

EXCISE_CLOCK = "2026-08-14T09:00:00Z"
FORM_5330_TAXABLE_REFERENCE = "5330-2026-000817"


def _delinquent_deposit(
    api: ApiClient, plan: PlanContext, clock: str
) -> Tuple[EmployerContext, Dict[str, Any], Dict[str, Any]]:
    """
    A small-plan employer whose June contributions reached the trust on 2026-07-20.

    The batch is delivered and reconciled, then the remittance is recorded and
    posted, which is what produces the `LATE` verdict the correction works from.
    """
    emp_ctx = fixtures.active_employer(api, plan)
    batch = fixtures.validated_batch(
        api,
        emp_ctx,
        pay_period_start=JUNE_PERIOD_START,
        pay_period_end=JUNE_PERIOD_END,
        pay_date=JUNE_PAY_DATE,
        withholding_date=JUNE_WITHHOLDING_DATE,
        payroll_provider_reference=JUNE_PAYROLL_REFERENCE,
    )
    fixtures.set_clock(api, clock)
    deposit = fixtures.pending_deposit(
        api,
        emp_ctx,
        batch,
        clock=None,
        deposit_date=DELINQUENT_DEPOSIT_DATE,
        deposit_reference=DELINQUENT_DEPOSIT_REFERENCE,
    )
    return emp_ctx, batch, deposit


def _post(api: ApiClient, plan: PlanContext, deposit_id: str, reference: str) -> dict:
    """Post a deposit to the trust as the plan's recordkeeper."""
    return validate_single(
        api.post_remittance_deposit(
            deposit_id, f.post_deposit_payload(reference), plan.recordkeeper_headers
        )
    )


def test_the_vfcp_variant_segments_the_interest_period_at_the_quarter_boundary(
    api: ApiClient, plan
):
    """
    The programme variant runs interest through the recovery date and rounds each
    calendar quarter on its own rate, so the answer is not the one a single
    unsegmented computation over the same period would give.

    "The interest period runs from the day after the `deposit_due_date` through the
    `recovery_date`, inclusive at both ends."

    "For each segment the server counts the dates the segment contains, multiplies
    the principal by that quarter's own annual rate expressed as a fraction of one
    hundred, multiplies by the segment's day count, divides by 365, and rounds half
    up to whole cents."

    "For a principal of 8500000 cents, a `deposit_due_date` of 2026-06-25, a
    `deposit_date` of 2026-07-20 and a `recovery_date` of 2026-08-31,
    `VFCP_RECOVERY_DATE` yields 139260 while `IRS_6621_UNDERPAYMENT` yields 52397."

    "otherwise `excise_tax_cents` is fifteen percent of `restoration_cents`, rounded
    half up to whole cents."

    Design: Difficulty/dual_variant_calc/lost_earnings_vfcp_recovery_date_segments_by_quarter
    """
    emp_ctx, batch, deposit = _delinquent_deposit(api, plan, CORRECTION_CLOCK)
    assert_fields(
        batch,
        deposit_rule=k.DEPOSIT_RULE_SMALL_PLAN,
        deposit_due_date=JUNE_DEPOSIT_DUE_DATE,
        batch_total_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )

    posted = _post(api, plan, deposit["id"], "NG-POST-0720")
    assert_fields(
        posted,
        timeliness_status=k.TIMELINESS_LATE,
        business_days_elapsed=23,
        late_by_business_days=16,
    )

    computed = validate_single(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(
                k.CORRECTION_VFCP_RECOVERY_DATE, VFCP_RECOVERY_DATE
            ),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        computed,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
        business_days_elapsed=23,
        late_by_business_days=16,
        correction_method=k.CORRECTION_VFCP_RECOVERY_DATE,
        recovery_date=VFCP_RECOVERY_DATE,
        lost_earnings_cents=139260,
        restoration_cents=139260,
        excise_tax_cents=20889,
    )
    assert emp_ctx.refresh(api)["adoption_status"] == k.EMPLOYER_SUSPENDED


def test_the_self_correction_variant_stops_at_the_deposit_date_on_one_rate(
    api: ApiClient, plan
):
    """
    The same delinquent deposit under the other method counts plain calendar days
    to the deposit date at the single quarter rate that contains it, and the stored
    recovery date never enters the arithmetic.

    "The period ends at the `deposit_date`, and the number of days is the plain
    calendar-day difference between the `deposit_date` and the `deposit_due_date`."

    "A single rate applies to the whole period — the rate of the calendar quarter
    that contains the `deposit_date` — with no segmentation at all."

    "The `recovery_date` is stored but never enters the arithmetic under this
    variant."

    "For a principal of 8500000 cents, a `deposit_due_date` of 2026-06-25, a
    `deposit_date` of 2026-07-20 and a `recovery_date` of 2026-08-31,
    `VFCP_RECOVERY_DATE` yields 139260 while `IRS_6621_UNDERPAYMENT` yields 52397."

    Design: Difficulty/dual_variant_calc/lost_earnings_irs_6621_single_rate_to_deposit_date
    """
    _, _, deposit = _delinquent_deposit(api, plan, CORRECTION_CLOCK)
    _post(api, plan, deposit["id"], "NG-POST-0720")

    computed = validate_single(
        api.compute_deposit_correction(
            deposit["id"],
            f.compute_correction_payload(
                k.CORRECTION_IRS_6621_UNDERPAYMENT, VFCP_RECOVERY_DATE
            ),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        computed,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
        correction_method=k.CORRECTION_IRS_6621_UNDERPAYMENT,
        recovery_date=VFCP_RECOVERY_DATE,
        lost_earnings_cents=52397,
        restoration_cents=52397,
        excise_tax_cents=7860,
    )
    assert computed["lost_earnings_cents"] != 139260, (
        "the recovery date is stored but unused, so this must not be the "
        "programme figure for the same deposit"
    )


def test_the_excise_threshold_reads_the_restoration_amount_not_lost_earnings(
    api: ApiClient, plan
):
    """
    Two identical corrections differ by one cent of reported investment return, and
    that cent alone decides both the excise tax and whether funding needs an excise
    return reference.

    "`restoration_cents` — the amount the employer must actually restore — is the
    greater of `lost_earnings_cents` and the supplied
    `actual_investment_return_cents`."

    "The de-minimis test is strictly less-than, so a `restoration_cents` of exactly
    10000 is taxable at 1500 while 9999 attracts no tax at all."

    "The payload may carry `form_5330_reference`, the excise tax return reference; it
    is required whenever the deposit's `excise_tax_cents` is greater than zero, and
    its absence in that case is rejected with `ERR_FORM_5330_REFERENCE_REQUIRED`."

    Design: Difficulty/boundary_precision_check/excise_tax_de_minimis_at_ten_thousand_cents
    """
    palisade = fixtures.active_employer(api, plan)
    quarry = fixtures.second_active_employer(api, plan)
    palisade_batch = fixtures.validated_batch(api, palisade)
    quarry_batch = fixtures.validated_batch(
        api, quarry, payroll_provider_reference=k.QUARRY_PAYROLL_REFERENCE
    )

    fixtures.set_clock(api, EXCISE_CLOCK)
    at_the_threshold = fixtures.pending_deposit(
        api,
        palisade,
        palisade_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-P813",
    )
    one_cent_below = fixtures.pending_deposit(
        api,
        quarry,
        quarry_batch,
        clock=None,
        deposit_date=k.DEPOSIT_DATE_EIGHTH_BUSINESS_DAY,
        deposit_reference="TRUST-WIRE-Q813",
    )
    for deposit, reference in (
        (at_the_threshold, "NG-POST-P813"),
        (one_cent_below, "NG-POST-Q813"),
    ):
        assert_fields(
            _post(api, plan, deposit["id"], reference),
            timeliness_status=k.TIMELINESS_LATE,
            late_by_business_days=1,
        )

    taxable = validate_single(
        api.compute_deposit_correction(
            at_the_threshold["id"],
            f.compute_correction_payload(
                k.CORRECTION_IRS_6621_UNDERPAYMENT,
                k.RECOVERY_DATE,
                actual_investment_return_cents=k.EXCISE_TAX_DE_MINIMIS_CENTS,
            ),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        taxable,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
        lost_earnings_cents=2096,
        restoration_cents=10000,
        excise_tax_cents=1500,
    )

    de_minimis = validate_single(
        api.compute_deposit_correction(
            one_cent_below["id"],
            f.compute_correction_payload(
                k.CORRECTION_IRS_6621_UNDERPAYMENT,
                k.RECOVERY_DATE,
                actual_investment_return_cents=k.EXCISE_TAX_DE_MINIMIS_CENTS - 1,
            ),
            plan.recordkeeper_headers,
        )
    )
    assert_fields(
        de_minimis,
        timeliness_status=k.TIMELINESS_CORRECTION_COMPUTED,
        lost_earnings_cents=2096,
        restoration_cents=9999,
        excise_tax_cents=0,
    )

    funded = validate_single(
        api.fund_deposit_correction(
            one_cent_below["id"], quarry.headers, f.fund_correction_payload()
        )
    )
    assert_fields(funded, timeliness_status=k.TIMELINESS_CORRECTED)
    assert_null_fields(funded, "form_5330_reference")
    assert_fields(
        quarry.refresh(api),
        account_balance_cents=8509999,
        adoption_status=k.EMPLOYER_ACTIVE,
    )
    assert_fields(plan.refresh(api), total_corrections_funded_cents=9999)

    validate_error(
        api.fund_deposit_correction(
            at_the_threshold["id"], palisade.headers, f.fund_correction_payload()
        ),
        ERR_FORM_5330_REFERENCE_REQUIRED,
        expected_status=422,
    )
    with_reference = validate_single(
        api.fund_deposit_correction(
            at_the_threshold["id"],
            palisade.headers,
            f.fund_correction_payload(FORM_5330_TAXABLE_REFERENCE),
        )
    )
    assert_fields(
        with_reference,
        timeliness_status=k.TIMELINESS_CORRECTED,
        form_5330_reference=FORM_5330_TAXABLE_REFERENCE,
    )
    assert_fields(palisade.refresh(api), account_balance_cents=8510000)


def test_one_posting_suspends_the_employer_and_unwinds_the_annual_return(
    api: ApiClient, plan
):
    """
    A single posting reaches four levels deep, and the last two land on entities the
    request never names: the plan document and a return that had already cleared its
    only branch.

    "At the second level the employer is suspended: its `adoption_status` moves from
    `ACTIVE` to `SUSPENDED`, its `contribution_hold` is set to true, its
    `open_correction_count` is incremented, and its `version` is incremented by one."

    "At the fourth level the plan's annual return is touched: every plan filing that
    is not yet `FILED` has the late deposit's `amount_cents` added to its
    `late_deposit_schedule_h_line_cents`, the delinquent-participant-contributions
    line; and a filing sitting in `READY_TO_FILE` has its employer-data branch
    revoked, meaning `employer_data_certified_at`, `certified_by_user_id` and
    `certified_employer_count` are all cleared and its `version` is incremented."

    "a filing with `audit_required` false falls all the way back to `PREPARED`, since
    the employer-data branch was the only branch it had"

    Design: Difficulty/transitive_cascade/late_deposit_suspends_employer_freezes_plan_and_reverts_filing
    """
    emp_ctx, batch, deposit = _delinquent_deposit(api, plan, POSTING_CLOCK)
    filing = fixtures.certified_filing(api, plan)
    assert_fields(
        filing,
        filing_status=k.FILING_READY_TO_FILE,
        late_deposit_schedule_h_line_cents=0,
        audit_required=False,
    )

    posted = _post(api, plan, deposit["id"], "NG-POST-0002")
    assert_fields(
        posted,
        deposit_status=k.DEPOSIT_POSTED,
        timeliness_status=k.TIMELINESS_LATE,
        business_days_elapsed=23,
        late_by_business_days=16,
    )
    assert_fields(
        validate_single(
            api.get_payroll_batch(batch["id"], plan.recordkeeper_headers)
        ),
        status=k.BATCH_REMITTED,
    )
    assert_fields(
        emp_ctx.refresh(api),
        adoption_status=k.EMPLOYER_SUSPENDED,
        contribution_hold=True,
        open_correction_count=1,
    )

    plan_document = plan.refresh(api)
    assert_fields(
        plan_document,
        suspended_employer_count=1,
        active_employer_count=0,
        compliance_posture=k.POSTURE_RESTRICTED,
        participant_count=13,
        audit_required=False,
    )
    assert_plan_control_invariants(plan_document)

    reverted = validate_single(
        api.get_plan_filing(filing["id"], plan.provider_headers)
    )
    assert_fields(
        reverted,
        filing_status=k.FILING_PREPARED,
        late_deposit_schedule_h_line_cents=k.CANONICAL_BATCH_TOTAL_CENTS,
    )
    assert_null_fields(
        reverted,
        "employer_data_certified_at",
        "certified_by_user_id",
        "certified_employer_count",
    )
