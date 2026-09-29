from flask import Blueprint

import calc
import db
import middleware as mw
import response
from errors import ApiError
from routes.institutions import find_institution

bp = Blueprint("plans", __name__)

PLAN_ACTIONS = ("SUBMIT_FOR_REVIEW", "APPROVE", "REJECT", "ACTIVATE",
                "DEACTIVATE", "REARM")
WINDOW_STATUSES = ("UNDER_REVIEW", "APPROVED", "ACTIVATED", "DEACTIVATED")
READ_ROLES = ("SystemAdmin", "FundingDeskOfficer", "ComplianceReviewer",
              "TreasuryController", "Examiner")


def find_plan(plan_id):
    record = db.contingency_plans.get(plan_id)
    if record is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return record


def _overlaps(institution_id, start, end, statuses, exclude_id=None):
    for plan in db.contingency_plans.values():
        if plan["institution_id"] != institution_id:
            continue
        if plan["id"] == exclude_id:
            continue
        if plan["status"] not in statuses:
            continue
        if plan["effective_from"] <= end and start <= plan["effective_to"]:
            return True
    return False


@bp.post("/institutions/<institution_id>/contingency-plans")
def create_plan(institution_id):
    user_id, _role = mw.auth("SystemAdmin", "TreasuryController")
    find_institution(institution_id)
    data = mw.body()
    label = mw.req_str(data, "plan_version_label")
    start = mw.req_date(data, "effective_from")
    end = mw.req_date(data, "effective_to")
    if start >= end:
        raise mw.bad("effective_from must be strictly before effective_to.")
    triggers = [mw.req_int(data, "stage_%d_trigger_bps" % n, minimum=0)
                for n in (1, 2, 3)]
    actions = [mw.req_str(data, "stage_%d_action_code" % n) for n in (1, 2, 3)]

    if _overlaps(institution_id, start, end, WINDOW_STATUSES):
        raise ApiError("ERR_PLAN_WINDOW_OVERLAP")
    if (not triggers[0] < triggers[1] < triggers[2]) or any(t > 10000 for t in triggers):
        raise ApiError("ERR_THRESHOLD_ORDER_INVALID")

    record = {
        "institution_id": institution_id,
        "plan_version_label": label,
        "effective_from": start,
        "effective_to": end,
        "stage_1_trigger_bps": triggers[0],
        "stage_2_trigger_bps": triggers[1],
        "stage_3_trigger_bps": triggers[2],
        "stage_1_action_code": actions[0],
        "stage_2_action_code": actions[1],
        "stage_3_action_code": actions[2],
        "status": "DRAFT",
        "activation_stage": "NONE",
        "required_buffer_cents": 0,
        "buffer_shortfall_cents": 0,
        "prepared_by_user_id": user_id,
        "approved_by_user_id": None,
    }
    db.stamp_new(record)
    db.contingency_plans[record["id"]] = record
    return response.created(db.public(record))


@bp.get("/institutions/<institution_id>/contingency-plans")
def list_plans(institution_id):
    mw.auth(*READ_ROLES)
    find_institution(institution_id)
    limit, offset = mw.page()
    rows = [r for r in db.contingency_plans.values()
            if r["institution_id"] == institution_id]
    status = mw.q("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["effective_from"], r["created_at"], r["_seq"]))
    return response.listing(db.public_list(rows), limit, offset)


@bp.get("/contingency-plans/<plan_id>")
def read_plan(plan_id):
    mw.auth(*READ_ROLES)
    return response.ok(db.public(find_plan(plan_id)))


PLAN_TRANSITIONS = {
    "SUBMIT_FOR_REVIEW": ("DRAFT", "UNDER_REVIEW"),
    "APPROVE": ("UNDER_REVIEW", "APPROVED"),
    "REJECT": ("UNDER_REVIEW", "REJECTED"),
    "ACTIVATE": ("APPROVED", "ACTIVATED"),
    "DEACTIVATE": ("ACTIVATED", "DEACTIVATED"),
    "REARM": ("DEACTIVATED", "APPROVED"),
}


@bp.post("/contingency-plans/<plan_id>/lifecycle-actions")
def plan_lifecycle_actions(plan_id):
    user_id, _role = mw.auth("SystemAdmin", "TreasuryController", "ComplianceReviewer")
    plan = find_plan(plan_id)
    data = mw.body()
    action = mw.req_enum(data, "action", PLAN_ACTIONS)
    mw.opt_str(data, "note")

    origin, target = PLAN_TRANSITIONS[action]
    if plan["status"] != origin:
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if action in ("APPROVE", "REJECT") and user_id == plan["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if action == "APPROVE" and _overlaps(plan["institution_id"],
                                        plan["effective_from"], plan["effective_to"],
                                        ("APPROVED", "ACTIVATED"),
                                        exclude_id=plan["id"]):
        raise ApiError("ERR_PLAN_WINDOW_OVERLAP")
    if action == "DEACTIVATE" and plan["buffer_shortfall_cents"] > 0:
        raise ApiError("ERR_BUFFER_SHORTFALL_UNFUNDED")

    plan["status"] = target
    if action == "APPROVE":
        plan["approved_by_user_id"] = user_id
    elif action == "ACTIVATE":
        institution = db.institutions.get(plan["institution_id"])
        calc.activate_plan_figures(plan, institution)
    elif action == "DEACTIVATE":
        plan["activation_stage"] = "NONE"
        plan["required_buffer_cents"] = 0
        plan["buffer_shortfall_cents"] = 0
    db.bump(plan)
    return response.ok(db.public(plan))
