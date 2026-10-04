"""Composite setup builders.

Every builder drives the public API only — there is no direct database access
anywhere in this suite.  Builders use ``get_success_data`` (lenient validator)
so setup failures surface as plain assertion errors instead of confusing
validator chains.

The builders are phased: each tier returns the entities it built so tests
can chain or inspect them.  Identity threading is mandatory: any role that
is entity-backed (CompanyUser, AccountantUser) gets headers built from the
persisted entity's id via ``make_company_user_headers`` /
``make_accountant_user_headers``.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from . import constants as C
from . import factories as f
from .test_users import (
    PLATFORM_ADMIN,
    make_accountant_user_headers,
    make_company_user_headers,
)


# --- pytest fixtures -------------------------------------------------------------


@pytest.fixture
def client():
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def api(client):
    """Alias kept so a test can read either name."""
    return client


# --- Logical clock ------------------------------------------------------------------


def set_clock(client, current_utc=C.CLOCK_INITIAL_INSTANT):
    response = client.set_clock(current_utc, headers=PLATFORM_ADMIN)
    assert response.status_code in (200, 201), (
        "setting the logical clock to {0} failed with {1}: {2}".format(
            current_utc, response.status_code, response.text
        )
    )
    return current_utc


def reset_clock(client):
    """Return the logical clock to its documented startup instant."""
    return set_clock(client, C.CLOCK_INITIAL_INSTANT)


# --- Tier 1: plans, firms, companies, users ------------------------------------------


def create_plan(client, **overrides):
    response = client.create_plan(f.create_plan_payload(**overrides), headers=PLATFORM_ADMIN)
    data = get_success_data(response)
    assert isinstance(data, dict) and data.get("id"), (
        "plan creation failed: {0}".format(response.text)
    )
    return data


def create_simple_start_plan(client, **overrides):
    response = client.create_plan(
        f.simple_start_plan_payload(**overrides), headers=PLATFORM_ADMIN
    )
    return get_success_data(response)


def create_essentials_plan(client, **overrides):
    response = client.create_plan(
        f.essentials_plan_payload(**overrides), headers=PLATFORM_ADMIN
    )
    return get_success_data(response)


def create_plus_plan(client, **overrides):
    response = client.create_plan(f.plus_plan_payload(**overrides), headers=PLATFORM_ADMIN)
    return get_success_data(response)


def create_advanced_plan(client, **overrides):
    response = client.create_plan(
        f.advanced_plan_payload(**overrides), headers=PLATFORM_ADMIN
    )
    return get_success_data(response)


def create_firm(client, **overrides):
    response = client.create_firm(f.create_firm_payload(**overrides), headers=PLATFORM_ADMIN)
    data = get_success_data(response)
    assert isinstance(data, dict) and data.get("id"), (
        "firm creation failed: {0}".format(response.text)
    )
    return data


def create_firm_user(client, firm_id, **overrides):
    response = client.create_firm_user(
        firm_id, f.create_firm_user_payload(firm_id, **overrides), headers=PLATFORM_ADMIN
    )
    return get_success_data(response)


def create_company(client, plan_id, **overrides):
    response = client.create_company(
        f.create_company_payload(plan_id, **overrides), headers=PLATFORM_ADMIN
    )
    data = get_success_data(response)
    assert isinstance(data, dict) and data.get("id"), (
        "company creation failed: {0}".format(response.text)
    )
    return data


def create_company_user(client, company_id, actor_headers=None, **overrides):
    """Invite a CompanyUser.  ``actor_headers`` may be PLATFORM_ADMIN (initial
    onboarding) or a built CompanyUser header set for subsequent invites."""
    if actor_headers is None:
        actor_headers = PLATFORM_ADMIN
    response = client.create_company_user(
        company_id, f.create_company_user_payload(company_id, **overrides),
        headers=actor_headers,
    )
    data = get_success_data(response)
    assert isinstance(data, dict) and data.get("id"), (
        "user invite failed: {0}".format(response.text)
    )
    return data


def create_primary_admin(client, company_id, **overrides):
    """Create the initial PRIMARY_ADMIN (PlatformAdmin does the onboarding)."""
    response = client.create_company_user(
        company_id, f.primary_admin_payload(company_id, **overrides),
        headers=PLATFORM_ADMIN,
    )
    data = get_success_data(response)
    assert isinstance(data, dict) and data.get("id"), (
        "primary admin invite failed: {0}".format(response.text)
    )
    return data


def accept_user(client, company_id, user_id):
    """The invitee accepts their own invitation (INVITED -> ACTIVE)."""
    response = client.accept_company_user(
        company_id, user_id, headers=make_company_user_headers(user_id)
    )
    return get_success_data(response)


def get_subscription(client, company_id):
    response = client.get_subscription(company_id, headers=PLATFORM_ADMIN)
    return get_success_data(response)


def activate_subscription(client, company_id, admin_id):
    """Activate the trial.  Returns the activated Subscription body."""
    response = client.activate_subscription(
        company_id,
        f.activate_subscription_payload(),
        headers=make_company_user_headers(admin_id),
    )
    return get_success_data(response)


# --- Tier 2: company with active subscription (most common composite) -----------------


def setup_company_with_active_subscription(
    client, plan_id=None, legal_name="Alpha Corp", **plan_overrides
):
    """Plan (default PLUS) + company + PRIMARY_ADMIN accepted + subscription ACTIVE.

    Returns dict with keys: plan, company, admin, admin_headers, subscription.
    """
    if plan_id is None:
        plan = create_plus_plan(client, **plan_overrides)
        plan_id = plan["id"]
    else:
        plan = client.get_plan(plan_id, headers=PLATFORM_ADMIN)
        plan = get_success_data(plan)
    company = create_company(client, plan_id, legal_name=legal_name)
    admin = create_primary_admin(client, company["id"])
    accept_user(client, company["id"], admin["id"])
    admin_headers = make_company_user_headers(admin["id"])
    subscription = activate_subscription(client, company["id"], admin["id"])
    return {
        "plan": plan,
        "company": company,
        "admin": admin,
        "admin_headers": admin_headers,
        "subscription": subscription,
    }


# --- Tier 2b: payroll -----------------------------------------------------------------


def add_payroll(client, company_id, admin_id, service_level="SELF_SERVICE"):
    """Attach a payroll add-on to the company's subscription."""
    subscription = get_subscription(client, company_id)
    response = client.create_payroll(
        company_id,
        f.create_payroll_payload(subscription["id"], service_level=service_level),
        headers=make_company_user_headers(admin_id),
    )
    return get_success_data(response)


