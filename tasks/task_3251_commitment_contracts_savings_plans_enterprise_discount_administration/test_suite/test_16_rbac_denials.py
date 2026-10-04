"""Tests for RBAC denials: role authorization and entity-backed ownership."""
from test_helpers import (
    validate_error,
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    make_manager_headers,
    make_platform_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    ingest_usage,
    set_clock,
    ApiErrorId,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()
PLATFORM = make_platform_headers()


def test_finance_analyst_cannot_generate_invoices(api):
    """PRD section 2.1: "`OrgAdmin` — the customer-side organization
    administrator. It manages linked accounts (create, suspend, reactivate),
    enterprise agreements (create and all lifecycle transitions), discount tiers,
    commitment plans (purchase and terminate), invoices (generate, finalize,
    dispute, resolve-dispute, settle, void), and true-up charges (assess and
    bill)."
    PRD section 2.1: "A request whose role is recognized but not permitted for
    the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/finance_analyst_cannot_generate_invoices
    """
    org = create_org(name="Rb Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=100)
    resp = api.generate_invoice({"org_id": org["id"], "period_index": 0}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403


def test_org_admin_cannot_waive_trueup_segregation_of_duties(api):
    """PRD section 2.1: "`FinanceAnalyst` — the customer-side finance analyst. It
    owns private pricing amendments, renewal review (open and close), true-up
    waivers, and renewal forecasts. It is deliberately segregated from `OrgAdmin`
    on true-up: the analyst may waive a charge but may never assess or bill one."
    PRD section 3.8: "An `ASSESSED` charge may be billed by an `OrgAdmin`, moving
    it to `BILLED`, or waived by a `FinanceAnalyst` — who supplies a `reason` —
    moving it to `WAIVED`; both transitions recompute `accrued_trueup_cents`, and
    waived charges drop out of that sum."

    Design: Corner/rbac/org_admin_cannot_waive_trueup_segregation_of_duties
    """
    org = create_org(name="So Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    agr = create_active_agreement(
        org["id"],
        tiers=[{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}],
        committed_spend_cents=10000,
        term_start="2026-09-01T00:00:00Z", term_end="2026-10-01T00:00:00Z",
    )
    acct = create_linked_account(org["id"], name="a1", external_ref="e1")
    ingest_usage(acct["id"], usage_hour_start="2026-09-01T00:00:00Z",
                 list_price_cents=6000)
    set_clock("2026-10-01T00:00:00Z")
    validate_success(api.run_period_close(org["id"], PLATFORM))
    tu = validate_success(
        api.assess_trueup({"agreement_id": agr["id"]}, ADMIN), expected_status=201
    )
    resp = api.waive_trueup_charge(tu["id"], {"reason": "goodwill"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403
    after_denial = validate_success(api.get_trueup_charge(tu["id"], ADMIN))
    assert after_denial["status"] == "ASSESSED"
    data = validate_success(
        api.waive_trueup_charge(tu["id"], {"reason": "goodwill"}, FINANCE)
    )
    assert data["status"] == "WAIVED"


def test_linked_account_manager_cannot_ingest_for_other_account(api):
    """PRD section 2.1: "A `LinkedAccountManager` may ingest usage only for its
    own account — that is, only when the payload's `linked_account_id` equals
    `X-User-ID` — and any attempt to ingest for another account is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/linked_account_manager_cannot_ingest_for_other_account
    """
    org = create_org(name="Ow Org", max_hourly_commitment_cents=1000,
                     capacity_quota_units=100)
    a1 = create_linked_account(org["id"], name="a1", external_ref="e1")
    a2 = create_linked_account(org["id"], name="a2", external_ref="e2")
    resp = api.create_usage_record(
        {"linked_account_id": a2["id"], "service_family": "COMPUTE",
         "usage_hour_start": "2026-09-01T00:00:00Z", "list_price_cents": 100},
        make_manager_headers(a1["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert resp.status_code == 403


def test_missing_role_header_unauthenticated(api):
    """PRD section 2.1: "Every request carries two headers: `X-User-ID`,
    identifying the acting principal, and `X-User-Role`, naming the role under
    which the principal acts. A request missing either header, or presenting a
    role value that is not one of the declared roles below, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    resp = api.list_billing_orgs(headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
    assert resp.status_code == 401
