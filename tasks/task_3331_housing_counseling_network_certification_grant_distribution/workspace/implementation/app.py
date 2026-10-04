import math
import os
import re
from datetime import timedelta
from decimal import Decimal

from flask import Flask

from logic import (
    CE_REQUIRED_CREDITS, CE_WINDOW_MONTHS, COMPETITIVE_SCORE_FLOOR,
    CORRECTIVE_PLAN_DAYS, MIN_HOURS_NO_OUTCOME, OUTCOME_CODES, PASS_THRESHOLD,
    PERFORMANCE_PASS_SCORE, PROGRAM_AREAS, competitive_component,
    compute_formula_shares, final_composite, fire_clock_transitions,
    households_served, provisional_composite, rating_for, recompute_member,
    required_match, seats_taken,
)
from store import (
    APPLICATION_FIELDS, ASSESSMENT_FIELDS, AUDIT_FIELDS, AWARD_FIELDS,
    CERT_FIELDS, CLIENT_FILE_FIELDS, COMMON, COURSE_FIELDS, COUNSELOR_FIELDS,
    CYCLE_FIELDS, DB, DISBURSEMENT_FIELDS, ENROLLMENT_FIELDS, EXP_REPORT_FIELDS,
    FILE_REVIEW_FIELDS, MEMBER_FIELDS, PERF_REVIEW_FIELDS, serialize,
    sort_entities,
)
from util import (
    CLOCK, ApiError, add_months, as_enum, as_int, as_int_range,
    as_nonempty_str, as_nonneg_int, auth, body, err_course_full,
    err_cross_entity, err_duplicate, err_hours_insufficient, err_invalid_request,
    err_invalid_state, err_match_not_met, err_not_chartered, err_not_found,
    err_not_reconcilable, err_pool_exhausted, err_posture_blocked, err_prereq,
    err_review_pending, err_score_too_low, err_segregation, err_stale_version,
    err_unauthorized, err_window_closed, error_response, fmt_dt, ok_object,
    paginate, parse_dt, req_field, require_roles,
)

app = Flask(__name__)

PREFIX = "/housing-network"

ALL_ROLES = [
    "NetworkDirector", "Assessor", "GrantOfficer", "Auditor",
    "ComplianceReviewer", "MemberAdmin", "TrainingRegistrar",
]

