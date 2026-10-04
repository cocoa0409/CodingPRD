"""Composite setup helpers for the GSE Loan Delivery API.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the harness restarts the server (and empties the database) before
each test, so no state can be assumed.

Identity threading: ownership-gated calls use make_seller_officer_headers /
make_servicer_officer_headers with the actual entity id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT, TEST_DEFAULTS
from .factories import (
    create_llpa_matrix_payload,
    create_loan_payload,
    create_master_agreement_payload,
    create_payment_event_payload,
    create_pool_payload,
    create_qc_audit_payload,
    create_qc_finding_payload,
    create_seller_payload,
    create_servicer_payload,
    create_servicing_transfer_payload,
    standard_llpa_row,
)
from .test_users import (
    TEST_USERS,
    make_seller_officer_headers,
    make_servicer_officer_headers,
)

ADMIN = TEST_USERS["gse_admin_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]
UW_ENGINE = TEST_USERS["uw_engine_headers"]
QC_AUDITOR = TEST_USERS["qc_auditor_headers"]


def set_clock(current_utc=CLOCK_DEFAULT):
    """Advance (or pin) the logical clock (PRD §2.6)."""
    resp = api_client.set_clock(current_utc, ADMIN)
    return get_success_data(resp)


def create_seller(**overrides):
    payload = create_seller_payload(**overrides)
    resp = api_client.create_seller(payload, ADMIN)
    return get_success_data(resp)


def create_approved_seller(**overrides):
    seller = create_seller(**overrides)
    get_success_data(api_client.approve_seller(seller["id"], ADMIN))
    seller["status"] = "APPROVED"
    return seller


def create_servicer(**overrides):
    payload = create_servicer_payload(**overrides)
    resp = api_client.create_servicer(payload, ADMIN)
    return get_success_data(resp)


def create_approved_servicer(**overrides):
    servicer = create_servicer(**overrides)
    get_success_data(api_client.approve_servicer(servicer["id"], ADMIN))
    servicer["status"] = "APPROVED"
    return servicer


def create_active_agreement(seller_id, servicer_id, **overrides):
    payload = create_master_agreement_payload(seller_id, servicer_id, **overrides)
    agreement = get_success_data(api_client.create_master_agreement(payload, ADMIN))
    get_success_data(api_client.activate_master_agreement(agreement["id"], ADMIN))
    agreement["status"] = "ACTIVE"
    return agreement


def create_active_llpa_matrix(rows=None, **overrides):
    payload = create_llpa_matrix_payload(rows=rows, **overrides)
    return get_success_data(api_client.create_llpa_matrix(payload, ADMIN))


def setup_counterparty_chain(seller_overrides=None, servicer_overrides=None,
                             grid_rows=None, set_clock_first=True):
    """Tier-2 chain: clock pinned, seller + servicer approved, agreement ACTIVE,
    LLPA grid ACTIVE. Returns (seller, servicer, agreement, matrix)."""
    if set_clock_first:
        set_clock()
    seller = create_approved_seller(**(seller_overrides or {}))
    servicer = create_approved_servicer(**(servicer_overrides or {}))
    agreement = create_active_agreement(seller["id"], servicer["id"])
    matrix = create_active_llpa_matrix(rows=grid_rows)
    return seller, servicer, agreement, matrix


def create_draft_loan(seller, servicer, agreement, **loan_overrides):
    payload = create_loan_payload(seller["id"], servicer["id"], agreement["id"],
                                  **loan_overrides)
    headers = make_seller_officer_headers(seller["id"])
    return get_success_data(api_client.create_loan(payload, headers))


def create_pool_for(seller, agreement, **overrides):
    payload = create_pool_payload(seller["id"], agreement["id"], **overrides)
    headers = make_seller_officer_headers(seller["id"])
    return get_success_data(api_client.create_pool(payload, headers))


def open_underwriting_case(loan, seller):
    headers = make_seller_officer_headers(seller["id"])
    return get_success_data(
        api_client.create_underwriting_case({"loan_id": loan["id"]}, headers)
    )


def add_validation_report(case, service_type, provider_reference):
    report = get_success_data(
        api_client.create_validation_report(
            case["id"],
            {"service_type": service_type, "provider_reference": provider_reference},
            UNDERWRITER,
        )
    )
    return report


def complete_report(report, result="VALIDATED"):
    return get_success_data(
        api_client.complete_validation_report(report["id"], {"result": result}, UNDERWRITER)
    )


def validate_case_round(case, results=None, ref_prefix="PR"):
    """Record and complete one report per service type for the case's current
    round. `results` maps service_type -> result; defaults to all VALIDATED."""
    results = results or {}
    reports = {}
    for service_type in ("INCOME", "ASSET", "EMPLOYMENT"):
        report = add_validation_report(case, service_type, f"{ref_prefix}-{service_type}")
        complete_report(report, results.get(service_type, "VALIDATED"))
        reports[service_type] = report
    return reports


def finalize_case(case):
    """Finalize a VALIDATED case using its current version (OCC, PRD §2.8)."""
    current = get_success_data(api_client.get_underwriting_case(case["id"], ADMIN))
    return get_success_data(
        api_client.finalize_underwriting_case(
            case["id"], {"expected_case_version": current["version"]}, UW_ENGINE
        )
    )


def underwrite_loan(loan, seller):
    """Walk a DRAFT loan through a fully validated, finalized underwriting case.
    Returns the finalized case."""
    case = open_underwriting_case(loan, seller)
    validate_case_round(case)
    return finalize_case(case)


def deliver_loan(loan, pool, seller):
    headers = make_seller_officer_headers(seller["id"])
    return get_success_data(
        api_client.deliver_loan(loan["id"], {"pool_id": pool["id"]}, headers)
    )


def issue_pool(pool, seller):
    headers = make_seller_officer_headers(seller["id"])
    get_success_data(api_client.lock_pool(pool["id"], headers))
    current = get_success_data(api_client.get_pool(pool["id"], ADMIN))
    return get_success_data(
        api_client.issue_pool(
            pool["id"], {"expected_pool_version": current["version"]}, headers
        )
    )


def create_underwritten_loan(seller, servicer, agreement, **loan_overrides):
    """Tier-3: create a loan and underwrite it (defaults APPROVE_ELIGIBLE).
    Returns the loan re-read after finalization."""
    loan = create_draft_loan(seller, servicer, agreement, **loan_overrides)
    underwrite_loan(loan, seller)
    return get_success_data(api_client.get_loan(loan["id"], ADMIN))


def create_purchased_loan(seller, servicer, agreement, pool=None, **loan_overrides):
    """Tier-3: create a loan, underwrite it, deliver it, and issue the pool.
    Returns (loan, pool)."""
    if pool is None:
        pool = create_pool_for(seller, agreement)
    loan = create_draft_loan(seller, servicer, agreement, **loan_overrides)
    underwrite_loan(loan, seller)
    deliver_loan(loan, pool, seller)
    issue_pool(pool, seller)
    loan = get_success_data(api_client.get_loan(loan["id"], ADMIN))
    return loan, pool


def open_audit(seller, sampling_method="RANDOM"):
    return get_success_data(
        api_client.create_qc_audit(
            create_qc_audit_payload(seller["id"], sampling_method=sampling_method), QC_AUDITOR
        )
    )


def add_finding(audit, loan, defect_category="COLLATERAL", severity="SIGNIFICANT"):
    return get_success_data(
        api_client.create_qc_finding(
            audit["id"],
            create_qc_finding_payload(loan["id"], defect_category=defect_category, severity=severity),
            QC_AUDITOR,
        )
    )


def issue_demand(finding):
    return get_success_data(api_client.issue_repurchase_demand(finding["id"], ADMIN))


def create_demand_for_loan(loan, seller, defect_category="COLLATERAL",
                           severity="SIGNIFICANT"):
    """Tier-3: audit + finding + issued findings + ISSUED repurchase demand.
    Returns (audit, finding, demand)."""
    audit = open_audit(seller)
    finding = add_finding(audit, loan, defect_category, severity)
    get_success_data(api_client.issue_findings(audit["id"], QC_AUDITOR))
    demand = issue_demand(finding)
    return audit, finding, demand


def appeal_demand(demand, seller, reason="contesting"):
    headers = make_seller_officer_headers(seller["id"])
    return get_success_data(
        api_client.appeal_repurchase_demand(demand["id"], {"appeal_reason": reason}, headers)
    )


def resolve_appeal(demand, outcome="UPHELD"):
    return get_success_data(
        api_client.resolve_appeal(demand["id"], {"outcome": outcome}, ADMIN)
    )


def create_upheld_demand(loan, seller, defect_category="COLLATERAL"):
    """Tier-3: demand ISSUED, appealed, resolved UPHELD.
    Returns (audit, finding, demand)."""
    audit, finding, demand = create_demand_for_loan(loan, seller, defect_category)
    appeal_demand(demand, seller)
    demand = resolve_appeal(demand, "UPHELD")
    return audit, finding, demand


def record_payments(loan, servicer, count, start_year=2026, start_month=9,
                    paid_on_time=True):
    """Tier-4: record `count` monthly payment events beginning at
    (start_year, start_month), one per month."""
    headers = make_servicer_officer_headers(servicer["id"])
    events = []
    year, month = start_year, start_month
    for _ in range(count):
        due = f"{year:04d}-{month:02d}-01T00:00:00Z"
        payload = create_payment_event_payload(loan["id"], due_date=due,
                                               paid_on_time=paid_on_time)
        events.append(get_success_data(api_client.create_payment_event(payload, headers)))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return events


def get_or_create_pipeline(seller):
    headers = make_seller_officer_headers(seller["id"])
    return get_success_data(
        api_client.create_pipeline({"seller_id": seller["id"]}, headers)
    )


def get_loan(loan_id):
    return get_success_data(api_client.get_loan(loan_id, ADMIN))


def get_pool(pool_id):
    return get_success_data(api_client.get_pool(pool_id, ADMIN))


def get_case(case_id):
    return get_success_data(api_client.get_underwriting_case(case_id, ADMIN))


def get_servicer(servicer_id):
    return get_success_data(api_client.get_servicer(servicer_id, ADMIN))


def get_seller(seller_id):
    return get_success_data(api_client.get_seller(seller_id, ADMIN))


def get_finding(finding_id):
    return get_success_data(api_client.get_qc_finding(finding_id, ADMIN))


def get_demand(demand_id):
    return get_success_data(api_client.get_repurchase_demand(demand_id, ADMIN))
