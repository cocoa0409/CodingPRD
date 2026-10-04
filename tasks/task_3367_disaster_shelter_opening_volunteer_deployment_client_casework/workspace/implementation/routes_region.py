"""Region, disaster relief operation, fund pool and cost ledger endpoints."""

from flask import Blueprint, request

import calc
import core
from core import (authenticate, base_row, find, insert, list_response, must_get,
                  ok_object, read_json, rows, serialize, touch, validate_body,
                  validate_enum)
from errors import ApiError

bp = Blueprint("region", __name__)

REGION_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "BloodServicesCoordinator"]
OP_ROLES = ["NationalHQAdmin", "RegionalCoordinator", "FinanceOfficer"]
INCIDENT_TYPES = ("HURRICANE", "WILDFIRE", "FLOOD", "EARTHQUAKE", "TORNADO")
RESTRICTIONS = ("UNRESTRICTED", "DONOR_RESTRICTED_DISASTER", "DONOR_RESTRICTED_BLOOD",
                "DONOR_RESTRICTED_LOCAL")
COST_CATEGORIES = ("SHELTER_OPERATIONS", "FEEDING", "VOLUNTEER_TRAVEL",
                   "FINANCIAL_ASSISTANCE", "HEALTH_SERVICES", "BLOOD_COLLECTION",
                   "LOGISTICS")
ENTRY_TYPES = ("CHARGE", "REVERSAL")


# ---------------------------------------------------------------- regions


@bp.post("/api/v1/regions")
def create_region():
    authenticate(["NationalHQAdmin"])
    body = read_json()
    validate_body(body, required={
        "code": str,
        "name": str,
        "state_codes": list,
        "coordinator_user_id": str,
        "volunteer_pool_target": int,
        "authorized_agency_codes": list,
    })
    if not body["code"].strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "code must be non-empty")
    if body["volunteer_pool_target"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "volunteer_pool_target must be >= 1")
    record = base_row()
    record.update({
        "code": body["code"],
        "name": body["name"],
        "state_codes": body["state_codes"],
        "coordinator_user_id": body["coordinator_user_id"],
        "volunteer_pool_target": body["volunteer_pool_target"],
        "authorized_agency_codes": body["authorized_agency_codes"],
        "available_volunteer_count": 0,
        "deployed_volunteer_count": 0,
        "blood_continuity_index": 0.0,
        "blood_continuity_status": "CRITICAL",
    })
    insert("regions", record)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/regions/<region_id>")
def read_region(region_id):
    authenticate(REGION_ROLES)
    region = must_get("regions", region_id)
    mode = request.args.get("continuity_mode") or "TRAILING"
    calc.refresh_region(region, mode if mode in ("TRAILING", "FORWARD_LOOKING") else "TRAILING")
    return ok_object(serialize(region))


def _region_children(region_id, table, roles, field="region_id"):
    authenticate(roles)
    region = must_get("regions", region_id)
    children = [row for row in rows(table) if row.get(field) == region["id"]]
    return list_response(children)


@bp.get("/api/v1/regions/<region_id>/disaster-relief-operations")
def region_operations(region_id):
    return _region_children(region_id, "disaster_relief_operations", REGION_ROLES)


@bp.get("/api/v1/regions/<region_id>/shelter-sites")
def region_sites(region_id):
    return _region_children(region_id, "shelter_sites",
                            ["NationalHQAdmin", "RegionalCoordinator", "ShelterManager"])


@bp.get("/api/v1/regions/<region_id>/volunteers")
def region_volunteers(region_id):
    return _region_children(region_id, "volunteers",
                            ["NationalHQAdmin", "RegionalCoordinator"], field="home_region_id")


@bp.get("/api/v1/regions/<region_id>/fund-pools")
def region_pools(region_id):
    return _region_children(region_id, "fund_pools",
                            ["NationalHQAdmin", "FinanceOfficer", "RegionalCoordinator"])


@bp.get("/api/v1/regions/<region_id>/blood-drives")
def region_drives(region_id):
    return _region_children(region_id, "blood_drives",
                            ["NationalHQAdmin", "BloodServicesCoordinator", "RegionalCoordinator"])


