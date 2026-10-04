"""Timetable endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_date,
    f_hhmm,
    f_int,
    f_str,
    forbid_unless_owner_host,
    new_row,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)
import svc

bp = Blueprint("timetables", __name__, url_prefix="/rail/timetables")


@bp.post("")
@endpoint("PassengerOperator")
def create_timetable():
    payload = body()
    corridor_id = f_str(payload, "corridor_id")
    operating_agreement_id = f_str(payload, "operating_agreement_id")
    service_date_start = f_date(payload, "service_date_start")
    service_date_end = f_date(payload, "service_date_end")
    trains_per_day = f_int(payload, "trains_per_day", minimum=1)
    departure_time_of_day = f_hhmm(payload, "departure_time_of_day")
    headway_minutes = f_int(payload, "headway_minutes", minimum=0)
    svc.need_corridor(corridor_id)
    agreement = svc.need_agreement(operating_agreement_id)
    # Referential integrity: corridor must match agreement's corridor
    if agreement["corridor_id"] != corridor_id:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            "Timetable corridor does not match agreement corridor.",
        )
    if service_date_end < service_date_start:
        raise ApiError(
            "ERR_VALIDATION", "service_date_end must be on or after service_date_start."
        )
    row = new_row(
        "timetable",
        corridor_id=corridor_id,
        operating_agreement_id=operating_agreement_id,
        service_date_start=service_date_start,
        service_date_end=service_date_end,
        trains_per_day=trains_per_day,
        departure_time_of_day=departure_time_of_day,
        headway_minutes=headway_minutes,
        status="DRAFT",
        revision_no=0,
    )
    db.timetables[row["id"]] = row
    return respond_object(dump(_serialize_timetable(row)), status=201)


def _serialize_timetable(row):
    """Emit departure_time_of_day as HH:MM and dates as YYYY-MM-DD."""
    out = dict(row)
    h, m = out["departure_time_of_day"]
    out["departure_time_of_day"] = "%02d:%02d" % (h, m)
    out["service_date_start"] = out["service_date_start"].isoformat()
    out["service_date_end"] = out["service_date_end"].isoformat()
    return out


@bp.get("")
@endpoint()
def list_timetables():
    rows = list(db.timetables.values())
    corridor_id = q_str("corridor_id")
    operating_agreement_id = q_str("operating_agreement_id")
    status = q_enum("status", svc.TIMETABLE_STATUSES)
    if corridor_id is not None:
        rows = [r for r in rows if r["corridor_id"] == corridor_id]
    if operating_agreement_id is not None:
        rows = [r for r in rows if r["operating_agreement_id"] == operating_agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_created(rows)
    return paginate(rows, dumper=lambda r: dump(_serialize_timetable(r)))


@bp.get("/<rid>")
@endpoint()
def get_timetable(rid):
    row = svc.need_timetable(rid)
    return respond_object(dump(_serialize_timetable(row)))


@bp.post("/<rid>/propose")
@endpoint("PassengerOperator")
def propose_timetable(rid):
    row = svc.need_timetable(rid)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Timetable is not DRAFT.")
    agreement = svc.need_agreement(row["operating_agreement_id"])
    segments = svc.corridor_segments(row["corridor_id"])
    svc.check_schedule_feasibility(row, segments, agreement)
    row["status"] = "PROPOSED"
    touch(row)
    return respond_object(dump(_serialize_timetable(row)))


@bp.post("/<rid>/review")
@endpoint("HostRailroadRep")
def review_timetable(rid):
    row = svc.need_timetable(rid)
    forbid_unless_owner_host(svc.host_for_timetable(row))
    if row["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Timetable is not PROPOSED.")
    row["status"] = "UNDER_REVIEW"
    touch(row)
    return respond_object(dump(_serialize_timetable(row)))


@bp.post("/<rid>/revise")
@endpoint("PassengerOperator")
def revise_timetable(rid):
    row = svc.need_timetable(rid)
    if row["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Timetable is not UNDER_REVIEW.")
    row["status"] = "PROPOSED"
    row["revision_no"] += 1
    touch(row)
    return respond_object(dump(_serialize_timetable(row)))


@bp.post("/<rid>/ratify")
@endpoint("HostRailroadRep")
def ratify_timetable(rid):
    row = svc.need_timetable(rid)
    forbid_unless_owner_host(svc.host_for_timetable(row))
    if row["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Timetable is not UNDER_REVIEW.")
    agreement = svc.need_agreement(row["operating_agreement_id"])
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Operating agreement is not ACTIVE.")
    row["status"] = "RATIFIED"
    touch(row)
    return respond_object(dump(_serialize_timetable(row)))


@bp.post("/<rid>/publish")
@endpoint("PassengerOperator")
def publish_timetable(rid):
    row = svc.need_timetable(rid)
    if row["status"] != "RATIFIED":
        raise ApiError("ERR_INVALID_STATE", "Timetable is not RATIFIED.")
    agreement = svc.need_agreement(row["operating_agreement_id"])
    segments = svc.corridor_segments(row["corridor_id"])
    svc.check_publish_guards(row, segments, agreement)
    # Materialize
    svc.materialize_runs(row, segments, agreement)
    row["status"] = "PUBLISHED"
    touch(row)
    # Supersede other PUBLISHED timetables on the same corridor with overlapping
    # service dates.
    for other in db.timetables.values():
        if other["id"] == row["id"]:
            continue
        if other["corridor_id"] != row["corridor_id"]:
            continue
        if other["status"] != "PUBLISHED":
            continue
        # Overlap of [start, end] inclusive
        if not (
            other["service_date_end"] < row["service_date_start"]
            or other["service_date_start"] > row["service_date_end"]
        ):
            other["status"] = "SUPERSEDED"
            touch(other)
    return respond_object(dump(_serialize_timetable(row)))
