"""TrainRun and SegmentPassage endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_str,
    forbid_unless_owner_host,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)
import svc

bp = Blueprint("runs", __name__, url_prefix="/rail")


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------
def _serialize_run(row):
    out = dict(row)
    return out


# ---------------------------------------------------------------------------
# TrainRun endpoints
# ---------------------------------------------------------------------------
@bp.get("/train-runs")
@endpoint()
def list_train_runs():
    rows = list(db.train_runs.values())
    timetable_id = q_str("timetable_id")
    service_date = q_str("service_date")
    status = q_enum("status", svc.RUN_STATUSES)
    if timetable_id is not None:
        rows = [r for r in rows if r["timetable_id"] == timetable_id]
    if service_date is not None:
        rows = [r for r in rows if r["service_date"] == service_date]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # sorted by scheduled_departure_at ASC then created_at ASC
    rows.sort(key=lambda r: (r["scheduled_departure_at"], r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.get("/train-runs/<rid>")
@endpoint()
def get_train_run(rid):
    row = svc.need_run(rid)
    return respond_object(dump(row))


@bp.post("/train-runs/<rid>/depart")
@endpoint("HostRailroadRep")
def depart_run(rid):
    payload = body()
    actual_departure_at = f_dt(payload, "actual_departure_at")
    row = svc.need_run(rid)
    forbid_unless_owner_host(svc.host_for_run(row))
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Run is not SCHEDULED.")
    row["actual_departure_at"] = actual_departure_at
    row["origin_departure_delay_minutes"] = svc._delay_minutes(
        actual_departure_at, row["scheduled_departure_at"]
    )
    row["status"] = "EN_ROUTE"
    touch(row)
    return respond_object(dump(row))


@bp.post("/train-runs/<rid>/complete")
@endpoint("HostRailroadRep")
def complete_run(rid):
    payload = body()
    actual_arrival_at = f_dt(payload, "actual_arrival_at")
    row = svc.need_run(rid)
    forbid_unless_owner_host(svc.host_for_run(row))
    if row["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", "Run is not EN_ROUTE.")
    # All passages must be final
    passages = [p for p in db.segment_passages.values() if p["train_run_id"] == row["id"]]
    if any(p["status"] == "PLANNED" for p in passages):
        raise ApiError(
            "ERR_RUN_PASSAGES_OPEN",
            "TrainRun has passages still in PLANNED status.",
        )
    row["actual_arrival_at"] = actual_arrival_at
    dest_delay = svc._delay_minutes(actual_arrival_at, row["scheduled_arrival_at"])
    row["destination_arrival_delay_minutes"] = dest_delay
    # Threshold from agreement
    agreement = svc.agreement_for_run(row)
    threshold = agreement["on_time_threshold_minutes"] if agreement else 0
    row["on_time_endpoint"] = dest_delay <= threshold
    # all-stations: every ACTUALIZED passage exit delay <= threshold
    on_time_all = row["on_time_endpoint"]
    if on_time_all:
        for p in passages:
            if p["status"] != "ACTUALIZED":
                continue
            exit_delay = svc._delay_minutes(p["actual_exit_at"], p["planned_exit_at"])
            if exit_delay > threshold:
                on_time_all = False
                break
    row["on_time_all_stations"] = on_time_all
    row["status"] = "COMPLETED"
    touch(row)
    return respond_object(dump(row))


@bp.post("/train-runs/<rid>/cancel")
@endpoint("PassengerOperator")
def cancel_run(rid):
    body()  # optional reason
    row = svc.need_run(rid)
    if row["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Run is not SCHEDULED.")
    row["status"] = "CANCELLED"
    row["cancellation_reason"] = "OPERATOR_CANCEL"
    touch(row)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# SegmentPassage endpoints
# ---------------------------------------------------------------------------
@bp.get("/segment-passages")
@endpoint()
def list_passages():
    rows = list(db.segment_passages.values())
    train_run_id = q_str("train_run_id")
    track_segment_id = q_str("track_segment_id")
    status = q_enum("status", svc.PASSAGE_STATUSES)
    if train_run_id is not None:
        rows = [r for r in rows if r["train_run_id"] == train_run_id]
    if track_segment_id is not None:
        rows = [r for r in rows if r["track_segment_id"] == track_segment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # sorted by segment_sequence_no ASC then created_at ASC
    rows.sort(key=lambda r: (r["segment_sequence_no"], r["created_at"], r["_seq"]))
    return paginate(rows)


@bp.get("/segment-passages/<rid>")
@endpoint()
def get_passage(rid):
    row = svc.need_passage(rid)
    return respond_object(dump(row))


@bp.post("/segment-passages/<rid>/actualize")
@endpoint("HostRailroadRep")
def actualize_passage(rid):
    payload = body()
    actual_entry_at = f_dt(payload, "actual_entry_at")
    actual_exit_at = f_dt(payload, "actual_exit_at")
    row = svc.need_passage(rid)
    forbid_unless_owner_host(svc.host_for_passage(row))
    if row["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Passage is not PLANNED.")
    run = svc.need_run(row["train_run_id"])
    if run["status"] != "EN_ROUTE":
        raise ApiError("ERR_INVALID_STATE", "Owning run is not EN_ROUTE.")
    # Maintenance clearance conflict
    locked_windows = [
        w
        for w in db.maintenance_windows.values()
        if w["status"] == "LOCKED" and w["track_segment_id"] == row["track_segment_id"]
    ]
    for w in locked_windows:
        if svc._passage_conflicts_window(actual_entry_at, actual_exit_at, w):
            raise ApiError(
                "ERR_MAINTENANCE_CONFLICT",
                "Occupancy intersects a LOCKED maintenance window.",
            )
    # SINGLE-track actual occupancy conflict
    segment = db.track_segments.get(row["track_segment_id"])
    if segment and segment["track_class"] == "SINGLE":
        for other in db.segment_passages.values():
            if other["id"] == row["id"]:
                continue
            if other["track_segment_id"] != row["track_segment_id"]:
                continue
            if other["status"] != "ACTUALIZED":
                continue
            o_start = other["actual_entry_at"]
            o_end = other["actual_exit_at"]
            if svc._half_open_overlap(actual_entry_at, actual_exit_at, o_start, o_end):
                raise ApiError(
                    "ERR_SEGMENT_OCCUPANCY_CONFLICT",
                    "Actual occupancy overlaps another ACTUALIZED passage on a SINGLE segment.",
                )
    row["actual_entry_at"] = actual_entry_at
    row["actual_exit_at"] = actual_exit_at
    row["status"] = "ACTUALIZED"
    touch(row)
    return respond_object(dump(row))
