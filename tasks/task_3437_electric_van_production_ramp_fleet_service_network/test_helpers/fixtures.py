"""Composite setup helpers for the Electric Van Fleet Ops API.

Every fixture builds its preconditions from scratch via PRD-declared
endpoints (each test runs against a freshly restarted, empty server) and uses
the lenient get_success_data() validator so setup failures surface as clear
"Setup failed" errors.

Identity threading: FleetManager is the entity-backed role. Every
ownership-gated call (depot create, charging-project create, order
create/submit/cancel, visit create/cancel, claim create) is made with
make_fleet_manager_headers(customer["id"]) — never the shared TEST_USERS
fallback.

All fixture datetimes are on/after the logical-clock start of
2026-09-01T00:00:00Z.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import LOGICAL_CLOCK_DEFAULT
from .factories import (
    DEFAULTS,
    adjudicate_payload,
    battery_health_payload,
    campaign_result_payload,
    clock_payload,
    close_month_payload,
    create_battery_module_payload,
    create_charging_project_payload,
    create_depot_payload,
    create_fleet_customer_payload,
    create_mobile_van_payload,
    create_parts_stock_payload,
    create_service_center_payload,
    create_service_visit_payload,
    create_software_campaign_payload,
    create_supplier_payload,
    create_uptime_contract_payload,
    create_vehicle_order_payload,
    create_vehicle_payload,
    create_warranty_claim_payload,
    diagnose_payload,
    downtime_event_payload,
    make_vin,
    readiness_audit_payload,
    transition_payload,
    vehicle_transition_payload,
)
from .test_users import (
    TEST_USERS,
    make_fleet_manager_headers,
    make_quality_inspector_headers,
)

_ADMIN = TEST_USERS["platform_admin_headers"]
_PLANNER = TEST_USERS["production_planner_headers"]
_INSPECTOR = TEST_USERS["quality_inspector_headers"]
_COMPLIANCE = TEST_USERS["compliance_officer_headers"]
_COORDINATOR = TEST_USERS["charging_coordinator_headers"]
_DISPATCHER = TEST_USERS["service_dispatcher_headers"]
_TECHNICIAN = TEST_USERS["service_technician_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
_RELEASE = TEST_USERS["release_manager_headers"]
_TELEMATICS = TEST_USERS["telematics_ingestion_headers"]


# =============================================================================
# Tier 0: logical clock
# =============================================================================

def set_logical_clock(to_iso8601=LOGICAL_CLOCK_DEFAULT):
    """Advance the logical clock (unprefixed platform endpoint, 200)."""
    return get_success_data(api_client.set_current_utc(clock_payload(to_iso8601), _ADMIN))


# =============================================================================
# Tier 1: single-entity creation and state progression
# =============================================================================

def create_fleet_customer(**overrides):
    """Register a fleet customer (201). Returns the FleetCustomer."""
    return get_success_data(
        api_client.create_fleet_customer(create_fleet_customer_payload(**overrides), _ADMIN)
    )


def create_depot(customer, **overrides):
    """Create a depot owned by customer (201). Identity-threaded."""
    headers = make_fleet_manager_headers(customer["id"])
    payload = create_depot_payload(customer["id"], **overrides)
    return get_success_data(api_client.create_depot(payload, headers))


def create_supplier(**overrides):
    """Register a supplier as the shared ProductionPlanner (201)."""
    return get_success_data(
        api_client.create_supplier(create_supplier_payload(**overrides), _PLANNER)
    )


def register_module(supplier_id, module_serial=None, pack_kwh=77, planner_headers=None):
    """Register a battery module (201); lands REGISTERED with failure_count 0."""
    serial = module_serial if module_serial is not None else f"M-{supplier_id[:4]}-001"
    payload = create_battery_module_payload(supplier_id, module_serial=serial, pack_kwh=pack_kwh)
    return get_success_data(
        api_client.create_battery_module(payload, planner_headers or _PLANNER)
    )


def transition_module(module_id, to_state, headers=None):
    """Drive a battery-module transition (200). Caller picks the role headers:
    QualityInspector for IN_QA/PASSED/FAILED, ProductionPlanner for REWORK."""
    return get_success_data(
        api_client.transition_battery_module(module_id, transition_payload(to_state), headers or _INSPECTOR)
    )


def create_passed_module(supplier_id, module_serial=None, pack_kwh=77):
    """Register a module and walk REGISTERED -> IN_QA -> PASSED with a
    distinct inspector (segregation: the shared planner registered it)."""
    module = register_module(supplier_id, module_serial=module_serial, pack_kwh=pack_kwh)
    transition_module(module["id"], "IN_QA", _INSPECTOR)
    return transition_module(module["id"], "PASSED", _INSPECTOR)


def create_passed_modules(supplier_id, count, pack_kwh=77, serial_prefix="M"):
    """N PASSED modules with deterministic serials. Returns list of modules."""
    modules = []
    for i in range(1, count + 1):
        modules.append(
            create_passed_module(supplier_id, module_serial=f"{serial_prefix}-{i:03d}", pack_kwh=pack_kwh)
        )
    return modules


def audit_supplier(supplier_id, on_time_pct, first_pass_yield_pct, open_corrective_actions,
                   auditor_headers=None):
    """Record a readiness audit (200) and return the recomputed Supplier."""
    payload = readiness_audit_payload(on_time_pct, first_pass_yield_pct, open_corrective_actions)
    return get_success_data(
        api_client.create_readiness_audit(supplier_id, payload, auditor_headers or _INSPECTOR)
    )


def audit_supplier_to_tier_c(supplier_id, auditor_headers=None):
    """Force tier C (fails both A and B conjunctive conditions)."""
    return audit_supplier(supplier_id, 50.0, 60.0, 5, auditor_headers=auditor_headers)


def audit_supplier_to_tier_a(supplier_id, auditor_headers=None):
    """Force tier A at the inclusive boundary values."""
    return audit_supplier(supplier_id, 95.0, 98.0, 0, auditor_headers=auditor_headers)


def audit_supplier_to_tier_b(supplier_id, auditor_headers=None):
    """Force tier B (below A, within the B envelope)."""
    return audit_supplier(supplier_id, 90.0, 93.0, 1, auditor_headers=auditor_headers)


# ---------------------------------------------------------------------------
# Vehicle orders
# ---------------------------------------------------------------------------

def create_order(customer, depot, supplier, **overrides):
    """Place a DRAFT vehicle order for the owning customer (201)."""
    headers = make_fleet_manager_headers(customer["id"])
    payload = create_vehicle_order_payload(customer["id"], depot["id"], supplier["id"], **overrides)
    return get_success_data(api_client.create_vehicle_order(payload, headers))


def submit_order(order, customer):
    """DRAFT -> SUBMITTED by the owning fleet manager (200)."""
    headers = make_fleet_manager_headers(customer["id"])
    return get_success_data(
        api_client.transition_vehicle_order(order["id"], transition_payload("SUBMITTED"), headers)
    )


def confirm_order(order, exemption_document_ref=None):
    """SUBMITTED/FRANCHISE_HOLD -> CONFIRMED by a ComplianceOfficer (200);
    promised_delivery_date is computed on entry."""
    payload = transition_payload("CONFIRMED", exemption_document_ref=exemption_document_ref)
    return get_success_data(api_client.transition_vehicle_order(order["id"], payload, _COMPLIANCE))


def hold_order(order):
    """SUBMITTED -> FRANCHISE_HOLD by a ComplianceOfficer (200)."""
    return get_success_data(
        api_client.transition_vehicle_order(order["id"], transition_payload("FRANCHISE_HOLD"), _COMPLIANCE)
    )


def create_submitted_order(customer, depot, supplier, **overrides):
    """Order walked DRAFT -> SUBMITTED. Returns the SUBMITTED order."""
    order = create_order(customer, depot, supplier, **overrides)
    return submit_order(order, customer)


def create_confirmed_order(customer, depot, supplier, exemption_document_ref=None, **overrides):
    """Order walked DRAFT -> SUBMITTED -> CONFIRMED. Returns the CONFIRMED
    order (its version field is the OCC basis for the first VIN registration)."""
    order = create_submitted_order(customer, depot, supplier, **overrides)
    return confirm_order(order, exemption_document_ref=exemption_document_ref)


def read_order(order_id, headers=None):
    return get_success_data(api_client.get_vehicle_order(order_id, headers or _PLANNER))


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

def register_vehicle_raw(order_id, module_id, vin, expected_vehicle_order_version, headers=None):
    """Raw VIN registration returning the Response — for OCC / error tests
    that need the unvalidated envelope (e.g. ERR_STALE_VERSION, 201-vs-error)."""
    payload = create_vehicle_payload(order_id, module_id, vin, expected_vehicle_order_version)
    return api_client.create_vehicle(payload, headers or _PLANNER)


def register_vehicle(order, module_id, vin):
    """Register a VIN against an order (201): refetches the order so the OCC
    field carries the current version, then registers. Returns the Vehicle."""
    fresh = read_order(order["id"])
    response = register_vehicle_raw(order["id"], module_id, vin, fresh["version"])
    return get_success_data(response)


def transition_vehicle(vehicle_id, dimension, to_state, headers=None):
    """Advance one parallel dimension of a vehicle (200) via ServiceDispatcher."""
    payload = vehicle_transition_payload(dimension, to_state)
    return get_success_data(api_client.transition_vehicle(vehicle_id, payload, headers or _DISPATCHER))


def provision_and_activate_telematics(vehicle_id, headers=None):
    """OFFLINE -> PROVISIONED -> ACTIVE (200 each)."""
    transition_vehicle(vehicle_id, "TELEMATICS", "PROVISIONED", headers)
    return transition_vehicle(vehicle_id, "TELEMATICS", "ACTIVE", headers)


def advance_delivery_to_at_depot(vehicle_id, headers=None):
    """ASSEMBLED -> IN_TRANSIT -> AT_DEPOT (200 each)."""
    transition_vehicle(vehicle_id, "DELIVERY", "IN_TRANSIT", headers)
    return transition_vehicle(vehicle_id, "DELIVERY", "AT_DEPOT", headers)


def commission_vehicle(vehicle_id, headers=None):
    """Full commissioning walk: telematics ACTIVE, then delivery
    ASSEMBLED -> IN_TRANSIT -> AT_DEPOT -> COMMISSIONED. Only valid when the
    parent order does not require depot charging, or commissioned capacity
    already satisfies the demand gate."""
    provision_and_activate_telematics(vehicle_id, headers)
    advance_delivery_to_at_depot(vehicle_id, headers)
    return transition_vehicle(vehicle_id, "DELIVERY", "COMMISSIONED", headers)


def read_vehicle(vehicle_id, headers=None):
    return get_success_data(api_client.get_vehicle(vehicle_id, headers or _DISPATCHER))


def report_battery_health(vehicle_id, measured_soh_pct, measured_at):
    """Ingest a battery-health report (200) as the telematics pipeline."""
    payload = battery_health_payload(measured_soh_pct, measured_at)
    return get_success_data(api_client.report_battery_health(vehicle_id, payload, _TELEMATICS))


# ---------------------------------------------------------------------------
# Charging projects
# ---------------------------------------------------------------------------

def read_depot(depot_id, headers=None):
    return get_success_data(api_client.get_depot(depot_id, headers or _ADMIN))


def create_charging_project(customer, depot, **overrides):
    """Create a charging project (201): refetches the depot so
    expected_depot_version is current. Lands in SURVEY, already committing
    its requested kW."""
    fresh = read_depot(depot["id"], make_fleet_manager_headers(customer["id"]))
    if "expected_depot_version" not in overrides:
        overrides["expected_depot_version"] = fresh["version"]
    headers = make_fleet_manager_headers(customer["id"])
    payload = create_charging_project_payload(depot["id"], **overrides)
    return get_success_data(api_client.create_charging_project(payload, headers))


def create_charging_project_raw(depot_id, expected_depot_version, headers, **overrides):
    """Raw project create returning the Response — for OCC / headroom /
    crew-window error tests that need the unvalidated envelope."""
    payload = create_charging_project_payload(
        depot_id, expected_depot_version=expected_depot_version, **overrides
    )
    return api_client.create_charging_project(payload, headers)


def transition_project(project_id, to_state, utility_denial_reason=None):
    """Drive a charging-project transition (200) via ChargingCoordinator."""
    payload = transition_payload(to_state, utility_denial_reason=utility_denial_reason)
    return get_success_data(api_client.transition_charging_project(project_id, payload, _COORDINATOR))


def advance_project_to_permitting(project_id):
    """SURVEY -> UTILITY_REVIEW -> PERMITTING."""
    transition_project(project_id, "UTILITY_REVIEW")
    return transition_project(project_id, "PERMITTING")


def advance_project_to_commissioned(project_id):
    """SURVEY -> UTILITY_REVIEW -> PERMITTING -> INSTALLATION -> COMMISSIONED.
    commissioned_capacity_kw is set equal to requested_capacity_kw."""
    advance_project_to_permitting(project_id)
    transition_project(project_id, "INSTALLATION")
    return transition_project(project_id, "COMMISSIONED")


def create_and_commission_project(customer, depot, requested_capacity_kw=25, **overrides):
    """Create a project and drive it to COMMISSIONED, contributing
    commissioned_capacity_kw to the depot's demand-gate pool."""
    overrides.setdefault("requested_capacity_kw", requested_capacity_kw)
    overrides.setdefault("install_window_start", "2026-09-05T00:00:00Z")
    overrides.setdefault("install_window_end", "2026-09-08T00:00:00Z")
    project = create_charging_project(customer, depot, **overrides)
    return advance_project_to_commissioned(project["id"])


