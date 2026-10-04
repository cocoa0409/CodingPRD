"""FulfillmentPlan governance: submit, approve (SoD + fiscal + escalation),
and abort (release cascades)."""

from flask import Blueprint, g

from auth import require_roles
from cascade import lines_of_plan, release_line, ready_gate_satisfied
from db import STORE, touch
from errors import ApiError
from resp import ok
from serialize import (
    ser_plan, plan_total, chapter_committed, chapter_granted_aggs,
    chapter_posture,
)
from util import body_json, rhu_div, opt_str

bp = Blueprint("plan_governance", __name__)


def _get_plan(pid):
    p = STORE["plans"].get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "FulfillmentPlan not found")
    return p


@bp.post("/wish-grant/fulfillment-plans/<pid>/submit")
@require_roles("WishCoordinator", "ChapterDirector")
def submit_plan(pid):
    plan = _get_plan(pid)
    body_json(required=False)
    if plan["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", 409,
            "submit requires DRAFT",
        )
    has_reserved = any(
        l["status"] == "RESERVED" for l in lines_of_plan(plan["id"])
    )
    if not has_reserved and plan["cash_cost_cents"] <= 0:
        raise ApiError(
            "ERR_EMPTY_PLAN", 422,
            "Plan needs a RESERVED line item or a positive cash cost",
        )
    plan["status"] = "PENDING_APPROVAL"
    touch(plan)
    return ok(ser_plan(plan))


@bp.post("/wish-grant/fulfillment-plans/<pid>/approve")
@require_roles("ChapterDirector", "NationalDirector")
def approve_plan(pid):
    plan = _get_plan(pid)
    body_json(required=False)
    if plan["status"] != "PENDING_APPROVAL":
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", 409,
            "approve requires PENDING_APPROVAL",
        )
    if plan["created_by_user_id"] == g.user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES", 403,
            "The plan creator cannot approve their own plan",
        )
    wish = STORE["wishes"][plan["wish_id"]]
    chapter = STORE["chapters"][wish["chapter_id"]]
    committed = chapter_committed(chapter["id"])
    if chapter_posture(chapter, committed) == "FROZEN":
        raise ApiError(
            "ERR_CHAPTER_BUDGET_FROZEN", 409,
            "Chapter posture is FROZEN",
        )
    total = plan_total(plan)
    if committed + total > chapter["fiscal_year_budget_cents"]:
        raise ApiError(
            "ERR_CHAPTER_BUDGET_EXCEEDED", 422,
            "Approving this plan would exceed the chapter budget",
        )
    cnt, granted_cost, _cash = chapter_granted_aggs(chapter["id"])
    projected_avg = rhu_div(granted_cost + total, cnt + 1)
    escalation = projected_avg > chapter["target_avg_cost_per_wish_cents"]
    if escalation and g.user_role != "NationalDirector":
        raise ApiError(
            "ERR_COST_ESCALATION_REQUIRED", 422,
            "Projected cost per wish exceeds target; NationalDirector required",
        )

    plan["status"] = "APPROVED"
    plan["approved_by_user_id"] = g.user_id
    plan["escalation_required"] = escalation
    touch(plan)
    for l in lines_of_plan(plan["id"]):
        if l["status"] == "RESERVED":
            l["status"] = "COMMITTED"
            touch(l)
    touch(chapter)
    wish["status"] = "PLAN_APPROVED"
    touch(wish)
    if ready_gate_satisfied(wish):
        wish["status"] = "READY_TO_SCHEDULE"
        touch(wish)
    return ok(ser_plan(plan))


@bp.post("/wish-grant/fulfillment-plans/<pid>/abort")
@require_roles("ChapterDirector")
def abort_plan(pid):
    plan = _get_plan(pid)
    body = body_json(required=False)
    opt_str(body, "reason")
    if plan["status"] not in ("PENDING_APPROVAL", "APPROVED"):
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", 409,
            "abort requires PENDING_APPROVAL or APPROVED",
        )
    wish = STORE["wishes"][plan["wish_id"]]
    if plan["status"] == "APPROVED" and wish["status"] == "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", 409,
            "An approved plan cannot be aborted while the wish is SCHEDULED",
        )
    was_approved = plan["status"] == "APPROVED"
    plan["status"] = "CANCELLED"
    touch(plan)
    for l in lines_of_plan(plan["id"]):
        if l["status"] in ("RESERVED", "COMMITTED"):
            release_line(l)
    if was_approved:
        chapter = STORE["chapters"][wish["chapter_id"]]
        touch(chapter)
        if wish["status"] in ("PLAN_APPROVED", "READY_TO_SCHEDULE"):
            wish["status"] = "PLANNING"
            touch(wish)
        elif wish["status"] == "MEDICAL_HOLD":
            wish["status"] = "PLANNING"
            wish["hold_return_state"] = None
            touch(wish)
    return ok(ser_plan(plan))
