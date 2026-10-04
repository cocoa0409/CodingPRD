"""
Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch against an empty database
(the harness restarts the API server before each test), using only endpoints the
PRD declares. Setup steps use the lenient `get_success_data()` validator so a
broken setup produces a clear "Setup step failed" error rather than a confusing
assertion failure downstream.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .test_users import (
    TEST_USERS,
    make_capacity_owner_headers,
    make_freight_agent_headers,
    make_network_admin_headers,
    make_settlement_operator_headers,
)

# ─── Small utilities ──────────────────────────────────────────────────────────

_code_counter = {"n": 0}


def unique_code(prefix: str) -> str:
    """A unique code per process, so repeated setup inside one test never
    collides on a network-wide uniqueness constraint."""
    _code_counter["n"] += 1
    return f"{prefix}-{_code_counter['n']:04d}"


def agent_headers(agent: dict) -> dict:
    """Ownership-gated headers for the acting FreightAgent."""
    return make_freight_agent_headers(agent["id"])


def bco_headers(bco: dict) -> dict:
    """Ownership-gated headers for the acting CapacityOwnerOperator."""
    return make_capacity_owner_headers(bco["id"])


def set_logical_clock(current_utc: str = DEFAULT_CLOCK) -> dict:
    """Drive the network's logical clock. Never falls back to wall-clock time."""
    res = api_client.set_clock({"current_utc": current_utc}, TEST_USERS["network_admin_headers"])
    data = get_success_data(res)
    return data if isinstance(data, dict) else {}


def get_load_version(load_id: str) -> int:
    """Read the parent load's current version, for the OCC guards."""
    return get_success_data(api_client.get_load(load_id, TEST_USERS["network_admin_headers"]))["version"]


def get_agent_version(agent_id: str) -> int:
    return get_success_data(api_client.get_agent(agent_id, TEST_USERS["network_admin_headers"]))["version"]


def get_bco(bco_id: str) -> dict:
    return get_success_data(
        api_client.get_capacity_owner(bco_id, TEST_USERS["network_admin_headers"])
    )


# ─── Tier 1: Agent enrollment and lifecycle ───────────────────────────────────

def enroll_agent(activate: bool = True, **overrides) -> dict:
    """Enroll an agent (201, PENDING_ENROLLMENT) and optionally activate it."""
    payload = {
        "agent_code": unique_code("AG"),
        "legal_name": "Test Freight Agency",
        "home_state": "TX",
        "commission_rate_pct": TEST_DEFAULTS["AGENT_COMMISSION_RATE"],
        "territory_codes": ["TX", "OK"],
        "customer_ownership_days": 365,
    }
    payload.update(overrides)
    agent = get_success_data(
        api_client.create_agent(payload, TEST_USERS["network_admin_headers"])
    )
    if activate:
        agent = get_success_data(
            api_client.activate_agent(agent["id"], TEST_USERS["network_admin_headers"])
        )
    return agent


def register_customer(agent: dict, **overrides) -> dict:
    """Register a shipper under an agent, acting as that agent."""
    payload = {
        "agent_id": agent["id"],
        "customer_ref": unique_code("CUST"),
        "shipper_name": "Test Shipper Co",
        "first_booked_at": DEFAULT_CLOCK,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_customer_account(payload, agent_headers(agent))
    )


def promote_load(agent: dict, customer_ref: str, **overrides) -> dict:
    """Promote a load onto the agent's board (201, POSTED)."""
    payload = {
        "agent_id": agent["id"],
        "customer_ref": customer_ref,
        "origin_state": "TX",
        "destination_state": "OK",
        "linehaul_revenue_cents": TEST_DEFAULTS["LINEHAUL_CENTS"],
        "fuel_surcharge_cents": TEST_DEFAULTS["FUEL_SURCHARGE_CENTS"],
        "accessorial_revenue_cents": TEST_DEFAULTS["ACCESSORIAL_CENTS"],
        "dispatched_miles": TEST_DEFAULTS["DISPATCHED_MILES"],
    }
    payload.update(overrides)
    return get_success_data(api_client.create_load(payload, agent_headers(agent)))


def agent_with_customer(**overrides) -> tuple:
    """An ACTIVE agent plus one customer account. Returns (agent, customer)."""
    agent = enroll_agent(**overrides)
    customer = register_customer(agent)
    return agent, customer


# ─── Tier 2: Capacity owner qualification ─────────────────────────────────────

