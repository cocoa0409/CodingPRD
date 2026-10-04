"""CapitalProject endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_enum,
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

bp = Blueprint("projects", __name__, url_prefix="/rail/capital-projects")


@bp.post("")
@endpoint("PassengerOperator")
def create_project():
    payload = body()
    operating_agreement_id = f_str(payload, "operating_agreement_id")
    track_segment_id = f_str(payload, "track_segment_id")
    project_type = f_enum(payload, "project_type", svc.PROJECT_TYPES)
    funded_amount_cents = f_int(payload, "funded_amount_cents", minimum=0)
    added_frequency_capacity = f_int(payload, "added_frequency_capacity", minimum=0)
    agreement = svc.need_agreement(operating_agreement_id)
    segment = svc.need_segment(track_segment_id)
    if segment["corridor_id"] != agreement["corridor_id"]:
        raise ApiError(
            "ERR_REFERENTIAL_INTEGRITY",
            "Capital project segment does not belong to the agreement's corridor.",
        )
    row = new_row(
        "capital_project",
        operating_agreement_id=operating_agreement_id,
        track_segment_id=track_segment_id,
        project_type=project_type,
        funded_amount_cents=funded_amount_cents,
        added_frequency_capacity=added_frequency_capacity,
        status="PROPOSED",
    )
    db.capital_projects[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.get("")
@endpoint()
def list_projects():
    rows = list(db.capital_projects.values())
    operating_agreement_id = q_str("operating_agreement_id")
    track_segment_id = q_str("track_segment_id")
    status = q_enum("status", svc.PROJECT_STATUSES)
    if operating_agreement_id is not None:
        rows = [r for r in rows if r["operating_agreement_id"] == operating_agreement_id]
    if track_segment_id is not None:
        rows = [r for r in rows if r["track_segment_id"] == track_segment_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.get("/<rid>")
@endpoint()
def get_project(rid):
    row = svc.need_project(rid)
    return respond_object(dump(row))


@bp.post("/<rid>/approve")
@endpoint("HostRailroadRep")
def approve_project(rid):
    payload = body()
    expected = f_int(payload, "expected_operating_agreement_version")
    row = svc.need_project(rid)
    agreement = svc.need_agreement(row["operating_agreement_id"])
    forbid_unless_owner_host(agreement["host_railroad_id"])
    # OCC (priority 5, before state)
    if expected != agreement["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_operating_agreement_version does not match current version.",
        )
    if row["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Project is not PROPOSED.")
    if agreement["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", "Operating agreement is not ACTIVE.")
    row["status"] = "FUNDED"
    touch(row)
    # Approval pins the agreement terms
    touch(agreement)
    return respond_object(dump(row))


@bp.post("/<rid>/start")
@endpoint("HostRailroadRep")
def start_project(rid):
    row = svc.need_project(rid)
    agreement = svc.need_agreement(row["operating_agreement_id"])
    forbid_unless_owner_host(agreement["host_railroad_id"])
    if row["status"] not in ("FUNDED", "SUSPENDED"):
        raise ApiError("ERR_INVALID_STATE", "Project is not FUNDED or SUSPENDED.")
    row["status"] = "IN_PROGRESS"
    touch(row)
    segment = db.track_segments.get(row["track_segment_id"])
    if segment and segment["status"] != "CAPITAL_HOLD":
        segment["status"] = "CAPITAL_HOLD"
        touch(segment)
    return respond_object(dump(row))


@bp.post("/<rid>/suspend")
@endpoint("HostRailroadRep")
def suspend_project(rid):
    body()  # optional reason
    row = svc.need_project(rid)
    agreement = svc.need_agreement(row["operating_agreement_id"])
    forbid_unless_owner_host(agreement["host_railroad_id"])
    if row["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Project is not IN_PROGRESS.")
    row["status"] = "SUSPENDED"
    touch(row)
    return respond_object(dump(row))


@bp.post("/<rid>/complete")
@endpoint("HostRailroadRep")
def complete_project(rid):
    row = svc.need_project(rid)
    agreement = svc.need_agreement(row["operating_agreement_id"])
    forbid_unless_owner_host(agreement["host_railroad_id"])
    if row["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Project is not IN_PROGRESS.")
    row["status"] = "COMPLETED"
    touch(row)
    segment = db.track_segments.get(row["track_segment_id"])
    if segment:
        segment["capacity_trains_per_day"] = (
            segment["capacity_trains_per_day"] + row["added_frequency_capacity"]
        )
        segment["status"] = "OPERABLE"
        touch(segment)
    return respond_object(dump(row))
