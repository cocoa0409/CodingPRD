"""Appeals, escalation, reinstatement and the final ban (PRD 3.8)."""

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
from services import calc, notify, posture

bp = Blueprint("appeals", __name__)


def _rule_of(action):
    violation = db.VIOLATIONS.get(action["violation_id"])
    if violation is None:
        return None
    return db.POLICY_RULES.get(violation["policy_rule_id"])


@bp.post("/appeals")
@mw.require(C.ROLE_SELLER)
def file_appeal():
    data = v.body()
    action = guards.body_fk(db.ENFORCEMENT_ACTIONS, data.get("enforcement_action_id"),
                            "ERR_ACTION_NOT_FOUND")
    plan = guards.body_fk(db.PLANS_OF_ACTION, data.get("plan_of_action_id"),
                          "ERR_POA_NOT_FOUND")
    if action is not None:
        mw.ensure_owner(action["seller_id"])

    v.req_str(data, "enforcement_action_id", 1, None)
    if v.present(data, "plan_of_action_id"):
        v.req_str(data, "plan_of_action_id", 1, None)
    grounds = v.req_str(data, "grounds", 20, 2000)
    if action is None:
        raise ApiError("ERR_ACTION_NOT_FOUND")

    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)

    existing = db.appeals_for(action["id"])
    if action["state"] not in ("ISSUED", "ACKNOWLEDGED"):
        # PRD 3.8: once an action is UPHELD or VACATED an appeal against it
        # already exists, and a fresh one is refused as a duplicate.
        if existing:
            raise ApiError("ERR_APPEAL_ALREADY_EXISTS")
        raise ApiError("ERR_ACTION_NOT_APPEALABLE_STATE")

    rule = _rule_of(action)
    if rule is not None and rule["requires_poa"]:
        accepted = [p for p in db.plans_of_action_for(action["id"])
                    if p["state"] == "ACCEPTED"]
        if not accepted:
            raise ApiError("ERR_POA_NOT_ACCEPTED")

    if clock.now() > action["appeal_deadline_at"]:
        raise ApiError("ERR_APPEAL_WINDOW_CLOSED")

    if existing:
        raise ApiError("ERR_APPEAL_ALREADY_EXISTS")

    if plan is not None and plan["enforcement_action_id"] != action["id"]:
        raise ApiError("ERR_POA_ACTION_MISMATCH")

    row = db.new_row(
        "appeal",
        enforcement_action_id=action["id"],
        plan_of_action_id=plan["id"] if plan is not None else None,
        grounds=grounds,
        state="SUBMITTED",
        decided_by_user_id=None,
        decided_at=None,
        denial_reason=None,
        rationale=None,
        escalation_deadline_at=None,
        escalation_requested_at=None,
        escalation_grounds=None,
        escalation_decided_by_user_id=None,
        reinstatement_granted=False,
    )
    db.APPEALS[row["id"]] = row
    return response.one(row, ser.appeal, 201)


@bp.get("/appeals")
@mw.require(C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_appeals():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.APPEALS)
    for field in ("enforcement_action_id", "plan_of_action_id", "state"):
        if field in request.args:
            wanted = request.args.get(field)
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.appeal, limit, offset, total)


