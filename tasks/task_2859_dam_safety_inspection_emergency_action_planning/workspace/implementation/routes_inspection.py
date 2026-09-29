"""Inspections, deficiencies and remediation orders (PRD Sections 3.3 and 3.4)."""

from flask import Blueprint, request

import calc
import guards
import services
from common import (
    ApiError, INVALID, body_dict, ok, ok_list, pagination, q_enum, q_str,
    v_array, v_dt, v_enum, v_int, v_string,
)
from derive import (
    dam_hazard_class, dam_latest_accepted_inspection, dam_open_deficiency_count,
    engineer_inspections, paginate, serialize_deficiency, serialize_inspection,
    serialize_order,
)
from store import db, insert, insertion_order, touch

bp = Blueprint("inspections", __name__)

OPEN_WINDOW_STATUSES = ("SCHEDULED", "SUBMITTED", "RETURNED")


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

@bp.route("/inspections", methods=["POST"])
def create_inspection():
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    dam_id = v_string(body, "dam_id", min_len=1)
    engineer_id = v_string(body, "engineer_id", min_len=1)
    inspection_type = v_enum(body, "inspection_type", calc.INSPECTION_TYPES)
    window_start = v_dt(body, "window_start")
    window_end = v_dt(body, "window_end")
    if window_end <= window_start:
        raise ApiError(INVALID, "window_end must be strictly after window_start")
    dam = guards.get_dam(dam_id)
    engineer = guards.get_engineer(engineer_id)
    guards.check_dam_operable(dam)
    guards.check_license_active(engineer)
    guards.check_certified_for(engineer, dam_hazard_class(dam))
    guards.check_dam_classified(dam)
    # Rung 30: the engineer's calendar, with a two-hour travel buffer either side.
    for existing in engineer_inspections(engineer["id"]):
        if existing["status"] not in OPEN_WINDOW_STATUSES:
            continue
        if calc.windows_conflict(window_start, window_end,
                                 existing["window_start"], existing["window_end"]):
            raise ApiError("ERR_ENGINEER_WINDOW_CONFLICT",
                           "engineer already holds an overlapping inspection window")
    inspection = insert(db.inspections, {
        "dam_id": dam["id"],
        "engineer_id": engineer["id"],
        "inspection_type": inspection_type,
        "window_start": window_start,
        "window_end": window_end,
        "performed_at": None,
        "condition_rating": None,
        "narrative": None,
        "status": "SCHEDULED",
        "deficiency_count": 0,
        "return_count": 0,
        "accepted_by_user_id": None,
        "accepted_at": None,
    })
    return ok(serialize_inspection(inspection), 201)


