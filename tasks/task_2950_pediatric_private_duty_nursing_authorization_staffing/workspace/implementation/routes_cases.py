"""Cases, supervisory visits and incident reports."""
from flask import Blueprint

import auth as authmod
import cascade
import derive
import envelope
import lookup
import serialize
import store
import validate
from errors import fail
from store import db, new_immutable_row, new_row
from timeutil import add_days, fmt_instant

bp = Blueprint("cases", __name__)

CASE_STATUSES = ("PENDING_STAFFING", "ACTIVE", "ON_HOLD", "CLOSED")
HOLD_REASONS = ("HOSPITALIZATION", "INCIDENT_REVIEW", "AUTHORIZATION_EXPIRED", "FAMILY_REQUEST")
VISIT_OUTCOMES = ("PASS", "DEFICIENT")
INCIDENT_CATEGORIES = (
    "HOSPITALIZATION", "MEDICATION_ERROR", "EQUIPMENT_FAILURE", "FALL", "MISSED_VISIT",
)
INCIDENT_SEVERITIES = ("LOW", "MODERATE", "HIGH")
INCIDENT_STATUSES = ("OPEN", "CLOSED")
IN_FLIGHT_TIMESHEET = ("CAPTURED", "EDITED", "SUBMITTED", "BILL_REJECTED")


# --------------------------------------------------------------------------- #
# 34-40. cases
# --------------------------------------------------------------------------- #
@bp.route("/cases", methods=["POST"])
def create_case():
    authmod.require("CaseManager")
    data = validate.body()
    patient = lookup.get_patient(validate.req_fk(data, "patient_id"))
    authorization = lookup.get_authorization(validate.req_fk(data, "authorization_id"))
    continuity_nurse_id = validate.opt_fk(data, "continuity_nurse_id")
    if continuity_nurse_id is not None:
        lookup.get_nurse(continuity_nurse_id)
    supervisor = validate.req_str(data, "assigned_supervisor_user_id")
    limit_value = validate.opt_int(data, "concurrent_nurse_limit", default=1, lo=1, hi=3)
    excluded = validate.opt_id_list(data, "excluded_nurse_ids", default=[])
    if authorization["status"] not in derive.STAFFABLE_AUTH_STATUS:
        fail("ERR_AUTHORIZATION_NOT_ACTIVE", "The authorization is not open for staffing.")
    if patient["payer_id"] != authorization["payer_id"]:
        fail("ERR_PAYER_MISMATCH", "The patient's payer does not match the authorization's payer.")
    row = new_row(
        patient_id=patient["id"],
        authorization_id=authorization["id"],
        continuity_nurse_id=continuity_nurse_id,
        assigned_supervisor_user_id=supervisor,
        concurrent_nurse_limit=limit_value,
        excluded_nurse_ids=excluded,
        status="PENDING_STAFFING",
        hold_reason=None,
        hold_incident_report_id=None,
    )
    db.cases[row["id"]] = row
    return cascade.respond(serialize.case, row, 201)


@bp.route("/cases/<case_id>", methods=["GET"])
def read_case(case_id):
    authmod.require("CaseManager", "Scheduler", "ClinicalSupervisor", "PayerReviewer")
    return envelope.ok(serialize.case(lookup.get_case(case_id)))


