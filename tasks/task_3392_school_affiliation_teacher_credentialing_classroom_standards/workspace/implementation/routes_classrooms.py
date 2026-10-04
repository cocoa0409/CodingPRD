"""Classrooms, student transfers, and classroom standards audits
(PRD 3.3; calculations.classroom_ratio_compliance, work_period_compliance,
materials_completeness_score, classroom_audit_verdict, transfer_conservation)."""

from decimal import Decimal

from flask import Blueprint, request

from derived import round2, round4, total_enrollment
from envelope import ok, pagination_params, list_response
from errors import (
    ApiError,
    ERR_VALIDATION,
    ERR_FORBIDDEN,
    ERR_SCHOOL_NOT_FOUND,
    ERR_CLASSROOM_NOT_FOUND,
    ERR_AUDIT_NOT_FOUND,
    ERR_CREDENTIAL_NOT_FOUND,
    ERR_VISIT_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_AGE_LEVEL_MISMATCH,
    ERR_TRANSFER_CROSS_SCHOOL,
    ERR_TRANSFER_EXCEEDS_ENROLLMENT,
    ERR_NO_ACTIVE_CATALOG,
)
from serializers import serialize_classroom, serialize_audit
from store import db, new_id, stamp_new, stamp_new_lean, touch, now_iso, active_catalog
from validation import (
    authenticate,
    require_role,
    payload,
    req_str,
    req_int,
    req_enum,
    req_list,
    AGE_LEVELS,
)

bp = Blueprint("classrooms", __name__)

CLASSROOM_READ_ROLES = {"SocietyAdmin", "AccreditationReviewer", "SchoolAdmin", "Consultant"}


def get_classroom_or_404(classroom_id):
    c = db.classrooms.get(classroom_id)
    if c is None:
        raise ApiError(ERR_CLASSROOM_NOT_FOUND[0], ERR_CLASSROOM_NOT_FOUND[1],
                       "No classroom with id %r." % classroom_id)
    return c


# ---------------------------------------------------------------------------
# Classrooms
# ---------------------------------------------------------------------------