DOCUMENT_TYPES = [
    "CDL", "MEDICAL_CARD", "MVR_REPORT", "DRUG_TEST", "OA_ENROLLMENT", "LIABILITY_INSURANCE",
]


def enroll_capacity_owner(**overrides) -> dict:
    """Enroll a BCO (201, PENDING_QUALIFICATION)."""
    payload = {
        "owner_code": unique_code("BCO"),
        "legal_name": "Test Trucking LLC",
        "home_terminal_city": "Amarillo",
        "revenue_split_pct": TEST_DEFAULTS["REVENUE_SPLIT_PCT"],
        "oa_enrolled": True,
        "liability_insurance_deductible_cents": 250000,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_capacity_owner(payload, TEST_USERS["network_admin_headers"])
    )


def post_ledger_entry(bco: dict, amount_cents: int, transaction_type: str = "ESCROW_DEPOSIT",
                      effective_at: str = DEFAULT_CLOCK) -> dict:
    payload = {
        "capacity_owner_id": bco["id"],
        "transaction_type": transaction_type,
        "amount_cents": amount_cents,
        "effective_at": effective_at,
    }
    return get_success_data(
        api_client.create_escrow_transaction(payload, TEST_USERS["settlement_operator_headers"])
    )


def file_standard_credentials(bco: dict, expires_at: str = "2027-01-05T00:00:00Z",
                              issued_at: str = "2026-01-05T00:00:00Z",
                              document_types=None) -> list:
    """File one credential for each of the six tracked document types."""
    docs = []
    for doc_type in (document_types or DOCUMENT_TYPES):
        payload = {
            "capacity_owner_id": bco["id"],
            "document_type": doc_type,
            "document_number": unique_code(f"DOC-{doc_type}"),
            "issued_at": issued_at,
            "expires_at": expires_at,
        }
        docs.append(
            get_success_data(
                api_client.create_compliance_document(payload, TEST_USERS["safety_reviewer_headers"])
            )
        )
    return docs


def add_fleet_unit(bco: dict, inspect: bool = True, inspected_at: str = "2026-08-15T00:00:00Z",
                   **overrides) -> dict:
    """Add a fleet unit, and by default record a passing inspection so it is
    IN_SERVICE with a CURRENT inspection."""
    payload = {
        "capacity_owner_id": bco["id"],
        "unit_number": unique_code("T"),
        "equipment_type": "TRACTOR",
        "model_year": 2021,
        "inspection_due_at": TEST_DEFAULTS["INSPECTION_DUE_AT"],
    }
    payload.update(overrides)
    equipment = get_success_data(
        api_client.create_equipment(payload, TEST_USERS["safety_reviewer_headers"])
    )
    if inspect:
        equipment = get_success_data(
            api_client.record_inspection(
                equipment["id"],
                {
                    "inspected_at": inspected_at,
                    "result": "PASS",
                    "inspector_certificate": unique_code("CERT"),
                },
                TEST_USERS["safety_reviewer_headers"],
            )
        )
    return equipment


def qualify_bco(bco: dict) -> dict:
    """Qualify a BCO, supplying the owner version the reviewer just observed."""
    fresh = get_bco(bco["id"])
    return get_success_data(
        api_client.qualify_capacity_owner(
            bco["id"],
            {"expected_network_capacity_owner_version": fresh["version"]},
            TEST_USERS["safety_reviewer_headers"],
        )
    )


def setup_qualified_bco(oa_enrolled: bool = True, escrow_cents: int = 250000,
                        unit_count: int = 1, qualify: bool = True,
                        document_expires_at: str = "2027-01-05T00:00:00Z",
                        **owner_overrides) -> dict:
    """A fully funded, credentialed BCO with an inspected TRACTOR; optionally
    walked through to QUALIFIED. Returns a bundle of its children."""
    bco = enroll_capacity_owner(oa_enrolled=oa_enrolled, **owner_overrides)
    if escrow_cents:
        post_ledger_entry(bco, escrow_cents)
    docs = file_standard_credentials(bco, expires_at=document_expires_at)
    units = [add_fleet_unit(bco) for _ in range(unit_count)]
    if qualify:
        bco = qualify_bco(bco)
    return {"bco": bco, "documents": docs, "equipment": units}


# ─── Tier 3: Offer book and the haul lifecycle ────────────────────────────────

