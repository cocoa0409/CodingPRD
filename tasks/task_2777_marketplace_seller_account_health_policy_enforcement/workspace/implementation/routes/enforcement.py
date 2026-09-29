"""Severity weighting, the enforcement ladder and acknowledgement (PRD 3.6)."""

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

bp = Blueprint("enforcement", __name__)


def _seller_plans(seller_id):
    plans = []
    for action in db.actions_of(seller_id):
        plans.extend(db.plans_of_action_for(action["id"]))
    return plans


@bp.post("/enforcement-actions")
@mw.require(C.ROLE_INVESTIGATOR)
def issue_action():
    data = v.body()
    violation = guards.body_fk(db.VIOLATIONS, data.get("violation_id"),
                              "ERR_VIOLATION_NOT_FOUND")
    v.req_str(data, "violation_id", 1, None)
    override = v.opt_enum(data, "action_type_override", C.ACTION_TYPES)
    if violation is None:
        raise ApiError("ERR_VIOLATION_NOT_FOUND")

    seller = db.SELLERS[violation["seller_id"]]
    rule = db.POLICY_RULES[violation["policy_rule_id"]]
    guards.ensure_not_banned(seller)

    if violation["state"] != "SUBSTANTIATED":
        raise ApiError("ERR_VIOLATION_NOT_SUBSTANTIATED")
    if rule["requires_poa"]:
        for plan in _seller_plans(seller["id"]):
            if plan["state"] in ("SUBMITTED", "RETURNED_FOR_REVISION"):
                raise ApiError("ERR_INVALID_STATE")

    now = clock.now()
    existing_actions = db.actions_of(seller["id"])
    prior_balance = calc.decayed_balance(existing_actions, now)
    prior_same_category = len([
        a for a in existing_actions
        if a["policy_category"] == rule["category"] and a["state"] in C.ACTION_LIVE_STATES
    ])
    points = calc.severity_points_applied(
        rule["base_severity_weight"],
        prior_same_category,
        rule["category"] == "INTELLECTUAL_PROPERTY"
        and violation["reporter_type"] == "RIGHTS_OWNER",
        seller.get("metric_tier") == "BREACHING",
    )
    post_balance = calc.q2(prior_balance + points)
    rung = calc.ladder_rung(post_balance, rule["category"])

    if override is not None and C.ACTION_SEVERITY[override] <= C.ACTION_SEVERITY[rung]:
        raise ApiError("ERR_OVERRIDE_NOT_MORE_SEVERE")

    for other in db.ENFORCEMENT_ACTIONS.values():
        if (other["violation_id"] == violation["id"]
                and other["state"] in C.ACTION_LIVE_STATES):
            raise ApiError("ERR_ACTION_ALREADY_EXISTS")

    action_type = override if override is not None else rung
    action = db.new_row(
        "action",
        seller_id=seller["id"],
        violation_id=violation["id"],
        policy_category=rule["category"],
        policy_rule_code=rule["code"],
        decay_exempt=rule["decay_exempt"],
        severity_points_applied=points,
        ladder_rung_computed=rung,
        action_type=action_type,
        override_applied=override is not None,
        issued_by_user_id=mw.actor(),
        issued_at=now,
        appeal_deadline_at=now + timedelta(days=C.APPEAL_WINDOW_DAYS),
        state="ISSUED",
        acknowledged_at=None,
        resolution_reason=None,
        removed_listing_count=0,
    )
    db.ENFORCEMENT_ACTIONS[action["id"]] = action

    # PRD 2.5 / 3.6: balance, then enforcement posture and its listing cascade,
    # then the funds posture.
    db.set_field(seller, "severity_points_balance", post_balance)
    posture.apply_enforcement(
        seller, force_suspension_cascade=(action_type == "ACCOUNT_SUSPENSION")
    )
    if action_type == "LISTING_REMOVAL":
        posture.remove_listings_for_action(
            seller, action, rule["removal_scope"], violation["listing_id"]
        )
    posture.apply_disbursement(seller)
    db.mark_dirty(seller)

    notify.emit(
        seller["id"], "ACTION_ISSUED", "ENFORCEMENT_ACTION", action["id"],
        policy_rule_code=rule["code"],
        severity_points_disclosed=points,
        appeal_deadline_at=action["appeal_deadline_at"],
        evidence_reference=violation["evidence_reference"],
        decision_rationale=violation["decision_note"],
    )
    return response.one(action, ser.action, 201)


@bp.get("/enforcement-actions")
@mw.require(C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def list_actions():
    limit, offset = v.pagination()
    rows = db.sorted_rows(db.ENFORCEMENT_ACTIONS)
    for field in ("seller_id", "violation_id", "state"):
        if field in request.args:
            wanted = request.args.get(field)
            rows = [r for r in rows if r.get(field) == wanted]
    page, total = response.paginate(rows, limit, offset)
    return response.many(page, ser.action, limit, offset, total)


@bp.get("/enforcement-actions/<action_id>")
@mw.require(C.ROLE_SELLER, C.ROLE_INVESTIGATOR, C.ROLE_REVIEWER, C.ROLE_OFFICER)
def read_action(action_id):
    action = guards.action(action_id)
    mw.ensure_owner(action["seller_id"])
    return response.one(action, ser.action, 200)


@bp.post("/enforcement-actions/<action_id>/acknowledge")
@mw.require(C.ROLE_SELLER)
def acknowledge(action_id):
    action = guards.action(action_id)
    mw.ensure_owner(action["seller_id"])
    seller = db.SELLERS[action["seller_id"]]
    guards.ensure_not_banned(seller)
    if action["state"] in ("UPHELD", "VACATED"):
        raise ApiError("ERR_ACTION_NOT_APPEALABLE_STATE")
    if action["state"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")

    db.set_field(action, "state", "ACKNOWLEDGED")
    db.set_field(action, "acknowledged_at", clock.now())
    return response.one(action, ser.action, 200)
