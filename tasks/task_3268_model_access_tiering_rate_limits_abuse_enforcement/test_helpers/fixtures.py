"""Composite setup helpers.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted server). Setup calls use
get_success_data() so failures surface as clear setup errors.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT_UTC
from .factories import (
    create_abuse_case_payload,
    create_enterprise_agreement_payload,
    create_invoice_payload,
    create_model_version_payload,
    create_organization_payload,
    create_payment_event_payload,
    create_queued_request_payload,
    create_safety_evaluation_payload,
    create_usage_record_payload,
)
from .test_users import (
    TEST_USERS,
    make_organization_admin_headers,
    make_trust_analyst_headers,
    make_trust_lead_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BILLING = TEST_USERS["billing_contact_headers"]
ANALYST = TEST_USERS["trust_analyst_headers"]
LEAD = TEST_USERS["trust_lead_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

def set_clock(current_utc: str = CLOCK_DEFAULT_UTC):
    """Set the logical clock (PlatformAdmin-only test-driving endpoint)."""
    resp = api_client.set_clock({"current_utc": current_utc}, ADMIN)
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_organization(legal_name: str = "Test Organization", **overrides) -> dict:
    resp = api_client.create_organization(
        create_organization_payload(legal_name=legal_name, **overrides), ADMIN
    )
    return get_success_data(resp)


def create_settled_payment(organization_id: str, amount_cents: int = 1000000,
                           kind: str = "PREPAID_TOPUP") -> dict:
    """Create a payment event and settle it. Returns the settled payment."""
    resp = api_client.create_payment_event(
        create_payment_event_payload(organization_id, kind=kind, amount_cents=amount_cents),
        ADMIN,
    )
    payment = get_success_data(resp)
    resp = api_client.settle_payment_event(payment["id"], ADMIN)
    return get_success_data(resp)


def create_pending_payment(organization_id: str, amount_cents: int = 1000000,
                           kind: str = "PREPAID_TOPUP") -> dict:
    resp = api_client.create_payment_event(
        create_payment_event_payload(organization_id, kind=kind, amount_cents=amount_cents),
        ADMIN,
    )
    return get_success_data(resp)


def create_and_activate_organization(legal_name: str = "Test Organization",
                                     topup_cents: int = 1000000) -> dict:
    """Create an organization, settle one payment, activate it. Returns the org."""
    org = create_organization(legal_name=legal_name)
    create_settled_payment(org["id"], amount_cents=topup_cents)
    resp = api_client.activate_organization(org["id"], ADMIN)
    return get_success_data(resp)


def create_active_model_version(**overrides) -> dict:
    """Register a model version and drive it DRAFT -> GATED -> ACTIVE via a
    passing STANDARD safety verdict (score 0.80 >= 0.70).

    Segregation of duties: the opener (TrustAnalyst) and the verdict lead
    (TrustLead) are distinct users.
    """
    resp = api_client.create_model_version(create_model_version_payload(**overrides), ADMIN)
    mv = get_success_data(resp)
    resp = api_client.create_safety_evaluation(
        mv["id"], create_safety_evaluation_payload(capability_class="STANDARD"),
        make_trust_analyst_headers("fixture-analyst"),
    )
    evaluation = get_success_data(resp)
    resp = api_client.submit_safety_verdict(
        evaluation["id"], {"score": 0.80}, make_trust_lead_headers("fixture-lead")
    )
    get_success_data(resp)
    resp = api_client.get_model_version(mv["id"], ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def setup_org_with_model(legal_name: str = "Fixture Org", **model_overrides):
    """ACTIVE organization + ACTIVE model version. Returns (org, model)."""
    org = create_and_activate_organization(legal_name=legal_name)
    mv = create_active_model_version(**model_overrides)
    return org, mv


def create_enterprise_agreement(organization_id: str, **overrides) -> dict:
    resp = api_client.create_enterprise_agreement(
        create_enterprise_agreement_payload(organization_id, **overrides), ADMIN
    )
    return get_success_data(resp)


def setup_enterprise_org(legal_name: str = "Enterprise Org", committed_tpm: int = 10000,
                         **agreement_overrides):
    """ACTIVE organization with a countersigned (ACTIVE) enterprise agreement.
    Returns (org, agreement)."""
    org = create_and_activate_organization(legal_name=legal_name)
    agreement = create_enterprise_agreement(
        org["id"], committed_tpm=committed_tpm, **agreement_overrides
    )
    resp = api_client.countersign_enterprise_agreement(agreement["id"], ADMIN)
    agreement = get_success_data(resp)
    resp = api_client.get_organization(org["id"], ADMIN)
    org = get_success_data(resp)
    return org, agreement


# ---------------------------------------------------------------------------
# Tier 3: enforcement lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_claimed_case(organization_id: str, severity: str = "MEDIUM",
                        analyst_id: str = "fixture-analyst"):
    """Create a MANUAL abuse case and claim it. Returns (case, case_version)."""
    resp = api_client.create_abuse_case(
        create_abuse_case_payload(organization_id, severity=severity),
        make_trust_analyst_headers(analyst_id),
    )
    case = get_success_data(resp)
    resp = api_client.claim_abuse_case(case["id"], make_trust_analyst_headers(analyst_id))
    case = get_success_data(resp)
    return case, case["version"]


def issue_action(case_id: str, case_version: int, action_type: str,
                 issuer_id: str = "fixture-analyst", role: str = "analyst") -> dict:
    """Issue a graduated action against a claimed case. Returns the action."""
    headers = (
        make_trust_analyst_headers(issuer_id)
        if role == "analyst"
        else make_trust_lead_headers(issuer_id)
    )
    resp = api_client.create_abuse_action(
        case_id,
        {"action_type": action_type, "expected_abuse_case_version": case_version},
        headers,
    )
    return get_success_data(resp)


def setup_restricted_org(legal_name: str = "Restricted Org", severity: str = "HIGH"):
    """ACTIVE organization moved to RESTRICTED via a claimed case + RESTRICT
    action. Returns (org, case)."""
    org = create_and_activate_organization(legal_name=legal_name)
    case, case_v = create_claimed_case(org["id"], severity=severity)
    issue_action(case["id"], case_v, "RESTRICT")
    resp = api_client.get_organization(org["id"], ADMIN)
    return get_success_data(resp), case


def setup_org_with_pending_appeal(legal_name: str = "Appeal Org", severity: str = "HIGH",
                                  analyst_id: str = "fixture-analyst"):
    """RESTRICTED organization with a PENDING appeal filed by its
    OrganizationAdmin. Returns (org, case, appeal)."""
    org, case = setup_restricted_org(legal_name=legal_name, severity=severity)
    # Re-claim info: setup_restricted_org issued the action under the default
    # analyst id; capture the appeal under the org's own admin identity.
    resp = api_client.create_appeal(
        {"abuse_case_id": case["id"]}, make_organization_admin_headers(org["id"])
    )
    appeal = get_success_data(resp)
    return org, case, appeal


# ---------------------------------------------------------------------------
# Tier 4: accumulation / threshold targeting
# ---------------------------------------------------------------------------

def create_org_with_settled_spend(legal_name: str, settled_amounts: list) -> dict:
    """Create an organization and settle each amount in `settled_amounts` as a
    separate PREPAID_TOPUP. Returns the organization (freshly fetched)."""
    org = create_organization(legal_name=legal_name)
    for amount in settled_amounts:
        create_settled_payment(org["id"], amount_cents=amount)
    resp = api_client.get_organization(org["id"], ADMIN)
    return get_success_data(resp)


def fill_window_with_direct_usage(org_id: str, model_version_id: str,
                                  minute_window_start: str, requests: int,
                                  tokens_per_request: int = 1):
    """Admit a direct usage record of `requests` requests into a window."""
    resp = api_client.create_usage_record(
        create_usage_record_payload(
            org_id,
            model_version_id,
            minute_window_start=minute_window_start,
            requests=requests,
            input_tokens=tokens_per_request,
            output_tokens=0,
            cached_tokens=0,
        ),
        make_organization_admin_headers(org_id),
    )
    return get_success_data(resp)


def enqueue_request(org_id: str, model_version_id: str, requests_cost: int = 1,
                    tokens_cost: int = 100) -> dict:
    resp = api_client.create_queued_request(
        create_queued_request_payload(
            org_id, model_version_id, requests_cost=requests_cost, tokens_cost=tokens_cost
        ),
        make_organization_admin_headers(org_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 5: billing lifecycle
# ---------------------------------------------------------------------------

def create_draft_invoice(organization_id: str, lines=None, **overrides) -> dict:
    payload = create_invoice_payload(organization_id, **overrides)
    if lines is not None:
        payload["lines"] = lines
    resp = api_client.create_invoice(payload, BILLING)
    return get_success_data(resp)


def finalize_invoice(invoice_id: str) -> dict:
    resp = api_client.finalize_invoice(invoice_id, BILLING)
    return get_success_data(resp)