def post_offer(agent: dict, load: dict, bco: dict, offered_pay_cents: int = 126000,
               offered_at: str = "2026-09-01T01:00:00Z") -> dict:
    """Post a board offer carrying the freshly read load version."""
    payload = {
        "load_id": load["id"],
        "capacity_owner_id": bco["id"],
        "offered_pay_cents": offered_pay_cents,
        "offered_at": offered_at,
        "expected_network_load_version": get_load_version(load["id"]),
    }
    return get_success_data(api_client.create_load_offer(payload, agent_headers(agent)))


def accept_offer(bco: dict, offer: dict, accepted_at: str = "2026-09-01T02:00:00Z") -> dict:
    return get_success_data(
        api_client.accept_load_offer(offer["id"], {"accepted_at": accepted_at}, bco_headers(bco))
    )


def award_load(agent: dict, load: dict, bco: dict, offered_pay_cents: int = 126000,
               offered_at: str = "2026-09-01T01:00:00Z",
               accepted_at: str = "2026-09-01T02:00:00Z") -> tuple:
    """Promote an offer and award it. Returns (offer, load_after_award)."""
    offer = post_offer(agent, load, bco, offered_pay_cents, offered_at)
    accept_offer(bco, offer, accepted_at)
    return offer, get_success_data(api_client.get_load(load["id"], TEST_USERS["network_admin_headers"]))


def cover_load(bco: dict, load: dict, equipment: dict,
               departed_at: str = "2026-09-01T03:00:00Z",
               deadline_at: str = "2026-09-02T03:00:00Z", expect_error: bool = False):
    payload = {
        "load_id": load["id"],
        "capacity_owner_id": bco["id"],
        "equipment_id": equipment["id"],
        "departed_at": departed_at,
        "deadline_at": deadline_at,
    }
    res = api_client.create_trip(payload, bco_headers(bco))
    return res if expect_error else get_success_data(res)


def dispatch_trip(bco: dict, trip: dict, dispatched_at: str = "2026-09-01T04:00:00Z") -> dict:
    return get_success_data(
        api_client.dispatch_trip(trip["id"], {"dispatched_at": dispatched_at}, bco_headers(bco))
    )


def complete_trip(bco: dict, trip: dict, actual_miles: int = None,
                  proof_of_delivery_code: str = None, clock: str = None) -> dict:
    """Complete a haul. The delivery instant is stamped from the logical clock,
    so `clock` sets it when the test needs a specific delivered_at."""
    if clock is not None:
        set_logical_clock(clock)
    payload = {
        "actual_miles": TEST_DEFAULTS["ACTUAL_MILES"] if actual_miles is None else actual_miles,
        "proof_of_delivery_code": proof_of_delivery_code or unique_code("POD"),
    }
    return get_success_data(api_client.complete_trip(trip["id"], payload, bco_headers(bco)))


def verify_pod(trip: dict, pod_verified: bool = True) -> dict:
    return get_success_data(
        api_client.verify_pod(
            trip["id"], {"pod_verified": pod_verified}, TEST_USERS["settlement_operator_headers"]
        )
    )


def run_haul_to_delivered(agent: dict, load: dict, bco: dict, equipment: dict,
                          clock: str = None, actual_miles: int = None, **trip_overrides) -> dict:
    """Award → cover → dispatch → complete. Returns the trip and the load."""
    payment = trip_overrides.pop("offered_pay_cents", 126000)
    _, awarded_load = award_load(agent, load, bco, offered_pay_cents=payment)
    trip = cover_load(bco, awarded_load, equipment, **trip_overrides)
    dispatch_trip(bco, trip)
    trip = complete_trip(bco, trip, actual_miles=actual_miles, clock=clock)
    return {"trip": trip, "load": awarded_load}


def run_haul_to_completed(agent: dict, load: dict, bco: dict, equipment: dict,
                          clock: str = None, actual_miles: int = None, **trip_overrides) -> dict:
    """The delivered haul plus POD verification (trip COMPLETED)."""
    result = run_haul_to_delivered(
        agent, load, bco, equipment, clock=clock, actual_miles=actual_miles, **trip_overrides
    )
    result["trip"] = verify_pod(result["trip"])
    return result


def create_draft_settlement(trip: dict, settlement_method: str = "FINAL") -> dict:
    return get_success_data(
        api_client.create_settlement(
            {"trip_id": trip["id"], "settlement_method": settlement_method},
            TEST_USERS["settlement_operator_headers"],
        )
    )


