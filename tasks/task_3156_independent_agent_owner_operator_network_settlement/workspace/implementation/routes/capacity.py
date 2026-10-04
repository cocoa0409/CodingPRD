"""CapacityOwner, Equipment and ComplianceDocument routes."""
from __future__ import annotations

from flask import Blueprint, request

from cascades import (
    abort_trips_of_bco, abort_trips_of_equipment, take_fleet_out_of_service,
)
from common import (
    STATE, ApiError, bad_request, body, client_fields, clock_dt, err, fetch,
    find, mint, ok, ok_empty, ok_list, paginate, parse_ts, query_str,
    require_auth, require_int, require_pct, require_bool, require_enum,
    require_role, require_text, require_ts, touch,
)
from domain import (
    EQUIPMENT_TYPES, ESCROW_BALANCE_FLOOR_CENTS, ESCROW_MIN_CENTS,
    MIN_ESCROW_FOR_DECERT_CENTS, REQUIRED_DOCUMENT_TYPES, SAFETY_MIN_SCORE,
    document_status, equipment_inspection_status, present, present_all,
    sync_bco, sync_document, sync_equipment, sync_trip,
)
from entities import apply_split

bp = Blueprint("capacity", __name__)

BCO_CREATE_ROLES = ("NetworkAdministrator",)
DOCUMENT_TYPES = ("CDL", "MEDICAL_CARD", "MVR_REPORT", "DRUG_TEST",
                  "OA_ENROLLMENT", "LIABILITY_INSURANCE")


# ─── CapacityOwner ───────────────────────────────────────────────────────────
@bp.post("/network/capacity-owners")
def create_capacity_owner():
    require_role(*BCO_CREATE_ROLES)
    payload = body()
    fields = client_fields(payload, [
        "owner_code", "legal_name", "home_terminal_city", "revenue_split_pct",
        "oa_enrolled", "liability_insurance_deductible_cents",
    ])
    owner_code = require_text(fields, "owner_code")
    for row in STATE.capacity_owners.values():
        if row["owner_code"] == owner_code:
            raise ApiError("ERR_DUPLICATE_OWNER_CODE", 409,
                           f"owner_code {owner_code} already exists in the network.")
    row = mint("capacity_owners", {
        "owner_code": owner_code,
        "legal_name": require_text(fields, "legal_name"),
        "home_terminal_city": require_text(fields, "home_terminal_city"),
        "revenue_split_pct": require_pct(fields, "revenue_split_pct"),
        "oa_enrolled": require_bool(fields, "oa_enrolled", False),
        "liability_insurance_deductible_cents": require_int(
            fields, "liability_insurance_deductible_cents", 250000, minimum=0),
        "escrow_balance_cents": 0,
        "maintenance_balance_cents": 0,
        "outstanding_advance_cents": 0,
        "safety_score": 100,
        "qualified_until": None,
        "qualification_posture": "QUALIFICATION_RESTRICTED",
        "status": "PENDING_QUALIFICATION",
    })
    sync_bco(row, bump=False)
    return ok(present("capacity_owner", row), 201)


@bp.get("/network/capacity-owners")
def list_capacity_owners():
    require_role("FreightAgent", "NetworkAdministrator", "SettlementOperator")
    rows = list(STATE.capacity_owners.values())
    status = query_str("status")
    posture = query_str("qualification_posture")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if posture:
        rows = [r for r in rows if present("capacity_owner", r)["qualification_posture"] == posture]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("capacity_owner", page), total, limit, offset)


@bp.get("/network/capacity-owners/<row_id>")
def get_capacity_owner(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SettlementOperator",
                 "NetworkAdministrator")
    row = fetch("capacity_owner", row_id)
    return ok(present("capacity_owner", row))


@bp.get("/network/capacity-owners/<row_id>/equipment")
def list_owner_equipment(row_id):
    require_role("FreightAgent", "CapacityOwnerOperator", "SafetyReviewer",
                 "NetworkAdministrator")
    fetch("capacity_owner", row_id)
    rows = [e for e in STATE.equipment.values() if e["capacity_owner_id"] == row_id]
    status = query_str("status")
    inspection = query_str("inspection_status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if inspection:
        rows = [r for r in rows
                if equipment_inspection_status(r, clock_dt()) == inspection]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("equipment", page), total, limit, offset)


