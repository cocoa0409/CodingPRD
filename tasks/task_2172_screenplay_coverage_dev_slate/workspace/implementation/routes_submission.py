"""Submission intake and the release-form gate."""

from flask import Blueprint

import calc
from core import (
    Field, authenticate, collection_rows, created, db, fail, filter_eq, fmt_dt,
    json_body, lookup, new_row, now, now_str, ok, ok_list, paginate, pagination,
    parse_dt, parse_fields, qp, touch,
)

bp = Blueprint("submission", __name__)

SUBMISSION_READ_ROLES = ("SlateAdmin", "StoryEditor", "BusinessAffairs", "DevelopmentExec",
                         "Reader", "Submitter")
SUBMISSION_LIST_ROLES = ("SlateAdmin", "StoryEditor", "BusinessAffairs", "DevelopmentExec",
                         "Reader")
RELEASE_READ_ROLES = ("SlateAdmin", "StoryEditor", "Submitter")


@bp.post("/submissions")
def create_submission():
    authenticate(("Submitter", "StoryEditor"))
    body = json_body()
    prop = None
    if body.get("property_id") is not None:
        prop = lookup("properties", body.get("property_id"), "ERR_PROPERTY_NOT_FOUND")
    data = parse_fields(body, [
        Field("property_id", "string", required=True),
        Field("submitting_agency", "string", required=True),
        Field("submitter_contact_email", "string", required=True),
        Field("submitted_via", "enum", required=True, enum=calc.SUBMITTED_VIA),
        Field("priority_flag", "enum", default="STANDARD", enum=calc.PRIORITY_FLAGS),
    ])
    received = now()
    due = calc.coverage_turnaround_due(received, data["priority_flag"])
    row = new_row("submissions", {
        "property_id": prop["id"],
        "submitting_agency": data["submitting_agency"],
        "submitter_contact_email": data["submitter_contact_email"],
        "submitted_via": data["submitted_via"],
        "priority_flag": data["priority_flag"],
        "release_form_required": calc.release_form_requirement(
            data["submitted_via"], data["submitting_agency"]),
        "received_at": fmt_dt(received),
        "coverage_due_at": fmt_dt(due),
        "status": "RECEIVED",
        "decision": "PENDING",
        "withdrawal_reason": None,
    })
    return created(row)


@bp.get("/submissions/<sid>")
def read_submission(sid):
    authenticate(SUBMISSION_READ_ROLES)
    return ok(lookup("submissions", sid, "ERR_SUBMISSION_NOT_FOUND"))


