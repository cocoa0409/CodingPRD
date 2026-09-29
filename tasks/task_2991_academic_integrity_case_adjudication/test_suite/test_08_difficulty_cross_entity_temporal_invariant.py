"""Difficulty suite: cross-entity state dependencies, temporal overlap and
compensating invariants (PRD §3.1, §3.3, §3.5, §3.7, §3.8, §2.11).

Every test in this module translates exactly one instance of the difficulty
design index and carries that instance's `Design:` tag as the last line of its
docstring.

The harness restarts the API server before every individual test, so each test
rebuilds its own world from an empty store with the logical clock at
`2026-08-01T00:00:00Z` (PRD §2.4).

The `seed_*` composites of `test_helpers.fixtures` are deliberately not used
here: `factories.student_payload` defaults `class_year` to 2027, while PRD §3.2
allows "a `class_year` from 1 to 8", and the composites give no way to override
it.  The primitive fixtures are reused instead, with an explicit legal
`class_year` on every student.
"""
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import make_reporter_headers, make_student_headers

_TRAINED_AT = constants.TEST_DEFAULTS["TRAINING_COMPLETED_AT"]
_INCIDENT_AT = constants.TEST_DEFAULTS["INCIDENT_AT"]


# ---------------------------------------------------------------------------
# Local composition helpers (no fixture in test_helpers fits, see module note)
# ---------------------------------------------------------------------------


def _world(api, officer, reporter_completed_at=_TRAINED_AT, **dept_overrides):
    """Clock at T0, the ENGL department, one trained reporter and the offering."""
    clock = fixtures.set_clock(fixtures.CLOCK_T0, officer, api)
    dept = fixtures.create_department(officer, api, **dept_overrides)
    reporter = fixtures.create_faculty(
        dept["id"],
        trained=True,
        completed_at=reporter_completed_at,
        headers=officer,
        client=api,
    )
    offering = fixtures.create_offering(dept["id"], reporter["id"], officer, api)
    return {
        "clock": clock,
        "officer": officer,
        "dept": dept,
        "reporter": reporter,
        "reporter_h": make_reporter_headers(reporter["id"]),
        "offering": offering,
        "evidence": [],
        "votes": [],
        "panelists": [],
    }


def _student(api, officer, class_year=3):
    return fixtures.create_student(officer, api, class_year=class_year)


def _room(api, officer):
    """ROOM-A: buffer 30 minutes on both sides, two sessions per UTC day."""
    return fixtures.create_room(
        officer,
        api,
        code="ROOM-A",
        seat_capacity=12,
        buffer_minutes=30,
        sessions_per_day_cap=2,
    )


def _draft_report(api, world, student, incident_at=_INCIDENT_AT, sha256=constants.SHA256_A):
    """A DRAFT PLAGIARISM report carrying the SEED-A similarity exhibit."""
    report = fixtures.create_report(
        world["offering"]["id"],
        student["id"],
        world["reporter_h"],
        api,
        incident_at=incident_at,
    )
    fixtures.attach_similarity_evidence(report["id"], world["reporter_h"], api, sha256=sha256)
    return validate_success(api.get_report(report["id"], world["officer"]))


def _case_for(api, world, student, incident_at=_INCIDENT_AT, sha256=constants.SHA256_A):
    """A fresh INTAKE_REVIEW case for `student` on the shared ENGL-201 offering."""
    report = _draft_report(api, world, student, incident_at=incident_at, sha256=sha256)
    fixtures.submit_report(report["id"], world["reporter_h"], api)
    fixtures.triage_report(report["id"], "ACCEPT", headers=world["officer"], client=api)
    case = fixtures.open_case(report["id"], world["officer"], api)
    child = dict(world)
    child["student"] = student
    child["student_h"] = make_student_headers(student["id"])
    child["report"] = report
    child["case"] = case
    child["evidence"] = []
    child["votes"] = []
    return child


def _notify(api, child, response_window_days=5):
    """Send the ALLEGATION_NOTICE, moving the case to NOTIFIED."""
    return fixtures.send_allegation_notice(child, response_window_days, api)


def _formal_notified(api, child, response_window_days=5, acknowledge=False):
    """NOTIFIED + pathway FORMAL, optionally with the notice acknowledged."""
    _notify(api, child, response_window_days)
    fixtures.set_pathway(child, "FORMAL", api)
    if acknowledge:
        fixtures.acknowledge_notice(child, api)
    return child


def _room_row(api, officer, room_id):
    return validate_success(api.get_hearing_room(room_id, officer))


def _dept_row(api, officer, department_id):
    return validate_success(api.get_department(department_id, officer))


def _student_row(api, officer, student_id):
    return validate_success(api.get_student(student_id, officer))


# ---------------------------------------------------------------------------
# cross_entity_state_dependency
# ---------------------------------------------------------------------------