@bp.route("/cases", methods=["GET"])
def list_cases():
    authmod.require("CaseManager", "Scheduler", "ClinicalSupervisor")
    limit, offset = validate.pagination()
    patient_id = validate.query_value("patient_id")
    authorization_id = validate.query_value("authorization_id")
    continuity_nurse_id = validate.query_value("continuity_nurse_id")
    hold_incident_report_id = validate.query_value("hold_incident_report_id")
    status = validate.query_enum("status", CASE_STATUSES)
    rows = store.ordered(db.cases)
    if patient_id is not None:
        rows = [r for r in rows if r["patient_id"] == patient_id]
    if authorization_id is not None:
        rows = [r for r in rows if r["authorization_id"] == authorization_id]
    if continuity_nurse_id is not None:
        rows = [r for r in rows if r["continuity_nurse_id"] == continuity_nurse_id]
    if hold_incident_report_id is not None:
        rows = [r for r in rows if r["hold_incident_report_id"] == hold_incident_report_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.case(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/cases/<case_id>/activate", methods=["POST"])
def activate_case(case_id):
    authmod.require("CaseManager")
    row = lookup.get_case(case_id)
    if row["status"] != "PENDING_STAFFING":
        fail("ERR_INVALID_STATE", "Only a PENDING_STAFFING case may be activated.")
    authorization = db.authorizations.get(row["authorization_id"])
    if authorization is None or authorization["status"] not in derive.STAFFABLE_AUTH_STATUS:
        fail("ERR_AUTHORIZATION_NOT_ACTIVE", "The authorization is not open for staffing.")
    patient = db.patients.get(row["patient_id"])
    if patient is not None and patient["status"] == "HOSPITALIZED":
        fail("ERR_PATIENT_HOSPITALIZED", "The patient is hospitalized.")
    row["status"] = "ACTIVE"
    cascade.touch(row)
    return cascade.respond(serialize.case, row)


@bp.route("/cases/<case_id>/hold", methods=["POST"])
def hold_case_endpoint(case_id):
    authmod.require("ClinicalSupervisor")
    row = lookup.get_case(case_id)
    data = validate.body()
    hold_reason = validate.req_enum(data, "hold_reason", HOLD_REASONS)
    if row["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE case may be placed on hold.")
    cascade.hold_case(row, hold_reason, None, "CASE_HOLD")
    return cascade.respond(serialize.case, row)


@bp.route("/cases/<case_id>/resume", methods=["POST"])
def resume_case(case_id):
    uid, _role = authmod.require("ClinicalSupervisor")
    row = lookup.get_case(case_id)
    if row["status"] != "ON_HOLD":
        fail("ERR_INVALID_STATE", "Only an ON_HOLD case may be resumed.")
    report = None
    if row["hold_incident_report_id"] is not None:
        report = db.incidents.get(row["hold_incident_report_id"])
        if report is not None and report["status"] != "CLOSED":
            fail("ERR_INVALID_STATE", "The holding incident report is still open.")
    patient = db.patients.get(row["patient_id"])
    if patient is not None and patient["status"] == "HOSPITALIZED":
        fail("ERR_PATIENT_HOSPITALIZED", "The patient is hospitalized.")
    if report is not None and report["reported_by_user_id"] == uid:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The supervisor who filed the holding report may not resume the case.")
    authorization = db.authorizations.get(row["authorization_id"])
    if authorization is None or authorization["status"] not in derive.STAFFABLE_AUTH_STATUS:
        fail("ERR_AUTHORIZATION_NOT_ACTIVE", "The authorization is not open for staffing.")
    row["status"] = "ACTIVE"
    row["hold_reason"] = None
    row["hold_incident_report_id"] = None
    cascade.touch(row)
    return cascade.respond(serialize.case, row)


@bp.route("/cases/<case_id>/close", methods=["POST"])
def close_case(case_id):
    authmod.require("CaseManager")
    row = lookup.get_case(case_id)
    data = validate.body()
    validate.req_str(data, "close_reason")
    if row["status"] not in ("PENDING_STAFFING", "ACTIVE", "ON_HOLD"):
        fail("ERR_INVALID_STATE", "The case is already closed.")
    for ts in derive.timesheets_of_case(row["id"]):
        if ts["status"] in IN_FLIGHT_TIMESHEET:
            fail("ERR_INVALID_STATE", "A timesheet of this case is still in flight.")
    row["status"] = "CLOSED"
    row["hold_reason"] = None
    cascade.touch(row)
    cascade.close_case_cascade(row)
    return cascade.respond(serialize.case, row)


# --------------------------------------------------------------------------- #
# 41-42. supervisory visits
# --------------------------------------------------------------------------- #
@bp.route("/cases/<case_id>/supervisory-visits", methods=["POST"])
def create_visit(case_id):
    uid, _role = authmod.require("ClinicalSupervisor")
    case = lookup.get_case(case_id)
    data = validate.body()
    visit_at = validate.req_instant(data, "visit_at")
    outcome = validate.req_enum(data, "outcome", VISIT_OUTCOMES)
    notes = validate.req_str(data, "notes")
    if visit_at > db.clock:
        validate.bad("Field 'visit_at' must not be after the current logical clock.")
    patient = db.patients.get(case["patient_id"])
    base = derive.base_cadence_days(patient)
    cadence = base if outcome == "PASS" else -(-base // 2)
    row = new_immutable_row(
        case_id=case["id"],
        supervisor_user_id=uid,
        visit_at=visit_at,
        outcome=outcome,
        notes=notes,
        cadence_days_applied=int(cadence),
        next_due_at=add_days(visit_at, int(cadence)),
    )
    db.visits[row["id"]] = row
    # The case's next_supervisory_visit_due_at and supervisory_status re-derive from
    # the latest visit, so the case row itself only needs its bookkeeping refreshed.
    cascade.touch(case)
    return cascade.respond_data(serialize.visit(row), 201)


@bp.route("/cases/<case_id>/supervisory-visits", methods=["GET"])
def list_visits(case_id):
    authmod.require("ClinicalSupervisor", "CaseManager", "PayerReviewer")
    case = lookup.get_case(case_id)
    limit, offset = validate.pagination()
    rows = derive.visits_of_case(case["id"])
    total = len(rows)
    body = [serialize.visit(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


# --------------------------------------------------------------------------- #
# 43-46. incident reports
# --------------------------------------------------------------------------- #
@bp.route("/incident-reports", methods=["POST"])
def create_incident():
    uid, _role = authmod.require("ClinicalSupervisor")
    data = validate.body()
    case = lookup.get_case(validate.req_fk(data, "case_id"))
    category = validate.req_enum(data, "category", INCIDENT_CATEGORIES)
    severity = validate.req_enum(data, "severity", INCIDENT_SEVERITIES)
    occurred_at = validate.req_instant(data, "occurred_at")
    narrative = validate.req_str(data, "narrative")
    if occurred_at > db.clock:
        validate.bad("Field 'occurred_at' must not be after the current logical clock.")
    if case["status"] not in ("PENDING_STAFFING", "ACTIVE", "ON_HOLD"):
        fail("ERR_INVALID_STATE", "Incidents may only be filed against an open case.")
    triggered = category == "HOSPITALIZATION" or severity == "HIGH"
    row = new_row(
        case_id=case["id"],
        reported_by_user_id=uid,
        category=category,
        severity=severity,
        occurred_at=occurred_at,
        narrative=narrative,
        status="OPEN",
        triggered_case_hold=triggered,
        resolution=None,
        patient_returned_home=False,
    )
    db.incidents[row["id"]] = row
    if category == "HOSPITALIZATION":
        patient = db.patients.get(case["patient_id"])
        if patient is not None and patient["status"] != "HOSPITALIZED":
            patient["status"] = "HOSPITALIZED"
            cascade.touch(patient)
        if case["status"] == "ACTIVE":
            cascade.hold_case(case, "HOSPITALIZATION", row["id"], "CASE_HOLD")
    elif severity == "HIGH":
        if case["status"] == "ACTIVE":
            cascade.hold_case(case, "INCIDENT_REVIEW", row["id"], "CASE_HOLD")
    return cascade.respond(serialize.incident, row, 201)


@bp.route("/incident-reports/<incident_id>", methods=["GET"])
def read_incident(incident_id):
    authmod.require("ClinicalSupervisor", "CaseManager", "PayerReviewer")
    return envelope.ok(serialize.incident(lookup.get_incident(incident_id)))


@bp.route("/cases/<case_id>/incident-reports", methods=["GET"])
def list_case_incidents(case_id):
    authmod.require("ClinicalSupervisor", "CaseManager", "PayerReviewer")
    case = lookup.get_case(case_id)
    limit, offset = validate.pagination()
    status = validate.query_enum("status", INCIDENT_STATUSES)
    rows = [r for r in store.ordered(db.incidents) if r["case_id"] == case["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    body = [serialize.incident(r) for r in validate.page(rows, limit, offset)]
    return envelope.ok_list(body, limit, offset, total)


@bp.route("/incident-reports/<incident_id>/close", methods=["POST"])
def close_incident(incident_id):
    authmod.require("ClinicalSupervisor")
    row = lookup.get_incident(incident_id)
    data = validate.body()
    resolution = validate.req_str(data, "resolution")
    returned_home = validate.opt_bool(data, "patient_returned_home", default=False)
    if row["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Only an OPEN incident report may be closed.")
    row["status"] = "CLOSED"
    row["resolution"] = resolution
    row["patient_returned_home"] = returned_home
    cascade.touch(row)
    case = db.cases.get(row["case_id"])
    if returned_home and case is not None:
        patient = db.patients.get(case["patient_id"])
        if patient is not None and patient["status"] == "HOSPITALIZED":
            patient["status"] = "ACTIVE"
            cascade.touch(patient)
    return cascade.respond(serialize.incident, row)
