"""MemberEnrollment endpoints + funnel transitions + disenroll cascade.

PRD §3.3. The CREATE-with-supersede pattern is the re-engagement mechanism.
"""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_state, err_input, err_stale,
                    ERR_MEMBER_NOT_FOUND, ERR_ENROLLMENT_NOT_FOUND,
                    ERR_ENROLLMENT_NOT_IDENTIFIED, ERR_ENROLLMENT_NOT_DECLINED,
                    ERR_ENROLLMENT_NOT_IN_OUTREACH, ERR_ENROLLMENT_NOT_CONSENTED,
                    ERR_ENROLLMENT_NOT_ACTIVE, ERR_ENROLLMENT_SUPERSEDED,
                    ERR_OUTREACH_ATTEMPTS_EXHAUSTED, ERR_CARE_TEAM_NOT_ACTIVE,
                    ERR_CONSENT_DOCUMENT_REQUIRED,
                    ERR_DISENROLLMENT_REASON_REQUIRED, ERR_INVALID_REQUEST)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services import serializers
from services.clock import now_iso, now_clock
from services.measurements import get_or_create_measurement, recompute_composite
from services.resources import base_fields, touch
from services.validation import (get_json_body, require_enum, require_int,
                                 optional_enum)

bp = Blueprint("enrollments", __name__)

MAX_OUTREACH_ATTEMPTS = 3

READ_ROLES = ["PlatformAdmin", "ContractAdministrator", "CareCoordinator",
              "EngagementSpecialist", "PerformanceAnalyst"]
WRITE_ROLE = ["EngagementSpecialist"]
OUTREACH_CHANNELS = {"PHONE", "MAIL", "IN_PERSON", "PCP_REFERRAL"}
DISENROLLMENT_REASONS = {"MEMBER_REQUEST", "PAYER_TERMINATION", "DECEASED",
                         "MOVED_OUT_OF_AREA", "NON_ENGAGEMENT"}


def _get_enrollment_or_404(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise err_not_found(ERR_ENROLLMENT_NOT_FOUND, "MemberEnrollment")
    return e


def _check_is_current(e):
    if not e.get("is_current"):
        raise err_state(ERR_ENROLLMENT_SUPERSEDED,
                        "Enrollment has been superseded by a newer enrollment")


def _program_period_for_member(member_id):
    member = db.members.get(member_id)
    if member is None:
        return 0
    program = db.care_programs.get(member.get("care_program_id"))
    return int(program.get("current_period_index") or 0) if program else 0


@bp.route("/members/<memberId>/enrollments", methods=["POST"])
def create_enrollment(memberId):
    require_roles(WRITE_ROLE)
    member = db.members.get(memberId)
    if member is None:
        raise err_not_found(ERR_MEMBER_NOT_FOUND, "Member")
    body = get_json_body()
    outreach_channel = require_enum(body, "outreach_channel", OUTREACH_CHANNELS)
    expected_member_version = require_int(body, "expected_member_version")

    # OCC (validation ladder rung 13; §2.5)
    if expected_member_version != int(member.get("version") or 0):
        raise err_stale()

    # CREATE-with-supersede: flip any prior is_current enrollment
    for prior in db.enrollments.values():
        if prior.get("member_id") == memberId and prior.get("is_current"):
            prior["is_current"] = False
            touch(prior)

    e = base_fields()
    e.update({
        "member_id": memberId,
        "outreach_channel": outreach_channel,
        "outreach_attempts": 0,
        "consent_recorded_at": None,
        "consent_document_id": None,
        "disenrollment_reason": None,
        "status": "IDENTIFIED",
        "is_current": True,
        # Internal bookkeeping for enrolled_member_months period checks
        "activated_period_index": None,
        "disenrolled_period_index": None,
    })
    db.enrollments[e["id"]] = e

    # Creating an enrollment advances the parent Member.version by 1 (§3.3)
    touch(member)
    return success_object(serializers.enrollment(e), status=201)


@bp.route("/members/<memberId>/enrollments", methods=["GET"])
def list_member_enrollments(memberId):
    require_roles(READ_ROLES)
    member = db.members.get(memberId)
    if member is None:
        raise err_not_found(ERR_MEMBER_NOT_FOUND, "Member")
    limit, offset = parse_pagination(request.args)
    items = [e for e in db.enrollments.values()
             if e.get("member_id") == memberId]
    s = request.args.get("status")
    if s:
        items = [e for e in items if e.get("status") == s]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.enrollment(e) for e in page],
                        limit, offset, total)