@bp.get("/api/v1/regions/<region_id>/clients")
def region_clients(region_id):
    return _region_children(region_id, "clients",
                            ["NationalHQAdmin", "RegionalCoordinator", "Caseworker"])


# ------------------------------------------------- disaster relief operations


@bp.post("/api/v1/disaster-relief-operations")
def create_operation():
    authenticate(["NationalHQAdmin", "RegionalCoordinator"])
    body = read_json()
    validate_body(body, required={
        "incident_code": str,
        "incident_type": str,
        "declared_at": "instant",
        "region_id": str,
    })
    validate_enum("incident_type", body["incident_type"], INCIDENT_TYPES)
    if not body["incident_code"].strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "incident_code must be non-empty")
    must_get("regions", body["region_id"])
    for existing in rows("disaster_relief_operations"):
        if existing["incident_code"] == body["incident_code"]:
            raise ApiError("ERR_DUPLICATE_INCIDENT_CODE", 409,
                           "incident_code already exists")
    record = base_row()
    record.update({
        "incident_code": body["incident_code"],
        "incident_type": body["incident_type"],
        "declared_at": core.iso_of(body["declared_at"]),
        "region_id": body["region_id"],
        "phase": "MOBILIZATION",
        "open_shelter_count": 0,
        "restricted_fund_balance_cents": 0,
    })
    insert("disaster_relief_operations", record)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/disaster-relief-operations/<operation_id>")
def read_operation(operation_id):
    authenticate(OP_ROLES)
    operation = must_get("disaster_relief_operations", operation_id)
    calc.refresh_operation(operation)
    return ok_object(serialize(operation))


@bp.post("/api/v1/disaster-relief-operations/<operation_id>/advance-phase")
def advance_phase(operation_id):
    authenticate(["NationalHQAdmin", "RegionalCoordinator"])
    validate_body(read_json(), required={})
    operation = must_get("disaster_relief_operations", operation_id)
    phase = operation["phase"]
    if phase == "CLOSED":
        raise ApiError("ERR_ALREADY_TERMINAL", 409, "the operation is closed")
    if phase == "MOBILIZATION":
        stood_up = any(s["disaster_relief_operation_id"] == operation["id"]
                       and s["posture"] in ("PENDING_OPEN", "OPEN", "RESTRICTED")
                       for s in rows("shelter_operations"))
        if not stood_up:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "no shelter operation exists under this operation")
        operation["phase"] = "ACTIVE"
    elif phase == "ACTIVE":
        calc.refresh_operation(operation)
        if operation["open_shelter_count"] > 2:
            raise ApiError("ERR_INVALID_STATE", 409, "too many open shelters to demobilize")
        operation["phase"] = "DEMOBILIZATION"
    elif phase == "DEMOBILIZATION":
        calc.refresh_operation(operation)
        if operation["open_shelter_count"] != 0:
            raise ApiError("ERR_INVALID_STATE", 409, "open shelters remain")
        operation["phase"] = "CLOSED"
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unknown phase")
    touch(operation)
    return ok_object(serialize(operation))


@bp.get("/api/v1/disaster-relief-operations/<operation_id>/deployment-candidates")
def deployment_candidates(operation_id):
    authenticate(["NationalHQAdmin", "RegionalCoordinator"])
    operation = must_get("disaster_relief_operations", operation_id)
    role_code = request.args.get("role_code")
    if not role_code:
        raise ApiError("ERR_INVALID_REQUEST", 400, "role_code is required")
    eligible = [v for v in rows("volunteers")
                if v["credential_status"] == "ACTIVE"
                and v["deployment_availability"] == "AVAILABLE"]
    if not eligible:
        raise ApiError("ERR_NO_ELIGIBLE_VOLUNTEER", 409, "no eligible volunteer is available")
    ranked = sorted(eligible, key=lambda v: (
        -calc.priority_score(v, operation, role_code),
        v.get("credential_refreshed_at") or "",
        v.get("created_at") or "",
    ))
    # PRD 3.5: "Candidates are returned highest score first" -- a workflow that
    # "states otherwise", so the generic created_at ordering of 2.3 must not be
    # re-applied on top of the ranking.
    limit, offset = core.pagination()
    window = ranked[offset:offset + limit]
    return core.ok_array(core.serialize_many(window), len(ranked), limit, offset)


