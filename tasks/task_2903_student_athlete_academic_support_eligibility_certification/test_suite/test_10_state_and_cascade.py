"""Cyclic state machines and multi-hop cascades."""

from test_helpers import assert_close, error, ok
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_APPEAL_ROUNDS_EXHAUSTED
from test_helpers.constants import (
    APPEAL_COMMITTEE_REVIEW,
    APPEAL_GRANTED,
    CERT_ACTION_REVOKE,
    ELIGIBILITY_INELIGIBLE,
    ELIGIBILITY_RESTORED_BY_WAIVER,
    RISK_TIER_1,
    RISK_TIER_2,
    RISK_TIER_3,
    SUPPORT_MANDATED,
    SUPPORT_NORMAL,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER_ALT,
    COMMITTEE,
    COMPLIANCE,
    INSTRUCTOR_SOC_1,
    OPERATIONS,
    SPECIALIST,
    instructor_headers,
)


def _revoked_certification_with_appeal_in_review(api):
    """A revoked but benchmark-passing certification with a live appeal."""
    ctx = fx.declared_passing_student(api, term_count=1)
    certification = fx.make_revoked_certification(api, ctx.student_id, ctx.term_id)
    appeal = fx.make_appeal_in_review(
        api, certification["id"], requested_credit_relief=0.0
    )
    ctx.certification = certification
    ctx.certification_id = certification["id"]
    ctx.appeal_id = appeal["id"]
    return ctx


def test_granted_appeal_restores_the_revoked_certification(api):
    """PRD 3.5: "If and only if the re-evaluated `benchmark_result` is now
    `PASS`, the certification transitions out of its failed state — `DENIED →
    RESTORED` or `REVOKED → RESTORED` — and because the certification became
    `RESTORED`, the student's `eligibility_state` is re-derived to
    `RESTORED_BY_WAIVER` and `degree_applicable_credits` is rewritten on the
    student row."

    Design: Difficulty/non_linear_state_machine/certification_revoke_restore_cycle
    """
    ctx = _revoked_certification_with_appeal_in_review(api)

    granted = ok(api.appeal_status(ctx.appeal_id, f.grant(0.0), COMMITTEE))

    assert granted["status"] == APPEAL_GRANTED
    assert_close(granted["granted_credit_relief"], 0.00)
    certification = fx.read_certification(api, ctx.certification_id)
    assert certification["status"] == "RESTORED"
    assert_close(certification["credit_relief_applied"], 0.00)
    assert certification["benchmark_result"] == "PASS"
    student = fx.read_student(api, ctx.student_id)
    assert student["eligibility_state"] == ELIGIBILITY_RESTORED_BY_WAIVER


def test_restored_certification_may_be_revoked_a_second_time(api):
    """PRD 3.4: "Because a revoked certification can be restored by a granted
    appeal and a restored certification can be revoked again, the cycle
    `CERTIFIED → REVOKED → RESTORED → REVOKED` may repeat any number of times
    for as long as the term stays open."

    Design: Difficulty/non_linear_state_machine/certification_revoke_restore_cycle
    """
    ctx = _revoked_certification_with_appeal_in_review(api)
    ok(api.appeal_status(ctx.appeal_id, f.grant(0.0), COMMITTEE))
    restored = fx.read_certification(api, ctx.certification_id)
    assert restored["status"] == "RESTORED"

    second_revoke = ok(
        api.certification_status(
            ctx.certification_id, f.action(CERT_ACTION_REVOKE), CERT_OFFICER_ALT
        )
    )

    # The row has now entered REVOKED twice: CERTIFIED, REVOKED, RESTORED,
    # REVOKED, which no linear pipeline could produce.
    assert second_revoke["status"] == "REVOKED"
    student = fx.read_student(api, ctx.student_id)
    assert student["eligibility_state"] == ELIGIBILITY_INELIGIBLE


def _appeal_at_round_three(api):
    """A denied certification whose appeal has looped twice, reaching round 3."""
    ctx = fx.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
        min_progress_gpa=2.0,
    )
    fx.record_grade(api, ctx.enrollment_id, "D")
    certification = fx.make_denied_certification(api, ctx.student_id, ctx.term_id)
    appeal = fx.make_appeal_in_review(
        api, certification["id"], requested_credit_relief=6.0
    )
    rounds = [appeal]
    for _ in range(2):
        fx.appeal_action(api, appeal["id"], "REQUEST_REVISION", COMMITTEE)
        rounds.append(fx.appeal_action(api, appeal["id"], "SUBMIT", ADVISOR))
        fx.appeal_action(api, appeal["id"], "OPEN_REVIEW", COMMITTEE)
    ctx.certification = certification
    ctx.certification_id = certification["id"]
    ctx.appeal_id = appeal["id"]
    ctx.rounds = rounds
    return ctx


