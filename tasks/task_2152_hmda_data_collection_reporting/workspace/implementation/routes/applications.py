"""Register record endpoints (PRD 3.2, 3.5)."""

from flask import Blueprint

import calc
import cascades
import constants as C
import serializers as S
import store
from auth import authenticate
from errors import fail
from response import array_response, object_response
from validate import (Field, bool_filter, check, enum_filter, json_body, lookup,
                      paginate, pagination)

bp = Blueprint("applications", __name__)

READ_ROLES = C.ALL_ROLES
BACK_OFFICE_READ_ROLES = ["SystemAdmin", "InstitutionAdmin", "ComplianceAnalyst",
                          "ComplianceOfficer", "Examiner"]

CREATE_FIELDS = [
    Field("institution_id", "string", required=True),
    Field("uli", "string", required=True),
    Field("application_date", "datetime", required=True),
    Field("application_channel", "string", required=True, enum=C.APPLICATION_CHANNELS),
    Field("loan_type", "string", required=True, enum=C.LOAN_TYPES),
    Field("loan_purpose", "string", required=True, enum=C.LOAN_PURPOSES),
    Field("occupancy_type", "string", required=True, enum=C.OCCUPANCY_TYPES),
    Field("lien_status", "string", required=True, enum=C.LIEN_STATUSES),
    Field("loan_amount_cents", "integer", required=True, minimum=1),
    Field("income_thousands", "integer"),
    Field("business_or_commercial_purpose", "boolean"),
    Field("open_end_line_of_credit", "boolean"),
    Field("supersedes_application_id", "string"),
]

PATCH_FIELDS = [
    Field("income_thousands", "integer"),
    Field("loan_amount_cents", "integer", minimum=1),
    Field("rate_spread", "number"),
    Field("purchaser_type", "string", enum=C.PURCHASER_TYPES),
    Field("denial_reason_codes", "array", member_enum=C.DENIAL_REASON_CODES),
    Field("occupancy_type", "string", enum=C.OCCUPANCY_TYPES),
    Field("lien_status", "string", enum=C.LIEN_STATUSES),
    Field("loan_purpose", "string", enum=C.LOAN_PURPOSES),
    Field("business_or_commercial_purpose", "boolean"),
]

ACTION_FIELDS = [
    Field("action_taken", "string", required=True, enum=C.ACTION_TAKEN_VALUES),
    Field("action_taken_date", "datetime", required=True),
    Field("denial_reason_codes", "array", member_enum=C.DENIAL_REASON_CODES),
    Field("purchaser_type", "string", enum=C.PURCHASER_TYPES),
    Field("rate_spread", "number"),
    Field("income_thousands", "integer"),
]

ADVANCE_FIELDS = [Field("to_stage", "string", required=True, enum=C.STAGES)]
REOPEN_FIELDS = [Field("reason", "string", required=True)]


@bp.route("/hmda/applications", methods=["POST"])
def create_application():
    authenticate(["LoanOfficer"])
    body = check(json_body(), CREATE_FIELDS)
    inst = lookup(store.institutions, body["institution_id"], "ERR_INSTITUTION_NOT_FOUND")
    superseded = None
    if body.get("supersedes_application_id") is not None:
        superseded = lookup(store.applications, body["supersedes_application_id"],
                            "ERR_APPLICATION_NOT_FOUND")
    for existing in store.applications.values():
        if (existing["institution_id"] == inst["id"]
                and existing["uli"] == body["uli"]
                and not existing["is_superseded"]):
            fail("ERR_DUPLICATE_ULI")

    row = store.new_row()
    row.update({
        "institution_id": inst["id"],
        "uli": body["uli"],
        "application_date": body["application_date"],
        "application_channel": body["application_channel"],
        "loan_type": body["loan_type"],
        "loan_purpose": body["loan_purpose"],
        "occupancy_type": body["occupancy_type"],
        "lien_status": body["lien_status"],
        "loan_amount_cents": body["loan_amount_cents"],
        "income_thousands": body.get("income_thousands"),
        "rate_spread": None,
        "purchaser_type": None,
        "denial_reason_codes": [],
        "business_or_commercial_purpose": bool(body.get("business_or_commercial_purpose") or False),
        "open_end_line_of_credit": bool(body.get("open_end_line_of_credit") or False),
        "action_taken": None,
        "action_taken_date": None,
        "supersedes_application_id": body.get("supersedes_application_id"),
        "is_superseded": False,
        "stage": "INTAKE",
        "lar_status": "PENDING_FIELDS",
        "captured_field_count": 0,
        "applicable_field_count": 0,
        "exclusion_reason": "NOT_EXCLUDED",
    })
    calc.application_completeness(row, inst)
    store.applications[row["id"]] = row

    if superseded is not None:
        superseded["is_superseded"] = True
        store.bump(superseded)

    calc.recompute_institution_counters(inst)
    store.bump(inst)
    return object_response(S.application(row), 201)