@bp.get("/network/capacity-owners/<row_id>/compliance-documents")
def list_owner_documents(row_id):
    require_role("CapacityOwnerOperator", "SafetyReviewer", "NetworkAdministrator")
    fetch("capacity_owner", row_id)
    rows = [d for d in STATE.compliance_documents.values()
            if d["capacity_owner_id"] == row_id]
    doc_type = query_str("document_type")
    status = query_str("status")
    if doc_type:
        rows = [r for r in rows if r["document_type"] == doc_type]
    if status:
        rows = [r for r in rows if document_status(r, clock_dt()) == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("compliance_document", page), total, limit, offset)


@bp.get("/network/capacity-owners/<row_id>/escrow-transactions")
def list_owner_ledger(row_id):
    require_role("CapacityOwnerOperator", "SettlementOperator", "NetworkAdministrator")
    fetch("capacity_owner", row_id)
    rows = [t for t in STATE.escrow_transactions.values()
            if t["capacity_owner_id"] == row_id]
    kind = query_str("transaction_type")
    status = query_str("status")
    from_ts = _query_ts("from_effective_at")
    to_ts = _query_ts("to_effective_at")
    if kind:
        rows = [r for r in rows if r["transaction_type"] == kind]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if from_ts is not None:
        rows = [r for r in rows if parse_ts(r["effective_at"], "effective_at") >= from_ts]
    if to_ts is not None:
        rows = [r for r in rows if parse_ts(r["effective_at"], "effective_at") <= to_ts]
    rows.sort(key=lambda r: (r["effective_at"], r["created_at"]))
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("escrow_transaction", page), total, limit, offset)


@bp.get("/network/capacity-owners/<row_id>/trips")
def list_owner_trips(row_id):
    require_role("CapacityOwnerOperator", "SettlementOperator", "SafetyReviewer",
                 "NetworkAdministrator")
    fetch("capacity_owner", row_id)
    rows = [t for t in STATE.trips.values() if t["capacity_owner_id"] == row_id]
    status = query_str("status")
    from_ts = _query_ts("from_departed_at")
    to_ts = _query_ts("to_departed_at")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if from_ts is not None:
        rows = [r for r in rows if parse_ts(r["departed_at"], "departed_at") >= from_ts]
    if to_ts is not None:
        rows = [r for r in rows if parse_ts(r["departed_at"], "departed_at") <= to_ts]
    rows.sort(key=lambda r: (r["departed_at"], r["created_at"]))
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("trip", page), total, limit, offset)


@bp.get("/network/capacity-owners/<row_id>/settlements")
def list_owner_settlements(row_id):
    require_role("CapacityOwnerOperator", "SettlementOperator", "NetworkAdministrator")
    fetch("capacity_owner", row_id)
    rows = [s for s in STATE.settlements.values() if s["capacity_owner_id"] == row_id]
    status = query_str("status")
    method = query_str("settlement_method")
    if status:
        rows = [r for r in rows if r["status"] == status]
    if method:
        rows = [r for r in rows if r["settlement_method"] == method]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("settlement", page), total, limit, offset)


@bp.post("/network/capacity-owners/<row_id>/qualify")
def qualify_capacity_owner(row_id):
    require_role("SafetyReviewer")
    row = fetch("capacity_owner", row_id)
    payload = body()
    fields = client_fields(payload, ["expected_network_capacity_owner_version"])
    expected = require_int(fields, "expected_network_capacity_owner_version")
    if row["status"] != "PENDING_QUALIFICATION":
        raise ApiError("ERR_CAPACITY_OWNER_NOT_QUALIFIABLE", 409,
                       "Capacity owner is not in PENDING_QUALIFICATION.")
    if expected != row["version"]:
        raise _stale("CapacityOwner", expected, row["version"])
    clock = clock_dt()
    docs = [d for d in STATE.compliance_documents.values()
            if d["capacity_owner_id"] == row_id]
    for doc_type in REQUIRED_DOCUMENT_TYPES:
        ok_doc = any(
            d["document_type"] == doc_type
            and document_status(d, clock) != "REJECTED"
            and parse_ts(d["expires_at"], "expires_at") > clock
            for d in docs
        )
        if not ok_doc:
            raise ApiError("ERR_SAFETY_DOCUMENT_MISSING", 422,
                           f"No unexpired {doc_type} credential on file.")
    if row["safety_score"] < SAFETY_MIN_SCORE:
        raise ApiError("ERR_SAFETY_SCORE_BELOW_MINIMUM", 422,
                       "Safety score is below the minimum.")
    if not any(e["capacity_owner_id"] == row_id and e["status"] == "IN_SERVICE"
               for e in STATE.equipment.values()):
        raise ApiError("ERR_EQUIPMENT_NOT_QUALIFIED", 422,
                       "The owner has no unit in service eligible to haul.")
    row["status"] = "QUALIFIED"
    sync_bco(row)
    return ok(present("capacity_owner", row))