# ---------------------------------------------------------------------------
# Service network
# ---------------------------------------------------------------------------

def create_service_center(**overrides):
    """Stand up a service center (201) as PlatformAdmin."""
    return get_success_data(
        api_client.create_service_center(create_service_center_payload(**overrides), _ADMIN)
    )


def create_mobile_van(service_center_id, **overrides):
    """Commission a mobile van homed at a center (201) as ServiceDispatcher."""
    return get_success_data(
        api_client.create_mobile_van(create_mobile_van_payload(service_center_id, **overrides), _DISPATCHER)
    )


def upsert_parts_stock(service_center_id, **overrides):
    """Upsert a parts stock row (201): positive qty_delta is a receipt."""
    return get_success_data(
        api_client.upsert_parts_stock(create_parts_stock_payload(service_center_id, **overrides), _DISPATCHER)
    )


def get_parts_stock(service_center_id, sku):
    """Read one stock row by listing the center's stocks (200)."""
    rows, _meta = _list_center_stocks(service_center_id)
    for row in rows:
        if row["sku"] == sku:
            return row
    raise AssertionError(f"Setup failed: no stock row for sku {sku} at center {service_center_id}")


def _list_center_stocks(service_center_id):
    resp = api_client.list_service_center_parts_stocks(service_center_id, _DISPATCHER)
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(resp)


