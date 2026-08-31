"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty database.

The central helper is `build_network`, which walks the reference network up to a
chosen stage:

    network        mill, quota contract, carrier + three coverages, truck, crew
    tract          + the harvest unit
    plan           + a DRAFT production plan
    plan_approved  + the plan promoted to APPROVED
    assignment     + one SCHEDULED crew assignment
    route          + the haul route from tract to mill
    mobilized      + POST /tracts/{id}/mobilize
    active         + POST /tracts/{id}/activate   (the default)
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_crew_assignment_payload,
    create_crew_payload,
    create_delivery_ticket_payload,
    create_haul_contractor_payload,
    create_haul_route_payload,
    create_insurance_certificate_payload,
    create_load_payload,
    create_mill_contract_payload,
    create_mill_payload,
    create_production_plan_payload,
    create_settlement_statement_payload,
    create_shutdown_order_payload,
    create_tract_payload,
    create_truck_payload,
)
from .test_users import (
    TEST_USERS,
    make_carrier_headers,
    make_scaler_headers,
    make_accountant_headers,
)

REQUIRED_COVERAGES = ("GENERAL_LIABILITY", "AUTO_LIABILITY", "WORKERS_COMP")

_STAGES = (
    "network",
    "tract",
    "plan",
    "plan_approved",
    "assignment",
    "route",
    "mobilized",
    "active",
)


def _stage_at_least(stage: str, target: str) -> bool:
    return _STAGES.index(stage) >= _STAGES.index(target)


def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


def ops_headers() -> dict:
    return TEST_USERS["ops_headers"]


def safety_headers() -> dict:
    return TEST_USERS["safety_headers"]


def accountant_headers() -> dict:
    return TEST_USERS["accountant_headers"]


def approver_headers() -> dict:
    return TEST_USERS["accountant_two_headers"]


# ─── Primitive creators ──────────────────────────────────────────────────────

def create_mill(**overrides) -> dict:
    return get_success_data(
        api_client.create_mill(create_mill_payload(**overrides), admin_headers())
    )


def create_mill_contract(mill_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_mill_contract(
            create_mill_contract_payload(mill_id, **overrides), admin_headers()
        )
    )


def create_haul_contractor(**overrides) -> dict:
    return get_success_data(
        api_client.create_haul_contractor(
            create_haul_contractor_payload(**overrides), admin_headers()
        )
    )


def file_certificate(contractor_id, coverage_type, **overrides) -> dict:
    return get_success_data(
        api_client.create_insurance_certificate(
            contractor_id,
            create_insurance_certificate_payload(coverage_type, **overrides),
            admin_headers(),
        )
    )


def file_all_coverages(contractor_id, **overrides) -> dict:
    """File GENERAL_LIABILITY, AUTO_LIABILITY and WORKERS_COMP; return their ids."""
    return {
        coverage: file_certificate(contractor_id, coverage, **overrides)["id"]
        for coverage in REQUIRED_COVERAGES
    }


def create_truck(contractor_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_truck(
            contractor_id, create_truck_payload(**overrides), admin_headers()
        )
    )


def create_crew(**overrides) -> dict:
    return get_success_data(
        api_client.create_crew(create_crew_payload(**overrides), admin_headers())
    )


def create_tract(**overrides) -> dict:
    return get_success_data(
        api_client.create_tract(create_tract_payload(**overrides), ops_headers())
    )


def create_production_plan(tract_id, expected_tract_version, **overrides) -> dict:
    return get_success_data(
        api_client.create_production_plan(
            tract_id,
            create_production_plan_payload(expected_tract_version, **overrides),
            ops_headers(),
        )
    )


def approve_production_plan(plan_id) -> dict:
    return get_success_data(api_client.approve_production_plan(plan_id, ops_headers()))


def create_crew_assignment(tract_id, crew_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_crew_assignment(
            tract_id, create_crew_assignment_payload(crew_id, **overrides), ops_headers()
        )
    )


def create_haul_route(tract_id, mill_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_haul_route(
            create_haul_route_payload(tract_id, mill_id, **overrides), admin_headers()
        )
    )


def set_clock(to_iso8601) -> dict:
    return get_success_data(api_client.set_clock(to_iso8601, admin_headers()))


# ─── The composite network builder ───────────────────────────────────────────

