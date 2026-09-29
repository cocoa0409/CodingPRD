"""Sanctioned activities and injury reports."""

from flask import Blueprint, g

import auth
import constants as C
import db
import guards
import response
import services
import util
import validation as v
from errors import ApiError

bp = Blueprint("activity", __name__)

_ACTIVITY_READERS = [
    "ProgramAdministrator", "LeagueAdministrator", "LeagueOfficial", "ClaimsExaminer",
]
_REPORT_READERS = [
    "ProgramAdministrator", "LeagueAdministrator", "LeagueOfficial", "ClaimsExaminer",
    "MedicalReviewer",
]


# ------------------------------------------------------- sanctioned activities

@bp.post("/sanctioned-activities")
def create_activity():
    auth.require_roles(["LeagueAdministrator"])
    body = v.json_body()
    auth.early_ownership("league_policy", body.get("league_policy_id"))
    policy_id = v.req_id(body, "league_policy_id")
    activity_type = v.req_enum(body, "activity_type", C.ACTIVITY_TYPES)
    venue_name = v.req_str(body, "venue_name")
    starts_at = v.req_instant(body, "starts_at")
    ends_at = v.req_instant(body, "ends_at")
    buffer_minutes = v.req_int(body, "travel_buffer_minutes", required=False,
                              default=None, minimum=0)
    policy = guards.resolve("league_policy", policy_id)
    auth.check_ownership(policy)
    guards.require_policy_in_force(policy, ("BOUND", "ACTIVE"))
    guards.require_league_sanctioned(policy)
    guards.require_not_frozen(policy)
    sport = guards.sport_of_policy(policy)
    if buffer_minutes is None:
        buffer_minutes = sport["travel_buffer_minutes"]
    if starts_at > ends_at:
        raise ApiError("ERR_ACTIVITY_OUTSIDE_TERM")
    if not guards.instant_in_term(policy, starts_at) or not guards.instant_in_term(policy, ends_at):
        raise ApiError("ERR_ACTIVITY_OUTSIDE_TERM")
    if services.conflicting_activity(policy["id"], starts_at, ends_at, buffer_minutes):
        raise ApiError("ERR_PARTICIPANT_ACTIVITY_CONFLICT")
    row = db.new_row("sanctioned_activities", {
        "league_policy_id": policy["id"],
        "activity_type": activity_type,
        "venue_name": venue_name,
        "starts_at": util.format_datetime(starts_at),
        "ends_at": util.format_datetime(ends_at),
        "travel_buffer_minutes": buffer_minutes,
        "status": "PENDING_SANCTION",
        "sanctioning_official_id": None,
        "rejection_reason": None,
        "is_covered_activity": activity_type in C.COVERED_ACTIVITY_TYPES,
    })
    response.mark_fresh(row)
    return response.respond_obj(row, 201)


