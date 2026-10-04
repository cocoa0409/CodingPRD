"""Composite setup builders and the pytest fixtures that expose the client.

Every builder drives the public API only - there is no direct database
access anywhere in this suite.  Builders use ``get_success_data`` so a setup
step the PRD allows to answer 200 or 201 does not have to be pinned at every
call site, and so a setup failure surfaces as a clear "Setup step failed"
message instead of a confusing assertion deep inside a test.

Time discipline: the system runs on a logical clock whose power-on reading is
2026-09-01T00:00:00Z (PRD section 2.4), so any builder that needs a different
"now" sets the clock FIRST and only then creates rows - nothing here relies
on wall-clock time.

Identity discipline: after a builder creates a Beneficiary row, every
ownership-gated call it makes uses ``make_beneficiary_headers(beneficiary["id"])``
(via the ``beneficiary_headers`` shortcut), never a shared constant.

The default billing scenario used by several builders deserves a comment,
because its dates are derived from the effective-month rules of PRD
section 3.2, not assumed: a beneficiary born 1961-06-12 attains in 2026-06
with IEP [2026-03, 2026-09]; enrolling at clock month 2026-05 is the
"before the attainment month" branch, so coverage is effective 2026-06, a
cycle inside 2026-06 activates it, and - with the canonical 2026 rate table
and no determination - the monthly bill is the IRMAA-free fallback of
18500 cents for PART_B and 3450 for PART_D.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import (
    COVERAGE_MA,
    ELECTION_WINDOW_AEP,
    FILING_SINGLE,
    PART_B,
    PART_D,
    RELIEF_BOTH,
    RELIEF_GRANTED,
    VERIFICATION_VERIFIED,
)
from .test_users import (
    APPEALS_OFFICER_HEADERS,
    BENEFIT_ADMINISTRATOR_HEADERS,
    FIELD_OFFICER_HEADERS,
    IRS_DATA_AGENT_HEADERS,
    make_beneficiary_headers,
)

# --- pytest fixtures ----------------------------------------------------------


@pytest.fixture
def client():
    """A client bound to the service under test (server lifecycle is the
    runner's concern)."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias so a test can read either name."""
    return client


# --- Tier 0: logical clock and the monthly cycle -------------------------------


def set_clock(client, to_iso8601, headers=BENEFIT_ADMINISTRATOR_HEADERS):
    """Move the logical clock; returns the ``current_utc`` reading."""
    return get_success_data(client.set_clock(to_iso8601, headers=headers))


def run_monthly_cycle(client, headers=BENEFIT_ADMINISTRATOR_HEADERS):
    """Run the monthly batch for the current clock month; returns the summary."""
    return get_success_data(client.run_monthly_cycle(headers=headers))


def advance_clock_and_run_cycle(client, to_iso8601,
                                headers=BENEFIT_ADMINISTRATOR_HEADERS):
    """Set the clock and immediately run the monthly batch; returns the summary."""
    set_clock(client, to_iso8601, headers=headers)
    return run_monthly_cycle(client, headers=headers)


# --- Tier 1: single-entity builders ----------------------------------------------


def publish_rate_schedule(client, coverage_year=2026,
                          headers=BENEFIT_ADMINISTRATOR_HEADERS, **overrides):
    """Publish a yearly rate table; 2026 and 2027 get the canonical figures."""
    if coverage_year == 2026:
        payload = f.rate_schedule_2026_payload(**overrides)
    elif coverage_year == 2027:
        payload = f.rate_schedule_2027_payload(**overrides)
    else:
        payload = f.rate_schedule_payload(coverage_year=coverage_year, **overrides)
    return get_success_data(client.create_rate_schedule(payload, headers=headers))


def publish_default_rate_schedules(client, headers=BENEFIT_ADMINISTRATOR_HEADERS):
    """Publish both canonical years; returns (schedule_2026, schedule_2027)."""
    return (
        publish_rate_schedule(client, 2026, headers=headers),
        publish_rate_schedule(client, 2027, headers=headers),
    )


def register_beneficiary(client, date_of_birth="1961-12-14", full_name=None,
                         headers=FIELD_OFFICER_HEADERS):
    """Register a beneficiary; returns the row with computed IEP fields."""
    overrides = {"date_of_birth": date_of_birth}
    if full_name is not None:
        overrides["full_name"] = full_name
    return get_success_data(
        client.create_beneficiary(f.beneficiary_payload(**overrides), headers=headers)
    )


def beneficiary_headers(beneficiary):
    """Headers for the Beneficiary caller who IS this row (ownership checks)."""
    return make_beneficiary_headers(beneficiary["id"])


def read_beneficiary(client, beneficiary_id, headers=FIELD_OFFICER_HEADERS):
    return get_success_data(client.get_beneficiary(beneficiary_id, headers=headers))


def beneficiary_version(client, beneficiary_id, headers=FIELD_OFFICER_HEADERS):
    """The current OCC version of a Beneficiary row."""
    return read_beneficiary(client, beneficiary_id, headers=headers)["version"]


def submit_tax_record(client, beneficiary_id, tax_year, magi_cents,
                      filing_status=FILING_SINGLE, headers=IRS_DATA_AGENT_HEADERS):
    return get_success_data(
        client.create_tax_record(
            f.tax_record_payload(beneficiary_id, tax_year, magi_cents, filing_status),
            headers=headers,
        )
    )


def enroll(client, beneficiary, part=PART_B, headers=None, **overrides):
    """Enroll the beneficiary in a part.  The caller sets the clock first;
    the caller is the beneficiary unless headers say otherwise."""
    return get_success_data(
        client.create_enrollment(
            f.enrollment_payload(beneficiary["id"], part, **overrides),
            headers=headers or beneficiary_headers(beneficiary),
        )
    )


def read_enrollment(client, enrollment_id, headers=FIELD_OFFICER_HEADERS):
    return get_success_data(client.get_enrollment(enrollment_id, headers=headers))


def terminate_enrollment(client, enrollment, headers=None):
    """Voluntarily end coverage; PENDING cancels, ACTIVE terminates."""
    return get_success_data(
        client.terminate_enrollment(
            enrollment["id"],
            headers=headers or make_beneficiary_headers(enrollment["beneficiary_id"]),
        )
    )


def create_employer_coverage(client, beneficiary, headers=None, **overrides):
    return get_success_data(
        client.create_employer_coverage(
            f.employer_coverage_payload(beneficiary["id"], **overrides),
            headers=headers or beneficiary_headers(beneficiary),
        )
    )


def verify_employer_coverage(client, record_id, decision=VERIFICATION_VERIFIED,
                             headers=FIELD_OFFICER_HEADERS):
    return get_success_data(
        client.verify_employer_coverage(
            record_id, f.verify_decision_payload(decision), headers=headers
        )
    )


def end_employer_coverage(client, record_id, coverage_end_month,
                          employment_end_month, headers=FIELD_OFFICER_HEADERS):
    return get_success_data(
        client.end_employer_coverage(
            record_id,
            f.end_coverage_payload(coverage_end_month, employment_end_month),
            headers=headers,
        )
    )


def create_withholding_arrangement(client, beneficiary, monthly_benefit_cents=21000,
                                   headers=None):
    return get_success_data(
        client.create_withholding_arrangement(
            f.withholding_arrangement_payload(
                beneficiary["id"], monthly_benefit_cents
            ),
            headers=headers or beneficiary_headers(beneficiary),
        )
    )


def adjust_arrangement(client, arrangement_id, monthly_benefit_cents,
                       headers=BENEFIT_ADMINISTRATOR_HEADERS):
    """Adjust the benefit amount; resumes a SUSPENDED arrangement only when the
    new amount covers the current monthly premiums (PRD section 3.7)."""
    return get_success_data(
        client.adjust_withholding_arrangement(
            arrangement_id,
            f.adjust_arrangement_payload(monthly_benefit_cents),
            headers=headers,
        )
    )


def create_determination(client, beneficiary, coverage_year, part=PART_B,
                         headers=FIELD_OFFICER_HEADERS):
    """Compute the premium for (beneficiary, coverage_year, part); the default
    author is the canonical field-officer identity."""
    return get_success_data(
        client.create_premium_determination(
            f.premium_determination_payload(beneficiary["id"], coverage_year, part),
            headers=headers,
        )
    )


def read_determination(client, determination_id, headers=FIELD_OFFICER_HEADERS):
    return get_success_data(
        client.get_premium_determination(determination_id, headers=headers)
    )


def file_appeal(client, determination, headers=None, **overrides):
    """File a life-changing-event appeal against a FINAL determination."""
    return get_success_data(
        client.create_appeal(
            f.appeal_payload(determination["id"], **overrides),
            headers=headers
            or make_beneficiary_headers(determination["beneficiary_id"]),
        )
    )


def adjudicate_appeal(client, appeal, decision, headers=APPEALS_OFFICER_HEADERS):
    """AppealsOfficer decision on an UNDER_REVIEW appeal (success path)."""
    return get_success_data(
        client.adjudicate_appeal(
            appeal["id"], f.appeal_decision_payload(decision), headers=headers
        )
    )


def respond_to_appeal(client, appeal, note="Additional documentation attached.",
                      headers=None):
    """Beneficiary answers a MORE_INFO_REQUESTED appeal."""
    return get_success_data(
        client.respond_to_appeal(
            appeal["id"],
            f.appeal_response_payload(note),
            headers=headers or make_beneficiary_headers(appeal["beneficiary_id"]),
        )
    )


def file_relief_case(client, beneficiary, headers=None, **overrides):
    """File an equitable-relief case (created UNDER_INVESTIGATION)."""
    return get_success_data(
        client.create_equitable_relief_case(
            f.relief_case_payload(beneficiary["id"], **overrides),
            headers=headers or beneficiary_headers(beneficiary),
        )
    )


def adjudicate_relief_case(client, relief_case, decision=RELIEF_GRANTED,
                           headers=FIELD_OFFICER_HEADERS):
    """FieldOfficer decision on an UNDER_INVESTIGATION case (success path)."""
    return get_success_data(
        client.adjudicate_equitable_relief_case(
            relief_case["id"], f.relief_decision_payload(decision), headers=headers
        )
    )


def pay_invoice_in_full(client, invoice, headers=None):
    """Pay exactly the invoice's outstanding amount; returns the PAID invoice."""
    return get_success_data(
        client.pay_invoice(
            invoice["id"],
            f.pay_invoice_payload(invoice["outstanding_cents"]),
            headers=headers or make_beneficiary_headers(invoice["beneficiary_id"]),
        )
    )


def make_election(client, beneficiary, election_window, target_coverage,
                  headers=None):
    """Read the beneficiary's CURRENT version and file an election with it.

    Returns the RAW response so the caller can assert either the 201 success
    or a 412 stale-version rejection.
    """
    version = beneficiary_version(
        client, beneficiary["id"], headers=headers or beneficiary_headers(beneficiary)
    )
    return client.create_election(
        f.election_payload(
            beneficiary["id"], election_window, target_coverage, version
        ),
        headers=headers or beneficiary_headers(beneficiary),
    )


def create_election(client, beneficiary, election_window, target_coverage,
                    headers=None):
    """The success-path form of ``make_election``; returns the election row."""
    return get_success_data(
        make_election(client, beneficiary, election_window, target_coverage,
                      headers=headers),
        expected_status=201,
    )


# --- Tier 1: list readers ---------------------------------------------------------


def list_enrollment_periods(client, beneficiary, headers=FIELD_OFFICER_HEADERS,
                            params=None):
    return get_success_data(
        client.list_enrollment_periods(beneficiary["id"], headers=headers,
                                       params=params)
    )


def list_enrollments(client, beneficiary, headers=FIELD_OFFICER_HEADERS,
                     params=None):
    return get_success_data(
        client.list_enrollments(beneficiary["id"], headers=headers, params=params)
    )


def list_employer_coverages(client, beneficiary, headers=FIELD_OFFICER_HEADERS,
                            params=None):
    return get_success_data(
        client.list_employer_coverages(beneficiary["id"], headers=headers,
                                       params=params)
    )


def list_tax_records(client, beneficiary, headers=FIELD_OFFICER_HEADERS,
                     params=None):
    return get_success_data(
        client.list_tax_records(beneficiary["id"], headers=headers, params=params)
    )


def list_premium_determinations(client, beneficiary, headers=FIELD_OFFICER_HEADERS,
                                params=None):
    return get_success_data(
        client.list_premium_determinations(beneficiary["id"], headers=headers,
                                           params=params)
    )


def list_appeals(client, beneficiary, headers=FIELD_OFFICER_HEADERS, params=None):
    return get_success_data(
        client.list_appeals(beneficiary["id"], headers=headers, params=params)
    )


def list_withholding_arrangements(client, beneficiary,
                                  headers=BENEFIT_ADMINISTRATOR_HEADERS,
                                  params=None):
    return get_success_data(
        client.list_withholding_arrangements(beneficiary["id"], headers=headers,
                                             params=params)
    )


def list_invoices(client, beneficiary, headers=None, params=None):
    """All of a beneficiary's invoices, created_at ascending (PRD section 2.3)."""
    return get_success_data(
        client.list_invoices(
            beneficiary["id"],
            headers=headers or beneficiary_headers(beneficiary),
            params=params,
        )
    )


def list_payer_coordination(client, beneficiary, headers=FIELD_OFFICER_HEADERS,
                            params=None):
    return get_success_data(
        client.list_payer_coordination(beneficiary["id"], headers=headers,
                                       params=params)
    )


def list_elections(client, beneficiary, headers=None, params=None):
    return get_success_data(
        client.list_elections(
            beneficiary["id"],
            headers=headers or beneficiary_headers(beneficiary),
            params=params,
        )
    )


def list_equitable_relief_cases(client, beneficiary, headers=FIELD_OFFICER_HEADERS,
                                params=None):
    return get_success_data(
        client.list_equitable_relief_cases(beneficiary["id"], headers=headers,
                                           params=params)
    )


def list_penalties(client, beneficiary, headers=FIELD_OFFICER_HEADERS, params=None):
    return get_success_data(
        client.list_penalties(beneficiary["id"], headers=headers, params=params)
    )


# --- Tier 2: beneficiary + enrollment composites ------------------------------------


def setup_beneficiary_with_enrollment(client, date_of_birth="1961-06-12",
                                      part=PART_B, enroll_at="2026-05-10T00:00:00Z"):
    """Beneficiary + one enrollment, still PENDING (effective month ahead of the
    clock).  Default dates: DOB 1961-06-12 attains 2026-06, so enrolling at
    2026-05 takes the before-attainment branch and coverage is effective
    2026-06 (PRD section 3.2).  Returns (beneficiary, enrollment)."""
    set_clock(client, enroll_at)
    beneficiary = register_beneficiary(client, date_of_birth=date_of_birth)
    enrollment = enroll(client, beneficiary, part=part)
    return beneficiary, enrollment


def setup_billed_enrollment(client, date_of_birth="1961-06-12", part=PART_B,
                            enroll_at="2026-05-10T00:00:00Z",
                            first_bill_at="2026-06-15T00:00:00Z"):
    """A DIRECT_BILL enrollment with its first ISSUED invoice.

    Publishes the canonical 2026 rate table, enrolls (effective 2026-06), then
    runs a cycle inside 2026-06: the enrollment activates with no withholding
    arrangement and the cycle bills the service month at the IRMAA-free
    fallback amount.  Returns (beneficiary, enrollment, invoice)."""
    publish_rate_schedule(client, 2026)
    beneficiary, enrollment = setup_beneficiary_with_enrollment(
        client, date_of_birth=date_of_birth, part=part, enroll_at=enroll_at
    )
    advance_clock_and_run_cycle(client, first_bill_at)
    enrollment = read_enrollment(client, enrollment["id"])
    invoices = list_invoices(client, beneficiary)
    assert len(invoices) == 1, "expected exactly one invoice after the first cycle"
    return beneficiary, enrollment, invoices[0]


# Cycle instants for the delinquency ladder: each bills the current service
# month and marks the previous month's unpaid invoice PAST_DUE.
_DELINQUENCY_CYCLE_INSTANTS = (
    "2026-06-15T00:00:00Z",  # activate + invoice for 2026-06
    "2026-07-15T00:00:00Z",  # 2026-06 invoice PAST_DUE + invoice for 2026-07
    "2026-08-15T00:00:00Z",  # 2026-07 invoice PAST_DUE + invoice for 2026-08
    "2026-09-15T00:00:00Z",  # third PAST_DUE -> termination + write-offs
)


def setup_delinquent_enrollment(client, past_due_count=2,
                                date_of_birth="1961-06-12", part=PART_B):
    """A DELINQUENT enrollment with ``past_due_count`` PAST_DUE invoices (1 or
    2; at 3 the enrollment terminates - use setup_terminated_by_delinquency).

    Returns (beneficiary, enrollment, invoices) with the enrollment re-read
    after the last cycle."""
    assert 1 <= past_due_count <= 2, (
        "past_due_count 3 terminates the enrollment; use "
        "setup_terminated_by_delinquency for that"
    )
    publish_rate_schedule(client, 2026)
    beneficiary, enrollment = setup_beneficiary_with_enrollment(
        client, date_of_birth=date_of_birth, part=part
    )
    for instant in _DELINQUENCY_CYCLE_INSTANTS[: past_due_count + 1]:
        advance_clock_and_run_cycle(client, instant)
    enrollment = read_enrollment(client, enrollment["id"])
    invoices = list_invoices(client, beneficiary)
    return beneficiary, enrollment, invoices


def setup_terminated_by_delinquency(client, date_of_birth="1961-06-12",
                                    part=PART_B):
    """Three consecutive PAST_DUE invoices: the fourth cycle terminates the
    enrollment (end_month = the clock month) and writes the unpaid invoices
    off (PRD section 3.7).  Returns (beneficiary, enrollment, invoices)."""
    publish_rate_schedule(client, 2026)
    beneficiary, enrollment = setup_beneficiary_with_enrollment(
        client, date_of_birth=date_of_birth, part=part
    )
    for instant in _DELINQUENCY_CYCLE_INSTANTS:
        advance_clock_and_run_cycle(client, instant)
    enrollment = read_enrollment(client, enrollment["id"])
    invoices = list_invoices(client, beneficiary)
    return beneficiary, enrollment, invoices


def setup_terminated_enrollment_interval(client, date_of_birth="1960-12-05",
                                         part=PART_B,
                                         enroll_at="2025-12-10T00:00:00Z",
                                         activate_at="2026-01-05T00:00:00Z",
                                         terminate_at="2026-06-10T00:00:00Z"):
    """An ACTIVE enrollment terminated voluntarily, leaving the half-open
    interval [effective_month, end_month) behind it.  Default dates give
    [2026-01, 2026-06).  Returns (beneficiary, enrollment); the clock is left
    at ``terminate_at``."""
    set_clock(client, enroll_at)
    beneficiary = register_beneficiary(client, date_of_birth=date_of_birth)
    enrollment = enroll(client, beneficiary, part=part)
    advance_clock_and_run_cycle(client, activate_at)
    set_clock(client, terminate_at)
    enrollment = terminate_enrollment(client, enrollment)
    return beneficiary, enrollment


def setup_withholding_shortfall(client, monthly_benefit_cents=21000,
                                date_of_birth="1961-06-12",
                                enroll_at="2026-05-10T00:00:00Z",
                                cycle_at="2026-06-05T00:00:00Z"):
    """The withholding waterfall with a shortfall (PRD section 3.7).

    PART_B (18500) and PART_D (3450) enrollments plus an arrangement whose
    benefit cannot cover both: the cycle fills PART_B fully, pays PART_D
    partially, suspends the arrangement, flips BOTH enrollments to
    DIRECT_BILL, and issues one arrears invoice for the PART_D shortfall
    (950 with the default benefit of 21000).

    Returns a dict: beneficiary, enrollment_b, enrollment_d, arrangement,
    invoices - all re-read after the cycle."""
    publish_rate_schedule(client, 2026)
    set_clock(client, enroll_at)
    beneficiary = register_beneficiary(client, date_of_birth=date_of_birth)
    enrollment_b = enroll(client, beneficiary, part=PART_B)
    enrollment_d = enroll(client, beneficiary, part=PART_D)
    arrangement = create_withholding_arrangement(
        client, beneficiary, monthly_benefit_cents
    )
    advance_clock_and_run_cycle(client, cycle_at)
    arrangements = list_withholding_arrangements(client, beneficiary)
    return {
        "beneficiary": beneficiary,
        "enrollment_b": read_enrollment(client, enrollment_b["id"]),
        "enrollment_d": read_enrollment(client, enrollment_d["id"]),
        "arrangement": arrangements[0],
        "invoices": list_invoices(client, beneficiary),
    }


def setup_verified_employer_coverage(client, employer_size=50,
                                     employer_name="ACME",
                                     coverage_start_month="2024-01",
                                     date_of_birth="1961-03-10",
                                     created_at="2026-01-05T00:00:00Z",
                                     **record_overrides):
    """Beneficiary + a VERIFIED employer coverage record.

    The clock is set to ``created_at`` BEFORE registration so the opening
    payer-coordination interval starts in that clock month; verification then
    recomputes the payer role retroactively from ``coverage_start_month``
    (PRD section 3.3).  Returns (beneficiary, record)."""
    set_clock(client, created_at)
    beneficiary = register_beneficiary(client, date_of_birth=date_of_birth)
    record = create_employer_coverage(
        client,
        beneficiary,
        employer_name=employer_name,
        employer_size=employer_size,
        coverage_start_month=coverage_start_month,
        **record_overrides
    )
    record = verify_employer_coverage(client, record["id"])
    return beneficiary, record


# --- Tier 3: determinations and appeals --------------------------------------------


def setup_determination(client, coverage_year=2027, part=PART_B,
                        date_of_birth="1960-01-15",
                        enroll_at="2025-01-10T00:00:00Z",
                        tax_records=((2025, 15000000),),
                        filing_status=FILING_SINGLE,
                        author_headers=FIELD_OFFICER_HEADERS):
    """Beneficiary + enrollment + a premium determination.

    Publishes the coverage year's canonical rate table, enrolls under the IEP
    (DOB 1960-01-15 attains 2025-01; enrolling at 2025-01 yields effective
    2025-02, inside the IEP, so no penalty), submits the given
    ``(tax_year, magi_cents)`` records, and computes the determination.  A
    record for ``coverage_year - 2`` makes the row FINAL; relying on
    ``coverage_year - 3`` leaves it PROVISIONAL (PRD section 3.5).

    Returns (beneficiary, enrollment, determination)."""
    publish_rate_schedule(client, coverage_year)
    set_clock(client, enroll_at)
    beneficiary = register_beneficiary(client, date_of_birth=date_of_birth)
    enrollment = enroll(client, beneficiary, part=part)
    for tax_year, magi_cents in tax_records:
        submit_tax_record(client, beneficiary["id"], tax_year, magi_cents,
                          filing_status=filing_status)
    determination = create_determination(
        client, beneficiary, coverage_year, part=part, headers=author_headers
    )
    return beneficiary, enrollment, determination


def setup_final_determination(client, coverage_year=2027, part=PART_B,
                              tax_year=None, magi_cents=15000000, **kwargs):
    """A FINAL determination: the tax record for coverage_year - 2 exists."""
    if tax_year is None:
        tax_year = coverage_year - 2
    return setup_determination(
        client,
        coverage_year=coverage_year,
        part=part,
        tax_records=((tax_year, magi_cents),),
        **kwargs
    )


def setup_provisional_determination(client, coverage_year=2027, part=PART_B,
                                    tax_year=None, magi_cents=9000000, **kwargs):
    """A PROVISIONAL determination: only the coverage_year - 3 record exists."""
    if tax_year is None:
        tax_year = coverage_year - 3
    return setup_determination(
        client,
        coverage_year=coverage_year,
        part=part,
        tax_records=((tax_year, magi_cents),),
        **kwargs
    )


def setup_appeal_under_review(client, appeal_overrides=None,
                              author_headers=FIELD_OFFICER_HEADERS, **det_kwargs):
    """A FINAL determination with an appeal already filed against it
    (UNDER_REVIEW).  Returns (beneficiary, determination, appeal)."""
    beneficiary, _enrollment, determination = setup_final_determination(
        client, author_headers=author_headers, **det_kwargs
    )
    appeal = file_appeal(client, determination, **(appeal_overrides or {}))
    return beneficiary, determination, appeal


# --- Tier 4/5: accumulation and cascade-ready composites ---------------------------


def setup_paid_invoice_pair(client, date_of_birth="1960-06-10",
                            enroll_at="2027-02-10T00:00:00Z",
                            coverage_year=2027, part=PART_B,
                            tax_year=2025, magi_cents=5000000,
                            author_headers=FIELD_OFFICER_HEADERS):
    """Two months of penalized premiums, billed and PAID - the pre-cascade
    state equitable relief and appeals reprice.

    Default arithmetic (all derivable from PRD sections 3.4 and 3.5 with the
    canonical rate tables): DOB 1960-06-10 ends the IEP at 2025-09; enrolling
    at 2027-02 under the GEP makes coverage effective 2027-03, leaving a
    17-month gap and a 10% PART_B penalty; the FINAL 2027 determination on
    5000000 cents of MAGI lands in tier 0, so the monthly bill is
    19000 base + 1900 penalty = 20900.  Cycles in 2027-03 and 2027-04 issue
    two invoices; both are paid in full.

    Returns a dict: beneficiary, enrollment, determination, invoices (paid)."""
    publish_default_rate_schedules(client)
    set_clock(client, enroll_at)
    beneficiary = register_beneficiary(client, date_of_birth=date_of_birth)
    enrollment = enroll(client, beneficiary, part=part)
    submit_tax_record(client, beneficiary["id"], tax_year, magi_cents)
    determination = create_determination(
        client, beneficiary, coverage_year, part=part, headers=author_headers
    )
    advance_clock_and_run_cycle(client, "2027-03-05T00:00:00Z")
    advance_clock_and_run_cycle(client, "2027-04-05T00:00:00Z")
    invoices = list_invoices(client, beneficiary)
    assert len(invoices) == 2, "expected exactly two billed months"
    paid = [pay_invoice_in_full(client, invoice) for invoice in invoices]
    return {
        "beneficiary": read_beneficiary(client, beneficiary["id"]),
        "enrollment": read_enrollment(client, enrollment["id"]),
        "determination": determination,
        "invoices": paid,
    }


def setup_relief_case_on_paid_pair(client, relief_overrides=None, **kwargs):
    """The paid invoice pair plus a filed equitable-relief case (default BOTH /
    PART_B / requested_effective_month 2026-06), ready for adjudication.
    Returns the paid-pair dict with an added ``relief_case`` entry."""
    state = setup_paid_invoice_pair(client, **kwargs)
    overrides = {
        "relief_type": RELIEF_BOTH,
        "part": PART_B,
        "requested_effective_month": "2026-06",
        "description": "Misinformed about the enrollment window",
    }
    overrides.update(relief_overrides or {})
    state["relief_case"] = file_relief_case(
        client, state["beneficiary"], **overrides
    )
    return state


def setup_beneficiary_with_ma_coverage(client, date_of_birth="1960-01-15",
                                       enroll_at="2025-01-10T00:00:00Z",
                                       aep_at="2026-10-20T00:00:00Z",
                                       effectuate_at="2027-01-05T00:00:00Z"):
    """Original coverage moved to the private-plan alternative through the
    annual window (PRD section 3.8): a PART_B enrollment, an AEP election
    targeting MA, and the cycle that effectuates it into an ACTIVE PART_C
    enrollment.  Returns (beneficiary, election) with the election re-read
    (EFFECTIVE)."""
    set_clock(client, enroll_at)
    beneficiary = register_beneficiary(client, date_of_birth=date_of_birth)
    enroll(client, beneficiary, part=PART_B)
    set_clock(client, aep_at)
    election = create_election(client, beneficiary, ELECTION_WINDOW_AEP,
                               COVERAGE_MA)
    advance_clock_and_run_cycle(client, effectuate_at)
    elections = list_elections(client, beneficiary)
    return beneficiary, elections[0]
