"""Composite setup helpers.

Every test starts against a freshly restarted server (empty database), so all
preconditions are built from scratch through the PRD's public endpoints. The
helpers below encapsulate the repeated multi-step chains:

  setup_approved_issuer      application -> submit -> review -> approve -> Issuer
  setup_issuer_with_engagement  + document custodian + ACTIVE engagement
  setup_draft_pool_with_loans + DRAFT pool with N loans
  setup_live_pool            + assemble -> CERTIFIED certification -> activate

All identity threading is explicit: IssuerOfficer headers are built with the
issuer's id, DocumentCustodian headers with the custodian's id, and the
segregation-of-duties rule is respected by using a different reviewer id than
the submitting officer.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_application_payload,
    create_certification_payload,
    create_custodial_account_payload,
    create_custodian_payload,
    create_engagement_payload,
    create_loan_payload,
    create_pool_payload,
)
from .test_users import (
    TEST_USERS,
    make_agency_reviewer_headers,
    make_applicant_officer_headers,
    make_document_custodian_headers,
    make_issuer_officer_headers,
)

REVIEWER_ID = "reviewer-1"


def set_clock(current_utc=TEST_DEFAULTS["CLOCK_DATE"]):
    """Drive the server logical clock (PlatformAdmin only)."""
    resp = api_client.set_clock(current_utc, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


def create_draft_application(officer_id, reviewer_id=None, **app_overrides):
    """Create an application in DRAFT as the given applicant officer."""
    headers = make_applicant_officer_headers(officer_id)
    resp = api_client.create_application(create_application_payload(**app_overrides), headers)
    return get_success_data(resp)


def submit_application(app_id, officer_id):
    resp = api_client.submit_application(app_id, make_applicant_officer_headers(officer_id))
    return get_success_data(resp)


def review_application(app_id, reviewer_id=REVIEWER_ID):
    resp = api_client.review_application(app_id, make_agency_reviewer_headers(reviewer_id))
    return get_success_data(resp)


def approve_application(app_id, reviewer_id=REVIEWER_ID):
    """Approve; returns the application (with approved_issuer_id set)."""
    resp = api_client.approve_application(app_id, make_agency_reviewer_headers(reviewer_id))
    return get_success_data(resp)


def get_issuer(issuer_id):
    resp = api_client.get_issuer(issuer_id, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


def setup_approved_issuer(officer_id, reviewer_id=REVIEWER_ID, **app_overrides):
    """Application -> submit -> review -> approve. Returns the Issuer.

    The submitting officer and approving reviewer use distinct opaque user
    ids so segregation of duties is satisfied by construction.
    """
    app = create_draft_application(officer_id, **app_overrides)
    submit_application(app["id"], officer_id)
    review_application(app["id"], reviewer_id)
    app = approve_application(app["id"], reviewer_id)
    issuer_id = app["approved_issuer_id"]
    return get_issuer(issuer_id)


def setup_issuer_with_engagement(officer_id, reviewer_id=REVIEWER_ID, **app_overrides):
    """Approved issuer + document custodian + ACTIVE engagement.

    Returns (issuer, custodian, engagement).
    """
    issuer = setup_approved_issuer(officer_id, reviewer_id=reviewer_id, **app_overrides)
    custodian = get_success_data(api_client.create_custodian(
        create_custodian_payload(), TEST_USERS["platform_admin_headers"]))
    engagement = get_success_data(api_client.create_engagement(
        create_engagement_payload(custodian["id"], issuer["id"]),
        make_issuer_officer_headers(issuer["id"])))
    return issuer, custodian, engagement


def create_draft_pool(issuer, custodian, pool_overrides=None):
    """Create a DRAFT pool against the issuer at its current version.

    Returns (pool, issuer_version_after_create). The issuer version is read
    back so later pool writes and report creates can thread the fresh OCC
    versions.
    """
    issuer_now = get_issuer(issuer["id"])
    payload = create_pool_payload(
        issuer["id"], custodian["id"], issuer_now["version"],
        **(pool_overrides or {}))
    pool = get_success_data(api_client.create_pool(
        payload, make_issuer_officer_headers(issuer["id"])))
    return pool


def add_loan(issuer_id, pool_id, principal_balance_cents, **loan_overrides):
    resp = api_client.create_loan(
        create_loan_payload(pool_id, principal_balance_cents, **loan_overrides),
        make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def assemble_pool(issuer_id, pool_id):
    resp = api_client.assemble_pool(pool_id, make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def certify_pool(custodian_id, pool_id, decision="CERTIFIED", exception_loan_ids=None):
    payload = create_certification_payload(decision)
    if exception_loan_ids is not None:
        payload["exception_loan_ids"] = exception_loan_ids
    resp = api_client.create_certification(
        pool_id, payload, make_document_custodian_headers(custodian_id))
    return get_success_data(resp)


def activate_pool(issuer_id, pool_id):
    resp = api_client.activate_pool(pool_id, make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def setup_draft_pool_with_loans(officer_id, loan_specs, reviewer_id=REVIEWER_ID,
                                pool_overrides=None, **app_overrides):
    """Approved issuer + custodian + engagement + DRAFT pool + loans.

    loan_specs: list of principal amounts in cents (or dicts of loan overrides
    that include principal_balance_cents).

    Returns (issuer, custodian, pool, loans).
    """
    issuer, custodian, _eng = setup_issuer_with_engagement(
        officer_id, reviewer_id=reviewer_id, **app_overrides)
    pool = create_draft_pool(issuer, custodian, pool_overrides)
    loans = []
    for spec in loan_specs:
        if isinstance(spec, dict):
            principal = spec.pop("principal_balance_cents")
            loans.append(add_loan(issuer["id"], pool["id"], principal, **spec))
        else:
            loans.append(add_loan(issuer["id"], pool["id"], spec))
    return issuer, custodian, pool, loans


def setup_live_pool(officer_id, loan_specs, reviewer_id=REVIEWER_ID,
                    pool_overrides=None, **app_overrides):
    """DRAFT pool + loans -> assemble -> CERTIFIED certification -> activate.

    Returns (issuer, custodian, pool, loans) with pool in LIVE. Activation
    auto-creates the current clock month's DRAFT investor report.
    """
    issuer, custodian, pool, loans = setup_draft_pool_with_loans(
        officer_id, loan_specs, reviewer_id=reviewer_id,
        pool_overrides=pool_overrides, **app_overrides)
    assemble_pool(issuer["id"], pool["id"])
    certify_pool(custodian["id"], pool["id"])
    pool = activate_pool(issuer["id"], pool["id"])
    return issuer, custodian, pool, loans


def list_reports_for_pool(pool_id):
    resp = api_client.list_investor_reports(
        TEST_USERS["platform_admin_headers"], params={"pool_id": pool_id})
    return get_success_data(resp)


def get_auto_report(pool_id):
    """Fetch the single auto-created DRAFT report for a just-activated pool."""
    reports = list_reports_for_pool(pool_id)
    assert len(reports) == 1, f"expected exactly one auto report, got {len(reports)}"
    return reports[0]


def submit_report(issuer_id, report_id):
    resp = api_client.submit_report(report_id, make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def accept_report(report_id, reviewer_id=REVIEWER_ID):
    resp = api_client.accept_report(report_id, make_agency_reviewer_headers(reviewer_id))
    return get_success_data(resp)


def reject_report(report_id, reviewer_id=REVIEWER_ID):
    resp = api_client.reject_report(report_id, make_agency_reviewer_headers(reviewer_id))
    return get_success_data(resp)


def list_payments_for_report(report_id):
    resp = api_client.list_pass_through_payments(
        TEST_USERS["platform_admin_headers"], params={"report_id": report_id})
    return get_success_data(resp)


def get_payment_for_report(report_id):
    payments = list_payments_for_report(report_id)
    assert len(payments) == 1, f"expected exactly one payment, got {len(payments)}"
    return payments[0]


def list_advances_for_issuer(issuer_id):
    resp = api_client.list_liquidity_advances(
        TEST_USERS["platform_admin_headers"], params={"issuer_id": issuer_id})
    return get_success_data(resp)


def get_pool(pool_id):
    resp = api_client.get_pool(pool_id, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


def create_account(issuer_id, account_type):
    resp = api_client.create_custodial_account(
        create_custodial_account_payload(issuer_id, account_type),
        make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def get_account(account_id):
    resp = api_client.get_custodial_account(account_id, TEST_USERS["platform_admin_headers"])
    return get_success_data(resp)


def post_transaction(issuer_id, account_id, component, amount_cents, **overrides):
    payload = {"component": component, "amount_cents": amount_cents}
    payload.update(overrides)
    resp = api_client.create_account_transaction(
        account_id, payload, make_issuer_officer_headers(issuer_id))
    return get_success_data(resp)


def setup_live_pool_with_accepted_report(officer_id, loan_specs, reviewer_id=REVIEWER_ID,
                                         pool_overrides=None, **app_overrides):
    """LIVE pool + auto report submitted + accepted.

    Returns (issuer, custodian, pool, loans, report, payment) with the
    pass-through payment in DUE.
    """
    issuer, custodian, pool, loans = setup_live_pool(
        officer_id, loan_specs, reviewer_id=reviewer_id,
        pool_overrides=pool_overrides, **app_overrides)
    report = get_auto_report(pool["id"])
    submit_report(issuer["id"], report["id"])
    accept_report(report["id"], reviewer_id)
    payment = get_payment_for_report(report["id"])
    return issuer, custodian, pool, loans, report, payment


def setup_pool_with_open_breach(officer_id, loan_a_principal, loan_b_principal,
                                reviewer_id=REVIEWER_ID):
    """LIVE pool of two loans where loan A is at DELINQ_60 so the pool rate
    breaches 500 bps and a DelinquencyBreach exists in OPEN.

    loan_a is the loan driven delinquent. Returns
    (issuer, custodian, pool, loan_a, loan_b, breach).
    """
    issuer, custodian, pool, loans = setup_live_pool(
        officer_id, [loan_a_principal, loan_b_principal], reviewer_id=reviewer_id)
    loan_a, loan_b = loans
    officer_headers = make_issuer_officer_headers(issuer["id"])
    get_success_data(api_client.set_loan_delinquency_status(loan_a["id"], "DELINQ_30", officer_headers))
    get_success_data(api_client.set_loan_delinquency_status(loan_a["id"], "DELINQ_60", officer_headers))
    resp = api_client.list_delinquency_breaches(
        TEST_USERS["platform_admin_headers"], params={"pool_id": pool["id"]})
    breaches = get_success_data(resp)
    assert len(breaches) == 1, f"expected exactly one breach, got {len(breaches)}"
    return issuer, custodian, pool, loan_a, loan_b, breaches[0]
