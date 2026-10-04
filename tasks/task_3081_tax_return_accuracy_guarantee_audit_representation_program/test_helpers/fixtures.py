"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (each test runs against a freshly restarted, empty server). Setup
calls use get_success_data() so failures surface as clear setup errors.

Named case-manager identities: scoping is done with the scoper headers so the
SoD anchor (claim.scoped_by_user_id) is recorded; resolution is done with the
resolver headers, a different operator, which the segregation-of-duties rule
requires.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_agent_payload,
    create_assignment_payload,
    create_claim_payload,
    create_client_payload,
    create_escrow_payload,
    create_notice_payload,
    create_office_payload,
    create_poa_payload,
    create_preparer_payload,
    create_product_payload,
    create_quality_close_payload,
    create_remediation_payload,
    create_return_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
OM = TEST_USERS["office_manager_headers"]
CM = TEST_USERS["case_manager_headers"]
CM_SCOPER = TEST_USERS["case_manager_scoper_headers"]
CM_RESOLVER = TEST_USERS["case_manager_resolver_headers"]

# --- Shared window/poa defaults (kept clear of clock movements in recipes) ---
DEFAULT_WINDOW_START = "2026-11-02T00:00:00Z"
DEFAULT_WINDOW_END = "2026-12-02T00:00:00Z"
DEFAULT_POA_EXPIRES = "2027-06-01T00:00:00Z"


# ─── Tier 1: basic building blocks ──────────────────────────────────────────

def create_office(**overrides):
    return get_success_data(api_client.create_office(create_office_payload(**overrides), ADMIN))


def create_preparer(office_id, **overrides):
    return get_success_data(api_client.create_preparer(create_preparer_payload(office_id, **overrides), OM))


def create_client(**overrides):
    return get_success_data(api_client.create_client(create_client_payload(**overrides), OM))


def create_agent(**overrides):
    return get_success_data(api_client.create_agent(create_agent_payload(**overrides), ADMIN))


def create_escrow(office_id, **overrides):
    return get_success_data(api_client.create_escrow(create_escrow_payload(office_id, **overrides), ADMIN))


def create_return(client_id, office_id, preparer_id, **overrides):
    return get_success_data(
        api_client.create_return(create_return_payload(client_id, office_id, preparer_id, **overrides), OM)
    )


def file_return(return_id):
    return get_success_data(api_client.file_return(return_id, OM))


def create_product(return_id, tier="STANDARD"):
    return get_success_data(api_client.create_product(create_product_payload(return_id, tier=tier), OM))


def create_notice(return_id, **overrides):
    return get_success_data(api_client.create_notice(create_notice_payload(return_id, **overrides), CM))


def open_claim(return_id, notice_id):
    """Open a claim, fetching the return's current version for the OCC field.
    Returns the claim as created (TRIAGE)."""
    ret = get_success_data(api_client.get_return(return_id, CM))
    payload = create_claim_payload(return_id, notice_id, ret["version"])
    return get_success_data(api_client.create_claim(payload, CM))


def scope_claim_in_scope(claim_id, error_attribution="PREPARER_ERROR"):
    """Scope a claim IN_SCOPE as the scoper manager (records the SoD anchor)."""
    return get_success_data(
        api_client.scope_claim(claim_id, {"scope": "IN_SCOPE", "error_attribution": error_attribution}, CM_SCOPER)
    )


def assign_agent(claim_id, agent_id, window_start=DEFAULT_WINDOW_START, window_end=DEFAULT_WINDOW_END):
    """Assign an agent; returns (assignment, claim-after-assign)."""
    asg = get_success_data(
        api_client.assign_claim(
            claim_id,
            create_assignment_payload(agent_id, window_start=window_start, window_end=window_end),
            CM,
        )
    )
    claim = get_success_data(api_client.get_claim(claim_id, CM))
    return asg, claim


