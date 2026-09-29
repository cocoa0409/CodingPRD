"""Investigating bodies, incident intake, routing, closure and the imposition
of interim measures (PRD section 3.8)."""

from datetime import timedelta

from flask import Blueprint, g, request

import auth
import calc
import clock
import derive
import envelope
import ops
import pagelib
import serialize
import store
import validate
from errors import fail

bp = Blueprint("cases", __name__)

CATEGORIES = ("SEXUAL_MISCONDUCT", "PHYSICAL_ABUSE", "EMOTIONAL_MISCONDUCT",
              "POLICY_VIOLATION", "FAILURE_TO_REPORT")
REPORTER_KINDS = ("MANDATORY_REPORTER", "PARENT", "ATHLETE", "ANONYMOUS")
CASE_STATUSES = ("INTAKE_REVIEW", "ROUTED", "CLOSED_SUBSTANTIATED",
                 "CLOSED_UNSUBSTANTIATED", "CLOSED_ADMINISTRATIVE")
MEASURE_KINDS = ("NO_CONTACT_DIRECTIVE", "TEMPORARY_SUSPENSION", "SUPERVISED_CONTACT_ONLY")
CLOSURE_REASONS = ("NO_JURISDICTION", "DUPLICATE_REPORT", "INVESTIGATION_COMPLETE")
OUTCOMES = ("SUBSTANTIATED", "UNSUBSTANTIATED")

BODY_SPEC = {
    "name": validate.string(min_len=1, max_len=160),
    "scope_categories": validate.array(validate.enum(CATEGORIES), min_items=1, max_items=5,
                                       unique=True),
    "max_open_cases": validate.integer(minimum=1),
    "intake_status": validate.enum(("ACCEPTING", "PAUSED"), required=False, default="ACCEPTING"),
}


@bp.post("/investigating-bodies")
@auth.endpoint("NgbAdmin")
def register_body():
    data = validate.body(auth.payload(), BODY_SPEC)
    row = store.new_row(
        name=data["name"],
        scope_categories=data["scope_categories"],
        intake_status=data["intake_status"],
        max_open_cases=data["max_open_cases"],
        open_case_count=0,
    )
    store.INVESTIGATING_BODIES[row["id"]] = row
    return envelope.created(serialize.investigating_body(row))


@bp.get("/investigating-bodies/<investigating_body_id>")
@auth.endpoint("NgbAdmin", "SafeSportOfficer")
def read_body(investigating_body_id):
    row = auth.investigating_body(investigating_body_id)
    return envelope.ok(serialize.investigating_body(row))


CASE_SPEC = {
    "club_id": validate.string(min_len=1),
    "reported_member_id": validate.string(min_len=1),
    "allegation_category": validate.enum(CATEGORIES),
    "reporter_kind": validate.enum(REPORTER_KINDS),
    "narrative": validate.string(min_len=20, max_len=4000),
    "occurred_at": validate.instant(),
}


@bp.post("/cases")
@auth.endpoint("SafeSportOfficer", "ClubAdministrator", "Member")
def file_case():
    data = validate.body(auth.payload(), CASE_SPEC)
    club = auth.club(data["club_id"])
    member = auth.member(data["reported_member_id"])
    auth.scope(club["id"])
    received = clock.now()
    elapsed = received - data["occurred_at"]
    timeliness = "TIMELY" if elapsed <= timedelta(hours=calc.MANDATORY_REPORT_WINDOW_HOURS) \
        else "LATE"
    row = store.new_row(
        club_id=club["id"],
        reported_member_id=member["id"],
        investigating_body_id=None,
        allegation_category=data["allegation_category"],
        reporter_kind=data["reporter_kind"],
        reporter_user_id=g.user_id,
        narrative=data["narrative"],
        occurred_at=data["occurred_at"],
        intake_received_at=received,
        report_timeliness=timeliness,
        status="INTAKE_REVIEW",
        routed_at=None,
        closure_reason=None,
        outcome=None,
        closed_at=None,
    )
    store.CASES[row["id"]] = row
    return envelope.created(serialize.case(row))


@bp.get("/cases")
@auth.endpoint("NgbAdmin", "SafeSportOfficer", "ComplianceAuditor")
def list_cases():
    args = request.args
    validate.query_enum(args, "status", CASE_STATUSES)
    rows = [c for c in store.CASES.values()
            if pagelib.match(c, args, "club_id")
            and pagelib.match(c, args, "reported_member_id")
            and pagelib.match(c, args, "investigating_body_id")
            and pagelib.match(c, args, "status")]
    return pagelib.page(store.ordered(rows), serialize.case, args)


@bp.get("/cases/<case_id>")
@auth.endpoint("NgbAdmin", "SafeSportOfficer", "ComplianceAuditor")
def read_case(case_id):
    return envelope.ok(serialize.case(auth.case(case_id)))