def test_submit_is_refused_once_the_clock_crosses_the_730_day_training_boundary(api, officer):
    """One clock tick past 730 days turns the reporter lapsed and stops submit.

    The reporter's newest completion sits at `2024-08-01T00:00:00Z`, exactly 730
    days before `2026-08-01T00:00:00Z`.

    PRD §3.1: "a completion exactly 730 days old still counts as current, while
    one 731 days old does not."  PRD §3.3 requires on submit that "the reporter's
    `training_status` must be `CURRENT`, otherwise `ERR_REPORTER_TRAINING_LAPSED`".
    PRD §2.4: "Moving the clock has no direct write effect on stored rows, but it
    changes the answers that derived fields give".

    Design: Difficulty/cross_entity_state_dependency/report_submit_depends_on_the_faculty_members_derived_training_status
    """
    world = _world(api, officer, reporter_completed_at="2024-08-01T00:00:00Z")
    student_one = _student(api, officer)
    student_two = _student(api, officer, class_year=2)

    current = validate_success(api.get_faculty_member(world["reporter"]["id"], officer))
    assertions.assert_faculty_member(current, {"training_status": "CURRENT"})
    assertions.assert_instant_equals(
        current["training_completed_at"], "2024-08-01T00:00:00Z", "training_completed_at"
    )
    version_before = current["version"]

    report_one = _draft_report(api, world, student_one)
    submitted = validate_success(
        api.submit_report(report_one["id"], world["reporter_h"])
    )
    assertions.assert_integrity_report(submitted, {"status": "SUBMITTED"})
    assertions.assert_instant_equals(
        submitted["submitted_at"], fixtures.CLOCK_T0, "submitted_at"
    )
    assertions.assert_pct_equals(
        submitted["evidence_strength_score"], 60.00, "evidence_strength_score"
    )

    after_submit = validate_success(api.get_faculty_member(world["reporter"]["id"], officer))
    assertions.assert_faculty_member(
        after_submit, {"training_status": "CURRENT", "reports_submitted_count": 1}
    )
    assertions.assert_pct_equals(
        _dept_row(api, officer, world["dept"]["id"])["training_completion_pct"],
        20.00,
        "training_completion_pct",
    )

    # A second DRAFT report, already carrying its similarity exhibit: PRD §3.3
    # says "Attaching an item recomputes the report's `evidence_strength_score`
    # and `evidence_complete` immediately", so it reads 60.00 while still DRAFT.
    report_two = _draft_report(
        api, world, student_two, incident_at="2026-07-21T00:00:00Z", sha256=constants.SHA256_C
    )
    assertions.assert_integrity_report(report_two, {"status": "DRAFT"})
    assertions.assert_pct_equals(
        report_two["evidence_strength_score"], 60.00, "evidence_strength_score"
    )

    fixtures.set_clock("2026-08-02T00:00:00Z", officer, api)

    lapsed = validate_success(api.get_faculty_member(world["reporter"]["id"], officer))
    assertions.assert_faculty_member(
        lapsed, {"training_status": "LAPSED", "reports_submitted_count": 1}
    )
    assert lapsed["version"] == version_before
    assertions.assert_instant_equals(
        lapsed["training_completed_at"], "2024-08-01T00:00:00Z", "training_completed_at"
    )
    assertions.assert_pct_equals(
        _dept_row(api, officer, world["dept"]["id"])["training_completion_pct"],
        0.00,
        "training_completion_pct",
    )

    validate_error(
        api.submit_report(report_two["id"], world["reporter_h"]),
        ApiErrorId.ERR_REPORTER_TRAINING_LAPSED.value,
        409,
    )

    still_draft = validate_success(api.get_report(report_two["id"], officer))
    assertions.assert_integrity_report(still_draft, {"status": "DRAFT"})
    assert still_draft["submitted_at"] is None
    assertions.assert_pct_equals(
        still_draft["evidence_strength_score"], 60.00, "evidence_strength_score"
    )
    assertions.assert_integrity_report(
        validate_success(api.get_report(report_one["id"], officer)), {"status": "SUBMITTED"}
    )
    assertions.assert_faculty_member(
        validate_success(api.get_faculty_member(world["reporter"]["id"], officer)),
        {"reports_submitted_count": 1},
    )


def test_a_fresh_training_completion_reopens_the_submit_the_lapse_had_closed(api, officer):
    """Recording a newer completion re-derives CURRENT and submit succeeds.

    PRD §3.1: "`training_status` is `CURRENT` when the most recent completion
    satisfies `completed_at` plus 730 days at or after the current logical clock"
    and the member's "`training_completed_at` and `training_module_code` are then
    re-derived from the newest completion on record".  PRD §3.3 on success:
    "`status` becomes `SUBMITTED`, `submitted_at` is set to the current logical
    clock ... and the reporter's `reports_submitted_count` increases by one."

    Design: Difficulty/cross_entity_state_dependency/report_submit_depends_on_the_faculty_members_derived_training_status
    """
    world = _world(api, officer, reporter_completed_at="2024-08-01T00:00:00Z")
    student = _student(api, officer)
    report = _draft_report(api, world, student)

    fixtures.set_clock("2026-08-02T00:00:00Z", officer, api)
    assertions.assert_faculty_member(
        validate_success(api.get_faculty_member(world["reporter"]["id"], officer)),
        {"training_status": "LAPSED"},
    )
    validate_error(
        api.submit_report(report["id"], world["reporter_h"]),
        ApiErrorId.ERR_REPORTER_TRAINING_LAPSED.value,
        409,
    )

    # No explicit status: a TrainingCompletion is not one of the resource types
    # PRD §2.6 enumerates, so §4's "new distinct resource in a collection -> 201"
    # and "derived-field recomputation -> 200" rules both plausibly apply to
    # this endpoint.  The claim under test is the re-derivation, not the code.
    get_success_data(
        api.create_training_completion(
            world["reporter"]["id"],
            factories.training_completion_payload(completed_at="2026-08-02T00:00:00Z"),
            officer,
        )
    )

    now_current = validate_success(api.get_faculty_member(world["reporter"]["id"], officer))
    assertions.assert_faculty_member(
        now_current, {"training_status": "CURRENT", "reports_submitted_count": 0}
    )
    assertions.assert_instant_equals(
        now_current["training_completed_at"], "2026-08-02T00:00:00Z", "training_completed_at"
    )

    submitted = validate_success(api.submit_report(report["id"], world["reporter_h"]))
    assertions.assert_integrity_report(submitted, {"status": "SUBMITTED"})
    assertions.assert_instant_equals(
        submitted["submitted_at"], "2026-08-02T00:00:00Z", "submitted_at"
    )
    assertions.assert_pct_equals(
        submitted["evidence_strength_score"], 60.00, "evidence_strength_score"
    )
    assertions.assert_faculty_member(
        validate_success(api.get_faculty_member(world["reporter"]["id"], officer)),
        {"training_status": "CURRENT", "reports_submitted_count": 1},
    )
    assertions.assert_pct_equals(
        _dept_row(api, officer, world["dept"]["id"])["training_completion_pct"],
        20.00,
        "training_completion_pct",
    )