def test_appeal_resubmission_increments_the_round_number(api):
    """PRD 3.5: "The advisor may then resubmit, taking the appeal
    `REVISION_REQUESTED → SUBMITTED`, which increments `round_number` by one and
    clears `decided_by_user_id` and `decided_at` so that the next round starts
    undecided; this edge closes the revision cycle, and a fourth submission is
    refused because `round_number` would pass the three-round ceiling."

    Design: Difficulty/non_linear_state_machine/appeal_revision_round_cycle
    """
    ctx = _appeal_at_round_three(api)

    # rounds[0] is the first review, then one resubmission per loop.
    assert ctx.rounds[0]["round_number"] == 1
    assert ctx.rounds[1]["round_number"] == 2
    assert ctx.rounds[2]["round_number"] == 3
    assert ctx.rounds[2]["status"] == "SUBMITTED"
    assert ctx.rounds[2]["decided_by_user_id"] is None
    assert ctx.rounds[2]["decided_at"] is None
    current = ok(api.get_appeal(ctx.appeal_id, COMMITTEE))
    assert current["status"] == APPEAL_COMMITTEE_REVIEW
    assert current["round_number"] == 3


def test_fourth_revision_request_is_refused_at_the_round_ceiling(api):
    """PRD 3.5: "A filing whose predecessor chain has already reached
    `round_number` 3 is rejected with `ERR_APPEAL_ROUNDS_EXHAUSTED`, and so is a
    revision request or a resubmission on an appeal already sitting at
    `round_number` 3."

    Design: Difficulty/non_linear_state_machine/appeal_revision_round_cycle
    """
    ctx = _appeal_at_round_three(api)

    response = api.appeal_status(
        ctx.appeal_id, f.action("REQUEST_REVISION"), COMMITTEE
    )

    error(response, ERR_APPEAL_ROUNDS_EXHAUSTED)
    unchanged = ok(api.get_appeal(ctx.appeal_id, COMMITTEE))
    assert unchanged["status"] == APPEAL_COMMITTEE_REVIEW
    assert unchanged["round_number"] == 3
    certification = fx.read_certification(api, ctx.certification_id)
    assert certification["status"] == "DENIED"
    assert certification["failure_reasons"] == ["GPA_BELOW_MINIMUM"]


def _certified_student_with_travel_exposure(api):
    """A certified student who also holds an untouched travelling enrollment."""
    ctx = fx.enrolled_student(
        api,
        term_count=1,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
        min_progress_gpa=2.0,
        student_overrides={"full_name": "Sam Seven", "sport_code": "BASE"},
    )
    fx.record_grade(api, ctx.enrollment_id, "B")
    soci = fx.make_course(
        api, subject_code="SOCI", course_number="150",
        title="Introduction to Sociology", credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1, meeting_days=[1, 3, 5],
        meeting_start_minute_utc=600, meeting_duration_minutes=180,
    )
    soci_enrollment = fx.make_enrollment(
        api, ctx.student_id, soci["id"], ctx.term_id
    )
    ctx.certification = fx.make_certified_certification(
        api, ctx.student_id, ctx.term_id
    )
    ctx.certification_id = ctx.certification["id"]
    ctx.soci_enrollment_id = soci_enrollment["id"]
    ctx.event = fx.make_approved_event(
        api, ctx.term_id, "2026-09-14T08:00:00Z", "2026-09-19T00:00:00Z",
        sport_code="BASE",
    )
    ctx.event_id = ctx.event["id"]
    return ctx


def test_revocation_moves_eligibility_without_touching_support(api):
    """PRD 3.4: "None of these re-derivations touches `support_status`: the two
    dimensions live on the same row and evolve independently, and a
    certification decision never moves the support dimension."

    Design: Difficulty/non_linear_state_machine/student_parallel_dimensions_independent
    """
    ctx = _certified_student_with_travel_exposure(api)
    before = fx.read_student(api, ctx.student_id)
    assert before["eligibility_state"] == "CERTIFIED"
    assert before["support_status"] == SUPPORT_NORMAL

    fx.revoke_certification(api, ctx.certification_id)

    after = fx.read_student(api, ctx.student_id)
    assert after["eligibility_state"] == ELIGIBILITY_INELIGIBLE
    assert after["support_status"] == SUPPORT_NORMAL
    assert after["risk_tier"] == RISK_TIER_1
    assert_close(after["risk_score"], 0.00)