# ---------------------------------------------------------------- fund pools


@bp.post("/api/v1/fund-pools")
def create_fund_pool():
    authenticate(["NationalHQAdmin", "FinanceOfficer"])
    body = read_json()
    validate_body(body, required={
        "fund_code": str,
        "restriction_type": str,
        "total_received_cents": int,
    }, optional={"region_id": str})
    validate_enum("restriction_type", body["restriction_type"], RESTRICTIONS)
    if not body["fund_code"].strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "fund_code must be non-empty")
    if body["total_received_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "total_received_cents must be >= 0")
    region_id = body.get("region_id")
    if region_id is not None:
        must_get("regions", region_id)
    for existing in rows("fund_pools"):
        if existing["fund_code"] == body["fund_code"]:
            raise ApiError("ERR_DUPLICATE_FUND_CODE", 409, "fund_code already exists")
    record = base_row()
    record.update({
        "fund_code": body["fund_code"],
        "restriction_type": body["restriction_type"],
        "region_id": region_id,
        "total_received_cents": body["total_received_cents"],
        "committed_cents": 0,
        "disbursed_cents": 0,
        "remaining_cents": body["total_received_cents"],
    })
    insert("fund_pools", record)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/fund-pools/<pool_id>")
def read_fund_pool(pool_id):
    authenticate(["NationalHQAdmin", "FinanceOfficer", "RegionalCoordinator"])
    pool = must_get("fund_pools", pool_id)
    calc.refresh_pool(pool)
    return ok_object(serialize(pool))


# ------------------------------------------------------------ cost ledger


@bp.post("/api/v1/disaster-relief-operations/<operation_id>/cost-ledger-entries")
def create_ledger_entry(operation_id):
    authenticate(["NationalHQAdmin", "FinanceOfficer"])
    body = read_json()
    validate_body(body, required={
        "expected_disaster_relief_operation_version": int,
        "fund_pool_id": str,
        "cost_category": str,
        "amount_cents": int,
        "entry_type": str,
        "incurred_at": "instant",
    })
    operation = must_get("disaster_relief_operations", operation_id)
    if body["expected_disaster_relief_operation_version"] != operation["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "the operation version is stale")
    must_get("fund_pools", body["fund_pool_id"])
    validate_enum("cost_category", body["cost_category"], COST_CATEGORIES)
    validate_enum("entry_type", body["entry_type"], ENTRY_TYPES)
    if body["amount_cents"] < 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "amount_cents must be >= 1")
    record = base_row()
    record.update({
        "disaster_relief_operation_id": operation["id"],
        "fund_pool_id": body["fund_pool_id"],
        "cost_category": body["cost_category"],
        "amount_cents": body["amount_cents"],
        "entry_type": body["entry_type"],
        "incurred_at": core.iso_of(body["incurred_at"]),
    })
    insert("cost_ledger_entries", record)
    before = operation["version"]
    calc.refresh_operation(operation)
    if operation["version"] == before:
        touch(operation)
    return ok_object(serialize(record), 201)


@bp.get("/api/v1/cost-ledger-entries/<entry_id>")
def read_ledger_entry(entry_id):
    authenticate(["NationalHQAdmin", "FinanceOfficer"])
    return ok_object(serialize(must_get("cost_ledger_entries", entry_id)))


@bp.get("/api/v1/cost-ledger-entries")
def list_ledger_entries():
    authenticate(["NationalHQAdmin", "FinanceOfficer"])
    entries = rows("cost_ledger_entries")
    operation_id = request.args.get("disaster_relief_operation_id")
    pool_id = request.args.get("fund_pool_id")
    if operation_id:
        entries = [e for e in entries if e["disaster_relief_operation_id"] == operation_id]
    if pool_id:
        entries = [e for e in entries if e["fund_pool_id"] == pool_id]
    return list_response(entries)
