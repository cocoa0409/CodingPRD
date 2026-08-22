"""Nonconformance, repair disposition and recast (PRD 3.9)."""
from flask import Blueprint

import auth
import cascade
import constants
import db
import errors
import lookup
import response
import serialize
import validation

bp = Blueprint("repairs", __name__)

_SUPERSEDABLE = ("OPEN", "DISPOSITIONED", "REPAIR_IN_PROGRESS", "REINSPECTION")


@bp.post("/repair-dispositions")
def open_report():
    user_id, _role = auth.require(constants.ROLE_QC_TECHNICIAN)
    body = validation.get_body()
    piece_id = validation.req_id(body, "piece_id")
    defect_type = validation.req_enum(body, "defect_type", constants.DEFECT_TYPES)
    severity = validation.req_enum(body, "severity", constants.SEVERITIES)
    description = validation.req_text(body, "description")
    expected_version = validation.req_int(body, "expected_piece_version")

    piece = lookup.piece(piece_id)

    if expected_version != piece["version"]:
        errors.fail(errors.ERR_STALE_PIECE_VERSION,
                    "expected_piece_version does not match the piece's version.")
    if piece["qc_status"] == "REJECTED":
        errors.fail(errors.ERR_PIECE_INVALID_STATE,
                    "The piece has already been rejected.")

    for existing in db.by_seq(list(db.store.repair_dispositions.values())):
        if existing["piece_id"] == piece_id and existing["status"] in _SUPERSEDABLE:
            existing["status"] = "SUPERSEDED"
            db.touch(existing)

    row = db.new_row(db.store.repair_dispositions, {
        "piece_id": piece_id,
        "defect_type": defect_type,
        "severity": severity,
        "description": description,
        "disposition": None,
        "status": "OPEN",
        "reinspection_fail_count": 0,
        "opened_by_user_id": user_id,
        "dispositioned_by_user_id": None,
        "repaired_by_user_id": None,
    })
    db.mark_fresh(row)

    piece["qc_status"] = "NONCONFORMING"
    piece["qc_hold_reason"] = "OPEN_NCR"
    db.touch(piece)
    cascade.touch_project_of(piece)
    return response.object_response(serialize.repair_disposition(row), 201)


@bp.post("/repair-dispositions/<report_id>/disposition")
def decide(report_id):
    user_id, _role = auth.require(constants.ROLE_QUALITY_ENGINEER)
    report = lookup.repair_disposition(report_id)
    body = validation.get_body()
    disposition = validation.req_enum(body, "disposition", constants.DISPOSITIONS)

    if report["status"] != "OPEN":
        errors.fail(errors.ERR_DISPOSITION_INVALID_STATE,
                    "Only an OPEN report may be dispositioned.")

    report["disposition"] = disposition
    report["dispositioned_by_user_id"] = user_id
    piece = db.store.pieces.get(report["piece_id"])

    if disposition in ("PATCH_MINOR", "STRUCTURAL_REPAIR"):
        report["status"] = "DISPOSITIONED"
        db.touch(report)
    elif disposition == "USE_AS_IS":
        report["status"] = "CLOSED_ACCEPTED"
        db.touch(report)
        if piece is not None:
            cascade.repair_piece(piece)
    else:  # REJECT_RECAST
        report["status"] = "REJECTED_RECAST"
        db.touch(report)
        if piece is not None:
            cascade.scrap_piece(piece)
    return response.object_response(serialize.repair_disposition(report), 200)


@bp.post("/repair-dispositions/<report_id>/start-repair")
def start_repair(report_id):
    user_id, _role = auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    report = lookup.repair_disposition(report_id)

    if report["status"] != "DISPOSITIONED":
        errors.fail(errors.ERR_DISPOSITION_INVALID_STATE,
                    "Only a DISPOSITIONED report may enter repair.")
    if user_id == report["dispositioned_by_user_id"]:
        errors.fail(errors.ERR_SEGREGATION_OF_DUTIES,
                    "The repairer may not be the engineer who signed the disposition.")

    report["status"] = "REPAIR_IN_PROGRESS"
    report["repaired_by_user_id"] = user_id
    db.touch(report)
    return response.object_response(serialize.repair_disposition(report), 200)


@bp.post("/repair-dispositions/<report_id>/submit-reinspection")
def submit_reinspection(report_id):
    auth.require(constants.ROLE_PRODUCTION_SUPERVISOR)
    report = lookup.repair_disposition(report_id)

    if report["status"] != "REPAIR_IN_PROGRESS":
        errors.fail(errors.ERR_DISPOSITION_INVALID_STATE,
                    "Only a report in repair may be submitted for reinspection.")

    report["status"] = "REINSPECTION"
    db.touch(report)
    return response.object_response(serialize.repair_disposition(report), 200)


@bp.post("/repair-dispositions/<report_id>/reinspect")
def reinspect(report_id):
    auth.require(constants.ROLE_QUALITY_ENGINEER)
    report = lookup.repair_disposition(report_id)
    body = validation.get_body()
    result = validation.req_enum(body, "result", constants.REINSPECT_RESULTS)

    if report["status"] != "REINSPECTION":
        errors.fail(errors.ERR_DISPOSITION_INVALID_STATE,
                    "Only a report under reinspection may be reinspected.")

    piece = db.store.pieces.get(report["piece_id"])
    if result == "PASS":
        report["status"] = "CLOSED_ACCEPTED"
        db.touch(report)
        if piece is not None:
            cascade.repair_piece(piece)
    else:
        report["reinspection_fail_count"] += 1
        if report["reinspection_fail_count"] < constants.MAX_REINSPECTION_FAILS:
            report["status"] = "REPAIR_IN_PROGRESS"
            db.touch(report)
        else:
            report["status"] = "REJECTED_RECAST"
            db.touch(report)
            if piece is not None:
                cascade.scrap_piece(piece)
    return response.object_response(serialize.repair_disposition(report), 200)
