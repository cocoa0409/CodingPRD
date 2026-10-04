"""Composite fixtures that walk the API to a wanted state.

Every test starts against an empty deployment, so each test builds the world
it needs from scratch through the public API only — no direct data writes.
Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a confusing assertion error.

The canonical shape returned by ``setup_two_plan_world`` is a dict:

    {
        "home": Plan,              # home plan, LICENSED
        "host": Plan,              # host plan, LICENSED
        "member": Member,          # member under the home plan
        "home_headers": headers,   # HomePlanOperator headers for home plan
        "host_headers": headers,   # HostPlanOperator headers for host plan
        ...                        # plus whatever the caller opted into
    }

Ownership-gated calls always use the entity-backed headers built from the
actual plan ids.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import BASE_CLOCK
from .test_users import (
    ASSOCIATION_ADMIN_HEADERS,
    make_home_plan_operator_headers,
    make_host_plan_operator_headers,
)


# ─── Tier 1: state progression ────────────────────────────────────────────


def set_clock(api: ApiClient, current_utc: str = BASE_CLOCK) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(current_utc), ASSOCIATION_ADMIN_HEADERS))


def create_plan(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a plan (starts PENDING). Returns the created plan."""
    return get_success_data(api.create_plan(f.plan_payload(**overrides), ASSOCIATION_ADMIN_HEADERS))


