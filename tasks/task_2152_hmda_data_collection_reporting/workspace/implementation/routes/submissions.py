"""The annual filing cycle and public disclosure (PRD 3.7)."""

from flask import Blueprint

import calc
import cascades
import constants as C
import serializers as S
import store
from auth import authenticate
from errors import fail
from response import array_response, object_response
from validate import (Field, check, enum_filter, json_body, lookup, paginate,
                      pagination)

bp = Blueprint("submissions", __name__)

BACK_OFFICE_READ_ROLES = ["SystemAdmin", "InstitutionAdmin", "ComplianceAnalyst",
                          "ComplianceOfficer", "Examiner"]

CREATE_FIELDS = [
    Field("institution_id", "string", required=True),
    Field("expected_institution_version", "integer", required=True),
]
ATTACH_FIELDS = [Field("edit_run_id", "string", required=True)]
CERTIFY_FIELDS = [Field("attestation_text", "string", required=True)]
REVIEW_FIELDS = [
    Field("decision", "string", required=True, enum=C.REVIEW_DECISIONS),
    Field("rejection_reason", "string"),
]
RESUBMIT_FIELDS = [Field("reason", "string", required=True)]


@bp.route("/hmda/submissions", methods=["POST"])
def create_submission():
    authenticate(["ComplianceOfficer"])
    body = check(json_body(), CREATE_FIELDS)
    inst = lookup(store.institutions, body["institution_id"], "ERR_INSTITUTION_NOT_FOUND")

    # step 7 -- optimistic concurrency on the parent Institution version
    if body["expected_institution_version"] != inst["version"]:
        fail("ERR_STALE_INSTITUTION_VERSION")

    for existing in store.ordered(store.filing_submissions.values()):
        if existing["institution_id"] == inst["id"] and existing["status"] == "DRAFT":
            existing["is_superseded"] = True
            store.touch(existing)

    inst["_submission_index"] += 1
    row = store.new_row()
    row.update({
        "institution_id": inst["id"],
        "edit_run_id": None,
        "activity_year": inst["activity_year"],
        "submission_index": inst["_submission_index"],
        "provisional_record_count": calc.submission_record_count(inst, "PROVISIONAL"),
        "final_record_count": None,
        "certified_by_user_id": None,
        "certified_at": None,
        "attestation_text": None,
        "filed_at": None,
        "deadline_at": inst["filing_deadline_at"],
        "is_late": None,
        "late_by_days": None,
        "rejection_reason": None,
        "resubmission_count": 0,
        "is_superseded": False,
        "status": "DRAFT",
        "_final_application_ids": [],
        "_archived_application_ids": [],
    })
    store.filing_submissions[row["id"]] = row
    store.bump(inst)
    return object_response(S.filing_submission(row), 201)


