"""Referral intake (PRD 3.3) and the seating decisions (PRD 3.4)."""
from flask import Blueprint

import derive
import validate as v
from auth import endpoint, scope_center, scope_school
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import eq, get_center, get_referral, get_student, q
from services import clock_date_plus, rederive_center
from store import D, new_row, ordered, store, touch

bp = Blueprint("referrals", __name__)

PATHWAYS = ("BEHAVIOR", "CREDIT_DEFICIENCY", "RE_ENGAGEMENT")
CREDIT_POLICIES = ("SEAT_TIME", "COMPETENCY")


def _student_of(referral):
    return store.students.get(referral["student_id"])


def _school_scope(ctx, referral):
    student = _student_of(referral)
    if student is not None:
        scope_school(ctx, student["home_school_id"])


@bp.post("/referrals")
@endpoint("HomeSchoolCounselor")
def create_referral(ctx):
    b = v.body()
    student_id = v.req_str(b, "student_id", 1, None)
    center_id = v.req_str(b, "center_id", 1, None)
    pathway = v.req_enum(b, "pathway", PATHWAYS)
    deficiency_credits = v.req_num(b, "deficiency_credits", lo=0, step="0.25")
    behavior_incident_count = v.req_int(b, "behavior_incident_count", 0, None)
    days_disengaged = v.req_int(b, "days_disengaged", 0, None)
    narrative = v.opt_str(b, "narrative", 1, 2000)
    prior_referral_id = v.opt_str(b, "prior_referral_id", 1, None)
    student = get_student(student_id)
    get_center(center_id)
    if prior_referral_id is not None:
        get_referral(prior_referral_id)
    scope_school(ctx, student["home_school_id"])
    for other in store.referrals.values():
        if other["student_id"] == student_id and \
                other["status"] in derive.NON_TERMINAL_REFERRAL_STATES:
            raise ApiError("ERR_DUPLICATE_ACTIVE_REFERRAL",
                           "the student already holds a referral in flight")
    row = new_row(
        student_id=student_id, center_id=center_id,
        prior_referral_id=prior_referral_id, pathway=pathway,
        deficiency_credits=deficiency_credits,
        behavior_incident_count=behavior_incident_count,
        days_disengaged=days_disengaged, narrative=narrative,
        priority_score=derive.priority_score(pathway, deficiency_credits,
                                             behavior_incident_count, days_disengaged,
                                             prior_referral_id),
        status="SUBMITTED", screening_note=None, missing_items=None,
        waitlist_reason=None, denial_reason=None, offer_expires_on=None,
        promoted_from_waitlist=False,
    )
    store.referrals[row["id"]] = row
    return created(derive.ser_referral(row))


@bp.get("/referrals/<referral_id>")
@endpoint("HomeSchoolCounselor", "PlacementCoordinator", "DistrictAdmin")
def read_referral(ctx, referral_id):
    row = get_referral(referral_id)
    scope_center(ctx, row["center_id"])
    _school_scope(ctx, row)
    return ok(derive.ser_referral(row))


@bp.get("/referrals")
@endpoint("HomeSchoolCounselor", "PlacementCoordinator", "DistrictAdmin")
def list_referrals(ctx):
    rows = ordered(store.referrals.values())
    if ctx.role == "PlacementCoordinator":
        rows = [r for r in rows if r["center_id"] == ctx.uid]
    if ctx.role == "HomeSchoolCounselor":
        rows = [r for r in rows
                if store.students[r["student_id"]]["home_school_id"] == ctx.uid]
    rows = eq(rows, "student_id", q("student_id"))
    rows = eq(rows, "center_id", q("center_id"))
    rows = eq(rows, "status", q("status"))
    rows = eq(rows, "pathway", q("pathway"))
    rows = eq(rows, "prior_referral_id", q("prior_referral_id"))
    return ok_list(rows, derive.ser_referral)


def _require_status(referral, expected):
    if referral["status"] != expected:
        raise ApiError("ERR_REFERRAL_STATE_INVALID",
                       "referral is %s, not %s" % (referral["status"], expected))


@bp.post("/referrals/<referral_id>/screen")
@endpoint("PlacementCoordinator")
def screen_referral(ctx, referral_id):
    referral = get_referral(referral_id)
    scope_center(ctx, referral["center_id"])
    b = v.body()
    note = v.opt_str(b, "screening_note", 1, None)
    _require_status(referral, "SUBMITTED")
    referral["status"] = "SCREENING"
    if note is not None:
        referral["screening_note"] = note
    touch(referral)
    return ok(derive.ser_referral(referral))


@bp.post("/referrals/<referral_id>/request-info")
@endpoint("PlacementCoordinator")
def request_info(ctx, referral_id):
    referral = get_referral(referral_id)
    scope_center(ctx, referral["center_id"])
    b = v.body()
    missing_items = v.req_str(b, "missing_items", 1, None)
    _require_status(referral, "SCREENING")
    referral["status"] = "INFO_REQUESTED"
    referral["missing_items"] = missing_items
    touch(referral)
    return ok(derive.ser_referral(referral))