@bp.post("/cases/<case_id>/route")
@auth.endpoint("SafeSportOfficer")
def route_case(case_id):
    case = auth.case(case_id)
    data = validate.body(auth.payload(),
                         {"investigating_body_id": validate.string(min_len=1)})
    body = auth.investigating_body(data["investigating_body_id"])
    if case["status"] != "INTAKE_REVIEW":
        fail("ERR_CASE_INVALID_STATE", "only an INTAKE_REVIEW case may be routed")
    if case["allegation_category"] not in body["scope_categories"]:
        fail("ERR_BODY_SCOPE_MISMATCH",
             "%s is outside the body's scope" % case["allegation_category"])
    if body["intake_status"] != "ACCEPTING":
        fail("ERR_BODY_INTAKE_PAUSED", "the investigating body has paused intake")
    if body["open_case_count"] >= body["max_open_cases"]:
        fail("ERR_BODY_CASELOAD_EXCEEDED", "the investigating body is at its caseload ceiling")

    case["status"] = "ROUTED"
    case["investigating_body_id"] = body["id"]
    case["routed_at"] = clock.now()
    store.bump(case)
    body["open_case_count"] += 1
    store.bump(body)
    derive.recompute_all()
    return envelope.ok(serialize.case(case))


CLOSE_SPEC = {
    "closure_reason": validate.enum(CLOSURE_REASONS),
    "outcome": validate.enum(OUTCOMES, required=False),
}


@bp.post("/cases/<case_id>/close")
@auth.endpoint("SafeSportOfficer")
def close_case(case_id):
    case = auth.case(case_id)
    data = validate.body(auth.payload(), CLOSE_SPEC)
    if case["status"] not in ("INTAKE_REVIEW", "ROUTED"):
        fail("ERR_CASE_INVALID_STATE", "the case is already closed")
    if case["status"] == "INTAKE_REVIEW" and data["outcome"] is not None:
        fail("ERR_CASE_INVALID_STATE",
             "an administrative closure carries no outcome")
    if case["status"] == "ROUTED" and data["outcome"] is None:
        fail("ERR_CASE_INVALID_STATE", "closing a routed case requires an outcome")
    if g.user_id == case["reporter_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "the reporter may not close their own case")

    member = store.MEMBERS[case["reported_member_id"]]
    case["closure_reason"] = data["closure_reason"]
    case["closed_at"] = clock.now()

    if case["status"] == "INTAKE_REVIEW":
        case["status"] = "CLOSED_ADMINISTRATIVE"
        store.bump(case)
        derive.recompute_all()
        return envelope.ok(serialize.case(case))

    body = store.INVESTIGATING_BODIES.get(case["investigating_body_id"])
    case["outcome"] = data["outcome"]
    if data["outcome"] == "SUBSTANTIATED":
        case["status"] = "CLOSED_SUBSTANTIATED"
        store.bump(case)
        if body is not None:
            body["open_case_count"] = max(0, body["open_case_count"] - 1)
            store.bump(body)
        ops.make_measures_permanent(member)
        ops.revoke_member(member, "PERMANENT_MEASURE")
    else:
        case["status"] = "CLOSED_UNSUBSTANTIATED"
        store.bump(case)
        if body is not None:
            body["open_case_count"] = max(0, body["open_case_count"] - 1)
            store.bump(body)
        ops.lift_measures(member, "CASE_UNSUBSTANTIATED")
        ops.restore_after_release(member)

    member["records_retained_through"] = derive.records_retained_through(member)
    store.bump(member)
    derive.recompute_all()
    return envelope.ok(serialize.case(case))


MEASURE_SPEC = {
    "member_id": validate.string(min_len=1),
    "measure_kind": validate.enum(MEASURE_KINDS),
    "effective_from": validate.instant(),
    "effective_to": validate.instant(required=False),
    "expected_member_version": validate.integer(minimum=0),
}


@bp.post("/cases/<case_id>/interim-measures")
@auth.endpoint("SafeSportOfficer")
def impose_measure(case_id):
    case = auth.case(case_id)
    data = validate.body(auth.payload(), MEASURE_SPEC)
    if data["effective_to"] is not None and data["effective_to"] < data["effective_from"]:
        validate.bad("effective_to must be at or after effective_from")
    member = auth.member(data["member_id"])
    if member["id"] != case["reported_member_id"]:
        fail("ERR_CLUB_SCOPE_VIOLATION",
             "the measure's member must be the member reported on the case")
    if data["expected_member_version"] != member["version"]:
        fail("ERR_STALE_MEMBER_VERSION", "expected_member_version does not match the member")
    if case["status"] not in ("INTAKE_REVIEW", "ROUTED"):
        fail("ERR_CASE_INVALID_STATE", "the case is closed")
    if derive.has_measure(member["id"], ("PERMANENT",)):
        fail("ERR_CONTACT_NOT_PERMITTED", "the member is already permanently restricted")
    if ops.measure_window_conflict(member["id"], data["measure_kind"],
                                   data["effective_from"], data["effective_to"]):
        fail("ERR_MEASURE_WINDOW_CONFLICT",
             "an active measure of the same kind still occupies this window")

    row = store.new_row(
        case_id=case["id"],
        member_id=member["id"],
        measure_kind=data["measure_kind"],
        permanence="TEMPORARY",
        effective_from=data["effective_from"],
        effective_to=data["effective_to"],
        status="ACTIVE",
        imposed_by_user_id=g.user_id,
        converted_by_user_id=None,
        lifted_at=None,
        lift_reason=None,
        rationale=None,
    )
    store.INTERIM_MEASURES[row["id"]] = row
    if data["measure_kind"] == "TEMPORARY_SUSPENSION" and member["membership_status"] == "ACTIVE":
        member["membership_status"] = "SUSPENDED"
    ops.suspend_placements(member)
    derive.recompute_member(member)
    store.bump(member)
    derive.recompute_all()
    return envelope.created(serialize.interim_measure(row))
