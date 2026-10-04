"""Home assessments and scope items (PRD 3.3)."""
from flask import Blueprint, request

from db import STORES, new_record, get_clock
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, req_int, opt_str,
    req_dt, req_array, raise_err, now_iso, parse_date, clock_date,
    TRADE_VALUES,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_APPLICATION_NOT_FOUND,
    E_ASSESSMENT_NOT_FOUND, E_SCOPE_ITEM_NOT_FOUND, E_INVALID_DATE_RANGE,
)
from logic import (
    bump, midpoint_cents, compute_priority_score, latest_assessment,
    get_application,
)
from serializers import ser_assessment, ser_scope_item

bp = Blueprint("assessments", __name__)

ASSESSMENT_STATUSES = ("SCHEDULED", "COMPLETED", "SCOPED", "CANCELLED")
SCOPE_CATEGORIES = ("SAFETY", "ACCESSIBILITY", "CRITICAL_SYSTEMS", "ENERGY",
                    "GENERAL")
SCOPE_ITEM_STATUSES = ("INCLUDED", "DROPPED", "COMPLETED")


def validate_scope_item_input(raw, index=""):
    """Scope-item input shape (PRD 3.3 / 3.5): enums, estimate range, and the
    required_trade <-> volunteer_performable coherence rule."""
    if not isinstance(raw, dict):
        raise_err(E_INVALID_REQUEST, 400, "scope item %s must be an object"
                  % index)
    category = raw.get("category")
    if category not in SCOPE_CATEGORIES:
        raise_err(E_INVALID_REQUEST, 400,
                  "scope item category must be one of "
                  + ", ".join(SCOPE_CATEGORIES))
    trade = raw.get("required_trade")
    if trade not in TRADE_VALUES:
        raise_err(E_INVALID_REQUEST, 400,
                  "required_trade must be one of " + ", ".join(TRADE_VALUES))
    vp = raw.get("volunteer_performable")
    if not isinstance(vp, bool):
        raise_err(E_INVALID_REQUEST, 400,
                  "volunteer_performable must be a boolean")
    permit = raw.get("requires_permit")
    if not isinstance(permit, bool):
        raise_err(E_INVALID_REQUEST, 400, "requires_permit must be a boolean")
    low = raw.get("est_low_cents")
    if isinstance(low, bool) or not isinstance(low, int) or low <= 0:
        raise_err(E_INVALID_REQUEST, 400, "est_low_cents must be > 0")
    high = raw.get("est_high_cents")
    if isinstance(high, bool) or not isinstance(high, int) or high < low:
        raise_err(E_INVALID_REQUEST, 400,
                  "est_high_cents must be >= est_low_cents")
    description = raw.get("description")
    if not isinstance(description, str):
        raise_err(E_INVALID_REQUEST, 400, "description must be a string")
    # Coherence: required_trade == NONE exactly when volunteer_performable.
    if (trade == "NONE") != bool(vp):
        raise_err(E_INVALID_REQUEST, 400,
                  "required_trade must be NONE exactly when "
                  "volunteer_performable is true")
    return {
        "category": category,
        "required_trade": trade,
        "volunteer_performable": vp,
        "requires_permit": permit,
        "est_low_cents": low,
        "est_high_cents": high,
        "description": description,
    }


def create_scope_item(assessment_id, clean):
    return new_record("scope_items", {
        "assessment_id": assessment_id,
        "category": clean["category"],
        "required_trade": clean["required_trade"],
        "volunteer_performable": clean["volunteer_performable"],
        "requires_permit": clean["requires_permit"],
        "est_low_cents": clean["est_low_cents"],
        "est_high_cents": clean["est_high_cents"],
        "description": clean["description"],
        "status": "INCLUDED",
        "midpoint_cents": midpoint_cents(clean["est_low_cents"],
                                         clean["est_high_cents"]),
    }, now_iso, common=False)


