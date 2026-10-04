"""Logical clock + HostRailroad + Corridor + TrackSegment endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_int,
    f_num,
    f_str,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
)
import svc

bp = Blueprint("network", __name__, url_prefix="/rail")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint("SystemAdmin")
def set_clock():
    payload = body()
    to_instant = f_dt(payload, "to_iso8601")
    db.clock = to_instant
    svc.agreement_expiry_sweep()
    from core import fmt_dt
    return respond_object({"current_utc": fmt_dt(db.clock)})


# ---------------------------------------------------------------------------
# HostRailroad
# ---------------------------------------------------------------------------
@bp.post("/host-railroads")
@endpoint("SystemAdmin")
def create_host_railroad():
    payload = body()
    name = f_str(payload, "name")
    reporting_mark = f_str(payload, "reporting_mark")
    row = new_row("host_railroad", name=name, reporting_mark=reporting_mark)
    db.host_railroads[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.get("/host-railroads/<rid>")
@endpoint()
def get_host_railroad(rid):
    row = svc.need_host(rid)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Corridor
# ---------------------------------------------------------------------------
@bp.post("/corridors")
@endpoint("SystemAdmin")
def create_corridor():
    payload = body()
    host_railroad_id = f_str(payload, "host_railroad_id")
    code = f_str(payload, "code")
    name = f_str(payload, "name")
    endpoint_a = f_str(payload, "endpoint_a")
    endpoint_b = f_str(payload, "endpoint_b")
    service_type = f_enum(payload, "service_type", svc.SERVICE_TYPES)
    annual_cost_cents = f_int(payload, "annual_cost_cents", minimum=0)
    svc.need_host(host_railroad_id)
    row = new_row(
        "corridor",
        host_railroad_id=host_railroad_id,
        code=code,
        name=name,
        endpoint_a=endpoint_a,
        endpoint_b=endpoint_b,
        service_type=service_type,
        annual_cost_cents=annual_cost_cents,
        status="ACTIVE",
    )
    db.corridors[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.get("/corridors")
@endpoint()
def list_corridors():
    rows = list(db.corridors.values())
    host_railroad_id = q_str("host_railroad_id")
    status = q_enum("status", svc.CORRIDOR_STATUSES)
    if host_railroad_id is not None:
        rows = [r for r in rows if r["host_railroad_id"] == host_railroad_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.get("/corridors/<rid>")
@endpoint()
def get_corridor(rid):
    row = svc.need_corridor(rid)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# TrackSegment
# ---------------------------------------------------------------------------
@bp.post("/track-segments")
@endpoint("SystemAdmin")
def create_track_segment():
    payload = body()
    corridor_id = f_str(payload, "corridor_id")
    sequence_no = f_int(payload, "sequence_no")
    milepost_start = f_num(payload, "milepost_start")
    milepost_end = f_num(payload, "milepost_end")
    state_code = f_str(payload, "state_code")
    track_class = f_enum(payload, "track_class", svc.TRACK_CLASSES)
    capacity_trains_per_day = f_int(payload, "capacity_trains_per_day", minimum=0)
    pure_run_minutes = f_int(payload, "pure_run_minutes", minimum=0)
    dwell_after_minutes = f_int(
        payload, "dwell_after_minutes", required=False, default=0, minimum=0
    )
    if milepost_end <= milepost_start:
        raise ApiError(
            "ERR_VALIDATION", "milepost_end must be greater than milepost_start."
        )
    svc.need_corridor(corridor_id)
    row = new_row(
        "track_segment",
        corridor_id=corridor_id,
        sequence_no=sequence_no,
        milepost_start=float(milepost_start),
        milepost_end=float(milepost_end),
        state_code=state_code,
        track_class=track_class,
        capacity_trains_per_day=capacity_trains_per_day,
        pure_run_minutes=pure_run_minutes,
        dwell_after_minutes=dwell_after_minutes,
        status="OPERABLE",
    )
    db.track_segments[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.get("/track-segments")
@endpoint()
def list_track_segments():
    rows = list(db.track_segments.values())
    corridor_id = q_str("corridor_id")
    state_code = q_str("state_code")
    status = q_enum("status", svc.SEGMENT_STATUSES)
    if corridor_id is not None:
        rows = [r for r in rows if r["corridor_id"] == corridor_id]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # Sort by corridor (created_at seq) then sequence_no asc
    corridor_order = {c["id"]: c["_seq"] for c in db.corridors.values()}
    rows.sort(key=lambda r: (corridor_order.get(r["corridor_id"], 0), r["sequence_no"], r["_seq"]))
    return paginate(rows)


@bp.get("/track-segments/<rid>")
@endpoint()
def get_track_segment(rid):
    row = svc.need_segment(rid)
    return respond_object(dump(row))
