"""School applications: level-advancement workflow (PRD 3.7)."""

from flask import Blueprint, request

from cascade import IN_FLIGHT_APPLICATION_STATES, OPEN_PLAN_STATES
from derived import school_clearance, brand_compliant, dues_current
from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_SCHOOL_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_VALIDATION,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_ACCREDITATION_TENURE_TOO_SHORT,
    ERR_SELF_STUDY_REQUIRED,
    ERR_VERIFICATION_VISIT_REQUIRED,
    ERR_CLASSROOM_REQUIRED,
    ERR_BRAND_DIFFERENTIATION_REQUIRED,
    ERR_CLASSROOM_NONCOMPLIANT,
    ERR_OPEN_IMPROVEMENT_PLAN,
    ERR_DUES_DELINQUENT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_IN_FLIGHT_APPLICATION_EXISTS,
    ERR_NO_ACTIVE_CATALOG,
)
from derived import school_classrooms
from serializers import serialize_application
from store import (
    db,
    new_id,
    stamp_new,
    touch,
    now_date,
    now_iso,
    active_catalog,
    parse_date,
    add_months,
)
from validation import authenticate, require_role, payload, req_enum

bp = Blueprint("applications", __name__)

APP_ROLES = {"SocietyAdmin", "AccreditationReviewer", "SchoolAdmin"}
APP_TYPES = {"AFFILIATION", "MEMBERSHIP", "ACCREDITATION"}
APP_OUTCOMES = {"APPROVED", "DENIED", "RETURNED"}

# The application type must name the school's next level.
_NEXT_TYPE = {
    "APPLICANT": "AFFILIATION",
    "AFFILIATE": "MEMBERSHIP",
    "MEMBER": "ACCREDITATION",
}
_NEXT_LEVEL = {
    "AFFILIATION": "AFFILIATE",
    "MEMBERSHIP": "MEMBER",
    "ACCREDITATION": "ACCREDITED",
}


def get_application_or_404(app_id):
    a = db.applications.get(app_id)
    if a is None:
        raise ApiError(ERR_APPLICATION_NOT_FOUND[0], ERR_APPLICATION_NOT_FOUND[1],
                       "No school application with id %r." % app_id)
    return a


def _latest_accepted_self_study(school_id):
    studies = [
        s for s in db.self_studies.values()
        if s["school_id"] == school_id and s["status"] == "ACCEPTED"
    ]
    if not studies:
        return None
    return max(studies, key=lambda s: (s["created_at"], s["_seq"]))


def _latest_report_filed_visit(self_study_id):
    visits = [
        v for v in db.visits.values()
        if v["self_study_id"] == self_study_id and v["status"] == "REPORT_FILED"
    ]
    if not visits:
        return None
    return max(visits, key=lambda v: (v["created_at"], v["_seq"]))