EIN_RE = re.compile(r"^[0-9]{9}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
FIPS_RE = re.compile(r"^[0-9]{5}$")
COURSE_CODE_RE = re.compile(r"^[A-Z]{2,4}-[0-9]{3}$")
FY_LABEL_RE = re.compile(r"FY\s*-?\s*(\d{4})", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error_response(err_not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_generic(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return error_response(err_invalid_request(str(err)))


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def ser_member(m):
    return serialize(m, MEMBER_FIELDS)


def ser_assessment(a):
    return serialize(a, ASSESSMENT_FIELDS)


def ser_counselor(c):
    return serialize(c, COUNSELOR_FIELDS)


def ser_course(c):
    d = serialize(c, [f for f in COURSE_FIELDS if f != "seats_taken"])
    d["seats_taken"] = seats_taken(c["id"])
    return d


def ser_enrollment(e):
    return serialize(e, ENROLLMENT_FIELDS)


def ser_cert(c):
    return serialize(c, CERT_FIELDS)


def ser_cycle(c):
    return serialize(c, CYCLE_FIELDS)


def ser_application(a):
    return serialize(a, APPLICATION_FIELDS)


def ser_award(a):
    return serialize(a, AWARD_FIELDS)


def ser_disbursement(d):
    return serialize(d, DISBURSEMENT_FIELDS)


def ser_client_file(f):
    return serialize(f, CLIENT_FILE_FIELDS)


def ser_file_review(r):
    return serialize(r, FILE_REVIEW_FIELDS)


def ser_exp_report(r):
    return serialize(r, EXP_REPORT_FIELDS)


def ser_audit(a):
    return serialize(a, AUDIT_FIELDS)


def ser_perf_review(r):
    return serialize(r, PERF_REVIEW_FIELDS)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def get_member(mid):
    m = DB.members.get(mid)
    if m is None:
        raise err_not_found("Member not found")
    return m


def get_assessment(aid):
    a = DB.assessments.get(aid)
    if a is None:
        raise err_not_found("Assessment not found")
    return a


def get_counselor(cid):
    c = DB.counselors.get(cid)
    if c is None:
        raise err_not_found("Counselor not found")
    return c


def get_course(cid):
    c = DB.courses.get(cid)
    if c is None:
        raise err_not_found("Course not found")
    return c


def get_enrollment(eid):
    e = DB.enrollments.get(eid)
    if e is None:
        raise err_not_found("Enrollment not found")
    return e


def get_cert(cid):
    c = DB.certifications.get(cid)
    if c is None:
        raise err_not_found("Certification not found")
    return c


def get_cycle(cid):
    c = DB.cycles.get(cid)
    if c is None:
        raise err_not_found("Grant cycle not found")
    return c


def get_application(aid):
    a = DB.applications.get(aid)
    if a is None:
        raise err_not_found("Grant application not found")
    return a


def get_award(aid):
    a = DB.awards.get(aid)
    if a is None:
        raise err_not_found("Grant award not found")
    return a


def get_disbursement(did):
    d = DB.disbursements.get(did)
    if d is None:
        raise err_not_found("Disbursement not found")
    return d


def get_client_file(fid):
    f = DB.client_files.get(fid)
    if f is None:
        raise err_not_found("Client file not found")
    return f


def get_file_review(rid):
    r = DB.file_reviews.get(rid)
    if r is None:
        raise err_not_found("File review not found")
    return r


def get_exp_report(rid):
    r = DB.exp_reports.get(rid)
    if r is None:
        raise err_not_found("Expenditure report not found")
    return r


def get_audit(aid):
    a = DB.audits.get(aid)
    if a is None:
        raise err_not_found("Compliance audit not found")
    return a


def get_perf_review(rid):
    r = DB.perf_reviews.get(rid)
    if r is None:
        raise err_not_found("Performance review not found")
    return r


def check_member_admin_owns(user_id, role, member_id):
    if role == "MemberAdmin" and user_id != member_id:
        raise err_unauthorized("MemberAdmin may only act for their own organization")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/_clock/set_current_utc")
def set_clock():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    data = body()
    raw = req_field(data, "to_iso8601")
    try:
        dt = parse_dt(raw)
    except (ValueError, TypeError):
        raise err_invalid_request("to_iso8601 must be a valid ISO-8601 timestamp")
    CLOCK.set(dt)
    fire_clock_transitions()
    return ok_object({"current_utc": fmt_dt(CLOCK.now())})


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/members")
def create_member():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    data = body()
    legal_name = data.get("legal_name")
    ein = data.get("ein")
    state_code = data.get("state_code")
    service_regions = data.get("service_regions")
    # uniqueness (priority 13) before payload shape (14)
    if legal_name is not None:
        for m in DB.members.values():
            if m["legal_name"] == legal_name:
                raise err_duplicate("legal_name already registered")
    if ein is not None:
        for m in DB.members.values():
            if m["ein"] == ein:
                raise err_duplicate("ein already registered")
    legal_name = as_nonempty_str(req_field(data, "legal_name"), "legal_name")
    ein = as_nonempty_str(req_field(data, "ein"), "ein")
    if not EIN_RE.match(ein):
        raise err_invalid_request("ein must be exactly 9 digits")
    state_code = as_nonempty_str(req_field(data, "state_code"), "state_code")
    if not STATE_RE.match(state_code):
        raise err_invalid_request("state_code must be two uppercase letters")
    service_regions = req_field(data, "service_regions")
    if (not isinstance(service_regions, list)
            or not (1 <= len(service_regions) <= 50)
            or any(not isinstance(s, str) or not FIPS_RE.match(s) for s in service_regions)):
        raise err_invalid_request("service_regions must be 1..50 five-digit FIPS codes")
    member = DB.new_entity(
        legal_name=legal_name, ein=ein, state_code=state_code,
        charter_status="APPLICANT", compliance_posture="CLEAR",
        service_regions=service_regions, chartered_at=None,
        revocation_reason=None, open_finding_count=0, failed_review_flag=False,
    )
    DB.members[member["id"]] = member
    return ok_object(ser_member(member), 201)


@app.get(f"{PREFIX}/members")
def list_members():
    auth_user = auth()
    require_roles(auth_user[1], ALL_ROLES)
    from flask import request
    items = list(DB.members.values())
    charter_status = request.args.get("charter_status")
    if charter_status:
        items = [m for m in items if m["charter_status"] == charter_status]
    state_code = request.args.get("state_code")
    if state_code:
        items = [m for m in items if m["state_code"] == state_code]
    posture = request.args.get("compliance_posture")
    if posture:
        items = [m for m in items if m["compliance_posture"] == posture]
    return paginate([ser_member(m) for m in sort_entities(items)])


@app.get(f"{PREFIX}/members/<mid>")
def get_one_member(mid):
    auth_user = auth()
    require_roles(auth_user[1], ALL_ROLES)
    return ok_object(ser_member(get_member(mid)))


@app.post(f"{PREFIX}/members/<mid>/begin-assessment")
def begin_assessment(mid):
    user_id, role = auth()
    require_roles(role, ["Assessor"])
    member = get_member(mid)
    if member["charter_status"] != "APPLICANT":
        raise err_invalid_state("Member must be APPLICANT to begin assessment")
    member["charter_status"] = "UNDER_ASSESSMENT"
    DB.touch(member)
    assessment = DB.new_entity(
        member_id=member["id"], governance_score=None, finance_score=None,
        program_capacity_score=None, composite_score=None,
        provisional_rating=None, final_rating=None,
        assessment_status="DRAFT", assessor_id=None,
    )
    DB.assessments[assessment["id"]] = assessment
    return ok_object(ser_assessment(assessment), 201)


@app.post(f"{PREFIX}/members/<mid>/charter")
def charter_member(mid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    member = get_member(mid)
    if member["charter_status"] != "PROVISIONAL":
        raise err_invalid_state("Member must be PROVISIONAL to charter")
    certified = any(
        cert["certification_status"] == "CERTIFIED"
        and DB.counselors.get(cert["counselor_id"], {}).get("member_id") == mid
        for cert in DB.certifications.values()
    )
    if not certified:
        raise err_invalid_state(
            "Chartering requires at least one CERTIFIED certification held by a counselor of this member")
    member["charter_status"] = "CHARTERED"
    member["chartered_at"] = CLOCK.now()
    DB.touch(member)
    recompute_member(member)
    return ok_object(ser_member(member))


@app.post(f"{PREFIX}/members/<mid>/reinstate")
def reinstate_member(mid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    member = get_member(mid)
    if member["charter_status"] != "PROBATION":
        raise err_invalid_state("Member must be PROBATION to reinstate")
    recompute_member(member)
    if member["open_finding_count"] != 0 or member["failed_review_flag"]:
        raise err_invalid_state(
            "Reinstatement requires zero open findings and no failed review flag")
    member["charter_status"] = "CHARTERED"
    DB.touch(member)
    recompute_member(member)
    return ok_object(ser_member(member))


@app.post(f"{PREFIX}/members/<mid>/revoke")
def revoke_member(mid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    member = get_member(mid)
    if member["charter_status"] != "PROBATION":
        raise err_invalid_state("Member must be PROBATION to revoke")
    data = body()
    reason = as_nonempty_str(req_field(data, "revocation_reason"), "revocation_reason")
    member["charter_status"] = "REVOKED"
    member["revocation_reason"] = reason
    DB.touch(member)
    # cascade: awards DISBURSING/ACTIVE/SUSPENDED -> TERMINATED
    for award in sort_entities([a for a in DB.awards.values() if a["member_id"] == mid]):
        if award["award_status"] in ("DISBURSING", "ACTIVE", "SUSPENDED"):
            award["award_status"] = "TERMINATED"
            DB.touch(award)
    # cascade: counselors ACTIVE -> SUSPENDED
    member_counselors = [c for c in DB.counselors.values() if c["member_id"] == mid]
    for counselor in sort_entities(member_counselors):
        if counselor["counselor_status"] == "ACTIVE":
            counselor["counselor_status"] = "SUSPENDED"
            DB.touch(counselor)
    # cascade: certifications CERTIFIED of those counselors -> REVOKED
    counselor_ids = {c["id"] for c in member_counselors}
    for cert in sort_entities([c for c in DB.certifications.values()
                               if c["counselor_id"] in counselor_ids]):
        if cert["certification_status"] == "CERTIFIED":
            cert["certification_status"] = "REVOKED"
            DB.touch(cert)
    recompute_member(member)
    return ok_object(ser_member(member))


# ---------------------------------------------------------------------------
# Assessments
# ---------------------------------------------------------------------------


@app.get(f"{PREFIX}/assessments")
def list_assessments():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "Assessor"])
    from flask import request
    items = list(DB.assessments.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [a for a in items if a["member_id"] == member_id]
    status = request.args.get("assessment_status")
    if status:
        items = [a for a in items if a["assessment_status"] == status]
    return paginate([ser_assessment(a) for a in sort_entities(items)])


@app.get(f"{PREFIX}/assessments/<aid>")
def get_one_assessment(aid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "Assessor"])
    return ok_object(ser_assessment(get_assessment(aid)))


@app.post(f"{PREFIX}/assessments/<aid>/submit")
def submit_assessment(aid):
    user_id, role = auth()
    require_roles(role, ["Assessor"])
    assessment = get_assessment(aid)
    if assessment["assessment_status"] != "DRAFT":
        raise err_invalid_state("Assessment must be DRAFT to submit")
    data = body()
    g = as_int_range(req_field(data, "governance_score"), "governance_score", 0, 100)
    f = as_int_range(req_field(data, "finance_score"), "finance_score", 0, 100)
    p = as_int_range(req_field(data, "program_capacity_score"), "program_capacity_score", 0, 100)
    assessment["governance_score"] = g
    assessment["finance_score"] = f
    assessment["program_capacity_score"] = p
    assessment["assessor_id"] = user_id
    composite = provisional_composite(g, f, p)
    assessment["composite_score"] = composite
    assessment["provisional_rating"] = rating_for(composite)
    assessment["assessment_status"] = "SUBMITTED"
    DB.touch(assessment)
    return ok_object(ser_assessment(assessment))


@app.post(f"{PREFIX}/assessments/<aid>/score")
def score_assessment(aid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    assessment = get_assessment(aid)
    if assessment["assessment_status"] != "SUBMITTED":
        raise err_invalid_state("Assessment must be SUBMITTED to countersign")
    if user_id == assessment["assessor_id"]:
        raise err_segregation("Countersigning director must differ from submitting assessor")
    assessment["assessment_status"] = "SCORED"
    DB.touch(assessment)
    return ok_object(ser_assessment(assessment))


@app.post(f"{PREFIX}/assessments/<aid>/adjudicate")
def adjudicate_assessment(aid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    assessment = get_assessment(aid)
    if assessment["assessment_status"] != "SCORED":
        raise err_invalid_state("Assessment must be SCORED to adjudicate")
    data = body()
    adj = as_int_range(req_field(data, "site_visit_adjustment"), "site_visit_adjustment", -10, 10)
    composite = final_composite(
        assessment["governance_score"], assessment["finance_score"],
        assessment["program_capacity_score"], adj)
    assessment["composite_score"] = composite
    assessment["final_rating"] = rating_for(composite)
    assessment["assessment_status"] = "ADJUDICATED"
    DB.touch(assessment)
    member = DB.members.get(assessment["member_id"])
    if member is not None and member["charter_status"] == "UNDER_ASSESSMENT":
        if assessment["final_rating"] in ("STRONG", "ADEQUATE"):
            member["charter_status"] = "PROVISIONAL"
            DB.touch(member)
        elif assessment["final_rating"] == "DEFICIENT":
            member["charter_status"] = "APPLICANT"
            DB.touch(member)
        recompute_member(member)
    return ok_object(ser_assessment(assessment))


@app.post(f"{PREFIX}/assessments/<aid>/withdraw")
def withdraw_assessment(aid):
    user_id, role = auth()
    require_roles(role, ["Assessor"])
    assessment = get_assessment(aid)
    if assessment["assessment_status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT assessment may be withdrawn")
    assessment["assessment_status"] = "WITHDRAWN"
    DB.touch(assessment)
    member = DB.members.get(assessment["member_id"])
    if member is not None and member["charter_status"] == "UNDER_ASSESSMENT":
        member["charter_status"] = "APPLICANT"
        DB.touch(member)
    return ok_object(ser_assessment(assessment))


# ---------------------------------------------------------------------------
# Counselors
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/counselors")
def create_counselor():
    user_id, role = auth()
    require_roles(role, ["MemberAdmin", "NetworkDirector"])
    data = body()
    member_id = data.get("member_id")
    email = data.get("email")
    if email is not None:
        for c in DB.counselors.values():
            if c["email"] == email:
                raise err_duplicate("email already registered")
    member_id = req_field(data, "member_id")
    member = get_member(member_id)
    check_member_admin_owns(user_id, role, member_id)
    full_name = as_nonempty_str(req_field(data, "full_name"), "full_name")
    email = as_nonempty_str(req_field(data, "email"), "email")
    now = CLOCK.now()
    counselor = DB.new_entity(
        member_id=member_id, full_name=full_name, email=email,
        counselor_status="ACTIVE", ce_credits_accumulated=0,
        ce_window_end=add_months(now, CE_WINDOW_MONTHS),
    )
    DB.counselors[counselor["id"]] = counselor
    return ok_object(ser_counselor(counselor), 201)


@app.get(f"{PREFIX}/counselors")
def list_counselors():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "MemberAdmin", "TrainingRegistrar", "ComplianceReviewer"])
    from flask import request
    items = list(DB.counselors.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [c for c in items if c["member_id"] == member_id]
    status = request.args.get("counselor_status")
    if status:
        items = [c for c in items if c["counselor_status"] == status]
    return paginate([ser_counselor(c) for c in sort_entities(items)])


@app.get(f"{PREFIX}/counselors/<cid>")
def get_one_counselor(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "MemberAdmin", "TrainingRegistrar", "ComplianceReviewer"])
    return ok_object(ser_counselor(get_counselor(cid)))


def _lapse_certifications(counselor):
    member = DB.members.get(counselor["member_id"])
    for cert in sort_entities([c for c in DB.certifications.values()
                               if c["counselor_id"] == counselor["id"]]):
        if cert["certification_status"] == "CERTIFIED":
            cert["certification_status"] = "LAPSED"
            DB.touch(cert)
    if member is not None:
        recompute_member(member)


@app.post(f"{PREFIX}/counselors/<cid>/suspend")
def suspend_counselor(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    counselor = get_counselor(cid)
    if counselor["counselor_status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE counselor may be suspended")
    counselor["counselor_status"] = "SUSPENDED"
    DB.touch(counselor)
    _lapse_certifications(counselor)
    return ok_object(ser_counselor(counselor))


@app.post(f"{PREFIX}/counselors/<cid>/reactivate")
def reactivate_counselor(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    counselor = get_counselor(cid)
    if counselor["counselor_status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED counselor may be reactivated")
    member = DB.members.get(counselor["member_id"])
    if member is None or member["charter_status"] != "CHARTERED":
        raise err_not_chartered("Reactivation requires the employing member to be CHARTERED")
    counselor["counselor_status"] = "ACTIVE"
    DB.touch(counselor)
    return ok_object(ser_counselor(counselor))


@app.post(f"{PREFIX}/counselors/<cid>/separate")
def separate_counselor(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    counselor = get_counselor(cid)
    if counselor["counselor_status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Only an ACTIVE or SUSPENDED counselor may be separated")
    was_active = counselor["counselor_status"] == "ACTIVE"
    counselor["counselor_status"] = "SEPARATED"
    DB.touch(counselor)
    if was_active:
        # withdraw REGISTERED enrollments
        affected_courses = set()
        for e in sort_entities([x for x in DB.enrollments.values()
                                if x["counselor_id"] == cid]):
            if e["enrollment_status"] == "REGISTERED":
                e["enrollment_status"] = "WITHDRAWN"
                DB.touch(e)
                affected_courses.add(e["course_id"])
        for course_id in affected_courses:
            course = DB.courses.get(course_id)
            if course is not None:
                DB.touch(course)
    # revoke non-terminal certifications
    for cert in sort_entities([c for c in DB.certifications.values()
                               if c["counselor_id"] == cid]):
        if cert["certification_status"] not in ("EXPIRED", "REVOKED"):
            cert["certification_status"] = "REVOKED"
            DB.touch(cert)
    member = DB.members.get(counselor["member_id"])
    if member is not None:
        recompute_member(member)
    return ok_object(ser_counselor(counselor))


# ---------------------------------------------------------------------------
# Courses & enrollments
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/courses")
def create_course():
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar"])
    data = body()
    course_code = data.get("course_code")
    if course_code is not None:
        for c in DB.courses.values():
            if c["course_code"] == course_code:
                raise err_duplicate("course_code already exists")
    course_code = as_nonempty_str(req_field(data, "course_code"), "course_code")
    if not COURSE_CODE_RE.match(course_code):
        raise err_invalid_request("course_code must match ^[A-Z]{2,4}-[0-9]{3}$")
    title = req_field(data, "title")
    if not isinstance(title, str):
        raise err_invalid_request("title must be a string")
    program_area = as_enum(req_field(data, "program_area"), "program_area", PROGRAM_AREAS)
    capacity = as_int_range(req_field(data, "capacity"), "capacity", 1, 500)
    ce_eligible = data.get("ce_eligible", False)
    if not isinstance(ce_eligible, bool):
        raise err_invalid_request("ce_eligible must be a boolean")
    ce_credits = data.get("ce_credits", 0)
    ce_credits = as_int_range(ce_credits, "ce_credits", 0, 60)
    try:
        delivery_start = parse_dt(req_field(data, "delivery_start"))
        delivery_end = parse_dt(req_field(data, "delivery_end"))
    except (ValueError, TypeError):
        raise err_invalid_request("delivery_start/delivery_end must be ISO-8601 timestamps")
    if delivery_end <= delivery_start:
        raise err_invalid_request("delivery_end must be strictly after delivery_start")
    prereq_id = data.get("prerequisite_course_id")
    if prereq_id is not None:
        get_course(prereq_id)
    course = DB.new_entity(
        course_code=course_code, title=title, program_area=program_area,
        capacity=capacity, ce_eligible=ce_eligible, ce_credits=ce_credits,
        delivery_start=delivery_start, delivery_end=delivery_end,
        prerequisite_course_id=prereq_id, course_status="SCHEDULED",
    )
    DB.courses[course["id"]] = course
    return ok_object(ser_course(course), 201)


@app.get(f"{PREFIX}/courses")
def list_courses():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "TrainingRegistrar", "MemberAdmin"])
    from flask import request
    items = list(DB.courses.values())
    area = request.args.get("program_area")
    if area:
        items = [c for c in items if c["program_area"] == area]
    status = request.args.get("course_status")
    if status:
        items = [c for c in items if c["course_status"] == status]
    prereq = request.args.get("prerequisite_course_id")
    if prereq:
        items = [c for c in items if c["prerequisite_course_id"] == prereq]
    return paginate([ser_course(c) for c in sort_entities(items)])


@app.get(f"{PREFIX}/courses/<cid>")
def get_one_course(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "TrainingRegistrar", "MemberAdmin"])
    return ok_object(ser_course(get_course(cid)))


@app.get(f"{PREFIX}/courses/<cid>/enrollments")
def list_course_enrollments(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "TrainingRegistrar"])
    course = get_course(cid)
    items = [e for e in DB.enrollments.values() if e["course_id"] == course["id"]]
    return paginate([ser_enrollment(e) for e in sort_entities(items)])


@app.post(f"{PREFIX}/courses/<cid>/cancel")
def cancel_course(cid):
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar"])
    course = get_course(cid)
    if course["course_status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED course may be cancelled")
    course["course_status"] = "CANCELLED"
    DB.touch(course)
    for e in sort_entities([x for x in DB.enrollments.values() if x["course_id"] == cid]):
        if e["enrollment_status"] == "REGISTERED":
            e["enrollment_status"] = "WITHDRAWN"
            DB.touch(e)
    return ok_object(ser_course(course))


@app.post(f"{PREFIX}/courses/<cid>/enrollments")
def create_enrollment(cid):
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar", "MemberAdmin"])
    course = get_course(cid)
    data = body()
    counselor_id = req_field(data, "counselor_id")
    counselor = get_counselor(counselor_id)
    if role == "MemberAdmin":
        check_member_admin_owns(user_id, role, counselor["member_id"])
    # state
    if course["course_status"] in ("CANCELLED", "CONCLUDED"):
        raise err_invalid_state("Course is not open for enrollment")
    # capacity (priority 7)
    if seats_taken(course["id"]) >= course["capacity"]:
        raise err_course_full()
    # prerequisite (priority 8)
    prereq_id = course.get("prerequisite_course_id")
    if prereq_id:
        completed = any(
            e["course_id"] == prereq_id and e["counselor_id"] == counselor_id
            and e["enrollment_status"] == "COMPLETED"
            for e in DB.enrollments.values()
        )
        if not completed:
            raise err_prereq()
    # delivery window (priority 9), half-open [start, end)
    now = CLOCK.now()
    if now < course["delivery_start"] or now >= course["delivery_end"]:
        raise err_window_closed("Enrollment is only permitted within the course delivery window")
    enrollment = DB.new_entity(
        course_id=course["id"], counselor_id=counselor_id,
        enrollment_status="REGISTERED", score=None, pass_threshold=PASS_THRESHOLD,
    )
    DB.enrollments[enrollment["id"]] = enrollment
    DB.touch(course)
    return ok_object(ser_enrollment(enrollment), 201)


@app.get(f"{PREFIX}/enrollments")
def list_enrollments():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "TrainingRegistrar", "MemberAdmin"])
    from flask import request
    items = list(DB.enrollments.values())
    counselor_id = request.args.get("counselor_id")
    if counselor_id:
        items = [e for e in items if e["counselor_id"] == counselor_id]
    status = request.args.get("enrollment_status")
    if status:
        items = [e for e in items if e["enrollment_status"] == status]
    return paginate([ser_enrollment(e) for e in sort_entities(items)])


@app.get(f"{PREFIX}/enrollments/<eid>")
def get_one_enrollment(eid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "TrainingRegistrar", "MemberAdmin"])
    return ok_object(ser_enrollment(get_enrollment(eid)))


@app.post(f"{PREFIX}/enrollments/<eid>/grade")
def grade_enrollment(eid):
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar"])
    enrollment = get_enrollment(eid)
    course = get_course(enrollment["course_id"])
    if enrollment["enrollment_status"] != "REGISTERED":
        raise err_invalid_state("Only a REGISTERED enrollment may be graded")
    if course["course_status"] != "IN_SESSION":
        raise err_invalid_state("Course must be IN_SESSION to grade")
    data = body()
    score = as_int_range(req_field(data, "score"), "score", 0, 100)
    enrollment["pass_threshold"] = PASS_THRESHOLD
    enrollment["score"] = score
    if score >= PASS_THRESHOLD:
        enrollment["enrollment_status"] = "COMPLETED"
        DB.touch(enrollment)
        DB.touch(course)
        if course["ce_eligible"]:
            counselor = DB.counselors.get(enrollment["counselor_id"])
            if counselor is not None:
                counselor["ce_credits_accumulated"] += course["ce_credits"]
                DB.touch(counselor)
        # re-evaluate continuing requirement on CERTIFIED certifications
        for cert in DB.certifications.values():
            if (cert["counselor_id"] == enrollment["counselor_id"]
                    and cert["certification_status"] == "CERTIFIED"):
                counselor = DB.counselors.get(enrollment["counselor_id"])
                met = (counselor is not None
                       and counselor["ce_credits_accumulated"] >= CE_REQUIRED_CREDITS)
                if cert["continuing_requirement_met"] != met:
                    cert["continuing_requirement_met"] = met
                    DB.touch(cert)
    else:
        enrollment["enrollment_status"] = "FAILED"
        DB.touch(enrollment)
        DB.touch(course)  # seat freed
    return ok_object(ser_enrollment(enrollment))


@app.post(f"{PREFIX}/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar", "MemberAdmin"])
    enrollment = get_enrollment(eid)
    if role == "MemberAdmin":
        counselor = DB.counselors.get(enrollment["counselor_id"])
        if counselor is not None:
            check_member_admin_owns(user_id, role, counselor["member_id"])
    if enrollment["enrollment_status"] != "REGISTERED":
        raise err_invalid_state("Only a REGISTERED enrollment may be withdrawn")
    enrollment["enrollment_status"] = "WITHDRAWN"
    DB.touch(enrollment)
    course = DB.courses.get(enrollment["course_id"])
    if course is not None:
        DB.touch(course)
    return ok_object(ser_enrollment(enrollment))


