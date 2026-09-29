"""On-site support providers and the services they deliver (PRD 3.7)."""
from flask import Blueprint

import derive
import validate as v
from auth import endpoint, scope_center, scope_provider
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import eq, get_center, get_placement, get_provider, get_support_session, q
from store import new_row, ordered, store, touch

bp = Blueprint("support", __name__)

ROLE_TYPES = ("COUNSELOR", "SOCIAL_WORKER", "BEHAVIOR_SPECIALIST")
SERVICE_CODES = ("ACADEMIC_COUNSELING", "BEHAVIOR_COACHING", "SOCIAL_WORK",
                 "RE_ENGAGEMENT_CHECKIN")


# --------------------------------------------------------------- providers
@bp.post("/support-providers")
@endpoint("DistrictAdmin")
def create_provider(ctx):
    b = v.body()
    center_id = v.req_str(b, "center_id", 1, None)
    role_type = v.req_enum(b, "role_type", ROLE_TYPES)
    full_name = v.req_str(b, "full_name", 1, 120)
    cap = v.opt_int(b, "max_concurrent_students", lo=1, hi=8, default=4)
    get_center(center_id)
    row = new_row(center_id=center_id, role_type=role_type, full_name=full_name,
                  max_concurrent_students=cap)
    store.providers[row["id"]] = row
    return created(derive.ser_provider(row))


@bp.get("/support-providers/<support_provider_id>")
@endpoint("DistrictAdmin", "PlacementCoordinator", "SupportProviderStaff")
def read_provider(ctx, support_provider_id):
    row = get_provider(support_provider_id)
    scope_center(ctx, row["center_id"])
    scope_provider(ctx, row["id"])
    return ok(derive.ser_provider(row))


@bp.get("/support-providers")
@endpoint("DistrictAdmin", "PlacementCoordinator")
def list_providers(ctx):
    rows = ordered(store.providers.values())
    if ctx.role == "PlacementCoordinator":
        rows = [r for r in rows if r["center_id"] == ctx.uid]
    rows = eq(rows, "center_id", q("center_id"))
    rows = eq(rows, "role_type", q("role_type"))
    return ok_list(rows, derive.ser_provider)


# ---------------------------------------------------------------- sessions
@bp.post("/support-sessions")
@endpoint("PlacementCoordinator", "SupportProviderStaff")
def create_support_session(ctx):
    b = v.body()
    provider_id = v.req_str(b, "support_provider_id", 1, None)
    placement_id = v.req_str(b, "placement_id", 1, None)
    start = v.req_dt(b, "start_at")
    end = v.req_dt(b, "end_at")
    service_code = v.req_enum(b, "service_code", SERVICE_CODES)
    provider = get_provider(provider_id)
    placement = get_placement(placement_id)
    scope_provider(ctx, provider_id)
    scope_center(ctx, placement["center_id"])
    if end <= start:
        raise ApiError("ERR_INVALID_INTERVAL", "end_at must be later than start_at")
    if provider["center_id"] != placement["center_id"]:
        raise ApiError("ERR_PROVIDER_CENTER_MISMATCH",
                       "the provider serves another center")
    overlapping = 0
    for other in store.support_sessions.values():
        if other["support_provider_id"] != provider_id:
            continue
        if other["status"] not in derive.OCCUPYING_SESSION_STATES:
            continue
        if other.get("_released"):
            continue
        # closed-interval intersection: touching endpoints intersect
        if start <= other["end_at"] and end >= other["start_at"]:
            overlapping += 1
    if overlapping + 1 > provider["max_concurrent_students"]:
        raise ApiError("ERR_PROVIDER_CAPACITY_EXCEEDED",
                       "the provider's concurrent caseload cap is reached")
    row = new_row(support_provider_id=provider_id, placement_id=placement_id,
                  start_at=start, end_at=end, service_code=service_code,
                  status="SCHEDULED", minutes_delivered=None, completion_note=None)
    store.support_sessions[row["id"]] = row
    return created(derive.ser_support_session(row))


@bp.get("/support-sessions/<support_session_id>")
@endpoint("PlacementCoordinator", "SupportProviderStaff", "DistrictAdmin")
def read_support_session(ctx, support_session_id):
    row = get_support_session(support_session_id)
    scope_center(ctx, store.placements[row["placement_id"]]["center_id"])
    scope_provider(ctx, row["support_provider_id"])
    return ok(derive.ser_support_session(row))


@bp.get("/support-sessions")
@endpoint("PlacementCoordinator", "SupportProviderStaff", "DistrictAdmin")
def list_support_sessions(ctx):
    rows = ordered(store.support_sessions.values())
    if ctx.role == "PlacementCoordinator":
        rows = [r for r in rows
                if store.placements[r["placement_id"]]["center_id"] == ctx.uid]
    elif ctx.role == "SupportProviderStaff":
        rows = [r for r in rows if r["support_provider_id"] == ctx.uid]
    rows = eq(rows, "support_provider_id", q("support_provider_id"))
    rows = eq(rows, "placement_id", q("placement_id"))
    rows = eq(rows, "status", q("status"))
    return ok_list(rows, derive.ser_support_session)


@bp.post("/support-sessions/<support_session_id>/complete")
@endpoint("SupportProviderStaff")
def complete_support_session(ctx, support_session_id):
    session = get_support_session(support_session_id)
    scope_provider(ctx, session["support_provider_id"])
    b = v.body()
    minutes = v.req_int(b, "minutes_delivered", lo=1, hi=480)
    note = v.opt_str(b, "completion_note", 1, None)
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SUPPORT_SESSION_STATE_INVALID",
                       "only a SCHEDULED support session may be completed")
    session["status"] = "COMPLETED"
    session["minutes_delivered"] = minutes
    if note is not None:
        session["completion_note"] = note
    touch(session)
    return ok(derive.ser_support_session(session))