def build_network(
    stage="active",
    mill=None,
    contract=None,
    carrier=None,
    with_certs=True,
    truck=None,
    crew=None,
    tract=None,
    plan=None,
    approve_plan=True,
    assignment=None,
    route=None,
):
    """Walk the reference network up to `stage`.

    Returns a dict carrying every created id plus ready-made identity-bound
    headers (`scaler_headers` for the mill, `carrier_headers` for the carrier).
    """
    assert stage in _STAGES, f"unknown stage {stage!r}"

    scn = {}

    mill_row = create_mill(**(mill or {}))
    scn["mill_a"] = mill_row
    scn["mill_a_id"] = mill_row["id"]
    scn["scaler_headers"] = make_scaler_headers(mill_row["id"])

    contract_row = create_mill_contract(mill_row["id"], **(contract or {}))
    scn["mc_a"] = contract_row
    scn["mc_a_id"] = contract_row["id"]

    carrier_row = create_haul_contractor(**(carrier or {}))
    scn["hc"] = carrier_row
    scn["hc_id"] = carrier_row["id"]
    scn["carrier_headers"] = make_carrier_headers(carrier_row["id"])

    if with_certs:
        cert_ids = file_all_coverages(carrier_row["id"])
        scn["cert_ids"] = cert_ids
        scn["cert_gl_id"] = cert_ids["GENERAL_LIABILITY"]
        scn["cert_al_id"] = cert_ids["AUTO_LIABILITY"]
        scn["cert_wc_id"] = cert_ids["WORKERS_COMP"]

    truck_row = create_truck(carrier_row["id"], **(truck or {}))
    scn["truck"] = truck_row
    scn["truck_id"] = truck_row["id"]

    crew_row = create_crew(**(crew or {}))
    scn["crew"] = crew_row
    scn["crew_id"] = crew_row["id"]

    if not _stage_at_least(stage, "tract"):
        return scn

    tract_row = create_tract(**(tract or {}))
    scn["tract"] = tract_row
    scn["tract_id"] = tract_row["id"]
    scn["tract_version"] = tract_row["version"]

    if _stage_at_least(stage, "plan"):
        plan_row = create_production_plan(
            tract_row["id"], tract_row["version"], **(plan or {})
        )
        scn["plan"] = plan_row
        scn["plan_id"] = plan_row["id"]

        if approve_plan and _stage_at_least(stage, "plan_approved"):
            approve_production_plan(plan_row["id"])

    if _stage_at_least(stage, "assignment"):
        assignment_row = create_crew_assignment(
            tract_row["id"], crew_row["id"], **(assignment or {})
        )
        scn["ca"] = assignment_row
        scn["ca_id"] = assignment_row["id"]

    if _stage_at_least(stage, "route"):
        route_row = create_haul_route(
            tract_row["id"], mill_row["id"], **(route or {})
        )
        scn["route_a"] = route_row
        scn["route_a_id"] = route_row["id"]

    if _stage_at_least(stage, "mobilized"):
        get_success_data(api_client.mobilize_tract(tract_row["id"], ops_headers()))

    if _stage_at_least(stage, "active"):
        get_success_data(api_client.activate_tract(tract_row["id"], ops_headers()))

    return scn


# ─── Load lifecycle helpers ──────────────────────────────────────────────────

def dispatch_load(scn, route_id=None, **overrides) -> dict:
    """Dispatch one load against the scenario's contract and route."""
    payload = create_load_payload(
        scn["tract_id"],
        scn["mc_a_id"],
        route_id or scn["route_a_id"],
        scn["truck_id"],
        **overrides,
    )
    return get_success_data(api_client.create_load(payload, ops_headers()))


def depart_load(scn, load_id) -> dict:
    return get_success_data(
        api_client.depart_load(load_id, scn["carrier_headers"])
    )


def arrive_load(scn, load_id) -> dict:
    return get_success_data(
        api_client.arrive_load(load_id, scn["carrier_headers"])
    )


def cancel_load(scn, load_id, reason="landing shut down by wet ground") -> dict:
    return get_success_data(
        api_client.cancel_load(load_id, {"reason": reason}, ops_headers())
    )


def load_at_mill(scn, route_id=None, **overrides) -> dict:
    """Dispatch a load, then depart and arrive it so it stands AT_MILL."""
    load = dispatch_load(scn, route_id=route_id, **overrides)
    depart_load(scn, load["id"])
    arrive_load(scn, load["id"])
    return load