def test_support_dimension_moves_without_touching_eligibility(api):
    """PRD 3.6: "From `SUPPORT_NORMAL` a student moves to `SUPPORT_MANDATED`
    when the tier lands in `TIER_2` or `TIER_3`, provided `apr_points_forfeited`
    is below 2 and no top-severity incident against the student has been
    substantiated or remediated; the study-hall obligation is rewritten on the
    move."

    Design: Difficulty/non_linear_state_machine/student_parallel_dimensions_independent
    """
    ctx = _certified_student_with_travel_exposure(api)
    fx.revoke_certification(api, ctx.certification_id)

    request = fx.make_request(api, ctx.event_id, ctx.soci_enrollment_id)

    assert request["missed_meeting_count"] == 3
    assert_close(request["missed_units"], 9.00)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 9.00)
    assert_close(student["missed_class_units_remaining"], 0.00)
    assert_close(student["risk_score"], 20.00)
    assert student["risk_tier"] == RISK_TIER_2
    assert student["support_status"] == SUPPORT_MANDATED
    assert_close(student["required_study_hall_hours"], 7.0, tolerance=0.05)
    # The eligibility dimension is untouched by the support move.
    assert student["eligibility_state"] == ELIGIBILITY_INELIGIBLE


def _tutor_at_two_penalty_points(api):
    """A TRAINED tutor holding 2 penalty points and one ACTIVE 8-hour assignment.

    The student carries a 6.00-unit travel charge against a 9.00 allowance and
    no completed coursework, so the tutoring credit is what holds
    ``required_study_hall_hours`` down at 6.0.
    """
    ctx = fx.travel_world(
        api,
        meeting_days=[1, 3, 5],
        meeting_duration_minutes=180,
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-17T00:00:00Z",
        sport_code="TRACK",
    )
    fx.make_request(api, ctx.event_id, ctx.enrollment_id)
    tutor = fx.make_trained_tutor(
        api, ctx.term_id, ["KINE"], full_name="Tom Tutor"
    )
    ctx.tutor_id = tutor["id"]
    ctx.assignment = fx.make_active_assignment(
        api, ctx.tutor_id, ctx.enrollment_id, 8.0
    )
    ctx.assignment_id = ctx.assignment["id"]
    first = fx.make_incident(
        api,
        ctx.student_id,
        incident_type="EXCESSIVE_TUTOR_HOURS",
        narrative="Tutor logged hours beyond the approved weekly allotment.",
        tutor_id=ctx.tutor_id,
    )
    fx.substantiate_incident(api, first["id"], "LEVEL_II")
    second = fx.make_incident(
        api,
        ctx.student_id,
        incident_type="UNTRAINED_TUTOR_SESSION",
        narrative="A second review found an unapproved session with the tutor.",
        tutor_id=ctx.tutor_id,
    )
    fx.incident_action(api, second["id"], "OPEN_INVESTIGATION")
    ctx.first_incident_id = first["id"]
    ctx.second_incident_id = second["id"]
    return ctx


def test_third_penalty_point_suspends_the_tutor(api):
    """PRD 3.9: "If the tutor's `penalty_points` has thereby reached three, the
    tutor moves `TRAINED → SUSPENDED` or `EXPIRED → SUSPENDED`; a tutor already
    `UNTRAINED`, `SUSPENDED` or `TERMINATED` accumulates the points with no
    status change at all."

    Design: Difficulty/transitive_cascade/incident_substantiation_cascade_depth_four
    """
    ctx = _tutor_at_two_penalty_points(api)
    before = fx.read_tutor(api, ctx.tutor_id)
    assert before["penalty_points"] == 2
    assert before["status"] == "TRAINED"

    substantiated = ok(
        api.incident_status(
            ctx.second_incident_id, f.substantiate("LEVEL_I"), COMPLIANCE
        )
    )

    assert substantiated["status"] == "SUBSTANTIATED"
    assert_close(substantiated["penalty_points_assessed"], 1.00)
    tutor = fx.read_tutor(api, ctx.tutor_id)
    assert tutor["penalty_points"] == 3
    assert tutor["status"] == "SUSPENDED"