def test_convene_is_refused_while_an_advisor_engagement_is_still_requested(api, officer):
    """The advisor gate lives on another entity and clears only on review.

    PRD §3.7 Convening: "No advisor engagement of the case may still be
    `REQUESTED`, otherwise `ERR_ADVISOR_REQUEST_PENDING`."  PRD §3.5: approval
    "sets `status` to `APPROVED`, clears `reconfirmation_required`, and grants
    `speaking_rights` only when `advisor_kind` is `ATTORNEY`".

    Design: Difficulty/cross_entity_state_dependency/convene_is_blocked_while_any_advisor_engagement_sits_in_requested
    """
    world = _world(api, officer)
    world["room"] = _room(api, officer)
    case = _case_for(api, world, _student(api, officer))
    _formal_notified(api, case, acknowledge=True)
    fixtures.request_advisor(case, "FACULTY_ADVISOR", api)
    fixtures.seed_panel(case, panel_size=3, client=api)
    fixtures.schedule_hearing(case, client=api)
    session = case["session"]
    assertions.assert_hearing_session(
        session,
        {"status": "SCHEDULED", "round_number": 1, "required_panel_size": 3, "quorum_required": 2},
    )

    fixtures.set_clock(fixtures.CLOCK_AT_SESSION, officer, api)
    validate_error(
        api.convene_hearing_session(session["id"], case["chair_h"]),
        ApiErrorId.ERR_ADVISOR_REQUEST_PENDING.value,
        409,
    )
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session["id"], officer)), {"status": "SCHEDULED"}
    )
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "HEARING_SCHEDULED"},
    )

    fixtures.review_advisor(case, "APPROVE", client=api)
    reviewed = validate_success(api.get_advisor_engagement(case["engagement"]["id"], officer))
    assertions.assert_advisor_engagement(
        reviewed,
        {"status": "APPROVED", "reconfirmation_required": False, "speaking_rights": False},
    )

    convened = validate_success(api.convene_hearing_session(session["id"], case["chair_h"]))
    assertions.assert_hearing_session(convened, {"status": "CONVENED"})
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "HEARING_IN_PROGRESS"},
    )

    votes, votes_meta = assertions.validate_list(
        api.list_panel_votes(officer, params={"session_id": session["id"]})
    )
    assert votes == []
    assert votes_meta["total_count"] == 0