def submit_settlement(settlement: dict, agent: dict) -> dict:
    """Submit with the agent version the operator just observed."""
    return get_success_data(
        api_client.submit_settlement(
            settlement["id"],
            {"expected_network_agent_version": get_agent_version(agent["id"])},
            TEST_USERS["settlement_operator_headers"],
        )
    )


def approve_settlement(settlement: dict) -> dict:
    """Approve as the network administrator (a different identity from the
    submitting settlement clerk)."""
    return get_success_data(
        api_client.approve_settlement(settlement["id"], TEST_USERS["network_admin_headers"])
    )


def settle_settlement(settlement: dict, load: dict) -> dict:
    """Settle with the load version the operator just observed."""
    return get_success_data(
        api_client.settle_settlement(
            settlement["id"],
            {"expected_network_load_version": get_load_version(load["id"])},
            TEST_USERS["settlement_operator_headers"],
        )
    )


def setup_approved_settlement(settlement_method: str = "FINAL", clock: str = DEFAULT_CLOCK,
                              oa_enrolled: bool = True, escrow_cents: int = 250000,
                              unit_count: int = 1, actual_miles: int = None,
                              **load_overrides) -> dict:
    """
    The full settlement chain short of settling:
    clock → ACTIVE agent → customer → QUALIFIED_CLEAR BCO (funded, credentialed,
    inspected) → POSTED load → offer → accept → cover → dispatch → complete →
    verify POD → DRAFT settlement → submit → approve.

    Returns a bundle with every party the caller needs.
    """
    set_logical_clock(clock)
    agent = enroll_agent()
    customer = register_customer(agent)
    bundle = setup_qualified_bco(oa_enrolled=oa_enrolled, escrow_cents=escrow_cents,
                                 unit_count=unit_count)
    bco, equipment = bundle["bco"], bundle["equipment"]
    load = promote_load(agent, customer["customer_ref"], **load_overrides)
    haul = run_haul_to_completed(agent, load, bco, equipment[0], actual_miles=actual_miles)
    settlement = create_draft_settlement(haul["trip"], settlement_method)
    settlement = submit_settlement(settlement, agent)
    settlement = approve_settlement(settlement)
    return {
        "agent": agent,
        "customer": customer,
        "bco": bco,
        "documents": bundle["documents"],
        "equipment": equipment,
        "load": get_success_data(api_client.get_load(load["id"], TEST_USERS["network_admin_headers"])),
        "trip": haul["trip"],
        "settlement": settlement,
    }


def setup_settled_load(settlement_method: str = "FINAL", clock: str = DEFAULT_CLOCK,
                       oa_enrolled: bool = True, escrow_cents: int = 250000,
                       actual_miles: int = None, **load_overrides) -> dict:
    """The approved-settlement bundle, settled end to end."""
    bundle = setup_approved_settlement(
        settlement_method=settlement_method, clock=clock, oa_enrolled=oa_enrolled,
        escrow_cents=escrow_cents, actual_miles=actual_miles, **load_overrides
    )
    bundle["settlement"] = settle_settlement(bundle["settlement"], bundle["load"])
    bundle["load"] = get_success_data(
        api_client.get_load(bundle["load"]["id"], TEST_USERS["network_admin_headers"])
    )
    return bundle


def deep_clone_owner(bco: dict) -> dict:
    """Clone a BCO's identified attributes into a fresh row."""
    return get_success_data(
        api_client.deep_clone_capacity_owner(
            bco["id"], {"source_capacity_owner_id": bco["id"]}, TEST_USERS["network_admin_headers"]
        )
    )


def deploy_cloned_owner(clone: dict, escrow_cents: int = 250000) -> dict:
    """Give a freshly cloned owner a working fleet, credentials and escrow, then
    qualify it, so it can run a haul like any other enrollee."""
    if escrow_cents:
        post_ledger_entry(clone, escrow_cents)
    docs = file_standard_credentials(clone)
    unit = add_fleet_unit(clone)
    clone = qualify_bco(clone)
    return {"bco": clone, "documents": docs, "equipment": [unit]}


# ─── Tier 4: Threshold / boundary targeting ───────────────────────────────────

