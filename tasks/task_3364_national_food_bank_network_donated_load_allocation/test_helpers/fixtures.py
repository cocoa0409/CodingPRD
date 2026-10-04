"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the API server is restarted (empty database) before each
test. Setup failures raise a clear "Setup failed" assertion rather than a
confusing downstream failure.
"""
import pytest
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _default_client
from .constants import (
    CLOCK_START,
    DEFAULT_POOL_CENTS,
    EPOCH_2026_09,
    FREIGHT_CENTS_PER_MILE,
    MAX_SUBSIDY_PER_LOAD_CENTS,
    MIN_SUBSIDY_CENTS,
    REMOTE_DISTANCE_THRESHOLD_MILES,
    REMOTE_UPLIFT_PCT,
    TRANSPORT_SHARE_PCT,
)
from .factories import (
    create_audit_payload,
    create_bid_payload,
    create_dispatch_payload,
    create_donor_agreement_payload,
    create_freight_decision_payload,
    create_load_payload,
    create_member_payload,
    create_pickup_payload,
    create_recall_payload,
    create_share_grant_payload,
    create_store_program_payload,
)
from .test_users import (
    ADMIN_OPERATOR_ID,
    AUDITOR_OPERATOR_ID,
    SECOND_ADMIN_OPERATOR_ID,
    TEST_USERS,
    make_admin_headers,
    make_auditor_headers,
    make_member_headers,
)

# ── Default identities ───────────────────────────────────────────────
ADMIN = TEST_USERS["admin_headers"]
AUDITOR = TEST_USERS["auditor_headers"]

DEFAULT_DELIVERY_WINDOW_START = "2026-09-03T08:00:00Z"
DEFAULT_DELIVERY_WINDOW_END = "2026-09-03T12:00:00Z"


def _api(api):
    return api if api is not None else _default_client


def _setup(response, step: str) -> dict:
    try:
        return get_success_data(response)
    except AssertionError as exc:
        raise AssertionError(f"Setup failed at '{step}': {exc}") from exc


def _setup_error(response, step: str, expected_error_id: str) -> dict:
    body = response.json() if response.text else {}
    if response.status_code < 400 or body.get("response_type") != "error":
        raise AssertionError(
            f"Setup failed at '{step}': expected {expected_error_id}, "
            f"got HTTP {response.status_code}: {response.text}"
        )
    return body["data"]


# ── Logical clock ────────────────────────────────────────────────────

def set_clock(api, current_utc: str = CLOCK_START, headers=None):
    """Set the logical clock; the startup default is 2026-09-01T00:00:00Z."""
    res = _api(api).set_clock({"current_utc": current_utc}, headers or ADMIN)
    return _setup(res, f"set_clock({current_utc})")


# ── Tier 1: state progression ────────────────────────────────────────

def create_member(api, headers=None, **overrides) -> dict:
    """Register a member food bank (PENDING_CERTIFICATION, zero balances)."""
    payload = create_member_payload(**overrides)
    res = _api(api).create_member(payload, headers or ADMIN)
    return _setup(res, f"create_member({payload.get('name')})")


def create_active_agreement(api, headers=None, **overrides) -> dict:
    """Create a donor agreement and activate it so loads can be drawn."""
    payload = create_donor_agreement_payload(**overrides)
    client = _api(api)
    agreement = _setup(
        client.create_donor_agreement(payload, headers or ADMIN),
        f"create_donor_agreement({payload.get('donor_name')})",
    )
    return _setup(
        client.activate_donor_agreement(agreement["id"], headers or ADMIN),
        "activate_donor_agreement",
    )


def create_audit(api, member_id, opened_by: str = ADMIN_OPERATOR_ID, **overrides) -> dict:
    """Open a standards audit; opened_by_user_id is stamped from X-User-ID."""
    payload = create_audit_payload(member_id, **overrides)
    res = _api(api).create_audit(payload, make_admin_headers(opened_by))
    return _setup(res, f"create_audit({payload.get('audit_type')})")


def complete_audit(api, audit_id, completed_by: str = AUDITOR_OPERATOR_ID) -> dict:
    """Complete an audit as an operator distinct from the opener."""
    res = _api(api).complete_audit(audit_id, make_auditor_headers(completed_by))
    return _setup(res, "complete_audit")


def certify_member(api, member_id, headers=None) -> dict:
    """Certify a member that already holds a passed COMPREHENSIVE audit."""
    res = _api(api).certify_member(member_id, headers or ADMIN)
    return _setup(res, "certify_member")


def create_certified_member(api, audit_scores=(85, 85, 85),
                            audit_opened_by: str = ADMIN_OPERATOR_ID, **overrides) -> dict:
    """Member + passed COMPREHENSIVE audit + certification, in one call chain."""
    client = _api(api)
    member = create_member(client, **overrides)
    audit = create_audit(
        client, member["id"], opened_by=audit_opened_by,
        storage_score=audit_scores[0],
        distribution_score=audit_scores[1],
        reporting_score=audit_scores[2],
    )
    complete_audit(client, audit["id"])
    return certify_member(client, member["id"])


def grant_shares(api, member: dict, epoch: str = EPOCH_2026_09, activity_basis=None) -> dict:
    """Apply one epoch's share grant to a member (returns the GRANT entry)."""
    payload = create_share_grant_payload(member["id"], member["version"], epoch=epoch)
    if activity_basis is not None:
        payload["activity_basis"] = activity_basis
    res = _api(api).create_share_grant(payload, ADMIN)
    return _setup(res, "grant_shares")


