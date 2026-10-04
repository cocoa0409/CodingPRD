"""Remote support monitoring windows — PRD §2.7, §3.9, endpoints 96-101."""

from decimal import Decimal

import db
import core
import services
import calculations as calc
from core import ApiError, D, now_iso, parse_iso, to_iso
from response import ok, page_of
from http_util import pagination, must_get, must_resolve, get_or_none, body, coerce_int, arg
from routes._common import route
from models import create

GEOFENCE_TYPES = ("GEOFENCE_ONLY", "GEOFENCE_PLUS_BUFFER")
PROTOCOLS = ("MONITOR_ONLY", "VOICE_ADVISORY", "STANDBY_TAKEOVER", "REMOTE_DISENGAGE")


def register(app):

    @route(app, "/api/remote-support-assignments", ["POST"], ["RemoteSupportSupervisor"])
    def create_assignment():
        """§3.9: the same person may not fill both seats; both operator identifiers
        name DriverProspect rows."""
        raw = body()
        allowed = {"corridor_id", "run_plan_id", "monitoring_start_at",
                   "monitoring_end_at", "remote_operator_id",
                   "safety_support_operator_id", "geofence_type",
                   "intervention_protocol"}
        for key in raw:
            if key not in allowed:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        for key in allowed:
            if key not in raw:
                raise ApiError("ERR_INVALID_REQUEST",
                               "Required field '%s' is missing." % key)
        corridor = get_or_none("Corridor", raw["corridor_id"])
        if corridor is None:
            raise ApiError("ERR_CORRIDOR_NOT_FOUND")
        run = get_or_none("RunPlan", raw["run_plan_id"])
        if run is None:
            raise ApiError("ERR_RUN_PLAN_NOT_FOUND")
        remote_op = must_resolve("DriverProspect", raw["remote_operator_id"])
        support_op = must_resolve("DriverProspect", raw["safety_support_operator_id"])
        start = parse_iso(raw["monitoring_start_at"])
        end = parse_iso(raw["monitoring_end_at"])
        if start is None or end is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "monitoring instants must be ISO 8601 UTC.")
        if not end > start:
            raise ApiError("ERR_INVALID_REQUEST",
                           "monitoring_end_at must be strictly after monitoring_start_at.")
        if raw["geofence_type"] not in GEOFENCE_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown geofence_type.")
        if raw["intervention_protocol"] not in PROTOCOLS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown intervention_protocol.")

        # Priority 38 — the remote operator and the safety support operator on one
        # monitoring window must be different people.
        if remote_op["id"] == support_op["id"]:
            raise ApiError("ERR_DUPLICATE_OPERATOR",
                           "The same operator cannot fill both seats.")

        # Priority 23 — the overlap screen runs against the same operator's other
        # active windows on the same corridor in either seat and in either direction.
        interval = _interval(raw["geofence_type"], start, end)
        if calc.monitoring_overlaps(corridor["id"],
                                    [remote_op["id"], support_op["id"]],
                                    interval):
            raise ApiError("ERR_MONITOR_OVERLAP",
                           "The monitoring window collides with another active window.")

        row = create("RemoteSupportAssignment", {
            "corridor_id": corridor["id"],
            "run_plan_id": run["id"],
            "monitoring_start_at": to_iso(start),
            "monitoring_end_at": to_iso(end),
            "remote_operator_id": remote_op["id"],
            "safety_support_operator_id": support_op["id"],
            "geofence_type": raw["geofence_type"],
            "intervention_protocol": raw["intervention_protocol"],
        })
        row["assignment_status"] = "SCHEDULED"
        row["intervention_count"] = 0
        row["safe_stop_required"] = False
        row["closure_source"] = None
        row["safe_stop_fee_cents"] = D(0)
        return ok(row, 201)

    @route(app, "/api/remote-support-assignments", ["GET"], ["Any"])
    def list_assignments():
        limit, offset = pagination()
        rows = db.all_rows("remote_support_assignments")
        for field in ("corridor_id", "run_plan_id", "remote_operator_id"):
            value = arg(field)
            if value:
                rows = [a for a in rows if a.get(field) == value]
        return page_of(db.sort_created(rows), limit, offset)

    @route(app, "/api/remote-support-assignments/<rid>", ["GET"], ["Any"])
    def get_assignment(rid):
        assignment = must_get("RemoteSupportAssignment", rid)
        return ok(assignment)

    @route(app, "/api/remote-support-assignments/<rid>/acknowledge", ["POST"],
           ["RemoteSupportOperator"])
    def acknowledge(rid):
        """§3.9: acknowledging moves the window to MONITORING and sets
        closure_source to REPOSITIONED_ACKNOWLEDGED.  The overlap screen is
        evaluated here as well."""
        assignment = must_get("RemoteSupportAssignment", rid)
        raw = body()
        _reject_unknown(raw)
        if assignment.get("assignment_status") != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", "Only a scheduled window can be acknowledged.")
        uid = _uid()
        if uid not in (assignment.get("remote_operator_id"),
                       assignment.get("safety_support_operator_id")):
            raise ApiError("ERR_UNAUTHORIZED",
                           "The monitoring window is held by another operator.")
        start = parse_iso(assignment.get("monitoring_start_at"))
        end = parse_iso(assignment.get("monitoring_end_at"))
        interval = _interval(assignment.get("geofence_type"), start, end)
        if calc.monitoring_overlaps(assignment.get("corridor_id"),
                                    [assignment.get("remote_operator_id"),
                                     assignment.get("safety_support_operator_id")],
                                    interval, exclude_id=rid):
            raise ApiError("ERR_MONITOR_OVERLAP",
                           "The monitoring window collides with another active window.")
        services.mark(assignment, "assignment_status", "MONITORING")
        services.mark(assignment, "closure_source", "REPOSITIONED_ACKNOWLEDGED")
        services.flush(assignment)
        return ok(assignment)

    @route(app, "/api/remote-support-assignments/<rid>/release", ["POST"],
           ["RemoteSupportSupervisor"])
    def release(rid):
        assignment = must_get("RemoteSupportAssignment", rid)
        raw = body()
        _reject_unknown(raw)
        if assignment.get("assignment_status") not in ("SCHEDULED", "MONITORING"):
            raise ApiError("ERR_INVALID_STATE", "The window is already closed.")
        services.mark(assignment, "assignment_status", "RELEASED")
        services.mark(assignment, "closure_source", "RELEASED")
        services.flush(assignment)
        return ok(assignment)

    @route(app, "/api/remote-support-assignments/<rid>/interventions", ["POST"],
           ["RemoteSupportOperator"])
    def interventions(rid):
        """§3.9: each intervention increments intervention_count and refreshes
        intervention_protocol."""
        assignment = must_get("RemoteSupportAssignment", rid)
        raw = body()
        for key in raw:
            if key != "intervention_protocol":
                raise ApiError("ERR_INVALID_REQUEST",
                               "Field '%s' is not declared for this endpoint." % key)
        if "intervention_protocol" not in raw:
            raise ApiError("ERR_INVALID_REQUEST",
                           "intervention_protocol is required.")
        if raw["intervention_protocol"] not in PROTOCOLS:
            raise ApiError("ERR_INVALID_REQUEST", "Unknown intervention_protocol.")
        if assignment.get("assignment_status") != "MONITORING":
            raise ApiError("ERR_INVALID_STATE",
                           "Interventions can only be logged on a MONITORING window.")
        uid = _uid()
        if uid not in (assignment.get("remote_operator_id"),
                       assignment.get("safety_support_operator_id")):
            raise ApiError("ERR_UNAUTHORIZED",
                           "The monitoring window is held by another operator.")
        services.mark(assignment, "intervention_count",
                      int(assignment.get("intervention_count") or 0) + 1)
        services.mark(assignment, "intervention_protocol", raw["intervention_protocol"])
        services.flush(assignment)
        return ok(assignment)


def _interval(geofence_type, start, end):
    """§2.7: under GEOFENCE_PLUS_BUFFER the interval is first expanded
    multiplicatively by 1.5 before screening, so a monitoring window that clears
    under the exact test can still be rejected under the buffered one."""
    if start is None or end is None:
        return (None, None)
    if geofence_type == "GEOFENCE_PLUS_BUFFER":
        span = (end - start) * 1.5 / 2
        return (start - span, end + span)
    return (start, end)


def _fee(assignment):
    corridor = db.get("corridors", assignment.get("corridor_id"))
    run = db.get("run_plans", assignment.get("run_plan_id"))
    carrier = services.carrier_of_run(run) if run else None
    if corridor is None or run is None or carrier is None:
        return D(0)
    fee, _exposure = calc.safe_stop_fee(corridor, run, carrier)
    return fee


def _uid():
    from http_util import actor_id
    return actor_id()


def _reject_unknown(raw):
    for key in raw:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field '%s' is not declared for this endpoint." % key)