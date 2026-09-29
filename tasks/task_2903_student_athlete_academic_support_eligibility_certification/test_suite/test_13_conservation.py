"""The three conservation invariants, each probed across a compensating move."""

from test_helpers import (
    assert_apr_ledger_conserved,
    assert_close,
    assert_missed_class_budget_conserved,
    assert_tutor_capacity_conserved,
    created,
    ok,
    page,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.constants import (
    APPLICABILITY_NOT_APPLICABLE,
    CERT_TYPE_CONTINUING,
    ELIGIBILITY_INELIGIBLE,
)
from test_helpers.test_users import (
    ADVISOR,
    INSTRUCTOR_HIST_1,
    INSTRUCTOR_SOC_1,
    OPERATIONS,
    REGISTRAR,
    SPECIALIST,
)


def _two_meeting_travel_charge(api):
    """A TRAVEL_APPROVED trip covering two 3-hour meetings, worth 6.00 units."""
    return fx.travel_world(
        api,
        meeting_days=[1, 3, 5],
        meeting_duration_minutes=180,
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-17T00:00:00Z",
        sport_code="WBB",
    )


def test_missed_class_charge_splits_the_allowance_without_drift(api):
    """PRD 3.8: "The charge posts immediately: the student's
    `missed_class_units_charged` increases by `missed_units`,
    `missed_class_units_remaining` becomes the `missed_class_units_allowance`
    minus the new charged total, and the event's `charged_units_total` increases
    by `missed_units`."

    Design: Difficulty/compensating_invariant/missed_class_unit_budget_conserved_after_cancellation
    """
    ctx = _two_meeting_travel_charge(api)

    request = created(
        api.create_missed_class_request(
            f.missed_class_request(ctx.event_id, ctx.enrollment_id), ADVISOR
        )
    )

    # Monday 2026-09-14 and Wednesday 2026-09-16 are inside the window; the
    # Friday meeting is not, so 3.00 + 3.00 units are charged.
    assert request["missed_meeting_count"] == 2
    assert_close(request["missed_units_gross"], 6.00)
    assert_close(request["missed_units"], 6.00)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_allowance"], 9.00)
    assert_close(student["missed_class_units_charged"], 6.00)
    assert_close(student["missed_class_units_remaining"], 3.00)
    assert_missed_class_budget_conserved(student)
    event = ok(api.get_event(ctx.event_id, OPERATIONS))
    assert_close(event["charged_units_total"], 6.00)


def test_cancelling_the_request_releases_every_charged_unit(api):
    """PRD 2.10: "`missed_class_units_charged` is the sum of `missed_units` over
    that student's missed-class requests in the holding statuses `DRAFT`,
    `PENDING_ACKNOWLEDGEMENT`, `ACKNOWLEDGED` and `DISPUTED`; requests in
    `CANCELLED` or `VOIDED` release their units."

    Design: Difficulty/compensating_invariant/missed_class_unit_budget_conserved_after_cancellation
    """
    ctx = _two_meeting_travel_charge(api)
    request = fx.make_request(api, ctx.event_id, ctx.enrollment_id)

    cancelled = fx.request_action(api, request["id"], "CANCEL", ADVISOR)

    assert cancelled["status"] == "CANCELLED"
    # The terminal row keeps its computed figure as a historical record.
    assert_close(cancelled["missed_units"], 6.00)
    student = fx.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 0.00)
    assert_close(student["missed_class_units_remaining"], 9.00)
    assert_missed_class_budget_conserved(student)
    event = ok(api.get_event(ctx.event_id, OPERATIONS))
    assert_close(event["charged_units_total"], 0.00)


def _tutor_with_three_active_assignments(api):
    """One TRAINED tutor holding three ACTIVE 2.00-hour assignments."""
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    term = fx.make_term(api, index=1, catalog_year=2026)
    course = fx.make_course(
        api, subject_code="SOCI", course_number="150",
        title="Introduction to Sociology", credit_hours=3.0,
        instructor_user_id=INSTRUCTOR_SOC_1,
    )
    tutor = fx.make_trained_tutor(
        api, term["id"], ["SOCI"], full_name="Tina Capacity",
        max_weekly_hours=20.0,
    )
    assignments = []
    students = []
    for suffix in ("A", "B", "C"):
        student = fx.make_student(
            api, full_name=f"Sam Twenty {suffix}", sport_code="SOC",
            entry_term_index=1, entry_catalog_year=2026,
        )
        enrollment = fx.make_enrollment(
            api, student["id"], course["id"], term["id"]
        )
        students.append(student)
        assignments.append(
            fx.make_active_assignment(
                api, tutor["id"], enrollment["id"], 2.0
            )
        )
    ctx = fx.Ctx(term_id=term["id"], tutor_id=tutor["id"])
    ctx.students = students
    ctx.assignments = assignments
    ctx.first_id = assignments[0]["id"]
    ctx.second_id = assignments[1]["id"]
    ctx.third_id = assignments[2]["id"]
    return ctx