@bp.route("/hmda/applications/<app_id>", methods=["PATCH"])
def patch_application(app_id):
    authenticate(["LoanOfficer"])
    app = lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    body = check(json_body(), PATCH_FIELDS)
    if app["stage"] == "ARCHIVED":
        fail("ERR_APPLICATION_ARCHIVED")
    inst = store.institutions[app["institution_id"]]
    for spec in PATCH_FIELDS:
        if spec.name in body:
            app[spec.name] = body[spec.name]
    if app["denial_reason_codes"] is None:
        app["denial_reason_codes"] = []
    if app["business_or_commercial_purpose"] is None:
        app["business_or_commercial_purpose"] = False
    calc.application_completeness(app, inst)
    store.bump(app)
    calc.recompute_institution_counters(inst)
    store.bump(inst)
    return object_response(S.application(app))


@bp.route("/hmda/applications/<app_id>", methods=["GET"])
def get_application(app_id):
    authenticate(READ_ROLES)
    app = lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    return object_response(S.application(app))


@bp.route("/hmda/applications/<app_id>/advance", methods=["POST"])
def advance_application(app_id):
    authenticate(["LoanOfficer"])
    app = lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    body = check(json_body(), ADVANCE_FIELDS)
    to_stage = body["to_stage"]
    stage = app["stage"]

    if stage == "INTAKE" and to_stage == "UNDERWRITING":
        # step 9 cross-entity guard
        has_applicant = any(d["application_id"] == app["id"] and d["applicant_role"] == "APPLICANT"
                            for d in store.demographic_entries.values())
        if not has_applicant:
            fail("ERR_MISSING_APPLICANT_DEMOGRAPHICS")
    elif stage == "UNDERWRITING" and to_stage == "DECISIONED":
        if app["application_date"] > store.now():
            fail("ERR_INVALID_STAGE_TRANSITION")
    elif stage == "DECISIONED" and to_stage == "REGISTER_LOCKED":
        if app["action_taken"] is None:
            fail("ERR_INVALID_STAGE_TRANSITION")
        if app["lar_status"] not in ("COMPLETE", "EXCLUDED"):
            fail("ERR_INVALID_STAGE_TRANSITION")
        assignment = calc.current_assignment(app["id"])
        if assignment is None or assignment["status"] not in C.GEOCODE_RESOLVED:
            fail("ERR_GEOCODE_UNRESOLVED")
    else:
        fail("ERR_INVALID_STAGE_TRANSITION")

    app["stage"] = to_stage
    store.bump(app)
    inst = store.institutions[app["institution_id"]]
    calc.recompute_institution_counters(inst)
    return object_response(S.application(app))


@bp.route("/hmda/applications/<app_id>/action-taken", methods=["POST"])
def record_action_taken(app_id):
    authenticate(["LoanOfficer"])
    app = lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    body = check(json_body(), ACTION_FIELDS)
    if app["stage"] == "ARCHIVED":
        fail("ERR_APPLICATION_ARCHIVED")
    inst = store.institutions[app["institution_id"]]

    action = body["action_taken"]
    action_date = body["action_taken_date"]
    denial_codes = body["denial_reason_codes"] if "denial_reason_codes" in body \
        else app["denial_reason_codes"]
    if denial_codes is None:
        denial_codes = []
    purchaser = body["purchaser_type"] if "purchaser_type" in body else app["purchaser_type"]

    # step 12 -- cross-field referential accuracy, in the pinned order
    if action in C.DENIAL_ACTIONS:
        if not denial_codes:
            fail("ERR_DENIAL_REASON_REQUIRED")
    elif denial_codes:
        fail("ERR_DENIAL_REASON_NOT_PERMITTED")
    if action == "PURCHASED_LOAN" and (purchaser is None or purchaser == "NOT_APPLICABLE"):
        fail("ERR_PURCHASER_TYPE_REQUIRED")

    # step 13 -- action-date accuracy, in the pinned order
    if action_date < app["application_date"]:
        fail("ERR_ACTION_DATE_BEFORE_APPLICATION")
    if action_date > store.now():
        fail("ERR_ACTION_DATE_IN_FUTURE")
    if action_date.year != inst["activity_year"]:
        fail("ERR_ACTION_DATE_OUTSIDE_ACTIVITY_YEAR")

    app["action_taken"] = action
    app["action_taken_date"] = action_date
    app["denial_reason_codes"] = denial_codes
    if "purchaser_type" in body:
        app["purchaser_type"] = body["purchaser_type"]
    if "rate_spread" in body:
        app["rate_spread"] = body["rate_spread"]
    if "income_thousands" in body:
        app["income_thousands"] = body["income_thousands"]

    calc.application_completeness(app, inst)
    store.bump(app)
    calc.recompute_institution_counters(inst)
    store.bump(inst)
    return object_response(S.application(app))


