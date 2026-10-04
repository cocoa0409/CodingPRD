"""Composite setup helpers (PRD §3 workflows).

Every fixture builds its preconditions from scratch via the public API — the
harness restarts the server before every test, so nothing persists. Setup
calls use the lenient get_success_data() validator so a setup failure surfaces
as a clear error, not a confusing assertion.

Identity threading (PRD §2.1): SupplierManager writes always carry the owning
supplier's id; customer-scoped writes always carry the owning customer's id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS as D
from .factories import (
    create_program_payload, create_supplier_payload, create_customer_payload,
    create_aircraft_unit_payload, create_workforce_plan_payload, hire_payload,
    create_rate_case_payload, create_commitment_payload, place_order_payload,
    create_work_package_payload, travel_work_package_payload,
    create_escape_rework_order_payload, close_rework_order_payload,
    report_escape_payload, begin_root_cause_payload, disposition_payload,
    schedule_flight_test_payload, record_outcome_payload,
    conduct_walkthrough_payload, create_storage_preservation_payload,
    create_delivery_negotiation_payload, counter_negotiation_payload,
    set_clock_payload,
)
from .test_users import (
    TEST_USERS, make_supplier_manager_headers, make_customer_headers,
    make_quality_inspector_headers,
)

_ADMIN = TEST_USERS["program_admin_headers"]
_PLANNER = TEST_USERS["production_planner_headers"]
_LINE = TEST_USERS["line_manager_headers"]
_DELIVERY = TEST_USERS["delivery_manager_headers"]


# --- Base creators (PRD §2.4, §3.1) ---

def set_clock(to_iso8601: str):
    """Move the server's logical clock (PRD §2.4)."""
    resp = api_client.set_clock(set_clock_payload(to_iso8601), _ADMIN)
    return get_success_data(resp)