def _tutor_assignments(api, tutor_id):
    rows, _ = page(api.list_assignments(SPECIALIST, {"tutor_id": tutor_id}))
    return rows


def test_suspension_and_termination_each_release_exactly_their_hours(api):
    """PRD 3.7: "Suspending an assignment takes it `ACTIVE → SUSPENDED`,
    increments `suspension_count` by one, decreases the tutor's
    `assigned_weekly_hours` by the assignment's `weekly_hours`, and re-runs the
    study-hall requirement and the support re-derivation for the student."

    Design: Difficulty/compensating_invariant/tutor_capacity_hours_conserved_after_termination
    """
    ctx = _tutor_with_three_active_assignments(api)
    before = fx.read_tutor(api, ctx.tutor_id)
    assert_close(before["assigned_weekly_hours"], 6.00)
    assert_tutor_capacity_conserved(before, _tutor_assignments(api, ctx.tutor_id))

    suspended = fx.assignment_action(api, ctx.second_id, "SUSPEND")
    after_suspend = fx.read_tutor(api, ctx.tutor_id)
    terminated = fx.assignment_action(
        api, ctx.third_id, "TERMINATE", terminated_reason="SPECIALIST_REQUEST"
    )
    after_terminate = fx.read_tutor(api, ctx.tutor_id)

    assert suspended["status"] == "SUSPENDED"
    assert suspended["suspension_count"] == 1
    assert_close(after_suspend["assigned_weekly_hours"], 4.00)
    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_reason"] == "SPECIALIST_REQUEST"
    assert_close(after_terminate["assigned_weekly_hours"], 2.00)
    assert_tutor_capacity_conserved(
        after_terminate, _tutor_assignments(api, ctx.tutor_id)
    )


def test_reinstatement_re_reserves_the_released_capacity(api):
    """PRD 2.10: "**Tutor capacity.** For every tutor, `assigned_weekly_hours`
    equals the sum of `weekly_hours` over that tutor's assignments whose status
    is `ACTIVE` — no more and no less — after every assignment transition, every
    cascade and every tutor status change."

    Design: Difficulty/compensating_invariant/tutor_capacity_hours_conserved_after_termination
    """
    ctx = _tutor_with_three_active_assignments(api)
    fx.assignment_action(api, ctx.second_id, "SUSPEND")
    fx.assignment_action(
        api, ctx.third_id, "TERMINATE", terminated_reason="SPECIALIST_REQUEST"
    )

    reinstated = fx.assignment_action(api, ctx.second_id, "REINSTATE")

    assert reinstated["status"] == "ACTIVE"
    # suspension_count is monotonic: reinstatement never decrements it.
    assert reinstated["suspension_count"] == 1
    tutor = fx.read_tutor(api, ctx.tutor_id)
    assert_close(tutor["assigned_weekly_hours"], 4.00)
    assert tutor["status"] == "TRAINED"
    assert_close(tutor["max_weekly_hours"], 20.00)
    rows = _tutor_assignments(api, ctx.tutor_id)
    assert_tutor_capacity_conserved(tutor, rows)
    first = ok(api.get_assignment(ctx.first_id, SPECIALIST))
    assert first["status"] == "ACTIVE"
    assert_close(first["weekly_hours"], 2.00)


