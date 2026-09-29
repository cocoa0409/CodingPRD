"""Corrective action plans and follow-up scheduling (PRD 3.8)."""

from flask import Blueprint

import auth
import derive
import envelope
import shapes
import store
from errors import ApiError
from routes import common, inspections

bp = Blueprint("plans", __name__)


def _fiscal_checks(insp, cost_cents, target_completion_at):
    """Priorities 80 and 81, in that order."""
    prop = store.properties.get(insp["property_id"])
    if prop is not None and cost_cents > prop["capital_reserve_cents"]:
        raise ApiError(
            "ERR_CAP_COST_EXCEEDS_RESERVE",
            "total_estimated_cost_cents exceeds the property's capital_reserve_cents.",
        )
    deadline = store.parse_instant(insp.get("cap_due_at"))
    if deadline is not None:
        target = store.parse_instant(target_completion_at)
        if target > deadline:
            raise ApiError(
                "ERR_CAP_TARGET_AFTER_DEADLINE",
                "target_completion_at falls after the inspection's cap_due_at.",
            )


@bp.post("/corrective-action-plans")
def submit_plan():
    user_id, role = auth.authenticate([auth.OWNER])
    values = shapes.validate(
        [
            shapes.F("inspection_id", "string"),
            shapes.F("narrative", "string"),
            shapes.F("total_estimated_cost_cents", "integer", minimum=0),
            shapes.F("milestone_count", "integer", minimum=1),
            shapes.F("target_completion_at", "datetime"),
            shapes.F("submitted_at", "datetime"),
        ]
    )
    insp = common.body_fetch("inspection", values["inspection_id"])
    auth.require_owner(role, user_id, insp["property_id"])
    _fiscal_checks(
        insp, values["total_estimated_cost_cents"], values["target_completion_at"]
    )
    row = {
        "inspection_id": insp["id"],
        "follow_up_inspection_id": None,
        "status": "SUBMITTED",
        "narrative": values["narrative"],
        "total_estimated_cost_cents": values["total_estimated_cost_cents"],
        "milestone_count": values["milestone_count"],
        "target_completion_at": values["target_completion_at"],
        "submitted_at": values["submitted_at"],
        "decided_at": None,
        "revision_count": 0,
        "reviewer_note": None,
    }
    store.stamp_new(row)
    store.plans[row["id"]] = row
    return envelope.created(row)


@bp.get("/corrective-action-plans/<plan_id>")
def read_plan(plan_id):
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    plan = common.fetch("plan", plan_id)
    auth.require_owner(role, user_id, auth.property_of_plan(plan))
    return envelope.ok(plan)


@bp.get("/corrective-action-plans")
def list_plans():
    user_id, role = auth.authenticate(auth.ANY_ROLE)
    return common.listing(
        store.plans.values(),
        ["inspection_id", "follow_up_inspection_id", "status"],
        role=role,
        user_id=user_id,
        property_getter=auth.property_of_plan,
    )


@bp.post("/corrective-action-plans/<plan_id>/review")
def review_plan(plan_id):
    auth.authenticate([auth.REVIEWER])
    values = shapes.validate(
        [
            shapes.F("decision", "enum", values=shapes.CAP_DECISION),
            shapes.F("decided_at", "datetime"),
            shapes.F("reviewer_note", "string", required=False),
        ]
    )
    plan = common.fetch("plan", plan_id)
    insp = store.inspections.get(plan["inspection_id"])
    if plan["status"] != "SUBMITTED" or insp is None or insp["status"] != "CAP_REQUIRED":
        raise ApiError(
            "ERR_CAP_INVALID_STATE",
            "The plan must be SUBMITTED and its inspection CAP_REQUIRED.",
        )
    if values["decision"] == "APPROVED":
        plan["status"] = "APPROVED"
        plan["decided_at"] = values["decided_at"]
        plan["reviewer_note"] = values.get("reviewer_note")
        store.touch(plan, bump_version=True)
        insp["status"] = "CAP_APPROVED"
        store.touch(insp, bump_version=True)
        return envelope.ok(plan)
    plan["status"] = "REJECTED"
    plan["decided_at"] = values["decided_at"]
    plan["reviewer_note"] = values.get("reviewer_note")
    store.touch(plan, bump_version=True)
    return envelope.ok(plan)