def setup_load_ready_to_cover(clock: str = DEFAULT_CLOCK, escrow_cents: int = 250000,
                              inspection_due_at: str = None, inspected_at: str = "2026-08-15T00:00:00Z",
                              **load_overrides) -> dict:
    """An awarded load whose BCO owns one inspected TRACTOR, positioned so the
    covering call is the next step under test."""
    set_logical_clock(clock)
    agent = enroll_agent()
    customer = register_customer(agent)
    overrides = {}
    if inspection_due_at:
        overrides["inspection_due_at"] = inspection_due_at
    bco = enroll_capacity_owner()
    if escrow_cents:
        post_ledger_entry(bco, escrow_cents)
    file_standard_credentials(bco)
    unit = add_fleet_unit(bco, inspected_at=inspected_at, **overrides)
    bco = qualify_bco(bco)
    load = promote_load(agent, customer["customer_ref"], **load_overrides)
    offer, awarded_load = award_load(agent, load, bco)
    return {"agent": agent, "customer": customer, "bco": bco, "equipment": unit,
            "load": awarded_load, "offer": offer}


def setup_pending_bco_with_unit(inspection_due_at: str = "2026-09-10T00:00:00Z",
                                escrow_cents: int = 250000, clock: str = DEFAULT_CLOCK,
                                unit_kwargs: dict = None) -> dict:
    """An enrolled BCO holding an escrow deposit and one unit still in
    PENDING_INSPECTION, for inspection-boundary work."""
    set_logical_clock(clock)
    bco = enroll_capacity_owner()
    if escrow_cents:
        post_ledger_entry(bco, escrow_cents)
    kwargs = {"inspect": False, "inspection_due_at": inspection_due_at}
    kwargs.update(unit_kwargs or {})
    unit = add_fleet_unit(bco, **kwargs)
    return {"bco": bco, "equipment": unit}


def setup_two_loads_one_bco(clock: str = DEFAULT_CLOCK, second_load_overrides: dict = None,
                            second_pay_cents: int = 115000) -> dict:
    """An ACTIVE agent, one QUALIFIED_CLEAR BCO, two POSTED loads and an open
    offer on each — the setup the single-commitment and tie-break claims need."""
    set_logical_clock(clock)
    agent = enroll_agent()
    customer_a = register_customer(agent)
    customer_b = register_customer(agent)
    bundle = setup_qualified_bco()
    bco, unit = bundle["bco"], bundle["equipment"][0]
    load_a = promote_load(agent, customer_a["customer_ref"])
    second = {"linehaul_revenue_cents": 160000, "fuel_surcharge_cents": 28800,
              "accessorial_revenue_cents": 9000, "dispatched_miles": 1000}
    second.update(second_load_overrides or {})
    load_b = promote_load(agent, customer_b["customer_ref"], **second)
    offer_a = post_offer(agent, load_a, bco, 126000, "2026-09-01T01:00:00Z")
    offer_b = post_offer(agent, load_b, bco, second_pay_cents, "2026-09-01T01:30:00Z")
    return {"agent": agent, "bco": bco, "equipment": unit,
            "load_a": load_a, "load_b": load_b, "offer_a": offer_a, "offer_b": offer_b}


def setup_en_route_haul(clock: str = DEFAULT_CLOCK, oa_enrolled: bool = True,
                        escrow_cents: int = 250000, **load_overrides) -> dict:
    """A load awarded and covered then dispatched, so the trip is EN_ROUTE —
    the launch point for every abort and cascade claim."""
    set_logical_clock(clock)
    agent = enroll_agent()
    customer = register_customer(agent)
    bundle = setup_qualified_bco(oa_enrolled=oa_enrolled, escrow_cents=escrow_cents)
    bco, unit = bundle["bco"], bundle["equipment"][0]
    load = promote_load(agent, customer["customer_ref"], **load_overrides)
    offer, awarded_load = award_load(agent, load, bco)
    trip = cover_load(bco, awarded_load, unit)
    trip = dispatch_trip(bco, trip)
    return {"agent": agent, "customer": customer, "bco": bco,
            "documents": bundle["documents"], "equipment": unit,
            "load": awarded_load, "offer": offer, "trip": trip}