@bp.route("/classrooms", methods=["POST"])
def create_classroom():
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    body = payload()
    # Tier 3: body FKs that are present and well-formed (school_id, then
    # credential_id per the global FK order).
    school_id = body.get("school_id")
    school = None
    if isinstance(school_id, str):
        school = db.schools.get(school_id)
        if school is None:
            raise ApiError(ERR_SCHOOL_NOT_FOUND[0], ERR_SCHOOL_NOT_FOUND[1],
                           "No school with id %r." % school_id)
    lead_raw = body.get("lead_credential_id")
    lead = None
    if lead_raw is not None and isinstance(lead_raw, str):
        lead = db.credentials.get(lead_raw)
        if lead is None:
            raise ApiError(ERR_CREDENTIAL_NOT_FOUND[0], ERR_CREDENTIAL_NOT_FOUND[1],
                           "No credential with id %r." % lead_raw)
    # Tier 4: field shape.
    if not isinstance(school_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'school_id' is required and must be a string.")
    name = req_str(body, "name")
    age_level = req_enum(body, "age_level", AGE_LEVELS)
    declared_age_span_years = req_int(body, "declared_age_span_years")
    enrolled_student_count = req_int(body, "enrolled_student_count", minimum=0)
    assistant_count = req_int(body, "assistant_count", minimum=0)
    if lead_raw is not None and not isinstance(lead_raw, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'lead_credential_id' must be a string when present.")
    # Tier 5: SchoolAdmin owns the school.
    if uid != school["id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "SchoolAdmin may only create classrooms for their own school.")
    # Tier 6: a supplied lead credential must be ACTIVE.
    if lead is not None and lead["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Lead credential is not ACTIVE.")
    # Tier 8: lead credential age level must equal the classroom's.
    if lead is not None and lead["age_level"] != age_level:
        raise ApiError(ERR_AGE_LEVEL_MISMATCH[0], ERR_AGE_LEVEL_MISMATCH[1],
                       "Lead credential age level does not match the classroom.")
    room = {
        "id": new_id(),
        "school_id": school["id"],
        "name": name,
        "age_level": age_level,
        "declared_age_span_years": declared_age_span_years,
        "enrolled_student_count": enrolled_student_count,
        "assistant_count": assistant_count,
        "lead_credential_id": lead["id"] if lead else None,
        "compliance_override": "NONE",
    }
    stamp_new(room)
    db.classrooms[room["id"]] = room
    return ok(serialize_classroom(room), 201)


@bp.route("/classrooms/<classroom_id>", methods=["GET"])
def get_classroom(classroom_id):
    _, role = authenticate()
    require_role(role, CLASSROOM_READ_ROLES)
    return ok(serialize_classroom(get_classroom_or_404(classroom_id)), 200)


@bp.route("/classrooms", methods=["GET"])
def list_classrooms():
    _, role = authenticate()
    require_role(role, CLASSROOM_READ_ROLES)
    args = request.args
    items = list(db.classrooms.values())
    for f in ("school_id", "lead_credential_id", "age_level"):
        v = args.get(f)
        if v is not None:
            items = [c for c in items if c.get(f) == v]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_classroom)


@bp.route("/classrooms/<classroom_id>/transfer-students", methods=["POST"])
def transfer_students(classroom_id):
    uid, role = authenticate()
    require_role(role, {"SchoolAdmin"})
    # Tier 3: path id, then the to_classroom_id body FK.
    frm = get_classroom_or_404(classroom_id)
    body = payload()
    to_id = body.get("to_classroom_id")
    to = None
    if isinstance(to_id, str):
        to = db.classrooms.get(to_id)
        if to is None:
            raise ApiError(ERR_CLASSROOM_NOT_FOUND[0], ERR_CLASSROOM_NOT_FOUND[1],
                           "No classroom with id %r." % to_id)
    # Tier 4: shape.
    if not isinstance(to_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'to_classroom_id' is required and must be a string.")
    student_count = req_int(body, "student_count", minimum=1)
    # Tier 5: SchoolAdmin owns the source classroom's school.
    if uid != frm["school_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "SchoolAdmin may only transfer within their own school.")
    # Tier 9: same school, same age level, count within source enrollment.
    if to["school_id"] != frm["school_id"]:
        raise ApiError(ERR_TRANSFER_CROSS_SCHOOL[0], ERR_TRANSFER_CROSS_SCHOOL[1],
                       "Transfers must stay within one school.")
    if to["age_level"] != frm["age_level"]:
        raise ApiError(ERR_AGE_LEVEL_MISMATCH[0], ERR_AGE_LEVEL_MISMATCH[1],
                       "Transfers require matching age levels.")
    if student_count > frm["enrolled_student_count"]:
        raise ApiError(ERR_TRANSFER_EXCEEDS_ENROLLMENT[0],
                       ERR_TRANSFER_EXCEEDS_ENROLLMENT[1],
                       "student_count exceeds the source classroom's enrollment.")
    frm["enrolled_student_count"] -= student_count
    touch(frm)
    to["enrolled_student_count"] += student_count
    touch(to)
    return ok({
        "from_classroom_id": frm["id"],
        "to_classroom_id": to["id"],
        "from_enrolled_student_count": frm["enrolled_student_count"],
        "to_enrolled_student_count": to["enrolled_student_count"],
        "school_total_enrollment": total_enrollment(frm["school_id"]),
    }, 200)


# ---------------------------------------------------------------------------
# Classroom audits
# ---------------------------------------------------------------------------

def _validate_materials_groups(body):
    groups = req_list(body, "materials_groups", non_empty=True)
    for g in groups:
        if not isinstance(g, dict):
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "Each materials group must be an object.")
        domain = g.get("domain")
        if not isinstance(domain, str) or domain == "":
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "Each materials group requires a 'domain'.")
        rc = g.get("required_count")
        pc = g.get("present_count")
        if not isinstance(rc, int) or isinstance(rc, bool) or rc < 1:
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "required_count must be a positive integer.")
        if not isinstance(pc, int) or isinstance(pc, bool) or pc < 0:
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "present_count must be a non-negative integer.")
        if pc > rc:
            raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                           "present_count may not exceed required_count.")
    return groups


