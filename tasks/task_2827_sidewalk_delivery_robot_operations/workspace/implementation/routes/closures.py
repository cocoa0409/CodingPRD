"""Segment closures and the five-link reroute cascade."""

from flask import Blueprint

import calc
import cascades
from common import must, serve_list
from db import bump, create_row, db, now_iso, parse_ts, public
from errors import ApiError, bad
from middleware import (
    arg_enum,
    arg_str,
    authorize,
    body,
    check_enum,
    check_timestamp,
    pagination,
)
from response import object_response

bp = Blueprint("closures", __name__)

READ_ROLES = ("PlatformAdmin", "FleetDispatcher", "RemoteOperator", "SafetyOfficer")
CLOSURE_KINDS = ("HARD", "ADVISORY")
CLOSURE_CAUSES = ("CONSTRUCTION", "WEATHER", "EVENT", "VANDALISM")
CLOSURE_STATES = ("SCHEDULED", "ACTIVE", "LIFTED")
CLOSURE_ACTIONS = ("ACTIVATE", "LIFT")


@bp.get("/segment-closures")
def list_closures():
    authorize(READ_ROLES)
    limit, offset = pagination()
    segment_id = arg_str("segment_id")
    state = arg_enum("state", CLOSURE_STATES)
    closure_kind = arg_enum("closure_kind", CLOSURE_KINDS)
    cause = arg_enum("cause", CLOSURE_CAUSES)
    rows = []
    for closure in db.closures.values():
        if segment_id is not None and closure["segment_id"] != segment_id:
            continue
        if state is not None and closure["state"] != state:
            continue
        if closure_kind is not None and closure["closure_kind"] != closure_kind:
            continue
        if cause is not None and closure["cause"] != cause:
            continue
        rows.append(closure)
    return serve_list(rows, limit, offset)


@bp.get("/segment-closures/<closure_id>")
def get_closure(closure_id):
    authorize(READ_ROLES)
    return object_response(public(must("closures", closure_id)))


@bp.post("/segment-closures")
def create_closure():
    authorize(("PlatformAdmin",))
    payload = body()
    for name in ("segment_id", "closure_kind", "cause", "starts_at_utc", "ends_at_utc"):
        if name not in payload or payload[name] is None:
            raise bad("Field '%s' is required." % name)
    closure_kind = check_enum(payload, "closure_kind", CLOSURE_KINDS)
    cause = check_enum(payload, "cause", CLOSURE_CAUSES)
    segment_id = payload["segment_id"]
    if not isinstance(segment_id, str) or segment_id == "":
        raise bad("Field 'segment_id' must be a non-empty string identifier.")
    starts_at = check_timestamp(payload, "starts_at_utc")
    ends_at = check_timestamp(payload, "ends_at_utc")
    if parse_ts(ends_at) <= parse_ts(starts_at):
        raise bad("Field 'ends_at_utc' must be strictly after 'starts_at_utc'.")

    segment = must("segments", segment_id)

    if closure_kind == "HARD":
        new_start = parse_ts(starts_at)
        new_end = parse_ts(ends_at)
        for existing in db.closures.values():
            if existing["segment_id"] != segment["id"]:
                continue
            if existing["closure_kind"] != "HARD":
                continue
            if existing["state"] not in ("SCHEDULED", "ACTIVE"):
                continue
            if new_start <= parse_ts(existing["ends_at_utc"]) and new_end >= parse_ts(
                existing["starts_at_utc"]
            ):
                raise ApiError("ERR_HARD_CLOSURE_OVERLAP")

    closure = create_row(
        db.closures,
        {
            "segment_id": segment["id"],
            "closure_kind": closure_kind,
            "cause": cause,
            "starts_at_utc": starts_at,
            "ends_at_utc": ends_at,
            "state": "SCHEDULED",
            "reroute_triggered_count": 0,
        },
    )
    return object_response(public(closure), 201)


def _activate_cascade(closure):
    """The five links, in fixed order."""
    # link 1
    closure["state"] = "ACTIVE"
    bump(closure)
    if closure["closure_kind"] != "HARD":
        return

    segment = db.segments.get(closure["segment_id"])
    if segment is None or segment["status"] != "APPROVED":
        return

    # link 2
    segment["status"] = "BLOCKED"
    segment["blocked_by_closure_id"] = closure["id"]
    bump(segment)

    # link 3
    plans = cascades.by_created(
        [
            p
            for p in db.plans.values()
            if p["plan_state"] == "ACTIVE" and segment["id"] in p["segment_sequence"]
        ]
    )
    for plan in plans:
        plan["plan_state"] = "SUPERSEDED"
        plan["rejection_reason"] = "SEGMENT_BLOCKED"
        bump(plan)
        closure["reroute_triggered_count"] += 1

        # link 4
        mission = db.missions.get(plan["mission_id"])
        if mission is None or mission["mission_state"] != "EN_ROUTE":
            continue
        mission["mission_state"] = "BLOCKED"
        mission["blocking_segment_id"] = segment["id"]
        mission["blocked_at_utc"] = now_iso()
        mission["active_route_plan_id"] = None
        bump(mission)

        # link 5
        order = db.orders.get(mission["order_id"])
        if order is None or order["order_state"] != "IN_TRANSIT":
            continue
        cascades.order_to_exception(order, calc.CLOSURE_CAUSE_MAP[closure["cause"]])


@bp.post("/segment-closures/<closure_id>/transitions")
def closure_transition(closure_id):
    authorize(("PlatformAdmin",))
    payload = body()
    action = check_enum(payload, "action", CLOSURE_ACTIONS)
    closure = must("closures", closure_id)

    if action == "ACTIVATE":
        if closure["state"] != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        current = parse_ts(now_iso())
        if not (
            parse_ts(closure["starts_at_utc"]) <= current <= parse_ts(closure["ends_at_utc"])
        ):
            raise ApiError(
                "ERR_INVALID_STATE_TRANSITION",
                "The logical clock is outside the closure interval.",
            )
        _activate_cascade(closure)
    else:  # LIFT
        if closure["state"] == "ACTIVE":
            closure["state"] = "LIFTED"
            bump(closure)
            if closure["closure_kind"] == "HARD":
                segment = db.segments.get(closure["segment_id"])
                if segment is not None:
                    other = any(
                        c["segment_id"] == segment["id"]
                        and c["closure_kind"] == "HARD"
                        and c["state"] == "ACTIVE"
                        and c["id"] != closure["id"]
                        for c in db.closures.values()
                    )
                    if not other and segment["status"] == "BLOCKED":
                        segment["status"] = "APPROVED"
                        segment["blocked_by_closure_id"] = None
                        bump(segment)
        elif closure["state"] == "SCHEDULED":
            closure["state"] = "LIFTED"
            bump(closure)
        else:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")

    return object_response(public(closure))
