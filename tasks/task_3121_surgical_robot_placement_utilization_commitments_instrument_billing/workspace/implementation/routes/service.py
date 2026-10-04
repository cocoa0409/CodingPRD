"""Service coverage contracts, incidents and loaner dispatches."""

from datetime import timedelta

from flask import Blueprint

from db import DB, base_record, as_str, check_version, to_iso, touch
from errors import ApiError
from middleware import authenticate, check_region
from response import success
from routes import common
from serializers import (service_contract as ser_contract,
                         incident as ser_incident,
                         loaner_dispatch as ser_dispatch)
from services import calc, machines

bp = Blueprint("service", __name__)

COVERAGE_TIERS = ("COMPREHENSIVE", "STANDARD", "LIMITED", "PARTS_ONLY")


@bp.post("/api/service-contracts")
def create_contract():
    """Create a coverage contract over a system.

    The response-time ladder is computed by `contract_response_time_commitment`
    and a tier outside the recognized set is rejected at the first step.
    """
    ctx = authenticate(["ServiceEngineer"])
    data = common.body()
    system = common.get_system(common.require_str(data, "robot_system_id"))
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    tier = common.require_str(data, "coverage_tier").upper()
    start = common.require_dt(data, "contract_start_utc")
    months = common.require_int(data, "contract_months")
    # Priority 39 — the tier must parse into the ladder.
    if tier not in COVERAGE_TIERS:
        raise ApiError("ERR_CONTRACT_TIER_UNRECOGNIZED")
    contract = base_record({
        "robot_system_id": system.get("id"),
        "coverage_tier": tier,
        "contract_start_utc": to_iso(start),
        "contract_months": months,
        "contract_status": "ACTIVE",
    })
    # Priority 33 — temporal validity against the system's installation instant.
    if not calc.contract_temporally_valid(contract, system):
        raise ApiError("ERR_CONTRACT_TEMPORALLY_INVALID")
    # Priority 40 — the parent-version guard runs last.
    check_version(system, data, "expected_robot_system_version")
    DB.service_contracts[contract["id"]] = contract
    # The coverage relationship is part of the system's state.
    touch(system)
    machines.refresh_system(system)
    return success(ser_contract(contract)), 201


@bp.get("/api/service-contracts")
def list_contracts():
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    records = list(DB.service_contracts.values())
    system_id = common.arg("robot_system_id")
    if system_id:
        records = [r for r in records if r.get("robot_system_id") == system_id]
    status = common.arg("contract_status")
    if status:
        records = [r for r in records if r.get("contract_status") == status]
    return common.paged(records, "service_contracts")


