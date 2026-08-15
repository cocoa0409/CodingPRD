"""Accommodation plans: create, submit, approve (OCC), request-revision (PRD §3.5)."""

from flask import Blueprint, request

import store
from auth import authenticate, require_role
from derived import plan_view
from envelope import ok_object
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
)
from routes.common import paginate, empty_body
from validate import Field, get_body, validate_body, bad

bp = Blueprint("plans", __name__)

SEVERITIES = {"FOOD_ALLERGY", "ENVIRONMENTAL_ALLERGY", "MEDICATION_ADMIN", "MOBILITY", "BEHAVIORAL"}

_CREATE_SPEC = {
    "child_id": Field("str", required=True),
    "severity": Field("enum", enum=SEVERITIES, required=True),
    "allergens": Field("allergens"),
    "instructions": Field("str", required=True),
    "requires_epinephrine": Field("bool", default=False),
}

_APPROVE_SPEC = {
    "expected_child_version": Field("int", required=True),
}

_REVISION_SPEC = {
    "revision_notes": Field("str", required=True),
}


def get_plan_or_404(plan_id):
    plan = store.get("accommodation_plans", plan_id)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "accommodation plan not found")
    return plan


def _check_parent_owns(ctx, plan):
    if ctx.role != "Parent":
        return
    child = store.get("children", plan["child_id"])
    if child is None or child["family_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only act on their own children's plans")


@bp.post("/vbs/accommodation-plans")
def create_plan():
    body = get_body()
    data = validate_body(body, _CREATE_SPEC)
    # Conditional field rule (P0): allergens required and non-empty iff FOOD_ALLERGY.
    if data["severity"] == "FOOD_ALLERGY":
        if "allergens" not in data or not data["allergens"]:
            bad("allergens is required and non-empty when severity is FOOD_ALLERGY")
    else:
        if "allergens" in data:
            bad("allergens is forbidden unless severity is FOOD_ALLERGY")
    ctx = authenticate()
    require_role(ctx, "Parent", "SafetyOfficer")
    child = store.get("children", data["child_id"])
    if ctx.role == "Parent" and child is not None and child["family_id"] != ctx.user_id:
        raise_err(ERR_FORBIDDEN, "parents may only create plans for their own children")
    if child is None:
        raise_err(ERR_NOT_FOUND, "child not found")
    plan = store.new_record(
        child_id=child["id"],
        severity=data["severity"],
        allergens=data.get("allergens") or [],
        instructions=data["instructions"],
        requires_epinephrine=data["requires_epinephrine"],
        status="DRAFT",
        revision_notes=None,
        reviewed_by=None,
    )
    store.put("accommodation_plans", plan)
    return ok_object(plan_view(plan), status=201)


@bp.post("/vbs/accommodation-plans/<plan_id>/submit")
def submit_plan(plan_id):
    empty_body()
    ctx = authenticate()
    require_role(ctx, "Parent")
    plan = get_plan_or_404(plan_id)
    _check_parent_owns(ctx, plan)
    if plan["status"] not in ("DRAFT", "NEEDS_REVISION"):
        raise_err(ERR_INVALID_STATE, "only DRAFT or NEEDS_REVISION plans may be submitted")
    plan["status"] = "SUBMITTED"
    store.touch(plan)
    return ok_object(plan_view(plan))


@bp.post("/vbs/accommodation-plans/<plan_id>/approve")
def approve_plan(plan_id):
    body = get_body()
    data = validate_body(body, _APPROVE_SPEC)
    ctx = authenticate()
    require_role(ctx, "SafetyOfficer")
    plan = get_plan_or_404(plan_id)
    child = store.get("children", plan["child_id"])
    # Priority 4 (OCC) runs ahead of the state gate.
    if child is None or data["expected_child_version"] != child["version"]:
        raise_err(ERR_STALE_VERSION, "expected_child_version does not match the child's version")
    if plan["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "only a SUBMITTED plan may be approved")
    plan["status"] = "APPROVED"
    plan["reviewed_by"] = ctx.user_id
    store.touch(plan)
    for other in store.all_of("accommodation_plans"):
        if (
            other["id"] != plan["id"]
            and other["child_id"] == plan["child_id"]
            and other["status"] == "APPROVED"
        ):
            other["status"] = "SUPERSEDED"
            store.touch(other)
    # The supersede mutates the child's plan set: the child's version advances.
    store.touch(child)
    return ok_object(plan_view(plan))


@bp.post("/vbs/accommodation-plans/<plan_id>/request-revision")
def request_revision(plan_id):
    body = get_body()
    data = validate_body(body, _REVISION_SPEC)
    ctx = authenticate()
    require_role(ctx, "SafetyOfficer")
    plan = get_plan_or_404(plan_id)
    if plan["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "only a SUBMITTED plan may be sent back for revision")
    plan["status"] = "NEEDS_REVISION"
    plan["revision_notes"] = data["revision_notes"]
    plan["reviewed_by"] = ctx.user_id
    store.touch(plan)
    return ok_object(plan_view(plan))


@bp.get("/vbs/accommodation-plans/<plan_id>")
def get_plan(plan_id):
    ctx = authenticate()
    require_role(ctx, "SafetyOfficer", "Parent", "CheckInStaff")
    plan = store.get("accommodation_plans", plan_id)
    if plan is not None:
        _check_parent_owns(ctx, plan)
    if plan is None:
        raise_err(ERR_NOT_FOUND, "accommodation plan not found")
    return ok_object(plan_view(plan))


@bp.get("/vbs/accommodation-plans")
def list_plans():
    ctx = authenticate()
    require_role(ctx, "SafetyOfficer", "CheckInStaff", "Parent")
    items = list(store.all_of("accommodation_plans"))
    if ctx.role == "Parent":
        own_children = {
            c["id"] for c in store.all_of("children") if c["family_id"] == ctx.user_id
        }
        items = [p for p in items if p["child_id"] in own_children]
    child_id = request.args.get("child_id")
    status = request.args.get("status")
    if child_id is not None:
        items = [p for p in items if p["child_id"] == child_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate(items, plan_view)
