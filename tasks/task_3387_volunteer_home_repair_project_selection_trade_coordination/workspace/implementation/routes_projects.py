"""Projects and OCC-guarded scope amendments (PRD 3.5, 3.9)."""
from flask import Blueprint, request

from db import STORES, new_record, get_clock
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, opt_array,
    opt_enum, raise_err, now_iso, parse_date, clock_date, parse_dt,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_PROJECT_NOT_FOUND,
    E_SCOPE_ITEM_NOT_FOUND, E_STALE_VERSION, E_NOT_DROPPABLE,
    E_ENVELOPE_EXCEEDED, E_INVALID_DATE_RANGE,
)
from logic import (
    bump, project_items, project_work_orders, envelope_for, cycle_ledger,
    sync_posture, midpoint_cents, add_calendar_months, get_application,
    reconciled_cost,
)
from cascades import cancel_project
from routes_assessments import validate_scope_item_input, create_scope_item
from serializers import ser_project

bp = Blueprint("projects", __name__)

PROJECT_STATUSES = ("PLANNING", "READY", "EVENT_SCHEDULED", "IN_BUILD",
                    "COMPLETED", "WARRANTY_ACTIVE", "CLOSED", "CANCELLED")
CANCELLATION_REASONS = ("FUNDING_WITHDRAWN", "STAFF_DECISION",
                        "HOMEOWNER_WITHDRAWN")


@bp.get("/rebuild/projects")
def list_projects():
    require_roles("Any")
    recs = list(STORES["projects"].values())
    aid = request.args.get("application_id")
    if aid is not None:
        recs = [r for r in recs if r["application_id"] == aid]
    fc = request.args.get("funding_cycle_id")
    if fc is not None:
        recs = [r for r in recs if r["funding_cycle_id"] == fc]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_project)


@bp.get("/rebuild/projects/<projectId>")
def get_project_route(projectId):
    require_roles("Any")
    rec = get_or_404("projects", projectId, E_PROJECT_NOT_FOUND)
    return ok_obj(ser_project(rec))


def _complete_project(rec):
    # Completion gates: every scope item COMPLETED or DROPPED; every work
    # order PAID or CANCELLED.
    for item in project_items(rec):
        if item["status"] not in ("COMPLETED", "DROPPED"):
            raise_err(E_INVALID_STATE, 409,
                      "every scope item must be COMPLETED or DROPPED")
    for w in project_work_orders(rec["id"]):
        if w["status"] not in ("PAID", "CANCELLED"):
            raise_err(E_INVALID_STATE, 409,
                      "every work order must be PAID or CANCELLED")
    completed_dt = parse_dt(get_clock())
    rec["completed_on"] = get_clock()
    until = add_calendar_months(completed_dt, 12)
    # Keep the time-of-day style of the clock stamp.
    rec["warranty_valid_until"] = until.strftime("%Y-%m-%dT%H:%M:%SZ") \
        if "T" in str(rec["completed_on"]) else until.strftime("%Y-%m-%d")
    rec["status"] = "COMPLETED"
    rec["reserved_balance_cents"] = 0
    bump(rec)
    app = get_application(rec["application_id"])
    if app is not None and app["status"] == "SELECTED":
        app["status"] = "FULFILLED"
        bump(app)


@bp.patch("/rebuild/projects/<projectId>")
def patch_project(projectId):
    require_roles("AffiliateStaff")
    rec = get_or_404("projects", projectId, E_PROJECT_NOT_FOUND)
    b = body()
    if "status" in b and b["status"] is not None:
        target = b["status"]
        if not isinstance(target, str) or target not in PROJECT_STATUSES:
            raise_err(E_INVALID_REQUEST, 400,
                      "status must be one of " + ", ".join(PROJECT_STATUSES))
        if target == "COMPLETED":
            if rec["status"] != "IN_BUILD":
                raise_err(E_INVALID_STATE, 409,
                          "project must be IN_BUILD to complete")
            _complete_project(rec)
        elif target == "CANCELLED":
            if rec["status"] not in ("PLANNING", "READY", "EVENT_SCHEDULED"):
                raise_err(E_INVALID_STATE, 409,
                          "only PLANNING, READY or EVENT_SCHEDULED projects "
                          "can be cancelled")
            reason = opt_enum(b, "cancellation_reason", CANCELLATION_REASONS,
                              default="STAFF_DECISION")
            cancel_project(rec, reason)
        elif target == "CLOSED":
            if rec["status"] != "WARRANTY_ACTIVE":
                raise_err(E_INVALID_STATE, 409,
                          "project must be WARRANTY_ACTIVE to close")
            until = parse_date(rec["warranty_valid_until"])
            if not (clock_date() > until):
                raise_err(E_INVALID_STATE, 409,
                          "warranty window must have passed before closing")
            open_claims = [c for c in STORES["warranty_claims"].values()
                           if c["project_id"] == rec["id"]
                           and c["status"] in ("SUBMITTED", "APPROVED")]
            if open_claims:
                raise_err(E_INVALID_STATE, 409,
                          "open warranty claims block closure")
            rec["status"] = "CLOSED"
            bump(rec)
        else:
            raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
        return ok_obj(ser_project(rec))
    if "follow_up_completed_on" in b:
        # Setting the 30-day follow-up on a COMPLETED project opens the
        # warranty period.
        if rec["status"] != "COMPLETED":
            raise_err(E_INVALID_STATE, 409,
                      "follow-up can only be recorded on a COMPLETED project")
        value = b["follow_up_completed_on"]
        if parse_dt(value) is None:
            raise_err(E_INVALID_REQUEST, 400,
                      "follow_up_completed_on must be an ISO-8601 date")
        if parse_date(value) < parse_date(rec["completed_on"]):
            raise_err(E_INVALID_DATE_RANGE, 422,
                      "follow_up_completed_on must be on or after "
                      "completed_on")
        rec["follow_up_completed_on"] = value
        rec["status"] = "WARRANTY_ACTIVE"
        bump(rec)
        return ok_obj(ser_project(rec))
    raise_err(E_INVALID_REQUEST, 400,
              "status or follow_up_completed_on is required")