# ---------------------------------------------------------------------------
# Certifications
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/certifications")
def create_certification():
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar"])
    data = body()
    counselor_id = req_field(data, "counselor_id")
    counselor = get_counselor(counselor_id)
    program_area = as_enum(req_field(data, "program_area"), "program_area", PROGRAM_AREAS)
    cert = DB.new_entity(
        counselor_id=counselor_id, program_area=program_area,
        certification_status="CANDIDATE", certified_at=None,
        lapse_deadline=None, continuing_requirement_met=False,
    )
    DB.certifications[cert["id"]] = cert
    return ok_object(ser_cert(cert), 201)


@app.get(f"{PREFIX}/certifications")
def list_certifications():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "TrainingRegistrar", "MemberAdmin", "ComplianceReviewer"])
    from flask import request
    items = list(DB.certifications.values())
    counselor_id = request.args.get("counselor_id")
    if counselor_id:
        items = [c for c in items if c["counselor_id"] == counselor_id]
    status = request.args.get("certification_status")
    if status:
        items = [c for c in items if c["certification_status"] == status]
    area = request.args.get("program_area")
    if area:
        items = [c for c in items if c["program_area"] == area]
    return paginate([ser_cert(c) for c in sort_entities(items)])


@app.get(f"{PREFIX}/certifications/<cid>")
def get_one_certification(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "TrainingRegistrar", "MemberAdmin", "ComplianceReviewer"])
    return ok_object(ser_cert(get_cert(cid)))