def test_adjournment_returns_the_approved_advisor_to_requested_and_re_blocks_convening(api, officer):
    """The rehearing notice re-arms the same cross-entity gate for round two.

    PRD §3.5: "When a rehearing notice pushes an approved engagement back to
    `REQUESTED`, `reconfirmation_required` becomes true and `speaking_rights`
    returns to false, and the case cannot be convened again until the engagement
    is reviewed afresh".  PRD §3.7 on adjournment: "The room's
    `booked_minutes_total` is **not** released, because the room was genuinely
    occupied."  Round two sits at `2026-09-05T10:00:00Z`, clearing the ten-day
    floor that runs "afresh from the rehearing notice" of `2026-08-20T10:00:00Z`.

    Design: Difficulty/cross_entity_state_dependency/convene_is_blocked_while_any_advisor_engagement_sits_in_requested
    """
    world = _world(api, officer)
    world["room"] = _room(api, officer)
    room_id = world["room"]["id"]
    case = _case_for(api, world, _student(api, officer))
    _formal_notified(api, case, acknowledge=True)
    fixtures.request_advisor(case, "FACULTY_ADVISOR", api)
    fixtures.review_advisor(case, "APPROVE", client=api)
    fixtures.seed_panel(case, panel_size=3, client=api)
    fixtures.schedule_hearing(case, client=api)
    session_one_id = case["session"]["id"]
    fixtures.convene_hearing(case, fixtures.CLOCK_AT_SESSION, api)
    fixtures.adjourn_hearing(case, api)

    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_one_id, officer)), {"status": "ADJOURNED"}
    )
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "FORMAL_REFERRED", "hearing_round": 1},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )

    notices, notices_meta = assertions.validate_list(
        api.list_notifications(
            officer, params={"case_id": case["case"]["id"], "kind": "REHEARING_NOTICE"}
        )
    )
    assert notices_meta["total_count"] == 1
    assertions.assert_notification(notices[0], {"kind": "REHEARING_NOTICE"})
    assertions.assert_instant_equals(
        notices[0]["sent_at"], "2026-08-20T10:00:00Z", "rehearing notice sent_at"
    )

    re_armed = validate_success(api.get_advisor_engagement(case["engagement"]["id"], officer))
    assertions.assert_advisor_engagement(
        re_armed,
        {"status": "REQUESTED", "reconfirmation_required": True, "speaking_rights": False},
    )

    fixtures.schedule_hearing(
        case, start_at="2026-09-05T10:00:00Z", end_at="2026-09-05T11:30:00Z", client=api
    )
    session_two = case["session"]
    assertions.assert_hearing_session(session_two, {"status": "SCHEDULED", "round_number": 2})
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "HEARING_SCHEDULED", "hearing_round": 2},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 300}
    )

    fixtures.set_clock("2026-09-05T10:00:00Z", officer, api)
    validate_error(
        api.convene_hearing_session(session_two["id"], case["chair_h"]),
        ApiErrorId.ERR_ADVISOR_REQUEST_PENDING.value,
        409,
    )
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_two["id"], officer)),
        {"status": "SCHEDULED"},
    )
    for session_id in (session_one_id, session_two["id"]):
        _, votes_meta = assertions.validate_list(
            api.list_panel_votes(officer, params={"session_id": session_id})
        )
        assert votes_meta["total_count"] == 0


# ---------------------------------------------------------------------------
# resource_temporal_overlap
# ---------------------------------------------------------------------------


def test_back_to_back_instructor_meetings_are_legal_while_a_one_minute_overlap_conflicts(api, officer):
    """The instructor calendar is half-open, so shared endpoints are free.

    PRD §3.5: "`ERR_INSTRUCTOR_CALENDAR_CONFLICT` is raised when the requested
    half-open interval intersects the half-open interval of any other meeting for
    the same instructor whose `status` is `SCHEDULED`, `HELD` or `NO_SHOW`;
    because the intervals are half-open, two back-to-back meetings that share an
    endpoint do not conflict."  PRD §2.9: a rejected request leaves the store
    byte-identical to its pre-request state.

    Design: Difficulty/resource_temporal_overlap/instructor_calendar_half_open_intervals_allow_back_to_back_meetings
    """
    world = _world(api, officer)
    case = _case_for(api, world, _student(api, officer))
    _notify(api, case)
    instructor_id = world["reporter"]["id"]

    fixtures.schedule_meeting(
        case, "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z", client=api
    )
    meeting_one = case["meeting"]
    assertions.assert_case_meeting(
        meeting_one,
        {"status": "SCHEDULED", "duration_minutes": 60, "instructor_id": instructor_id},
    )

    fixtures.schedule_meeting(
        case, "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z", client=api
    )
    meeting_two = case["meeting"]
    assertions.assert_case_meeting(
        meeting_two, {"status": "SCHEDULED", "duration_minutes": 60}
    )
    assertions.assert_instant_equals(
        meeting_two["start_at"], meeting_one["end_at"], "back-to-back boundary"
    )
    assert meeting_two["id"] != meeting_one["id"]

    validate_error(
        api.create_case_meeting(
            factories.case_meeting_payload(
                case["case"]["id"],
                instructor_id,
                "2026-08-10T09:59:00Z",
                "2026-08-10T10:59:00Z",
            ),
            officer,
        ),
        ApiErrorId.ERR_INSTRUCTOR_CALENDAR_CONFLICT.value,
        409,
    )

    rows, meta = assertions.validate_list(
        api.list_case_meetings(officer, params={"instructor_id": instructor_id})
    )
    assert meta["total_count"] == 2
    assert {row["id"]: row["status"] for row in rows} == {
        meeting_one["id"]: "SCHEDULED",
        meeting_two["id"]: "SCHEDULED",
    }
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "NOTIFIED"},
    )


