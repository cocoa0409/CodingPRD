"""PrefunctionalChecklist endpoints."""
from flask import Blueprint

import calc
import services
from core import (
    ALL_ROLES, ROLE_CONTRACTOR, ROLE_CX_AUTHORITY, actor, authenticate, body_json,
    bump_project, clock, db, fail, new_row, ok, ok_list, paginate, public, q,
    sorted_rows, touch, v_bool, v_enum, v_string,
)
from finders import get_checklist, get_equipment

bp = Blueprint("checklists", __name__)


def _refresh_counts(checklist):
    items = checklist["items"]
    checklist["item_count"] = len(items)
    checklist["passed_item_count"] = sum(1 for i in items if i["result"] in ("PASS", "NA"))
    checklist["failed_item_count"] = sum(1 for i in items if i["result"] == "FAIL")


@bp.post("/prefunctional-checklists")
def create_checklist():
    authenticate([ROLE_CX_AUTHORITY])
    body = body_json()
    equipment_id = v_string(body, "equipment_id")
    template_code = v_string(body, "template_code")

    get_equipment(equipment_id)

    row = new_row(db.checklists, {
        "equipment_id": equipment_id,
        "template_code": template_code,
        "status": "DRAFT",
        "items": [],
        "item_count": 0,
        "passed_item_count": 0,
        "failed_item_count": 0,
        "executed_by_user_id": None,
        "verified_by_user_id": None,
        "rework_cycle_count": 0,
    })
    services.reconcile()
    return ok(public(row), 201)


@bp.get("/prefunctional-checklists")
def list_checklists():
    authenticate(ALL_ROLES)
    rows = sorted_rows(list(db.checklists.values()))
    equipment_id = q("equipment_id")
    status = q("status")
    if equipment_id is not None:
        rows = [r for r in rows if r["equipment_id"] == equipment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, limit, offset, total = paginate(rows)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.get("/prefunctional-checklists/<checklist_id>")
def read_checklist(checklist_id):
    authenticate(ALL_ROLES)
    return ok(public(get_checklist(checklist_id)))


@bp.post("/prefunctional-checklists/<checklist_id>/items")
def append_item(checklist_id):
    authenticate([ROLE_CX_AUTHORITY])
    checklist = get_checklist(checklist_id)
    body = body_json()
    item_code = v_string(body, "item_code")
    description = v_string(body, "description")
    is_safety_critical = v_bool(body, "is_safety_critical")

    if checklist["status"] not in ("DRAFT", "REWORK"):
        fail("ERR_INVALID_STATE",
             "Items may only be appended while the checklist is DRAFT or REWORK.")
    if any(i["item_code"] == item_code for i in checklist["items"]):
        fail("ERR_DUPLICATE_ITEM_CODE", "item_code '%s' is already present." % item_code)

    checklist["items"].append({
        "item_code": item_code,
        "description": description,
        "is_safety_critical": is_safety_critical,
        "result": "PENDING",
        "recorded_by_user_id": None,
        "recorded_at": None,
    })
    _refresh_counts(checklist)
    touch(checklist)
    services.reconcile()
    return ok(public(checklist), 201)


@bp.post("/prefunctional-checklists/<checklist_id>/record-item")
def record_item(checklist_id):
    authenticate([ROLE_CONTRACTOR])
    checklist = get_checklist(checklist_id)
    body = body_json()
    item_code = v_string(body, "item_code")
    result = v_enum(body, "result", calc.ITEM_RESULT_INPUTS)
    v_string(body, "note", required=False, default=None)

    item = next((i for i in checklist["items"] if i["item_code"] == item_code), None)
    if item is None:
        fail("ERR_ITEM_NOT_FOUND", "No item with item_code '%s'." % item_code)

    item["result"] = result
    item["recorded_by_user_id"] = actor()
    item["recorded_at"] = clock.now_iso()
    _refresh_counts(checklist)
    touch(checklist)
    services.reconcile()
    return ok(public(checklist))


@bp.post("/prefunctional-checklists/<checklist_id>/execute")
def execute_checklist(checklist_id):
    authenticate([ROLE_CONTRACTOR])
    checklist = get_checklist(checklist_id)
    equipment_row = db.equipment.get(checklist["equipment_id"])

    if checklist["status"] not in ("DRAFT", "REWORK"):
        fail("ERR_INVALID_STATE", "Only a DRAFT or REWORK checklist may be executed.")
    if equipment_row["install_status"] not in ("INSTALLED", "STARTED_UP"):
        fail("ERR_EQUIPMENT_NOT_READY",
             "The equipment unit must be INSTALLED or STARTED_UP.")
    if checklist["item_count"] < 1:
        fail("ERR_CHECKLIST_EMPTY", "The checklist carries no items.")
    if any(i["result"] == "PENDING" for i in checklist["items"]):
        fail("ERR_CHECKLIST_INCOMPLETE", "An item still reads PENDING.")

    checklist["status"] = "EXECUTED"
    checklist["executed_by_user_id"] = actor()
    touch(checklist)
    services.reconcile()
    return ok(public(checklist))


@bp.post("/prefunctional-checklists/<checklist_id>/verify")
def verify_checklist(checklist_id):
    authenticate([ROLE_CX_AUTHORITY])
    checklist = get_checklist(checklist_id)
    equipment_row = db.equipment.get(checklist["equipment_id"])
    project = db.projects.get(equipment_row["project_id"])

    if checklist["status"] != "EXECUTED":
        fail("ERR_INVALID_STATE", "Only an EXECUTED checklist may be verified.")
    if actor() == checklist["executed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The verifier may not be the executor.")
    if any(i["is_safety_critical"] and i["result"] == "FAIL" for i in checklist["items"]):
        fail("ERR_SAFETY_ITEM_FAILED", "A safety-critical item failed.")
    if equipment_row["blocking_issue_count"] != 0:
        fail("ERR_INVALID_STATE",
             "The equipment unit still carries blocking deficiencies.")

    checklist["status"] = "VERIFIED"
    checklist["verified_by_user_id"] = actor()
    touch(checklist)

    if equipment_row["verification_status"] == "UNVERIFIED":
        equipment_row["verification_status"] = "PREFUNCTIONAL_VERIFIED"
        touch(equipment_row)

    bump_project(project)
    services.reconcile()
    return ok(public(checklist))


@bp.post("/prefunctional-checklists/<checklist_id>/reject")
def reject_checklist(checklist_id):
    authenticate([ROLE_CX_AUTHORITY])
    checklist = get_checklist(checklist_id)
    body = body_json()
    v_string(body, "reason")

    equipment_row = db.equipment.get(checklist["equipment_id"])
    project = db.projects.get(equipment_row["project_id"])

    if checklist["status"] not in ("EXECUTED", "VERIFIED"):
        fail("ERR_INVALID_STATE", "Only an EXECUTED or VERIFIED checklist may be rejected.")

    was_verified = checklist["status"] == "VERIFIED"
    checklist["status"] = "REWORK"
    checklist["rework_cycle_count"] = checklist["rework_cycle_count"] + 1
    checklist["executed_by_user_id"] = None
    for item in checklist["items"]:
        item["result"] = "PENDING"
        item["recorded_by_user_id"] = None
        item["recorded_at"] = None
    _refresh_counts(checklist)

    if was_verified:
        checklist["verified_by_user_id"] = None
        if services.demote_equipment(equipment_row):
            services.cancel_scheduled_tests(equipment_row["id"], {"SCHEDULED"})

    touch(checklist)
    bump_project(project)
    services.reconcile()
    return ok(public(checklist))