def create_licensed_plan(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register a plan and activate its license. Returns the LICENSED plan."""
    plan = create_plan(api, **overrides)
    return get_success_data(api.activate_license(plan["id"], ASSOCIATION_ADMIN_HEADERS))


def create_member(api: ApiClient, home_plan: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Register a member under the given home plan."""
    return get_success_data(
        api.create_member(
            f.member_payload(home_plan["id"], **overrides),
            make_home_plan_operator_headers(home_plan["id"]),
        )
    )


def create_national_account(api: ApiClient, controlling_plan: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Create a national account arrangement (starts PROPOSED)."""
    return get_success_data(
        api.create_national_account(
            f.national_account_payload(controlling_plan["id"], **overrides),
            ASSOCIATION_ADMIN_HEADERS,
        )
    )


def create_active_national_account(api: ApiClient, controlling_plan: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Create a national account and activate it. The controlling plan must be LICENSED."""
    account = create_national_account(api, controlling_plan, **overrides)
    return get_success_data(api.activate_national_account(account["id"], ASSOCIATION_ADMIN_HEADERS))


def create_rate_schedule(api: ApiClient, host_plan: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Publish a negotiated rate window on the given host plan."""
    return get_success_data(
        api.create_rate_schedule(
            f.rate_schedule_payload(host_plan["id"], **overrides),
            make_host_plan_operator_headers(host_plan["id"]),
        )
    )


def create_access_fee_schedule(api: ApiClient, home_plan: Dict[str, Any], host_plan: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Publish the access-fee tier schedule between a home and a host plan."""
    return get_success_data(
        api.create_access_fee_schedule(
            f.access_fee_schedule_payload(home_plan["id"], host_plan["id"], **overrides),
            ASSOCIATION_ADMIN_HEADERS,
        )
    )


# ─── Tier 2: entity hierarchy ─────────────────────────────────────────────


def setup_two_plan_world(
    api: ApiClient,
    member_overrides: Optional[Dict[str, Any]] = None,
    with_rate_schedule: bool = True,
    rate_overrides: Optional[Dict[str, Any]] = None,
    with_fee_schedule: bool = True,
    fee_overrides: Optional[Dict[str, Any]] = None,
    with_national_account: bool = False,
    account_overrides: Optional[Dict[str, Any]] = None,
    clock: str = BASE_CLOCK,
) -> Dict[str, Any]:
    """The standard world: LICENSED home plan (CA), LICENSED host plan (TX),
    one member under the home plan, and optionally the standing rate and
    access-fee schedules. Returns the world dict with entity-backed headers."""
    set_clock(api, clock)
    home = create_licensed_plan(api, plan_code="HCA", legal_name="Home Plan CA", service_area_states=["CA"])
    host = create_licensed_plan(api, plan_code="TTX", legal_name="Host Plan TX", service_area_states=["TX"])

    world: Dict[str, Any] = {
        "home": home,
        "host": host,
        "home_headers": make_home_plan_operator_headers(home["id"]),
        "host_headers": make_host_plan_operator_headers(host["id"]),
    }

    account = None
    if with_national_account:
        account = create_active_national_account(api, home, **(account_overrides or {}))
        world["account"] = account

    m_over = dict(member_overrides or {})
    if account is not None and "national_account_id" not in m_over:
        m_over["national_account_id"] = account["id"]
    member = create_member(api, home, **m_over)
    world["member"] = member

    if with_rate_schedule:
        world["rate_schedule"] = create_rate_schedule(api, host, **(rate_overrides or {}))
    if with_fee_schedule:
        world["fee_schedule"] = create_access_fee_schedule(api, home, host, **(fee_overrides or {}))

    return world


# ─── Tier 3: full lifecycle shortcuts ─────────────────────────────────────


def create_claim(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Submit an inter-plan claim hosted by the world's host plan."""
    return get_success_data(
        api.create_claim(
            f.claim_payload(world["member"]["id"], world["host"]["id"], **overrides),
            world["host_headers"],
        )
    )


def create_priced_claim(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Submit a claim and price it (RECEIVED -> PRICED)."""
    claim = create_claim(api, world, **overrides)
    return get_success_data(api.price_claim(claim["id"], world["host_headers"]))


def create_routed_claim(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Submit a claim, price it, and route it (RECEIVED -> PRICED -> ROUTED)."""
    claim = create_priced_claim(api, world, **overrides)
    return get_success_data(api.route_claim(claim["id"], world["host_headers"]))


def create_paid_claim(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Walk a claim through to PAID: submit -> price -> route -> determine -> pay."""
    claim = create_routed_claim(api, world, **overrides)
    get_success_data(api.determine_benefit(claim["id"], world["home_headers"]))
    return get_success_data(api.pay_claim(claim["id"], world["host_headers"]))


def create_propagated_adjustment(api: ApiClient, world: Dict[str, Any], claim: Dict[str, Any], delta: int, reason: str = "repricing") -> Dict[str, Any]:
    """Create an adjustment on the claim and walk it to PROPAGATED.

    Reads the claim's current version fresh so the OCC guard passes.
    """
    current = get_success_data(api.get_claim(claim["id"], world["host_headers"]))
    adjustment = get_success_data(
        api.create_adjustment(
            claim["id"],
            f.adjustment_payload(current["version"], reason=reason, delta_allowed_cents=delta),
            world["host_headers"],
        )
    )
    get_success_data(api.validate_adjustment(adjustment["id"], world["host_headers"]))
    return get_success_data(api.propagate_adjustment(adjustment["id"], world["home_headers"]))


def create_applied_adjustment(api: ApiClient, world: Dict[str, Any], claim: Dict[str, Any], delta: int, reason: str = "repricing") -> Dict[str, Any]:
    """Create an adjustment and walk it all the way to APPLIED."""
    adjustment = create_propagated_adjustment(api, world, claim, delta, reason)
    return get_success_data(api.apply_adjustment(adjustment["id"], world["host_headers"]))


# ─── Tier 4: settlement batch progression ─────────────────────────────────


def create_settlement_batch(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Open a settlement batch with the home plan as debtor and the host as creditor."""
    return get_success_data(
        api.create_settlement_batch(
            f.settlement_batch_payload(world["home"]["id"], world["host"]["id"], **overrides),
            world["host_headers"],
        )
    )


def create_finalized_batch(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Open a batch and finalize it (OPEN -> FINALIZED)."""
    batch = create_settlement_batch(api, world, **overrides)
    return get_success_data(api.finalize_batch(batch["id"], world["host_headers"]))


def create_acknowledged_batch(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Open, finalize, and acknowledge a batch (FINALIZED -> ACKNOWLEDGED)."""
    batch = create_finalized_batch(api, world, **overrides)
    return get_success_data(api.acknowledge_batch(batch["id"], world["home_headers"]))


def create_disbursed_batch(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Open, finalize, acknowledge, and disburse a batch."""
    batch = create_acknowledged_batch(api, world, **overrides)
    return get_success_data(api.disburse_batch(batch["id"], ASSOCIATION_ADMIN_HEADERS))


def create_reconciled_batch(api: ApiClient, world: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Walk a batch all the way to the terminal RECONCILED state."""
    batch = create_disbursed_batch(api, world, **overrides)
    return get_success_data(api.reconcile_batch(batch["id"], ASSOCIATION_ADMIN_HEADERS))


# ─── Tier 5: composite worlds ─────────────────────────────────────────────


def setup_paid_claim_world(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Standard world plus one claim walked to PAID. Adds "claim" to the world."""
    world = setup_two_plan_world(api, **kwargs)
    world["claim"] = create_paid_claim(api, world)
    return world


def setup_disputed_batch_world(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    """Standard world with one PAID claim and a FINALIZED-then-DISPUTED batch.
    Adds "claim" and "batch" to the world; the batch is in DISPUTED state."""
    world = setup_paid_claim_world(api, **kwargs)
    world["batch"] = create_finalized_batch(api, world)
    disputed = get_success_data(api.dispute_batch(world["batch"]["id"], world["home_headers"]))
    world["batch"] = disputed
    return world