def write_ticket(scn, load_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_delivery_ticket(
            load_id, create_delivery_ticket_payload(**overrides), scn["scaler_headers"]
        )
    )


def certify_ticket(scn, ticket_id) -> dict:
    return get_success_data(
        api_client.certify_delivery_ticket(ticket_id, scn["scaler_headers"])
    )


def reject_ticket(scn, ticket_id, reject_reason="EXCESS_DEFECT") -> dict:
    return get_success_data(
        api_client.reject_delivery_ticket(
            ticket_id, {"reject_reason": reject_reason}, scn["scaler_headers"]
        )
    )


def deliver_load(scn, route_id=None, ticket=None, **overrides):
    """Dispatch -> depart -> arrive -> scale -> certify. Returns (load, ticket)."""
    load = load_at_mill(scn, route_id=route_id, **overrides)
    ticket_row = write_ticket(scn, load["id"], **(ticket or {}))
    certify_ticket(scn, ticket_row["id"])
    return load, ticket_row


def reject_load_at_mill(scn, reject_reason="EXCESS_DEFECT", ticket=None, **overrides):
    """Dispatch -> depart -> arrive -> scale -> reject. Returns (load, ticket)."""
    load = load_at_mill(scn, **overrides)
    ticket_row = write_ticket(scn, load["id"], **(ticket or {}))
    reject_ticket(scn, ticket_row["id"], reject_reason)
    return load, ticket_row


# ─── Shutdown helpers ────────────────────────────────────────────────────────

def declare_shutdown(scn, **overrides) -> dict:
    return get_success_data(
        api_client.create_shutdown_order(
            scn["tract_id"], create_shutdown_order_payload(**overrides), ops_headers()
        )
    )


def lift_shutdown(scn, order_id, soil_moisture_index=40) -> dict:
    return get_success_data(
        api_client.lift_shutdown_order(
            order_id, {"soil_moisture_index": soil_moisture_index}, ops_headers()
        )
    )


def suspend_tract_by_shutdown(scn, reason="WET_WEATHER", soil_moisture_index=85) -> dict:
    """Drive an ACTIVE tract to SUSPENDED and return the order."""
    return declare_shutdown(
        scn, reason=reason, soil_moisture_index=soil_moisture_index
    )


# ─── Compliance helpers ──────────────────────────────────────────────────────

def record_finding(scn, severity="MINOR", points=5, occurred_on="2026-07-30", note=None):
    payload = {
        "severity": severity,
        "points": points,
        "occurred_on": occurred_on,
    }
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.create_safety_finding(scn["hc_id"], payload, safety_headers())
    )


def revoke_certificate(certificate_id, reason="policy cancelled for non-payment"):
    return get_success_data(
        api_client.revoke_insurance_certificate(
            certificate_id, {"reason": reason}, safety_headers()
        )
    )


def suspend_carrier(scn, reason="missed corrective action deadline"):
    return get_success_data(
        api_client.suspend_haul_contractor(
            scn["hc_id"], {"reason": reason}, safety_headers()
        )
    )


def reinstate_carrier(scn, note="corrective action closed"):
    return get_success_data(
        api_client.reinstate_haul_contractor(
            scn["hc_id"], {"note": note}, safety_headers()
        )
    )


# ─── Settlement helpers ──────────────────────────────────────────────────────

def compile_statement(
    scn,
    period_start="2026-08-01",
    period_end="2026-08-31",
    compiler_user_id="acct-1",
    expected_haul_contractor_version=None,
    **overrides,
):
    """Re-read the carrier's version, then compile a statement over the period."""
    if expected_haul_contractor_version is None:
        carrier = read_haul_contractor(scn["hc_id"])
        expected_haul_contractor_version = carrier["version"]
    payload = create_settlement_statement_payload(
        scn["hc_id"],
        expected_haul_contractor_version,
        period_start=period_start,
        period_end=period_end,
        **overrides,
    )
    return get_success_data(
        api_client.create_settlement_statement(
            payload, make_accountant_headers(compiler_user_id)
        )
    )


def submit_statement(statement_id, user_id="acct-1"):
    return get_success_data(
        api_client.submit_settlement_statement(
            statement_id, make_accountant_headers(user_id)
        )
    )


def approve_statement(statement_id, user_id="acct-2"):
    return get_success_data(
        api_client.approve_settlement_statement(
            statement_id, make_accountant_headers(user_id)
        )
    )


