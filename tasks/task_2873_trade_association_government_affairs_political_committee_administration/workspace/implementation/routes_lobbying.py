"""Lobbying registration and activity endpoints (PRD 3.5)."""
from flask import Blueprint

import derive
from constants import ACTIVITY_KINDS, API_PREFIX, JURISDICTIONS, hours3
from core import (
    arg, authenticate, body, fail, filtered, format_instant, insert, iso_date, now_dt,
    parse_date, respond, touch,
)
from serializers import dump, listing
from validate import get_date, get_enum, get_hours, get_int, get_str

bp = Blueprint("lobbying", __name__, url_prefix=API_PREFIX)

REG_READ_ROLES = ["ComplianceOfficer", "GovAffairsDirector", "BoardTrustee"]


def _registration(registration_id):
    return derive.lookup("registrations", registration_id, "ERR_REGISTRATION_NOT_FOUND")


@bp.post("/lobbying-registrations")
def draft_registration():
    authenticate(["ComplianceOfficer"])
    payload = body()
    jurisdiction_code = get_enum(payload, "jurisdiction_code", JURISDICTIONS)
    registrant_name = get_str(payload, "registrant_name", max_len=200)
    coverage_start_date = get_date(payload, "coverage_start_date")
    coverage_end_date = get_date(payload, "coverage_end_date")
    if coverage_end_date <= coverage_start_date:
        fail("ERR_INVALID_REQUEST",
             "Field 'coverage_end_date' must be strictly later than 'coverage_start_date'.")
    registration = insert("registrations", {
        "jurisdiction_code": jurisdiction_code,
        "registrant_name": registrant_name,
        "coverage_start_date": iso_date(coverage_start_date),
        "coverage_end_date": iso_date(coverage_end_date),
        "status": "DRAFT",
        "filed_at": None,
        "amendment_round": 0,
        "ytd_reportable_cents": 0,
        "ytd_reportable_hours": 0.0,
        "terminated_at": None,
    })
    return respond(dump("registrations", registration), status=201)


@bp.get("/lobbying-registrations/<registration_id>")
def read_registration(registration_id):
    authenticate(REG_READ_ROLES)
    return respond(dump("registrations", _registration(registration_id)))


@bp.post("/lobbying-registrations/<registration_id>/file")
def file_registration(registration_id):
    authenticate(["ComplianceOfficer"])
    registration = _registration(registration_id)
    if registration["status"] != "DRAFT":
        fail("ERR_INVALID_REGISTRATION_STATE", "Only a DRAFT registration can be filed.")
    start = parse_date(registration["coverage_start_date"])
    end = parse_date(registration["coverage_end_date"])
    for other in derive.rows_of("registrations"):
        if other["id"] == registration_id:
            continue
        if other["status"] not in ("ACTIVE", "AMENDMENT_PENDING"):
            continue
        if other["jurisdiction_code"] != registration["jurisdiction_code"]:
            continue
        if other["registrant_name"] != registration["registrant_name"]:
            continue
        if derive.coverage_windows_overlap(
                start, end, parse_date(other["coverage_start_date"]),
                parse_date(other["coverage_end_date"])):
            fail("ERR_REGISTRATION_COVERAGE_OVERLAP",
                 "A live registration already covers these days for this registrant.")
    registration["status"] = "ACTIVE"
    registration["filed_at"] = format_instant(now_dt())
    touch(registration)
    return respond(dump("registrations", registration))


@bp.post("/lobbying-registrations/<registration_id>/amend")
def amend_registration(registration_id):
    authenticate(["ComplianceOfficer"])
    registration = _registration(registration_id)
    if registration["status"] != "ACTIVE":
        fail("ERR_INVALID_REGISTRATION_STATE",
             "Only an ACTIVE registration can enter amendment.")
    registration["status"] = "AMENDMENT_PENDING"
    touch(registration)
    return respond(dump("registrations", registration))


@bp.post("/lobbying-registrations/<registration_id>/certify-amendment")
def certify_amendment(registration_id):
    authenticate(["ComplianceOfficer"])
    registration = _registration(registration_id)
    if registration["status"] != "AMENDMENT_PENDING":
        fail("ERR_INVALID_REGISTRATION_STATE",
             "Only an AMENDMENT_PENDING registration can be certified.")
    registration["status"] = "ACTIVE"
    registration["amendment_round"] = registration["amendment_round"] + 1
    touch(registration)
    return respond(dump("registrations", registration))


@bp.post("/lobbying-registrations/<registration_id>/terminate")
def terminate_registration(registration_id):
    authenticate(["ComplianceOfficer"])
    registration = _registration(registration_id)
    if registration["status"] != "ACTIVE":
        fail("ERR_INVALID_REGISTRATION_STATE", "Only an ACTIVE registration can be terminated.")
    for report in derive.where("reports", registration_id=registration_id):
        if report["status"] == "OPEN":
            fail("ERR_OPEN_REPORT_BLOCKS_TERMINATION",
                 "An expenditure report of this registration is still OPEN.")
    registration["status"] = "TERMINATED"
    registration["terminated_at"] = format_instant(now_dt())
    touch(registration)
    return respond(dump("registrations", registration))