def book_visit(customer, vehicle_id, service_center_id=None, mobile_van_id=None, **overrides):
    """Book a service visit (201) as the owning fleet manager; reserves parts."""
    headers = make_fleet_manager_headers(customer["id"])
    payload = create_service_visit_payload(
        vehicle_id, service_center_id=service_center_id, mobile_van_id=mobile_van_id, **overrides
    )
    return get_success_data(api_client.create_service_visit(payload, headers))


def start_visit(visit_id, technician_headers=None):
    """SCHEDULED -> IN_PROGRESS (200) as ServiceTechnician."""
    return get_success_data(
        api_client.transition_service_visit(
            visit_id, transition_payload("IN_PROGRESS"), technician_headers or _TECHNICIAN
        )
    )


def complete_visit(visit_id, technician_headers=None):
    """IN_PROGRESS -> COMPLETED (200): consumes reserved parts, records the
    completing technician."""
    return get_success_data(
        api_client.transition_service_visit(
            visit_id, transition_payload("COMPLETED"), technician_headers or _TECHNICIAN
        )
    )


def cancel_visit(visit_id, customer):
    """SCHEDULED -> CANCELLED (200) by the owning fleet manager; releases the
    reserved parts."""
    headers = make_fleet_manager_headers(customer["id"])
    return get_success_data(
        api_client.transition_service_visit(visit_id, transition_payload("CANCELLED"), headers)
    )