def test_cancelling_the_colliding_meetings_frees_the_identical_instructor_interval(api, officer):
    """Cancellation releases the calendar; the refused interval becomes legal.

    PRD §3.5: "On `CANCELLED`, `advisor_present` is set to false and the
    instructor's interval is released, so a later meeting may occupy exactly the
    same half-open interval."  The conflict check only looks at meetings whose
    "`status` is `SCHEDULED`, `HELD` or `NO_SHOW`".

    Design: Difficulty/resource_temporal_overlap/instructor_calendar_half_open_intervals_allow_back_to_back_meetings
    """
    world = _world(api, officer)
    case = _case_for(api, world, _student(api, officer))
    _notify(api, case)
    instructor_id = world["reporter"]["id"]

    fixtures.schedule_meeting(
        case, "2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z", client=api
    )
    meeting_one = case["meeting"]
    fixtures.schedule_meeting(
        case, "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z", client=api
    )
    meeting_two = case["meeting"]

    overlapping = factories.case_meeting_payload(
        case["case"]["id"], instructor_id, "2026-08-10T09:59:00Z", "2026-08-10T10:59:00Z"
    )
    validate_error(
        api.create_case_meeting(overlapping, officer),
        ApiErrorId.ERR_INSTRUCTOR_CALENDAR_CONFLICT.value,
        409,
    )

    for meeting_id in (meeting_one["id"], meeting_two["id"]):
        cancelled = validate_success(
            api.record_meeting_outcome(
                meeting_id, factories.meeting_outcome_payload("CANCELLED"), officer
            )
        )
        assertions.assert_case_meeting(
            cancelled, {"status": "CANCELLED", "advisor_present": False}
        )

    meeting_three = validate_success(api.create_case_meeting(overlapping, officer), 201)
    assertions.assert_case_meeting(
        meeting_three,
        {"status": "SCHEDULED", "duration_minutes": 60, "instructor_id": instructor_id},
    )
    assertions.assert_instant_equals(
        meeting_three["start_at"], "2026-08-10T09:59:00Z", "re-booked start_at"
    )

    rows, meta = assertions.validate_list(
        api.list_case_meetings(officer, params={"instructor_id": instructor_id})
    )
    assert meta["total_count"] == 3
    assert {row["id"]: row["status"] for row in rows} == {
        meeting_one["id"]: "CANCELLED",
        meeting_two["id"]: "CANCELLED",
        meeting_three["id"]: "SCHEDULED",
    }


def test_touching_buffered_room_intervals_conflict_while_one_minute_of_separation_does_not(api, officer):
    """The room interval is closed, so a touching buffered endpoint conflicts.

    Session one holds `2026-08-20T10:00:00Z`-`11:30:00Z`, buffered by 30 minutes
    on both sides to the closed interval `09:30`-`12:00`.  A request for
    `12:30`-`13:30` buffers to `12:00`-`14:00`, which touches at `12:00`.

    PRD §3.7: "the requested interval ... must not intersect the same buffered
    interval of any session in that room whose `status` is `SCHEDULED` or
    `CONVENED`, and because the interval is closed, two sessions whose buffered
    intervals merely touch at an endpoint **do** conflict."  On success "the
    room's `booked_minutes_total` increases by the session's whole minutes plus
    twice the room's `buffer_minutes`" — 90 + 60 then 60 + 60, so 270.

    Design: Difficulty/resource_temporal_overlap/hearing_room_closed_buffered_intervals_reject_touching_endpoints_and_enforce_the_daily_cap
    """
    world = _world(api, officer)
    world["room"] = _room(api, officer)
    room_id = world["room"]["id"]
    fixtures.seed_panel(world, panel_size=3, client=api)
    panelist_ids = [panelist["id"] for panelist in world["panelists"]]

    case_one = _case_for(api, world, _student(api, officer))
    _formal_notified(api, case_one)
    case_two = _case_for(
        api,
        world,
        _student(api, officer, class_year=2),
        incident_at="2026-07-21T00:00:00Z",
        sha256=constants.SHA256_C,
    )
    _formal_notified(api, case_two)

    fixtures.schedule_hearing(case_one, client=api)
    session_one = case_one["session"]
    assertions.assert_hearing_session(session_one, {"status": "SCHEDULED", "round_number": 1})
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )

    validate_error(
        api.create_hearing_session(
            factories.hearing_session_payload(
                case_two["case"]["id"],
                room_id,
                world["chair"]["id"],
                panelist_ids,
                "2026-08-20T12:30:00Z",
                "2026-08-20T13:30:00Z",
            ),
            officer,
        ),
        ApiErrorId.ERR_ROOM_BUFFER_CONFLICT.value,
        409,
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )
    assertions.assert_case(
        fixtures.read_case(case_two["case"]["id"], officer, api),
        {"adjudication_status": "NOTIFIED", "hearing_round": 0},
    )

    session_two = validate_success(
        api.create_hearing_session(
            factories.hearing_session_payload(
                case_two["case"]["id"],
                room_id,
                world["chair"]["id"],
                panelist_ids,
                "2026-08-20T12:31:00Z",
                "2026-08-20T13:31:00Z",
            ),
            officer,
        ),
        201,
    )
    assertions.assert_hearing_session(
        session_two,
        {"status": "SCHEDULED", "round_number": 1, "required_panel_size": 3, "quorum_required": 2},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 270}
    )
    assertions.assert_case(
        fixtures.read_case(case_two["case"]["id"], officer, api),
        {"adjudication_status": "HEARING_SCHEDULED", "hearing_round": 1},
    )

    rows, meta = assertions.validate_list(
        api.list_hearing_sessions(officer, params={"room_id": room_id})
    )
    assert meta["total_count"] == 2
    assert sorted(row["id"] for row in rows) == sorted([session_one["id"], session_two["id"]])