@bp.post("/corrective-action-plans/<plan_id>/resubmit")
def resubmit_plan(plan_id):
    user_id, role = auth.authenticate([auth.OWNER])
    values = shapes.validate(
        [
            shapes.F("narrative", "string"),
            shapes.F("total_estimated_cost_cents", "integer", minimum=0),
            shapes.F("milestone_count", "integer", minimum=1),
            shapes.F("target_completion_at", "datetime"),
        ]
    )
    plan = common.fetch("plan", plan_id)
    auth.require_owner(role, user_id, auth.property_of_plan(plan))
    if plan["status"] != "REJECTED":
        raise ApiError(
            "ERR_CAP_INVALID_STATE", "Only a REJECTED plan may be resubmitted."
        )
    insp = store.inspections.get(plan["inspection_id"])
    _fiscal_checks(
        insp, values["total_estimated_cost_cents"], values["target_completion_at"]
    )
    plan["status"] = "SUBMITTED"
    plan["narrative"] = values["narrative"]
    plan["total_estimated_cost_cents"] = values["total_estimated_cost_cents"]
    plan["milestone_count"] = values["milestone_count"]
    plan["target_completion_at"] = values["target_completion_at"]
    plan["revision_count"] = plan["revision_count"] + 1
    plan["decided_at"] = None
    plan["reviewer_note"] = None
    store.touch(plan, bump_version=True)
    return envelope.ok(plan)


@bp.post("/corrective-action-plans/<plan_id>/schedule-follow-up")
def schedule_follow_up(plan_id):
    auth.authenticate([auth.INSPECTOR])
    values = shapes.validate(
        [
            shapes.F("scheduled_start", "datetime"),
            shapes.F("scheduled_end", "datetime"),
        ]
    )
    plan = common.fetch("plan", plan_id)
    if plan["status"] != "APPROVED":
        raise ApiError(
            "ERR_CAP_INVALID_STATE",
            "Only an APPROVED plan may have its follow-up scheduled.",
        )
    parent = store.inspections.get(plan["inspection_id"])
    start = shapes.instant(values, "scheduled_start")
    end = shapes.instant(values, "scheduled_end")
    if end <= start:
        raise ApiError(
            "ERR_INVALID_TIME_WINDOW",
            "scheduled_end must be strictly after scheduled_start.",
        )
    if inspections.window_conflict(parent["property_id"], start, end):
        raise ApiError(
            "ERR_INSPECTION_WINDOW_CONFLICT",
            "The follow-up window conflicts with another live inspection window.",
        )
    target = store.parse_instant(plan["target_completion_at"])
    followup_due = store.parse_instant(parent.get("followup_due_at"))
    if start < target or (followup_due is not None and start > followup_due):
        raise ApiError(
            "ERR_FOLLOW_UP_TOO_EARLY",
            "The follow-up window must open at or after target_completion_at and "
            "no later than followup_due_at.",
        )

    follow_up = inspections.new_inspection_row(
        parent["property_id"],
        parent["standard_id"],
        values["scheduled_start"],
        values["scheduled_end"],
        "FOLLOW_UP",
    )
    plan["follow_up_inspection_id"] = follow_up["id"]
    plan["status"] = "FOLLOW_UP_SCHEDULED"
    store.touch(plan, bump_version=True)
    parent["status"] = "FOLLOW_UP_SCHEDULED"
    store.touch(parent, bump_version=True)
    derive.refresh_unit_history(parent["id"])
    return envelope.created(follow_up)