@bp.route("/enrollments", methods=["GET"])
def list_enrollments():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = list(db.enrollments.values())
    mid = request.args.get("member_id")
    if mid:
        items = [e for e in items if e.get("member_id") == mid]
    s = request.args.get("status")
    if s:
        items = [e for e in items if e.get("status") == s]
    ic = request.args.get("is_current")
    if ic is not None and ic != "":
        want = ic.strip().lower() in ("true", "1", "yes")
        items = [e for e in items if bool(e.get("is_current")) == want]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([serializers.enrollment(e) for e in page],
                        limit, offset, total)


@bp.route("/enrollments/<enrollmentId>", methods=["GET"])
def get_enrollment(enrollmentId):
    require_roles(READ_ROLES)
    e = _get_enrollment_or_404(enrollmentId)
    return success_object(serializers.enrollment(e))


@bp.route("/enrollments/<enrollmentId>/begin-outreach", methods=["POST"])
def begin_outreach(enrollmentId):
    require_roles(WRITE_ROLE)
    e = _get_enrollment_or_404(enrollmentId)
    # State precondition (rung 5): IDENTIFIED or DECLINED
    if e["status"] not in ("IDENTIFIED", "DECLINED"):
        if e["status"] == "OUTREACH":
            raise err_state(ERR_ENROLLMENT_NOT_IDENTIFIED,
                            "Enrollment is already in OUTREACH")
        raise err_state(ERR_ENROLLMENT_NOT_IDENTIFIED,
                        "Enrollment must be IDENTIFIED or DECLINED for begin-outreach")
    # is_current invariant (rung 6)
    _check_is_current(e)
    # Both paths reset outreach_attempts to 1 (PRD §3.3)
    e["status"] = "OUTREACH"
    e["outreach_attempts"] = 1
    touch(e)
    return success_object(serializers.enrollment(e))


@bp.route("/enrollments/<enrollmentId>/record-attempt", methods=["POST"])
def record_attempt(enrollmentId):
    require_roles(WRITE_ROLE)
    e = _get_enrollment_or_404(enrollmentId)
    # PRD §3.3: once the counter has reached the cap (which auto-declined the
    # enrollment), "the same ERR_OUTREACH_ATTEMPTS_EXHAUSTED rejection surfaces
    # on any subsequent record-attempt call" — so the exhaustion check
    # pre-empts the state check for this endpoint.
    if int(e.get("outreach_attempts") or 0) >= MAX_OUTREACH_ATTEMPTS:
        raise err_state(ERR_OUTREACH_ATTEMPTS_EXHAUSTED,
                        "Outreach attempts exhausted; enrollment auto-declined")
    if e["status"] != "OUTREACH":
        raise err_state(ERR_ENROLLMENT_NOT_IN_OUTREACH,
                        "Enrollment must be in OUTREACH to record an attempt")
    _check_is_current(e)
    e["outreach_attempts"] = int(e.get("outreach_attempts") or 0) + 1
    if e["outreach_attempts"] >= MAX_OUTREACH_ATTEMPTS:
        # Auto-exit at the cap (PRD §3.3)
        e["status"] = "DECLINED"
        e["disenrollment_reason"] = "NON_ENGAGEMENT"
    touch(e)
    return success_object(serializers.enrollment(e))


@bp.route("/enrollments/<enrollmentId>/record-consent", methods=["POST"])
def record_consent(enrollmentId):
    require_roles(WRITE_ROLE)
    e = _get_enrollment_or_404(enrollmentId)
    if e["status"] != "OUTREACH":
        raise err_state(ERR_ENROLLMENT_NOT_IN_OUTREACH,
                        "Enrollment must be in OUTREACH to record consent")
    _check_is_current(e)
    body = get_json_body()
    consent_document_id = body.get("consent_document_id")
    if consent_document_id is None or (isinstance(consent_document_id, str)
                                       and consent_document_id.strip() == ""):
        raise err_input(ERR_CONSENT_DOCUMENT_REQUIRED,
                        "consent_document_id is required at CONSENTED transition")
    e["status"] = "CONSENTED"
    e["consent_recorded_at"] = now_iso()
    e["consent_document_id"] = consent_document_id
    touch(e)

    # Side effect: create a DRAFT CareTeam with null clinician FKs (§3.3)
    ct = base_fields()
    ct.update({
        "enrollment_id": e["id"],
        "member_id": e["member_id"],
        "primary_np_id": None,
        "social_worker_id": None,
        "behavioral_clinician_id": None,
        "status": "DRAFT",
        "composition_complete": False,
    })
    db.care_teams[ct["id"]] = ct
    return success_object(serializers.enrollment(e))