# ---------------------------------------------------------------------------
# Software campaigns
# ---------------------------------------------------------------------------

def create_campaign(**overrides):
    """Create a software campaign in DRAFT (201) as ReleaseManager."""
    return get_success_data(
        api_client.create_software_campaign(create_software_campaign_payload(**overrides), _RELEASE)
    )


def transition_campaign(campaign_id, to_state):
    """Drive a campaign transition (200) as ReleaseManager."""
    return get_success_data(
        api_client.transition_software_campaign(campaign_id, transition_payload(to_state), _RELEASE)
    )


def start_campaign(**overrides):
    """Campaign advanced DRAFT -> CANARY. Returns the CANARY campaign."""
    campaign = create_campaign(**overrides)
    return transition_campaign(campaign["id"], "CANARY")


def record_campaign_result(campaign_id, vehicle_id, result):
    """Append one vehicle result (201) as the telematics pipeline; on SUCCESS
    the vehicle's software_version advances to the campaign target."""
    payload = campaign_result_payload(vehicle_id, result)
    return get_success_data(api_client.record_vehicle_result(campaign_id, payload, _TELEMATICS))


def read_campaign(campaign_id, headers=None):
    return get_success_data(api_client.get_software_campaign(campaign_id, headers or _RELEASE))


# ---------------------------------------------------------------------------
# Warranty claims
# ---------------------------------------------------------------------------