@app.post(f"{PREFIX}/certifications/<cid>/certify")
def certify(cid):
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar"])
    cert = get_cert(cid)
    if cert["certification_status"] != "CANDIDATE":
        raise err_invalid_state("Only a CANDIDATE certification may be certified")
    counselor = get_counselor(cert["counselor_id"])
    member = DB.members.get(counselor["member_id"])
    if counselor["counselor_status"] != "ACTIVE":
        raise err_invalid_state("Counselor must be ACTIVE to certify")
    if member is None or member["charter_status"] not in ("PROVISIONAL", "CHARTERED"):
        raise err_not_chartered("Counselor's member must be PROVISIONAL or CHARTERED")
    completed = [
        e for e in DB.enrollments.values()
        if e["counselor_id"] == counselor["id"] and e["enrollment_status"] == "COMPLETED"
    ]
    if not completed:
        raise err_cert_requirement(
            "Counselor has no COMPLETED enrollment")
    matched = any(
        DB.courses.get(e["course_id"], {}).get("program_area") == cert["program_area"]
        for e in completed
    )
    if not matched:
        raise err_cross_entity(
            "No COMPLETED enrollment in a course of this program area")
    now = CLOCK.now()
    cert["certification_status"] = "CERTIFIED"
    cert["certified_at"] = now
    cert["lapse_deadline"] = add_months(now, CE_WINDOW_MONTHS)
    cert["continuing_requirement_met"] = (
        counselor["ce_credits_accumulated"] >= CE_REQUIRED_CREDITS)
    DB.touch(cert)
    return ok_object(ser_cert(cert))


@app.post(f"{PREFIX}/certifications/<cid>/evaluate-continuing-requirement")
def evaluate_ce(cid):
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar"])
    cert = get_cert(cid)
    if cert["certification_status"] != "CERTIFIED":
        raise err_invalid_state("Only a CERTIFIED certification may be evaluated")
    now = CLOCK.now()
    if cert["lapse_deadline"] is None or now <= cert["lapse_deadline"]:
        raise err_window_closed("Evaluation is only permitted after the lapse deadline")
    counselor = DB.counselors.get(cert["counselor_id"])
    met = (counselor is not None
           and counselor["ce_credits_accumulated"] >= CE_REQUIRED_CREDITS)
    cert["continuing_requirement_met"] = met
    if not met:
        cert["certification_status"] = "LAPSED"
    DB.touch(cert)
    if not met and counselor is not None:
        member = DB.members.get(counselor["member_id"])
        if member is not None:
            recompute_member(member)
    return ok_object(ser_cert(cert))


@app.post(f"{PREFIX}/certifications/<cid>/reinstate")
def reinstate_cert(cid):
    user_id, role = auth()
    require_roles(role, ["TrainingRegistrar"])
    cert = get_cert(cid)
    if cert["certification_status"] != "LAPSED":
        raise err_invalid_state("Only a LAPSED certification may be reinstated")
    counselor = get_counselor(cert["counselor_id"])
    if counselor["counselor_status"] != "ACTIVE":
        raise err_invalid_state("Counselor must be ACTIVE to reinstate")
    if counselor["ce_credits_accumulated"] < CE_REQUIRED_CREDITS:
        raise err_cert_requirement("Insufficient CE credits for reinstatement")
    now = CLOCK.now()
    cert["certification_status"] = "CERTIFIED"
    cert["certified_at"] = now
    cert["lapse_deadline"] = add_months(now, CE_WINDOW_MONTHS)
    cert["continuing_requirement_met"] = True
    DB.touch(cert)
    member = DB.members.get(counselor["member_id"])
    if member is not None:
        recompute_member(member)
    return ok_object(ser_cert(cert))


# ---------------------------------------------------------------------------
# Grant cycles
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/grant-cycles")
def create_cycle():
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    data = body()
    fy = data.get("fiscal_year")
    if fy is not None and isinstance(fy, int) and not isinstance(fy, bool):
        for c in DB.cycles.values():
            if c["fiscal_year"] == fy:
                raise err_duplicate("fiscal_year already exists")
    fiscal_year = as_int_range(req_field(data, "fiscal_year"), "fiscal_year", 2000, 2100)
    formula_pool = as_nonneg_int(req_field(data, "formula_pool_cents"), "formula_pool_cents")
    competitive_pool = as_nonneg_int(req_field(data, "competitive_pool_cents"), "competitive_pool_cents")
    for c in DB.cycles.values():
        if c["fiscal_year"] == fiscal_year:
            raise err_duplicate("fiscal_year already exists")
    cycle = DB.new_entity(
        fiscal_year=fiscal_year, formula_pool_cents=formula_pool,
        competitive_pool_cents=competitive_pool, cycle_status="OPEN",
        formula_committed_cents=0, competitive_committed_cents=0,
    )
    DB.cycles[cycle["id"]] = cycle
    return ok_object(ser_cycle(cycle), 201)


@app.get(f"{PREFIX}/grant-cycles")
def list_cycles():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin", "Auditor"])
    from flask import request
    items = list(DB.cycles.values())
    status = request.args.get("cycle_status")
    if status:
        items = [c for c in items if c["cycle_status"] == status]
    return paginate([ser_cycle(c) for c in sort_entities(items)])