@bp.post("/network/capacity-owners/<row_id>/deep-clone")
def deep_clone_capacity_owner(row_id):
    require_role("NetworkAdministrator")
    source = fetch("capacity_owner", row_id)
    payload = body()
    fields = client_fields(payload, ["source_capacity_owner_id"])
    supplied = require_text(fields, "source_capacity_owner_id")
    if supplied != row_id:
        raise ApiError("ERR_CAPACITY_OWNER_NOT_FOUND", 404,
                       f"No capacity owner with id {supplied}.")
    suffix = 1
    existing = {r["owner_code"] for r in STATE.capacity_owners.values()}
    while f"{source['owner_code']}-CLONE-{suffix}" in existing:
        suffix += 1
    row = mint("capacity_owners", {
        "owner_code": f"{source['owner_code']}-CLONE-{suffix}",
        "legal_name": f"{source['legal_name']} (Clone {suffix})",
        "home_terminal_city": source["home_terminal_city"],
        "revenue_split_pct": source["revenue_split_pct"],
        "oa_enrolled": source["oa_enrolled"],
        "liability_insurance_deductible_cents":
            source["liability_insurance_deductible_cents"],
        "escrow_balance_cents": 0,
        "maintenance_balance_cents": 0,
        "outstanding_advance_cents": 0,
        "safety_score": 100,
        "qualified_until": None,
        "qualification_posture": "QUALIFICATION_RESTRICTED",
        "status": "PENDING_QUALIFICATION",
    })
    sync_bco(row, bump=False)
    return ok(present("capacity_owner", row), 201)


@bp.post("/network/capacity-owners/<row_id>/suspend")
def suspend_capacity_owner(row_id):
    require_role("SafetyReviewer")
    row = fetch("capacity_owner", row_id)
    fields = client_fields(body(), ["reason_code"])
    require_text(fields, "reason_code")
    if row["status"] != "QUALIFIED":
        raise ApiError("ERR_CAPACITY_OWNER_NOT_QUALIFIED", 409,
                       "Capacity owner is not QUALIFIED.")
    row["status"] = "OUT_OF_SERVICE"
    take_fleet_out_of_service(row_id)
    abort_trips_of_bco(row_id)
    from cascades import release_awarded_loads
    release_awarded_loads(row_id, ("AWARDED",))
    sync_bco(row)
    return ok(present("capacity_owner", row))


@bp.post("/network/capacity-owners/<row_id>/reinstate")
def reinstate_capacity_owner(row_id):
    require_role("SafetyReviewer")
    row = fetch("capacity_owner", row_id)
    fields = client_fields(body(), ["reason_code"])
    if "reason_code" in fields:
        require_text(fields, "reason_code")
    if row["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_CAPACITY_OWNER_NOT_OUT_OF_SERVICE", 409,
                       "Capacity owner is not OUT_OF_SERVICE.")
    if row["safety_score"] < SAFETY_MIN_SCORE:
        raise ApiError("ERR_SAFETY_SCORE_BELOW_MINIMUM", 422,
                       "Safety score is below the minimum.")
    if row["escrow_balance_cents"] < ESCROW_MIN_CENTS:
        raise ApiError("ERR_ESCROW_BALANCE_INSUFFICIENT", 402,
                       "Escrow balance is below the required floor.")
    for unit in STATE.equipment.values():
        if unit["capacity_owner_id"] == row_id \
                and equipment_inspection_status(unit, clock_dt()) == "OVERDUE":
            raise ApiError("ERR_EQUIPMENT_INSPECTION_OVERDUE", 409,
                           "A unit of this owner carries an overdue inspection.")
    row["status"] = "QUALIFIED"
    sync_bco(row)
    return ok(present("capacity_owner", row))


