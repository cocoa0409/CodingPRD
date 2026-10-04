from decimal import Decimal

from flask import Blueprint, request

import auth
import clock
import constants as C
import db
import domain
import util
from errors import ApiError
from serializers import serialize

bp = Blueprint("enrollments", __name__)

READ_ROLES = ["CNCSProgramOfficer", "ComplianceOfficer", "GranteeStaff", "Member"]

EXIT_STATUS = {
    "SUCCESSFUL": "EXITED_SUCCESSFUL",
    "COMPELLING_CIRCUMSTANCE": "EXITED_COMPELLING",
    "FOR_CAUSE": "RELEASED_FOR_CAUSE",
}


def _load_enrollment_or_404(enrollmentId):
    enrollment = db.store.enrollments.get(enrollmentId)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    return enrollment


def _check_enrollment_read_ownership(uid, role, enrollment):
    if role == "Member":
        auth.check_member_ownership(uid, role, enrollment["member_id"])
    elif role == "GranteeStaff":
        award = db.store.awards.get(enrollment["award_id"])
        if award is not None:
            auth.check_grantee_ownership(uid, role, award["organization_id"])


def _check_enrollment_write_ownership(uid, role, enrollment):
    award = db.store.awards.get(enrollment["award_id"])
    if award is not None:
        auth.check_grantee_ownership(uid, role, award["organization_id"])