@bp.route("/school-applications", methods=["POST"])
def create_application():
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    body = payload()
    # Tier 3: school_id body FK.
    school_id = body.get("school_id")
    school = None
    if isinstance(school_id, str):
        school = db.schools.get(school_id)
        if school is None:
            raise ApiError(ERR_SCHOOL_NOT_FOUND[0], ERR_SCHOOL_NOT_FOUND[1],
                           "No school with id %r." % school_id)
    # Tier 4: shape (expected_school_version is a non-optional input, PRD 2.8).
    if not isinstance(school_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'school_id' is required and must be a string.")
    app_type = req_enum(body, "type", APP_TYPES)
    expected = body.get("expected_school_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'expected_school_version' is required and must be an integer.")
    # Tier 5: SchoolAdmin owns the school.
    if uid != school["id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "SchoolAdmin may only apply for their own school.")
    # Tier 6: OCC first, then the type-matches-next-level state check.
    if expected != school["version"]:
        raise ApiError(ERR_STALE_VERSION[0], ERR_STALE_VERSION[1],
                       "expected_school_version does not match the school's current version.")
    if _NEXT_TYPE.get(school["membership_level"]) != app_type:
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Application type does not match the school's next level.")
    # Tier 9: at most one in-flight application per school.
    for a in db.applications.values():
        if a["school_id"] == school["id"] and a["status"] in IN_FLIGHT_APPLICATION_STATES:
            raise ApiError(ERR_IN_FLIGHT_APPLICATION_EXISTS[0],
                           ERR_IN_FLIGHT_APPLICATION_EXISTS[1],
                           "The school already has an in-flight application.")
    app = {
        "id": new_id(),
        "school_id": school["id"],
        "type": app_type,
        "status": "DRAFT",
        "supporting_self_study_id": None,
        "submitted_at": None,
        "decided_at": None,
        "reviewer_user_id": None,
    }
    stamp_new(app)
    db.applications[app["id"]] = app
    touch(school)  # creating an application is a direct school mutation
    return ok(serialize_application(app), 201)


@bp.route("/school-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    _, role = authenticate()
    require_role(role, APP_ROLES)
    return ok(serialize_application(get_application_or_404(app_id)), 200)


@bp.route("/school-applications", methods=["GET"])
def list_applications():
    _, role = authenticate()
    require_role(role, APP_ROLES)
    args = request.args
    items = list(db.applications.values())
    for f in ("school_id", "status", "type", "supporting_self_study_id"):
        v = args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_application)


@bp.route("/school-applications/<app_id>/submit", methods=["POST"])
def submit_application(app_id):
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    app = get_application_or_404(app_id)
    # Tier 5: ownership.
    if uid != app["school_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "SchoolAdmin may only submit their own school's application.")
    # Tier 6: submission only from DRAFT or RETURNED.
    if app["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a DRAFT or RETURNED application can be submitted.")
    school = db.schools[app["school_id"]]
    cat = active_catalog()
    study = None
    # Tier 7: ACCREDITATION tenure against the ACTIVE catalog (equality passes).
    if app["type"] == "ACCREDITATION":
        if cat is None:
            raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                           "No ACTIVE standards catalog exists.")
        member_since = parse_date(school.get("member_since") or "")
        eligible = None
        if member_since is not None:
            eligible = add_months(member_since, int(cat["min_membership_months_before_accreditation"]))
        if eligible is None or now_date() < eligible:
            raise ApiError(ERR_ACCREDITATION_TENURE_TOO_SHORT[0],
                           ERR_ACCREDITATION_TENURE_TOO_SHORT[1],
                           "The school has not held MEMBER level long enough.")
    # Tier 8: ACCREDITATION needs an ACCEPTED self-study and a REPORT_FILED visit.
    if app["type"] == "ACCREDITATION":
        study = _latest_accepted_self_study(school["id"])
        if study is None:
            raise ApiError(ERR_SELF_STUDY_REQUIRED[0], ERR_SELF_STUDY_REQUIRED[1],
                           "An ACCEPTED self-study is required.")
        if _latest_report_filed_visit(study["id"]) is None:
            raise ApiError(ERR_VERIFICATION_VISIT_REQUIRED[0],
                           ERR_VERIFICATION_VISIT_REQUIRED[1],
                           "A REPORT_FILED verification visit on the accepted "
                           "self-study is required.")
    # Tier 9: per-type constraint checks.
    if app["type"] == "AFFILIATION":
        if not school_classrooms(school["id"]):
            raise ApiError(ERR_CLASSROOM_REQUIRED[0], ERR_CLASSROOM_REQUIRED[1],
                           "AFFILIATION requires at least one classroom.")
        if not brand_compliant(school):
            raise ApiError(ERR_BRAND_DIFFERENTIATION_REQUIRED[0],
                           ERR_BRAND_DIFFERENTIATION_REQUIRED[1],
                           "The school is not brand-compliant.")
    elif app["type"] == "MEMBERSHIP":
        if not school_clearance(school["id"], "LATEST_PASS"):
            raise ApiError(ERR_CLASSROOM_NONCOMPLIANT[0], ERR_CLASSROOM_NONCOMPLIANT[1],
                           "Not every classroom clears LATEST_PASS.")
    else:  # ACCREDITATION
        if not school_clearance(school["id"], "NO_FAIL_IN_CYCLE"):
            raise ApiError(ERR_CLASSROOM_NONCOMPLIANT[0], ERR_CLASSROOM_NONCOMPLIANT[1],
                           "Not every classroom clears NO_FAIL_IN_CYCLE.")
        open_plans = [
            p for p in db.plans.values()
            if p["school_id"] == school["id"] and p["status"] in OPEN_PLAN_STATES
        ]
        if open_plans:
            raise ApiError(ERR_OPEN_IMPROVEMENT_PLAN[0], ERR_OPEN_IMPROVEMENT_PLAN[1],
                           "The school has an open improvement plan.")
    # Tier 10: fiscal — dues must be current at submission.
    if not dues_current(school):
        raise ApiError(ERR_DUES_DELINQUENT[0], ERR_DUES_DELINQUENT[1],
                       "The school's dues are not current.")
    app["status"] = "UNDER_REVIEW"
    app["submitted_at"] = now_iso()
    if app["type"] == "ACCREDITATION":
        app["supporting_self_study_id"] = study["id"]
    touch(app)
    return ok(serialize_application(app), 200)


@bp.route("/school-applications/<app_id>/review", methods=["POST"])
def review_application(app_id):
    uid, role = authenticate()
    require_role(role, {"AccreditationReviewer"})
    app = get_application_or_404(app_id)
    body = payload()
    outcome = req_enum(body, "outcome", APP_OUTCOMES)
    # Tier 6: only an UNDER_REVIEW application is actionable.
    if app["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an UNDER_REVIEW application can be reviewed.")
    school = db.schools[app["school_id"]]
    if outcome == "RETURNED":
        app["status"] = "RETURNED"
        touch(app)
        return ok(serialize_application(app), 200)
    if outcome == "DENIED":
        app["status"] = "DENIED"
        app["decided_at"] = now_iso()
        app["reviewer_user_id"] = uid
        touch(app)
        return ok(serialize_application(app), 200)
    # APPROVED: tier-6/8 posture checks for ACCREDITATION, tier-9 segregation,
    # tier-10 dues recheck.
    if app["type"] == "ACCREDITATION":
        if school["standing"] != "GOOD_STANDING":
            raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                           "ACCREDITATION approval requires GOOD_STANDING.")
        visit = _latest_report_filed_visit(app.get("supporting_self_study_id") or "")
        verdict_ok = False
        if visit is not None:
            if visit["verdict"] == "COMPLIANT":
                verdict_ok = True
            elif visit["verdict"] == "IMPROVEMENT_REQUIRED":
                verdict_ok = any(
                    p["visit_id"] == visit["id"] and p["status"] == "VERIFIED"
                    for p in db.plans.values()
                )
        if not verdict_ok:
            raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                           "The supporting visit's verdict does not permit approval.")
        if uid == visit["consultant_id"]:
            raise ApiError(ERR_SEGREGATION_OF_DUTIES[0], ERR_SEGREGATION_OF_DUTIES[1],
                           "The approving reviewer must differ from the visit's consultant.")
    if not dues_current(school):
        raise ApiError(ERR_DUES_DELINQUENT[0], ERR_DUES_DELINQUENT[1],
                       "The school's dues are not current at decision time.")
    # Advance the school's membership level and stamp the anniversary.
    new_level = _NEXT_LEVEL[app["type"]]
    school["membership_level"] = new_level
    today = now_date().isoformat()
    if new_level == "AFFILIATE":
        school["affiliated_since"] = today
    elif new_level == "MEMBER":
        school["member_since"] = today
    elif new_level == "ACCREDITED":
        school["accredited_since"] = today
    touch(school)  # a membership-level advance is a direct school mutation
    app["status"] = "APPROVED"
    app["decided_at"] = now_iso()
    app["reviewer_user_id"] = uid
    touch(app)
    return ok(serialize_application(app), 200)