@bp.get("/appeals/<appeal_id>")
@mw.require(C.ROLE_SELLER, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def read_appeal(appeal_id):
    appeal = guards.appeal(appeal_id)
    action = db.ENFORCEMENT_ACTIONS[appeal["enforcement_action_id"]]
    mw.ensure_owner(action["seller_id"])
    return response.one(appeal, ser.appeal, 200)


@bp.post("/appeals/<appeal_id>/start-review")
@mw.require(C.ROLE_REVIEWER)
def start_review(appeal_id):
    appeal = guards.appeal(appeal_id)
    action = db.ENFORCEMENT_ACTIONS[appeal["enforcement_action_id"]]
    mw.ensure_distinct(action["issued_by_user_id"])
    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)
    if appeal["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    db.set_field(appeal, "state", "UNDER_REVIEW")
    return response.one(appeal, ser.appeal, 200)


def _grant(appeal, action, seller, resolution_reason):
    """The compensating reinstatement cascade of PRD 3.8."""
    db.set_field(appeal, "reinstatement_granted",
                 action["action_type"] == "ACCOUNT_SUSPENSION")
    db.set_field(action, "state", "VACATED")
    db.set_field(action, "resolution_reason", resolution_reason)
    if action["action_type"] == "ACCOUNT_SUSPENSION":
        db.set_field(seller, "reinstated_count", seller["reinstated_count"] + 1)
    posture.recompute(seller, release_reason="APPEAL_GRANTED")


@bp.post("/appeals/<appeal_id>/decide")
@mw.require(C.ROLE_REVIEWER)
def decide_appeal(appeal_id):
    appeal = guards.appeal(appeal_id)
    action = db.ENFORCEMENT_ACTIONS[appeal["enforcement_action_id"]]
    mw.ensure_distinct(action["issued_by_user_id"])

    data = v.body()
    outcome = v.req_enum(data, "outcome", C.APPEAL_OUTCOMES)
    denial_reason = v.opt_enum(data, "denial_reason", C.DENIAL_REASONS)
    rationale = v.req_str(data, "rationale", 20, 2000)
    if outcome == "DENIED" and denial_reason is None:
        v.bad("'denial_reason' is required on a denial.")

    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)
    if appeal["state"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")

    if outcome == "GRANTED":
        repeats = calc.repeat_offense_count(action, db.actions_of(seller["id"]))
        if repeats >= C.APPEAL_REPEAT_DENIAL_THRESHOLD:
            raise ApiError("ERR_REPEAT_OFFENSE_DENIAL")

    now = clock.now()
    db.set_field(appeal, "decided_by_user_id", mw.actor())
    db.set_field(appeal, "decided_at", now)
    db.set_field(appeal, "rationale", rationale)
    db.set_field(appeal, "state", outcome)

    if outcome == "GRANTED":
        _grant(appeal, action, seller, "APPEAL_GRANTED")
        notify.emit(seller["id"], "APPEAL_DECISION", "APPEAL", appeal["id"],
                    decision_rationale=rationale)
    else:
        db.set_field(appeal, "denial_reason", denial_reason)
        deadline = now + timedelta(days=C.ESCALATION_WINDOW_DAYS)
        db.set_field(appeal, "escalation_deadline_at", deadline)
        db.set_field(action, "state", "UPHELD")
        db.set_field(action, "resolution_reason", "APPEAL_DENIED")
        notify.emit(seller["id"], "APPEAL_DECISION", "APPEAL", appeal["id"],
                    decision_rationale=rationale, escalation_deadline_at=deadline)
    return response.one(appeal, ser.appeal, 200)


@bp.post("/appeals/<appeal_id>/escalate")
@mw.require(C.ROLE_SELLER)
def escalate(appeal_id):
    appeal = guards.appeal(appeal_id)
    action = db.ENFORCEMENT_ACTIONS[appeal["enforcement_action_id"]]
    mw.ensure_owner(action["seller_id"])

    data = v.body()
    grounds = v.req_str(data, "escalation_grounds", 20, 2000)

    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)
    if appeal["state"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE")
    if clock.now() > appeal["escalation_deadline_at"]:
        raise ApiError("ERR_ESCALATION_WINDOW_CLOSED")

    db.set_field(appeal, "state", "ESCALATED_REVIEW")
    db.set_field(appeal, "escalation_requested_at", clock.now())
    db.set_field(appeal, "escalation_grounds", grounds)
    return response.one(appeal, ser.appeal, 200)


@bp.post("/appeals/<appeal_id>/escalation-decision")
@mw.require(C.ROLE_OFFICER)
def escalation_decision(appeal_id):
    appeal = guards.appeal(appeal_id)
    action = db.ENFORCEMENT_ACTIONS[appeal["enforcement_action_id"]]
    mw.ensure_distinct(appeal["decided_by_user_id"], action["issued_by_user_id"])

    data = v.body()
    outcome = v.req_enum(data, "outcome", C.ESCALATION_OUTCOMES)
    denial_reason = v.opt_enum(data, "denial_reason", C.DENIAL_REASONS)
    rationale = v.req_str(data, "rationale", 20, 2000)
    if outcome == "FINAL_DENIED" and denial_reason is None:
        v.bad("'denial_reason' is required on a denial.")

    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)
    if appeal["state"] != "ESCALATED_REVIEW":
        raise ApiError("ERR_INVALID_STATE")

    if outcome == "GRANTED_ON_ESCALATION":
        repeats = calc.repeat_offense_count(action, db.actions_of(seller["id"]))
        if repeats >= C.APPEAL_REPEAT_DENIAL_THRESHOLD:
            raise ApiError("ERR_REPEAT_OFFENSE_DENIAL")

    db.set_field(appeal, "escalation_decided_by_user_id", mw.actor())
    db.set_field(appeal, "rationale", rationale)
    db.set_field(appeal, "state", outcome)

    if outcome == "GRANTED_ON_ESCALATION":
        _grant(appeal, action, seller, "ESCALATION_GRANTED")
    else:
        db.set_field(appeal, "denial_reason", denial_reason)
        db.set_field(action, "resolution_reason", "ESCALATION_DENIED")
        if action["action_type"] == "ACCOUNT_SUSPENSION":
            db.set_field(seller, "ban_reason", "ESCALATION_EXHAUSTED")
            posture.recompute(seller)
            notify.emit(seller["id"], "ACCOUNT_BANNED", "SELLER", seller["id"],
                        decision_rationale=rationale)

    notify.emit(seller["id"], "ESCALATION_DECISION", "APPEAL", appeal["id"],
                decision_rationale=rationale)
    return response.one(appeal, ser.appeal, 200)
