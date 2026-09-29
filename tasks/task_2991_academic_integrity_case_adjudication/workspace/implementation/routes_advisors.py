"""Advisor engagements and instructor meetings (PRD 3.5)."""

from flask import Blueprint, request

import calc
from db import S, new_row, touch
from errors import fail
from lookup import (case_or_404, engagement_or_404, faculty_or_404, filter_rows,
                    meeting_or_404)
from middleware import (ROLE_FACULTY_REPORTER, ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR,
                        ROLE_STUDENT, auth, require_owner)
from response import created, ok, ok_list, pagination
from serializers import engagement_json, meeting_json
from shapes import Field, peek, validate
from util import whole_minutes

bp = Blueprint("advisors", __name__)

ADVISOR_KINDS = ("FACULTY_ADVISOR", "STUDENT_PEER", "ATTORNEY")

ENGAGEMENT_FIELDS = [
    Field("case_id", "string"),
    Field("advisor_full_name", "string", min_len=1, max_len=120),
    Field("advisor_kind", "enum", values=ADVISOR_KINDS),
    Field("advisor_bar_licensed", "boolean", required=False, default=False),
]

REVIEW_FIELDS = [
    Field("decision", "enum", values=("APPROVE", "DENY")),
    Field("decision_reason", "string", required=False, min_len=1, max_len=500),
]

MEETING_FIELDS = [
    Field("case_id", "string"),
    Field("instructor_id", "string"),
    Field("start_at", "datetime"),
    Field("end_at", "datetime"),
    Field("advisor_present", "boolean", required=False, default=False),
]

OUTCOME_FIELDS = [Field("outcome", "enum", values=("HELD", "NO_SHOW", "CANCELLED"))]

MEETING_CASE_STATES = ("NOTIFIED", "INFORMAL_PROPOSED", "FORMAL_REFERRED")


def fk_filter(param, resolver):
    raw = request.args.get(param)
    if raw is not None and raw != "":
        resolver(raw)


# ------------------------------------------------------- advisor engagements

@bp.route("/integrity/advisor-engagements", methods=["POST"])
def request_advisor():
    actor = auth([ROLE_STUDENT])
    hinted = peek("case_id")
    known = S.cases.get(hinted) if isinstance(hinted, str) else None
    if known is not None:
        require_owner(actor, known["student_id"])
    body = validate(ENGAGEMENT_FIELDS)
    case = case_or_404(body["case_id"])
    attorney = body["advisor_kind"] == "ATTORNEY"
    # The attorney-eligibility check outranks the advisor-count check (PRD 2.9).
    if attorney and case["recommended_ladder_rank"] < calc.ATTORNEY_ADVISOR_MIN_RANK:
        fail("ERR_ATTORNEY_ADVISOR_NOT_PERMITTED",
             "An attorney advisor requires a recommended ladder rank of 6 or above.")
    if attorney and not body["advisor_bar_licensed"]:
        fail("ERR_ATTORNEY_NOT_LICENSED", "An attorney advisor must be bar licensed.")
    if calc.advisor_live_count(case["id"]) >= calc.ADVISOR_LIMIT_PER_CASE:
        fail("ERR_ADVISOR_LIMIT_REACHED",
             "The case already holds two requested or approved advisor engagements.")
    row = new_row(
        case_id=case["id"],
        advisor_full_name=body["advisor_full_name"],
        advisor_kind=body["advisor_kind"],
        advisor_bar_licensed=body["advisor_bar_licensed"],
        status="REQUESTED",
        reconfirmation_required=False,
        decision_reason=None,
    )
    S.engagements[row["id"]] = row
    return created(engagement_json(row))


@bp.route("/integrity/advisor-engagements", methods=["GET"])
def list_engagements():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_STUDENT, ROLE_PANEL_CHAIR])
    limit, offset = pagination()
    fk_filter("case_id", case_or_404)
    rows = filter_rows(S.engagements, {
        "case_id": "case_id",
        "status": "status",
        "advisor_kind": "advisor_kind",
    })
    return ok_list(rows, engagement_json, limit, offset)


@bp.route("/integrity/advisor-engagements/<row_id>", methods=["GET"])
def read_engagement(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_STUDENT, ROLE_PANEL_CHAIR])
    return ok(engagement_json(engagement_or_404(row_id)))


@bp.route("/integrity/cases/<row_id>/advisor-engagements", methods=["GET"])
def list_case_engagements(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_PANEL_CHAIR, ROLE_STUDENT])
    # PRD 2.6: the parent identifier is resolved before anything nested.
    case = case_or_404(row_id)
    limit, offset = pagination()
    rows = calc.engagements_of_case(case["id"])
    return ok_list(rows, engagement_json, limit, offset)