@bp.post("/network/capacity-owners/<row_id>/decertify")
def decertify_capacity_owner(row_id):
    require_role("SafetyReviewer")
    row = fetch("capacity_owner", row_id)
    fields = client_fields(body(), ["reason_code"])
    if "reason_code" in fields:
        require_text(fields, "reason_code")
    if row["status"] == "DECERTIFIED":
        raise ApiError("ERR_CAPACITY_OWNER_ALREADY_DECERTIFIED", 409,
                       "Capacity owner is already DECERTIFIED.")
    if row["escrow_balance_cents"] < MIN_ESCROW_FOR_DECERT_CENTS:
        raise ApiError("ERR_ESCROW_BALANCE_INSUFFICIENT", 402,
                       "Escrow balance is below the decertification floor.")
    row["status"] = "DECERTIFIED"
    take_fleet_out_of_service(row_id)
    abort_trips_of_bco(row_id)
    from cascades import release_awarded_loads
    release_awarded_loads(row_id, ("AWARDED", "COVERED"))
    sync_bco(row)
    return ok(present("capacity_owner", row))


# ─── Equipment ───────────────────────────────────────────────────────────────
@bp.post("/network/equipment")
def create_equipment():
    require_role("SafetyReviewer", "NetworkAdministrator")
    payload = body()
    fields = client_fields(payload, [
        "capacity_owner_id", "unit_number", "equipment_type", "model_year",
        "inspection_due_at",
    ])
    owner = fetch("capacity_owner", require_text(fields, "capacity_owner_id"))
    unit_number = require_text(fields, "unit_number")
    for row in STATE.equipment.values():
        if row["capacity_owner_id"] == owner["id"] and row["unit_number"] == unit_number:
            raise ApiError("ERR_DUPLICATE_UNIT_NUMBER", 409,
                           f"unit_number {unit_number} already exists in this fleet.")
    due = require_ts(fields, "inspection_due_at")
    row = mint("equipment", {
        "capacity_owner_id": owner["id"],
        "unit_number": unit_number,
        "equipment_type": require_enum(fields, "equipment_type", EQUIPMENT_TYPES),
        "model_year": require_int(fields, "model_year", minimum=1980, maximum=2030),
        "inspection_due_at": fields["inspection_due_at"],
        "_inspection_due_dt": due,
        "inspection_passed_at": None,
        "inspection_status": "DUE",
        "status": "PENDING_INSPECTION",
    })
    sync_equipment(row, bump=False)
    sync_bco(owner)
    return ok(present("equipment", row), 201)


@bp.get("/network/equipment")
def list_equipment():
    require_role("SafetyReviewer", "NetworkAdministrator")
    rows = list(STATE.equipment.values())
    owner_id = query_str("capacity_owner_id")
    status = query_str("status")
    inspection = query_str("inspection_status")
    if owner_id:
        rows = [r for r in rows if r["capacity_owner_id"] == owner_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    if inspection:
        rows = [r for r in rows
                if equipment_inspection_status(r, clock_dt()) == inspection]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("equipment", page), total, limit, offset)


def _load_unit(row_id):
    return fetch("equipment", row_id)


@bp.get("/network/equipment/<row_id>")
def get_equipment(row_id):
    require_role("CapacityOwnerOperator", "SafetyReviewer", "NetworkAdministrator")
    return ok(present("equipment", _load_unit(row_id)))


@bp.get("/network/equipment/<row_id>/trips")
def list_equipment_trips(row_id):
    require_role("CapacityOwnerOperator", "SafetyReviewer", "NetworkAdministrator")
    _load_unit(row_id)
    rows = [t for t in STATE.trips.values() if t["equipment_id"] == row_id]
    status = query_str("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["departed_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("trip", page), total, limit, offset)


