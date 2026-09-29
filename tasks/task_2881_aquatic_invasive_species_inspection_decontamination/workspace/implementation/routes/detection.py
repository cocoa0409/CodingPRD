"""Detection reports and infestation escalation (PRD 3.8)."""

from flask import Blueprint

import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, fmt_iso, serialize, touch
from validate import (arg_filter, opt_dt, opt_str, read_body, req_enum,
                      req_ref, req_str, require_auth)

bp = Blueprint("detection", __name__)

DETECTION_CLASSES = ("LIVE_ORGANISM", "DEAD_ORGANISM", "PLANT_FRAGMENT")
VERDICTS = ("ACCEPTED", "REJECTED")


@bp.post("/detection-reports")
def create_report():
    user_id, _role, _actor = require_auth(("Inspector",))
    body = read_body()
    record_id = req_ref(body, "inspection_record_id")
    species_code = req_str(body, "species_code", max_len=32)
    detection_class = req_enum(body, "detection_class", DETECTION_CLASSES)
    observed_at = opt_dt(body, "observed_at")

    record = services.record_or_404(record_id)

    row = base_row()
    row.update({
        "inspection_record_id": record["id"],
        "water_body_id": record["prior_water_body_id"],
        "reported_by_inspector_id": user_id,
        "species_code": species_code,
        "detection_class": detection_class,
        "observed_at": fmt_iso(observed_at),
        "status": "DRAFT",
        "submission_count": 0,
        "state_db_ack_id": None,
        "rejection_reason": None,
    })
    db.detection_reports[row["id"]] = row
    return created(serialize(row))


@bp.get("/detection-reports/<did>")
def get_report(did):
    require_auth(ALL_ROLES)
    return ok(serialize(services.detection_report_or_404(did)))


@bp.get("/detection-reports")
def list_reports():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "inspection_record_id": arg_filter("inspection_record_id"),
        "water_body_id": arg_filter("water_body_id"),
        "reported_by_inspector_id": arg_filter("reported_by_inspector_id"),
        "status": arg_filter("status"),
        "detection_class": arg_filter("detection_class"),
    }
    rows = [r for r in db.detection_reports.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/detection-reports/<did>/submission")
def submit_report(did):
    user_id, _role, actor = require_auth(("Inspector",))
    body = read_body()
    opt_str(body, "notes", min_len=None)

    report = services.detection_report_or_404(did)

    if report["reported_by_inspector_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    if report["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_REPORT_INVALID_STATE")

    services.require_active(actor)

    report["status"] = "SUBMITTED"
    report["submission_count"] += 1
    report["rejection_reason"] = None
    touch(report)
    return ok(serialize(report))


@bp.post("/detection-reports/<did>/state-acknowledgement")
def acknowledge_report(did):
    user_id, _role, _actor = require_auth(("StateDataSteward",))
    body = read_body()
    verdict = req_enum(body, "verdict", VERDICTS)
    ack_id = opt_str(body, "state_db_ack_id", min_len=None)
    rejection_reason = opt_str(body, "rejection_reason", min_len=None)

    report = services.detection_report_or_404(did)

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_INVALID_STATE")

    if user_id == report["reported_by_inspector_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if verdict == "REJECTED":
        report["status"] = "REJECTED"
        report["rejection_reason"] = rejection_reason
    else:
        report["status"] = "ACCEPTED"
        report["state_db_ack_id"] = ack_id
        services.accept_detection(report)

    touch(report)
    return ok(serialize(report))