@bp.route("/hmda/applications/<app_id>/reopen", methods=["POST"])
def reopen_application(app_id):
    authenticate(["ComplianceAnalyst"])
    app = lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    check(json_body(), REOPEN_FIELDS)
    if app["stage"] != "REGISTER_LOCKED":
        fail("ERR_INVALID_STAGE_TRANSITION")
    inst = store.institutions[app["institution_id"]]
    cascades.reopen_cascade(app, inst)
    store.bump(app)
    store.bump(inst)
    return object_response(S.application(app))


# ---------------------------------------------------------------------------
# Reverse-reachability sub-resource listings
# ---------------------------------------------------------------------------

@bp.route("/hmda/applications/<app_id>/corrections", methods=["GET"])
def list_corrections(app_id):
    authenticate(READ_ROLES)
    lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    limit, offset = pagination()
    rows = [a for a in store.ordered(store.applications.values())
            if a["supersedes_application_id"] == app_id]
    items, total = paginate(rows, limit, offset, S.application)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/applications/<app_id>/demographic-entries", methods=["GET"])
def list_demographic_entries(app_id):
    authenticate(READ_ROLES)
    lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    limit, offset = pagination()
    applicant_role = enum_filter("applicant_role", C.APPLICANT_ROLES)
    rows = [d for d in store.ordered(store.demographic_entries.values())
            if d["application_id"] == app_id
            and (applicant_role is None or d["applicant_role"] == applicant_role)]
    items, total = paginate(rows, limit, offset, S.demographic_entry)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/applications/<app_id>/geocode-assignments", methods=["GET"])
def list_geocode_assignments(app_id):
    authenticate(READ_ROLES)
    lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    limit, offset = pagination()
    is_current = bool_filter("is_current")
    rows = [g for g in store.ordered(store.geocode_assignments.values())
            if g["application_id"] == app_id
            and (is_current is None or g["is_current"] is is_current)]
    items, total = paginate(rows, limit, offset, S.geocode_assignment)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/applications/<app_id>/edit-exceptions", methods=["GET"])
def list_edit_exceptions(app_id):
    authenticate(READ_ROLES)
    lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    limit, offset = pagination()
    status = enum_filter("status", C.EDIT_EXCEPTION_STATUSES)
    severity = enum_filter("severity", C.EDIT_SEVERITIES)
    rows = [e for e in store.ordered(store.edit_exceptions.values())
            if e["application_id"] == app_id
            and (status is None or e["status"] == status)
            and (severity is None or e["severity"] == severity)]
    items, total = paginate(rows, limit, offset, S.edit_exception)
    return array_response(items, limit, offset, total)


@bp.route("/hmda/applications/<app_id>/audit-findings", methods=["GET"])
def list_audit_findings(app_id):
    authenticate(BACK_OFFICE_READ_ROLES)
    lookup(store.applications, app_id, "ERR_APPLICATION_NOT_FOUND")
    limit, offset = pagination()
    resolution = enum_filter("resolution", C.FINDING_RESOLUTIONS)
    rows = [f for f in store.ordered(store.audit_findings.values())
            if f["application_id"] == app_id
            and (resolution is None or f["resolution"] == resolution)]
    items, total = paginate(rows, limit, offset, S.audit_finding)
    return array_response(items, limit, offset, total)
