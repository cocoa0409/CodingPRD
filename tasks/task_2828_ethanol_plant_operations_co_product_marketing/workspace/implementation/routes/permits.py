"""Permit conditions, monitoring readings and deviation resolution."""
import guards
import serialize
from envelope import ok, ok_list
from errors import fail
from routes import bp
from shape import enum_param, page, pagination, require_auth, take
from store import db, new_row, touch
from util import D, rhu

PERMIT_TYPES = ["AIR_EMISSIONS", "WATER_DISCHARGE"]
SEVERITIES = ["MINOR", "MAJOR", "CRITICAL"]
CONDITION_STATUSES = ("COMPLIANT", "EXCEEDANCE")

CONDITION_SPEC = {
    "condition_code": {"type": "string", "required": True},
    "permit_type": {"type": "enum", "required": True, "values": PERMIT_TYPES},
    "parameter_name": {"type": "string", "required": True},
    "limit_value": {"type": "dec", "required": True, "gt": 0, "places": 3},
    "unit": {"type": "string", "required": True},
    "averaging_period_hours": {"type": "int", "required": True, "gt": 0},
    "severity": {"type": "enum", "required": True, "values": SEVERITIES},
}
READING_SPEC = {
    "value": {"type": "dec", "required": True, "ge": 0, "places": 3},
    "measured_at": {"type": "instant", "required": True},
    "sample_reference": {"type": "string"},
}
RESOLVE_SPEC = {"resolution_note": {"type": "string", "required": True}}


@bp.route("/permit-conditions", methods=["POST"])
def create_condition():
    require_auth(["ComplianceOfficer"])
    body = take(CONDITION_SPEC)
    guards.unique(db.conditions, "condition_code", body["condition_code"])
    condition = new_row({
        "condition_code": body["condition_code"],
        "permit_type": body["permit_type"],
        "parameter_name": body["parameter_name"],
        "limit_value": rhu(body["limit_value"], 3),
        "unit": body["unit"],
        "averaging_period_hours": body["averaging_period_hours"],
        "severity": body["severity"],
        "status": "COMPLIANT",
        "exceedance_count": 0,
        "last_exceedance_at": None,
        "resolution_note": None,
    })
    db.conditions[condition["id"]] = condition
    return ok(serialize.condition_out(condition), 201)


@bp.route("/permit-conditions/<condition_id>", methods=["GET"])
def get_condition(condition_id):
    require_auth(["PlantManager", "ComplianceOfficer", "ProcessOperator"])
    condition = guards.get_condition(condition_id)
    return ok(serialize.condition_out(condition))


@bp.route("/permit-conditions", methods=["GET"])
def list_conditions():
    require_auth(["PlantManager", "ComplianceOfficer", "ProcessOperator"])
    permit_type = enum_param("permit_type", PERMIT_TYPES)
    status = enum_param("status", CONDITION_STATUSES)
    severity = enum_param("severity", SEVERITIES)
    limit, offset = pagination()
    rows = list(db.conditions.values())
    if permit_type is not None:
        rows = [r for r in rows if r["permit_type"] == permit_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    rows = sorted(rows, key=lambda r: (r["condition_code"], r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.condition_out(r) for r in window],
                   limit, offset, len(rows))


@bp.route("/permit-conditions/<condition_id>/readings", methods=["POST"])
def create_permit_reading(condition_id):
    require_auth(["ProcessOperator", "ComplianceOfficer"])
    body = take(READING_SPEC)
    condition = guards.get_condition(condition_id)
    reading = new_row({
        "condition_id": condition["id"],
        "measured_at": body["measured_at"],
        "value": rhu(body["value"], 3),
        "sample_reference": body["sample_reference"],
    }, versioned=False)
    db.permit_readings[reading["id"]] = reading
    average, _count = serialize.condition_rolling(condition)
    if (condition["status"] == "COMPLIANT" and average is not None
            and D(average) > D(condition["limit_value"])):
        condition["status"] = "EXCEEDANCE"
        condition["exceedance_count"] = int(condition["exceedance_count"]) + 1
        condition["last_exceedance_at"] = db.clock
    touch(condition)
    return ok(serialize.permit_reading_out(reading), 201)


@bp.route("/permit-conditions/<condition_id>/readings", methods=["GET"])
def list_permit_readings(condition_id):
    require_auth(["PlantManager", "ComplianceOfficer", "ProcessOperator"])
    limit, offset = pagination()
    condition = guards.get_condition(condition_id)
    rows = [r for r in db.permit_readings.values()
            if r["condition_id"] == condition["id"]]
    rows = sorted(rows, key=lambda r: (r["measured_at"], r["created_at"], r["_seq"]))
    window = page(rows, limit, offset)
    return ok_list([serialize.permit_reading_out(r) for r in window],
                   limit, offset, len(rows))


@bp.route("/permit-conditions/<condition_id>/resolve-deviation", methods=["POST"])
def resolve_deviation(condition_id):
    require_auth(["ComplianceOfficer"])
    body = take(RESOLVE_SPEC)
    condition = guards.get_condition(condition_id)
    if condition["status"] != "EXCEEDANCE":
        fail("ERR_CONDITION_NOT_IN_EXCEEDANCE",
             "Condition %s is COMPLIANT and has no deviation to resolve"
             % condition["condition_code"])
    average, _count = serialize.condition_rolling(condition)
    if average is None or D(average) > D(condition["limit_value"]):
        fail("ERR_CONDITION_NOT_IN_EXCEEDANCE",
             "The rolling average is still above the permitted limit")
    condition["status"] = "COMPLIANT"
    condition["resolution_note"] = body["resolution_note"]
    touch(condition)
    return ok(serialize.condition_out(condition))