@bp.get("/lobbying-registrations/<registration_id>/activities")
def list_registration_activities(registration_id):
    authenticate(REG_READ_ROLES)
    _registration(registration_id)
    rows = filtered(derive.registration_activities(registration_id), status=arg("status"))
    return listing("activities", rows)


@bp.get("/lobbying-registrations/<registration_id>/expenditure-reports")
def list_registration_reports(registration_id):
    authenticate(REG_READ_ROLES)
    _registration(registration_id)
    rows = filtered(derive.where("reports", registration_id=registration_id),
                    status=arg("status"), period_code=arg("period_code"))
    return listing("reports", rows)


@bp.post("/lobbying-activities")
def log_activity():
    authenticate(["GovAffairsDirector"])
    payload = body()
    registration_id = get_str(payload, "registration_id")
    position_id = get_str(payload, "position_id")
    activity_kind = get_enum(payload, "activity_kind", ACTIVITY_KINDS)
    activity_date = get_date(payload, "activity_date")
    hours = get_hours(payload, "hours")
    expenditure_cents = get_int(payload, "expenditure_cents", minimum=0)
    coalition_partner_name = get_str(payload, "coalition_partner_name", required=False,
                                     max_len=200, allow_blank=True)
    registration = _registration(registration_id)
    position = derive.lookup("positions", position_id, "ERR_POSITION_NOT_FOUND")
    if registration["status"] != "ACTIVE":
        fail("ERR_REGISTRATION_NOT_ACTIVE",
             "Activity may only be logged under an ACTIVE registration.")
    if position["status"] != "ADOPTED":
        fail("ERR_POSITION_NOT_ADOPTED", "Only an ADOPTED position may be cited.")
    partner_given = bool(coalition_partner_name and coalition_partner_name.strip())
    if activity_kind in ("COALITION_CONTRIBUTION", "THIRD_PARTY_ADVOCACY") and not partner_given:
        fail("ERR_COALITION_PARTNER_REQUIRED",
             "coalition_partner_name is mandatory for %s." % activity_kind)
    start = parse_date(registration["coverage_start_date"])
    end = parse_date(registration["coverage_end_date"])
    if not (start <= activity_date <= end):
        fail("ERR_ACTIVITY_OUTSIDE_COVERAGE",
             "activity_date lies outside the registration's coverage window.")
    if hours == 0 and expenditure_cents == 0:
        fail("ERR_EMPTY_ACTIVITY", "An activity must record hours or expenditure.")
    disclosure = activity_kind == "THIRD_PARTY_ADVOCACY" or (
        activity_kind == "COALITION_CONTRIBUTION"
        and expenditure_cents >= 500000)
    activity = insert("activities", {
        "registration_id": registration_id,
        "position_id": position_id,
        "activity_kind": activity_kind,
        "coalition_partner_name": coalition_partner_name,
        "third_party_disclosure_required": disclosure,
        "activity_date": iso_date(activity_date),
        "hours": hours3(hours),
        "expenditure_cents": expenditure_cents,
        "staff_cost_cents": derive.staff_cost_for(hours),
        "logged_at": format_instant(now_dt()),
        "status": "LOGGED",
        "void_reason": None,
    })
    derive.compute_registration_totals(registration)
    threshold = derive.rule(registration["jurisdiction_code"])["registration_threshold_cents"]
    if (registration["amendment_round"] == 0
            and registration["status"] == "ACTIVE"
            and registration["ytd_reportable_cents"] >= threshold):
        registration["status"] = "AMENDMENT_PENDING"
    touch(registration)
    derive.refresh_open_reports(activity)
    return respond(dump("activities", activity), status=201)


@bp.post("/lobbying-activities/<activity_id>/void")
def void_activity(activity_id):
    authenticate(["GovAffairsDirector"])
    activity = derive.lookup("activities", activity_id, "ERR_ACTIVITY_NOT_FOUND")
    payload = body()
    void_reason = get_str(payload, "void_reason", max_len=500)
    if activity["status"] == "VOIDED":
        fail("ERR_ACTIVITY_ALREADY_VOIDED", "This activity has already been voided.")
    if derive.reports_covering_activity(activity, ("CERTIFIED",)):
        fail("ERR_ACTIVITY_IN_CERTIFIED_REPORT",
             "A certified expenditure report already includes this activity.")
    activity["status"] = "VOIDED"
    activity["void_reason"] = void_reason
    touch(activity)
    registration = _registration(activity["registration_id"])
    derive.compute_registration_totals(registration)
    touch(registration)
    derive.refresh_open_reports(activity)
    return respond(dump("activities", activity))