def create_claim(customer, vehicle_id, claim_lines=None, service_visit_id=None, **overrides):
    """Submit a warranty claim (201) as the owning fleet manager."""
    headers = make_fleet_manager_headers(customer["id"])
    payload = create_warranty_claim_payload(
        vehicle_id, claim_lines=claim_lines, service_visit_id=service_visit_id, **overrides
    )
    return get_success_data(api_client.create_warranty_claim(payload, headers))


def diagnose_claim(claim_id, diagnosis_notes=None, technician_headers=None):
    """SUBMITTED -> DIAGNOSED (200) as ServiceTechnician."""
    return get_success_data(
        api_client.diagnose_warranty_claim(
            claim_id, diagnose_payload(diagnosis_notes), technician_headers or _TECHNICIAN
        )
    )


def adjudicate_claim(claim_id, decision, denial_reason=None, adjuster_headers=None):
    """DIAGNOSED -> SETTLED (APPROVE, computes settlement) or DENIED (DENY,
    requires denial_reason). Adjudicator must differ from diagnostician."""
    payload = adjudicate_payload(decision, denial_reason=denial_reason)
    return get_success_data(
        api_client.adjudicate_warranty_claim(claim_id, payload, adjuster_headers or _ADJUSTER)
    )


# ---------------------------------------------------------------------------
# Uptime contracts
# ---------------------------------------------------------------------------