def dispute_statement(statement_id, headers, dispute_reason="demurrage minutes disputed"):
    return get_success_data(
        api_client.dispute_settlement_statement(
            statement_id, {"dispute_reason": dispute_reason}, headers
        )
    )


def revise_statement(statement_id, note="recompiled after dispute", user_id="acct-1"):
    return get_success_data(
        api_client.revise_settlement_statement(
            statement_id, {"note": note}, make_accountant_headers(user_id)
        )
    )


def pay_statement(statement_id, payment_reference="ACH-2026-08-0001", user_id="acct-1"):
    return get_success_data(
        api_client.pay_settlement_statement(
            statement_id, {"payment_reference": payment_reference},
            make_accountant_headers(user_id),
        )
    )


def settle_one_delivered_load(scn, **overrides):
    """Deliver one load and compile a DRAFT statement covering August 2026.

    Returns (load, ticket, statement).
    """
    load, ticket = deliver_load(scn, **overrides)
    statement = compile_statement(scn)
    return load, ticket, statement


# ─── Readers ─────────────────────────────────────────────────────────────────
# Several child resources have no single-resource GET, so they are read back
# through their parent's listing.

def read_mill(mill_id) -> dict:
    return get_success_data(api_client.get_mill(mill_id, admin_headers()))


def read_mill_contract(contract_id) -> dict:
    return get_success_data(api_client.get_mill_contract(contract_id, admin_headers()))


def read_haul_contractor(contractor_id) -> dict:
    return get_success_data(
        api_client.get_haul_contractor(contractor_id, admin_headers())
    )


def read_tract(tract_id) -> dict:
    return get_success_data(api_client.get_tract(tract_id, admin_headers()))


def read_crew(crew_id) -> dict:
    return get_success_data(api_client.get_crew(crew_id, admin_headers()))


def read_crew_assignment(assignment_id) -> dict:
    return get_success_data(
        api_client.get_crew_assignment(assignment_id, admin_headers())
    )


def read_haul_route(route_id) -> dict:
    return get_success_data(api_client.get_haul_route(route_id, admin_headers()))


def read_load(load_id) -> dict:
    return get_success_data(api_client.get_load(load_id, admin_headers()))


def read_delivery_ticket(ticket_id) -> dict:
    return get_success_data(api_client.get_delivery_ticket(ticket_id, admin_headers()))


def read_settlement_statement(statement_id) -> dict:
    return get_success_data(
        api_client.get_settlement_statement(statement_id, admin_headers())
    )


def _find_by_id(rows, row_id, label):
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"{label} {row_id} not found in listing of {len(rows)} rows")


def list_production_plans(tract_id) -> list:
    return get_success_data(
        api_client.list_production_plans(
            tract_id, admin_headers(), params={"limit": 100}
        )
    )


def read_production_plan(tract_id, plan_id) -> dict:
    return _find_by_id(list_production_plans(tract_id), plan_id, "ProductionPlan")


def list_shutdown_orders(tract_id) -> list:
    return get_success_data(
        api_client.list_shutdown_orders(
            tract_id, admin_headers(), params={"limit": 100}
        )
    )


def read_shutdown_order(tract_id, order_id) -> dict:
    return _find_by_id(list_shutdown_orders(tract_id), order_id, "ShutdownOrder")


def list_trucks(contractor_id) -> list:
    return get_success_data(
        api_client.list_trucks(contractor_id, admin_headers(), params={"limit": 100})
    )


def read_truck(contractor_id, truck_id) -> dict:
    return _find_by_id(list_trucks(contractor_id), truck_id, "Truck")


def list_certificates(contractor_id) -> list:
    return get_success_data(
        api_client.list_insurance_certificates(
            contractor_id, admin_headers(), params={"limit": 100}
        )
    )


def read_certificate(contractor_id, certificate_id) -> dict:
    return _find_by_id(
        list_certificates(contractor_id), certificate_id, "InsuranceCertificate"
    )


def list_findings(contractor_id) -> list:
    return get_success_data(
        api_client.list_safety_findings(
            contractor_id, admin_headers(), params={"limit": 100}
        )
    )


def list_loads(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(api_client.list_loads(admin_headers(), params=query))


def rehaul_children(load_id) -> list:
    return list_loads(rehaul_of_load_id=load_id)


def list_tickets(**params) -> list:
    query = {"limit": 100}
    query.update(params)
    return get_success_data(
        api_client.list_delivery_tickets(admin_headers(), params=query)
    )