@bp.post("/referrals/<referral_id>/resubmit")
@endpoint("HomeSchoolCounselor")
def resubmit_referral(ctx, referral_id):
    referral = get_referral(referral_id)
    _school_scope(ctx, referral)
    b = v.body()
    deficiency = v.opt_num(b, "deficiency_credits", lo=0, step="0.25")
    incidents = v.opt_int(b, "behavior_incident_count", 0, None)
    disengaged = v.opt_int(b, "days_disengaged", 0, None)
    narrative = v.opt_str(b, "narrative", 1, 2000)
    _require_status(referral, "INFO_REQUESTED")
    if deficiency is not None:
        referral["deficiency_credits"] = deficiency
    if incidents is not None:
        referral["behavior_incident_count"] = incidents
    if disengaged is not None:
        referral["days_disengaged"] = disengaged
    if narrative is not None:
        referral["narrative"] = narrative
    referral["missing_items"] = None
    referral["status"] = "SCREENING"
    referral["priority_score"] = derive.priority_score(
        referral["pathway"], referral["deficiency_credits"],
        referral["behavior_incident_count"], referral["days_disengaged"],
        referral["prior_referral_id"])
    touch(referral)
    return ok(derive.ser_referral(referral))


@bp.post("/referrals/<referral_id>/offer")
@endpoint("PlacementCoordinator")
def offer_seat(ctx, referral_id):
    referral = get_referral(referral_id)
    scope_center(ctx, referral["center_id"])
    b = v.body()
    valid_days = v.opt_int(b, "offer_valid_days", 1, None, default=10)
    expected = v.req_int(b, "expected_center_version")
    center = store.centers[referral["center_id"]]
    if expected != center["version"]:
        raise ApiError("ERR_STALE_CENTER_VERSION",
                       "expected_center_version does not match the center")
    _require_status(referral, "SCREENING")
    posture = derive.center_posture(center)
    if posture == "FROZEN":
        raise ApiError("ERR_INTAKE_FROZEN", "the center's intake posture is FROZEN")
    if posture == "RESTRICTED" and referral["pathway"] != "BEHAVIOR" and \
            D(referral["priority_score"]) < D("0.5000"):
        raise ApiError("ERR_INTAKE_RESTRICTED",
                       "a RESTRICTED center only seats BEHAVIOR or high-priority referrals")
    referral["status"] = "PLACEMENT_OFFERED"
    referral["offer_expires_on"] = clock_date_plus(valid_days)
    referral["promoted_from_waitlist"] = False
    touch(referral)
    touch(center)
    rederive_center(center, posture)
    return ok(derive.ser_referral(referral))


@bp.post("/referrals/<referral_id>/waitlist")
@endpoint("PlacementCoordinator")
def waitlist_referral(ctx, referral_id):
    referral = get_referral(referral_id)
    scope_center(ctx, referral["center_id"])
    b = v.body()
    reason = v.req_str(b, "waitlist_reason", 1, None)
    _require_status(referral, "SCREENING")
    referral["status"] = "WAITLISTED"
    referral["waitlist_reason"] = reason
    touch(referral)
    return ok(derive.ser_referral(referral))


@bp.post("/referrals/<referral_id>/deny")
@endpoint("PlacementCoordinator")
def deny_referral(ctx, referral_id):
    referral = get_referral(referral_id)
    scope_center(ctx, referral["center_id"])
    b = v.body()
    reason = v.req_str(b, "denial_reason", 1, None)
    _require_status(referral, "SCREENING")
    referral["status"] = "DENIED"
    referral["denial_reason"] = reason
    touch(referral)
    return ok(derive.ser_referral(referral))


@bp.post("/referrals/<referral_id>/withdraw-offer")
@endpoint("PlacementCoordinator")
def withdraw_offer(ctx, referral_id):
    referral = get_referral(referral_id)
    scope_center(ctx, referral["center_id"])
    b = v.body()
    note = v.opt_str(b, "screening_note", 1, None)
    _require_status(referral, "PLACEMENT_OFFERED")
    center = store.centers[referral["center_id"]]
    old_posture = derive.center_posture(center)
    referral["status"] = "SCREENING"
    referral["offer_expires_on"] = None
    referral["promoted_from_waitlist"] = False
    if note is not None:
        referral["screening_note"] = note
    touch(referral)
    touch(center)
    rederive_center(center, old_posture)
    return ok(derive.ser_referral(referral))


@bp.post("/referrals/<referral_id>/accept-offer")
@endpoint("HomeSchoolCounselor")
def accept_offer(ctx, referral_id):
    referral = get_referral(referral_id)
    _school_scope(ctx, referral)
    b = v.body()
    credit_policy = v.req_enum(b, "credit_policy", CREDIT_POLICIES)
    start_date = v.req_date(b, "start_date")
    _require_status(referral, "PLACEMENT_OFFERED")
    center = store.centers[referral["center_id"]]
    old_posture = derive.center_posture(center)
    referral["status"] = "ACCEPTED"
    touch(referral)
    placement = new_row(
        referral_id=referral["id"], student_id=referral["student_id"],
        center_id=referral["center_id"], credit_policy=credit_policy,
        start_date=start_date, status="ACTIVE", days_present=0, days_enrolled=0,
        re_entry_requested_by_user_id=None, target_re_entry_date=None,
        actual_re_entry_date=None, re_entry_denial_reason=None, exit_reason=None,
    )
    store.placements[placement["id"]] = placement
    touch(center)
    rederive_center(center, old_posture)
    return created(derive.ser_placement(placement))