@bp.post("/network/equipment/<row_id>/record-inspection")
def record_inspection(row_id):
    require_role("SafetyReviewer")
    unit = _load_unit(row_id)
    payload = body()
    fields = client_fields(payload, [
        "inspected_at", "result", "inspector_certificate",
    ])
    if unit["status"] == "RETIRED":
        raise ApiError("ERR_EQUIPMENT_ALREADY_RETIRED", 409,
                       "The unit is RETIRED and accepts no inspection.")
    inspected_at = require_ts(fields, "inspected_at")
    result = require_text(fields, "result")
    due = unit["_inspection_due_dt"]
    owner = STATE.capacity_owners.get(unit["capacity_owner_id"])

    if unit["status"] == "IN_SERVICE":
        if result == "PASS":
            if inspected_at >= due:
                raise ApiError("ERR_EQUIPMENT_INSPECTION_OVERDUE", 409,
                               "inspected_at is at or after inspection_due_at.")
            unit["inspection_passed_at"] = fields["inspected_at"]
            sync_equipment(unit)
            if owner is not None:
                sync_bco(owner)
            return ok(present("equipment", unit))
        # FAIL on an in-service unit moves it backwards to PENDING_INSPECTION.
        if owner is None or owner["status"] not in ("PENDING_QUALIFICATION", "QUALIFIED"):
            raise ApiError("ERR_CAPACITY_OWNER_NOT_QUALIFIED", 409,
                           "The owning capacity owner is not in a qualifying status.")
        if inspected_at >= due:
            raise ApiError("ERR_EQUIPMENT_INSPECTION_OVERDUE", 409,
                           "inspected_at is at or after inspection_due_at.")
        unit["status"] = "PENDING_INSPECTION"
        unit["_restricted"] = True
        sync_equipment(unit)
        abort_trips_of_equipment(row_id)
        if owner is not None:
            sync_bco(owner)
        return ok(present("equipment", unit))

    # From PENDING_INSPECTION or OUT_OF_SERVICE only a pass returns a unit to service.
    require_text(fields, "inspector_certificate")
    if inspected_at >= due:
        raise ApiError("ERR_EQUIPMENT_INSPECTION_OVERDUE", 409,
                       "inspected_at is at or after inspection_due_at.")
    if result != "PASS":
        raise ApiError("ERR_EQUIPMENT_INSPECTION_FAILED", 400,
                       "Only a PASS result returns a unit to service.")
    if owner is None or owner["status"] not in ("PENDING_QUALIFICATION", "QUALIFIED"):
        raise ApiError("ERR_CAPACITY_OWNER_NOT_QUALIFIED", 409,
                       "The owning capacity owner is not in a qualifying status.")
    unit["inspection_passed_at"] = fields["inspected_at"]
    unit["status"] = "IN_SERVICE"
    unit["_restricted"] = False
    sync_equipment(unit)
    sync_bco(owner)
    return ok(present("equipment", unit))


@bp.post("/network/equipment/<row_id>/place-out-of-service")
def place_equipment_out_of_service(row_id):
    require_role("SafetyReviewer")
    unit = _load_unit(row_id)
    fields = client_fields(body(), ["reason_code"])
    require_text(fields, "reason_code")
    if unit["status"] != "IN_SERVICE":
        raise ApiError("ERR_EQUIPMENT_NOT_IN_SERVICE", 409,
                       "The unit is not IN_SERVICE.")
    unit["status"] = "OUT_OF_SERVICE"
    # A unit the reviewer takes off the road is a live restriction input.
    unit["_restricted"] = True
    sync_equipment(unit)
    abort_trips_of_equipment(row_id)
    owner = STATE.capacity_owners.get(unit["capacity_owner_id"])
    if owner is not None:
        sync_bco(owner)
    return ok(present("equipment", unit))