def create_certified_member_with_shares(api, shares_epoch: str = EPOCH_2026_09, **overrides) -> dict:
    """Certified member that has received its epoch grant; returns fresh state."""
    client = _api(api)
    member = create_certified_member(client, **overrides)
    grant_shares(client, member, epoch=shares_epoch)
    return _setup(client.get_member(member["id"], ADMIN), "get_member after grant")


def setup_two_member_epoch(api, m1_population: int = 250_000, m2_population: int = 100_000,
                           epoch: str = EPOCH_2026_09):
    """Two certified members that both receive the same epoch's grant.

    With populations 250000 and 100000 the frozen-demand split is 71429 / 28571.
    Returns (m1, m2) re-read after both grants.
    """
    client = _api(api)
    m1 = create_certified_member(
        client,
        name="Greater Cleveland Food Bank", state_code="OH",
        food_insecure_population=m1_population,
        storage_capacity_lbs=200_000, refrigerated_capacity_lbs=50_000,
        transport_ability="LOCAL",
    )
    m2 = create_certified_member(
        client,
        name="Food Bank of Iowa", state_code="IA",
        food_insecure_population=m2_population,
        storage_capacity_lbs=150_000, refrigerated_capacity_lbs=30_000,
        transport_ability="REGIONAL",
        audit_opened_by=SECOND_ADMIN_OPERATOR_ID,
    )
    grant_shares(client, m1, epoch=epoch)
    grant_shares(client, m2, epoch=epoch)
    m1 = _setup(client.get_member(m1["id"], ADMIN), "get_member m1")
    m2 = _setup(client.get_member(m2["id"], ADMIN), "get_member m2")
    return m1, m2


# ── Tier 2: loads ────────────────────────────────────────────────────

def create_load(api, agreement_id, headers=None, **overrides) -> dict:
    """Create a donated truckload (starts POSTED / CLEAR / PENDING)."""
    payload = create_load_payload(agreement_id, **overrides)
    res = _api(api).create_load(payload, headers or ADMIN)
    return _setup(res, f"create_load(lot {payload.get('lot_code')})")


def create_bidding_load(api, agreement_id, headers=None, **overrides) -> dict:
    """Create a load and open it for bidding."""
    client = _api(api)
    load = create_load(client, agreement_id, headers=headers, **overrides)
    return _setup(client.post_load(load["id"], headers or ADMIN), "post_load")


def create_loads_sharing_lot(api, agreement_id, weights, lot_code="LOT-77",
                             category="DRY_GOODS", storage_type="DRY",
                             post=True, distance_miles=260, **overrides):
    """Create several loads of the same lot; optionally open each for bidding."""
    client = _api(api)
    loads = []
    for weight in weights:
        load = create_load(
            client, agreement_id,
            product_category=category, storage_type=storage_type,
            weight_lbs=weight, lot_code=lot_code, distance_miles=distance_miles,
            **overrides,
        )
        if post:
            load = _setup(client.post_load(load["id"], ADMIN), "post_load")
        loads.append(load)
    return loads


# ── Bids ─────────────────────────────────────────────────────────────

def submit_bid(api, load: dict, member: dict, shares_offered: int = 400,
               preference_rank: int = 1, can_self_transport: bool = False,
               expected_load_version=None) -> dict:
    """Submit a bid as the member itself (entity-backed identity)."""
    if expected_load_version is None:
        expected_load_version = load["version"]
    payload = create_bid_payload(
        member["id"], expected_load_version,
        shares_offered=shares_offered, preference_rank=preference_rank,
        can_self_transport=can_self_transport,
    )
    res = _api(api).create_bid(load["id"], payload, make_member_headers(member["id"]))
    return _setup(res, "submit_bid")


