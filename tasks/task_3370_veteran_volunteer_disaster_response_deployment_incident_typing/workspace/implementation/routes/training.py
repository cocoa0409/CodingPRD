"""Training pipeline: courses, enrollments, seat accounting, waitlist, and the
completion side effect that mints a PENDING_VERIFICATION certification.
"""
from datetime import timedelta
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
import timeutil
from constants import (
    CERT_KINDS, ENROLLMENT_STATUSES, MAX_COURSE_CAPACITY, CERT_GRANT_VALIDITY_DAYS,
)

bp = Blueprint("training", __name__)

COURSE_READ_ROLES = ("SystemAdmin", "TrainingDirector", "SafetyOfficer",
                     "OperationsLead", "Volunteer")
ENROLLMENT_READ_ROLES = ("SystemAdmin", "TrainingDirector", "SafetyOfficer", "Volunteer")


@bp.post("/vdr/training-courses")
def create_course():
    body = V.get_body()
    V.check_unknown(body, {"title", "grants_cert_kind", "capacity", "starts_at",
                           "lead_instructor_volunteer_id"})
    title = V.req_str(body, "title")
    grants = V.req_enum(body, "grants_cert_kind", CERT_KINDS)
    capacity = V.req_int(body, "capacity", lo=1, hi=MAX_COURSE_CAPACITY)
    starts_at = V.req_dt(body, "starts_at")
    lead_id = V.req_str(body, "lead_instructor_volunteer_id")
    auth.require_roles("TrainingDirector")
    lead = db.get("volunteers", lead_id)
    if lead is None:
        errors.volunteer_not_found()
    if not lead["instructor_certified"]:
        errors.err("ERR_INSTRUCTOR_NOT_CERTIFIED", 422,
                   "lead instructor must be an instructor_certified volunteer")
    course = db.mint("courses", {
        "title": title,
        "grants_cert_kind": grants,
        "capacity": capacity,
        "starts_at": timeutil.fmt(starts_at),
        "lead_instructor_volunteer_id": lead_id,
        "seats_taken": 0,
    })
    return envelope.ok(domain.public(course), 201)


@bp.get("/vdr/training-courses/<cid>")
def get_course(cid):
    auth.require_roles(*COURSE_READ_ROLES)
    course = db.get("courses", cid)
    if course is None:
        errors.training_course_not_found()
    return envelope.ok(domain.public(course))


@bp.post("/vdr/training-courses/<cid>/enrollments")
def create_enrollment(cid):
    body = V.get_body()
    V.check_unknown(body, {"volunteer_id"})
    volunteer_id = V.req_str(body, "volunteer_id")
    auth.require_roles("TrainingDirector")
    course = db.get("courses", cid)
    if course is None:
        errors.training_course_not_found()
    vol = db.get("volunteers", volunteer_id)
    if vol is None:
        errors.volunteer_not_found()
    duplicate = [e for e in db.store["enrollments"].values()
                 if e["course_id"] == cid and e["volunteer_id"] == volunteer_id
                 and e["status"] in ("ENROLLED", "WAITLISTED")]
    if duplicate:
        errors.err("ERR_DUPLICATE_ENROLLMENT", 409,
                   "volunteer already holds a live enrollment in this course")
    if course["seats_taken"] < course["capacity"]:
        status = "ENROLLED"
        position = None
        course["seats_taken"] += 1
        db.touch(course)
    else:
        status = "WAITLISTED"
        position = 1 + len([e for e in db.store["enrollments"].values()
                            if e["course_id"] == cid and e["status"] == "WAITLISTED"])
    enrollment = db.mint("enrollments", {
        "course_id": cid,
        "volunteer_id": volunteer_id,
        "status": status,
        "waitlist_position": position,
    })
    return envelope.ok(domain.public(enrollment), 201)


@bp.get("/vdr/training-enrollments")
def list_enrollments():
    auth.require_roles(*ENROLLMENT_READ_ROLES)
    items = db.all_of("enrollments")
    for param in ("course_id", "volunteer_id", "status"):
        value = V.qparam(param)
        if value is not None:
            items = [e for e in items if e.get(param) == value]
    return envelope.paginate(domain.public_list(items))


@bp.get("/vdr/training-enrollments/<eid>")
def get_enrollment(eid):
    uid, role = auth.require_roles(*ENROLLMENT_READ_ROLES)
    enrollment = db.get("enrollments", eid)
    if enrollment is None:
        errors.enrollment_not_found()
    if role == "Volunteer" and enrollment["volunteer_id"] != uid:
        errors.unauthorized("a Volunteer may only read their own enrollments")
    return envelope.ok(domain.public(enrollment))


@bp.patch("/vdr/training-enrollments/<eid>")
def patch_enrollment(eid):
    body = V.get_body()
    V.check_unknown(body, {"status"})
    target = V.req_enum(body, "status", ENROLLMENT_STATUSES)
    uid, role = auth.require_roles("TrainingDirector", "Volunteer")
    if target in ("COMPLETED", "FAILED") and role != "TrainingDirector":
        errors.unauthorized("marking outcomes is restricted to TrainingDirector")
    if target in ("ENROLLED", "WAITLISTED"):
        errors.invalid_state("status %s is assigned by the system" % target)
    enrollment = db.get("enrollments", eid)
    if enrollment is None:
        errors.enrollment_not_found()
    if target == "DROPPED" and role == "Volunteer" and uid != enrollment["volunteer_id"]:
        errors.unauthorized("a Volunteer may only drop their own enrollment")
    cur = enrollment["status"]
    course = db.get("courses", enrollment["course_id"])

    if target in ("COMPLETED", "FAILED"):
        if cur != "ENROLLED":
            errors.invalid_state("cannot transition enrollment from %s to %s" % (cur, target))
        if db.now() < timeutil.parse_iso(course["starts_at"]):
            errors.invalid_state("the course has not begun")
        enrollment["status"] = target
        db.touch(enrollment)
        if target == "COMPLETED":
            now = db.now()
            db.mint("certifications", {
                "volunteer_id": enrollment["volunteer_id"],
                "kind": course["grants_cert_kind"],
                "status": "PENDING_VERIFICATION",
                "issued_at": timeutil.fmt(now),
                "expires_at": timeutil.fmt(now + timedelta(days=CERT_GRANT_VALIDITY_DAYS)),
                "verified_by_user_id": None,
                "renewal_count": 0,
            })
    elif target == "DROPPED":
        if cur not in ("ENROLLED", "WAITLISTED"):
            errors.invalid_state("cannot transition enrollment from %s to DROPPED" % cur)
        enrollment["status"] = "DROPPED"
        enrollment["waitlist_position"] = None
        db.touch(enrollment)
        if cur == "ENROLLED":
            course["seats_taken"] = max(0, course["seats_taken"] - 1)
            db.touch(course)
        else:
            remaining = [e for e in db.all_of("enrollments")
                         if e["course_id"] == course["id"] and e["status"] == "WAITLISTED"]
            for position, e in enumerate(remaining, start=1):
                if e["waitlist_position"] != position:
                    e["waitlist_position"] = position
                    db.touch(e)
    return envelope.ok(domain.public(enrollment))