def _first_term_closed_with_full_points(api):
    """A CERTIFIED first term closed at 2/2, with the second term still OPEN."""
    ctx = fx.enrolled_student(
        api,
        term_count=2,
        clock="2026-09-01T00:00:00Z",
        credit_hours=12.0,
        declare_major_in_term=1,
        student_overrides={"full_name": "Sam Twentyone", "sport_code": "TRACK"},
    )
    fx.record_grade(api, ctx.enrollment_id, "B")
    history = fx.make_course(
        api, subject_code="HIST", course_number="210",
        title="Modern World History", credit_hours=12.0,
        instructor_user_id=INSTRUCTOR_HIST_1,
    )
    fx.make_rule(
        api,
        ctx.program_id,
        history["id"],
        effective_catalog_year=2026,
        applicability=APPLICABILITY_NOT_APPLICABLE,
    )
    # An ENROLLED intent in the next term, which the PROJECTED variant reads.
    ctx.next_term_enrollment = fx.make_enrollment(
        api, ctx.student_id, history["id"], ctx.terms[1]["id"]
    )
    ctx.first_certification = fx.make_certified_certification(
        api, ctx.student_id, ctx.term_id
    )
    ctx.first_certification_id = ctx.first_certification["id"]
    ctx.second_term_id = ctx.terms[1]["id"]
    ctx.first_close = fx.close_term(api, ctx.term_id, "2026-12-18T00:00:00Z")
    return ctx


def test_first_close_awards_both_points_and_forfeits_none(api):
    """PRD 3.9: "Each student's `apr_points_earned` then increases by the sum of
    the two point tests, `apr_points_possible` increases by 2, and
    `apr_points_forfeited` is set so that `apr_points_possible` equals
    `apr_points_earned` plus `apr_points_forfeited` exactly after the close."

    Design: Difficulty/compensating_invariant/apr_points_possible_conserved_across_revocation
    """
    ctx = _first_term_closed_with_full_points(api)

    assert ctx.first_close["apr_status"] == "CLOSED"
    assert ctx.first_close["apr_points_possible"] == 2
    assert ctx.first_close["apr_points_earned"] == 2
    assert ctx.first_close["squad_apr"] == 1000
    student = fx.read_student(api, ctx.student_id)
    assert student["apr_points_possible"] == 2
    assert student["apr_points_earned"] == 2
    assert student["apr_points_forfeited"] == 0
    assert_apr_ledger_conserved(student)
    certification = fx.read_certification(api, ctx.first_certification_id)
    assert certification["status"] == "CERTIFIED"


def test_revocation_absorbs_its_loss_as_forfeited_points(api):
    """PRD 2.10: "**The academic-progress-rate points ledger.** For every
    student, `apr_points_possible` equals `apr_points_earned` plus
    `apr_points_forfeited` exactly, after every close. Points are never rolled
    back once awarded or forfeited: revoking a certification after a close changes
    the student's eligibility standing but leaves all three counters untouched, so
    the equality survives."

    Design: Difficulty/compensating_invariant/apr_points_possible_conserved_across_revocation
    """
    ctx = _first_term_closed_with_full_points(api)
    fx.set_clock(api, "2027-01-11T00:00:00Z")
    second = fx.make_certified_certification(
        api, ctx.student_id, ctx.second_term_id,
        certification_type=CERT_TYPE_CONTINUING,
    )
    assert second["benchmark_result"] == "PASS"
    assert_close(second["required_progress_pct"], 0.0000, tolerance=0.00005)
    assert_close(second["progress_pct"], 0.2000, tolerance=0.00005)

    revoked = fx.revoke_certification(api, second["id"])
    after_revoke = fx.read_student(api, ctx.student_id)
    second_close = fx.close_term(api, ctx.second_term_id, "2027-05-14T00:00:00Z")

    assert revoked["status"] == "REVOKED"
    assert after_revoke["eligibility_state"] == ELIGIBILITY_INELIGIBLE
    # The already-closed term is untouched by the revocation.
    assert after_revoke["apr_points_possible"] == 2
    assert after_revoke["apr_points_earned"] == 2
    assert after_revoke["apr_points_forfeited"] == 0
    first_term = ok(api.get_term(ctx.term_id, REGISTRAR))
    assert first_term["squad_apr"] == 1000
    # The eligibility point is lost; with no later term the retention point is
    # awarded by default.
    assert second_close["apr_points_possible"] == 2
    assert second_close["apr_points_earned"] == 1
    assert second_close["squad_apr"] == 500
    student = fx.read_student(api, ctx.student_id)
    assert student["apr_points_possible"] == 4
    assert student["apr_points_earned"] == 3
    assert student["apr_points_forfeited"] == 1
    assert_apr_ledger_conserved(student)
    first_certification = fx.read_certification(api, ctx.first_certification_id)
    assert first_certification["status"] == "CERTIFIED"