def withdraw_bid(api, bid_id, member: dict) -> dict:
    res = _api(api).withdraw_bid(bid_id, make_member_headers(member["id"]))
    return _setup(res, "withdraw_bid")


# ── Tier 3: lifecycle shortcuts ──────────────────────────────────────

def award_load(api, load_id, headers=None, **payload) -> dict:
    res = _api(api).award_load(load_id, headers or ADMIN, payload or None)
    return _setup(res, "award_load")


def record_freight_decision(api, load_id, decision="COVERED", detour_miles=None,
                            headers=None) -> dict:
    payload = create_freight_decision_payload(decision, **(
        {"detour_miles": detour_miles} if detour_miles is not None else {}
    ))
    res = _api(api).record_freight_decision(load_id, payload, headers or ADMIN)
    return _setup(res, "record_freight_decision")


def dispatch_load(api, load_id, window_start=DEFAULT_DELIVERY_WINDOW_START,
                  window_end=DEFAULT_DELIVERY_WINDOW_END, headers=None) -> dict:
    payload = create_dispatch_payload(window_start, window_end)
    res = _api(api).dispatch_load(load_id, payload, headers or ADMIN)
    return _setup(res, "dispatch_load")


def deliver_load(api, load_id, headers=None) -> dict:
    res = _api(api).deliver_load(load_id, headers or ADMIN)
    return _setup(res, "deliver_load")


def setup_load_with_bid(api, agreement_id, member: dict, shares_offered: int = 400,
                        preference_rank: int = 1, can_self_transport: bool = False,
                        **load_overrides):
    """Bidding load + one SUBMITTED bid by `member`. Returns (load, bid)."""
    client = _api(api)
    load = create_bidding_load(client, agreement_id, **load_overrides)
    bid = submit_bid(client, load, member, shares_offered=shares_offered,
                     preference_rank=preference_rank,
                     can_self_transport=can_self_transport)
    return load, bid


def setup_awarded_load(api, agreement_id, member: dict, shares_offered: int = 400,
                       preference_rank: int = 1, can_self_transport: bool = False,
                       **load_overrides):
    """Load awarded to `member` with freight_decision PENDING. Returns (load, bid)."""
    client = _api(api)
    load, bid = setup_load_with_bid(
        client, agreement_id, member, shares_offered=shares_offered,
        preference_rank=preference_rank, can_self_transport=can_self_transport,
        **load_overrides,
    )
    awarded = award_load(client, load["id"])
    return awarded, bid


def setup_freight_decided_load(api, agreement_id, member: dict, decision="COVERED",
                               detour_miles=None, can_self_transport: bool = False,
                               **load_overrides):
    """Awarded load whose freight position is settled. Returns (load, bid)."""
    client = _api(api)
    load, bid = setup_awarded_load(
        client, agreement_id, member, can_self_transport=can_self_transport,
        **load_overrides,
    )
    decided = record_freight_decision(client, load["id"], decision=decision,
                                      detour_miles=detour_miles)
    return decided, bid


def setup_dispatched_load(api, agreement_id, member: dict,
                          window_start=DEFAULT_DELIVERY_WINDOW_START,
                          window_end=DEFAULT_DELIVERY_WINDOW_END,
                          **load_overrides):
    """Load in IN_TRANSIT to `member`. Returns (load, bid)."""
    client = _api(api)
    load, bid = setup_freight_decided_load(client, agreement_id, member, **load_overrides)
    in_transit = dispatch_load(client, load["id"], window_start=window_start,
                               window_end=window_end)
    return in_transit, bid


def setup_delivered_load(api, agreement_id, member: dict, weight_lbs: int = 40_000,
                         distance_miles: int = 120, lot_code: str = "LOT-D1",
                         window_start=DEFAULT_DELIVERY_WINDOW_START,
                         window_end=DEFAULT_DELIVERY_WINDOW_END,
                         shares_offered: int = 100, can_self_transport: bool = True):
    """Full lifecycle through DELIVERED. Returns (load, bid)."""
    client = _api(api)
    load, bid = setup_dispatched_load(
        client, agreement_id, member,
        weight_lbs=weight_lbs, distance_miles=distance_miles, lot_code=lot_code,
        shares_offered=shares_offered, can_self_transport=can_self_transport,
        window_start=window_start, window_end=window_end,
    )
    delivered = deliver_load(client, load["id"])
    return delivered, bid


