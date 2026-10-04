"""Composite setup helpers for the retirement-benefit domain.

The runner restarts the API server before every test, so each helper builds
its preconditions from scratch against an empty database whose logical clock
reads the startup default 2026-09-01T00:00:00Z (PRD §2.4) until a helper
explicitly sets it.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .constants import awi_cents
from .factories import (
    create_claim_payload,
    create_correction_request_payload,
    create_overpayment_case_payload,
    create_payee_case_payload,
    create_relationship_payload,
    create_wage_report_payload,
    create_worker_payload,
)
from .test_users import (
    TEST_USERS,
    make_claimant_headers,
    make_claims_specialist_headers,
    make_senior_adjudicator_headers,
)

CS = TEST_USERS["claims_specialist_headers"]
SA = TEST_USERS["senior_adjudicator_headers"]
PA = TEST_USERS["program_administrator_headers"]
EMP = TEST_USERS["employer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_worker(**overrides):
    """Worker intake as ClaimsSpecialist. Returns the Worker (201)."""
    return get_success_data(api.create_worker(create_worker_payload(**overrides), CS))


def set_clock(to_iso8601):
    """Advance/set the logical clock (ProgramAdministrator). Returns current_utc payload."""
    return get_success_data(api.set_clock(to_iso8601, PA))


def post_wage_report(worker_id, tax_year, amount_cents, **overrides):
    """Post one employer wage report (Employer role). Returns the WageReport (201)."""
    return get_success_data(
        api.create_wage_report(
            create_wage_report_payload(worker_id, tax_year, amount_cents, **overrides), EMP
        )
    )


def post_awi_wage_reports(worker_id, start_year, end_year):
    """Post one covered wage report per tax year in [start_year, end_year], each
    at that year's average wage index level (PRD §3.1). Returns the reports."""
    return [
        post_wage_report(worker_id, year, awi_cents(year))
        for year in range(start_year, end_year + 1)
    ]


def file_claim(worker_id, claim_type, entitlement_month, **overrides):
    """File a claim as the worker themself (Claimant, ownership-threaded).
    Returns the FILED claim (201)."""
    return get_success_data(
        api.create_claim(
            create_claim_payload(worker_id, claim_type, entitlement_month, **overrides),
            make_claimant_headers(worker_id),
        )
    )


def approve_claim(claim_id, headers=None):
    """Approve a claim as ClaimsSpecialist. Returns the ENTITLED claim (200)."""
    return get_success_data(api.approve_claim(claim_id, headers or CS))


def get_claim(claim_id):
    """Fresh read of one claim as ClaimsSpecialist."""
    return get_success_data(api.get_claim(claim_id, CS))


def get_worker(worker_id):
    """Fresh read of one worker as ClaimsSpecialist."""
    return get_success_data(api.get_worker(worker_id, CS))


def run_batch(run_month):
    """Run the monthly cycle for an explicit run_month. Returns the run report."""
    return get_success_data(api.run_monthly_cycle(PA, run_month=run_month))


def run_batch_at(clock_iso, run_month):
    """Set the logical clock, then run the monthly cycle. Returns the run report."""
    set_clock(clock_iso)
    return run_batch(run_month)


# ---------------------------------------------------------------------------
# Tier 2: worker + earnings record
# ---------------------------------------------------------------------------

def create_worker_with_awi_record(start_year, end_year, **worker_overrides):
    """Worker born 1964-06 (unless overridden) with covered wage reports at the
    average-wage-index level for every year in [start_year, end_year]."""
    worker = create_worker(**worker_overrides)
    post_awi_wage_reports(worker["id"], start_year, end_year)
    return worker


def earnings_year_row(worker_id, tax_year):
    """Fetch the worker's EarningsYear row for one tax year (None when absent)."""
    rows = get_success_data(api.list_earnings_years(worker_id, CS))
    for row in rows:
        if row["tax_year"] == tax_year:
            return row
    return None