@app.get(f"{PREFIX}/grant-cycles/<cid>")
def get_one_cycle(cid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin", "Auditor"])
    return ok_object(ser_cycle(get_cycle(cid)))


@app.post(f"{PREFIX}/grant-cycles/<cid>/lock-formula")
def lock_formula(cid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    cycle = get_cycle(cid)
    if cycle["cycle_status"] != "OPEN":
        raise err_invalid_state("Cycle must be OPEN to lock the formula")
    cycle["cycle_status"] = "FORMULA_LOCKED"
    DB.touch(cycle)
    for app_obj in sort_entities([a for a in DB.applications.values()
                                  if a["cycle_id"] == cid]):
        if app_obj["application_status"] == "SUBMITTED":
            app_obj["application_status"] = "UNDER_REVIEW"
            DB.touch(app_obj)
    return ok_object(ser_cycle(cycle))


@app.post(f"{PREFIX}/grant-cycles/<cid>/open-competitive-review")
def open_competitive_review(cid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    cycle = get_cycle(cid)
    if cycle["cycle_status"] != "FORMULA_LOCKED":
        raise err_invalid_state("Cycle must be FORMULA_LOCKED to open competitive review")
    cycle["cycle_status"] = "COMPETITIVE_REVIEW"
    DB.touch(cycle)
    return ok_object(ser_cycle(cycle))


@app.post(f"{PREFIX}/grant-cycles/<cid>/finalize")
def finalize_cycle(cid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    cycle = get_cycle(cid)
    if cycle["cycle_status"] != "COMPETITIVE_REVIEW":
        raise err_invalid_state("Cycle must be COMPETITIVE_REVIEW to finalize")
    for app_obj in DB.applications.values():
        if (app_obj["cycle_id"] == cid
                and app_obj["application_status"] == "UNDER_REVIEW"
                and app_obj["requested_competitive_cents"] > 0
                and app_obj["review_score"] is None):
            raise err_invalid_state(
                "Cannot finalize: an under-review application with a competitive request lacks a review score")
    cycle["cycle_status"] = "AWARDED"
    DB.touch(cycle)
    return ok_object(ser_cycle(cycle))


@app.post(f"{PREFIX}/grant-cycles/<cid>/close")
def close_cycle(cid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    cycle = get_cycle(cid)
    if cycle["cycle_status"] != "AWARDED":
        raise err_invalid_state("Cycle must be AWARDED to close")
    for award in DB.awards.values():
        if award["cycle_id"] == cid and award["award_status"] not in (
                "RECONCILED", "CLOSED", "TERMINATED"):
            raise err_invalid_state(
                "Cannot close: not every award has reached a terminal state")
    cycle["cycle_status"] = "CLOSED"
    DB.touch(cycle)
    return ok_object(ser_cycle(cycle))


# ---------------------------------------------------------------------------
# Grant applications
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/grant-applications")
def create_application():
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    data = body()
    cycle_id = req_field(data, "cycle_id")
    member_id = req_field(data, "member_id")
    cycle = get_cycle(cycle_id)
    member = get_member(member_id)
    check_member_admin_owns(user_id, role, member_id)
    program_area = as_enum(req_field(data, "program_area"), "program_area", PROGRAM_AREAS)
    req_formula = as_nonneg_int(req_field(data, "requested_formula_cents"), "requested_formula_cents")
    req_competitive = as_nonneg_int(req_field(data, "requested_competitive_cents"), "requested_competitive_cents")
    pledged_match = as_nonneg_int(req_field(data, "pledged_match_cents"), "pledged_match_cents")
    expected = as_int(req_field(data, "expected_cycle_version"), "expected_cycle_version")
    if expected != cycle["version"]:
        raise err_stale_version()
    app_obj = DB.new_entity(
        cycle_id=cycle_id, member_id=member_id, program_area=program_area,
        requested_formula_cents=req_formula,
        requested_competitive_cents=req_competitive,
        pledged_match_cents=pledged_match, application_status="DRAFT",
        review_score=None, reviewer_id=None,
    )
    DB.applications[app_obj["id"]] = app_obj
    DB.touch(cycle)  # creating an application increments the cycle version
    return ok_object(ser_application(app_obj), 201)


@app.get(f"{PREFIX}/grant-applications")
def list_applications():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin"])
    from flask import request
    items = list(DB.applications.values())
    cycle_id = request.args.get("cycle_id")
    if cycle_id:
        items = [a for a in items if a["cycle_id"] == cycle_id]
    member_id = request.args.get("member_id")
    if member_id:
        items = [a for a in items if a["member_id"] == member_id]
    status = request.args.get("application_status")
    if status:
        items = [a for a in items if a["application_status"] == status]
    return paginate([ser_application(a) for a in sort_entities(items)])


@app.get(f"{PREFIX}/grant-applications/<aid>")
def get_one_application(aid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin"])
    return ok_object(ser_application(get_application(aid)))


@app.post(f"{PREFIX}/grant-applications/<aid>/submit")
def submit_application(aid):
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    app_obj = get_application(aid)
    check_member_admin_owns(user_id, role, app_obj["member_id"])
    if app_obj["application_status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT application may be submitted")
    member = DB.members.get(app_obj["member_id"])
    if member is None or member["charter_status"] != "CHARTERED":
        raise err_not_chartered("Only CHARTERED members may submit applications")
    recompute_member(member)
    if member["compliance_posture"] not in ("CLEAR", "WATCH"):
        raise err_posture_blocked("Member posture blocks application submission")
    cycle = DB.cycles.get(app_obj["cycle_id"])
    if cycle is None or cycle["cycle_status"] != "OPEN":
        raise err_window_closed("Applications may only be submitted while the cycle is OPEN")
    app_obj["application_status"] = "SUBMITTED"
    DB.touch(app_obj)
    return ok_object(ser_application(app_obj))


@app.post(f"{PREFIX}/grant-applications/<aid>/score")
def score_application(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    app_obj = get_application(aid)
    if app_obj["application_status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW application may be scored")
    data = body()
    score = as_int_range(req_field(data, "review_score"), "review_score", 0, 100)
    app_obj["review_score"] = score
    app_obj["reviewer_id"] = user_id
    DB.touch(app_obj)
    return ok_object(ser_application(app_obj))


@app.post(f"{PREFIX}/grant-applications/<aid>/award")
def award_application(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    app_obj = get_application(aid)
    if app_obj["application_status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW application may be awarded")
    cycle = DB.cycles.get(app_obj["cycle_id"])
    if cycle is None or cycle["cycle_status"] != "AWARDED":
        raise err_invalid_state("Cycle must be AWARDED before awarding applications")
    # segregation of duties
    if app_obj["review_score"] is not None and user_id == app_obj["reviewer_id"]:
        raise err_segregation("Awarding officer must differ from the reviewer")
    member = DB.members.get(app_obj["member_id"])
    recompute_member(member)
    if member["compliance_posture"] == "FROZEN":
        raise err_posture_blocked("FROZEN members cannot receive awards")
    # competitive floor
    if (app_obj["requested_competitive_cents"] > 0
            and (app_obj["review_score"] is None
                 or app_obj["review_score"] < COMPETITIVE_SCORE_FLOOR)):
        raise err_score_too_low()
    # one award per application
    for a in DB.awards.values():
        if a["application_id"] == aid:
            raise err_duplicate("An award already exists for this application")
    # compute components
    shares = compute_formula_shares(cycle)
    formula_cents = shares.get(aid, 0)
    competitive_cents = competitive_component(
        app_obj["review_score"], app_obj["requested_competitive_cents"])
    # pool sufficiency
    if cycle["formula_committed_cents"] + formula_cents > cycle["formula_pool_cents"]:
        raise err_pool_exhausted("Formula pool exhausted")
    if cycle["competitive_committed_cents"] + competitive_cents > cycle["competitive_pool_cents"]:
        raise err_pool_exhausted("Competitive pool exhausted")
    total = formula_cents + competitive_cents
    match = required_match(member, total)
    award = DB.new_entity(
        application_id=aid, cycle_id=app_obj["cycle_id"],
        member_id=app_obj["member_id"], formula_component_cents=formula_cents,
        competitive_component_cents=competitive_cents,
        required_match_cents=match, verified_match_cents=0,
        award_status="DISBURSING", disbursed_cents=0,
    )
    DB.awards[award["id"]] = award
    app_obj["application_status"] = "AWARDED"
    DB.touch(app_obj)
    cycle["formula_committed_cents"] += formula_cents
    cycle["competitive_committed_cents"] += competitive_cents
    DB.touch(cycle)
    return ok_object(ser_award(award), 201)


@app.post(f"{PREFIX}/grant-applications/<aid>/decline")
def decline_application(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    app_obj = get_application(aid)
    if app_obj["application_status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW application may be declined")
    app_obj["application_status"] = "DECLINED"
    DB.touch(app_obj)
    return ok_object(ser_application(app_obj))


@app.post(f"{PREFIX}/grant-applications/<aid>/withdraw")
def withdraw_application(aid):
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    app_obj = get_application(aid)
    check_member_admin_owns(user_id, role, app_obj["member_id"])
    if app_obj["application_status"] != "DRAFT":
        raise err_invalid_state("Only a DRAFT application may be withdrawn")
    app_obj["application_status"] = "WITHDRAWN"
    DB.touch(app_obj)
    return ok_object(ser_application(app_obj))


# ---------------------------------------------------------------------------
# Grant awards
# ---------------------------------------------------------------------------


@app.get(f"{PREFIX}/grant-awards")
def list_awards():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin", "Auditor"])
    from flask import request
    items = list(DB.awards.values())
    for param, field in (("cycle_id", "cycle_id"), ("member_id", "member_id"),
                         ("application_id", "application_id"),
                         ("award_status", "award_status")):
        v = request.args.get(param)
        if v:
            items = [a for a in items if a[field] == v]
    return paginate([ser_award(a) for a in sort_entities(items)])


@app.get(f"{PREFIX}/grant-awards/<aid>")
def get_one_award(aid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin", "Auditor"])
    return ok_object(ser_award(get_award(aid)))


@app.post(f"{PREFIX}/grant-awards/<aid>/verify-match")
def verify_match(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    award = get_award(aid)
    data = body()
    additional = as_nonneg_int(req_field(data, "additional_match_cents"), "additional_match_cents")
    award["verified_match_cents"] += additional
    DB.touch(award)
    return ok_object(ser_award(award))


@app.post(f"{PREFIX}/grant-awards/<aid>/activate")
def activate_award(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    award = get_award(aid)
    if award["award_status"] != "DISBURSING":
        raise err_invalid_state("Only a DISBURSING award may be activated")
    if award["verified_match_cents"] < award["required_match_cents"]:
        raise err_match_not_met()
    data = body()
    expected = as_int(req_field(data, "expected_award_version"), "expected_award_version")
    if expected != award["version"]:
        raise err_stale_version()
    award["award_status"] = "ACTIVE"
    DB.touch(award)
    return ok_object(ser_award(award))


@app.post(f"{PREFIX}/grant-awards/<aid>/suspend")
def suspend_award(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    award = get_award(aid)
    if award["award_status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE award may be suspended")
    award["award_status"] = "SUSPENDED"
    DB.touch(award)
    return ok_object(ser_award(award))


@app.post(f"{PREFIX}/grant-awards/<aid>/resume")
def resume_award(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    award = get_award(aid)
    if award["award_status"] != "SUSPENDED":
        raise err_invalid_state("Only a SUSPENDED award may be resumed")
    blocking = any(
        a["award_id"] == aid and a["audit_status"] in ("FINDINGS_ISSUED", "ESCALATED")
        for a in DB.audits.values()
    )
    if blocking:
        raise err_invalid_state(
            "Award cannot resume while an audit is FINDINGS_ISSUED or ESCALATED")
    award["award_status"] = "ACTIVE"
    DB.touch(award)
    return ok_object(ser_award(award))


@app.post(f"{PREFIX}/grant-awards/<aid>/reconcile")
def reconcile_award(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    award = get_award(aid)
    if award["award_status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE award may be reconciled")
    total = award["formula_component_cents"] + award["competitive_component_cents"]
    if award["disbursed_cents"] != total:
        raise err_not_reconcilable("Disbursed total does not equal award total")
    for r in DB.exp_reports.values():
        if r["award_id"] == aid and r["report_status"] not in ("ACCEPTED", "AUDITED"):
            raise err_not_reconcilable("Not every expenditure report is ACCEPTED or AUDITED")
    award["award_status"] = "RECONCILED"
    DB.touch(award)
    return ok_object(ser_award(award))


@app.post(f"{PREFIX}/grant-awards/<aid>/close")
def close_award(aid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    award = get_award(aid)
    if award["award_status"] != "RECONCILED":
        raise err_invalid_state("Only a RECONCILED award may be closed")
    award["award_status"] = "CLOSED"
    DB.touch(award)
    return ok_object(ser_award(award))


# ---------------------------------------------------------------------------
# Disbursements
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/disbursements")
def create_disbursement():
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    data = body()
    award_id = req_field(data, "award_id")
    award = get_award(award_id)
    member = DB.members.get(award["member_id"])
    if member is not None:
        recompute_member(member)
        if member["compliance_posture"] == "FROZEN":
            raise err_posture_blocked("FROZEN members cannot receive new disbursements")
    if award["award_status"] == "SUSPENDED":
        raise err_invalid_state("Suspended awards block new disbursement creation")
    if award["award_status"] in ("CLOSED", "TERMINATED"):
        raise err_invalid_state("Terminal awards cannot receive disbursements")
    amount = as_int(req_field(data, "amount_cents"), "amount_cents")
    if amount <= 0:
        raise err_invalid_request("amount_cents must be > 0")
    existing = [d for d in DB.disbursements.values() if d["award_id"] == award_id]
    tranche_index = len(existing) + 1
    disb = DB.new_entity(
        award_id=award_id, tranche_index=tranche_index, amount_cents=amount,
        disbursement_status="PENDING",
    )
    DB.disbursements[disb["id"]] = disb
    return ok_object(ser_disbursement(disb), 201)


@app.get(f"{PREFIX}/disbursements")
def list_disbursements():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "Auditor"])
    from flask import request
    items = list(DB.disbursements.values())
    award_id = request.args.get("award_id")
    if award_id:
        items = [d for d in items if d["award_id"] == award_id]
    status = request.args.get("disbursement_status")
    if status:
        items = [d for d in items if d["disbursement_status"] == status]
    return paginate([ser_disbursement(d) for d in sort_entities(items)])


@app.get(f"{PREFIX}/disbursements/<did>")
def get_one_disbursement(did):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "Auditor"])
    return ok_object(ser_disbursement(get_disbursement(did)))


@app.post(f"{PREFIX}/disbursements/<did>/post")
def post_disbursement(did):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    disb = get_disbursement(did)
    award = get_award(disb["award_id"])
    if disb["disbursement_status"] != "PENDING":
        raise err_invalid_state("Only a PENDING disbursement may be posted")
    if award["award_status"] not in ("DISBURSING", "ACTIVE"):
        raise err_invalid_state("Award must be DISBURSING or ACTIVE to post")
    total = award["formula_component_cents"] + award["competitive_component_cents"]
    if award["disbursed_cents"] + disb["amount_cents"] > total:
        raise err_pool_exhausted("Disbursement would exceed the award total")
    disb["disbursement_status"] = "POSTED"
    DB.touch(disb)
    award["disbursed_cents"] += disb["amount_cents"]
    DB.touch(award)
    return ok_object(ser_disbursement(disb))


@app.post(f"{PREFIX}/disbursements/<did>/void")
def void_disbursement(did):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    disb = get_disbursement(did)
    if disb["disbursement_status"] != "PENDING":
        raise err_invalid_state("Only a PENDING disbursement may be voided")
    disb["disbursement_status"] = "VOIDED"
    DB.touch(disb)
    return ok_object(ser_disbursement(disb))


# ---------------------------------------------------------------------------
# Client files
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/client-files")
def create_client_file():
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    data = body()
    member_id = req_field(data, "member_id")
    counselor_id = req_field(data, "counselor_id")
    member = get_member(member_id)
    counselor = get_counselor(counselor_id)
    check_member_admin_owns(user_id, role, member_id)
    if counselor["member_id"] != member_id:
        raise err_cross_entity("Counselor does not belong to the file's member")
    program_area = as_enum(req_field(data, "program_area"), "program_area", PROGRAM_AREAS)
    household_size = as_int_range(req_field(data, "household_size"), "household_size", 1, 20)
    f = DB.new_entity(
        member_id=member_id, counselor_id=counselor_id, program_area=program_area,
        household_size=household_size, opened_on=CLOCK.now(),
        file_status="OPEN", outcome_code=None, counseling_hours=0.0,
    )
    DB.client_files[f["id"]] = f
    return ok_object(ser_client_file(f), 201)


@app.get(f"{PREFIX}/client-files")
def list_client_files():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "MemberAdmin", "ComplianceReviewer"])
    from flask import request
    items = list(DB.client_files.values())
    for param in ("member_id", "counselor_id", "file_status", "program_area"):
        v = request.args.get(param)
        if v:
            items = [f for f in items if f[param] == v]
    return paginate([ser_client_file(f) for f in sort_entities(items)])


@app.get(f"{PREFIX}/client-files/<fid>")
def get_one_client_file(fid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "MemberAdmin", "ComplianceReviewer"])
    return ok_object(ser_client_file(get_client_file(fid)))


@app.post(f"{PREFIX}/client-files/<fid>/begin-counseling")
def begin_counseling(fid):
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    f = get_client_file(fid)
    check_member_admin_owns(user_id, role, f["member_id"])
    if f["file_status"] != "OPEN":
        raise err_invalid_state("Only an OPEN file may begin counseling")
    member = DB.members.get(f["member_id"])
    if member is not None:
        recompute_member(member)
        if member["compliance_posture"] == "FROZEN":
            raise err_posture_blocked("FROZEN members cannot begin counseling")
    counselor = DB.counselors.get(f["counselor_id"])
    if counselor is None or counselor["counselor_status"] != "ACTIVE":
        raise err_invalid_state("Assigned counselor must be ACTIVE")
    certified = any(
        c["counselor_id"] == counselor["id"]
        and c["certification_status"] == "CERTIFIED"
        and c["program_area"] == f["program_area"]
        for c in DB.certifications.values()
    )
    if not certified:
        raise err_cross_entity(
            "Counselor holds no CERTIFIED certification in the file's program area")
    f["file_status"] = "COUNSELING"
    DB.touch(f)
    return ok_object(ser_client_file(f))


@app.post(f"{PREFIX}/client-files/<fid>/record-outcome")
def record_outcome(fid):
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    f = get_client_file(fid)
    check_member_admin_owns(user_id, role, f["member_id"])
    if f["file_status"] != "COUNSELING":
        raise err_invalid_state("Only a COUNSELING file may record an outcome")
    data = body()
    outcome = as_enum(req_field(data, "outcome_code"), "outcome_code", OUTCOME_CODES)
    hours_raw = req_field(data, "counseling_hours")
    if isinstance(hours_raw, bool) or not isinstance(hours_raw, (int, float)):
        raise err_invalid_request("counseling_hours must be a number")
    hours = Decimal(str(hours_raw))
    if hours < 0 or hours != hours.quantize(Decimal("0.1")):
        raise err_invalid_request("counseling_hours must be >= 0 with one decimal place")
    if outcome == "NO_OUTCOME" and hours < Decimal(str(MIN_HOURS_NO_OUTCOME)):
        raise err_hours_insufficient()
    f["outcome_code"] = outcome
    f["counseling_hours"] = float(hours)
    f["file_status"] = "OUTCOME_RECORDED"
    DB.touch(f)
    return ok_object(ser_client_file(f))


@app.post(f"{PREFIX}/client-files/<fid>/close")
def close_client_file(fid):
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    f = get_client_file(fid)
    check_member_admin_owns(user_id, role, f["member_id"])
    if f["file_status"] != "OUTCOME_RECORDED":
        raise err_invalid_state("Only an OUTCOME_RECORDED file may be closed")
    for r in DB.file_reviews.values():
        if r["client_file_id"] == fid and r["review_status"] not in ("PASSED", "REMEDIATED"):
            raise err_review_pending()
    f["file_status"] = "CLOSED"
    DB.touch(f)
    return ok_object(ser_client_file(f))


# ---------------------------------------------------------------------------
# File reviews
# ---------------------------------------------------------------------------


@app.post(f"{PREFIX}/file-reviews")
def create_file_review():
    user_id, role = auth()
    require_roles(role, ["ComplianceReviewer"])
    data = body()
    client_file_id = req_field(data, "client_file_id")
    get_client_file(client_file_id)
    review = DB.new_entity(
        client_file_id=client_file_id, reviewer_id=user_id,
        review_status="OPEN", deficiency_codes=[], reviewed_at=None,
    )
    DB.file_reviews[review["id"]] = review
    return ok_object(ser_file_review(review), 201)


@app.get(f"{PREFIX}/file-reviews")
def list_file_reviews():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "ComplianceReviewer", "MemberAdmin"])
    from flask import request
    items = list(DB.file_reviews.values())
    cf = request.args.get("client_file_id")
    if cf:
        items = [r for r in items if r["client_file_id"] == cf]
    status = request.args.get("review_status")
    if status:
        items = [r for r in items if r["review_status"] == status]
    return paginate([ser_file_review(r) for r in sort_entities(items)])


@app.get(f"{PREFIX}/file-reviews/<rid>")
def get_one_file_review(rid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "ComplianceReviewer", "MemberAdmin"])
    return ok_object(ser_file_review(get_file_review(rid)))


def _member_of_review(review):
    f = DB.client_files.get(review["client_file_id"])
    if f is None:
        return None
    return DB.members.get(f["member_id"])


@app.post(f"{PREFIX}/file-reviews/<rid>/pass")
def pass_file_review(rid):
    user_id, role = auth()
    require_roles(role, ["ComplianceReviewer"])
    review = get_file_review(rid)
    if review["review_status"] != "OPEN":
        raise err_invalid_state("Only an OPEN review may be passed")
    review["review_status"] = "PASSED"
    review["reviewed_at"] = CLOCK.now()
    DB.touch(review)
    member = _member_of_review(review)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_file_review(review))


@app.post(f"{PREFIX}/file-reviews/<rid>/fail")
def fail_file_review(rid):
    user_id, role = auth()
    require_roles(role, ["ComplianceReviewer"])
    review = get_file_review(rid)
    if review["review_status"] != "OPEN":
        raise err_invalid_state("Only an OPEN review may be failed")
    data = body()
    codes = req_field(data, "deficiency_codes")
    if not isinstance(codes, list) or not codes:
        raise err_invalid_request("deficiency_codes must be a non-empty list")
    review["review_status"] = "FAILED"
    review["deficiency_codes"] = codes
    review["reviewed_at"] = CLOCK.now()
    DB.touch(review)
    member = _member_of_review(review)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_file_review(review))


@app.post(f"{PREFIX}/file-reviews/<rid>/remediate")
def remediate_file_review(rid):
    user_id, role = auth()
    require_roles(role, ["ComplianceReviewer"])
    review = get_file_review(rid)
    if review["review_status"] != "FAILED":
        raise err_invalid_state("Only a FAILED review may be remediated")
    review["review_status"] = "REMEDIATED"
    DB.touch(review)
    member = _member_of_review(review)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_file_review(review))


# ---------------------------------------------------------------------------
# Expenditure reports
# ---------------------------------------------------------------------------


def compute_cumulative(report, include_self):
    award_id = report["award_id"]
    total = 0
    for r in DB.exp_reports.values():
        if r["award_id"] != award_id or r["id"] == report["id"]:
            continue
        if r["report_status"] in ("ACCEPTED", "AUDITED") and r["period_start"] <= report["period_start"]:
            total += r["reported_spent_cents"]
    if include_self and report["report_status"] in ("ACCEPTED", "AUDITED"):
        total += report["reported_spent_cents"]
    return total


def recompute_report_cumulatives(award_id):
    for r in DB.exp_reports.values():
        if r["award_id"] != award_id:
            continue
        new_cum = compute_cumulative(r, include_self=True)
        if r["cumulative_spent_cents"] != new_cum:
            r["cumulative_spent_cents"] = new_cum
            DB.touch(r)


@app.post(f"{PREFIX}/expenditure-reports")
def create_exp_report():
    user_id, role = auth()
    require_roles(role, ["MemberAdmin"])
    data = body()
    award_id = req_field(data, "award_id")
    award = get_award(award_id)
    check_member_admin_owns(user_id, role, award["member_id"])
    try:
        period_start = parse_dt(req_field(data, "period_start"))
        period_end = parse_dt(req_field(data, "period_end"))
    except (ValueError, TypeError):
        raise err_invalid_request("period_start/period_end must be ISO-8601 timestamps")
    if period_end <= period_start:
        raise err_invalid_request("period_end must be strictly after period_start")
    spent = as_nonneg_int(req_field(data, "reported_spent_cents"), "reported_spent_cents")
    report = DB.new_entity(
        award_id=award_id, period_start=period_start, period_end=period_end,
        reported_spent_cents=spent, report_status="SUBMITTED",
        cumulative_spent_cents=0,
    )
    DB.exp_reports[report["id"]] = report
    report["cumulative_spent_cents"] = compute_cumulative(report, include_self=False)
    return ok_object(ser_exp_report(report), 201)


@app.get(f"{PREFIX}/expenditure-reports")
def list_exp_reports():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin", "Auditor"])
    from flask import request
    items = list(DB.exp_reports.values())
    award_id = request.args.get("award_id")
    if award_id:
        items = [r for r in items if r["award_id"] == award_id]
    status = request.args.get("report_status")
    if status:
        items = [r for r in items if r["report_status"] == status]
    return paginate([ser_exp_report(r) for r in sort_entities(items)])


@app.get(f"{PREFIX}/expenditure-reports/<rid>")
def get_one_exp_report(rid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer", "MemberAdmin", "Auditor"])
    return ok_object(ser_exp_report(get_exp_report(rid)))


@app.post(f"{PREFIX}/expenditure-reports/<rid>/accept")
def accept_exp_report(rid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    report = get_exp_report(rid)
    if report["report_status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED report may be accepted")
    award = get_award(report["award_id"])
    projected = compute_cumulative(report, include_self=False) + report["reported_spent_cents"]
    if projected > award["disbursed_cents"]:
        raise err_pool_exhausted("Cumulative spending would exceed disbursed amount")
    report["report_status"] = "ACCEPTED"
    DB.touch(report)
    recompute_report_cumulatives(report["award_id"])
    return ok_object(ser_exp_report(report))


@app.post(f"{PREFIX}/expenditure-reports/<rid>/flag")
def flag_exp_report(rid):
    user_id, role = auth()
    require_roles(role, ["GrantOfficer"])
    report = get_exp_report(rid)
    if report["report_status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED report may be flagged")
    report["report_status"] = "FLAGGED"
    DB.touch(report)
    audit = DB.new_entity(
        award_id=report["award_id"], auditor_id=None, audit_status="OPEN",
        disallowance_cents=0, parent_audit_id=None,
    )
    audit["_source_report_id"] = report["id"]
    DB.audits[audit["id"]] = audit
    return ok_object(ser_exp_report(report))


# ---------------------------------------------------------------------------
# Compliance audits
# ---------------------------------------------------------------------------


@app.get(f"{PREFIX}/compliance-audits")
def list_audits():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "Auditor", "GrantOfficer"])
    from flask import request
    items = list(DB.audits.values())
    award_id = request.args.get("award_id")
    if award_id:
        items = [a for a in items if a["award_id"] == award_id]
    status = request.args.get("audit_status")
    if status:
        items = [a for a in items if a["audit_status"] == status]
    parent = request.args.get("parent_audit_id")
    if parent:
        items = [a for a in items if a.get("parent_audit_id") == parent]
    return paginate([ser_audit(a) for a in sort_entities(items)])


@app.get(f"{PREFIX}/compliance-audits/<aid>")
def get_one_audit(aid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "Auditor", "GrantOfficer"])
    return ok_object(ser_audit(get_audit(aid)))


def _member_of_audit(audit):
    award = DB.awards.get(audit["award_id"])
    if award is None:
        return None
    return DB.members.get(award["member_id"])


@app.post(f"{PREFIX}/compliance-audits/<aid>/issue-findings")
def issue_findings(aid):
    user_id, role = auth()
    require_roles(role, ["Auditor"])
    audit = get_audit(aid)
    if audit["audit_status"] != "OPEN":
        raise err_invalid_state("Only an OPEN audit may issue findings")
    data = body()
    disallowance = as_nonneg_int(req_field(data, "disallowance_cents"), "disallowance_cents")
    audit["disallowance_cents"] = disallowance
    audit["auditor_id"] = user_id
    audit["audit_status"] = "FINDINGS_ISSUED"
    DB.touch(audit)
    # cascade link 2: linked flagged report -> AUDITED
    source_report_id = audit.get("_source_report_id")
    if source_report_id:
        report = DB.exp_reports.get(source_report_id)
        if report is not None and report["report_status"] == "FLAGGED":
            report["report_status"] = "AUDITED"
            DB.touch(report)
            recompute_report_cumulatives(report["award_id"])
    member = _member_of_audit(audit)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_audit(audit))


@app.post(f"{PREFIX}/compliance-audits/<aid>/resolve")
def resolve_audit(aid):
    user_id, role = auth()
    require_roles(role, ["Auditor"])
    audit = get_audit(aid)
    if audit["audit_status"] != "FINDINGS_ISSUED":
        raise err_invalid_state("Only a FINDINGS_ISSUED audit may be resolved")
    audit["audit_status"] = "RESOLVED"
    DB.touch(audit)
    member = _member_of_audit(audit)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_audit(audit))