def add_employee(client, company_id, admin_id, payroll_addon_id, **overrides):
    response = client.create_payroll_employee(
        company_id,
        f.create_payroll_employee_payload(payroll_addon_id, **overrides),
        headers=make_company_user_headers(admin_id),
    )
    return get_success_data(response)


# --- Tier 2c: bank connections, categories, rules --------------------------------------


def add_bank_connection(client, company_id, admin_id, **overrides):
    """Create + authorize a bank connection.  Returns the ACTIVE body."""
    response = client.create_bank_connection(
        company_id,
        f.create_bank_connection_payload(company_id, **overrides),
        headers=make_company_user_headers(admin_id),
    )
    connection = get_success_data(response)
    auth = client.authorize_bank_connection(
        company_id, connection["id"], headers=make_company_user_headers(admin_id)
    )
    return get_success_data(auth)


def add_category(client, company_id, admin_id, **overrides):
    response = client.create_category(
        company_id,
        f.create_category_payload(company_id, **overrides),
        headers=make_company_user_headers(admin_id),
    )
    return get_success_data(response)


def add_rule(client, company_id, admin_id, category_id, **overrides):
    response = client.create_categorization_rule(
        company_id,
        f.create_rule_payload(company_id, category_id, **overrides),
        headers=make_company_user_headers(admin_id),
    )
    return get_success_data(response)


def ingest_txn(client, company_id, connection_id, **overrides):
    """Ingest a raw bank transaction (test-driver, PlatformAdmin)."""
    response = client.ingest_bank_transaction(
        company_id,
        connection_id,
        f.ingest_txn_payload(**overrides),
        headers=PLATFORM_ADMIN,
    )
    return get_success_data(response)


# --- Tier 2d: billing transfer ---------------------------------------------------------


def create_firm_with_admin(client, **firm_overrides):
    """Create a firm plus a firm-admin AccountantUser.  Returns (firm, firm_admin)."""
    firm = create_firm(client, **firm_overrides)
    firm_admin = create_firm_user(
        client, firm["id"], is_firm_admin=True,
        full_name="Firm Admin", email="admin@{0}.example".format(firm["id"][:8]),
    )
    return firm, firm_admin


def initiate_transfer_to_firm(client, company_id, subscription_id, firm_id, firm_admin_id):
    """Firm admin initiates a CLIENT -> FIRM billing transfer."""
    response = client.create_billing_transfer(
        company_id,
        f.create_billing_transfer_payload(
            company_id, subscription_id, firm_id, to_owner="FIRM"
        ),
        headers=make_accountant_user_headers(firm_admin_id),
    )
    return get_success_data(response)


def client_accept_transfer(client, company_id, transfer_id, admin_id, expected_version):
    response = client.client_accept_billing_transfer(
        company_id,
        transfer_id,
        f.accept_transfer_payload(expected_version),
        headers=make_company_user_headers(admin_id),
    )
    return get_success_data(response)