# ── Retail store programs and pickups ────────────────────────────────

def create_store_program(api, member: dict, **overrides) -> dict:
    """Register a program as the member itself; posture follows the member."""
    payload = create_store_program_payload(member["id"], **overrides)
    res = _api(api).create_store_program(payload, make_member_headers(member["id"]))
    return _setup(res, "create_store_program")


def schedule_pickup(api, program: dict, member: dict, scheduled_date: str,
                    window_start: str, window_end: str) -> dict:
    payload = create_pickup_payload(scheduled_date, window_start, window_end)
    res = _api(api).schedule_pickup(program["id"], payload, make_member_headers(member["id"]))
    return _setup(res, "schedule_pickup")


def miss_pickup(api, pickup_id, member: dict) -> dict:
    res = _api(api).miss_pickup(pickup_id, make_member_headers(member["id"]))
    return _setup(res, "miss_pickup")


def complete_pickup(api, pickup_id, member: dict, collected_lbs: int) -> dict:
    res = _api(api).complete_pickup(pickup_id, {"collected_lbs": collected_lbs},
                                    make_member_headers(member["id"]))
    return _setup(res, "complete_pickup")


def setup_program_with_pickups(api, member: dict, windows, frequency="DAILY",
                               **program_overrides):
    """ACTIVE program plus one SCHEDULED pickup per (date, start, end) tuple."""
    client = _api(api)
    program = create_store_program(client, member, pickup_frequency=frequency,
                                   **program_overrides)
    pickups = [
        schedule_pickup(client, program, member, date, start, end)
        for (date, start, end) in windows
    ]
    return program, pickups


# ── Recalls ──────────────────────────────────────────────────────────

def create_recall(api, agreement_id, lot_code="LOT-77", product_category="DRY_GOODS",
                  affected_lbs=1_000, scope=None, headers=None) -> dict:
    payload = create_recall_payload(
        agreement_id, lot_code=lot_code, product_category=product_category,
        affected_lbs=affected_lbs,
    )
    if scope is not None:
        payload["scope"] = scope
    res = _api(api).create_recall(payload, headers or ADMIN)
    return _setup(res, "create_recall")


def trace_recall(api, recall_id, headers=None) -> dict:
    res = _api(api).trace_recall(recall_id, headers or ADMIN)
    return _setup(res, "trace_recall")


def resolve_recall(api, recall_id, headers=None) -> dict:
    res = _api(api).resolve_recall(recall_id, headers or ADMIN)
    return _setup(res, "resolve_recall")


def list_recall_holds(api, headers=None, **params):
    from prd_bench_local_runner.testing import validate_paginated
    data, meta = validate_paginated(_api(api).list_recall_holds(headers or ADMIN, params=params))
    return data, meta


# ── Expected-value calculators (PRD formulas) ────────────────────────

def expected_freight_estimate(distance_miles: int, detour_miles: int = 0) -> int:
    """base = (distance_miles + detour_miles) * 185 cents."""
    return (distance_miles + detour_miles) * FREIGHT_CENTS_PER_MILE


def expected_freight_subsidy(distance_miles: int, transport_ability: str,
                             can_self_transport: bool, pool_remaining_cents: int,
                             detour_miles: int = 0) -> int:
    """The PRD freight formula: per-component ceil, then sum, then nested min."""
    import math
    base = expected_freight_estimate(distance_miles, detour_miles)
    share_pct = 0 if can_self_transport else TRANSPORT_SHARE_PCT[transport_ability]
    raw = math.ceil(base * share_pct / 100)
    uplift = 0
    if (not can_self_transport
            and distance_miles >= REMOTE_DISTANCE_THRESHOLD_MILES
            and transport_ability in ("NONE", "LOCAL")):
        uplift = math.ceil(base * REMOTE_UPLIFT_PCT / 100)
    subsidy = min(raw + uplift, pool_remaining_cents, MAX_SUBSIDY_PER_LOAD_CENTS)
    if subsidy < MIN_SUBSIDY_CENTS:
        subsidy = 0
    return subsidy


def expected_activity_bonus(delivered_lbs: int) -> int:
    """15 shares for every full ten thousand pounds delivered."""
    return (delivered_lbs // 10_000) * 15


def expected_meal_equivalent(delivered_lbs: int, factor: float = 1.2) -> int:
    return int(delivered_lbs // factor)


def assert_balance(expected: int, member: dict, context: str = ""):
    assert member["share_balance"] == expected, (
        f"Expected share_balance {expected}, got {member['share_balance']} {context}"
    )