def draft_and_execute_poa(claim_id, agent_id, expires_at=DEFAULT_POA_EXPIRES):
    """Draft a POA on the claim and execute it with the fresh draft version.
    Returns (poa_after_execute, claim_after_execute)."""
    poa = get_success_data(api_client.create_poa(claim_id, create_poa_payload(agent_id, expires_at=expires_at), CM))
    get_success_data(api_client.execute_poa(claim_id, {"expected_poa_version": poa["version"]}, CM))
    poa_after = get_success_data(api_client.get_poa(poa["id"], CM))
    claim = get_success_data(api_client.get_claim(claim_id, CM))
    return poa_after, claim


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def pay_notice(notice_id):
    return get_success_data(api_client.pay_notice(notice_id, OM))


def quality_close(office_id, **overrides):
    return get_success_data(api_client.quality_close_office(office_id, create_quality_close_payload(**overrides), OM))


def resolve_claim(claim_id):
    """Resolve as the resolver manager (different operator than the scoper)."""
    return get_success_data(api_client.resolve_claim(claim_id, CM_RESOLVER))


# ─── Tier 2: scenario composites ────────────────────────────────────────────

def setup_office_preparer_client(office_overrides=None, preparer_overrides=None, client_overrides=None):
    """Office + one ASSOCIATE preparer + one client. Returns (office, preparer, client)."""
    office = create_office(**(office_overrides or {}))
    preparer = create_preparer(office["id"], **(preparer_overrides or {}))
    client = create_client(**(client_overrides or {}))
    return office, preparer, client


def setup_filed_return(components=None, product_tier=None, **kwargs):
    """Office + preparer + client + a FILED return; optionally a product.
    Returns dict with office, preparer, client, tax_return, and product (or None)."""
    office, preparer, client = setup_office_preparer_client(
        office_overrides=kwargs.get("office_overrides"),
        preparer_overrides=kwargs.get("preparer_overrides"),
        client_overrides=kwargs.get("client_overrides"),
    )
    tax_return = create_return(
        client["id"], office["id"], preparer["id"], components=components or ["1040_SIMPLE"]
    )
    tax_return = file_return(tax_return["id"])
    product = create_product(tax_return["id"], tier=product_tier) if product_tier else None
    return {
        "office": office,
        "preparer": preparer,
        "client": client,
        "tax_return": tax_return,
        "product": product,
    }


def setup_claim_in_triage(components=None, product_tier="STANDARD", notice_overrides=None,
                          with_escrow=False, **kwargs):
    """Full intake chain up to a claim in TRIAGE with a linked OPEN notice.
    Returns dict with office, preparer, client, tax_return, product, notice, claim,
    and escrow (or None)."""
    ctx = setup_filed_return(components=components, product_tier=product_tier, **kwargs)
    escrow = create_escrow(ctx["office"]["id"]) if with_escrow else None
    notice = create_notice(ctx["tax_return"]["id"], **(notice_overrides or {}))
    claim = open_claim(ctx["tax_return"]["id"], notice["id"])
    ctx.update({"notice": notice, "claim": claim, "escrow": escrow})
    return ctx


def setup_claim_in_representing(components=None, product_tier="STANDARD", notice_overrides=None,
                                error_attribution="PREPARER_ERROR", with_escrow=False,
                                agent_overrides=None, window_start=DEFAULT_WINDOW_START,
                                window_end=DEFAULT_WINDOW_END, poa_expires_at=DEFAULT_POA_EXPIRES,
                                **kwargs):
    """Full chain through TRIAGE -> SCOPE_CONFIRMED -> ASSIGNED -> REPRESENTING.
    Scoping is performed by the scoper manager, so resolution must use the resolver.
    Returns dict with office, preparer, client, tax_return, product, notice, claim,
    agent, assignment, poa, escrow (or None)."""
    ctx = setup_claim_in_triage(
        components=components, product_tier=product_tier, notice_overrides=notice_overrides,
        with_escrow=with_escrow, **kwargs,
    )
    agent = create_agent(**(agent_overrides or {}))
    scope_claim_in_scope(ctx["claim"]["id"], error_attribution=error_attribution)
    assignment, _ = assign_agent(ctx["claim"]["id"], agent["id"], window_start, window_end)
    poa, claim = draft_and_execute_poa(ctx["claim"]["id"], agent["id"], expires_at=poa_expires_at)
    ctx.update({"agent": agent, "assignment": assignment, "poa": poa, "claim": claim})
    return ctx