@bp.route("/integrity/advisor-engagements/<row_id>/review", methods=["POST"])
def review_engagement(row_id):
    auth([ROLE_INTEGRITY_OFFICER])
    body = validate(REVIEW_FIELDS)
    if body["decision"] == "DENY" and body["decision_reason"] is None:
        fail("ERR_INVALID_REQUEST", "decision_reason is required on a denial.")
    engagement = engagement_or_404(row_id)
    if engagement["status"] != "REQUESTED":
        fail("ERR_ADVISOR_ENGAGEMENT_STATE_INVALID",
             "Only a REQUESTED advisor engagement may be reviewed.")
    if body["decision"] == "APPROVE":
        engagement["status"] = "APPROVED"
        engagement["reconfirmation_required"] = False
    else:
        engagement["status"] = "DENIED"
        engagement["decision_reason"] = body["decision_reason"]
    touch(engagement)
    return ok(engagement_json(engagement))


# ---------------------------------------------------------- case meetings

@bp.route("/integrity/case-meetings", methods=["POST"])
def schedule_meeting():
    auth([ROLE_FACULTY_REPORTER, ROLE_INTEGRITY_OFFICER])
    body = validate(MEETING_FIELDS)
    case = case_or_404(body["case_id"])
    faculty_or_404(body["instructor_id"])
    if case["adjudication_status"] not in MEETING_CASE_STATES:
        fail("ERR_CASE_STATE_INVALID",
             "A meeting may only be booked while the case is in NOTIFIED, "
             "INFORMAL_PROPOSED or FORMAL_REFERRED.")
    start_at = body["start_at"]
    end_at = body["end_at"]
    # PRD 3.5: the meeting's own instructor_id is the reporter of the case's
    # originating report, and it is that member's calendar that is occupied.
    report = calc.report_of_case(case)
    instructor_id = report["reporter_id"] if report else body["instructor_id"]
    # PRD 3.5: the window check outranks the conflict check.
    problem = calc.interval_problem(start_at, end_at)
    if problem is not None:
        fail("ERR_MEETING_WINDOW_INVALID", problem)
    if calc.instructor_calendar_conflict(instructor_id, start_at, end_at):
        fail("ERR_INSTRUCTOR_CALENDAR_CONFLICT",
             "The instructor's calendar already holds a meeting over this interval.")
    row = new_row(
        case_id=case["id"],
        instructor_id=instructor_id,
        start_at=start_at,
        end_at=end_at,
        duration_minutes=whole_minutes(start_at, end_at),
        status="SCHEDULED",
        advisor_present=body["advisor_present"],
    )
    S.meetings[row["id"]] = row
    return created(meeting_json(row))


@bp.route("/integrity/case-meetings", methods=["GET"])
def list_meetings():
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_STUDENT])
    limit, offset = pagination()
    fk_filter("case_id", case_or_404)
    fk_filter("instructor_id", faculty_or_404)
    rows = filter_rows(S.meetings, {
        "case_id": "case_id",
        "instructor_id": "instructor_id",
        "status": "status",
    })
    return ok_list(rows, meeting_json, limit, offset)


@bp.route("/integrity/case-meetings/<row_id>", methods=["GET"])
def read_meeting(row_id):
    auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER, ROLE_STUDENT])
    return ok(meeting_json(meeting_or_404(row_id)))


@bp.route("/integrity/case-meetings/<row_id>/outcome", methods=["POST"])
def record_outcome(row_id):
    actor = auth([ROLE_INTEGRITY_OFFICER, ROLE_FACULTY_REPORTER])
    known = S.meetings.get(row_id)
    hinted = peek("outcome")
    if known is not None:
        # HELD and NO_SHOW belong to the meeting's own instructor; CANCELLED is
        # an office action (PRD 3.5).
        if hinted in ("HELD", "NO_SHOW"):
            require_owner(actor, known["instructor_id"])
        elif hinted == "CANCELLED" and actor.role != ROLE_INTEGRITY_OFFICER:
            fail("ERR_NOT_RESOURCE_OWNER",
                 "Cancelling a meeting is reserved to the integrity office.")
    body = validate(OUTCOME_FIELDS)
    meeting = meeting_or_404(row_id)
    if meeting["status"] != "SCHEDULED":
        fail("ERR_MEETING_STATE_INVALID", "The meeting outcome has already been recorded.")
    outcome = body["outcome"]
    if outcome == "HELD" and S.clock < meeting["start_at"]:
        fail("ERR_MEETING_WINDOW_INVALID", "HELD may not be recorded before start_at.")
    if outcome == "NO_SHOW" and S.clock < meeting["end_at"]:
        fail("ERR_MEETING_WINDOW_INVALID", "NO_SHOW may not be recorded before end_at.")
    if outcome == "HELD":
        meeting["advisor_present"] = calc.case_has_approved_advisor(meeting["case_id"])
    else:
        meeting["advisor_present"] = False
    meeting["status"] = outcome
    touch(meeting)
    return ok(meeting_json(meeting))