def test_the_daily_cap_refuses_a_third_session_whose_buffered_interval_is_disjoint(api, officer):
    """Two sessions on one UTC date exhaust the cap even with the room free.

    The third request sits at `15:00`-`16:00`, buffering to the closed interval
    `14:30`-`16:30`, which touches neither `09:30`-`12:00` nor `12:01`-`14:01`.

    PRD §3.7: "the room may not already hold `sessions_per_day_cap` sessions with
    `status` `SCHEDULED` or `CONVENED` whose `start_at` falls on the same UTC
    calendar date as the requested `start_at`, otherwise
    `ERR_ROOM_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/hearing_room_closed_buffered_intervals_reject_touching_endpoints_and_enforce_the_daily_cap
    """
    world = _world(api, officer)
    world["room"] = _room(api, officer)
    room_id = world["room"]["id"]
    assertions.assert_hearing_room(world["room"], {"sessions_per_day_cap": 2, "buffer_minutes": 30})
    fixtures.seed_panel(world, panel_size=3, client=api)
    panelist_ids = [panelist["id"] for panelist in world["panelists"]]

    case_one = _case_for(api, world, _student(api, officer))
    _formal_notified(api, case_one)
    case_two = _case_for(
        api,
        world,
        _student(api, officer, class_year=2),
        incident_at="2026-07-21T00:00:00Z",
        sha256=constants.SHA256_C,
    )
    _formal_notified(api, case_two)
    case_three = _case_for(
        api,
        world,
        _student(api, officer, class_year=4),
        incident_at="2026-07-22T00:00:00Z",
        sha256=constants.SHA256_D,
    )
    _formal_notified(api, case_three)

    fixtures.schedule_hearing(case_one, client=api)
    fixtures.schedule_hearing(
        case_two, start_at="2026-08-20T12:31:00Z", end_at="2026-08-20T13:31:00Z", client=api
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 270}
    )

    validate_error(
        api.create_hearing_session(
            factories.hearing_session_payload(
                case_three["case"]["id"],
                room_id,
                world["chair"]["id"],
                panelist_ids,
                "2026-08-20T15:00:00Z",
                "2026-08-20T16:00:00Z",
            ),
            officer,
        ),
        ApiErrorId.ERR_ROOM_DAILY_CAPACITY_EXCEEDED.value,
        409,
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 270}
    )
    assertions.assert_case(
        fixtures.read_case(case_three["case"]["id"], officer, api),
        {"adjudication_status": "NOTIFIED", "hearing_round": 0},
    )
    _, meta = assertions.validate_list(
        api.list_hearing_sessions(officer, params={"room_id": room_id})
    )
    assert meta["total_count"] == 2


# ---------------------------------------------------------------------------
# compensating_invariant
# ---------------------------------------------------------------------------


def test_cancelling_a_scheduled_session_releases_exactly_its_reserved_minutes(api, officer):
    """The room ledger returns to its pre-booking value, to the exact minute.

    PRD §3.7 Cancelling: cancellation "releases exactly the minutes that
    scheduling reserved from the room's `booked_minutes_total`, and returns the
    case to `FORMAL_REFERRED` with `version` advanced.  `hearing_round` is **not**
    decremented".  PRD §2.11: `booked_minutes_total` "must equal its defining sum
    after every request, including every rejected one".

    Design: Difficulty/compensating_invariant/room_minutes_ledger_is_released_exactly_on_cancel_but_never_on_adjourn
    """
    world = _world(api, officer)
    world["room"] = _room(api, officer)
    room_id = world["room"]["id"]
    case = _case_for(api, world, _student(api, officer))
    _formal_notified(api, case, acknowledge=True)
    fixtures.seed_panel(case, panel_size=3, client=api)

    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 0}
    )

    fixtures.schedule_hearing(case, client=api)
    session_one = case["session"]
    assertions.assert_hearing_session(session_one, {"status": "SCHEDULED", "round_number": 1})
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )

    fixtures.cancel_hearing(case, api)
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_one["id"], officer)),
        {"status": "CANCELLED"},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 0}
    )
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "FORMAL_REFERRED", "hearing_round": 1},
    )

    fixtures.schedule_hearing(case, client=api)
    session_two = case["session"]
    assert session_two["id"] != session_one["id"]
    assertions.assert_hearing_session(session_two, {"status": "SCHEDULED", "round_number": 2})
    assertions.assert_instant_equals(
        session_two["start_at"], session_one["start_at"], "re-booked start_at"
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "HEARING_SCHEDULED", "hearing_round": 2},
    )


def test_adjourning_never_releases_the_room_while_a_later_cancel_releases_only_its_own(api, officer):
    """Adjournment leaves the charge standing; the round-two cancel drops to 150.

    PRD §2.11: "Adjourning releases nothing, because the room was genuinely
    occupied."  PRD §3.7 on adjournment: "The room's `booked_minutes_total` is
    **not** released".  Round two sits at `2026-09-05T10:00:00Z`, clearing the
    ten-day floor that runs "afresh from the rehearing notice".

    Design: Difficulty/compensating_invariant/room_minutes_ledger_is_released_exactly_on_cancel_but_never_on_adjourn
    """
    world = _world(api, officer)
    world["room"] = _room(api, officer)
    room_id = world["room"]["id"]
    case = _case_for(api, world, _student(api, officer))
    _formal_notified(api, case, acknowledge=True)
    fixtures.seed_panel(case, panel_size=3, client=api)

    fixtures.schedule_hearing(case, client=api)
    session_one_id = case["session"]["id"]
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )

    fixtures.convene_hearing(case, fixtures.CLOCK_AT_SESSION, api)
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_one_id, officer)),
        {"status": "CONVENED"},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )

    fixtures.adjourn_hearing(case, api)
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_one_id, officer)),
        {"status": "ADJOURNED"},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "FORMAL_REFERRED", "hearing_round": 1},
    )

    fixtures.schedule_hearing(
        case, start_at="2026-09-05T10:00:00Z", end_at="2026-09-05T11:30:00Z", client=api
    )
    session_two = case["session"]
    assertions.assert_hearing_session(session_two, {"status": "SCHEDULED", "round_number": 2})
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 300}
    )

    fixtures.cancel_hearing(case, api)
    assertions.assert_hearing_session(
        validate_success(api.get_hearing_session(session_two["id"], officer)),
        {"status": "CANCELLED"},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )
    assertions.assert_case(
        fixtures.read_case(case["case"]["id"], officer, api),
        {"adjudication_status": "FORMAL_REFERRED", "hearing_round": 2},
    )

    rows, meta = assertions.validate_list(
        api.list_hearing_sessions(officer, params={"room_id": room_id})
    )
    assert meta["total_count"] == 2
    assert {row["id"]: row["status"] for row in rows} == {
        session_one_id: "ADJOURNED",
        session_two["id"]: "CANCELLED",
    }