@bp.post("/rebuild/assessments")
def create_assessment():
    require_roles("AffiliateStaff")
    b = body()
    app_id = b.get("application_id")
    if app_id is None:
        raise_err(E_INVALID_REQUEST, 400, "application_id is required")
    app = get_or_404("applications", app_id, E_APPLICATION_NOT_FOUND)
    if app["status"] not in ("VERIFIED", "ASSESSING", "ASSESSED"):
        raise_err(E_INVALID_STATE, 409,
                  "application must be VERIFIED, ASSESSING or ASSESSED")
    scheduled_on = req_dt(b, "scheduled_on")
    if parse_date(scheduled_on) < clock_date():
        raise_err(E_INVALID_DATE_RANGE, 422,
                  "scheduled_on must be on or after the current date")
    rec = new_record("assessments", {
        "application_id": app_id,
        "scheduled_on": scheduled_on,
        "status": "SCHEDULED",
        "safety_hazard_max_severity": None,
        "accessibility_needs_count": None,
        "critical_systems_notes": None,
        "completed_on": None,
    }, now_iso)
    # VERIFIED -> ASSESSING, and ASSESSED -> ASSESSING (re-assessment loop).
    if app["status"] in ("VERIFIED", "ASSESSED"):
        app["status"] = "ASSESSING"
        bump(app)
    return ok_obj(ser_assessment(rec), 201)


@bp.get("/rebuild/assessments")
def list_assessments():
    require_roles("Any")
    recs = list(STORES["assessments"].values())
    aid = request.args.get("application_id")
    if aid is not None:
        recs = [r for r in recs if r["application_id"] == aid]
    return list_response(recs, ser_assessment)


@bp.get("/rebuild/assessments/<assessmentId>")
def get_assessment(assessmentId):
    require_roles("Any")
    rec = get_or_404("assessments", assessmentId, E_ASSESSMENT_NOT_FOUND)
    return ok_obj(ser_assessment(rec))


@bp.post("/rebuild/assessments/<assessmentId>/complete")
def complete_assessment(assessmentId):
    require_roles("Assessor")
    rec = get_or_404("assessments", assessmentId, E_ASSESSMENT_NOT_FOUND)
    if rec["status"] != "SCHEDULED":
        raise_err(E_INVALID_STATE, 409,
                  "assessment must be SCHEDULED to complete")
    b = body()
    severity = req_int(b, "safety_hazard_max_severity", lo=0, hi=5)
    needs_count = req_int(b, "accessibility_needs_count", lo=0)
    notes = opt_str(b, "critical_systems_notes", default=None)
    items_in = req_array(b, "scope_items", non_empty=True)
    cleaned = [validate_scope_item_input(it, str(i))
               for i, it in enumerate(items_in)]
    for c in cleaned:
        create_scope_item(rec["id"], c)
    rec["safety_hazard_max_severity"] = severity
    rec["accessibility_needs_count"] = needs_count
    rec["critical_systems_notes"] = notes
    rec["status"] = "COMPLETED"
    rec["completed_on"] = get_clock()
    bump(rec)
    return ok_obj(ser_assessment(rec))


@bp.patch("/rebuild/assessments/<assessmentId>")
def patch_assessment(assessmentId):
    require_roles("Assessor", "AffiliateStaff")
    rec = get_or_404("assessments", assessmentId, E_ASSESSMENT_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in ASSESSMENT_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(ASSESSMENT_STATUSES))
    if target == "SCOPED":
        if rec["status"] != "COMPLETED":
            raise_err(E_INVALID_STATE, 409,
                      "assessment must be COMPLETED to scope")
        rec["status"] = "SCOPED"
        bump(rec)
        app = get_application(rec["application_id"])
        latest = latest_assessment(rec["application_id"])
        if (app is not None and latest is not None
                and latest["id"] == rec["id"]
                and app["status"] == "ASSESSING"):
            app["status"] = "ASSESSED"
            app["priority_score"] = compute_priority_score(
                app, rec["safety_hazard_max_severity"])
            bump(app)
    elif target == "CANCELLED":
        if rec["status"] != "SCHEDULED":
            raise_err(E_INVALID_STATE, 409,
                      "only a SCHEDULED assessment can be cancelled")
        rec["status"] = "CANCELLED"
        bump(rec)
    else:
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    return ok_obj(ser_assessment(rec))


@bp.get("/rebuild/scope-items")
def list_scope_items():
    require_roles("Any")
    recs = list(STORES["scope_items"].values())
    aid = request.args.get("assessment_id")
    if aid is not None:
        recs = [r for r in recs if r["assessment_id"] == aid]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_scope_item)


@bp.get("/rebuild/scope-items/<scopeItemId>")
def get_scope_item(scopeItemId):
    require_roles("Any")
    rec = get_or_404("scope_items", scopeItemId, E_SCOPE_ITEM_NOT_FOUND)
    return ok_obj(ser_scope_item(rec))