@bp.get("/submissions")
def list_submissions():
    authenticate(SUBMISSION_LIST_ROLES)
    limit, offset = pagination()
    rows = collection_rows("submissions")
    rows = filter_eq(rows, "property_id", qp("property_id"))
    rows = filter_eq(rows, "status", qp("status"))
    rows = filter_eq(rows, "submitted_via", qp("submitted_via"))
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.post("/submissions/<sid>/release-forms")
def open_release_form(sid):
    authenticate(("StoryEditor",))
    submission = lookup("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("expires_at", "datetime", required=True)])
    expires = parse_dt(data["expires_at"])
    if submission["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "A release form may only be opened on a RECEIVED submission.")
    if not submission["release_form_required"]:
        fail("ERR_INVALID_STATE", "This submission does not require a release form.")
    for form in calc.release_forms_of(submission["id"]):
        if form["status"] in ("REQUIRED", "SENT", "EXECUTED", "WAIVED"):
            fail("ERR_INVALID_STATE", "A release form already exists on this submission.")
    row = new_row("release_forms", {
        "submission_id": submission["id"],
        "status": "REQUIRED",
        "expires_at": fmt_dt(expires),
        "signer_name": None,
        "signed_at": None,
        "waiver_reason": None,
    })
    submission["status"] = "RELEASE_PENDING"
    touch(submission)
    return created(row)


@bp.get("/submissions/<sid>/release-forms")
def list_submission_release_forms(sid):
    authenticate(RELEASE_READ_ROLES)
    submission = lookup("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    limit, offset = pagination()
    rows = calc.release_forms_of(submission["id"])
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit, offset, total)


@bp.get("/release-forms/<fid>")
def read_release_form(fid):
    authenticate(RELEASE_READ_ROLES)
    return ok(lookup("release_forms", fid, "ERR_RELEASE_FORM_NOT_FOUND"))


@bp.post("/release-forms/<fid>/send")
def send_release_form(fid):
    authenticate(("StoryEditor",))
    form = lookup("release_forms", fid, "ERR_RELEASE_FORM_NOT_FOUND")
    if form["status"] != "REQUIRED":
        fail("ERR_INVALID_STATE", "Only a REQUIRED release form may be sent.")
    if now() > parse_dt(form["expires_at"]):
        fail("ERR_INVALID_STATE", "The release form window has closed.")
    form["status"] = "SENT"
    touch(form)
    return ok(form)


@bp.post("/release-forms/<fid>/execute")
def execute_release_form(fid):
    authenticate(("Submitter",))
    form = lookup("release_forms", fid, "ERR_RELEASE_FORM_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("signer_name", "string", required=True)])
    if form["status"] != "SENT":
        fail("ERR_INVALID_STATE", "Only a SENT release form may be executed.")
    if now() > parse_dt(form["expires_at"]):
        fail("ERR_INVALID_STATE", "The release form window has closed.")
    form["status"] = "EXECUTED"
    form["signer_name"] = data["signer_name"]
    form["signed_at"] = now_str()
    touch(form)
    submission = db.submissions.get(form["submission_id"])
    if submission is not None:
        submission["status"] = "INTAKE_CLEARED"
        touch(submission)
    return ok(form)


@bp.post("/release-forms/<fid>/waive")
def waive_release_form(fid):
    authenticate(("StoryEditor",))
    form = lookup("release_forms", fid, "ERR_RELEASE_FORM_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("waiver_reason", "string", required=True)])
    if form["status"] not in ("REQUIRED", "SENT"):
        fail("ERR_INVALID_STATE", "Only a REQUIRED or SENT release form may be waived.")
    form["status"] = "WAIVED"
    form["waiver_reason"] = data["waiver_reason"]
    touch(form)
    submission = db.submissions.get(form["submission_id"])
    if submission is not None:
        submission["status"] = "INTAKE_CLEARED"
        touch(submission)
    return ok(form)


@bp.post("/submissions/<sid>/clear-intake")
def clear_intake(sid):
    authenticate(("StoryEditor",))
    submission = lookup("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    if submission["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "Intake may only be cleared from RECEIVED.")
    if submission["release_form_required"]:
        satisfied = any(f["status"] in ("EXECUTED", "WAIVED")
                        for f in calc.release_forms_of(submission["id"]))
        if not satisfied:
            fail("ERR_RELEASE_FORM_REQUIRED", "An executed or waived release form is required.")
    submission["status"] = "INTAKE_CLEARED"
    touch(submission)
    return ok(submission)


@bp.post("/submissions/<sid>/withdraw")
def withdraw_submission(sid):
    authenticate(("Submitter", "StoryEditor"))
    submission = lookup("submissions", sid, "ERR_SUBMISSION_NOT_FOUND")
    body = json_body()
    data = parse_fields(body, [Field("reason", "string", required=True)])
    if submission["status"] in calc.SUBMISSION_TERMINAL:
        fail("ERR_TERMINAL_STATE", "This submission has already reached a terminal state.")
    calc.apply_lazy_expiry(submission)
    submission["status"] = "WITHDRAWN"
    submission["withdrawal_reason"] = data["reason"]
    touch(submission)
    for form in calc.release_forms_of(submission["id"]):
        if form["status"] in ("REQUIRED", "SENT"):
            form["status"] = "EXPIRED"
            touch(form)
    for assignment in calc.assignments_of(submission["id"]):
        if assignment["status"] not in calc.ASSIGNMENT_OPEN:
            continue
        assignment["status"] = "RECALLED"
        touch(assignment)
        report = calc.report_of_assignment(assignment["id"])
        if report is not None and report["status"] not in ("APPROVED", "REJECTED"):
            report["status"] = "REJECTED"
            touch(report)
        reader = db.readers.get(assignment["reader_id"])
        if reader is not None:
            calc.recompute_reader_counters(reader)
            touch(reader)
    return ok(submission)