@bp.get("/sanctioned-activities/<sanctioned_activity_id>")
def get_activity(sanctioned_activity_id):
    auth.require_roles(_ACTIVITY_READERS)
    row = guards.resolve("sanctioned_activity", sanctioned_activity_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/sanctioned-activities")
def list_activities():
    auth.require_roles(_ACTIVITY_READERS)
    limit, offset = v.pagination()
    policy_id = v.query_str("league_policy_id")
    status = v.query_enum("status", C.ACTIVITY_STATUSES)
    activity_type = v.query_enum("activity_type", C.ACTIVITY_TYPES)
    rows = db.all_rows("sanctioned_activities")
    if policy_id is not None:
        rows = [r for r in rows if r["league_policy_id"] == policy_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if activity_type is not None:
        rows = [r for r in rows if r["activity_type"] == activity_type]
    return response.respond_list(rows, limit, offset)


@bp.post("/sanctioned-activities/<sanctioned_activity_id>/sanction-decision")
def decide_activity(sanctioned_activity_id):
    auth.require_roles(["LeagueOfficial"])
    activity = guards.resolve("sanctioned_activity", sanctioned_activity_id)
    body = v.json_body()
    decision = v.req_enum(body, "decision", C.ACTIVITY_DECISIONS)
    v.req_str(body, "reason", required=False, default=None)
    if activity["status"] != "PENDING_SANCTION":
        raise ApiError("ERR_INVALID_ACTIVITY_STATE")
    policy = db.get("league_policies", activity["league_policy_id"])
    if decision == "SANCTION":
        guards.require_policy_in_force(policy, ("BOUND", "ACTIVE"))
        guards.require_not_frozen(policy)
        services.touch(activity, status="SANCTIONED", sanctioning_official_id=g.user_id)
    else:
        services.touch(activity, status="REJECTED", rejection_reason="OFFICIAL_DECLINED")
    return response.respond_obj(activity)


# -------------------------------------------------------------- injury reports

def _verification_window_expired(report):
    created = util.parse_datetime(report["created_at"])
    return util.day_diff(db.now(), created) > C.VERIFICATION_WINDOW_DAYS


@bp.post("/injury-reports")
def create_injury_report():
    auth.require_roles(["LeagueAdministrator"])
    body = v.json_body()
    auth.early_ownership("enrollment", body.get("enrollment_id"))
    enrollment_id = v.req_id(body, "enrollment_id")
    activity_id = v.req_id(body, "sanctioned_activity_id")
    injury_datetime = v.req_instant(body, "injury_datetime")
    body_part = v.req_enum(body, "body_part", C.BODY_PARTS)
    description = v.req_str(body, "injury_description")
    severity_tier = v.req_enum(body, "severity_tier", C.SEVERITY_TIERS)
    enrollment = guards.resolve("enrollment", enrollment_id)
    activity = guards.resolve("sanctioned_activity", activity_id)
    auth.check_ownership(enrollment)
    if activity["league_policy_id"] != enrollment["league_policy_id"]:
        raise ApiError("ERR_SCOPE_MISMATCH")
    if enrollment["status"] != "ENROLLED":
        raise ApiError("ERR_INVALID_ENROLLMENT_STATE")
    policy = db.get("league_policies", enrollment["league_policy_id"])
    guards.require_policy_in_force(policy, ("ACTIVE",))
    guards.require_league_sanctioned(policy)
    guards.require_not_frozen(policy)
    if not activity["is_covered_activity"]:
        raise ApiError("ERR_ACTIVITY_NOT_COVERED")
    if activity["status"] == "REJECTED":
        raise ApiError("ERR_ACTIVITY_NOT_SANCTIONED")
    starts_at = util.parse_datetime(activity["starts_at"])
    ends_at = util.parse_datetime(activity["ends_at"])
    if not (starts_at <= injury_datetime <= ends_at):
        raise ApiError("ERR_INJURY_OUTSIDE_ACTIVITY_WINDOW")
    reported_on = util.midnight(db.now())
    days_to_report = util.day_diff(reported_on, injury_datetime)
    if days_to_report > C.FILING_WINDOW_DAYS:
        raise ApiError("ERR_FILING_WINDOW_EXPIRED")
    if enrollment["coverage_status"] == "LIFETIME_EXHAUSTED":
        raise ApiError("ERR_LIFETIME_BENEFIT_EXHAUSTED")
    row = db.new_row("injury_reports", {
        "enrollment_id": enrollment["id"],
        "sanctioned_activity_id": activity["id"],
        "injury_datetime": util.format_datetime(injury_datetime),
        "body_part": body_part,
        "injury_description": description,
        "severity_tier": severity_tier,
        "reported_on_date": util.format_datetime(reported_on),
        "days_to_report": days_to_report,
        "status": "PENDING_VERIFICATION",
        "correction_round_count": 0,
        "correction_note": None,
        "verifying_official_id": None,
        "verified_at": None,
        "official_attestation": None,
        "rejection_reason": None,
    })
    response.mark_fresh(row)
    return response.respond_obj(row, 201)


@bp.get("/injury-reports/<injury_report_id>")
def get_injury_report(injury_report_id):
    auth.require_roles(_REPORT_READERS)
    row = guards.resolve("injury_report", injury_report_id)
    auth.check_ownership(row)
    return response.respond_obj(row)


@bp.get("/injury-reports")
def list_injury_reports():
    auth.require_roles(_REPORT_READERS)
    limit, offset = v.pagination()
    enrollment_id = v.query_str("enrollment_id")
    activity_id = v.query_str("sanctioned_activity_id")
    status = v.query_enum("status", C.REPORT_STATUSES)
    severity_tier = v.query_enum("severity_tier", C.SEVERITY_TIERS)
    rows = db.all_rows("injury_reports")
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if activity_id is not None:
        rows = [r for r in rows if r["sanctioned_activity_id"] == activity_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if severity_tier is not None:
        rows = [r for r in rows if r["severity_tier"] == severity_tier]
    return response.respond_list(rows, limit, offset)


@bp.post("/injury-reports/<injury_report_id>/return-for-correction")
def return_report(injury_report_id):
    auth.require_roles(["LeagueOfficial"])
    report = guards.resolve("injury_report", injury_report_id)
    body = v.json_body()
    note = v.req_str(body, "correction_note")
    if report["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_REPORT_STATE")
    enrollment = db.get("enrollments", report["enrollment_id"])
    policy = db.get("league_policies", enrollment["league_policy_id"])
    guards.require_policy_in_force(policy, ("ACTIVE",))
    activity = db.get("sanctioned_activities", report["sanctioned_activity_id"])
    if activity["sanctioning_official_id"] == g.user_id:
        raise ApiError("ERR_OFFICIAL_SEGREGATION_VIOLATION")
    if report["correction_round_count"] >= C.MAX_CORRECTION_ROUNDS:
        raise ApiError("ERR_CORRECTION_ROUNDS_EXHAUSTED")
    services.touch(
        report,
        status="RETURNED_FOR_CORRECTION",
        correction_round_count=report["correction_round_count"] + 1,
        correction_note=note,
    )
    return response.respond_obj(report)


@bp.post("/injury-reports/<injury_report_id>/resubmit")
def resubmit_report(injury_report_id):
    auth.require_roles(["LeagueAdministrator"])
    report = guards.resolve("injury_report", injury_report_id)
    auth.check_ownership(report)
    body = v.json_body()
    description = v.req_str(body, "injury_description")
    severity_tier = v.req_enum(body, "severity_tier", C.SEVERITY_TIERS)
    if report["status"] != "RETURNED_FOR_CORRECTION":
        raise ApiError("ERR_INVALID_REPORT_STATE")
    enrollment = db.get("enrollments", report["enrollment_id"])
    policy = db.get("league_policies", enrollment["league_policy_id"])
    guards.require_policy_in_force(policy, ("ACTIVE",))
    guards.require_not_frozen(policy)
    if _verification_window_expired(report):
        raise ApiError("ERR_VERIFICATION_WINDOW_EXPIRED")
    services.touch(
        report,
        status="PENDING_VERIFICATION",
        injury_description=description,
        severity_tier=severity_tier,
    )
    return response.respond_obj(report)


@bp.post("/injury-reports/<injury_report_id>/verification-decision")
def decide_report(injury_report_id):
    auth.require_roles(["LeagueOfficial"])
    report = guards.resolve("injury_report", injury_report_id)
    body = v.json_body()
    decision = v.req_enum(body, "decision", C.VERIFY_DECISIONS)
    attestation = v.req_str(body, "official_attestation", required=(decision == "VERIFY"),
                            default=None)
    v.req_str(body, "reason", required=False, default=None)
    if report["status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_REPORT_STATE")
    enrollment = db.get("enrollments", report["enrollment_id"])
    policy = db.get("league_policies", enrollment["league_policy_id"])
    activity = db.get("sanctioned_activities", report["sanctioned_activity_id"])
    guards.require_policy_in_force(policy, ("ACTIVE",))
    if decision == "VERIFY":
        # Ladder priority 11 outranks every coverage-safety and temporal check below.
        guards.require_not_frozen(policy)
    if activity["sanctioning_official_id"] == g.user_id:
        raise ApiError("ERR_OFFICIAL_SEGREGATION_VIOLATION")
    if decision == "REJECT":
        services.touch(
            report,
            status="REJECTED",
            rejection_reason="OFFICIAL_DECLINED",
            verifying_official_id=g.user_id,
        )
        return response.respond_obj(report)
    if activity["status"] != "SANCTIONED":
        raise ApiError("ERR_ACTIVITY_NOT_SANCTIONED")
    if not activity["is_covered_activity"]:
        raise ApiError("ERR_ACTIVITY_NOT_COVERED")
    if _verification_window_expired(report):
        raise ApiError("ERR_VERIFICATION_WINDOW_EXPIRED")
    if enrollment["coverage_status"] == "LIFETIME_EXHAUSTED":
        raise ApiError("ERR_LIFETIME_BENEFIT_EXHAUSTED")
    services.touch(
        report,
        status="VERIFIED",
        verified_at=db.now_iso(),
        verifying_official_id=g.user_id,
        official_attestation=attestation,
    )
    claim = services.open_claim_from_report(report, enrollment, policy)
    response.mark_fresh(claim)
    services.recompute_policy(policy)
    return response.respond_obj(report)
