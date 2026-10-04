"""DelayIncident and DispatchPriorityDispute endpoints."""
from flask import Blueprint, g

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
    now,
)
import svc

bp = Blueprint("incidents", __name__, url_prefix="/rail")


# ---------------------------------------------------------------------------
# DelayIncident
# ---------------------------------------------------------------------------
@bp.post("/delay-incidents")
@endpoint("HostRailroadRep")
def create_incident():
    payload = body()
    train_run_id = f_str(payload, "train_run_id")
    cause_code = f_enum(payload, "cause_code", svc.CAUSE_CODES)
    delay_minutes = f_int(payload, "delay_minutes", minimum=0)
    segment_passage_id = f_str(payload, "segment_passage_id", required=False)
    run = svc.need_run(train_run_id)
    # Host must own the run's railroad
    forbid_unless_owner_host(svc.host_for_run(run))
    # Referential integrity: passage must belong to run
    if segment_passage_id is not None:
        passage = svc.need_passage(segment_passage_id)
        if passage["train_run_id"] != train_run_id:
            raise ApiError(
                "ERR_REFERENTIAL_INTEGRITY",
                "Segment passage does not belong to the train run.",
            )
    row = new_row(
        "delay_incident",
        train_run_id=train_run_id,
        segment_passage_id=segment_passage_id,
        cause_code=cause_code,
        delay_minutes=delay_minutes,
        host_attributable=cause_code in svc.HOST_CAUSES,
        origin="CODED",
        status="OPEN",
    )
    db.delay_incidents[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.get("/delay-incidents")
@endpoint()
def list_incidents():
    rows = list(db.delay_incidents.values())
    train_run_id = q_str("train_run_id")
    segment_passage_id = q_str("segment_passage_id")
    status = q_enum("status", svc.INCIDENT_STATUSES)
    cause_code = q_enum("cause_code", svc.CAUSE_CODES)
    if train_run_id is not None:
        rows = [r for r in rows if r["train_run_id"] == train_run_id]
    if segment_passage_id is not None:
        rows = [r for r in rows if r.get("segment_passage_id") == segment_passage_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if cause_code is not None:
        rows = [r for r in rows if r["cause_code"] == cause_code]
    return paginate(sort_created(rows))


@bp.get("/delay-incidents/<rid>")
@endpoint()
def get_incident(rid):
    row = svc.need_incident(rid)
    return respond_object(dump(row))


@bp.post("/delay-incidents/<rid>/confirm")
@endpoint("PassengerOperator")
def confirm_incident(rid):
    row = svc.need_incident(rid)
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Incident is not OPEN.")
    row["status"] = "CONFIRMED"
    touch(row)
    run = db.train_runs.get(row["train_run_id"])
    if run:
        svc.recompute_run_attributed_minutes(run)
    return respond_object(dump(row))


@bp.post("/delay-incidents/<rid>/dispute")
@endpoint("PassengerOperator", "HostRailroadRep")
def dispute_incident(rid):
    payload = body()
    reason = f_str(payload, "reason", required=False)
    row = svc.need_incident(rid)
    if g.role == "HostRailroadRep":
        forbid_unless_owner_host(svc.host_for_incident(row))
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Incident is not OPEN.")
    row["status"] = "DISPUTED"
    touch(row)
    dispute = new_row(
        "dispute",
        delay_incident_id=row["id"],
        train_run_id=row["train_run_id"],
        reason=reason,
        resolution=None,
        resolved_at=None,
        status="UNDER_REVIEW",
    )
    db.disputes[dispute["id"]] = dispute
    return respond_object(dump(dispute), status=201)


# ---------------------------------------------------------------------------
# DispatchPriorityDispute
# ---------------------------------------------------------------------------
@bp.get("/disputes")
@endpoint()
def list_disputes():
    rows = list(db.disputes.values())
    train_run_id = q_str("train_run_id")
    delay_incident_id = q_str("delay_incident_id")
    status = q_enum("status", svc.DISPUTE_STATUSES)
    if train_run_id is not None:
        rows = [r for r in rows if r["train_run_id"] == train_run_id]
    if delay_incident_id is not None:
        rows = [r for r in rows if r["delay_incident_id"] == delay_incident_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.get("/disputes/<rid>")
@endpoint()
def get_dispute(rid):
    row = svc.need_dispute(rid)
    return respond_object(dump(row))


@bp.post("/disputes/<rid>/escalate")
@endpoint("PassengerOperator")
def escalate_dispute(rid):
    row = svc.need_dispute(rid)
    if row["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE", "Dispute is not UNDER_REVIEW.")
    row["status"] = "ESCALATED"
    touch(row)
    return respond_object(dump(row))


@bp.post("/disputes/<rid>/resolve")
@endpoint("SystemAdmin")
def resolve_dispute(rid):
    payload = body()
    resolution = f_enum(payload, "resolution", svc.RESOLUTIONS)
    row = svc.need_dispute(rid)
    incident = svc.need_incident(row["delay_incident_id"])
    if row["status"] == "UNDER_REVIEW":
        if resolution != "UPHELD":
            raise ApiError(
                "ERR_INVALID_STATE",
                "OVERTURNED resolution requires the dispute to be ESCALATED.",
            )
    elif row["status"] == "ESCALATED":
        pass
    else:
        raise ApiError("ERR_INVALID_STATE", "Dispute is already RESOLVED.")
    row["resolution"] = resolution
    row["resolved_at"] = now()
    row["status"] = "RESOLVED"
    touch(row)
    if resolution == "UPHELD":
        incident["status"] = "CONFIRMED"
    else:
        incident["status"] = "REVERSED"
    touch(incident)
    run = db.train_runs.get(incident["train_run_id"])
    if run:
        svc.recompute_run_attributed_minutes(run)
    return respond_object(dump(row))