@bp.route("/classroom-audits", methods=["POST"])
def create_audit():
    uid, role = authenticate()
    require_role(role, {"Consultant"})
    body = payload()
    # Tier 3: classroom_id, then visit_id when present and well-formed.
    classroom_id = body.get("classroom_id")
    room = None
    if isinstance(classroom_id, str):
        room = db.classrooms.get(classroom_id)
        if room is None:
            raise ApiError(ERR_CLASSROOM_NOT_FOUND[0], ERR_CLASSROOM_NOT_FOUND[1],
                           "No classroom with id %r." % classroom_id)
    visit_raw = body.get("visit_id")
    visit = None
    if visit_raw is not None and isinstance(visit_raw, str):
        visit = db.visits.get(visit_raw)
        if visit is None:
            raise ApiError(ERR_VISIT_NOT_FOUND[0], ERR_VISIT_NOT_FOUND[1],
                           "No verification visit with id %r." % visit_raw)
    # Tier 4: observation shape.
    if not isinstance(classroom_id, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'classroom_id' is required and must be a string.")
    if visit_raw is not None and not isinstance(visit_raw, str):
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "Field 'visit_id' must be a string when present.")
    students_present = req_int(body, "students_present", minimum=0)
    adults_present = req_int(body, "adults_present", minimum=1)
    observed_uninterrupted_minutes = req_int(body, "observed_uninterrupted_minutes", minimum=0)
    groups = _validate_materials_groups(body)
    # Tier 5: a visit-linked audit may only be filed by the visit's consultant.
    if visit is not None and uid != visit["consultant_id"]:
        raise ApiError(ERR_FORBIDDEN[0], ERR_FORBIDDEN[1],
                       "Only the visit's assigned consultant may file a linked audit.")
    # Tier 6: a supplied visit must still be SCHEDULED.
    if visit is not None and visit["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "The linked visit is not SCHEDULED.")
    # Tier 8: the visit must belong to the classroom's school.
    if visit is not None and visit["school_id"] != room["school_id"]:
        raise ApiError(ERR_AGE_LEVEL_MISMATCH[0], ERR_AGE_LEVEL_MISMATCH[1],
                       "The linked visit belongs to a different school.")
    # Tier 9: an ACTIVE catalog is required when the school has none pinned.
    school = db.schools[room["school_id"]]
    catalog = None
    if school.get("pinned_catalog_id"):
        catalog = db.catalogs.get(school["pinned_catalog_id"])
    if catalog is None:
        catalog = active_catalog()
    if catalog is None:
        raise ApiError(ERR_NO_ACTIVE_CATALOG[0], ERR_NO_ACTIVE_CATALOG[1],
                       "No ACTIVE standards catalog exists.")
    level = room["age_level"]

    # Ratio check: students/adults rounded half-up to 2dp; equality passes.
    ratio = round2(Decimal(students_present) / Decimal(adults_present))
    cap = Decimal(str(catalog["max_students_per_adult_by_level"].get(level, 0)))
    ratio_pass = ratio <= cap

    # Work-period check: sitting exactly on the minimum passes.
    work_min = catalog["min_uninterrupted_work_minutes_by_level"].get(level, 0)
    work_period_pass = observed_uninterrupted_minutes >= work_min

    # Materials check: round each group's ratio FIRST (2dp half-up), then take
    # the exact arithmetic mean; comparison uses the unrounded mean.
    per_group = [
        round2(Decimal(g["present_count"]) / Decimal(g["required_count"]))
        for g in groups
    ]
    mean = sum(per_group) / Decimal(len(per_group))
    threshold = Decimal(str(catalog["materials_pass_threshold"]))
    materials_pass = mean >= threshold
    materials_score = float(round4(mean))

    # Multi-age check: inclusive minimum.
    span_min = catalog["min_multi_age_span_years_by_level"].get(level, 0)
    multi_age_pass = room["declared_age_span_years"] >= span_min

    failed = []
    if not ratio_pass:
        failed.append("RATIO")
    if not work_period_pass:
        failed.append("WORK_PERIOD")
    if not materials_pass:
        failed.append("MATERIALS")
    if not multi_age_pass:
        failed.append("MULTI_AGE")
    verdict = "COMPLIANT" if not failed else "NONCOMPLIANT"

    audit = {
        "id": new_id(),
        "classroom_id": room["id"],
        "visit_id": visit["id"] if visit else None,
        "catalog_id": catalog["id"],
        "auditor_consultant_id": uid,
        "observed_at": now_iso(),
        "students_present": students_present,
        "adults_present": adults_present,
        "observed_uninterrupted_minutes": observed_uninterrupted_minutes,
        "materials_score": materials_score,
        "materials_groups": [
            {"domain": g["domain"], "required_count": g["required_count"],
             "present_count": g["present_count"]}
            for g in groups
        ],
        "ratio_students_per_adult": float(ratio),
        "ratio_pass": ratio_pass,
        "work_period_pass": work_period_pass,
        "materials_pass": materials_pass,
        "multi_age_pass": multi_age_pass,
        "verdict": verdict,
        "failed_checks": failed,
    }
    stamp_new_lean(audit)
    db.audits[audit["id"]] = audit
    return ok(serialize_audit(audit), 201)


AUDIT_READ_ROLES = {"SocietyAdmin", "AccreditationReviewer", "SchoolAdmin", "Consultant"}


@bp.route("/classroom-audits/<audit_id>", methods=["GET"])
def get_audit(audit_id):
    _, role = authenticate()
    require_role(role, AUDIT_READ_ROLES)
    a = db.audits.get(audit_id)
    if a is None:
        raise ApiError(ERR_AUDIT_NOT_FOUND[0], ERR_AUDIT_NOT_FOUND[1],
                       "No classroom audit with id %r." % audit_id)
    return ok(serialize_audit(a), 200)


@bp.route("/classroom-audits", methods=["GET"])
def list_audits():
    _, role = authenticate()
    require_role(role, AUDIT_READ_ROLES)
    args = request.args
    items = list(db.audits.values())
    for f in ("classroom_id", "catalog_id", "visit_id", "verdict"):
        v = args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    items.sort(key=lambda a: (a["created_at"], a["_seq"]))
    limit, offset = pagination_params()
    return list_response(items, limit, offset, serialize_audit)
