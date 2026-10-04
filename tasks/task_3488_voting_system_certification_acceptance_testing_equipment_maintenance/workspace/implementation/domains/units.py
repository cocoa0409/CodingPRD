"""EquipmentUnit endpoints (PRD 3.7) and custody transfers (PRD 2.9).

Two parallel state dimensions (operational_status, custody_status) evolve
independently. IN_MAINTENANCE is system-managed: direct writes are
ERR_INVALID_STATE. While QUARANTINED, custody transfers, deploy/store, and
work-order creation are rejected with ERR_UNIT_QUARANTINED (PRD 3.7 prose);
the quarantine gate is therefore evaluated before generic state legality for
deploy/store requests on this endpoint.
"""
from flask import Blueprint

from auth import auth_context, peek_to_state, require_acting_official, require_role, require_transition_actor
from constants import (
    BATTERY_CYCLE_MAX,
    STORAGE_HUMIDITY_MAX_PCT,
    STORAGE_HUMIDITY_MIN_PCT,
    STORAGE_TEMP_MAX_C,
    STORAGE_TEMP_MIN_C,
)
from envelope import apply_filters, list_page, ok_object
from errors import err_forbidden_ownership, err_invalid_request, err_invalid_state, err_not_found, raise_err
from store import db
from util import now, stamp_new, touch
from validation import body_json, no_extra, req_bool, req_enum, req_int, req_str

bp = Blueprint("units", __name__)

UNIT_STATES = {"IN_STORAGE", "IN_SERVICE", "IN_MAINTENANCE", "QUARANTINED", "RETIRED", "SECURED", "UNSEALED"}
UNIT_ACTORS = {
    "IN_SERVICE": {"ElectionOfficial"},
    "IN_STORAGE": {"ElectionOfficial", "CertificationAuthority"},
    "QUARANTINED": {"CertificationAuthority"},
    "RETIRED": {"ElectionOfficial"},
}
UNIT_FROM = {
    "IN_SERVICE": {"IN_STORAGE"},
    "IN_STORAGE": {"IN_SERVICE", "QUARANTINED"},
    "QUARANTINED": {"IN_SERVICE", "IN_STORAGE"},
    "RETIRED": {"IN_SERVICE", "IN_STORAGE"},
}


def abort_open_work_orders(unit, restoring):
    """Abort SCHEDULED/IN_PROGRESS work orders of a unit.

    restoring=True (retire path): an IN_PROGRESS abort restores the unit's
    pre-maintenance status before the caller applies the terminal status.
    restoring=False (quarantine path): the unit stays QUARANTINED and
    pre_maintenance_status is cleared without restoration.
    """
    for wo in db.maintenance_work_orders.values():
        if wo["equipment_unit_id"] == unit["id"] and wo["status"] in {"SCHEDULED", "IN_PROGRESS"}:
            if wo["status"] == "IN_PROGRESS" and restoring:
                unit["operational_status"] = unit["pre_maintenance_status"]
            wo["status"] = "ABORTED"
            touch(wo)
    unit["pre_maintenance_status"] = None


@bp.post("/evote/equipment-units")
def create_unit():
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    body = body_json()
    no_extra(body, {"jurisdiction_id", "voting_system_id", "serial_number", "initial_custodian_id"})
    jurisdiction_id = req_str(body, "jurisdiction_id")
    system_id = req_str(body, "voting_system_id")
    serial = req_str(body, "serial_number")
    custodian_id = req_str(body, "initial_custodian_id")
    if db.jurisdictions.get(jurisdiction_id) is None:
        raise_err("ERR_JURISDICTION_NOT_FOUND", 404, "jurisdiction_id does not resolve")
    system = db.voting_systems.get(system_id)
    if system is None:
        raise_err("ERR_SYSTEM_NOT_FOUND", 404, "voting_system_id does not resolve")
    custodian = db.election_officials.get(custodian_id)
    if custodian is None:
        raise_err("ERR_OFFICIAL_NOT_FOUND", 404, "initial_custodian_id does not resolve")
    require_acting_official(uid, jurisdiction_id)
    for unit in db.equipment_units.values():
        if unit["serial_number"] == serial:
            raise_err("ERR_DUPLICATE_SERIAL", 409, "serial_number already registered")
    if system["status"] != "FIELDED":
        raise_err("ERR_SYSTEM_NOT_FIELDED", 422, "voting system must be FIELDED")
    if custodian["status"] != "ACTIVE":
        raise_err("ERR_OFFICIAL_INACTIVE", 422, "initial custodian is INACTIVE")
    if custodian["jurisdiction_id"] != jurisdiction_id:
        raise_err("ERR_OFFICIAL_JURISDICTION_MISMATCH", 422, "custodian belongs to another jurisdiction")
    rec = stamp_new({})
    rec.update({
        "jurisdiction_id": jurisdiction_id,
        "voting_system_id": system_id,
        "serial_number": serial,
        "operational_status": "IN_STORAGE",
        "custody_status": "SECURED",
        "current_custodian_id": custodian_id,
        "battery_cycles": 0,
        "storage_excursion_count": 0,
        "pre_maintenance_status": None,
        "calibrated_paper_weight_gsm": None,
        "calibrated_paper_thickness_microns": None,
    })
    db.equipment_units[rec["id"]] = rec
    return ok_object(rec, 201)


