from flask import Blueprint

from common import (
    API_PREFIX, db, new_entity, touch, serialize, object_response, paginate,
    sorted_rows, filter_equals, authenticate, json_body, get_car, get_resource,
    check_contract_party, fail, req_id, req_string, req_period_month, req_date,
    clock_iso, require_contract_operational, require_car_not_decommissioned,
    require_car_not_red_tagged, visits_of_car, contract_of_car,
    ALL_ROLES, ROLE_ADMIN, ROLE_CONTRACTOR, ROLE_MANAGER, MAX_REWORK_COUNT,
)
from calc import task_compliance

bp = Blueprint("visits", __name__)


def _visit_context(visit_id):
    visit = get_resource(db.visits, visit_id)
    car = db.cars.get(visit["car_id"])
    contract = contract_of_car(car) if car is not None else None
    return visit, car, contract


@bp.route(API_PREFIX + "/visits", methods=["POST"])
def create_visit():
    user_id, role = authenticate([ROLE_ADMIN, ROLE_CONTRACTOR])
    body = json_body()
    car_id = req_id(body, "car_id")
    car = get_car(car_id)
    contract = contract_of_car(car)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    period_month = req_period_month(body)
    scheduled_date = req_date(body, "scheduled_date")
    if body["scheduled_date"][0:7] != period_month:
        fail("ERR_VALIDATION", "scheduled_date must fall inside period_month.")

    require_contract_operational(contract)
    require_car_not_decommissioned(car)
    require_car_not_red_tagged(car)

    for existing in visits_of_car(car_id):
        if existing["period_month"] == period_month and existing["status"] != "REJECTED":
            fail("ERR_VISIT_MONTH_DUPLICATE")

    visit = new_entity({
        "car_id": car_id,
        "period_month": period_month,
        "scheduled_date": body["scheduled_date"],
        "status": "SCHEDULED",
        "task_items": [],
        "completed_task_codes": [],
        "missing_task_codes": [],
        "performed_at": None,
        "performed_by_user_id": None,
        "verified_at": None,
        "verified_by_user_id": None,
        "dispute_reason": None,
        "rework_count": 0,
    })
    db.visits[visit["id"]] = visit
    return object_response(serialize(visit), 201)


@bp.route(API_PREFIX + "/visits/<visit_id>", methods=["GET"])
def read_visit(visit_id):
    authenticate(ALL_ROLES)
    visit = get_resource(db.visits, visit_id)
    return object_response(serialize(visit))


@bp.route(API_PREFIX + "/visits", methods=["GET"])
def list_visits():
    authenticate(ALL_ROLES)
    rows = sorted_rows(db.visits)
    rows = filter_equals(rows, "car_id")
    rows = filter_equals(rows, "status")
    rows = filter_equals(rows, "period_month")
    return paginate(rows)


def _parse_task_items(body):
    if "task_items" not in body or body["task_items"] is None:
        fail("ERR_VALIDATION", "Field 'task_items' is required.")
    raw = body["task_items"]
    if not isinstance(raw, list):
        fail("ERR_VALIDATION", "Field 'task_items' must be an array.")
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_VALIDATION", "Each task item must be an object.")
        code = entry.get("task_code")
        if not isinstance(code, str) or code == "":
            fail("ERR_VALIDATION", "Each task item requires a string 'task_code'.")
        completed = entry.get("completed")
        if not isinstance(completed, bool):
            fail("ERR_VALIDATION", "Each task item requires a boolean 'completed'.")
        note = entry.get("note")
        if note is not None and not isinstance(note, str):
            fail("ERR_VALIDATION", "Task item 'note' must be a string.")
        items.append({"task_code": code, "completed": completed, "note": note})
    return items


@bp.route(API_PREFIX + "/visits/<visit_id>/perform", methods=["POST"])
def perform_visit(visit_id):
    user_id, role = authenticate([ROLE_CONTRACTOR])
    visit, car, contract = _visit_context(visit_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    items = _parse_task_items(body)

    if visit["status"] not in ("SCHEDULED", "DISPUTED"):
        fail("ERR_INVALID_STATE_TRANSITION")
    require_contract_operational(contract)
    require_car_not_decommissioned(car)

    completed, missing = task_compliance(contract, items)
    visit["task_items"] = items
    visit["completed_task_codes"] = completed
    visit["missing_task_codes"] = missing
    visit["status"] = "PERFORMED"
    visit["performed_at"] = clock_iso()
    visit["performed_by_user_id"] = user_id
    touch(visit)
    return object_response(serialize(visit))


@bp.route(API_PREFIX + "/visits/<visit_id>/verify", methods=["POST"])
def verify_visit(visit_id):
    user_id, role = authenticate([ROLE_MANAGER])
    visit, car, contract = _visit_context(visit_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)

    if visit["status"] != "PERFORMED":
        fail("ERR_INVALID_STATE_TRANSITION")
    require_contract_operational(contract)
    if user_id == visit.get("performed_by_user_id"):
        fail("ERR_SEGREGATION_OF_DUTIES")
    if visit["missing_task_codes"]:
        fail("ERR_TASK_LIST_INCOMPLETE")

    visit["status"] = "VERIFIED"
    visit["verified_at"] = clock_iso()
    visit["verified_by_user_id"] = user_id
    touch(visit)
    return object_response(serialize(visit))


@bp.route(API_PREFIX + "/visits/<visit_id>/dispute", methods=["POST"])
def dispute_visit(visit_id):
    user_id, role = authenticate([ROLE_MANAGER])
    visit, car, contract = _visit_context(visit_id)
    if contract is not None:
        check_contract_party(contract, user_id, role)
    body = json_body()
    reason = req_string(body, "dispute_reason")

    if visit["status"] != "PERFORMED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if visit["rework_count"] >= MAX_REWORK_COUNT:
        fail("ERR_REWORK_LIMIT_EXCEEDED")

    visit["status"] = "DISPUTED"
    visit["dispute_reason"] = reason
    visit["rework_count"] = visit["rework_count"] + 1
    touch(visit)
    return object_response(serialize(visit))
