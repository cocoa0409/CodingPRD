"""Composite setup helpers.

The interesting claims all require the system to be in a specific state that
takes several calls to reach - an approved segment, a READY report, an APPROVED
grant, an OPEN cycle with a PLANNED deliverable. These helpers build that state
through the public API and return the created resources, so tests can focus on
the behavior under assertion.

Setup calls go through ``get_success_data`` so a broken precondition fails with
a clear "Setup failed" message instead of a confusing assertion error.

Ownership rule: every supplier-side write is made with
``make_supplier_analyst_headers(account_id)`` carrying the real account id,
because supplier calls are ownership-gated on ``X-User-ID``.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .constants import TEST_DEFAULTS
from .test_users import TEST_USERS, make_data_steward_headers, make_supplier_analyst_headers

ADMIN = TEST_USERS["retailer_admin_headers"]
MANAGER = TEST_USERS["category_manager_headers"]
SCIENTIST = TEST_USERS["insights_scientist_headers"]
STEWARD = TEST_USERS["data_steward_headers"]


# ── Tier 1: account + contract setup ─────────────────────────────────────────


def create_account(api, name: str = "Test Supplier Co", region: str = "NW") -> Dict[str, Any]:
    """Create a supplier account. Returns the account object."""
    resp = api.create_supplier_account(
        factories.supplier_account_payload(account_name=name, region=region), ADMIN
    )
    return get_success_data(resp)


def create_contract(
    api,
    account_id: str,
    tier: str = "TIER_CATEGORY",
    report_credit_allowance: int = 10,
    activation_budget_cents: int = 100000,
    redistribution_allowed: bool = True,
    modeled_derivation_allowed: bool = True,
) -> Dict[str, Any]:
    """Create an ACTIVE subscription contract under an account."""
    resp = api.create_subscription_contract(
        account_id,
        factories.subscription_contract_payload(
            tier=tier,
            report_credit_allowance=report_credit_allowance,
            activation_budget_cents=activation_budget_cents,
            redistribution_allowed=redistribution_allowed,
            modeled_derivation_allowed=modeled_derivation_allowed,
        ),
        ADMIN,
    )
    return get_success_data(resp)


def add_scope(api, contract_id: str, category_code: str = "SNACKS", brand_codes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Add a category scope to a contract."""
    resp = api.add_category_scope(
        contract_id,
        factories.category_scope_payload(
            category_code=category_code,
            brand_codes=list(brand_codes) if brand_codes is not None else ["ACME"],
        ),
        ADMIN,
    )
    return get_success_data(resp)


