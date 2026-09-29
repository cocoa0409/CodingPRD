"""Pitch intake: submission, coverage, rights clearance and advancement."""

from flask import Blueprint, request

import domain as d
from auth import (ROLE_AGENCY_REP, ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC,
                  ROLE_PLATFORM_ADMIN, agency_scope_guard, authorize)
from errors import ApiError
from responses import object_response, paginated
from store import add_days, new_row, store, touch
from validators import (json_body, require_body, v_date, v_decimal, v_enum,
                        v_string, v_string_array)

bp = Blueprint("pitch", __name__)


def _new_project(pitch, slate, predecessor_project_id=None, title=None):
    row = new_row(
        pitch_id=pitch["id"],
        slate_id=slate["id"],
        predecessor_project_id=predecessor_project_id,
        title=title if title is not None else pitch["title"],
        dev_status="ACTIVE_DEVELOPMENT",
        turnaround_status="NONE",
        turnaround_offered_at=None,
        writeoff_cents=0,
        abandoned_at=None,
        abandon_reason=None,
        recoupment_paid_cents=0,
    )
    store.projects[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# pitches
# ---------------------------------------------------------------------------

@bp.post("/pitches")
@authorize(ROLE_AGENCY_REP)
def create_pitch(principal):
    body = json_body()
    raw_agency_id = body.get("agency_id") if isinstance(body, dict) else None
    agency_scope_guard(principal, raw_agency_id)
    require_body(body)

    agency = d.get_agency(raw_agency_id)
    slate = d.get_slate(body.get("slate_id"))

    title = v_string(body, "title", max_len=160)
    logline = v_string(body, "logline", max_len=600)
    packaging_elements = v_string_array(body, "packaging_elements",
                                       max_entries=6, max_len=200)
    underlying_ip_key = v_string(body, "underlying_ip_key", required=False,
                                 max_len=80, allow_null=True, default=None)

    # 23 -- packaging permission.
    if packaging_elements and not agency["packaging_allowed"]:
        raise ApiError("ERR_PACKAGING_NOT_PERMITTED")

    # 41 -- the agency's per-season allotment.
    used = d.submissions_used_count(agency, slate["season_year"])
    if used >= d.effective_submission_cap(agency):
        raise ApiError("ERR_AGENCY_SUBMISSION_CAP_REACHED")

    row = new_row(
        agency_id=agency["id"],
        slate_id=slate["id"],
        title=title,
        logline=logline,
        packaging_elements=packaging_elements,
        underlying_ip_key=underlying_ip_key,
        status="SUBMITTED",
        coverage_score=None,
        coverage_round=0,
        recommendation=None,
    )
    store.pitches[row["id"]] = row
    return object_response(d.serialize_pitch(row), 201)


@bp.get("/pitches/<pitch_id>")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_AGENCY_REP)
def read_pitch(principal, pitch_id):
    row = d.get_pitch(pitch_id)
    agency_scope_guard(principal, row["agency_id"])
    return object_response(d.serialize_pitch(row))


@bp.get("/pitches")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_DEV_EXEC, ROLE_BUSINESS_AFFAIRS, ROLE_AGENCY_REP)
def list_pitches(principal):
    agency_id = request.args.get("agency_id")
    if principal.is_agency_rep:
        if agency_id is not None and agency_id != principal.user_id:
            raise ApiError("ERR_AGENCY_SCOPE_VIOLATION")
        agency_id = principal.user_id

    rows = d.ordered(list(store.pitches.values()))
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    slate_id = request.args.get("slate_id")
    if slate_id is not None:
        rows = [r for r in rows if r["slate_id"] == slate_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, d.serialize_pitch)


@bp.post("/pitches/<pitch_id>/coverage")
@authorize(ROLE_DEV_EXEC)
def record_coverage(principal, pitch_id):
    pitch = d.get_pitch(pitch_id)
    body = require_body(json_body())
    score = v_decimal(body, "coverage_score", minimum=0, maximum=100, max_places=1)
    recommendation = v_enum(body, "recommendation", d.RECOMMENDATIONS)

    if pitch["status"] not in ("SUBMITTED", "COVERED"):
        raise ApiError("ERR_INVALID_PITCH_STATE")

    pitch["coverage_score"] = score
    pitch["recommendation"] = recommendation
    pitch["coverage_round"] = pitch["coverage_round"] + 1
    if recommendation == "ADVANCE":
        pitch["status"] = "COVERED"
    else:
        pitch["status"] = "PASSED"
    touch(pitch)
    return object_response(d.serialize_pitch(pitch))


# ---------------------------------------------------------------------------
# rights checks
# ---------------------------------------------------------------------------

@bp.post("/pitches/<pitch_id>/rights-checks")
@authorize(ROLE_BUSINESS_AFFAIRS)
def file_rights_check(principal, pitch_id):
    pitch = d.get_pitch(pitch_id)
    body = require_body(json_body())
    ip_key = v_string(body, "underlying_ip_key", max_len=80)
    chain = v_enum(body, "chain_of_title_status", d.CHAIN_OF_TITLE_STATUSES)
    holdback_start = v_date(body, "holdback_start_date")
    holdback_end = v_date(body, "holdback_end_date")
    if holdback_end < holdback_start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "holdback_end_date must be on or after holdback_start_date.")

    row = new_row(
        with_version=False,
        pitch_id=pitch["id"],
        underlying_ip_key=ip_key,
        chain_of_title_status=chain,
        holdback_start_date=holdback_start,
        holdback_end_date=holdback_end,
        quiet_period_end_date=add_days(holdback_end, d.RIGHTS_QUIET_BUFFER_DAYS),
        result=d.RIGHTS_RESULT_BY_CHAIN[chain],
    )
    store.rights_checks[row["id"]] = row
    return object_response(d.serialize_rights_check(row), 201)


@bp.get("/pitches/<pitch_id>/rights-checks")
@authorize(ROLE_PLATFORM_ADMIN, ROLE_BUSINESS_AFFAIRS, ROLE_DEV_EXEC)
def list_rights_checks(principal, pitch_id):
    pitch = d.get_pitch(pitch_id)
    return paginated(d.rights_checks_of_pitch(pitch), d.serialize_rights_check)


# ---------------------------------------------------------------------------
# advancement
# ---------------------------------------------------------------------------

@bp.post("/pitches/<pitch_id>/advance")
@authorize(ROLE_DEV_EXEC)
def advance_pitch(principal, pitch_id):
    pitch = d.get_pitch(pitch_id)

    # 10 -- the pitch must be COVERED with a standing ADVANCE recommendation.
    if pitch["status"] != "COVERED" or pitch["recommendation"] != "ADVANCE":
        raise ApiError("ERR_INVALID_PITCH_STATE")

    # 24 -- the newest rights check must have come back CLEAR.
    checks = d.rights_checks_of_pitch(pitch)
    if not checks:
        raise ApiError("ERR_RIGHTS_NOT_CLEAR")
    newest = checks[-1]
    if newest["result"] != "CLEAR":
        raise ApiError("ERR_RIGHTS_NOT_CLEAR")

    # 28 -- the property must be free of holdback and quiet buffer today.
    today = store.today()
    if newest["holdback_start_date"] <= today <= newest["quiet_period_end_date"]:
        raise ApiError("ERR_RIGHTS_HOLDBACK_CONFLICT")

    # 33 -- the slate must not be LOCKED.
    slate = d.get_slate(pitch["slate_id"])
    d.require_slate_not_locked(slate)

    pitch["status"] = "ADVANCED"
    touch(pitch)
    project = _new_project(pitch, slate)
    touch(slate)
    return object_response(d.serialize_project(project), 201)
