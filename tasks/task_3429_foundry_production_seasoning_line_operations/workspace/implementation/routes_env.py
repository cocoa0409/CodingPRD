"""Environmental permit endpoints: permits, readings, breach remediation (PRD 3.7)."""
from flask import Blueprint, request

import calc
import domain
import envelope
import serialize
import store
from authz import ALL_ROLES, authenticate, authorize, check_sod
from errors import err
from validate import paginate_params, parse_body, validate, validate_no_fields

bp = Blueprint("env", __name__)

PERMIT_TYPES = ["AIR_EMISSIONS", "SAND_RECLAMATION", "DUST_CONTROL"]
READING_SOURCES = ["MELT_FURNACE", "SHAKEOUT_LINE", "SAND_PLANT", "SEASONING_OVEN"]


@bp.route("/foundry/environmental-permits", methods=["POST"])
def create_permit():
    _uid, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    vals = validate(
        parse_body(),
        [
            {"name": "permit_type", "kind": "enum", "values": PERMIT_TYPES},
            {"name": "limit_value", "kind": "number", "gt": 0},
            {"name": "measurement_unit", "kind": "string", "nonempty": True},
            {"name": "compliance_period", "kind": "enum", "values": ["MONTHLY"]},
        ],
    )
    ent = store.make_entity()
    ent.update(
        {
            "permit_type": vals["permit_type"],
            "limit_value": vals["limit_value"],
            "measurement_unit": vals["measurement_unit"],
            "compliance_period": vals["compliance_period"],
            "status": "ACTIVE",
            "over_limit_reading_count_current_period": 0,
            "last_breach_reading_recorded_by": None,
        }
    )
    store.db["permits"][ent["id"]] = ent
    return envelope.success(serialize.permit(ent), status=201)


@bp.route("/foundry/environmental-permits", methods=["GET"])
def list_permits():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = paginate_params()
    items = list(store.db["permits"].values())
    ptype = request.args.get("permit_type")
    status = request.args.get("status")
    if ptype is not None:
        items = [p for p in items if p["permit_type"] == ptype]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return envelope.list_payload(items, serialize.permit, limit, offset)


@bp.route("/foundry/environmental-permits/<pid>", methods=["GET"])
def get_permit(pid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    p = domain.get_or_404("permits", pid)
    return envelope.success(serialize.permit(p))


@bp.route("/foundry/environmental-permits/<pid>/readings", methods=["POST"])
def create_reading(pid):
    uid, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    vals = validate(
        parse_body(),
        [
            {"name": "reading_value", "kind": "number", "gt": 0},
            {"name": "source", "kind": "enum", "values": READING_SOURCES},
        ],
    )
    permit = domain.get_or_404("permits", pid)
    if permit["permit_type"] == "SAND_RECLAMATION":
        raise err(
            "ERR_INVALID_REQUEST",
            "SAND_RECLAMATION permits are rate-driven and do not accept readings",
        )
    reading = store.make_leaf()
    reading.update(
        {
            "permit_id": permit["id"],
            "reading_value": vals["reading_value"],
            "source": vals["source"],
            "recorded_by": uid,
        }
    )
    store.db["readings"][reading["id"]] = reading

    limit = calc.D(permit["limit_value"])
    value = calc.D(vals["reading_value"])
    hold_melts = permit["permit_type"] == "AIR_EMISSIONS"
    if value >= limit * calc.BREACH_MULTIPLIER:
        # Immediate breach, bypassing the counting path (from ACTIVE or WARNING).
        if permit["status"] in ("ACTIVE", "WARNING"):
            domain.breach_permit(permit, uid, hold_melts=hold_melts)
    elif value >= limit:
        permit["over_limit_reading_count_current_period"] += 1
        if permit["status"] == "ACTIVE":
            permit["status"] = "WARNING"
            store.touch(permit)
        elif (
            permit["status"] == "WARNING"
            and permit["over_limit_reading_count_current_period"] >= 2
        ):
            domain.breach_permit(permit, uid, hold_melts=hold_melts)
    return envelope.success(serialize.emissions_reading(reading), status=201)


@bp.route("/foundry/environmental-permits/<pid>/readings", methods=["GET"])
def list_readings(pid):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    domain.get_or_404("permits", pid)
    limit, offset = paginate_params()
    items = [r for r in store.db["readings"].values() if r["permit_id"] == pid]
    return envelope.list_payload(items, serialize.emissions_reading, limit, offset)


@bp.route("/foundry/environmental-permits/<pid>/acknowledge-breach", methods=["POST"])
def acknowledge_breach(pid):
    uid, role = authenticate()
    authorize(role, ["FoundryManager"])
    p = domain.try_get("permits", pid)
    if p is not None:
        check_sod(uid, p["last_breach_reading_recorded_by"])
    validate_no_fields()
    if p is None:
        raise err("ERR_RESOURCE_NOT_FOUND", f"permit not found: {pid}")
    if p["status"] != "BREACH":
        raise err("ERR_INVALID_STATE_TRANSITION", "permit is not in BREACH")
    p["status"] = "REMEDIATION"
    store.touch(p)
    return envelope.success(serialize.permit(p))


@bp.route("/foundry/environmental-permits/<pid>/certify-remediation", methods=["POST"])
def certify_remediation(pid):
    uid, role = authenticate()
    authorize(role, ["EnvironmentalOfficer"])
    p = domain.try_get("permits", pid)
    if p is not None:
        check_sod(uid, p["last_breach_reading_recorded_by"])
    validate_no_fields()
    if p is None:
        raise err("ERR_RESOURCE_NOT_FOUND", f"permit not found: {pid}")
    if p["status"] != "REMEDIATION":
        raise err("ERR_INVALID_STATE_TRANSITION", "permit is not in REMEDIATION")
    p["status"] = "ACTIVE"
    p["over_limit_reading_count_current_period"] = 0
    domain.resume_cascade()
    store.touch(p)
    return envelope.success(serialize.permit(p))