@app.post(f"{PREFIX}/compliance-audits/<aid>/escalate")
def escalate_audit(aid):
    user_id, role = auth()
    require_roles(role, ["Auditor"])
    audit = get_audit(aid)
    if audit["audit_status"] != "FINDINGS_ISSUED":
        raise err_invalid_state("Only a FINDINGS_ISSUED audit may be escalated")
    if audit["disallowance_cents"] <= 0:
        raise err_invalid_state("Escalation requires a disallowance greater than zero")
    audit["audit_status"] = "ESCALATED"
    DB.touch(audit)
    award = DB.awards.get(audit["award_id"])
    if award is not None:
        if award["award_status"] in ("ACTIVE", "DISBURSING"):
            award["award_status"] = "SUSPENDED"
        clawback = audit["disallowance_cents"]
        award["disbursed_cents"] = max(0, award["disbursed_cents"] - clawback)
        DB.touch(award)
        # credit the cycle pools back: competitive first, then formula
        cycle = DB.cycles.get(award["cycle_id"])
        if cycle is not None:
            comp_credit = min(clawback, cycle["competitive_committed_cents"])
            cycle["competitive_committed_cents"] -= comp_credit
            remainder = clawback - comp_credit
            formula_credit = min(remainder, cycle["formula_committed_cents"])
            cycle["formula_committed_cents"] -= formula_credit
            DB.touch(cycle)
    member = _member_of_audit(audit)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_audit(audit))


