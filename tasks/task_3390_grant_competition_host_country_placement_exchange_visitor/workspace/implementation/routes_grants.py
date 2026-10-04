"""Grant endpoints: grant-confirmation (final award), grant read, lifecycle
transitions (ACTIVATE / COMPLETE / TERMINATE), and grant-scoped listings that
live under the application path."""

from flask import Blueprint

import domain
import envelope
import serialize
from auth import auth, require_roles, check_owner
from constants import (
    ROLE_APPLICANT,
    ROLE_PROGRAM_OFFICER,
    ROLE_HOST_COMMISSION,
    ROLE_PLATFORM_ADMIN,
)
from errors import ApiError
from store import STORE, now
from timeutil import parse_iso
from validate import (
    body,
    check_unknown,
    req,
    as_dt,
    pagination,
    page_slice,
    V,
)

bp = Blueprint("grants", __name__)

GRANT_READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_PROGRAM_OFFICER, ROLE_HOST_COMMISSION, ROLE_APPLICANT)
GRANT_ACTIONS = ("ACTIVATE", "COMPLETE", "TERMINATE")


@bp.get("/exchange/applications/<aid>/grants")
def list_grants_of_application(aid):
    user, role = auth()
    require_roles(role, GRANT_READ_ROLES)
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    check_owner(role, user, application["applicant_id"])
    limit, offset = pagination()
    items = [g for g in STORE.grants.values() if g["application_id"] == aid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.grant_out(g) for g in page], total, limit, offset)


@bp.post("/exchange/applications/<aid>/grant-confirmation")
def grant_confirmation(aid):
    _, role = auth()
    require_roles(role, [ROLE_PROGRAM_OFFICER])
    application = STORE.applications.get(aid)
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", 404, "No application with the given id")
    grant = domain.grant_of_application(aid)
    # Priority 6: the grant must still be PROVISIONAL.
    if grant is not None and grant["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_STATE", 409, "Grant is not PROVISIONAL")
    payload = body()
    start = as_dt(req(payload, "start_date"), "start_date")
    end = as_dt(req(payload, "end_date"), "end_date")
    # Priority 8: start_date must not precede the logical clock's date.
    if start.date() < now().date():
        raise ApiError("ERR_START_DATE_IN_PAST", 409, "Grant start_date precedes the logical clock date")
    # Priority 9: structural validation.
    check_unknown(payload, {"start_date", "end_date"})
    if end <= start:
        raise V("end_date must be after start_date")
    program = STORE.programs[application["country_program_id"]]
    duration = (end.year - start.year) * 12 + (end.month - start.month)
    if duration < program["min_duration_months"] or duration > program["max_duration_months"]:
        raise ApiError(
            "ERR_DURATION_OUT_OF_RANGE", 422, "Confirmed duration is outside the program bounds"
        )
    # Priority 9: half-open [start_date, end_date) overlap with another live
    # grant of the same applicant; pure adjacency is permitted.
    applicant_id = application["applicant_id"]
    for other in STORE.grants.values():
        if grant is not None and other["id"] == grant["id"]:
            continue
        if other["status"] not in ("CONFIRMED", "ACTIVE", "SUSPENDED"):
            continue
        other_app = STORE.applications[other["application_id"]]
        if other_app["applicant_id"] != applicant_id:
            continue
        o_start = parse_iso(other["start_date"])
        o_end = parse_iso(other["end_date"])
        if start < o_end and o_start < end:
            raise ApiError(
                "ERR_GRANT_PERIOD_OVERLAP",
                409,
                "Confirmed period overlaps another live grant of the applicant",
            )
    # Priority 10: an accepted placement must exist (application GRANT_PENDING).
    if grant is None or application["status"] != "GRANT_PENDING":
        raise ApiError(
            "ERR_PLACEMENT_NOT_SECURED",
            409,
            "Grant confirmation requires an accepted placement round",
        )
    domain.confirm_grant(grant, application, start, end)
    return envelope.ok(serialize.grant_out(grant))


@bp.get("/exchange/grants/<gid>")
def get_grant(gid):
    user, role = auth()
    require_roles(role, GRANT_READ_ROLES)
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    check_owner(role, user, domain.applicant_of_grant(grant))
    return envelope.ok(serialize.grant_out(grant))


@bp.post("/exchange/grants/<gid>/transition")
def grant_transition(gid):
    _, role = auth()
    require_roles(role, [ROLE_PROGRAM_OFFICER])
    payload = body()
    # Priority 3: path existence precedes every other domain check (PRD 2.9).
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    check_unknown(payload, {"action", "termination_reason"})
    action = payload.get("action")
    if action is None:
        raise V("Missing required field: action")
    clock = now()

    if action == "ACTIVATE":
        if grant["status"] != "CONFIRMED":
            raise ApiError("ERR_INVALID_STATE", 409, "Only a CONFIRMED grant can be activated")
        # Priority 7: pre-departure orientation must be recorded.
        if grant["orientation_completed_at"] is None:
            raise ApiError(
                "ERR_ORIENTATION_INCOMPLETE",
                409,
                "Pre-departure orientation is not recorded (no visa sponsorship issued)",
            )
        # Priority 8: the logical clock must be at or past start_date.
        if clock < parse_iso(grant["start_date"]):
            raise ApiError(
                "ERR_START_DATE_NOT_REACHED", 409, "The grant start_date has not been reached"
            )
        domain.activate_grant(grant)
    elif action == "COMPLETE":
        if grant["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "Only an ACTIVE grant can be completed")
        if clock < parse_iso(grant["end_date"]):
            raise ApiError(
                "ERR_END_DATE_NOT_REACHED", 409, "The grant end_date has not been reached"
            )
        final_ok = any(
            r["grant_id"] == gid
            and r["report_type"] == "FINAL"
            and r["status"] in ("SUBMITTED", "ACCEPTED")
            for r in STORE.reports.values()
        )
        if not final_ok:
            raise ApiError(
                "ERR_FINAL_REPORT_MISSING",
                409,
                "No FINAL report in SUBMITTED or ACCEPTED status exists for this grant",
            )
        domain.complete_grant(grant)
    elif action == "TERMINATE":
        if grant["status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Only an ACTIVE or SUSPENDED grant can be terminated early",
            )
        # Termination requires the clock strictly before end_date; at or
        # beyond end_date, completion is the correct path.
        if clock >= parse_iso(grant["end_date"]):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "The grant end_date has been reached; use COMPLETE instead",
            )
        reason = payload.get("termination_reason")
        if reason is not None and not isinstance(reason, str):
            raise V("Field termination_reason must be a string")
        domain.terminate_grant(grant, reason)
    else:
        raise V("Unknown action for grant transition: %r" % action)
    return envelope.ok(serialize.grant_out(grant))


@bp.get("/exchange/grants/<gid>/alumni-profiles")
def list_alumni_by_grant(gid):
    user, role = auth()
    require_roles(role, GRANT_READ_ROLES)
    grant = STORE.grants.get(gid)
    if grant is None:
        raise ApiError("ERR_GRANT_NOT_FOUND", 404, "No grant with the given id")
    check_owner(role, user, domain.applicant_of_grant(grant))
    limit, offset = pagination()
    items = [p for p in STORE.alumni.values() if p["grant_id"] == gid]
    page, total = page_slice(items, limit, offset)
    return envelope.ok_list([serialize.alumni_out(p) for p in page], total, limit, offset)