@bp.route("/awards/<awardId>/enrollments", methods=["POST"])
def create_enrollment(awardId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    award = db.store.awards.get(awardId)
    if award is not None:
        auth.check_grantee_ownership(uid, role, award["organization_id"])
    auth.check_not_debarred(uid, role)
    if award is None:
        raise ApiError("ERR_AWARD_NOT_FOUND", 404, "Award not found")
    body = util.body_json()
    member_id = body.get("member_id")
    # Tier 6: body foreign-key existence (member_id) precedes shape.
    if util.is_str(member_id) and member_id not in db.store.members:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    term_category = body.get("term_category")
    start_raw = body.get("service_start_date")
    end_raw = body.get("service_end_date")
    start_date = util.parse_date(start_raw)
    end_date = util.parse_date(end_raw)
    expected_version = body.get("expected_award_version")
    if not util.is_str(member_id) or not member_id.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400, "member_id is required")
    if term_category not in C.TERM_CATEGORIES:
        raise ApiError("ERR_INVALID_REQUEST", 400, "term_category is invalid")
    if start_date is None or end_date is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "service dates must be ISO dates (YYYY-MM-DD)"
        )
    if not end_date > start_date:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "service_end_date must be strictly after service_start_date",
        )
    if not util.is_int(expected_version):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_award_version is required"
        )
    member = db.store.members[member_id]
    # Tier 9: award posture.
    if award["status"] != "ACTIVE":
        raise ApiError("ERR_AWARD_SUSPENDED", 409, "Award is not ACTIVE")
    # Tier 14: optimistic concurrency on the award.
    if expected_version != award["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_award_version does not match the award"
        )
    # Tier 15: member must be >= 17 at service_start_date.
    dob = util.parse_date(member["date_of_birth"])
    if util.add_years_date(dob, C.MIN_MEMBER_AGE_YEARS) > start_date:
        raise ApiError(
            "ERR_MEMBER_TOO_YOUNG", 422, "Member is younger than 17 at service start"
        )
    # Tier 16: debarred members may never serve again.
    if member["status"] == "DEBARRED":
        raise ApiError("ERR_MEMBER_INELIGIBLE", 422, "Member is DEBARRED")
    # Tier 17: at least one criminal history check on file.
    latest = domain.latest_check(member_id)
    if latest is None:
        raise ApiError(
            "ERR_CRIMINAL_CHECK_OUTSTANDING",
            422,
            "Member has no criminal history check on file",
        )
    # Tier 18: latest check must not be FLAGGED (PENDING is acceptable).
    if latest["adjudication"] == "FLAGGED":
        raise ApiError(
            "ERR_CRIMINAL_CHECK_FLAGGED", 422, "Latest criminal history check is FLAGGED"
        )
    # Tier 26: half-open service-period overlap.
    for other in db.store.enrollments.values():
        if other["member_id"] != member_id:
            continue
        if other["status"] not in ("PENDING_CHECKS", "ACTIVE", "SUSPENDED"):
            continue
        other_start = util.parse_date(other["service_start_date"])
        other_end = util.parse_date(other["service_end_date"])
        if start_date < other_end and other_start < end_date:
            raise ApiError(
                "ERR_SERVICE_PERIOD_OVERLAP",
                409,
                "Member already holds an overlapping enrollment",
            )
    # Tier 28: deterministic slot selector (lowest slot_index).
    candidates = [
        s
        for s in db.store.slots.values()
        if s["award_id"] == awardId
        and s["status"] == "OPEN"
        and s["term_category"] == term_category
    ]
    if not candidates:
        raise ApiError(
            "ERR_NO_OPEN_SLOT",
            409,
            "No OPEN slot of the requested term category on this award",
        )
    slot = min(candidates, key=lambda s: (s["slot_index"], s.get("created_at", "")))
    slot["status"] = "RESERVED"
    domain.touch(slot)
    domain.touch(award)  # creating an enrollment bumps the award's version
    already_cleared = latest["adjudication"] == "CLEARED"
    enrollment = db.new_entity(
        {
            "id": util.new_id(),
            "member_id": member_id,
            "award_id": awardId,
            "slot_id": slot["id"],
            "term_category": term_category,
            "term_minutes": C.TERM_MINUTES[term_category],
            "service_start_date": start_raw,
            "service_end_date": end_raw,
            "certified_minutes": 0,
            "fundraising_certified_minutes": 0,
            "allowance_paid_cents": 0,
            "suspension_origin": "NONE",
            "exit_reason": None,
            "exited_at": None,
            "exit_overpayment_cents": None,
            "education_award_id": None,
            "status": "ACTIVE" if already_cleared else "PENDING_CHECKS",
        }
    )
    db.store.enrollments[enrollment["id"]] = enrollment
    if already_cleared:
        slot["status"] = "FILLED"
        slot["fill_count"] += 1
        domain.touch(slot)
    return util.ok(serialize(enrollment), 201)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    items = list(db.store.enrollments.values())
    if role == "Member":
        items = [e for e in items if e["member_id"] == uid]
    elif role == "GranteeStaff":
        items = [
            e
            for e in items
            if db.store.awards.get(e["award_id"], {}).get("organization_id") == uid
        ]
    member_id = request.args.get("member_id")
    award_id = request.args.get("award_id")
    slot_id = request.args.get("slot_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if award_id is not None:
        items = [e for e in items if e["award_id"] == award_id]
    if slot_id is not None:
        items = [e for e in items if e["slot_id"] == slot_id]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/enrollments/<enrollmentId>", methods=["GET"])
def get_enrollment(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    enrollment = _load_enrollment_or_404(enrollmentId)
    _check_enrollment_read_ownership(uid, role, enrollment)
    return util.ok(serialize(enrollment), 200)


@bp.route("/enrollments/<enrollmentId>/suspend", methods=["POST"])
def suspend_enrollment(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    enrollment = db.store.enrollments.get(enrollmentId)
    if enrollment is not None:
        _check_enrollment_write_ownership(uid, role, enrollment)
    auth.check_not_debarred(uid, role)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    if enrollment["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment is not ACTIVE")
    enrollment["status"] = "SUSPENDED"
    enrollment["suspension_origin"] = "MANUAL"
    domain.touch(enrollment)
    return util.ok(serialize(enrollment), 200)


@bp.route("/enrollments/<enrollmentId>/reinstate", methods=["POST"])
def reinstate_enrollment(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    enrollment = db.store.enrollments.get(enrollmentId)
    if enrollment is not None:
        _check_enrollment_write_ownership(uid, role, enrollment)
    auth.check_not_debarred(uid, role)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    if enrollment["status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE", 409, "Enrollment is not SUSPENDED")
    award = db.store.awards.get(enrollment["award_id"])
    if award is None or award["status"] != "ACTIVE":
        raise ApiError("ERR_AWARD_SUSPENDED", 409, "Award is not ACTIVE")
    enrollment["status"] = "ACTIVE"
    enrollment["suspension_origin"] = "NONE"
    domain.touch(enrollment)
    return util.ok(serialize(enrollment), 200)


@bp.route("/enrollments/<enrollmentId>/exit", methods=["POST"])
def exit_enrollment(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["GranteeStaff"])
    enrollment = db.store.enrollments.get(enrollmentId)
    if enrollment is not None:
        _check_enrollment_write_ownership(uid, role, enrollment)
    auth.check_not_debarred(uid, role)
    if enrollment is None:
        raise ApiError("ERR_ENROLLMENT_NOT_FOUND", 404, "Enrollment not found")
    body = util.body_json()
    exit_reason = body.get("exit_reason")
    if exit_reason not in C.EXIT_REASONS:
        raise ApiError("ERR_INVALID_REQUEST", 400, "exit_reason is invalid")
    if enrollment["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Enrollment is not ACTIVE or SUSPENDED"
        )
    certified = enrollment["certified_minutes"]
    term_minutes = enrollment["term_minutes"]
    if exit_reason == "FOR_CAUSE":
        for grievance in db.store.grievances.values():
            if (
                grievance["enrollment_id"] == enrollmentId
                and grievance["status"] == "ESCALATED"
            ):
                raise ApiError(
                    "ERR_GRIEVANCE_PENDING",
                    409,
                    "An ESCALATED grievance blocks a for-cause release",
                )
    elif exit_reason == "SUCCESSFUL":
        if certified < term_minutes:
            raise ApiError(
                "ERR_MIN_HOURS_NOT_MET",
                422,
                "Certified minutes are below the term requirement",
            )
    else:  # COMPELLING_CIRCUMSTANCE
        if certified * 100 < C.PRORATION_FLOOR_PCT * term_minutes:
            raise ApiError(
                "ERR_PRORATION_FLOOR_NOT_MET",
                422,
                "Certified minutes are below 15% of the term",
            )
    now = clock.now()
    category = enrollment["term_category"]
    allowance_total = C.ALLOWANCE_TOTAL_CENTS[category]
    if exit_reason == "SUCCESSFUL":
        earned = allowance_total
        issued_amount = C.AWARD_CENTS[category]
    else:
        earned = (allowance_total * certified) // term_minutes
        if exit_reason == "COMPELLING_CIRCUMSTANCE":
            issued_amount = util.round_half_up_int(
                Decimal(C.AWARD_CENTS[category]) * Decimal(certified) / Decimal(term_minutes)
            )
        else:
            issued_amount = None
    enrollment["exit_reason"] = exit_reason
    enrollment["exited_at"] = clock.iso(now)
    enrollment["exit_overpayment_cents"] = max(
        0, enrollment["allowance_paid_cents"] - earned
    )
    if issued_amount is not None:
        education_award = db.new_entity(
            {
                "id": util.new_id(),
                "member_id": enrollment["member_id"],
                "enrollment_id": enrollment["id"],
                "term_category": category,
                "issued_amount_cents": issued_amount,
                "remaining_balance_cents": issued_amount,
                "issued_at": clock.iso(now),
                "use_deadline_at": clock.iso(
                    util.add_years_datetime(now, C.AWARD_USE_DEADLINE_YEARS)
                ),
                "status": "ISSUED",
            }
        )
        db.store.education_awards[education_award["id"]] = education_award
        enrollment["education_award_id"] = education_award["id"]
    else:
        member = db.store.members.get(enrollment["member_id"])
        if member is not None:
            member["status"] = "DEBARRED"
            member["for_cause_release_count"] += 1
            domain.touch(member)
    enrollment["status"] = EXIT_STATUS[exit_reason]
    domain.touch(enrollment)
    slot = db.store.slots.get(enrollment["slot_id"])
    if slot is not None and slot["status"] == "FILLED":
        slot["status"] = "VACATED"
        domain.refill_vacated_slot(slot)
    return util.ok(serialize(enrollment), 200)


@bp.route("/enrollments/<enrollmentId>/hour-entries", methods=["GET"])
def list_hour_entries(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, READ_ROLES)
    enrollment = _load_enrollment_or_404(enrollmentId)
    _check_enrollment_read_ownership(uid, role, enrollment)
    items = [
        e for e in db.store.hour_entries.values() if e["enrollment_id"] == enrollmentId
    ]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return util.list_response(items, serialize)


@bp.route("/enrollments/<enrollmentId>/allowance-payments", methods=["GET"])
def list_allowance_payments(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer", "GranteeStaff", "Member"])
    enrollment = _load_enrollment_or_404(enrollmentId)
    _check_enrollment_read_ownership(uid, role, enrollment)
    items = [
        p for p in db.store.payments.values() if p["enrollment_id"] == enrollmentId
    ]
    return util.list_response(items, serialize)


@bp.route("/enrollments/<enrollmentId>/grievances", methods=["GET"])
def list_enrollment_grievances(enrollmentId):
    uid, role = auth.authenticate()
    auth.authorize(role, ["CNCSProgramOfficer", "GranteeStaff", "Member"])
    enrollment = _load_enrollment_or_404(enrollmentId)
    _check_enrollment_read_ownership(uid, role, enrollment)
    items = [
        g for g in db.store.grievances.values() if g["enrollment_id"] == enrollmentId
    ]
    status = request.args.get("status")
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return util.list_response(items, serialize)