@bp.post("/rebuild/projects/<projectId>/scope-amendments")
def amend_scope(projectId):
    require_roles("AffiliateStaff")
    rec = get_or_404("projects", projectId, E_PROJECT_NOT_FOUND)
    b = body()
    drop_ids = opt_array(b, "drop_item_ids", default=[])
    restore_ids = opt_array(b, "restore_item_ids", default=[])
    # Tier 4: body FK existence for every referenced scope item.
    for iid in list(drop_ids) + list(restore_ids):
        if not isinstance(iid, str):
            raise_err(E_INVALID_REQUEST, 400,
                      "scope item ids must be strings")
        item = STORES["scope_items"].get(iid)
        if item is None or item["assessment_id"] != rec["_assessment_id"]:
            raise_err(E_SCOPE_ITEM_NOT_FOUND, 404,
                      "scope item %s not found on this project" % iid)
    # Tier 5: OCC — expected_project_version is non-optional.
    if ("expected_project_version" not in b
            or b["expected_project_version"] is None):
        raise_err(E_INVALID_REQUEST, 400,
                  "expected_project_version is required")
    expected = b["expected_project_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(E_INVALID_REQUEST, 400,
                  "expected_project_version must be an integer")
    if expected != rec["version"]:
        raise_err(E_STALE_VERSION, 412,
                  "expected_project_version does not match the project "
                  "version")
    # Tier 6: state gate.
    if rec["status"] not in ("PLANNING", "READY"):
        raise_err(E_INVALID_STATE, 409,
                  "scope amendments require the project in PLANNING or READY")
    add_items = opt_array(b, "add_items", default=[])
    cleaned_adds = [validate_scope_item_input(x, str(i))
                    for i, x in enumerate(add_items)]
    # Item-level drop/restore preconditions.
    for iid in drop_ids:
        item = STORES["scope_items"][iid]
        if item["status"] != "INCLUDED":
            raise_err(E_INVALID_STATE, 409,
                      "only INCLUDED items can be dropped")
        covered = any(
            w["status"] not in ("CANCELLED", "PAID")
            and iid in w["scope_item_ids"]
            for w in project_work_orders(rec["id"]))
        if covered:
            raise_err(E_NOT_DROPPABLE, 422,
                      "item %s is covered by a non-terminal work order" % iid)
    for iid in restore_ids:
        item = STORES["scope_items"][iid]
        if item["status"] != "DROPPED":
            raise_err(E_INVALID_STATE, 409,
                      "only DROPPED items can be restored")
    # Tier 11: fiscal headroom on the envelope delta.
    surviving = [i for i in project_items(rec)
                 if i["status"] == "INCLUDED" and i["id"] not in drop_ids]
    restored = [STORES["scope_items"][iid] for iid in restore_ids]
    new_est = sum(i["midpoint_cents"] for i in surviving + restored)
    new_est += sum(midpoint_cents(c["est_low_cents"], c["est_high_cents"])
                   for c in cleaned_adds)
    new_envelope = envelope_for(new_est)
    delta = new_envelope - rec["envelope_cents"]
    cycle = STORES["funding_cycles"].get(rec["funding_cycle_id"])
    available = cycle_ledger(cycle)["available_cents"]
    if delta > available:
        raise_err(E_ENVELOPE_EXCEEDED, 402,
                  "envelope delta exceeds the cycle's available funding")
    # All checks passed: apply atomically.
    for iid in drop_ids:
        STORES["scope_items"][iid]["status"] = "DROPPED"
    for iid in restore_ids:
        STORES["scope_items"][iid]["status"] = "INCLUDED"
    for c in cleaned_adds:
        create_scope_item(rec["_assessment_id"], c)
    rec["envelope_cents"] = new_envelope
    rec["provisional_estimate_cents"] = new_est
    rec["reserved_balance_cents"] = rec["reserved_balance_cents"] + delta
    sync_posture(rec, touch=False)
    bump(rec)
    return ok_obj(ser_project(rec), 201)