def _two_case_world_with_a_rank_four_proposal(api, officer):
    """Case A decided RESPONSIBLE with a rank-4 proposal; case B in INTAKE_REVIEW.

    Panel recommendations 4 and 6 give the lower middle, 4 (PRD §3.7), which acts
    as a floor over the tier rank 3, so the case's `recommended_ladder_rank` is 4
    and the office band runs 3 through 5 (PRD §3.8).
    """
    world = _world(api, officer)
    world["room"] = _room(api, officer)
    world["hist"] = validate_success(
        api.create_department(factories.hist_department_payload(), officer), 201
    )
    fixtures.seed_panel(world, panel_size=3, client=api)
    student_a = _student(api, officer)
    student_b = _student(api, officer, class_year=2)
    case_a = _case_for(api, world, student_a)
    case_b = _case_for(
        api,
        world,
        student_b,
        incident_at="2026-07-21T00:00:00Z",
        sha256=constants.SHA256_C,
    )
    _formal_notified(api, case_a, acknowledge=True)
    fixtures.schedule_hearing(case_a, client=api)
    fixtures.convene_hearing(case_a, fixtures.CLOCK_AT_SESSION, api)
    fixtures.cast_vote(case_a, 0, "RESPONSIBLE", 4, api)
    fixtures.cast_vote(case_a, 1, "RESPONSIBLE", 6, api)
    fixtures.cast_vote(case_a, 2, "NOT_RESPONSIBLE", None, api)
    fixtures.decide_hearing(case_a, api)
    decided = fixtures.read_case(case_a["case"]["id"], officer, api)
    assertions.assert_case(
        decided,
        {
            "adjudication_status": "DECIDED",
            "responsibility_finding": "RESPONSIBLE",
            "finding_basis": "PANEL",
            "panel_severity_recommendation": 4,
            "recommended_ladder_rank": 4,
        },
    )
    fixtures.propose_sanction(
        case_a, ladder_rank=4, effective_from="2026-08-21T00:00:00Z", client=api
    )
    assertions.assert_sanction(
        case_a["sanction"],
        {"status": "PROPOSED", "kind": "TRANSCRIPT_NOTATION_ONLY", "ladder_rank": 4},
    )
    return world, case_a, case_b, student_a, student_b