@bp.route("/hmda/submissions/<submission_id>", methods=["GET"])
def get_submission(submission_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    row = lookup(store.filing_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    return object_response(S.filing_submission(row))


@bp.route("/hmda/submissions/<submission_id>/attach-edit-run", methods=["POST"])
def attach_edit_run(submission_id):
    authenticate(["ComplianceOfficer"])
    sub = lookup(store.filing_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    body = check(json_body(), ATTACH_FIELDS)
    run = lookup(store.edit_runs, body["edit_run_id"], "ERR_EDIT_RUN_NOT_FOUND")

    # step 8 -- state preconditions
    if sub["status"] != "DRAFT":
        fail("ERR_INVALID_SUBMISSION_STATE")
    if run["status"] not in ("COMPLETED", "CLEARED_ALL"):
        fail("ERR_EDIT_RUN_INVALIDATED")

    # step 12 -- cross-field referential accuracy
    if run["institution_id"] != sub["institution_id"]:
        fail("ERR_EDIT_RUN_INSTITUTION_MISMATCH")

    sub["status"] = "EDITS_ATTACHED"
    sub["edit_run_id"] = run["id"]
    store.bump(sub)
    return object_response(S.filing_submission(sub))


@bp.route("/hmda/submissions/<submission_id>/certify", methods=["POST"])
def certify_submission(submission_id):
    user_id, _role = authenticate(["ComplianceOfficer"])
    sub = lookup(store.filing_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    body = check(json_body(), CERTIFY_FIELDS)

    # step 8 -- state precondition
    if sub["status"] != "EDITS_ATTACHED":
        fail("ERR_INVALID_SUBMISSION_STATE")

    run = store.edit_runs.get(sub["edit_run_id"])
    exceptions = cascades.exceptions_of_run(run["id"]) if run is not None else []

    # step 10 -- segregation of duties
    for exc in exceptions:
        if exc["status"] == "VERIFIED" and exc["verified_by_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES")

    # step 16 -- aggregate and quota gates, in the pinned order
    for exc in exceptions:
        if exc["status"] == "OPEN" and exc["severity"] in C.BLOCKING_SEVERITIES:
            fail("ERR_OPEN_VALIDITY_EDITS")
    if run["verified_exception_count"] < run["required_verified_quota"]:
        fail("ERR_VERIFICATION_QUOTA_NOT_MET")

    inst = store.institutions[sub["institution_id"]]
    final_set = calc.final_record_set(inst)
    sub["status"] = "CERTIFIED"
    sub["certified_by_user_id"] = user_id
    sub["certified_at"] = store.now()
    sub["attestation_text"] = body["attestation_text"]
    sub["final_record_count"] = len(final_set)
    sub["_final_application_ids"] = [a["id"] for a in final_set]
    store.bump(sub)

    inst["filing_posture"] = "LOCKED_FOR_FILING"
    store.bump(inst)
    return object_response(S.filing_submission(sub))


@bp.route("/hmda/submissions/<submission_id>/file", methods=["POST"])
def file_submission(submission_id):
    authenticate(["ComplianceOfficer"])
    sub = lookup(store.filing_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    json_body()
    inst = store.institutions[sub["institution_id"]]

    # step 8 -- state preconditions
    if sub["status"] != "CERTIFIED":
        fail("ERR_INVALID_SUBMISSION_STATE")
    if inst["filing_posture"] != "LOCKED_FOR_FILING":
        fail("ERR_INVALID_SUBMISSION_STATE")

    # hop 1 -- the filing itself and the deadline comparison
    filed_at = store.now()
    is_late, late_by_days = calc.filing_lateness(filed_at, sub["deadline_at"])
    sub["status"] = "FILED"
    sub["filed_at"] = filed_at
    sub["is_late"] = is_late
    sub["late_by_days"] = late_by_days
    store.bump(sub)
    inst["filing_posture"] = "FILED_YEAR"

    # hop 2 -- FINAL-set records in REGISTER_LOCKED are archived
    final_set = [store.applications[a_id] for a_id in sub["_final_application_ids"]
                 if a_id in store.applications]
    archived = []
    for app in final_set:
        if app["stage"] == "REGISTER_LOCKED":
            app["stage"] = "ARCHIVED"
            store.bump(app)
            archived.append(app["id"])
    sub["_archived_application_ids"] = archived

    # hop 3 -- the institution's open register is recomputed
    calc.recompute_institution_counters(inst)
    if inst["open_register_count"] == 0:
        inst["filing_posture"] = "CLOSED_YEAR"

    # publication -- exactly two statements, MODIFIED_LAR then DISCLOSURE_REPORT
    redaction = calc.disclosure_redaction(final_set)
    for statement_type in ("MODIFIED_LAR", "DISCLOSURE_REPORT"):
        row = store.new_row(versioned=False)
        row.update({
            "submission_id": sub["id"],
            "statement_type": statement_type,
            "record_count": sub["final_record_count"],
            "tract_suppression_count": redaction["tract_suppression_count"],
            "suppressed_record_count": redaction["suppressed_record_count"],
            "redacted_field_count": redaction["redacted_field_count"],
            "published_at": filed_at,
        })
        store.disclosure_statements[row["id"]] = row

    store.bump(inst)
    return object_response(S.filing_submission(sub))


@bp.route("/hmda/submissions/<submission_id>/review", methods=["POST"])
def review_submission(submission_id):
    authenticate(["Examiner"])
    sub = lookup(store.filing_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    body = check(json_body(), REVIEW_FIELDS)

    # step 8 -- state precondition
    if sub["status"] != "FILED":
        fail("ERR_INVALID_SUBMISSION_STATE")

    inst = store.institutions[sub["institution_id"]]
    if body["decision"] == "ACCEPT":
        sub["status"] = "ACCEPTED"
        store.bump(sub)
        store.bump(inst)
        return object_response(S.filing_submission(sub))

    sub["status"] = "REJECTED"
    sub["rejection_reason"] = body.get("rejection_reason")
    store.bump(sub)
    for app_id in sub["_archived_application_ids"]:
        app = store.applications.get(app_id)
        if app is not None and app["stage"] == "ARCHIVED":
            app["stage"] = "REGISTER_LOCKED"
            store.bump(app)
    sub["_archived_application_ids"] = []
    inst["filing_posture"] = "OPEN"
    calc.recompute_institution_counters(inst)
    store.bump(inst)
    return object_response(S.filing_submission(sub))


@bp.route("/hmda/submissions/<submission_id>/resubmit", methods=["POST"])
def resubmit_submission(submission_id):
    authenticate(["ComplianceOfficer"])
    sub = lookup(store.filing_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    check(json_body(), RESUBMIT_FIELDS)

    # step 8 -- state precondition
    if sub["status"] != "REJECTED":
        fail("ERR_INVALID_SUBMISSION_STATE")

    sub["status"] = "DRAFT"
    sub["resubmission_count"] += 1
    sub["edit_run_id"] = None
    sub["certified_by_user_id"] = None
    sub["certified_at"] = None
    sub["attestation_text"] = None
    sub["final_record_count"] = None
    sub["filed_at"] = None
    sub["is_late"] = None
    sub["late_by_days"] = None
    sub["_final_application_ids"] = []
    store.bump(sub)
    return object_response(S.filing_submission(sub))


@bp.route("/hmda/submissions/<submission_id>/disclosure-statements", methods=["GET"])
def list_disclosure_statements(submission_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    lookup(store.filing_submissions, submission_id, "ERR_SUBMISSION_NOT_FOUND")
    limit, offset = pagination()
    statement_type = enum_filter("statement_type", C.STATEMENT_TYPES)
    rows = [d for d in store.ordered(store.disclosure_statements.values())
            if d["submission_id"] == submission_id
            and (statement_type is None or d["statement_type"] == statement_type)]
    items, total = paginate(rows, limit, offset, S.disclosure_statement)
    return array_response(items, limit, offset, total)
