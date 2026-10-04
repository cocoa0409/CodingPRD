"""Composite setup helpers for multi-step API scenarios.

Every fixture builds its preconditions from scratch against an empty database,
using only PRD-declared endpoints. Setup calls use get_success_data() (lenient)
so failures surface as clear "Setup failed" assertion messages.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .factories import (
    create_affiliate_payload,
    create_work_payload,
    create_share_claim_payload,
    create_licensee_payload,
    issue_license_payload,
    create_performance_payload,
    create_cycle_payload,
)
from .test_users import (
    TEST_USERS,
    make_publisher_headers,
    make_songwriter_headers,
    make_licensee_headers,
)

__all__ = [
    "REGISTRAR", "LIC_ADMIN", "COURT", "DISTRIBUTOR", "FINANCE", "FINANCE2", "SYSADMIN",
    "DEFAULT_BROADCASTER_REVENUE", "DEFAULT_BROADCASTER_FEE",
    "_create_affiliate", "_create_work", "_create_claim", "_confirm_work",
    "_create_licensee", "_issue_license", "_ingest_performance", "_create_cycle",
    "_get_cycle", "_close_collection", "_list_cycle_statements",
    "create_publisher_affiliate", "create_songwriter_affiliate", "create_confirmed_work",
    "create_broadcaster_with_license", "setup_performance_ready", "setup_with_performance",
    "setup_calculating_cycle", "setup_distributed_cycle",
]

REGISTRAR = TEST_USERS["pro_registrar_headers"]
LIC_ADMIN = TEST_USERS["pro_licensing_admin_headers"]
COURT = TEST_USERS["rate_court_officer_headers"]
DISTRIBUTOR = TEST_USERS["royalty_distributor_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
FINANCE2 = TEST_USERS["finance_officer_2_headers"]
SYSADMIN = TEST_USERS["pro_system_admin_headers"]

# Default broadcaster whose formula fee is 4,800,000,000 cents:
# 300,000,000,000 cents of revenue all inside tier 1 at 0.0160 (PRD §3.4).
DEFAULT_BROADCASTER_REVENUE = 300000000000
DEFAULT_BROADCASTER_FEE = 4800000000


def _create_affiliate(party_type="PUBLISHER", **overrides):
    party_type = overrides.pop("party_type", party_type)
    data = get_success_data(
        api.create_affiliate(create_affiliate_payload(party_type=party_type, **overrides), REGISTRAR)
    )
    assert isinstance(data, dict) and data.get("id"), f"Setup failed: affiliate create -> {data}"
    return data


def _create_work(publisher_id, **overrides):
    data = get_success_data(
        api.create_work(create_work_payload(publisher_id, **overrides), make_publisher_headers(publisher_id))
    )
    assert isinstance(data, dict) and data.get("id"), f"Setup failed: work create -> {data}"
    return data


def _create_claim(work_id, affiliate_id, role, bps, headers=None):
    """Create a share claim as the owning affiliate (entity-backed role)."""
    if headers is None:
        headers = (
            make_songwriter_headers(affiliate_id) if role == "WRITER" else make_publisher_headers(affiliate_id)
        )
    data = get_success_data(
        api.create_share_claim(
            work_id,
            create_share_claim_payload(
                affiliate_id, role=role, collection_share_bps=bps, interest_share_bps=bps
            ),
            headers,
        )
    )
    assert isinstance(data, dict) and data.get("id"), f"Setup failed: share claim create -> {data}"
    return data


def _confirm_work(work_id):
    data = get_success_data(api.confirm_work(work_id, REGISTRAR))
    assert data.get("status") == "CONFIRMED", f"Setup failed: work confirm -> {data}"
    return data


def _create_licensee(**overrides):
    data = get_success_data(api.create_licensee(create_licensee_payload(**overrides), LIC_ADMIN))
    assert isinstance(data, dict) and data.get("id"), f"Setup failed: licensee create -> {data}"
    return data


def _issue_license(licensee, **overrides):
    data = get_success_data(
        api.issue_license(
            licensee["id"],
            issue_license_payload(licensee["version"], **overrides),
            LIC_ADMIN,
        )
    )
    assert isinstance(data, dict) and data.get("id"), f"Setup failed: license issue -> {data}"
    return data


def _ingest_performance(work_id, license_id, **overrides):
    data = get_success_data(
        api.ingest_performance(create_performance_payload(work_id, license_id, **overrides), DISTRIBUTOR)
    )
    assert isinstance(data, dict) and data.get("id"), f"Setup failed: performance ingest -> {data}"
    return data


def _create_cycle(**overrides):
    data = get_success_data(api.create_cycle(create_cycle_payload(**overrides), DISTRIBUTOR))
    assert isinstance(data, dict) and data.get("id"), f"Setup failed: cycle create -> {data}"
    return data


def _get_cycle(cycle_id):
    return get_success_data(api.get_cycle(cycle_id, DISTRIBUTOR))


def _close_collection(cycle_id):
    cycle = _get_cycle(cycle_id)
    data = get_success_data(
        api.close_collection(cycle_id, {"expected_cycle_version": cycle["version"]}, DISTRIBUTOR)
    )
    assert data.get("status") == "CALCULATING", f"Setup failed: close-collection -> {data}"
    return data


def _list_cycle_statements(cycle_id, params=None):
    data = get_success_data(api.list_cycle_statements(cycle_id, DISTRIBUTOR, params=params))
    assert isinstance(data, list), f"Setup failed: list cycle statements -> {data}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------

def create_publisher_affiliate(**overrides):
    """An ACTIVE affiliate, PUBLISHER unless the caller overrides party_type."""
    overrides.setdefault("party_type", "PUBLISHER")
    return _create_affiliate(**overrides)


def create_songwriter_affiliate(**overrides):
    """An ACTIVE affiliate, SONGWRITER unless the caller overrides party_type."""
    overrides.setdefault("party_type", "SONGWRITER")
    return _create_affiliate(**overrides)


def create_confirmed_work(publisher=None, claim_bps=10000, **work_overrides):
    """Publisher affiliate + work + one ACCEPTED publisher claim + confirm.

    Returns (publisher, work).
    """
    if publisher is None:
        publisher = _create_affiliate(party_type="PUBLISHER")
    work = _create_work(publisher["id"], **work_overrides)
    _create_claim(work["id"], publisher["id"], "PUBLISHER", claim_bps)
    work = _confirm_work(work["id"])
    return publisher, work


# ---------------------------------------------------------------------------
# Tier 2: entity hierarchy
# ---------------------------------------------------------------------------

def create_broadcaster_with_license(revenue=DEFAULT_BROADCASTER_REVENUE, usage_units=0,
                                    effective_date="2026-01-01", expiry_date="2026-12-31"):
    """BROADCASTER licensee + ACTIVE license. Returns (licensee, license)."""
    licensee = _create_licensee(
        category="BROADCASTER", reported_revenue_cents=revenue, usage_units=usage_units
    )
    license_ = _issue_license(licensee, effective_date=effective_date, expiry_date=expiry_date)
    return licensee, license_


def setup_performance_ready(licensee_overrides=None, license_overrides=None):
    """Confirmed work (single 10000-bps publisher claim) + ACTIVE broadcaster license.

    Returns dict(publisher, work, licensee, license).
    """
    publisher, work = create_confirmed_work()
    licensee = _create_licensee(**(licensee_overrides or {}))
    license_ = _issue_license(licensee, **(license_overrides or {}))
    return {
        "publisher": publisher,
        "work": work,
        "licensee": licensee,
        "license": license_,
    }


def setup_with_performance(**kwargs):
    """setup_performance_ready + one ingested ACCEPTED performance.

    Returns dict(publisher, work, licensee, license, event).
    """
    ctx = setup_performance_ready(**kwargs)
    event = _ingest_performance(ctx["work"]["id"], ctx["license"]["id"])
    ctx["event"] = event
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: full lifecycle shortcuts (cycles)
# ---------------------------------------------------------------------------

def setup_calculating_cycle(event_overrides=None, **kwargs):
    """Performance ingested + cycle COLLECTING -> CALCULATING (closed).

    Returns dict(publisher, work, licensee, license, event, cycle).
    """
    ctx = setup_with_performance(**kwargs)
    event = ctx["event"]
    cycle = _create_cycle()
    get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
    get_success_data(
        api.capture_performances(cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR)
    )
    cycle = _close_collection(cycle["id"])
    ctx["cycle"] = cycle
    return ctx


def setup_distributed_cycle(event_overrides=None, extra_setup=None, **kwargs):
    """Full lifecycle through DISTRIBUTED: all current-epoch statements FINALIZED.

    extra_setup: optional callable(ctx) invoked after capture but before
    close-collection (e.g., to suspend the publisher affiliate so its share
    routes to the unclaimed pool).

    Returns dict(publisher, work, licensee, license, event, cycle, statements).
    """
    ctx = setup_with_performance(**kwargs)
    event = ctx["event"]
    cycle = _create_cycle()
    get_success_data(api.open_cycle(cycle["id"], DISTRIBUTOR))
    get_success_data(
        api.capture_performances(cycle["id"], {"performance_event_ids": [event["id"]]}, DISTRIBUTOR)
    )
    if extra_setup is not None:
        extra_setup(ctx)
    cycle = _close_collection(cycle["id"])
    statements = _list_cycle_statements(cycle["id"])
    for stmt in statements:
        get_success_data(api.finalize_statement(stmt["id"], DISTRIBUTOR))
    cycle = get_success_data(api.distribute_cycle(cycle["id"], DISTRIBUTOR))
    assert cycle.get("status") == "DISTRIBUTED", f"Setup failed: distribute -> {cycle}"
    ctx["cycle"] = cycle
    ctx["statements"] = _list_cycle_statements(cycle["id"])
    return ctx