def setup_terminated_agent_with_customer(clock: str = DEFAULT_CLOCK) -> dict:
    """An ACTIVE agent with one exclusively-owned customer account, terminated."""
    set_logical_clock(clock)
    agent = enroll_agent()
    customer = register_customer(agent)
    before = get_success_data(api_client.get_agent(agent["id"], TEST_USERS["network_admin_headers"]))
    # PRD §2.9 re-evaluates every clock-derived field on the next read, so the
    # account's pre-termination state has to be read before the termination.
    customer_before = get_success_data(
        api_client.get_customer_account(customer["id"], TEST_USERS["network_admin_headers"])
    )
    agent = get_success_data(
        api_client.terminate_agent(
            agent["id"], {"reason_code": "PORTFOLIO_EXIT"}, TEST_USERS["network_admin_headers"]
        )
    )
    return {"agent": agent, "customer": customer, "agent_before": before,
            "customer_before": customer_before}


# ─── Tier 5: Finalization / terminal-state helpers ────────────────────────────

def setup_out_of_service_bco_with_unit(clock: str = DEFAULT_CLOCK) -> dict:
    """A QUALIFIED owner with two inspected units, then one unit placed out of
    service — the two-dimension posture setup."""
    set_logical_clock(clock)
    bundle = setup_qualified_bco(unit_count=2)
    bco, units = bundle["bco"], bundle["equipment"]
    unit_after = get_success_data(
        api_client.place_equipment_out_of_service(
            units[1]["id"], {"reason_code": "BRAKE_SYSTEM_FAILURE"},
            TEST_USERS["safety_reviewer_headers"],
        )
    )
    return {"bco": bco, "equipment": units, "unit_after": unit_after}


def setup_settlement_awaiting_submit(clock: str = DEFAULT_CLOCK, oa_enrolled: bool = True,
                                     escrow_cents: int = 250000, **load_overrides) -> dict:
    """A COMPLETED trip with a DRAFT FINAL settlement that has not been
    submitted yet."""
    set_logical_clock(clock)
    agent = enroll_agent()
    customer = register_customer(agent)
    bundle = setup_qualified_bco(oa_enrolled=oa_enrolled, escrow_cents=escrow_cents)
    bco, unit = bundle["bco"], bundle["equipment"][0]
    load = promote_load(agent, customer["customer_ref"], **load_overrides)
    haul = run_haul_to_completed(agent, load, bco, unit)
    settlement = create_draft_settlement(haul["trip"], "FINAL")
    return {"agent": agent, "customer": customer, "bco": bco, "equipment": unit,
            "load": haul["load"], "trip": haul["trip"], "settlement": settlement}


def setup_advance_position(clock: str = DEFAULT_CLOCK, deposit_cents: int = 250000,
                           advance_cents: int = 200000) -> dict:
    """A BCO holding a known escrow deposit, then a posted advance through the
    normal business path."""
    set_logical_clock(clock)
    bco = enroll_capacity_owner()
    post_ledger_entry(bco, deposit_cents)
    before = get_bco(bco["id"])
    advance = get_success_data(
        api_client.run_advance_post(
            {"capacity_owner_id": bco["id"], "amount_cents": advance_cents,
             "effective_at": "2026-09-01T05:00:00Z"},
            TEST_USERS["settlement_operator_headers"],
        )
    )
    return {"bco": bco, "before": before, "advance": advance, "deposit_cents": deposit_cents}


def setup_haul_to_delivered(clock: str = DEFAULT_CLOCK, **load_overrides) -> dict:
    """An ACTIVE agent, one QUALIFIED_CLEAR BCO and one load run all the way to
    DELIVERED, so the fee schedule has one eligible and one paid load."""
    set_logical_clock(clock)
    agent = enroll_agent()
    customer = register_customer(agent)
    bundle = setup_qualified_bco()
    bco, unit = bundle["bco"], bundle["equipment"][0]
    load = promote_load(agent, customer["customer_ref"], **load_overrides)
    haul = run_haul_to_delivered(agent, load, bco, unit)
    return {"agent": agent, "customer": customer, "bco": bco,
            "equipment": unit, "load": haul["load"], "trip": haul["trip"]}


