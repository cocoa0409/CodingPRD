"""Complaint handling, malfunction reporting and field actions (PRD 3.8)."""

from flask import Blueprint

import calc
import cascades
import lookup
import serialize
from errors import ApiError
from response import created_response, list_response, object_response
from store import add_days, create_row, db, now_clock, rows, touch
from validation import (ALL_ROLES, Body, COMPLAINT_STATUSES, FIELD_ACTIONS,
                        SEVERITIES, authenticate_and_authorize, bool_filter,
                        enum_filter, json_body, pagination, paginate, str_filter)

bp = Blueprint("complaints", __name__)


@bp.post("/complaints")
def create_complaint():
    authenticate_and_authorize(("RegulatoryAffairs", "DistributionPlanner"))
    body = Body(json_body())
    reagent_lot_id = body.req_str("reagent_lot_id")
    complaint_code = body.req_str("complaint_code")
    narrative = body.req_str("narrative")
    death_or_injury = body.opt_bool("device_related_death_or_injury", False)

    # Rung 45 - body foreign keys.
    lookup.reagent_lot(reagent_lot_id)

    row = create_row(db.complaints, {
        "reagent_lot_id": reagent_lot_id,
        "complaint_code": complaint_code,
        "narrative": narrative,
        "device_related_death_or_injury": death_or_injury,
        "received_at": now_clock(),
        "severity": None,
        "malfunction_suspected": None,
        "reportable": None,
        "report_due_at": None,
        "report_ref": None,
        "reported_at": None,
        "report_late": None,
        "field_action": None,
        "field_action_decided_by_user_id": None,
        "field_action_decided_at": None,
        "triaged_by_user_id": None,
        "status": "RECEIVED",
    })
    return created_response(serialize.complaint(row))


@bp.get("/complaints/<complaint_id>")
def read_complaint(complaint_id):
    authenticate_and_authorize(ALL_ROLES)
    row = lookup.complaint(complaint_id)
    return object_response(serialize.complaint(row))