def create_uptime_contract(customer, **overrides):
    """Create an uptime contract (201) as PlatformAdmin."""
    payload = create_uptime_contract_payload(customer["id"], **overrides)
    return get_success_data(api_client.create_uptime_contract(payload, _ADMIN))


def read_uptime_contract(customer, contract_id):
    """Read one contract back by listing the customer's contracts (there is no
    single-GET endpoint for contracts)."""
    resp = api_client.list_fleet_customer_uptime_contracts(customer["id"], _ADMIN)
    from prd_bench_local_runner.testing import validate_paginated
    rows, _meta = validate_paginated(resp)
    for row in rows:
        if row["id"] == contract_id:
            return row
    raise AssertionError(f"Setup failed: contract {contract_id} not listed for customer {customer['id']}")


def append_downtime(contract, vehicle_id, started_at, ended_at=None, expected_version=None):
    """Append a downtime event (201) with the OCC guard. expected_version
    defaults to the passed contract dict's current version; the refreshed
    contract from the response is returned for chaining."""
    version = expected_version if expected_version is not None else contract["version"]
    payload = downtime_event_payload(vehicle_id, started_at, version, ended_at=ended_at)
    return get_success_data(api_client.append_downtime_event(contract["id"], payload, _TELEMATICS))


def close_month(contract_id, month):
    """Close a measurement month (200) as PlatformAdmin; computes the uptime
    credit per the contract's pro_rating variant."""
    return get_success_data(api_client.close_uptime_month(contract_id, close_month_payload(month), _ADMIN))


# =============================================================================
# Tier 2/3: composite fleet scenarios
# =============================================================================

def setup_customer_with_depot(depot_state="CA", depot_capacity_kw=500, set_clock=True, **customer_overrides):
    """Clock + customer + one owned depot. Returns (customer, depot)."""
    if set_clock:
        set_logical_clock()
    customer = create_fleet_customer(**customer_overrides)
    depot = create_depot(customer, state_code=depot_state, total_capacity_kw=depot_capacity_kw)
    return customer, depot


def setup_supplier_with_passed_modules(count, pack_kwh=77, serial_prefix="M"):
    """One supplier plus `count` PASSED modules. Returns (supplier, modules)."""
    supplier = create_supplier()
    modules = create_passed_modules(supplier["id"], count, pack_kwh=pack_kwh, serial_prefix=serial_prefix)
    return supplier, modules


def setup_base_fleet(
    quantity=2,
    pack_kwh=77,
    register_count=None,
    depot_state="CA",
    depot_capacity_kw=500,
    delivery_method="DIRECT_DELIVERY",
    telematics_tier="STANDARD",
    requires_depot_charging=False,
    exemption_document_ref=None,
    serial_prefix="M",
    vin_seq_start=1,
):
    """The canonical fleet chain, built entirely through public endpoints:

    clock -> customer -> depot -> supplier -> N PASSED modules ->
    order DRAFT -> SUBMITTED -> CONFIRMED -> VIN registrations.

    register_count defaults to quantity; pass a smaller register_count to
    leave registration slots open (e.g. ramp-gate boundary tests where the
    final registration must fail outside the fixture).

    Returns a dict: customer, depot, supplier, modules (all PASSED modules),
    order (CONFIRMED snapshot), vehicles (registered so far).
    """
    set_logical_clock()
    customer = create_fleet_customer()
    depot = create_depot(customer, state_code=depot_state, total_capacity_kw=depot_capacity_kw)
    supplier = create_supplier()
    modules = create_passed_modules(supplier["id"], quantity, pack_kwh=pack_kwh, serial_prefix=serial_prefix)
    order = create_confirmed_order(
        customer,
        depot,
        supplier,
        exemption_document_ref=exemption_document_ref,
        quantity=quantity,
        battery_pack_kwh=pack_kwh,
        telematics_tier=telematics_tier,
        delivery_method=delivery_method,
        requires_depot_charging=requires_depot_charging,
    )
    to_register = register_count if register_count is not None else quantity
    vehicles = []
    for i in range(to_register):
        vehicles.append(register_vehicle(order, modules[i]["id"], make_vin(vin_seq_start + i)))
    return {
        "customer": customer,
        "depot": depot,
        "supplier": supplier,
        "modules": modules,
        "order": order,
        "vehicles": vehicles,
    }


