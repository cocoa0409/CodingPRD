"""Plans of action: submission, revision and review (PRD 3.7)."""

from datetime import timedelta

from flask import Blueprint, request

import clock
import constants as C
import db
import guards
import middleware as mw
import response
import serializers as ser
import validators as v
from errors import ApiError
from services import notify

bp = Blueprint("plans", __name__)

POA_ERR = "ERR_POA_INCOMPLETE"


def _check_content(root_cause, corrective, preventive):
    """PRD 3.7 content thresholds — rejection step 8, ERR_POA_INCOMPLETE."""
    trimmed = root_cause.strip()
    if len(trimmed) < 40 or len(trimmed) > 2000:
        v.bad("'root_cause' must be 40 to 2000 characters after trimming.", POA_ERR)
    for key, value in (("corrective_measures", corrective),
                       ("preventive_measures", preventive)):
        if len(value) < 1 or len(value) > 10:
            v.bad("'%s' must hold 1 to 10 elements." % key, POA_ERR)
        for element in value:
            if not isinstance(element, str) or len(element) < 10 or len(element) > 500:
                v.bad("every element of '%s' must be 10 to 500 characters." % key, POA_ERR)


@bp.post("/plans-of-action")
@mw.require(C.ROLE_SELLER)
def submit_plan():
    data = v.body()
    action = guards.body_fk(db.ENFORCEMENT_ACTIONS, data.get("enforcement_action_id"),
                            "ERR_ACTION_NOT_FOUND")
    if action is not None:
        mw.ensure_owner(action["seller_id"])

    v.req_str(data, "enforcement_action_id", 1, None)
    root_cause = v.req_str(data, "root_cause")
    corrective = v.req_str_array(data, "corrective_measures", 0, 10 ** 6, 0, 10 ** 6)
    preventive = v.req_str_array(data, "preventive_measures", 0, 10 ** 6, 0, 10 ** 6)
    expected_version = v.req_int(data, "expected_enforcement_action_version", minimum=0)
    if action is None:
        raise ApiError("ERR_ACTION_NOT_FOUND")

    _check_content(root_cause, corrective, preventive)

    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)

    if action["state"] not in ("ISSUED", "ACKNOWLEDGED"):
        raise ApiError("ERR_INVALID_STATE")
    rule = _rule_of(action)
    if rule is None or not rule["requires_poa"]:
        raise ApiError("ERR_INVALID_STATE")

    siblings = db.plans_of_action_for(action["id"])
    for plan in siblings:
        if plan["state"] in ("ACCEPTED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE")

    if expected_version != action["version"]:
        raise ApiError("ERR_STALE_ACTION_VERSION")

    for plan in siblings:
        if plan["state"] == "SUBMITTED":
            raise ApiError("ERR_POA_ALREADY_OPEN")

    superseded = None
    for plan in siblings:
        if plan["state"] == "RETURNED_FOR_REVISION":
            superseded = plan
    revision_count = 0
    if superseded is not None:
        db.set_field(superseded, "state", "SUPERSEDED")
        revision_count = superseded["revision_count"] + 1

    row = db.new_row(
        "plan",
        enforcement_action_id=action["id"],
        root_cause=root_cause,
        corrective_measures=corrective,
        preventive_measures=preventive,
        state="SUBMITTED",
        revision_count=revision_count,
        submitted_at=clock.now(),
        deadline_at=action["issued_at"] + timedelta(days=C.POA_DEADLINE_DAYS),
        reviewed_by_user_id=None,
        review_notes=None,
    )
    db.PLANS_OF_ACTION[row["id"]] = row
    db.mark_dirty(action)
    return response.one(row, ser.plan, 201)


def _rule_of(action):
    violation = db.VIOLATIONS.get(action["violation_id"])
    if violation is None:
        return None
    return db.POLICY_RULES.get(violation["policy_rule_id"])


@bp.get("/plans-of-action")
@mw.require(C.ROLE_SELLER, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_plans():
    limit, offset = v.pagination()
    rows = sorted(
        db.PLANS_OF_ACTION.values(),
        key=lambda r: (-r["submitted_at"].timestamp(), r["created_at"], r["_seq"]),
    )
    if mw.is_seller():
        owned = {
            a["id"] for a in db.ENFORCEMENT_ACTIONS.values()
            if a["seller_id"] == mw.actor()
        }
        rows = [r for r in rows if r["enforcement_action_id"] in owned]
    for field in ("enforcement_action_id", "state"):
        if field in request.args:
            wanted = request.args.get(field)
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.plan, limit, offset, total)


@bp.get("/plans-of-action/<plan_id>")
@mw.require(C.ROLE_SELLER, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def read_plan(plan_id):
    plan = guards.plan(plan_id)
    action = db.ENFORCEMENT_ACTIONS[plan["enforcement_action_id"]]
    mw.ensure_owner(action["seller_id"])
    return response.one(plan, ser.plan, 200)


@bp.post("/plans-of-action/<plan_id>/review")
@mw.require(C.ROLE_OFFICER)
def review_plan(plan_id):
    plan = guards.plan(plan_id)
    action = db.ENFORCEMENT_ACTIONS[plan["enforcement_action_id"]]
    mw.ensure_distinct(action["issued_by_user_id"])

    data = v.body()
    decision = v.req_enum(data, "decision", C.POA_DECISIONS)
    review_notes = v.opt_str(data, "review_notes")

    if decision == "ACCEPT":
        _check_content(plan["root_cause"], plan["corrective_measures"],
                       plan["preventive_measures"])

    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)

    if plan["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    if decision == "RETURN" and plan["revision_count"] >= C.POA_MAX_REVISIONS:
        raise ApiError("ERR_POA_REVISION_LIMIT")

    target = {"ACCEPT": "ACCEPTED", "RETURN": "RETURNED_FOR_REVISION",
              "REJECT": "REJECTED"}[decision]
    db.set_field(plan, "state", target)
    db.set_field(plan, "reviewed_by_user_id", mw.actor())
    db.set_field(plan, "review_notes", review_notes)
    db.mark_dirty(action)

    rationale = review_notes
    if rationale is None:
        rationale = "Plan of action review decision: %s" % decision
    notify.emit(seller["id"], "POA_DECISION", "PLAN_OF_ACTION", plan["id"],
                decision_rationale=rationale)
    return response.one(plan, ser.plan, 200)
