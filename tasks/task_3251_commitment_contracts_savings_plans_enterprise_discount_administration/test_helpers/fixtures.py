"""Composite setup helpers for multi-step PRD scenarios.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the runner restarts the server before every test). Setup calls use
the lenient get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agreement_payload,
    create_billing_org_payload,
    create_discount_tier_payload,
    create_linked_account_payload,
    create_plan_payload,
    create_usage_payload,
    create_credit_grant_payload,
    create_amendment_payload,
    generate_invoice_payload,
)
from .test_users import (
    make_admin_headers,
    make_finance_headers,
    make_manager_headers,
    make_platform_headers,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()
PLATFORM = make_platform_headers()


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_org(**overrides):
    """Create a billing org. Returns the org dict."""
    resp = api_client.create_billing_org(create_billing_org_payload(**overrides), PLATFORM)
    return get_success_data(resp)


def create_linked_account(org_id, **overrides):
    resp = api_client.create_linked_account(
        create_linked_account_payload(org_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_agreement(org_id, **overrides):
    resp = api_client.create_enterprise_agreement(
        create_agreement_payload(org_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def add_tier(agreement_id, **overrides):
    resp = api_client.create_discount_tier(
        create_discount_tier_payload(agreement_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_active_agreement(org_id, tiers=None, **overrides):
    """Agreement with tiers, activated. Returns (agreement_dict, version)."""
    agr = create_agreement(org_id, **overrides)
    for t in (tiers if tiers is not None else [{"service_family": "COMPUTE", "threshold_cents": 0, "rate": 0.10}]):
        add_tier(agr["id"], **t)
    resp = api_client.activate_agreement(agr["id"], ADMIN)
    return get_success_data(resp)


def ingest_usage(account_id, **overrides):
    """Ingest one usage record as the account's own manager (ownership-gated)."""
    resp = api_client.create_usage_record(
        create_usage_payload(account_id, **overrides), make_manager_headers(account_id)
    )
    return get_success_data(resp)


def create_plan(org_id, agreement_id, **overrides):
    resp = api_client.create_commitment_plan(
        create_plan_payload(org_id, agreement_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_grant(org_id, **overrides):
    resp = api_client.create_credit_grant(
        create_credit_grant_payload(org_id, **overrides), PLATFORM
    )
    return get_success_data(resp)


def set_clock(to_iso8601):
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, PLATFORM)
    return get_success_data(resp)


def period_close(org_id):
    resp = api_client.run_period_close(org_id, PLATFORM)
    return get_success_data(resp)


def generate_invoice(org_id, period_index=0):
    resp = api_client.generate_invoice(
        generate_invoice_payload(org_id, period_index=period_index), ADMIN
    )
    return get_success_data(resp)


def get_agreement(agreement_id):
    resp = api_client.get_enterprise_agreement(agreement_id, ADMIN)
    return get_success_data(resp)


def get_invoice(invoice_id):
    resp = api_client.get_invoice(invoice_id, ADMIN)
    return get_success_data(resp)


def get_invoice_lines(invoice_id):
    resp = api_client.list_invoice_lines(invoice_id, ADMIN, params={"limit": 100})
    body = resp.json()
    return body["data"]


def get_credit_grant(grant_id):
    resp = api_client.get_credit_grant(grant_id, ADMIN)
    return get_success_data(resp)


def create_amendment(agreement_id, expected_version, **overrides):
    resp = api_client.create_pricing_amendment(
        create_amendment_payload(agreement_id, expected_version, **overrides), FINANCE
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy / basic scenarios
# ---------------------------------------------------------------------------

def setup_org_with_account(**org_overrides):
    """Org + one linked account. Returns (org, account)."""
    org = create_org(**org_overrides)
    acct = create_linked_account(org["id"])
    return org, acct


def setup_org_agreement_account(tiers=None, org_overrides=None, agr_overrides=None):
    """Org + ACTIVE agreement (with tiers) + one account.

    Returns (org, agreement, account).
    """
    org = create_org(**(org_overrides or {}))
    agr = create_active_agreement(org["id"], tiers=tiers, **(agr_overrides or {}))
    acct = create_linked_account(org["id"])
    return org, agr, acct


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_draft_invoice(org_id, account_id, usage_cents, period_index=0,
                        hour="2026-09-01T00:00:00Z", family="COMPUTE",
                        is_marketplace=None):
    """Ingest usage and generate a DRAFT invoice. Returns the invoice dict."""
    payload = dict(service_family=family, usage_hour_start=hour,
                   list_price_cents=usage_cents)
    if is_marketplace is not None:
        payload["is_marketplace"] = is_marketplace
    ingest_usage(account_id, **payload)
    return generate_invoice(org_id, period_index=period_index)


def setup_finalized_invoice(org_id, account_id, usage_cents, period_index=0, **kw):
    """DRAFT invoice generated and finalized. Returns invoice dict."""
    inv = setup_draft_invoice(org_id, account_id, usage_cents, period_index, **kw)
    resp = api_client.finalize_invoice(inv["id"], ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 4: threshold / accumulation targeting
# ---------------------------------------------------------------------------

def setup_expired_agreement(org_id, agr_id, term_end_instant="2026-10-01T00:00:00Z"):
    """Advance the logical clock past term_end and run a period close so the
    ACTIVE agreement auto-expires. Returns the refreshed agreement dict."""
    set_clock(term_end_instant)
    period_close(org_id)
    return get_agreement(agr_id)


def setup_closed_periods_with_usage(org_id, account_id, period_amounts):
    """For each amount in period_amounts, ingest usage in the current period
    then run a period close. After this helper, len(period_amounts) closed
    periods carry usage."""
    for i, amount in enumerate(period_amounts):
        hour = f"2026-09-01T{i:02d}:00:00Z"
        ingest_usage(account_id, usage_hour_start=hour, list_price_cents=amount)
        period_close(org_id)


# ---------------------------------------------------------------------------
# Tier 5: terminal-state scenarios
# ---------------------------------------------------------------------------

def setup_shortfall_assessed(org_overrides=None, committed=10000, usage_cents=6000,
                             term_end="2026-10-01T00:00:00Z"):
    """Org + ACTIVE agreement (committed, COMPUTE tier, term ending term_end)
    + account + usage billed into an invoice; clock past term; period close
    expires the agreement; assess runs. Returns dict with org, agr, acct,
    invoice, and the assess response data."""
    org, agr, acct = setup_org_agreement_account(
        org_overrides=org_overrides,
        agr_overrides={"committed_spend_cents": committed,
                       "term_end": term_end},
    )
    inv = setup_draft_invoice(org["id"], acct["id"], usage_cents)
    setup_expired_agreement(org["id"], agr["id"], term_end_instant=term_end)
    resp = api_client.assess_trueup({"agreement_id": agr["id"]}, ADMIN)
    return {
        "org": org, "agr": agr, "acct": acct, "invoice": inv,
        "assess_response": resp,
    }