def transfer_billing_to_firm(client, scenario, firm, firm_admin):
    """Full hand-off: initiate + client accept.  Returns the COMPLETED transfer."""
    company = scenario["company"]
    admin = scenario["admin"]
    subscription = scenario["subscription"]
    transfer = initiate_transfer_to_firm(
        client, company["id"], subscription["id"], firm["id"], firm_admin["id"]
    )
    # Subscription version may have advanced (e.g. activation).  Re-read.
    current = get_subscription(client, company["id"])
    return client_accept_transfer(
        client, company["id"], transfer["id"], admin["id"], current["version"]
    )


# --- Tier 2e: access grants --------------------------------------------------------------


def issue_and_accept_grant(client, company_id, admin_id, firm_id, accountant_user_id,
                            access_level="FULL_BOOKKEEPING"):
    """Company issues grant; the advisor accepts it.  Returns the ACTIVE grant."""
    response = client.create_access_grant(
        company_id,
        f.create_access_grant_payload(
            company_id, accountant_user_id, firm_id, access_level=access_level
        ),
        headers=make_company_user_headers(admin_id),
    )
    grant = get_success_data(response)
    accepted = client.accept_access_grant(
        firm_id, grant["id"], headers=make_accountant_user_headers(accountant_user_id)
    )
    return get_success_data(accepted)


# --- Tier 3: invoicing and reconciliation -----------------------------------------------


def issue_invoice_now(client, company_id, subscription_id):
    """Issue the subscription's current DRAFT invoice and return the ISSUED body.

    PRD: "An invoice is born DRAFT" and the platform operator issues it via
    POST /api/companies/{id}/invoices/{iid}/issue.  The system generates each
    period's DRAFT on the billing date; activation also creates its first
    invoice in DRAFT.  Locate the latest DRAFT for the subscription and issue
    it by id.
    """
    listed = client.list_company_invoices(
        company_id,
        headers=PLATFORM_ADMIN,
        params={"subscription_id": subscription_id, "limit": 100},
    )
    invoices = get_success_data(listed)
    invoices = invoices["items"] if isinstance(invoices, dict) and "items" in invoices else invoices
    invoices = list(invoices)
    drafts = [i for i in invoices if i["invoice_status"] == "DRAFT"]
    assert drafts, (
        "no DRAFT invoice found for subscription {0}".format(subscription_id)
    )
    response = client.issue_invoice(
        company_id, drafts[-1]["id"], headers=PLATFORM_ADMIN
    )
    return get_success_data(response)


def issue_and_pay_invoice(client, company_id, subscription_id, admin_id):
    invoice = issue_invoice_now(client, company_id, subscription_id)
    response = client.pay_invoice(
        company_id, invoice["id"], headers=make_company_user_headers(admin_id)
    )
    return get_success_data(response)


def start_recon(client, company_id, admin_id, connection_id, **overrides):
    """Create + start a reconciliation.  Returns the IN_PROGRESS body."""
    response = client.create_reconciliation(
        company_id,
        f.create_reconciliation_payload(company_id, connection_id, **overrides),
        headers=make_company_user_headers(admin_id),
    )
    recon = get_success_data(response)
    started = client.start_reconciliation(
        company_id, recon["id"], headers=make_company_user_headers(admin_id)
    )
    return get_success_data(started)


def complete_recon(client, company_id, admin_id, connection_id, **overrides):
    """Create + start + complete (requires difference == 0)."""
    recon = start_recon(client, company_id, admin_id, connection_id, **overrides)
    completed = client.complete_reconciliation(
        company_id, recon["id"], headers=make_company_user_headers(admin_id)
    )
    return get_success_data(completed)


# --- Tier 4: suspend a subscription via invoice aging -------------------------------------


def drive_subscription_to_suspended(client, company_id, admin_id, subscription_id):
    """Issue the current-period invoice, then age the clock so the
    subscription reaches SUSPENDED (invoice ISSUED 5 days past period_end ->
    PAST_DUE; 30+ days PAST_DUE -> SUSPENDED).

    Returns the suspended Subscription body and the aged invoice.
    """
    invoice = issue_invoice_now(client, company_id, subscription_id)
    # 36 days past boot: 5 days past period_end -> PAST_DUE; +30 -> SUSPENDED.
    set_clock(client, "2026-11-07T00:00:00Z")
    subscription = get_subscription(client, company_id)
    assert subscription["lifecycle_status"] == "SUSPENDED", (
        "expected SUSPENDED, got {0}".format(subscription["lifecycle_status"])
    )
    return subscription, invoice


# --- Tier 5: cancel / final-state -------------------------------------------------------


def cancel_subscription(client, company_id, admin_id, reason="test"):
    response = client.cancel_subscription(
        company_id,
        f.cancel_subscription_payload(reason=reason),
        headers=make_company_user_headers(admin_id),
    )
    return get_success_data(response)