@bp.get("/api/service-contracts/<contract_id>")
def get_contract(contract_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    return success(ser_contract(common.get_contract(contract_id)))


@bp.get("/api/robot-systems/<system_id>/service-contracts")
def list_system_contracts(system_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    common.get_system(system_id)
    records = calc.contracts_of_system(system_id)
    status = common.arg("contract_status")
    if status:
        records = [r for r in records if r.get("contract_status") == status]
    return common.paged(records, "service_contracts")


@bp.post("/api/service-contracts/<contract_id>/terminate")
def terminate_contract(contract_id):
    """Terminate a contract and resolve the system's open incidents."""
    authenticate(["ServiceEngineer"])
    contract = common.get_contract(contract_id)
    system = DB.robot_systems.get(contract.get("robot_system_id"))
    account = DB.hospital_accounts.get((system or {}).get("hospital_account_id"))
    data = common.body()
    if contract.get("contract_status") != "ACTIVE":
        raise ApiError("ERR_SERVICE_CONTRACT_NOT_ACTIVE")
    check_version(contract, data, "expected_contract_version")
    machines.contract_terminate(contract, account)
    return success(ser_contract(contract))


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

@bp.post("/api/incident-service-requests")
def file_incident():
    """File a service incident and derive its severity from the system's posture
    and coverage at the filing instant."""
    ctx = authenticate(["ServiceEngineer"])
    data = common.body()
    system = common.get_system(common.require_str(data, "robot_system_id"))
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    started = common.require_dt(data, "incident_started_at")
    contract = calc.active_contract(system.get("id"))
    hours = calc.contract_response_hours(contract) if contract else None
    severity = calc.incident_severity(system, account)
    incident = base_record({
        "robot_system_id": system.get("id"),
        "incident_started_at": to_iso(started),
        "resolved_at_utc": None,
        "acknowledged_at_utc": None,
        "incident_severity": severity,
        "request_status": "OPEN",
        "resolution_notes": None,
        "_account_id": account.get("id"),
        "_penalty_tier_index": calc.service_tier_index(contract) if contract else 0,
        "_commitment_hours": hours,
    })
    if hours is not None:
        incident["response_due_at_utc"] = to_iso(started + timedelta(hours=int(hours)))
    DB.incidents[incident["id"]] = incident
    return success(ser_incident(incident)), 201


@bp.get("/api/incident-service-requests")
def list_incidents():
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    records = list(DB.incidents.values())
    system_id = common.arg("robot_system_id")
    if system_id:
        records = [r for r in records if r.get("robot_system_id") == system_id]
    status = common.arg("request_status")
    if status:
        records = [r for r in records if r.get("request_status") == status]
    return common.paged(records, "incidents")


@bp.get("/api/incident-service-requests/<incident_id>")
def get_incident(incident_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    return success(ser_incident(common.get_incident(incident_id)))


@bp.get("/api/robot-systems/<system_id>/incident-service-requests")
def list_system_incidents(system_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    common.get_system(system_id)
    records = calc.incidents_of_system(system_id)
    status = common.arg("request_status")
    if status:
        records = [r for r in records if r.get("request_status") == status]
    return common.paged(records, "incidents")


@bp.post("/api/incident-service-requests/<incident_id>/acknowledge")
def acknowledge_incident(incident_id):
    """Acknowledge an incident, stopping the response-time clock."""
    authenticate(["ServiceEngineer"])
    incident = common.get_incident(incident_id)
    data = common.body()
    check_version(incident, data, "expected_incident_version")
    incident["request_status"] = "ACKNOWLEDGED"
    incident["acknowledged_at_utc"] = to_iso(DB.clock)
    touch(incident)
    return success(ser_incident(incident))


@bp.post("/api/incident-service-requests/<incident_id>/resolve")
def resolve_incident(incident_id):
    """Resolve an incident, score its penalty and refresh the balance."""
    authenticate(["ServiceEngineer"])
    incident = common.get_incident(incident_id)
    account = DB.hospital_accounts.get(incident.get("_account_id"))
    data = common.body()
    check_version(incident, data, "expected_incident_version")
    incident["request_status"] = "RESOLVED"
    incident["resolved_at_utc"] = to_iso(DB.clock)
    if data.get("resolution_notes") is not None:
        incident["resolution_notes"] = as_str(data.get("resolution_notes"))
    touch(incident)
    if account is not None:
        account["_coverage_ceiling_points"] = calc.penalty_balance(account)
    return success(ser_incident(incident))


# ---------------------------------------------------------------------------
# Loaner dispatches
# ---------------------------------------------------------------------------

@bp.post("/api/loaner-dispatches")
def program_dispatch():
    """Program a loaner unit against a system's outage window."""
    ctx = authenticate(["ServiceEngineer"])
    data = common.body()
    system = common.get_system(common.require_str(data, "robot_system_id"))
    account = common.get_account(system.get("hospital_account_id"))
    check_region(ctx, account)
    serial = common.require_str(data, "loaner_serial_number")
    start = common.require_dt(data, "dispatch_window_start_utc")
    end = common.require_dt(data, "dispatch_window_end_utc")
    # Priority 30 — the declared window must be coherent.
    if not end > start:
        raise ApiError("ERR_INVALID_WINDOW")
    # Priority 21 — the buffered occupancy must not overlap a non-terminal
    # dispatch on the same loaner unit; adjacency is permitted.
    if calc.loaner_conflict(start, serial, DB.loaner_dispatches.values()):
        raise ApiError("ERR_LOANER_WINDOW_CONFLICT")
    dispatch = base_record({
        "robot_system_id": system.get("id"),
        "loaner_serial_number": serial,
        "dispatch_window_start_utc": to_iso(start),
        "dispatch_window_end_utc": to_iso(end),
        "reservation_status": "PROGRAMMED",
        "reclaim_reason": None,
    })
    DB.loaner_dispatches[dispatch["id"]] = dispatch
    return success(ser_dispatch(dispatch)), 201


@bp.get("/api/loaner-dispatches")
def list_dispatches():
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    records = list(DB.loaner_dispatches.values())
    system_id = common.arg("robot_system_id")
    if system_id:
        records = [r for r in records if r.get("robot_system_id") == system_id]
    status = common.arg("reservation_status")
    if status:
        records = [r for r in records if r.get("reservation_status") == status]
    return common.paged(records, "loaner_dispatches")


@bp.get("/api/loaner-dispatches/<dispatch_id>")
def get_dispatch(dispatch_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    return success(ser_dispatch(common.get_dispatch(dispatch_id)))


@bp.get("/api/robot-systems/<system_id>/loaner-dispatches")
def list_system_dispatches(system_id):
    authenticate(["PlatformAdmin", "ServiceEngineer"])
    common.get_system(system_id)
    records = calc.dispatches_of_system(system_id)
    status = common.arg("reservation_status")
    if status:
        records = [r for r in records if r.get("reservation_status") == status]
    return common.paged(records, "loaner_dispatches")


@bp.post("/api/loaner-dispatches/<dispatch_id>/activate")
def activate_dispatch(dispatch_id):
    authenticate(["ServiceEngineer"])
    dispatch = common.get_dispatch(dispatch_id)
    data = common.body()
    if dispatch.get("reservation_status") != "PROGRAMMED":
        raise ApiError("ERR_INVALID_REQUEST")
    check_version(dispatch, data, "expected_dispatch_version")
    dispatch["reservation_status"] = "ACTIVATED"
    touch(dispatch)
    return success(ser_dispatch(dispatch))