@bp.get("/complaints")
def list_complaints():
    authenticate_and_authorize(ALL_ROLES)
    limit, offset = pagination()
    reagent_lot_id = str_filter("reagent_lot_id")
    status = enum_filter("status", COMPLAINT_STATUSES)
    reportable = bool_filter("reportable")
    severity = enum_filter("severity", SEVERITIES)
    items = rows(db.complaints)
    if reagent_lot_id is not None:
        items = [r for r in items if r["reagent_lot_id"] == reagent_lot_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if reportable is not None:
        items = [r for r in items if r["reportable"] == reportable]
    if severity is not None:
        items = [r for r in items if r["severity"] == severity]
    page = paginate(items, limit, offset)
    return list_response([serialize.complaint(r) for r in page],
                         limit, offset, len(items))


@bp.post("/complaints/<complaint_id>/triage")
def triage_complaint(complaint_id):
    user_id, _role = authenticate_and_authorize(("RegulatoryAffairs",))
    body = Body(json_body())
    severity = body.req_enum("severity", SEVERITIES)
    malfunction_suspected = body.req_bool("malfunction_suspected")
    complaint = lookup.complaint(complaint_id)

    # Rung 60 - state precondition.
    if complaint["status"] != "RECEIVED":
        raise ApiError("ERR_COMPLAINT_STATE_INVALID",
                       "A complaint in %s has already been triaged."
                       % complaint["status"])

    complaint["severity"] = severity
    complaint["malfunction_suspected"] = malfunction_suspected
    complaint["triaged_by_user_id"] = user_id
    complaint["status"] = "TRIAGED"
    reportable = calc.complaint_reportable(
        malfunction_suspected, complaint["device_related_death_or_injury"], severity)
    complaint["reportable"] = reportable
    if reportable:
        days = 5 if complaint["device_related_death_or_injury"] else 30
        complaint["report_due_at"] = add_days(complaint["received_at"], days)
    else:
        complaint["report_due_at"] = None
    touch(complaint)
    return object_response(serialize.complaint(complaint))


@bp.post("/complaints/<complaint_id>/malfunction-report")
def file_malfunction_report(complaint_id):
    authenticate_and_authorize(("RegulatoryAffairs",))
    body = Body(json_body())
    report_ref = body.req_str("report_ref")
    complaint = lookup.complaint(complaint_id)

    # Rung 60 - state precondition.
    if complaint["status"] not in ("TRIAGED", "FIELD_ACTION_DECIDED"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID",
                       "A complaint in %s cannot be reported." % complaint["status"])
    if not complaint["reportable"]:
        raise ApiError("ERR_COMPLAINT_STATE_INVALID",
                       "The complaint is not reportable.")

    reported_at = now_clock()
    complaint["report_ref"] = report_ref
    complaint["reported_at"] = reported_at
    # A report filed at exactly the deadline instant is on time.
    complaint["report_late"] = bool(complaint["report_due_at"] is not None
                                    and reported_at > complaint["report_due_at"])
    if complaint["status"] == "TRIAGED":
        complaint["status"] = "MALFUNCTION_REPORTED"
    touch(complaint)
    return object_response(serialize.complaint(complaint))


@bp.post("/complaints/<complaint_id>/field-action")
def decide_field_action(complaint_id):
    user_id, _role = authenticate_and_authorize(("QAReleaser",))
    body = Body(json_body())
    field_action = body.req_enum("field_action", FIELD_ACTIONS)
    body.opt_str("justification")
    complaint = lookup.complaint(complaint_id)
    lot = db.reagent_lots[complaint["reagent_lot_id"]]

    # Rung 50 - segregation of duties against the releaser of the lot.
    if lot["released_by_user_id"] is not None and \
            lot["released_by_user_id"] == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The releaser of the lot may not decide its field action.")

    # Rung 60 - state precondition.
    if complaint["status"] not in ("TRIAGED", "MALFUNCTION_REPORTED"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID",
                       "A complaint in %s cannot take a field action."
                       % complaint["status"])

    # Rung 96 - field action justification. PRD 3.8 enumerates the field-action
    # gates exhaustively (complaint state, segregation of duties, REMOVAL needs
    # HIGH severity); the lot's own disposition_status is NOT one of them and
    # carries no rung on the 2.6 ladder, so nothing may pre-empt this rung.
    if field_action == "REMOVAL" and complaint["severity"] != "HIGH":
        raise ApiError("ERR_FIELD_ACTION_NOT_JUSTIFIED")

    complaint["field_action"] = field_action
    complaint["field_action_decided_by_user_id"] = user_id
    complaint["field_action_decided_at"] = now_clock()
    complaint["status"] = "FIELD_ACTION_DECIDED"
    touch(complaint)

    if field_action in ("CORRECTION", "REMOVAL"):
        cascades.recall_lot(lot, field_action)
    return object_response(serialize.complaint(complaint))


@bp.post("/complaints/<complaint_id>/close")
def close_complaint(complaint_id):
    authenticate_and_authorize(("RegulatoryAffairs",))
    json_body()
    complaint = lookup.complaint(complaint_id)

    # Rung 60 - state precondition.
    if complaint["status"] not in ("TRIAGED", "MALFUNCTION_REPORTED",
                                  "FIELD_ACTION_DECIDED"):
        raise ApiError("ERR_COMPLAINT_STATE_INVALID",
                       "A complaint in %s cannot be closed." % complaint["status"])
    if complaint["field_action"] is None:
        raise ApiError("ERR_COMPLAINT_STATE_INVALID",
                       "The field-action branch has not run.")

    # Rung 95 - an outstanding malfunction report blocks the join.
    if complaint["reportable"] and complaint["reported_at"] is None:
        raise ApiError("ERR_MALFUNCTION_REPORT_PENDING")

    complaint["status"] = "CLOSED"
    touch(complaint)
    return object_response(serialize.complaint(complaint))