@app.post(f"{PREFIX}/compliance-audits/<aid>/reopen")
def reopen_audit(aid):
    user_id, role = auth()
    require_roles(role, ["Auditor"])
    audit = get_audit(aid)
    if audit["audit_status"] != "FINDINGS_ISSUED":
        raise err_invalid_state("Only a FINDINGS_ISSUED audit may be re-opened")
    audit["audit_status"] = "OPEN"
    DB.touch(audit)
    successor = DB.new_entity(
        award_id=audit["award_id"], auditor_id=user_id, audit_status="OPEN",
        disallowance_cents=0, parent_audit_id=aid,
    )
    DB.audits[successor["id"]] = successor
    member = _member_of_audit(audit)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_audit(successor), 201)


# ---------------------------------------------------------------------------
# Performance reviews
# ---------------------------------------------------------------------------


def review_fiscal_year(review):
    m = FY_LABEL_RE.search(review["review_period"] or "")
    if m:
        return int(m.group(1))
    opened = review["created_at"]
    return opened.year + 1 if opened.month >= 10 else opened.year


@app.post(f"{PREFIX}/performance-reviews")
def create_perf_review():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    data = body()
    member_id = req_field(data, "member_id")
    member = get_member(member_id)
    review_period = data.get("review_period")
    if review_period is not None:
        for r in DB.perf_reviews.values():
            if r["member_id"] == member_id and r["review_period"] == review_period:
                raise err_duplicate("review_period already exists for this member")
    review_period = as_nonempty_str(review_period, "review_period")
    review = DB.new_entity(
        member_id=member_id, review_period=review_period, households_served=0,
        review_score=None, review_status="OPEN", corrective_plan_due=None,
    )
    DB.perf_reviews[review["id"]] = review
    return ok_object(ser_perf_review(review), 201)