def setup_commissioned_fleet(num_vehicles=2, **base_kwargs):
    """setup_base_fleet with every registered vehicle driven to telematics
    ACTIVE and delivery COMMISSIONED (the in-service fleet set)."""
    base_kwargs.setdefault("quantity", num_vehicles)
    fleet = setup_base_fleet(**base_kwargs)
    commissioned = [commission_vehicle(vehicle["id"]) for vehicle in fleet["vehicles"]]
    fleet["vehicles"] = commissioned
    fleet["order"] = read_order(fleet["order"]["id"])
    return fleet


def setup_fulfilled_order(quantity=1, **base_kwargs):
    """Base fleet where registering `quantity` VINs auto-walks the order
    CONFIRMED -> IN_PRODUCTION -> FULFILLED. Returns the fleet dict with a
    refreshed FULFILLED order."""
    fleet = setup_base_fleet(quantity=quantity, **base_kwargs)
    fleet["order"] = read_order(fleet["order"]["id"])
    return fleet


# =============================================================================
# Tier 4: threshold / accumulation targeting
# =============================================================================

def setup_depot_with_project(
    depot_capacity_kw=500,
    requested_capacity_kw=40,
    crew_count=1,
    install_window_start="2026-10-01T00:00:00Z",
    install_window_end="2026-10-10T00:00:00Z",
    advance_to=None,
):
    """Customer + depot + one charging project, optionally advanced along
    SURVEY -> UTILITY_REVIEW -> PERMITTING -> INSTALLATION -> COMMISSIONED.
    advance_to names the farthest state reached (None = stay in SURVEY).
    Returns dict: customer, depot (fresh), project.
    """
    customer, depot = setup_customer_with_depot(depot_capacity_kw=depot_capacity_kw)
    project = create_charging_project(
        customer,
        depot,
        requested_capacity_kw=requested_capacity_kw,
        crew_count=crew_count,
        install_window_start=install_window_start,
        install_window_end=install_window_end,
    )
    path = ["UTILITY_REVIEW", "PERMITTING", "INSTALLATION", "COMMISSIONED"]
    if advance_to is not None:
        for state in path:
            project = transition_project(project["id"], state)
            if state == advance_to:
                break
    return {"customer": customer, "depot": read_depot(depot["id"]), "project": project}


def register_vehicles_for_order(order, module_ids, vin_seq_start=1):
    """Register one VIN per module against the order, refetching the order
    version before each registration. Returns the list of Vehicles."""
    vehicles = []
    for i, module_id in enumerate(module_ids):
        vehicles.append(register_vehicle(order, module_id, make_vin(vin_seq_start + i)))
    return vehicles


# =============================================================================
# Tier 5: terminal-state / full-lifecycle shortcuts
# =============================================================================