def create_program(**overrides) -> dict:
    resp = api_client.create_program(create_program_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def create_supplier(**overrides) -> dict:
    resp = api_client.create_supplier(create_supplier_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def create_customer(**overrides) -> dict:
    resp = api_client.create_customer(create_customer_payload(**overrides), _ADMIN)
    return get_success_data(resp)


def get_program(program_id: str) -> dict:
    """Fresh read of a program (live computed fields recompute on read, PRD §2.9)."""
    return get_success_data(api_client.get_program(program_id, _ADMIN))


def get_program_version(program_id: str) -> int:
    return get_program(program_id)["version"]


# --- Tier 2: entity hierarchy (program -> customer -> aircraft) ---

def setup_program_with_customer(program_overrides=None, customer_overrides=None):
    """Program + registered customer. Returns (program, customer)."""
    program = create_program(**(program_overrides or {}))
    customer = create_customer(**(customer_overrides or {}))
    return program, customer


def setup_aircraft(program_overrides=None, customer_overrides=None,
                   aircraft_overrides=None, line_number=None):
    """Program + customer + one aircraft (IN_PRODUCTION / CLEAR / NOT_STARTED).

    Returns (program, customer, aircraft).
    """
    program, customer = setup_program_with_customer(program_overrides, customer_overrides)
    overrides = dict(aircraft_overrides or {})
    if line_number is not None:
        overrides["line_number"] = line_number
    resp = api_client.create_aircraft_unit(
        program["id"], create_aircraft_unit_payload(customer["id"], **overrides), _PLANNER
    )
    aircraft = get_success_data(resp)
    return program, customer, aircraft


def add_aircraft(program_id: str, customer_id: str, **overrides) -> dict:
    """Second (or later) aircraft on an existing program."""
    resp = api_client.create_aircraft_unit(
        program_id, create_aircraft_unit_payload(customer_id, **overrides), _PLANNER
    )
    return get_success_data(resp)


# --- Work packages and traveled work (PRD §3.4, §3.5) ---

def add_work_package(aircraft_id: str, **overrides) -> dict:
    resp = api_client.create_work_package(
        aircraft_id, create_work_package_payload(**overrides), _LINE
    )
    return get_success_data(resp)


def complete_work_package(work_package_id: str) -> dict:
    return get_success_data(api_client.complete_work_package(work_package_id, _LINE))


def travel_work_package(work_package_id: str, traveled_hours=4) -> dict:
    resp = api_client.travel_work_package(
        work_package_id, travel_work_package_payload(traveled_hours), _LINE
    )
    return get_success_data(resp)


def travel_and_get_rework(aircraft_id: str, work_package_id: str, traveled_hours=4):
    """Travel a package and return (work_package, spawned TRAVELED_WORK rework order).

    The rework order is a cascade side effect of travel (PRD §3.4); it is
    discovered via the work-package reverse listing.
    """
    wp = travel_work_package(work_package_id, traveled_hours)
    resp = api_client.list_work_package_rework_orders(work_package_id, _LINE)
    orders = get_success_data(resp)
    assert len(orders) == 1, f"expected exactly one spawned rework order, got {len(orders)}"
    return wp, orders[0]


def setup_assembly_complete_aircraft(program_overrides=None, customer_overrides=None,
                                     aircraft_overrides=None, line_number=None,
                                     work_package_overrides=None):
    """Aircraft with one completed work package -> production_status ASSEMBLY_COMPLETE
    via the bubble-up rule (PRD §3.4). Returns (program, customer, aircraft, work_package).
    """
    program, customer, aircraft = setup_aircraft(
        program_overrides, customer_overrides, aircraft_overrides, line_number
    )
    wp = add_work_package(aircraft["id"], **(work_package_overrides or {}))
    complete_work_package(wp["id"])
    aircraft = get_success_data(api_client.get_aircraft_unit(aircraft["id"], _ADMIN))
    return program, customer, aircraft, wp


# --- Tier 3: delivery acceptance pipeline (PRD §3.8) ---

def begin_delivery(aircraft_id: str) -> dict:
    return get_success_data(api_client.begin_delivery(aircraft_id, _DELIVERY))


def setup_aircraft_in_flight_testing(program_overrides=None, customer_overrides=None,
                                     aircraft_overrides=None, line_number=None):
    """ASSEMBLY_COMPLETE aircraft with delivery_status FLIGHT_TESTING.
    Returns (program, customer, aircraft)."""
    program, customer, aircraft, _wp = setup_assembly_complete_aircraft(
        program_overrides, customer_overrides, aircraft_overrides, line_number
    )
    begin_delivery(aircraft["id"])
    aircraft = get_success_data(api_client.get_aircraft_unit(aircraft["id"], _ADMIN))
    return program, customer, aircraft


def schedule_flight_test(aircraft_id: str, **overrides) -> dict:
    resp = api_client.schedule_flight_test(
        aircraft_id, schedule_flight_test_payload(**overrides), _DELIVERY
    )
    return get_success_data(resp)


def schedule_and_pass_flight_test(aircraft_id: str, **overrides) -> dict:
    """One SCHEDULED test recorded PASS (PRD §3.8: COMPLETED with outcome PASS)."""
    ft = schedule_flight_test(aircraft_id, **overrides)
    resp = api_client.record_flight_test_outcome(ft["id"], record_outcome_payload("PASS"), _DELIVERY)
    return get_success_data(resp)


def setup_aircraft_config_verified(program_overrides=None, customer_overrides=None,
                                   aircraft_overrides=None, line_number=None):
    """Aircraft walked to CONFIG_VERIFIED: ASSEMBLY_COMPLETE -> FLIGHT_TESTING,
    one PASS flight test, verify-configuration (PRD §3.8).
    Returns (program, customer, aircraft, flight_test)."""
    program, customer, aircraft = setup_aircraft_in_flight_testing(
        program_overrides, customer_overrides, aircraft_overrides, line_number
    )
    ft = schedule_and_pass_flight_test(aircraft["id"])
    get_success_data(api_client.verify_configuration(aircraft["id"], _DELIVERY))
    aircraft = get_success_data(api_client.get_aircraft_unit(aircraft["id"], _ADMIN))
    return program, customer, aircraft, ft


def conduct_walkthrough(aircraft_id: str, customer_id: str, snag_count=0) -> dict:
    """Customer-side call: X-User-ID must equal the aircraft's customer_id (PRD §3.8)."""
    resp = api_client.conduct_walkthrough(
        aircraft_id, conduct_walkthrough_payload(snag_count), make_customer_headers(customer_id)
    )
    return get_success_data(resp)


def setup_aircraft_walkthrough_passed(program_overrides=None, customer_overrides=None,
                                      aircraft_overrides=None, line_number=None):
    """Aircraft at WALKTHROUGH_PASSED (snag-free walkthrough). Returns (program, customer, aircraft)."""
    program, customer, aircraft, _ft = setup_aircraft_config_verified(
        program_overrides, customer_overrides, aircraft_overrides, line_number
    )
    conduct_walkthrough(aircraft["id"], customer["id"], snag_count=0)
    aircraft = get_success_data(api_client.get_aircraft_unit(aircraft["id"], _ADMIN))
    return program, customer, aircraft


def setup_aircraft_accepted(program_overrides=None, customer_overrides=None,
                            aircraft_overrides=None, line_number=None):
    """Full lifecycle to delivery acceptance: production DELIVERED, delivery ACCEPTED
    (PRD §3.8). Returns (program, customer, aircraft)."""
    program, customer, aircraft = setup_aircraft_walkthrough_passed(
        program_overrides, customer_overrides, aircraft_overrides, line_number
    )
    resp = api_client.accept_delivery(aircraft["id"], make_customer_headers(customer["id"]))
    aircraft = get_success_data(resp)
    return program, customer, aircraft


# --- Tier 3: quality escape evidentiary chain (PRD §3.6) ---

def create_open_escape(aircraft_id: str, severity="MAJOR", description="Nonconformance",
                       reporter_id="insp-1") -> dict:
    """Report an escape; aircraft moves to quality HOLD (PRD §3.6)."""
    resp = api_client.report_quality_escape(
        aircraft_id,
        report_escape_payload(severity=severity, description=description),
        make_quality_inspector_headers(reporter_id),
    )
    return get_success_data(resp)


def create_escape_in_root_cause(aircraft_id: str, severity="MAJOR",
                                description="Nonconformance", reporter_id="insp-1",
                                conformance_refs=None) -> dict:
    """Escape walked OPEN -> notified -> ROOT_CAUSE with conformance refs (PRD §3.6)."""
    esc = create_open_escape(aircraft_id, severity, description, reporter_id)
    get_success_data(
        api_client.notify_regulator(esc["id"], make_quality_inspector_headers(reporter_id))
    )
    resp = api_client.begin_root_cause(
        esc["id"], begin_root_cause_payload(conformance_refs),
        make_quality_inspector_headers(reporter_id),
    )
    return get_success_data(resp)


def create_dispositioned_escape(aircraft_id: str, severity="MAJOR",
                                description="Nonconformance", reporter_id="insp-1",
                                dispositioner_id="insp-2",
                                disposition_code="USE_AS_IS") -> dict:
    """Escape in DISPOSITIONED; dispositioner differs from reporter (segregation,
    PRD §3.6)."""
    esc = create_escape_in_root_cause(aircraft_id, severity, description, reporter_id)
    resp = api_client.disposition_escape(
        esc["id"], disposition_payload(disposition_code),
        make_quality_inspector_headers(dispositioner_id),
    )
    return get_success_data(resp)


def create_closed_escape(aircraft_id: str, severity="MAJOR",
                         description="Nonconformance", reporter_id="insp-1",
                         dispositioner_id="insp-2",
                         disposition_code="USE_AS_IS") -> dict:
    """Escape fully closed (DISPOSITIONED -> CLOSED); aircraft quality returns to
    CLEAR when it is the last open escape (PRD §3.6)."""
    esc = create_dispositioned_escape(
        aircraft_id, severity, description, reporter_id, dispositioner_id, disposition_code
    )
    resp = api_client.close_escape(esc["id"], make_quality_inspector_headers(dispositioner_id))
    return get_success_data(resp)


# --- Rework close/credit (PRD §3.5) ---

def create_escape_rework_order(escape_id: str, estimated_hours=3, inspector_id="insp-1") -> dict:
    resp = api_client.create_escape_rework_order(
        escape_id, create_escape_rework_order_payload(estimated_hours),
        make_quality_inspector_headers(inspector_id),
    )
    return get_success_data(resp)


def close_rework_order(rework_order_id: str, actual_hours=4, parts_cents=0) -> dict:
    resp = api_client.close_rework_order(
        rework_order_id, close_rework_order_payload(actual_hours, parts_cents), _LINE
    )
    return get_success_data(resp)


def credit_rework_order(rework_order_id: str) -> dict:
    return get_success_data(api_client.credit_rework_order(rework_order_id, _LINE))


# --- Storage and preservation (PRD §3.7) ---

def create_storage(aircraft_id: str, **overrides) -> dict:
    """Move an ASSEMBLY_COMPLETE aircraft into storage (-> IN_STORAGE)."""
    resp = api_client.create_storage_preservation(
        aircraft_id, create_storage_preservation_payload(**overrides), _DELIVERY
    )
    return get_success_data(resp)


def setup_aircraft_in_storage(program_overrides=None, customer_overrides=None,
                              aircraft_overrides=None, line_number=None,
                              storage_overrides=None):
    """ASSEMBLY_COMPLETE aircraft stored in a bay (ACTIVE preservation).
    Returns (program, customer, aircraft, storage)."""
    program, customer, aircraft, _wp = setup_assembly_complete_aircraft(
        program_overrides, customer_overrides, aircraft_overrides, line_number
    )
    storage = create_storage(aircraft["id"], **(storage_overrides or {}))
    aircraft = get_success_data(api_client.get_aircraft_unit(aircraft["id"], _ADMIN))
    return program, customer, aircraft, storage


# --- Supplier capacity commitments (PRD §3.3) ---

def setup_confirmed_commitment(program_id: str, component_code=None, committed_rate=None,
                               lead_time_months=None, unit_price_cents=None,
                               supplier_overrides=None):
    """Supplier + commitment confirmed (DRAFT -> CONFIRMED). The SupplierManager
    header carries the owning supplier's id throughout (PRD §2.1).
    Returns (supplier, commitment)."""
    supplier = create_supplier(**(supplier_overrides or {}))
    sm_headers = make_supplier_manager_headers(supplier["id"])
    resp = api_client.create_capacity_commitment(
        supplier["id"],
        create_commitment_payload(
            program_id,
            component_code=component_code or D["COMPONENT_CODE"],
            committed_rate_per_month=committed_rate or D["COMMITTED_RATE_PER_MONTH"],
            lead_time_months=lead_time_months or D["LEAD_TIME_MONTHS"],
            unit_price_cents=unit_price_cents or D["UNIT_PRICE_CENTS"],
        ),
        sm_headers,
    )
    commitment = get_success_data(resp)
    commitment = get_success_data(api_client.confirm_commitment(commitment["id"], sm_headers))
    return supplier, commitment


def place_order(commitment_id: str, supplier_id: str, quantity=None,
                assumed_rate_per_month=None, required_by_month=None) -> dict:
    payload = place_order_payload(
        quantity=quantity if quantity is not None else D["ORDER_QUANTITY"],
        assumed_rate_per_month=(
            assumed_rate_per_month if assumed_rate_per_month is not None
            else D["ASSUMED_RATE_PER_MONTH"]
        ),
        required_by_month=required_by_month or D["REQUIRED_BY_MONTH"],
    )
    resp = api_client.place_order(
        commitment_id, payload, make_supplier_manager_headers(supplier_id)
    )
    return get_success_data(resp)


def setup_ordered_commitment(program_id: str, quantity=None, assumed_rate_per_month=None,
                             required_by_month=None, **commitment_kwargs):
    """Supplier + CONFIRMED commitment with one order placed (-> ORDERED).
    Returns (supplier, commitment)."""
    supplier, commitment = setup_confirmed_commitment(program_id, **commitment_kwargs)
    commitment = place_order(
        commitment["id"], supplier["id"], quantity, assumed_rate_per_month, required_by_month
    )
    return supplier, commitment


# --- Workforce plans (PRD §3.1) ---

def create_workforce_plan(program_id: str, skill_code=None, required_headcount=None) -> dict:
    resp = api_client.create_workforce_plan(
        program_id,
        create_workforce_plan_payload(
            skill_code=skill_code or f"SKILL-{required_headcount or D['REQUIRED_HEADCOUNT']}",
            required_headcount=required_headcount or D["REQUIRED_HEADCOUNT"],
        ),
        _PLANNER,
    )
    return get_success_data(resp)


def hire(workforce_plan_id: str, count: int) -> dict:
    return get_success_data(api_client.hire(workforce_plan_id, hire_payload(count), _PLANNER))


# --- Tier 4: gating-ready program (PRD §2.9, §3.2) ---

def setup_gating_ready_program(components=("ENG", "LG"), committed_rate=8,
                               workforce=(("AVIONICS", 10, 10), ("STRUCTURES", 10, 7)),
                               program_overrides=None):
    """Program with one CONFIRMED commitment per component code at `committed_rate`
    and workforce plans hired per (skill, required, hired) triples.

    With the defaults (2 components at rate 8, 17/20 hired) the live readiness
    against rate <= 8 is min(100.0, 85.0) - 0.0 = 85.0 (PRD §2.9).

    Returns dict(program=..., suppliers=[...], commitments=[...], plans=[...]).
    """
    overrides = {"required_component_codes": len(components)}
    overrides.update(program_overrides or {})
    program = create_program(**overrides)
    suppliers, commitments, plans = [], [], []
    for code in components:
        supplier, commitment = setup_confirmed_commitment(
            program["id"], component_code=code, committed_rate=committed_rate
        )
        suppliers.append(supplier)
        commitments.append(commitment)
    for skill_code, required, hired_count in workforce:
        plan = create_workforce_plan(program["id"], skill_code, required)
        if hired_count:
            plan = hire(plan["id"], hired_count)
        plans.append(plan)
    return {
        "program": program,
        "suppliers": suppliers,
        "commitments": commitments,
        "plans": plans,
    }


# --- Rate cases (PRD §3.2); OCC: create carries the program's current version ---

def create_rate_case(program_id: str, proposed_rate=None, effective_month=None,
                     demand_backlog_units=None) -> dict:
    resp = api_client.create_rate_case(
        program_id,
        create_rate_case_payload(
            get_program_version(program_id),
            proposed_rate=proposed_rate or D["PROPOSED_RATE"],
            effective_month=effective_month or D["EFFECTIVE_MONTH"],
            demand_backlog_units=(
                demand_backlog_units if demand_backlog_units is not None
                else D["DEMAND_BACKLOG_UNITS"]
            ),
        ),
        _PLANNER,
    )
    return get_success_data(resp)


def create_rate_case_in_state(program_id: str, target_state: str, **kwargs) -> dict:
    """Walk a rate case to DRAFT, ANNOUNCED, or GATED_REVIEW (PRD §3.2)."""
    case = create_rate_case(program_id, **kwargs)
    if target_state == "DRAFT":
        return case
    case = get_success_data(api_client.announce_rate_case(case["id"], _PLANNER))
    if target_state == "ANNOUNCED":
        return case
    if target_state == "GATED_REVIEW":
        case = get_success_data(api_client.request_gating_review(case["id"], _PLANNER))
        return case
    raise ValueError(f"unsupported target_state {target_state!r}")


# --- Delivery negotiations (PRD §3.9) ---

def setup_negotiation(aircraft_id: str, proposed_delivery_date=None,
                      compensation_variant=None) -> dict:
    """Round-1 PROPOSED negotiation opened by the DeliveryManager; customer_id is
    copied from the aircraft (PRD §3.9)."""
    resp = api_client.create_delivery_negotiation(
        aircraft_id,
        create_delivery_negotiation_payload(
            proposed_delivery_date=proposed_delivery_date or D["PROPOSED_DELIVERY_DATE"],
            compensation_variant=compensation_variant or D["COMPENSATION_VARIANT"],
        ),
        _DELIVERY,
    )
    return get_success_data(resp)


def counter_negotiation(negotiation: dict, customer_id: str,
                        proposed_delivery_date="2026-10-12",
                        compensation_variant="CONTRACTUAL_LIQUIDATED") -> dict:
    """One turn-taking counter. The actor follows the standing status: PROPOSED
    awaits the Customer, COUNTERED awaits the DeliveryManager (PRD §3.9). OCC
    version is threaded from the passed negotiation."""
    if negotiation["status"] == "PROPOSED":
        headers = make_customer_headers(customer_id)
    else:
        headers = _DELIVERY
    resp = api_client.counter_negotiation(
        negotiation["id"],
        counter_negotiation_payload(
            negotiation["version"],
            proposed_delivery_date=proposed_delivery_date,
            compensation_variant=compensation_variant,
        ),
        headers,
    )
    return get_success_data(resp)


def drive_negotiation_to_round(negotiation: dict, customer_id: str, target_round=6) -> dict:
    """Counter back and forth until round_number == target_round (max 6, PRD §3.9).
    Dates step one day per round to keep each round's basis distinct."""
    month, day = 10, 12
    while negotiation["round_number"] < target_round:
        negotiation = counter_negotiation(
            negotiation, customer_id,
            proposed_delivery_date=f"2026-{month:02d}-{day:02d}",
        )
        day += 1
    return negotiation