@bp.route("/inspections/<inspection_id>", methods=["GET"])
def read_inspection(inspection_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    inspection = guards.get_inspection(inspection_id)
    guards.check_identity(user_id, role)
    return ok(serialize_inspection(inspection))


@bp.route("/inspections", methods=["GET"])
def list_inspections():
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    limit, offset = pagination()
    dam_id = q_str("dam_id")
    engineer_id = q_str("engineer_id")
    status = q_enum("status", calc.INSPECTION_STATUSES)
    inspection_type = q_enum("inspection_type", calc.INSPECTION_TYPES)
    guards.check_identity(user_id, role)
    rows = list(db.inspections.values())
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if engineer_id is not None:
        rows = [r for r in rows if r["engineer_id"] == engineer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if inspection_type is not None:
        rows = [r for r in rows if r["inspection_type"] == inspection_type]
    data, total = paginate(rows, limit, offset, serialize_inspection)
    return ok_list(data, limit, offset, total)


@bp.route("/inspections/<inspection_id>/submit", methods=["POST"])
def submit_inspection(inspection_id):
    user_id, role = guards.authenticate(request, ("Engineer",))
    body = body_dict()
    performed_at = v_dt(body, "performed_at")
    condition_rating = v_enum(body, "condition_rating", calc.CONDITION_RATINGS)
    narrative = v_string(body, "narrative", min_len=1)
    raw_deficiencies = v_array(body, "deficiencies", required=False, default=[])
    parsed_deficiencies = []
    for index, item in enumerate(raw_deficiencies):
        if not isinstance(item, dict):
            raise ApiError(INVALID, "deficiencies[%d] must be an object" % index)
        parsed_deficiencies.append({
            "category": v_enum(item, "category", calc.ENGINEER_DEFICIENCY_CATEGORIES),
            "severity": v_enum(item, "severity", calc.SEVERITIES),
            "description": v_string(item, "description", min_len=1),
        })
    inspection = guards.get_inspection(inspection_id)
    engineer = guards.check_identity(user_id, role)
    guards.check_assigned_engineer(user_id, inspection["engineer_id"])
    guards.check_inspection_state(inspection, ("SCHEDULED", "RETURNED"))
    guards.check_license_active(engineer)
    dam = guards.get_dam(inspection["dam_id"])
    guards.check_certified_for(engineer, dam_hazard_class(dam))
    # Rung 26: performed_at must land inside the scheduled window.
    if performed_at < inspection["window_start"] or performed_at >= inspection["window_end"]:
        raise ApiError("ERR_OUTSIDE_INSPECTION_WINDOW",
                       "performed_at must be at or after window_start and strictly before window_end")
    # Rung 27: performed_at may not be in the future of the logical clock.
    if performed_at > db.clock:
        raise ApiError("ERR_PERFORMED_AT_IN_FUTURE", "performed_at is later than the current logical clock")

    before_open = dam_open_deficiency_count(dam["id"])

    inspection["performed_at"] = performed_at
    inspection["condition_rating"] = condition_rating
    inspection["narrative"] = narrative
    inspection["status"] = "SUBMITTED"
    inspection["deficiency_count"] = len(parsed_deficiencies)

    # A resubmission discards the still-open findings of the previous submission;
    # findings already ordered against are left untouched.
    for existing in list(db.deficiencies.values()):
        if existing["inspection_id"] == inspection["id"] and existing["status"] == "OPEN":
            del db.deficiencies[existing["id"]]
    for entry in parsed_deficiencies:
        insert(db.deficiencies, {
            "dam_id": dam["id"],
            "inspection_id": inspection["id"],
            "source": "INSPECTION",
            "category": entry["category"],
            "severity": entry["severity"],
            "description": entry["description"],
            "status": "OPEN",
            "remediation_due_at": None,
            "closed_at": None,
        })
    touch(inspection)
    if dam_open_deficiency_count(dam["id"]) != before_open:
        touch(dam)
    return ok(serialize_inspection(inspection))


@bp.route("/inspections/<inspection_id>/accept", methods=["POST"])
def accept_inspection(inspection_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer"))
    inspection = guards.get_inspection(inspection_id)
    engineer = guards.check_identity(user_id, role)
    guards.check_inspection_state(inspection, ("SUBMITTED",))
    if engineer is not None:
        guards.check_license_active(engineer)
    # Rung 37: segregation of duties.
    if user_id == inspection["engineer_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the engineer of record may not accept their own inspection")
    dam = guards.get_dam(inspection["dam_id"])
    inspection["status"] = "ACCEPTED"
    inspection["accepted_by_user_id"] = user_id
    inspection["accepted_at"] = db.clock
    touch(inspection)
    touch(dam)
    return ok(serialize_inspection(inspection))


@bp.route("/inspections/<inspection_id>/return", methods=["POST"])
def return_inspection(inspection_id):
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    v_string(body, "reason", min_len=1)
    inspection = guards.get_inspection(inspection_id)
    guards.check_inspection_state(inspection, ("SUBMITTED",))
    inspection["status"] = "RETURNED"
    inspection["return_count"] = inspection["return_count"] + 1
    touch(inspection)
    return ok(serialize_inspection(inspection))


# ---------------------------------------------------------------------------
# Deficiencies
# ---------------------------------------------------------------------------

@bp.route("/deficiencies/<deficiency_id>", methods=["GET"])
def read_deficiency(deficiency_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    deficiency = guards.get_deficiency(deficiency_id)
    guards.check_identity(user_id, role)
    return ok(serialize_deficiency(deficiency))


@bp.route("/deficiencies", methods=["GET"])
def list_deficiencies():
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    limit, offset = pagination()
    dam_id = q_str("dam_id")
    inspection_id = q_str("inspection_id")
    status = q_enum("status", calc.DEFICIENCY_STATUSES)
    severity = q_enum("severity", calc.SEVERITIES)
    source = q_enum("source", calc.DEFICIENCY_SOURCES)
    category = q_enum("category", calc.DEFICIENCY_CATEGORIES)
    guards.check_identity(user_id, role)
    rows = list(db.deficiencies.values())
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if inspection_id is not None:
        rows = [r for r in rows if r["inspection_id"] == inspection_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]
    data, total = paginate(rows, limit, offset, serialize_deficiency)
    return ok_list(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Remediation orders
# ---------------------------------------------------------------------------

@bp.route("/deficiencies/<deficiency_id>/remediation-orders", methods=["POST"])
def issue_remediation_order(deficiency_id):
    guards.authenticate(request, ("ProgramAdmin",))
    body = body_dict()
    order_type = v_enum(body, "order_type", calc.ORDER_TYPES)
    requested_response_days = v_int(body, "requested_response_days", minimum=1)
    deficiency = guards.get_deficiency(deficiency_id)
    guards.check_deficiency_state(deficiency, ("OPEN", "ESCALATED"))
    dam = guards.get_dam(deficiency["dam_id"])
    guards.check_dam_operable(dam)

    hazard_class = dam_hazard_class(dam)
    effective_days = calc.effective_response_days(
        deficiency["severity"], hazard_class, requested_response_days, order_type)
    issued_at = db.clock
    deadline = calc.compliance_deadline(issued_at, effective_days)
    order = insert(db.orders, {
        "deficiency_id": deficiency["id"],
        "dam_id": dam["id"],
        "owner_id": dam["owner_id"],
        "order_type": order_type,
        "requested_response_days": requested_response_days,
        "effective_response_days": effective_days,
        "issued_at": issued_at,
        "compliance_deadline_at": deadline,
        "daily_penalty_rate_cents": calc.daily_penalty_rate_cents(deficiency["severity"], hazard_class),
        "status": "ISSUED",
        "response_filed_at": None,
        "corrective_action_summary": None,
        "completed_at": None,
        "verified_by_user_id": None,
        "defaulted_at": None,
        "assessed_penalty_cents": 0,
    })
    deficiency["status"] = "ORDERED"
    deficiency["remediation_due_at"] = deadline
    touch(deficiency)
    return ok(serialize_order(order), 201)


@bp.route("/remediation-orders/<order_id>", methods=["GET"])
def read_order(order_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    order = guards.get_order(order_id)
    guards.check_identity(user_id, role)
    return ok(serialize_order(order))


@bp.route("/remediation-orders", methods=["GET"])
def list_orders():
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "Engineer", "DamOwner"))
    limit, offset = pagination()
    deficiency_id = q_str("deficiency_id")
    dam_id = q_str("dam_id")
    owner_id = q_str("owner_id")
    status = q_enum("status", calc.ORDER_STATUSES)
    order_type = q_enum("order_type", calc.ORDER_TYPES)
    guards.check_identity(user_id, role)
    rows = list(db.orders.values())
    if deficiency_id is not None:
        rows = [r for r in rows if r["deficiency_id"] == deficiency_id]
    if dam_id is not None:
        rows = [r for r in rows if r["dam_id"] == dam_id]
    if owner_id is not None:
        rows = [r for r in rows if r["owner_id"] == owner_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if order_type is not None:
        rows = [r for r in rows if r["order_type"] == order_type]
    data, total = paginate(rows, limit, offset, serialize_order)
    return ok_list(data, limit, offset, total)


@bp.route("/remediation-orders/<order_id>/penalty-preview", methods=["GET"])
def penalty_preview(order_id):
    user_id, role = guards.authenticate(request, ("ProgramAdmin", "DamOwner"))
    order = guards.get_order(order_id)
    guards.check_identity(user_id, role)
    guards.check_order_state(order, ("ISSUED", "RESPONSE_FILED"))
    days = calc.overdue_days(db.clock, order["compliance_deadline_at"])
    provisional = calc.provisional_penalty_cents(order["daily_penalty_rate_cents"], days)
    return ok({
        "order_id": order["id"],
        "overdue_days": days,
        "daily_penalty_rate_cents": order["daily_penalty_rate_cents"],
        "provisional_penalty_cents": provisional,
        "response_filed": order["response_filed_at"] is not None,
    })


@bp.route("/remediation-orders/<order_id>/response", methods=["POST"])
def file_order_response(order_id):
    user_id, role = guards.authenticate(request, ("DamOwner",))
    body = body_dict()
    corrective_action_summary = v_string(body, "corrective_action_summary", min_len=1)
    completed_at = v_dt(body, "completed_at")
    order = guards.get_order(order_id)
    guards.check_identity(user_id, role)
    guards.check_resource_owner(user_id, role, order["owner_id"])
    guards.check_order_state(order, ("ISSUED",))
    order["status"] = "RESPONSE_FILED"
    if order["response_filed_at"] is None:
        order["response_filed_at"] = db.clock
    order["corrective_action_summary"] = corrective_action_summary
    order["completed_at"] = completed_at
    touch(order)
    deficiency = db.deficiencies.get(order["deficiency_id"])
    if deficiency is not None and deficiency["status"] == "ORDERED":
        deficiency["status"] = "REMEDIATION_SUBMITTED"
        touch(deficiency)
    return ok(serialize_order(order))


@bp.route("/remediation-orders/<order_id>/verify", methods=["POST"])
def verify_order(order_id):
    user_id, role = guards.authenticate(request, ("Engineer",))
    body = body_dict()
    outcome = v_enum(body, "outcome", ("SATISFIED", "REJECTED"))
    v_string(body, "notes", min_len=1)
    order = guards.get_order(order_id)
    engineer = guards.check_identity(user_id, role)
    guards.check_order_state(order, ("RESPONSE_FILED",))
    guards.check_license_active(engineer)
    deficiency = db.deficiencies.get(order["deficiency_id"])
    dam = db.dams.get(order["dam_id"])
    order["verified_by_user_id"] = user_id
    if outcome == "SATISFIED":
        order["status"] = "SATISFIED"
        touch(order)
        if deficiency is not None:
            deficiency["status"] = "CLOSED_VERIFIED"
            deficiency["closed_at"] = db.clock
            touch(deficiency)
        if dam is not None:
            touch(dam)
            services.maybe_release_enforcement(dam)
    else:
        order["status"] = "ISSUED"
        touch(order)
        if deficiency is not None:
            deficiency["status"] = "ORDERED"
            touch(deficiency)
    return ok(serialize_order(order))
