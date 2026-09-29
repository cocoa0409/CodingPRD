"""Abuse-prevention training: course catalogue and assignment lifecycle."""

from flask import Blueprint, g, request

import auth
import clock
import derive
import envelope
import ops
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("training", __name__)

TIERS = ("TIER_1", "TIER_2", "TIER_3")
ASSIGNMENT_STATUSES = ("ASSIGNED", "IN_PROGRESS", "COMPLETED", "EXPIRED")

COURSE_SPEC = {
    "code": validate.string(min_len=3, max_len=20, pattern=validate.COURSE_CODE),
    "title": validate.string(min_len=1, max_len=200),
    "validity_days": validate.integer(minimum=1, maximum=3650),
    "delivery_mode": validate.enum(("ONLINE", "IN_PERSON")),
    "required_for_tiers": validate.array(validate.enum(TIERS), min_items=1, max_items=3,
                                         unique=True),
    "pass_score": validate.integer(required=False, minimum=0, maximum=100, default=80),
}


@bp.post("/training-courses")
@auth.endpoint("NgbAdmin")
def publish_course():
    data = validate.body(auth.payload(), COURSE_SPEC)
    if store.course_by_code(data["code"]) is not None:
        fail("ERR_DUPLICATE_COURSE_CODE", "course code %s is already published" % data["code"])
    row = store.new_row(
        code=data["code"],
        title=data["title"],
        validity_days=data["validity_days"],
        delivery_mode=data["delivery_mode"],
        required_for_tiers=data["required_for_tiers"],
        pass_score=data["pass_score"],
    )
    store.TRAINING_COURSES[row["id"]] = row
    derive.recompute_all()
    return envelope.created(serialize.training_course(row))


ASSIGNMENT_SPEC = {
    "member_id": validate.string(min_len=1),
    "course_code": validate.string(min_len=1),
    "due_at": validate.instant(),
}


@bp.post("/training-assignments")
@auth.endpoint("NgbAdmin", "ClubAdministrator")
def create_assignment():
    data = validate.body(auth.payload(), ASSIGNMENT_SPEC)
    member = auth.member(data["member_id"])
    course = store.course_by_code(data["course_code"])
    if course is None:
        fail("ERR_TRAINING_COURSE_NOT_FOUND",
             "course %s is not published" % data["course_code"])
    auth.scope_member(member)
    if member["screening_status"] == "DISQUALIFIED":
        fail("ERR_MEMBER_DISQUALIFIED", "a disqualified member may not be assigned training")
    row = store.new_row(
        member_id=member["id"],
        course_code=course["code"],
        status="ASSIGNED",
        assigned_at=clock.now(),
        due_at=data["due_at"],
        started_at=None,
        completed_at=None,
        score=None,
        expires_at=None,
    )
    store.TRAINING_ASSIGNMENTS[row["id"]] = row
    derive.recompute_all()
    return envelope.created(serialize.training_assignment(row))


@bp.get("/training-assignments")
@auth.endpoint("NgbAdmin", "ComplianceAuditor", "SafeSportOfficer")
def list_assignments():
    args = request.args
    validate.query_enum(args, "status", ASSIGNMENT_STATUSES)
    rows = [a for a in store.TRAINING_ASSIGNMENTS.values()
            if pagelib.match(a, args, "member_id")
            and pagelib.match(a, args, "course_code")
            and pagelib.match(a, args, "status")]
    return pagelib.page(store.ordered(rows), serialize.training_assignment, args)


@bp.get("/training-assignments/<training_assignment_id>")
@auth.endpoint("NgbAdmin", "ClubAdministrator", "ComplianceAuditor", "SafeSportOfficer")
def read_assignment(training_assignment_id):
    row = auth.training_assignment(training_assignment_id)
    auth.scope_member(store.MEMBERS[row["member_id"]])
    return envelope.ok(serialize.training_assignment(row))


@bp.post("/training-assignments/<training_assignment_id>/start")
@auth.endpoint("Member", "ClubAdministrator")
def start_assignment(training_assignment_id):
    row = auth.training_assignment(training_assignment_id)
    member = store.MEMBERS[row["member_id"]]
    auth.scope_member(member)
    auth.owner(row["member_id"])
    validate.body(auth.payload(), {})
    if row["status"] != "ASSIGNED":
        fail("ERR_TRAINING_ASSIGNMENT_INVALID_STATE",
             "only an ASSIGNED assignment may be started")
    row["status"] = "IN_PROGRESS"
    row["started_at"] = clock.now()
    store.bump(row)
    derive.recompute_all()
    return envelope.ok(serialize.training_assignment(row))


@bp.post("/training-assignments/<training_assignment_id>/complete")
@auth.endpoint("Member", "ClubAdministrator")
def complete_assignment(training_assignment_id):
    row = auth.training_assignment(training_assignment_id)
    member = store.MEMBERS[row["member_id"]]
    auth.scope_member(member)
    auth.owner(row["member_id"])
    data = validate.body(auth.payload(), {"score": validate.integer(minimum=0, maximum=100)})
    course = store.course_by_code(row["course_code"])
    if row["status"] != "IN_PROGRESS":
        fail("ERR_TRAINING_ASSIGNMENT_INVALID_STATE",
             "only an IN_PROGRESS assignment may be completed")
    if course is None or data["score"] < course["pass_score"]:
        fail("ERR_TRAINING_ASSIGNMENT_INVALID_STATE",
             "the submitted score does not reach the course pass score")

    row["status"] = "COMPLETED"
    row["completed_at"] = clock.now()
    row["score"] = data["score"]
    row["expires_at"] = clock.plus_days(row["completed_at"], course["validity_days"])
    store.bump(row)

    derive.recompute_member(member)
    ops.stamp_horizons(member)
    ops.bubble_membership(member)
    ops.stamp_horizons(member)
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.training_assignment(row))