def test_imposing_then_completing_returns_both_ledgers_to_their_pre_operation_values(api, officer):
    """Completion exactly reverses hop three and closes the department count.

    PRD §3.8 Completion: "the student's `active_sanction_points` decreases by the
    sanction's `ladder_rank`, exactly reversing hop three, and `standing` is
    re-derived; ... the department's `open_case_count` decreases by one;
    `adjudication_status` becomes `CLOSED`".  PRD §3.2: "a rank-4 sanction leaves
    the student in good standing".  PRD §2.11 requires each of the three ledgers
    to "equal its defining sum after every request".

    Design: Difficulty/compensating_invariant/student_points_and_department_open_case_count_return_to_their_pre_operation_values
    """
    world, case_a, case_b, student_a, student_b = _two_case_world_with_a_rank_four_proposal(
        api, officer
    )
    engl_id = world["dept"]["id"]
    hist_id = world["hist"]["id"]
    room_id = world["room"]["id"]
    sanction_id = case_a["sanction"]["id"]

    # Pre-operation ledger readings.
    assert _dept_row(api, officer, engl_id)["open_case_count"] == 2
    assert _dept_row(api, officer, hist_id)["open_case_count"] == 0
    assertions.assert_student(
        _student_row(api, officer, student_a["id"]),
        {"active_sanction_points": 0, "prior_upheld_count": 0, "standing": "GOOD_STANDING"},
    )

    fixtures.impose_sanction(case_a, client=api)
    imposed = validate_success(api.get_sanction(sanction_id, officer))
    assertions.assert_sanction(imposed, {"status": "IMPOSED", "ladder_rank": 4})
    assertions.assert_instant_equals(
        imposed["imposed_at"], fixtures.CLOCK_AT_SESSION, "imposed_at"
    )
    assertions.assert_case(
        fixtures.read_case(case_a["case"]["id"], officer, api),
        {"adjudication_status": "SANCTION_IMPOSED", "notation_status": "PENDING_POSTING"},
    )
    assertions.assert_student(
        _student_row(api, officer, student_a["id"]),
        {"active_sanction_points": 4, "prior_upheld_count": 1, "standing": "GOOD_STANDING"},
    )
    assertions.assert_student(
        _student_row(api, officer, student_b["id"]),
        {"active_sanction_points": 0, "prior_upheld_count": 0, "standing": "GOOD_STANDING"},
    )
    assert _dept_row(api, officer, engl_id)["open_case_count"] == 2
    assert _dept_row(api, officer, hist_id)["open_case_count"] == 0

    fixtures.complete_sanction(case_a, client=api)
    completed = validate_success(api.get_sanction(sanction_id, officer))
    assertions.assert_sanction(completed, {"status": "COMPLETED", "ladder_rank": 4})
    assertions.assert_instant_equals(
        completed["completed_at"], fixtures.CLOCK_AT_SESSION, "completed_at"
    )

    closed = fixtures.read_case(case_a["case"]["id"], officer, api)
    assertions.assert_case(
        closed,
        {"adjudication_status": "CLOSED", "notation_status": "PENDING_POSTING"},
    )
    assert closed["expungement_eligible_at"] is None
    assertions.assert_student(
        _student_row(api, officer, student_a["id"]),
        {"active_sanction_points": 0, "prior_upheld_count": 1, "standing": "GOOD_STANDING"},
    )
    assertions.assert_student(
        _student_row(api, officer, student_b["id"]),
        {"active_sanction_points": 0, "prior_upheld_count": 0},
    )
    assert _dept_row(api, officer, engl_id)["open_case_count"] == 1
    assert _dept_row(api, officer, hist_id)["open_case_count"] == 0
    assertions.assert_case(
        fixtures.read_case(case_b["case"]["id"], officer, api),
        {"adjudication_status": "INTAKE_REVIEW"},
    )
    assertions.assert_hearing_room(
        _room_row(api, officer, room_id), {"booked_minutes_total": 150}
    )


def test_a_replayed_completion_reports_a_state_error_and_releases_nothing_twice(api, officer):
    """The second completion is refused and no counter or ledger moves again.

    PRD §2.9: "a rejected request leaves the store byte-identical to its
    pre-request state, including every derived counter and ledger."  PRD §3.4:
    dismissal "decreases the department's `open_case_count` by one, sets
    `adjudication_status` to `DISMISSED`".

    Which state error comes back is deliberately not pinned to one id.  PRD §3.8
    names exactly two gates for this endpoint — "The office completes a sanction
    that is in `IMPOSED`; any other status is `ERR_SANCTION_STATE_INVALID`. No
    appeal of the case may be in `SUBMITTED` or `UNDER_REVIEW`, otherwise
    `ERR_CASE_STATE_INVALID`" — so an implementation that reads the rank-13 case
    gate as exactly that appeal condition answers `ERR_SANCTION_STATE_INVALID`,
    while one that also treats the now-`CLOSED` terminal case as inadmissible
    answers `ERR_CASE_STATE_INVALID` at the earlier rank.  Both are faithful; the
    compensating-invariant claim under test is the untouched store.

    Design: Difficulty/compensating_invariant/student_points_and_department_open_case_count_return_to_their_pre_operation_values
    """
    world, case_a, case_b, student_a, student_b = _two_case_world_with_a_rank_four_proposal(
        api, officer
    )
    engl_id = world["dept"]["id"]
    hist_id = world["hist"]["id"]
    sanction_id = case_a["sanction"]["id"]

    fixtures.impose_sanction(case_a, client=api)
    fixtures.complete_sanction(case_a, client=api)
    assert _dept_row(api, officer, engl_id)["open_case_count"] == 1
    assertions.assert_student(
        _student_row(api, officer, student_a["id"]), {"active_sanction_points": 0}
    )

    replay = api.complete_sanction(sanction_id, officer)
    assert replay.status_code == 409, replay.text
    validate_error_is_one_of(
        replay,
        [
            ApiErrorId.ERR_CASE_STATE_INVALID.value,
            ApiErrorId.ERR_SANCTION_STATE_INVALID.value,
        ],
    )

    assertions.assert_sanction(
        validate_success(api.get_sanction(sanction_id, officer)), {"status": "COMPLETED"}
    )
    assertions.assert_case(
        fixtures.read_case(case_a["case"]["id"], officer, api),
        {"adjudication_status": "CLOSED"},
    )
    assertions.assert_student(
        _student_row(api, officer, student_a["id"]),
        {"active_sanction_points": 0, "prior_upheld_count": 1, "standing": "GOOD_STANDING"},
    )
    assert _dept_row(api, officer, engl_id)["open_case_count"] == 1
    assert _dept_row(api, officer, hist_id)["open_case_count"] == 0

    dismissed = validate_success(
        api.dismiss_case(case_b["case"]["id"], factories.dismiss_payload(), officer)
    )
    assertions.assert_case(dismissed, {"adjudication_status": "DISMISSED"})
    assert _dept_row(api, officer, engl_id)["open_case_count"] == 0
    assert _dept_row(api, officer, hist_id)["open_case_count"] == 0
    assertions.assert_student(
        _student_row(api, officer, student_b["id"]),
        {"active_sanction_points": 0, "prior_upheld_count": 0},
    )
