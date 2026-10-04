"""FeeAssignment routes: propose (OCC), get, list, accept, reject, cancel."""
from flask import Blueprint, request

from auth import require_roles, ALL_ROLES
from store import db
from response import ok, ok_list, ApiError, err_not_found, err_invalid_request, err_forbidden
from helpers import new_record, touch, paginate, sort_by_created, recompute_trust
from clock import now, fmt, parse
import views

bp = Blueprint("fee_assignments", __name__)


def get_agent_or_404(agent_id):
    a = db["agents"].get(agent_id)
    if not a:
        raise err_not_found("Agent not found")
    return a


def get_assignment_or_404(aid):
    fa = db["fee_assignments"].get(aid)
    if not fa:
        raise err_not_found("FeeAssignment not found")
    return fa


@bp.route("/agents/<agentId>/fee-assignments", methods=["POST"])
def propose_assignment(agentId):
    require_roles("ManagingBroker")
    a = get_agent_or_404(agentId)
    body = request.get_json(silent=True) or {}
    schedule_id = body.get("fee_schedule_id")
    ef_s = body.get("effective_from")
    et_s = body.get("effective_to")
    expected = body.get("expected_agent_version")
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_agent_version is required")
    if expected != a["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Agent version has advanced")
    ef, et = parse(ef_s), parse(et_s)
    if ef is None or et is None:
        raise err_invalid_request("effective_from and effective_to must be ISO-8601 timestamps")
    if et <= ef:
        raise err_invalid_request("effective_to must be after effective_from")
    # referential integrity: schedule exists and its window covers the assignment
    s = db["fee_schedules"].get(schedule_id)
    if not s:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "fee_schedule_id does not resolve")
    sef, seto = parse(s["effective_from"]), parse(s["effective_to"])
    if not (sef <= ef and et <= seto):
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422,
                       "Schedule window does not cover the assignment window")
    # overlap check against non-terminal assignments for the same agent
    for other in db["fee_assignments"].values():
        if other["agent_id"] != a["id"] or other["status"] in ("REJECTED", "CANCELLED", "SUPERSEDED"):
            continue
        oef, oet = parse(other["effective_from"]), parse(other["effective_to"])
        if ef < oet and oef < et:
            raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                           "Assignment window overlaps another assignment")
    # supersede any prior PROPOSED assignment
    for other in db["fee_assignments"].values():
        if other["agent_id"] == a["id"] and other["status"] == "PROPOSED":
            other["status"] = "SUPERSEDED"
            touch(other)
    rec = new_record()
    rec.update({
        "agent_id": a["id"],
        "fee_schedule_id": schedule_id,
        "effective_from": ef_s,
        "effective_to": et_s,
        "expected_agent_version": expected,
        "status": "PROPOSED",
    })
    db["fee_assignments"][rec["id"]] = rec
    touch(a)  # parent agent version advances on proposal
    return ok(views.assignment_view(rec), 201)


@bp.route("/fee-assignments/<assignmentId>", methods=["GET"])
def get_assignment(assignmentId):
    require_roles(*ALL_ROLES)
    fa = get_assignment_or_404(assignmentId)
    return ok(views.assignment_view(fa))


@bp.route("/agents/<agentId>/fee-assignments", methods=["GET"])
def list_agent_assignments(agentId):
    require_roles(*ALL_ROLES)
    get_agent_or_404(agentId)
    items = [fa for fa in db["fee_assignments"].values() if fa["agent_id"] == agentId]
    args = request.args
    if args.get("status") is not None:
        items = [f for f in items if f["status"] == args.get("status")]
    if args.get("agent_id") is not None:
        items = [f for f in items if f["agent_id"] == args.get("agent_id")]
    if args.get("fee_schedule_id") is not None:
        items = [f for f in items if f["fee_schedule_id"] == args.get("fee_schedule_id")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.assignment_view(f) for f in page], total, limit, offset)


@bp.route("/fee-assignments", methods=["GET"])
def list_assignments():
    require_roles(*ALL_ROLES)
    items = list(db["fee_assignments"].values())
    args = request.args
    if args.get("agent_id") is not None:
        items = [f for f in items if f["agent_id"] == args.get("agent_id")]
    if args.get("fee_schedule_id") is not None:
        items = [f for f in items if f["fee_schedule_id"] == args.get("fee_schedule_id")]
    if args.get("status") is not None:
        items = [f for f in items if f["status"] == args.get("status")]
    items = sort_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([views.assignment_view(f) for f in page], total, limit, offset)


@bp.route("/fee-assignments/<assignmentId>/accept", methods=["POST"])
def accept_assignment(assignmentId):
    uid, _role = require_roles("Agent")
    fa = get_assignment_or_404(assignmentId)
    a = db["agents"].get(fa["agent_id"])
    if uid != fa["agent_id"]:
        raise err_forbidden("Agents may only accept their own assignments")
    if fa["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not PROPOSED")
    s = db["fee_schedules"].get(fa["fee_schedule_id"])
    n = now()
    fa_ef = parse(fa["effective_from"])
    if s:
        sef, seto = parse(s["effective_from"]), parse(s["effective_to"])
        if not (sef <= fa_ef < seto and sef <= n < seto):
            raise ApiError("ERR_SCHEDULE_WINDOW_VIOLATION", 409,
                           "Schedule window does not cover the assignment start and clock")
    first_accepted = not any(
        x for x in db["fee_assignments"].values()
        if x["agent_id"] == fa["agent_id"] and x["status"] == "ACCEPTED"
    )
    fa["status"] = "ACCEPTED"
    touch(fa)
    if a:
        if first_accepted and a["status"] == "PENDING_ONBOARDING":
            a["status"] = "ACTIVE"
            a["onboarded_at"] = fmt(n)
            office = db["offices"].get(a["office_id"])
            if office:
                office["active_agent_count"] = sum(
                    1 for x in db["agents"].values()
                    if x["office_id"] == office["id"] and x["status"] == "ACTIVE"
                )
        touch(a)
    return ok(views.assignment_view(fa))


@bp.route("/fee-assignments/<assignmentId>/reject", methods=["POST"])
def reject_assignment(assignmentId):
    uid, _role = require_roles("Agent")
    fa = get_assignment_or_404(assignmentId)
    if uid != fa["agent_id"]:
        raise err_forbidden("Agents may only reject their own assignments")
    if fa["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not PROPOSED")
    fa["status"] = "REJECTED"
    touch(fa)
    return ok(views.assignment_view(fa))


@bp.route("/fee-assignments/<assignmentId>/cancel", methods=["POST"])
def cancel_assignment(assignmentId):
    require_roles("ManagingBroker")
    fa = get_assignment_or_404(assignmentId)
    if fa["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Assignment is not PROPOSED")
    fa["status"] = "CANCELLED"
    touch(fa)
    return ok(views.assignment_view(fa))