def test_tutor_suspension_terminates_assignments_and_raises_study_hall(api):
    """PRD 3.9: "Where the tutor did become suspended, each of that tutor's
    assignments in `PROPOSED` or `ACTIVE` moves to `TERMINATED` with
    `terminated_reason` of `TUTOR_SUSPENDED` in `created_at` ascending order, and
    the tutor's `assigned_weekly_hours` drops by each formerly active
    assignment's `weekly_hours`."

    Design: Difficulty/transitive_cascade/incident_substantiation_cascade_depth_four
    """
    ctx = _tutor_at_two_penalty_points(api)
    before = fx.read_student(api, ctx.student_id)
    assert_close(before["required_study_hall_hours"], 6.0, tolerance=0.05)

    ok(
        api.incident_status(
            ctx.second_incident_id, f.substantiate("LEVEL_I"), COMPLIANCE
        )
    )

    assignment = ok(api.get_assignment(ctx.assignment_id, SPECIALIST))
    assert assignment["status"] == "TERMINATED"
    assert assignment["terminated_reason"] == "TUTOR_SUSPENDED"
    tutor = fx.read_tutor(api, ctx.tutor_id)
    assert_close(tutor["assigned_weekly_hours"], 0.00)
    student = fx.read_student(api, ctx.student_id)
    # The tutoring credit vanished, so the gross 10.0 now stands unrelieved.
    assert_close(student["required_study_hall_hours"], 10.0, tolerance=0.05)
    assert_close(student["substantiated_penalty_points"], 3.00)
    assert_close(student["risk_score"], 64.58)
    assert student["risk_tier"] == RISK_TIER_3
    assert student["support_status"] == SUPPORT_MANDATED
    assert_close(student["missed_class_units_charged"], 6.00)


def _acknowledged_nine_unit_charge(api):
    """An ACKNOWLEDGED request that has consumed the whole 9.00-unit budget."""
    ctx = fx.travel_world(
        api,
        meeting_days=[1, 3, 5],
        meeting_duration_minutes=180,
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-19T00:00:00Z",
        sport_code="MBB",
    )
    fx.add_graded_course(
        api, ctx, ctx.term, grade="B", credit_hours=12.0, subject_code="HIST"
    )
    request = fx.make_notified_request(api, ctx.event_id, ctx.enrollment_id)
    ctx.request = fx.request_action(
        api,
        request["id"],
        "ACKNOWLEDGE",
        instructor_headers(ctx.course["instructor_user_id"]),
        instructor_response_note="Attendance excused; make-up quiz scheduled.",
    )
    ctx.request_id = request["id"]
    return ctx


def test_event_cancellation_voids_the_request_and_refunds_the_budget(api):
    """PRD 3.8: "Cancelling a `TRAVEL_APPROVED` event releases everything: each
    missed-class request of that event in `DRAFT`, `PENDING_ACKNOWLEDGEMENT`,
    `ACKNOWLEDGED` or `DISPUTED` moves to `VOIDED` in `created_at` ascending
    order; each affected student's `missed_class_units_charged` decreases by that
    request's `missed_units` while `missed_class_units_remaining` increases by
    the same amount; the event's `charged_units_total` becomes 0"

    Design: Difficulty/transitive_cascade/event_cancellation_cascade_refund_chain
    """
    ctx = _acknowledged_nine_unit_charge(api)
    assert ctx.request["status"] == "ACKNOWLEDGED"

    cancelled = fx.event_action(api, ctx.event_id, "CANCEL")

    assert cancelled["status"] == "CANCELLED"
    request = ok(api.get_missed_class_request(ctx.request_id, ADVISOR))
    assert request["status"] == "VOIDED"
    # The voided row keeps its computed figure for the audit trail.
    assert_close(request["missed_units"], 9.00)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 0.00)
    assert_close(student["missed_class_units_remaining"], 9.00)
    event = ok(api.get_event(ctx.event_id, OPERATIONS))
    assert_close(event["charged_units_total"], 0.00)


def test_event_cancellation_rescores_risk_and_relaxes_support(api):
    """PRD 3.8: "the risk score re-runs for each affected student and rewrites
    `risk_score` and `risk_tier`; the study-hall requirement re-runs and
    rewrites `required_study_hall_hours`; `support_status` is re-derived; and
    each affected student's `version` increments by one."

    Design: Difficulty/transitive_cascade/event_cancellation_cascade_refund_chain
    """
    ctx = _acknowledged_nine_unit_charge(api)
    before = fx.read_student(api, ctx.student_id)
    assert_close(before["risk_score"], 20.00)
    assert before["risk_tier"] == RISK_TIER_2
    assert before["support_status"] == SUPPORT_MANDATED
    assert_close(before["required_study_hall_hours"], 7.0, tolerance=0.05)

    fx.event_action(api, ctx.event_id, "CANCEL")

    after = fx.read_student(api, ctx.student_id)
    assert_close(after["risk_score"], 0.00)
    assert after["risk_tier"] == RISK_TIER_1
    assert after["support_status"] == SUPPORT_NORMAL
    assert_close(after["required_study_hall_hours"], 0.0, tolerance=0.05)
    assert after["version"] == before["version"] + 1