@bp.post("/network/equipment/<row_id>/retire")
def retire_equipment(row_id):
    require_role("NetworkAdministrator")
    unit = _load_unit(row_id)
    fields = client_fields(body(), ["reason_code"])
    if "reason_code" in fields:
        require_text(fields, "reason_code")
    if unit["status"] == "RETIRED":
        raise ApiError("ERR_EQUIPMENT_ALREADY_RETIRED", 409,
                       "The unit is already RETIRED.")
    if unit["status"] == "IN_SERVICE":
        for trip in STATE.trips.values():
            if trip["equipment_id"] == row_id \
                    and trip["status"] in ("DISPATCH_PENDING", "EN_ROUTE"):
                raise ApiError("ERR_EQUIPMENT_HAS_ACTIVE_TRIP", 409,
                               "A trip on this unit is still non-terminal.")
    if unit["status"] == "PENDING_INSPECTION":
        owner = STATE.capacity_owners.get(unit["capacity_owner_id"])
        territory = list(owner["territory_codes"]) if owner else []
        for offer in STATE.load_offers.values():
            if offer["status"] != "OPEN":
                continue
            load = STATE.loads.get(offer["load_id"])
            if load is None:
                continue
            if load["awarded_capacity_owner_id"] != unit["capacity_owner_id"]:
                continue
            if load["origin_state"] in territory:
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "An open offer references a load held by this fleet.")
    unit["status"] = "RETIRED"
    sync_equipment(unit)
    abort_trips_of_equipment(row_id)
    owner = STATE.capacity_owners.get(unit["capacity_owner_id"])
    if owner is not None:
        sync_bco(owner)
    return ok(present("equipment", unit))


# ─── ComplianceDocument ──────────────────────────────────────────────────────
@bp.post("/network/compliance-documents")
def create_compliance_document():
    require_role("SafetyReviewer")
    payload = body()
    fields = client_fields(payload, [
        "capacity_owner_id", "document_type", "document_number", "issued_at",
        "expires_at",
    ])
    owner = fetch("capacity_owner", require_text(fields, "capacity_owner_id"))
    issued_at = require_ts(fields, "issued_at")
    expires_at = require_ts(fields, "expires_at")
    if expires_at <= issued_at:
        raise bad_request("expires_at must be strictly after issued_at.")
    row = mint("compliance_documents", {
        "capacity_owner_id": owner["id"],
        "document_type": require_enum(fields, "document_type", DOCUMENT_TYPES),
        "document_number": require_text(fields, "document_number"),
        "issued_at": fields["issued_at"],
        "expires_at": fields["expires_at"],
        "_issued_at": fields["issued_at"],
        "_expires_at": fields["expires_at"],
        "_expires_dt": expires_at,
        "_status": "VALID",
        "_verified": False,
        "status": "VALID",
    })
    sync_document(row, bump=False)
    sync_bco(owner)
    return ok(present("compliance_document", row), 201)


@bp.get("/network/compliance-documents")
def list_compliance_documents():
    require_role("SafetyReviewer", "NetworkAdministrator")
    rows = list(STATE.compliance_documents.values())
    owner_id = query_str("capacity_owner_id")
    doc_type = query_str("document_type")
    status = query_str("status")
    if owner_id:
        rows = [r for r in rows if r["capacity_owner_id"] == owner_id]
    if doc_type:
        rows = [r for r in rows if r["document_type"] == doc_type]
    if status:
        rows = [r for r in rows if document_status(r, clock_dt()) == status]
    rows.sort(key=lambda r: r["created_at"])
    page, total, limit, offset = paginate(rows)
    return ok_list(present_all("compliance_document", page), total, limit, offset)


@bp.get("/network/compliance-documents/<row_id>")
def get_compliance_document(row_id):
    require_role("CapacityOwnerOperator", "SafetyReviewer", "NetworkAdministrator")
    row = fetch("compliance_document", row_id)
    return ok(present("compliance_document", row))


@bp.post("/network/compliance-documents/<row_id>/verify")
def verify_compliance_document(row_id):
    require_role("SafetyReviewer")
    row = fetch("compliance_document", row_id)
    payload = body()
    fields = client_fields(payload, ["verified_at"])
    if "verified_at" in fields:
        parse_ts(fields["verified_at"], "verified_at")
    # The verification is what observes the lapse and cascades to the host.
    row["_verified"] = True
    sync_document(row)
    owner = STATE.capacity_owners.get(row["capacity_owner_id"])
    if owner is not None:
        sync_bco(owner)
    return ok(present("compliance_document", row))


def _query_ts(name: str):
    value = query_str(name)
    if value is None:
        return None
    return parse_ts(value, name)


def _stale(label: str, expected: int, actual: int) -> ApiError:
    return ApiError("ERR_STALE_VERSION", 412,
                    f"expected version {expected} does not match the current "
                    f"{label} version {actual}.")