@bp.route("/enrollments/<enrollmentId>/record-decline", methods=["POST"])
def record_decline(enrollmentId):
    require_roles(WRITE_ROLE)
    e = _get_enrollment_or_404(enrollmentId)
    if e["status"] != "OUTREACH":
        raise err_state(ERR_ENROLLMENT_NOT_IN_OUTREACH,
                        "Enrollment must be in OUTREACH to record a decline")
    _check_is_current(e)
    e["status"] = "DECLINED"
    touch(e)
    return success_object(serializers.enrollment(e))


@bp.route("/enrollments/<enrollmentId>/activate", methods=["POST"])
def activate_enrollment(enrollmentId):
    require_roles(WRITE_ROLE)
    e = _get_enrollment_or_404(enrollmentId)
    if e["status"] != "CONSENTED":
        raise err_state(ERR_ENROLLMENT_NOT_CONSENTED,
                        "Enrollment must be CONSENTED for activation")
    _check_is_current(e)
    # Care-team readiness (rung 7): the care team for this enrollment must be ACTIVE
    ct = None
    for t in db.care_teams.values():
        if t.get("enrollment_id") == e["id"]:
            ct = t
            break
    if ct is None or ct.get("status") != "ACTIVE":
        raise err_state(ERR_CARE_TEAM_NOT_ACTIVE,
                        "Care team must be ACTIVE before enrollment activation")

    e["status"] = "ACTIVE"
    e["activated_period_index"] = _program_period_for_member(e["member_id"])
    touch(e)

    # Seed the performance infrastructure (PRD §3.5)
    member = db.members.get(e["member_id"])
    if member is not None:
        period = _program_period_for_member(member["id"])
        get_or_create_measurement(member.get("payer_contract_id"),
                                  member["id"], period)
    return success_object(serializers.enrollment(e))


@bp.route("/enrollments/<enrollmentId>/disenroll", methods=["POST"])
def disenroll(enrollmentId):
    require_roles(WRITE_ROLE)
    e = _get_enrollment_or_404(enrollmentId)
    if e["status"] not in ("ACTIVE", "CONSENTED"):
        raise err_state(ERR_ENROLLMENT_NOT_ACTIVE,
                        "Enrollment must be ACTIVE or CONSENTED to disenroll")
    _check_is_current(e)
    body = get_json_body()
    reason = body.get("disenrollment_reason")
    if reason is None or (isinstance(reason, str) and reason.strip() == ""):
        raise err_input(ERR_DISENROLLMENT_REASON_REQUIRED,
                        "disenrollment_reason is required")
    if reason not in DISENROLLMENT_REASONS:
        raise err_input(ERR_INVALID_REQUEST,
                        "Invalid disenrollment_reason: %r" % reason)

    was_active = e["status"] == "ACTIVE"
    e["status"] = "DISENROLLED"
    e["disenrollment_reason"] = reason
    e["is_current"] = False
    e["disenrolled_period_index"] = _program_period_for_member(e["member_id"])
    touch(e)

    if was_active:
        # Cascade: every SCHEDULED visit child → CANCELLED (ENROLLMENT_ENDED),
        # each decrements its clinician's active_daily_visit_count (§3.7).
        for v in db.visits.values():
            if v.get("enrollment_id") == e["id"] and v.get("status") == "SCHEDULED":
                v["status"] = "CANCELLED"
                v["cancellation_reason"] = "ENROLLMENT_ENDED"
                touch(v)
                clin = db.clinicians.get(v.get("clinician_id"))
                if clin is not None:
                    clin["active_daily_visit_count"] = max(
                        0, int(clin.get("active_daily_visit_count") or 0) - 1)
                    touch(clin)

    # Cascade: care team → RETIRED regardless of prior status (§3.7)
    for t in db.care_teams.values():
        if t.get("enrollment_id") == e["id"] and t.get("status") != "RETIRED":
            t["status"] = "RETIRED"
            touch(t)

    # Recompute the period's measurement with the member excluded going forward
    member = db.members.get(e["member_id"])
    if member is not None:
        period = _program_period_for_member(member["id"])
        from services.measurements import find_measurement
        m = find_measurement(member.get("payer_contract_id"),
                             member["id"], period)
        if m is not None:
            recompute_composite(m)
            touch(m)

    return success_object(serializers.enrollment(e))