def setup_sealed_equipment_with_closed_trip(clock: str = DEFAULT_CLOCK,
                                            delivered_at: str = "2026-09-02T10:00:00Z") -> dict:
    """A BCO whose only unit closed a haul delivering at `delivered_at`, plus a
    second load already awarded to the same BCO and ready to be covered — the
    launch point for the turnaround-buffer boundary."""
    set_logical_clock(clock)
    agent = enroll_agent()
    customer_a = register_customer(agent)
    customer_b = register_customer(agent)
    bundle = setup_qualified_bco()
    bco, unit = bundle["bco"], bundle["equipment"][0]

    load_a = promote_load(agent, customer_a["customer_ref"])
    offer_a = post_offer(agent, load_a, bco, 126000, "2026-09-01T01:00:00Z")
    accept_offer(bco, offer_a)
    awarded_a = get_success_data(api_client.get_load(load_a["id"], TEST_USERS["network_admin_headers"]))
    trip_a = cover_load(bco, awarded_a, unit, departed_at="2026-09-01T03:00:00Z",
                        deadline_at=delivered_at)
    dispatch_trip(bco, trip_a)
    trip_a = complete_trip(bco, trip_a, clock=delivered_at)
    verify_pod(trip_a)

    load_b = promote_load(agent, customer_b["customer_ref"])
    offer_b = post_offer(agent, load_b, bco, 118000, "2026-09-02T11:00:00Z")
    accept_offer(bco, offer_b, accepted_at="2026-09-02T11:30:00Z")
    next_load = get_success_data(api_client.get_load(load_b["id"], TEST_USERS["network_admin_headers"]))

    delivered_trip = get_success_data(api_client.get_trip(trip_a["id"], TEST_USERS["network_admin_headers"]))
    return {"agent": agent, "bco": bco, "equipment": unit,
            "trip": delivered_trip, "next_load": next_load}


def setup_eligible_loads(agent: dict, customer_ref: str, count: int) -> list:
    """Create `count` loads in the AWARDED status for one agent.

    Each load needs its own capacity owner: a truck may only hold one non-terminal
    load, so `count` owners are enrolled, funded, credentialed, equipped and
    qualified, and each is awarded exactly one load.
    """
    awarded = []
    for _ in range(count):
        bundle = setup_qualified_bco()
        bco, unit = bundle["bco"], bundle["equipment"][0]
        load = promote_load(agent, customer_ref)
        offer = post_offer(agent, load, bco, 126000, "2026-09-01T01:00:00Z")
        accept_offer(bco, offer)
        awarded.append(
            get_success_data(api_client.get_load(load["id"], TEST_USERS["network_admin_headers"]))
        )
    return awarded


def setup_oa_clone_pair(settlement_method: str = "PROVISIONAL") -> dict:
    """Two capacity owners that differ only in `oa_enrolled`: an enrolled one and
    an identical non-enrolled one, each carrying byte-identical settlement
    inputs. Each runs an identical haul on the same revenue mix, so only the
    enrollment gate distinguishes their occupational-accident premiums.

    PRD §3.2 states that the administrative deep-clone capability copies
    `oa_enrolled` from its source verbatim, so the non-enrolled twin is enrolled
    directly rather than cloned from the enrolled owner.
    """
    set_logical_clock()
    agent = enroll_agent()
    customer = register_customer(agent)
    origin = setup_qualified_bco(oa_enrolled=True)
    twin = setup_qualified_bco(oa_enrolled=False)

    enrolled_load = promote_load(agent, customer["customer_ref"])
    enrolled_run = run_haul_to_completed(
        agent, enrolled_load, origin["bco"], origin["equipment"][0]
    )
    twin_load = promote_load(agent, customer["customer_ref"])
    twin_run = run_haul_to_completed(agent, twin_load, twin["bco"], twin["equipment"][0])

    enrolled_cost = get_success_data(
        api_client.evaluate_load_settlement(
            enrolled_load["id"], {"settlement_method": settlement_method},
            TEST_USERS["settlement_operator_headers"],
        )
    )
    twin_cost = get_success_data(
        api_client.evaluate_load_settlement(
            twin_load["id"], {"settlement_method": settlement_method},
            TEST_USERS["settlement_operator_headers"],
        )
    )
    return {
        "agent": agent, "customer": customer,
        "origin": origin, "twin": twin["bco"],
        "enrolled_trip": enrolled_run["trip"], "twin_trip": twin_run["trip"],
        "enrolled_cost": enrolled_cost, "twin_cost": twin_cost,
    }


def find_ledger_entry(bco: dict, transaction_type: str) -> dict:
    """The first ledger row of the given type for a BCO."""
    data, _meta = validate_paginated(
        api_client.list_capacity_owner_ledger(
            bco["id"],
            TEST_USERS["settlement_operator_headers"],
            params={"transaction_type": transaction_type},
        )
    )
    assert data, f"expected at least one {transaction_type} ledger row"
    return data[0]