# ---------------------------------------------------------------------------
# Tier 3: claim lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_entitled_retirement(start_year, end_year, entitlement_month,
                              approve_clock_iso=None, **worker_overrides):
    """Worker with an AWI-level record plus an approved RETIREMENT claim.

    The claim is filed and approved without any clock manipulation unless
    approve_clock_iso is given (the clock is then set before approval, so a
    future entitlement month adjudicates at a sensible logical time).
    Returns (worker, entitled_claim).
    """
    worker = create_worker_with_awi_record(start_year, end_year, **worker_overrides)
    claim = file_claim(worker["id"], "RETIREMENT", entitlement_month)
    if approve_clock_iso is not None:
        set_clock(approve_clock_iso)
    entitled = approve_claim(claim["id"])
    return worker, entitled


def generate_payments(claim_id, months):
    """Run one batch per month (each at a clock inside that month) so the claim
    accrues one payment per listed month. months are 'YYYY-MM' strings; the
    clock is set to the 20th of the month."""
    reports = []
    for month in months:
        reports.append(run_batch_at(f"{month}-20T00:00:00Z", month))
    return reports


def list_payments(claim_id):
    return get_success_data(api.list_claim_payments(claim_id, CS))


def payment_for_month(claim_id, month):
    """The claim's payment row for one 'YYYY-MM' month (None when absent)."""
    for payment in list_payments(claim_id):
        if payment["month"] == month:
            return payment
    return None


def list_recomputation_events(claim_id):
    return get_success_data(api.list_claim_recomputation_events(claim_id, CS))


# ---------------------------------------------------------------------------
# Tier 4: relationships and auxiliary claims
# ---------------------------------------------------------------------------

def create_relationship(covered_id, spouse_id, relationship_type, marriage_date,
                        divorce_date=None, verify=False):
    """Assert a relationship as ClaimsSpecialist; optionally verify it.
    Returns the relationship (VERIFIED when verify=True)."""
    overrides = {}
    if divorce_date is not None:
        overrides["divorce_date"] = divorce_date
    rel = get_success_data(
        api.create_relationship(
            create_relationship_payload(
                covered_id, spouse_id, relationship_type, marriage_date, **overrides
            ),
            CS,
        )
    )
    if verify:
        rel = get_success_data(api.verify_relationship(rel["id"], CS))
    return rel


def file_auxiliary_claim(spouse_id, claim_type, entitlement_month, relationship_id):
    """File an auxiliary claim as the spouse themself (Claimant)."""
    return file_claim(
        spouse_id, claim_type, entitlement_month, relationship_id=relationship_id
    )


# ---------------------------------------------------------------------------
# Tier 5: corrections, overpayments, payees
# ---------------------------------------------------------------------------

def file_correction(worker_id, tax_year, claimed_earnings_cents, evidence_type="WAGE_STATEMENT"):
    """File a correction request as the worker themself. Returns PENDING_REVIEW."""
    return get_success_data(
        api.create_correction_request(
            create_correction_request_payload(
                worker_id, tax_year, claimed_earnings_cents, evidence_type=evidence_type
            ),
            make_claimant_headers(worker_id),
        )
    )


def create_overpayment_case(claim_id, amount_cents, period_start_month, period_end_month,
                            reason="REPORTING_ERROR", creator_id=None):
    """Open an overpayment case as ClaimsSpecialist; creator_id pins created_by."""
    headers = make_claims_specialist_headers(creator_id) if creator_id else CS
    return get_success_data(
        api.create_overpayment_case(
            create_overpayment_case_payload(
                claim_id, amount_cents, period_start_month, period_end_month, reason=reason
            ),
            headers,
        )
    )


def get_overpayment_case(case_id, claim_id):
    """Fresh read of one case via the claim's case list."""
    for case in get_success_data(api.list_claim_overpayment_cases(claim_id, CS)):
        if case["id"] == case_id:
            return case
    return None


def create_payee_case(claim_id, creator_id=None, **overrides):
    """Open a payee determination as ClaimsSpecialist; creator_id pins created_by."""
    headers = make_claims_specialist_headers(creator_id) if creator_id else CS
    return get_success_data(
        api.create_payee_case(create_payee_case_payload(claim_id, **overrides), headers)
    )


def decide_payee_case(case_id, outcome, adjudicator_id=None):
    """Decide a payee case as SeniorAdjudicator; adjudicator_id pins the decider."""
    headers = make_senior_adjudicator_headers(adjudicator_id) if adjudicator_id else SA
    return get_success_data(api.decide_payee_case(case_id, outcome, headers))