def setup_service_scenario(
    stock_sku="BRK-1",
    stock_qty=5,
    reorder_threshold=1,
    visit_parts=None,
    mobile=False,
    window_start="2026-09-10T09:00:00Z",
    window_end="2026-09-10T10:00:00Z",
    purpose="REPAIR",
):
    """Commissioned single-vehicle fleet + service center (+ optional mobile
    van) + one stocked sku + a SCHEDULED visit reserving visit_parts.

    Returns dict: fleet (setup_commissioned_fleet result), center, stock,
    van (or None), visit.
    """
    fleet = setup_commissioned_fleet(num_vehicles=1)
    customer = fleet["customer"]
    vehicle = fleet["vehicles"][0]
    center = create_service_center()
    stock = upsert_parts_stock(
        center["id"], sku=stock_sku, qty_delta=stock_qty, reorder_threshold=reorder_threshold
    )
    van = create_mobile_van(center["id"]) if mobile else None
    lines = visit_parts if visit_parts is not None else [{"sku": stock_sku, "qty": 1}]
    visit = book_visit(
        customer,
        vehicle["id"],
        service_center_id=None if mobile else center["id"],
        mobile_van_id=van["id"] if mobile else None,
        window_start=window_start,
        window_end=window_end,
        purpose=purpose,
        parts_lines=lines,
    )
    return {"fleet": fleet, "center": center, "stock": stock, "van": van, "visit": visit}


def setup_completed_visit(**scenario_kwargs):
    """Service scenario with the visit worked to COMPLETED (parts consumed,
    completed_by_user_id recorded). Returns the scenario dict."""
    scenario = setup_service_scenario(**scenario_kwargs)
    start_visit(scenario["visit"]["id"])
    scenario["visit"] = complete_visit(scenario["visit"]["id"])
    return scenario


def setup_diagnosed_claim(claim_lines=None, diagnosis_notes="Inspected on bench."):
    """Commissioned fleet + a claim moved SUBMITTED -> DIAGNOSED by the shared
    technician. Returns dict: fleet, claim."""
    fleet = setup_commissioned_fleet(num_vehicles=1)
    claim = create_claim(fleet["customer"], fleet["vehicles"][0]["id"], claim_lines=claim_lines)
    claim = diagnose_claim(claim["id"], diagnosis_notes=diagnosis_notes)
    return {"fleet": fleet, "claim": claim}


def setup_settled_claim(claim_lines=None):
    """Claim adjudicated APPROVE by the shared adjuster (segregation-safe:
    distinct from the diagnostician). Returns dict: fleet, claim (SETTLED)."""
    scenario = setup_diagnosed_claim(claim_lines=claim_lines)
    scenario["claim"] = adjudicate_claim(scenario["claim"]["id"], "APPROVE")
    return scenario


def setup_denied_claim(claim_lines=None, denial_reason="Not a covered defect."):
    """Claim adjudicated DENY. Returns dict: fleet, claim (DENIED)."""
    scenario = setup_diagnosed_claim(claim_lines=claim_lines)
    scenario["claim"] = adjudicate_claim(
        scenario["claim"]["id"], "DENY", denial_reason=denial_reason
    )
    return scenario


def setup_campaign_with_results(target_version="2.0.0", scope="ALL", results=()):
    """Campaign in CANARY plus recorded results. `results` is an iterable of
    (vehicle_id, result) pairs recorded in order. Returns the refreshed
    campaign."""
    campaign = start_campaign(target_version=target_version, telematics_tier_scope=scope)
    for vehicle_id, result in results:
        campaign = record_campaign_result(campaign["id"], vehicle_id, result)
    return read_campaign(campaign["id"])


def setup_uptime_contract_with_fleet(
    num_vehicles=2,
    pro_rating="ROUTE_DAY",
    committed_uptime_pct=97.0,
    monthly_service_fee_cents=2000000,
    measurement_start_date="2026-09-01",
):
    """Commissioned in-service fleet of num_vehicles plus an uptime contract
    on the customer. Returns dict: fleet, contract."""
    fleet = setup_commissioned_fleet(num_vehicles=num_vehicles)
    contract = create_uptime_contract(
        fleet["customer"],
        pro_rating=pro_rating,
        committed_uptime_pct=committed_uptime_pct,
        monthly_service_fee_cents=monthly_service_fee_cents,
        measurement_start_date=measurement_start_date,
    )
    return {"fleet": fleet, "contract": contract}