@app.get(f"{PREFIX}/performance-reviews")
def list_perf_reviews():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "MemberAdmin"])
    from flask import request
    items = list(DB.perf_reviews.values())
    member_id = request.args.get("member_id")
    if member_id:
        items = [r for r in items if r["member_id"] == member_id]
    status = request.args.get("review_status")
    if status:
        items = [r for r in items if r["review_status"] == status]
    return paginate([ser_perf_review(r) for r in sort_entities(items)])


@app.get(f"{PREFIX}/performance-reviews/<rid>")
def get_one_perf_review(rid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "MemberAdmin"])
    return ok_object(ser_perf_review(get_perf_review(rid)))


@app.post(f"{PREFIX}/performance-reviews/<rid>/score")
def score_perf_review(rid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    review = get_perf_review(rid)
    if review["review_status"] != "OPEN":
        raise err_invalid_state("Only an OPEN review may be scored")
    data = body()
    score = as_int_range(req_field(data, "review_score"), "review_score", 0, 100)
    review["review_score"] = score
    review["households_served"] = households_served(
        review["member_id"], review_fiscal_year(review))
    review["review_status"] = "SCORED"
    DB.touch(review)
    return ok_object(ser_perf_review(review))


@app.post(f"{PREFIX}/performance-reviews/<rid>/resolve")
def resolve_perf_review(rid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    review = get_perf_review(rid)
    if review["review_status"] != "SCORED":
        raise err_invalid_state("Only a SCORED review may be resolved")
    data = body()
    verdict = as_enum(req_field(data, "verdict"), "verdict",
                      {"SATISFACTORY", "CORRECTIVE_ACTION"})
    member = DB.members.get(review["member_id"])
    if verdict == "SATISFACTORY":
        if review["review_score"] < PERFORMANCE_PASS_SCORE:
            raise err_invalid_state(
                "SATISFACTORY verdict requires a score of at least 70")
        review["review_status"] = "SATISFACTORY"
        DB.touch(review)
    else:
        if review["review_score"] >= PERFORMANCE_PASS_SCORE:
            raise err_invalid_state(
                "CORRECTIVE_ACTION verdict requires a score below 70")
        review["review_status"] = "CORRECTIVE_ACTION"
        review["corrective_plan_due"] = CLOCK.now() + timedelta(days=CORRECTIVE_PLAN_DAYS)
        DB.touch(review)
        if member is not None:
            recompute_member(member)
    return ok_object(ser_perf_review(review))


@app.post(f"{PREFIX}/performance-reviews/<rid>/close-plan")
def close_plan_perf_review(rid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    review = get_perf_review(rid)
    if review["review_status"] != "CORRECTIVE_ACTION":
        raise err_invalid_state("Only a CORRECTIVE_ACTION review may close its plan")
    now = CLOCK.now()
    if review["corrective_plan_due"] is not None and now > review["corrective_plan_due"]:
        raise err_window_closed("The corrective plan deadline has passed")
    member = DB.members.get(review["member_id"])
    if member is not None:
        recompute_member(member)
        if member["open_finding_count"] != 0:
            raise err_invalid_state(
                "Plan close requires zero open findings for the member")
    review["review_status"] = "CLOSED"
    DB.touch(review)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_perf_review(review))


@app.post(f"{PREFIX}/performance-reviews/<rid>/escalate")
def escalate_perf_review(rid):
    user_id, role = auth()
    require_roles(role, ["NetworkDirector"])
    review = get_perf_review(rid)
    if review["review_status"] != "CORRECTIVE_ACTION":
        raise err_invalid_state("Only a CORRECTIVE_ACTION review may be escalated")
    now = CLOCK.now()
    if review["corrective_plan_due"] is None or now <= review["corrective_plan_due"]:
        raise err_window_closed("Escalation requires the corrective plan deadline to have passed")
    review["review_status"] = "ESCALATED"
    DB.touch(review)
    member = DB.members.get(review["member_id"])
    if member is not None and member["charter_status"] == "CHARTERED":
        member["charter_status"] = "PROBATION"
        DB.touch(member)
    if member is not None:
        recompute_member(member)
    return ok_object(ser_perf_review(review))


# ---------------------------------------------------------------------------
# Congressional report
# ---------------------------------------------------------------------------


@app.get(f"{PREFIX}/reports/congressional")
def congressional_report():
    user_id, role = auth()
    require_roles(role, ["NetworkDirector", "GrantOfficer"])
    from flask import request
    fy_raw = request.args.get("fiscal_year")
    if fy_raw is None:
        raise err_invalid_request("fiscal_year query parameter is required")
    try:
        fiscal_year = int(fy_raw)
    except (TypeError, ValueError):
        raise err_invalid_request("fiscal_year must be an integer")
    by_area = {area: 0 for area in sorted(PROGRAM_AREAS)}
    total = 0
    for member in DB.members.values():
        if member["charter_status"] == "REVOKED":
            continue
        mid = member["id"]
        # per-area breakdown for this member
        from logic import fy_window
        start, end = fy_window(fiscal_year)
        for f in DB.client_files.values():
            if f["member_id"] != mid:
                continue
            if f["file_status"] not in ("OUTCOME_RECORDED", "CLOSED"):
                continue
            oc = f.get("outcome_code")
            if oc is None or oc == "NO_OUTCOME":
                continue
            opened = f["opened_on"]
            if opened is None or opened < start or opened >= end:
                continue
            by_area[f["program_area"]] += 1
            total += 1
    return ok_object({
        "fiscal_year": fiscal_year,
        "total_households": total,
        "by_program_area": by_area,
    })


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
