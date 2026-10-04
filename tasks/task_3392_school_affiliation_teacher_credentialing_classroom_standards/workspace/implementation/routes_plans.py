"""Improvement plans (PRD 3.6): respond with OCC, reviewer adjudication,
and the standing auto-restore on final verification."""

from datetime import timedelta

from flask import Blueprint, request

from cascade import apply_standing_transition, OPEN_PLAN_STATES
from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_PLAN_NOT_FOUND,
    ERR_VALIDATION,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
)
from serializers import serialize_plan
from store import db, touch, now_date, now_iso, active_catalog
from validation import authenticate, require_role, payload, req_str, req_enum

bp = Blueprint("plans", __name__)

PLAN_ROLES = {"SocietyAdmin", "AccreditationReviewer", "SchoolAdmin"}
PLAN_OUTCOMES = {"VERIFIED", "CHANGES_REQUESTED"}


def get_plan_or_404(plan_id):
    p = db.plans.get(plan_id)
    if p is None:
        raise ApiError(ERR_PLAN_NOT_FOUND[0], ERR_PLAN_NOT_FOUND[1],
                       "No improvement plan with id %r." % plan_id)
    return p


@bp.route("/improvement-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _, role = authenticate()
    require_role(role, PLAN_ROLES)
    return ok(serialize_plan(get_plan_or_404(plan_id)), 200)


@bp.route("/improvement-plans", methods=["GET"])
def list_plans():
    _, role = authenticate()
    require_role(role, PLAN_ROLES)
    args = request.args
    items = list(db.plans.values())
    for f in ("school_id", "visit_id", "status"):
        v = args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_plan)


@bp.route("/improvement-plans/<plan_id>/respond", methods=["POST"])
def respond_to_plan(plan_id):
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    plan = get_plan_or_404(plan_id)
    body = payload()
    # Tier 4: response_notes and the OCC token are non-optional (PRD 2.8).
    notes = body.get("response_notes")
    if not isinstance(notes, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'response_notes' is required and must be a string.")
    expected = body.get("expected_improvement_plan_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'expected_improvement_plan_version' is required "
                       "and must be an integer.")
    # Tier 5: the school's own SchoolAdmin responds.
    if uid != plan["school_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "SchoolAdmin may only respond to their own school's plans.")
    # Tier 6: OCC evaluated BEFORE the state check within this tier.
    if expected != plan["version"]:
        raise ApiError(ERR_STALE_VERSION[0], ERR_STALE_VERSION[1],
                       "expected_improvement_plan_version does not match the "
                       "plan's current version.")
    if plan["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an OPEN or OVERDUE plan can be answered.")
    plan["response_notes"] = notes
    plan["submitted_at"] = now_iso()
    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok(serialize_plan(plan), 200)


@bp.route("/improvement-plans/<plan_id>/review", methods=["POST"])
def review_plan(plan_id):
    _, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    plan = get_plan_or_404(plan_id)
    body = payload()
    outcome = req_enum(body, "outcome", PLAN_OUTCOMES)
    # Tier 6: only a SUBMITTED plan is adjudicable.
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a SUBMITTED plan can be reviewed.")
    if outcome == "VERIFIED":
        plan["status"] = "VERIFIED"
        plan["verified_at"] = now_iso()
        touch(plan)
        # When no plan of the school remains open and standing is PROBATION,
        # the school's standing auto-restores to GOOD_STANDING (PRD 3.7).
        school = db.schools.get(plan["school_id"])
        if school is not None and school["standing"] == "PROBATION":
            remaining = [
                p for p in db.plans.values()
                if p["school_id"] == school["id"] and p["status"] in OPEN_PLAN_STATES
            ]
            if not remaining:
                apply_standing_transition(school, "GOOD_STANDING")
    else:  # CHANGES_REQUESTED: back to OPEN with a fresh due_date.
        plan["status"] = "OPEN"
        cat = active_catalog()
        if cat is not None:
            plan["due_date"] = (
                now_date() + timedelta(days=int(cat["plan_response_days"]))
            ).isoformat()
        touch(plan)
    return ok(serialize_plan(plan), 200)