@bp.get("/evote/equipment-units")
def list_units():
    auth_context()
    items = apply_filters(
        list(db.equipment_units.values()),
        {"jurisdiction_id", "voting_system_id", "current_custodian_id", "operational_status", "custody_status"},
    )
    return list_page(items)


def get_unit_or_404(unit_id):
    unit = db.equipment_units.get(unit_id)
    if unit is None:
        err_not_found("equipment unit not found")
    return unit


@bp.get("/evote/equipment-units/<unit_id>")
def get_unit(unit_id):
    auth_context()
    return ok_object(get_unit_or_404(unit_id), 200)


@bp.post("/evote/equipment-units/<unit_id>/transitions")
def unit_transition(unit_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial", "CertificationAuthority"})
    ts = peek_to_state()
    require_transition_actor(role, ts, UNIT_ACTORS)
    unit = get_unit_or_404(unit_id)
    body = body_json()
    no_extra(body, {"to_state", "storage_temperature_c", "storage_humidity_pct"})
    to_state = req_enum(body, "to_state", UNIT_STATES)
    # Priority 4: the official store path carries the environment pair.
    store_from_service = to_state == "IN_STORAGE" and unit["operational_status"] == "IN_SERVICE"
    temp_c = hum_pct = None
    if store_from_service:
        temp_c = body.get("storage_temperature_c")
        hum_pct = body.get("storage_humidity_pct")
        if (
            (isinstance(temp_c, bool) or not isinstance(temp_c, (int, float)))
            or (isinstance(hum_pct, bool) or not isinstance(hum_pct, (int, float)))
        ):
            err_invalid_request("storage_temperature_c and storage_humidity_pct are required to store")
    # Priority 6: ElectionOfficial ownership (CertificationAuthority is opaque).
    if role == "ElectionOfficial":
        require_acting_official(uid, unit["jurisdiction_id"])
    # Quarantine gate (PRD 3.7): deploy/store against a QUARANTINED unit is
    # ERR_UNIT_QUARANTINED; only the CA release QUARANTINED -> IN_STORAGE passes.
    if unit["operational_status"] == "QUARANTINED":
        if role == "CertificationAuthority" and to_state == "IN_STORAGE":
            pass  # release path
        elif to_state in {"IN_SERVICE", "IN_STORAGE"}:
            raise_err("ERR_UNIT_QUARANTINED", 409, "unit is QUARANTINED")
    # Priority 8: state legality. IN_MAINTENANCE / custody states are
    # system-only targets -> invalid state.
    if to_state not in UNIT_FROM or unit["operational_status"] not in UNIT_FROM[to_state]:
        err_invalid_state("unit cannot transition from %s to %s" % (unit["operational_status"], to_state))
    # From-specific actor: the CA's IN_STORAGE transition is the quarantine
    # release only; storing from IN_SERVICE is an ElectionOfficial act.
    if to_state == "IN_STORAGE" and unit["operational_status"] == "IN_SERVICE" and role != "ElectionOfficial":
        raise_err("ERR_UNAUTHORIZED", 403, "only a jurisdiction official stores an in-service unit")
    if to_state == "QUARANTINED" and role != "CertificationAuthority":
        raise_err("ERR_UNAUTHORIZED", 403, "only the certification authority quarantines")
    # Priority 11: tamper-evidence safety on deploy/retire.
    if to_state in {"IN_SERVICE", "RETIRED"} and unit["custody_status"] != "SECURED":
        raise_err("ERR_UNIT_UNSEALED", 422, "custody seal is broken")
    # Priority 12: battery ceiling on deploy (exactly 500 rejected).
    if to_state == "IN_SERVICE" and unit["battery_cycles"] >= BATTERY_CYCLE_MAX:
        raise_err("ERR_BATTERY_CYCLE_LIMIT", 422, "battery cycle limit reached")
    # Priority 19: system must not be RETIRED on deploy.
    if to_state == "IN_SERVICE":
        system = db.voting_systems.get(unit["voting_system_id"])
        if system is not None and system["status"] == "RETIRED":
            raise_err("ERR_SYSTEM_RETIRED", 422, "voting system is RETIRED")
    # Apply.
    if to_state == "QUARANTINED":
        abort_open_work_orders(unit, restoring=False)
        unit["operational_status"] = "QUARANTINED"
    elif to_state == "RETIRED":
        abort_open_work_orders(unit, restoring=True)
        unit["operational_status"] = "RETIRED"
    elif to_state == "IN_STORAGE" and store_from_service:
        if not (STORAGE_TEMP_MIN_C <= temp_c <= STORAGE_TEMP_MAX_C) or not (
            STORAGE_HUMIDITY_MIN_PCT <= hum_pct <= STORAGE_HUMIDITY_MAX_PCT
        ):
            unit["storage_excursion_count"] += 1
        unit["operational_status"] = "IN_STORAGE"
    else:
        unit["operational_status"] = to_state
    touch(unit)
    return ok_object(unit, 200)


@bp.post("/evote/equipment-units/<unit_id>/record-usage")
def record_usage(unit_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    unit = get_unit_or_404(unit_id)
    body = body_json()
    no_extra(body, {"cycles_used"})
    cycles = req_int(body, "cycles_used", minv=0)
    require_acting_official(uid, unit["jurisdiction_id"])
    if unit["operational_status"] != "IN_SERVICE":
        err_invalid_state("usage accumulates only on an IN_SERVICE unit")
    unit["battery_cycles"] += cycles
    touch(unit)
    return ok_object(unit, 200)


@bp.post("/evote/equipment-units/<unit_id>/custody-transfers")
def create_custody_transfer(unit_id):
    uid, role = auth_context()
    require_role(role, {"ElectionOfficial"})
    unit = get_unit_or_404(unit_id)
    body = body_json()
    no_extra(body, {"to_official_id", "seal_number", "seal_intact"})
    to_official_id = req_str(body, "to_official_id")
    seal_number = req_str(body, "seal_number")
    seal_intact = req_bool(body, "seal_intact")
    to_official = db.election_officials.get(to_official_id)
    if to_official is None:
        raise_err("ERR_OFFICIAL_NOT_FOUND", 404, "to_official_id does not resolve")
    # Priority 6: the acting official must be the unit's current custodian.
    acting = db.election_officials.get(uid)
    if acting is None or uid != unit["current_custodian_id"]:
        err_forbidden_ownership("custody transfers are initiated by the current custodian")
    if acting["status"] != "ACTIVE":
        raise_err("ERR_OFFICIAL_INACTIVE", 422, "acting official is INACTIVE")
    if unit["operational_status"] == "QUARANTINED":
        raise_err("ERR_UNIT_QUARANTINED", 409, "unit is QUARANTINED")
    for transfer in db.custody_transfers.values():
        if transfer["equipment_unit_id"] == unit_id and transfer["seal_number"] == seal_number:
            raise_err("ERR_SEAL_NUMBER_REUSED", 409, "seal_number already used on this unit")
    if to_official_id == uid:
        raise_err("ERR_SELF_TRANSFER", 422, "cannot transfer custody to oneself")
    if to_official["status"] != "ACTIVE":
        raise_err("ERR_OFFICIAL_INACTIVE", 422, "receiving official is INACTIVE")
    if to_official["jurisdiction_id"] != unit["jurisdiction_id"]:
        raise_err("ERR_OFFICIAL_JURISDICTION_MISMATCH", 422, "receiving official is in another jurisdiction")
    rec = stamp_new({}, versioned=False)
    rec.update({
        "equipment_unit_id": unit_id,
        "from_official_id": uid,
        "to_official_id": to_official_id,
        "seal_number": seal_number,
        "seal_intact": seal_intact,
        "transferred_at": now(),
    })
    db.custody_transfers[rec["id"]] = rec
    unit["current_custodian_id"] = to_official_id
    if seal_intact is False:
        unit["custody_status"] = "UNSEALED"
    touch(unit)
    return ok_object(rec, 201)


@bp.get("/evote/equipment-units/<unit_id>/custody-transfers")
def list_custody_transfers(unit_id):
    auth_context()
    get_unit_or_404(unit_id)
    items = [t for t in db.custody_transfers.values() if t["equipment_unit_id"] == unit_id]
    return list_page(items)


@bp.get("/evote/equipment-units/<unit_id>/maintenance-work-orders")
def list_unit_work_orders(unit_id):
    auth_context()
    get_unit_or_404(unit_id)
    items = [w for w in db.maintenance_work_orders.values() if w["equipment_unit_id"] == unit_id]
    items = apply_filters(items, {"status", "work_type"})
    return list_page(items)