def account_with_contract(
    api,
    name: str = "Test Supplier Co",
    tier: str = "TIER_CATEGORY",
    report_credit_allowance: int = 10,
    activation_budget_cents: int = 100000,
    redistribution_allowed: bool = True,
    modeled_derivation_allowed: bool = True,
    scope_category: Optional[str] = None,
    scope_brands: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Account + ACTIVE contract (+ optional category scope).

    Returns {"account", "contract", "analyst_headers", "scope" (or None)}.
    """
    account = create_account(api, name=name)
    contract = create_contract(
        api,
        account["id"],
        tier=tier,
        report_credit_allowance=report_credit_allowance,
        activation_budget_cents=activation_budget_cents,
        redistribution_allowed=redistribution_allowed,
        modeled_derivation_allowed=modeled_derivation_allowed,
    )
    scope = None
    if scope_category:
        scope = add_scope(api, contract["id"], category_code=scope_category, brand_codes=scope_brands)
    return {
        "account": account,
        "contract": contract,
        "analyst_headers": make_supplier_analyst_headers(account["id"]),
        "scope": scope,
    }


# ── Tier 2: panel ingest ─────────────────────────────────────────────────────


def make_households(count: int, prefix: str, **shared) -> List[Dict[str, Any]]:
    """Build ``count`` household entries with refs ``{prefix}01..{prefix}{count}``.

    ``shared`` overrides apply to every entry (category_codes, brand_metrics...).
    """
    return [factories.household_payload(f"{prefix}{i:02d}", **shared) for i in range(1, count + 1)]


def ingest_households(api, households: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Bulk-ingest households; returns the response data (ingested_count, rejected)."""
    resp = api.ingest_households(households, ADMIN)
    return get_success_data(resp)


def ingest_category_households(api, count: int, prefix: str, category_code: str = "SNACKS", **shared) -> Dict[str, Any]:
    """Ingest ``count`` households all transacting in one category."""
    return ingest_households(api, make_households(count, prefix, category_codes=[category_code], **shared))


# ── Tier 3: insight reports ──────────────────────────────────────────────────


def create_report(
    api,
    contract_id: str,
    analyst_headers: Dict[str, str],
    report_type: str = "CATEGORY",
    category_code: str = "SNACKS",
    **overrides,
) -> Dict[str, Any]:
    """Request an insight report; returns the REQUESTED report."""
    resp = api.create_insight_report(
        factories.insight_report_payload(
            contract_id, report_type=report_type, category_code=category_code, **overrides
        ),
        analyst_headers,
    )
    return get_success_data(resp)


def create_ready_report(
    api,
    contract_id: str,
    analyst_headers: Dict[str, str],
    report_type: str = "CATEGORY",
    category_code: str = "SNACKS",
    **overrides,
) -> Dict[str, Any]:
    """Create a report and generate it to READY.

    Requires the panel to already hold at least the minimum cell population for
    the category; the caller owns that precondition.
    """
    report = create_report(
        api, contract_id, analyst_headers, report_type=report_type, category_code=category_code, **overrides
    )
    resp = api.generate_report(report["id"], analyst_headers)
    generated = get_success_data(resp)
    assert generated["status"] == "READY", (
        f"Setup failed: expected READY report, got {generated['status']}"
    )
    return generated


# ── Tier 4: segments and activations ─────────────────────────────────────────


def create_segment(
    api,
    contract_id: str,
    analyst_headers: Dict[str, str],
    category_code: str = "SNACKS",
    segment_name: str = "Test Segment",
    **criteria,
) -> Dict[str, Any]:
    """Create a DRAFT segment with computed size."""
    resp = api.create_segment(
        factories.segment_payload(
            contract_id, segment_name=segment_name, category_code=category_code, **criteria
        ),
        analyst_headers,
    )
    return get_success_data(resp)


def submit_segment(api, segment_id: str, analyst_headers: Dict[str, str]) -> Dict[str, Any]:
    resp = api.submit_segment(segment_id, analyst_headers)
    return get_success_data(resp)


def approve_segment(api, segment_id: str, steward_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    resp = api.approve_segment(segment_id, steward_headers or STEWARD)
    return get_success_data(resp)


def create_approved_segment(
    api,
    contract_id: str,
    analyst_headers: Dict[str, str],
    category_code: str = "SNACKS",
    steward_headers: Optional[Dict[str, str]] = None,
    **criteria,
) -> Dict[str, Any]:
    """Segment walked DRAFT -> PENDING_APPROVAL -> APPROVED. Returns it."""
    segment = create_segment(api, contract_id, analyst_headers, category_code=category_code, **criteria)
    submitted = submit_segment(api, segment["id"], analyst_headers)
    assert submitted["status"] == "PENDING_APPROVAL", (
        f"Setup failed: submit landed in {submitted['status']}"
    )
    approved = approve_segment(api, segment["id"], steward_headers)
    assert approved["status"] == "APPROVED", f"Setup failed: approve landed in {approved['status']}"
    return approved


def create_activation(
    api,
    segment: Dict[str, Any],
    analyst_headers: Dict[str, str],
    channels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a PENDING activation on an APPROVED segment (OCC on its version)."""
    resp = api.create_activation(
        segment["id"],
        factories.activation_payload(segment["version"], channels=channels or ["COUPON"]),
        analyst_headers,
    )
    return get_success_data(resp)


# ── Tier 5: clean-room grants ────────────────────────────────────────────────


def create_grant(
    api,
    account_id: str,
    analyst_headers: Optional[Dict[str, str]] = None,
    valid_from: str = "2026-09-01T00:00:00Z",
    valid_until: str = "2026-12-01T00:00:00Z",
    query_budget_total: int = 100,
) -> Dict[str, Any]:
    """Request a clean-room grant; returns the REQUESTED grant."""
    headers = analyst_headers or make_supplier_analyst_headers(account_id)
    resp = api.create_grant(
        factories.grant_payload(
            account_id,
            valid_from=valid_from,
            valid_until=valid_until,
            query_budget_total=query_budget_total,
        ),
        headers,
    )
    return get_success_data(resp)


def create_approved_grant(
    api,
    account_id: str,
    steward_user_id: str = "steward-approver-1",
    **overrides,
) -> Dict[str, Any]:
    """Grant walked REQUESTED -> APPROVED by a steward distinct from the requester."""
    grant = create_grant(api, account_id, **overrides)
    resp = api.approve_grant(grant["id"], make_data_steward_headers(steward_user_id))
    approved = get_success_data(resp)
    assert approved["status"] == "APPROVED", f"Setup failed: approve landed in {approved['status']}"
    return approved


def read_grant(api, grant_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_grant(grant_id, STEWARD))


def read_contract(api, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, ADMIN))


# ── Tier 6: cycles and deliverables ──────────────────────────────────────────


def create_cycle(
    api,
    category_code: str = "SNACKS",
    window_start: str = "2026-09-20",
    window_end: str = "2026-09-25",
) -> Dict[str, Any]:
    """Schedule a line review cycle (born SCHEDULED)."""
    resp = api.create_cycle(
        factories.cycle_payload(
            category_code=category_code, window_start=window_start, window_end=window_end
        ),
        MANAGER,
    )
    return get_success_data(resp)


def create_deliverable(
    api,
    cycle_id: str,
    contract_id: str,
    insight_report_id: str,
    due_at: str = "2026-09-15T00:00:00Z",
) -> Dict[str, Any]:
    """Plan a PLANNED deliverable inside a cycle."""
    resp = api.create_deliverable(
        cycle_id,
        factories.deliverable_payload(contract_id, insight_report_id, due_at=due_at),
        MANAGER,
    )
    return get_success_data(resp)


def read_cycle(api, cycle_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_cycle(cycle_id, MANAGER))


def list_cycle_deliverables(api, cycle_id: str) -> List[Dict[str, Any]]:
    resp = api.list_cycle_deliverables(cycle_id, MANAGER)
    return get_success_data(resp)


# ── Tier 7: incrementality studies ───────────────────────────────────────────


def create_study(
    api,
    brand_code: str = "ACME",
    category_code: str = "SNACKS",
    window_start: str = "2026-09-01",
    window_end: str = "2026-09-10",
) -> Dict[str, Any]:
    """Create a DRAFT incrementality study."""
    resp = api.create_study(
        factories.study_payload(
            brand_code=brand_code,
            category_code=category_code,
            window_start=window_start,
            window_end=window_end,
        ),
        SCIENTIST,
    )
    return get_success_data(resp)


def start_study(api, study_id: str) -> Dict[str, Any]:
    resp = api.start_study(study_id, SCIENTIST)
    return get_success_data(resp)


def read_study(api, study_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_study(study_id, SCIENTIST))


# ── Clock ────────────────────────────────────────────────────────────────────


def set_clock(api, to_iso8601: str) -> Dict[str, Any]:
    resp = api.set_clock(to_iso8601, ADMIN)
    return get_success_data(resp)
