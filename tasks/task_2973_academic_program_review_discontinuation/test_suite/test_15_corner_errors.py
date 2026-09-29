"""Error corners: the per-family not-found ids, the seat and student gates, and the fixed refusal order between them."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import *  # noqa: F401,F403
from test_helpers.test_users import (
    make_external_reviewer_headers,
    make_hr_partner_headers,
    make_provost_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)

# Well-formed v4 UUIDs that resolve to nothing on an empty database.
UNKNOWN_SELF_STUDY_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_VISIT_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_DECISION_ID = "00000000-0000-4000-8000-000000000003"
UNKNOWN_NOTIFICATION_ID = "00000000-0000-4000-8000-000000000004"
UNKNOWN_PLAN_ID = "00000000-0000-4000-8000-000000000005"
UNKNOWN_GUARANTEE_ID = "00000000-0000-4000-8000-000000000006"
UNKNOWN_STUDENT_ID = "00000000-0000-4000-8000-000000000007"
UNKNOWN_APPOINTMENT_ID = "00000000-0000-4000-8000-000000000008"

# §3.4: the visit window has elapsed by this instant, so completion is permitted.
CLOCK_AFTER_FIRST_VISIT = "2026-08-23T00:00:00Z"


def _assert_message_present(error, label):
    """§2.2: an error envelope carries a non-empty human-readable message."""
    assert isinstance(error.get("message"), str), (
        f"{label}: data.message must be a string, got {error.get('message')!r}"
    )
    assert error["message"].strip(), f"{label}: data.message must be non-empty"


def test_every_unknown_path_id_reports_its_own_entity_not_found(api):
    """Eight entity families each answer an unknown path id with their own 404.

    Check 7 resolves every path identifier left to right and reports the 404
    naming the missing record type — never a shared generic id — and it ranks
    above check 9's body validation and above check 40's advising gate, so a
    request whose payload would also have been rejected still reports the
    not-found.

    Design: Corner/errors/every_unknown_path_id_reports_its_own_entity_not_found
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    coordinator = make_review_coordinator_headers()
    provost = make_provost_headers()
    registrar = make_registrar_headers()
    hr = make_hr_partner_headers()

    e1 = validate_error(
        api.transition_self_study(
            UNKNOWN_SELF_STUDY_ID, factories.self_study_accept_payload(), coordinator
        ),
        ERR_SELF_STUDY_NOT_FOUND,
        404,
    )
    _assert_message_present(e1, "self-study")

    e2 = validate_error(
        api.get_reviewer_visit(UNKNOWN_VISIT_ID, coordinator), ERR_VISIT_NOT_FOUND, 404
    )
    _assert_message_present(e2, "visit")

    e3 = validate_error(
        api.get_decision_record(UNKNOWN_DECISION_ID, provost), ERR_DECISION_NOT_FOUND, 404
    )
    _assert_message_present(e3, "decision")

    e4 = validate_error(
        api.transition_agency_notification(
            UNKNOWN_NOTIFICATION_ID,
            factories.notification_send_payload("TX-0001"),
            coordinator,
        ),
        ERR_NOTIFICATION_NOT_FOUND,
        404,
    )
    _assert_message_present(e4, "notification")

    e5 = validate_error(
        api.get_teach_out_plan(UNKNOWN_PLAN_ID, coordinator), ERR_PLAN_NOT_FOUND, 404
    )
    _assert_message_present(e5, "plan")

    e6 = validate_error(
        api.allocate_seats(
            UNKNOWN_GUARANTEE_ID,
            factories.seat_waive_payload(waived_reason_code="NO-DEMAND"),
            registrar,
        ),
        ERR_GUARANTEE_NOT_FOUND,
        404,
    )
    _assert_message_present(e6, "guarantee")

    e7 = validate_error(
        api.record_advising(
            UNKNOWN_STUDENT_ID,
            factories.advising_payload(advised_credits_per_term=9, plan_signed=False),
            registrar,
        ),
        ERR_STUDENT_NOT_FOUND,
        404,
    )
    _assert_message_present(e7, "student advising")

    e8 = validate_error(
        api.transition_faculty_appointment(
            UNKNOWN_APPOINTMENT_ID, factories.retain_payload(), hr
        ),
        ERR_APPOINTMENT_NOT_FOUND,
        404,
    )
    _assert_message_present(e8, "appointment")

    # The unknown path id is reported at priority 7, ahead of the priority-9 body
    # check that would have rejected this term index on a real plan and ahead of
    # the priority-40 advising check.
    e9 = validate_error(
        api.record_student_progress(
            UNKNOWN_STUDENT_ID,
            factories.student_complete_payload(completion_term_index=99),
            registrar,
        ),
        ERR_STUDENT_NOT_FOUND,
        404,
    )
    _assert_message_present(e9, "student progress")

    # None of the nine calls created anything.
    _programs, program_meta = validate_paginated(
        api.list_programs(registrar, params={"limit": 10, "offset": 0})
    )
    assert program_meta["total_count"] == 0
    _plans, plan_meta = validate_paginated(
        api.list_teach_out_plans(coordinator, params={"limit": 10, "offset": 0})
    )
    assert plan_meta["total_count"] == 0
    _decisions, decision_meta = validate_paginated(
        api.list_decision_records(coordinator, params={"limit": 10, "offset": 0})
    )
    assert decision_meta["total_count"] == 0


def test_a_second_report_without_an_addendum_request_is_refused(api):
    """A second report is refused unless the cycle is sitting in ADDENDUM_REQUESTED.

    §3.5 permits addenda only from `ADDENDUM_REQUESTED`, and check 25 refuses
    every later report with `ERR_REPORT_ALREADY_FILED` (409) once `report_count`
    has left 0. The refusal writes nothing: the visit keeps its single report and
    its `REPORTED` state, and the cycle's addendum round stays closed.

    Design: Corner/errors/a_second_report_without_an_addendum_request_is_refused
    """
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_id = program["id"]
    coordinator = make_review_coordinator_headers()
    cycle = fixtures.open_cycle(api, program_id)
    self_study = fixtures.create_self_study(api, cycle["id"], program_id)
    fixtures.accept_self_study(api, self_study["id"], program_id)
    reviewer = fixtures.register_reviewer(
        api,
        full_name="Dr Nala Osei",
        institution="Westmoor University",
        specialty_code="HIST",
    )
    visit = fixtures.schedule_visit(api, cycle["id"], reviewer["id"])
    fixtures.set_clock(api, CLOCK_AFTER_FIRST_VISIT)
    fixtures.complete_visit(api, visit["id"])
    first_report = fixtures.file_report(
        api,
        visit["id"],
        reviewer["id"],
        recommendation="IMPROVE",
        finding_codes=["F-ENROLL"],
        narrative="First and only report.",
    )
    assert first_report["sequence_number"] == 1

    refused = api.create_reviewer_report(
        visit["id"],
        factories.reviewer_report_payload(
            recommendation="DISCONTINUE",
            finding_codes=["F-COST"],
            narrative="A second opinion nobody asked for.",
        ),
        make_external_reviewer_headers(reviewer["id"]),
    )
    validate_error(refused, ERR_REPORT_ALREADY_FILED, 409)

    visit_after = validate_success(api.get_reviewer_visit(visit["id"], coordinator))
    assert visit_after["report_count"] == 1
    assert visit_after["state"] == "REPORTED"

    cycle_after = fixtures.read_cycle(api, cycle["id"])
    assert cycle_after["state"] == "REPORT_RECEIVED"
    assert cycle_after["addendum_round"] == 0, (
        "a refused filing does not open an addendum round"
    )

    reports, meta = validate_paginated(
        api.list_reviewer_reports(
            visit["id"], coordinator, params={"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    assert reports[0]["id"] == first_report["id"]
    assert reports[0]["recommendation"] == "IMPROVE"
    assert reports[0]["finding_codes"] == ["F-ENROLL"]
    assert reports[0]["sequence_number"] == 1


def test_the_seat_ledger_refuses_over_release_and_refuses_to_drop_a_held_guarantee(api):
    """Three refusals defend the seat conservation invariant from three angles.

    Check 38 refuses a release the named student cannot cover — whether they hold
    nothing at all or hold fewer than the released count, and the release is
    refused whole rather than clamped. Check 39 refuses a waive while
    `seats_committed` is above 0. Once the seats are properly released the same
    waive succeeds, and `WAIVED` is terminal, so check 12 answers ahead of the
    seat checks on every later action. §3.9 drops a waived row out of
    `guaranteed_seat_total`, which re-derives `seat_shortfall`.

    Design: Corner/errors/the_seat_ledger_refuses_over_release_and_refuses_to_drop_a_held_guarantee
    """
    registrar = make_registrar_headers()
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = ctx.plan["id"]
    g1 = fixtures.add_guarantee(
        api, ctx, course_code="HIST-301", term_index=4, seats_guaranteed=5
    )
    s1 = fixtures.enrol_student(
        api, ctx, student_number="S-0001", credits_remaining=24, max_credits_per_term=15
    )
    s2 = fixtures.enrol_student(
        api, ctx, student_number="S-0002", credits_remaining=12, max_credits_per_term=12
    )

    def read_guarantee():
        rows, _meta = validate_paginated(
            api.list_course_guarantees(
                plan_id, registrar, params={"limit": 10, "offset": 0}
            )
        )
        return rows[0]

    def read_students():
        rows, meta = validate_paginated(
            api.list_displaced_students(
                plan_id, registrar, params={"limit": 10, "offset": 0}
            )
        )
        return {row["id"]: row for row in rows}, meta

    committed = validate_success(
        api.allocate_seats(
            g1["id"], factories.seat_commit_payload(s1["id"], 3), registrar
        )
    )
    assert committed["seats_committed"] == 3
    assert committed["seats_available"] == 2

    # s2 holds nothing on g1; the guarantee holding somebody else's three seats
    # does not license a release on s2's behalf.
    validate_error(
        api.allocate_seats(
            g1["id"], factories.seat_release_payload(s2["id"], 1), registrar
        ),
        ERR_SEAT_NOT_COMMITTED,
        409,
    )
    # s1 holds exactly three, so releasing four is refused whole, not clamped.
    validate_error(
        api.allocate_seats(
            g1["id"], factories.seat_release_payload(s1["id"], 4), registrar
        ),
        ERR_SEAT_NOT_COMMITTED,
        409,
    )

    held = read_guarantee()
    assert held["seats_committed"] == 3
    assert held["seats_available"] == 2
    assert held["status"] == "PLANNED"
    students, _meta = read_students()
    assert students[s1["id"]]["committed_seat_count"] == 3
    assert students[s2["id"]]["committed_seat_count"] == 0

    validate_error(
        api.allocate_seats(g1["id"], factories.seat_waive_payload(), registrar),
        ERR_GUARANTEE_HAS_COMMITMENTS,
        409,
    )
    still_planned = read_guarantee()
    assert still_planned["status"] == "PLANNED"
    assert still_planned["waived_reason_code"] is None

    released = validate_success(
        api.allocate_seats(
            g1["id"], factories.seat_release_payload(s1["id"], 3), registrar
        )
    )
    assert released["seats_committed"] == 0
    assert released["seats_available"] == 5
    students, _meta = read_students()
    assert students[s1["id"]]["committed_seat_count"] == 0
    assertions.assert_seat_conservation([released], list(students.values()))

    waived = validate_success(
        api.allocate_seats(
            g1["id"],
            factories.seat_waive_payload(waived_reason_code="NO-DEMAND"),
            registrar,
        )
    )
    assert waived["status"] == "WAIVED"
    assert waived["waived_reason_code"] == "NO-DEMAND"

    # WAIVED is terminal, so check 12 answers ahead of the priority-39 seat check
    # even though seats_committed is now 0.
    validate_error(
        api.allocate_seats(
            g1["id"],
            factories.seat_waive_payload(waived_reason_code="NO-DEMAND"),
            registrar,
        ),
        ERR_GUARANTEE_STATE_INVALID,
        409,
    )
    validate_error(
        api.allocate_seats(
            g1["id"],
            factories.seat_substitute_payload(
                substitute_course_code="HIST-305",
                substitution_justification="Equivalent seminar.",
            ),
            registrar,
        ),
        ERR_GUARANTEE_STATE_INVALID,
        409,
    )
    terminal = read_guarantee()
    assert terminal["status"] == "WAIVED"
    assert terminal["substitute_course_code"] is None

    plan = validate_success(api.get_teach_out_plan(plan_id, registrar))
    assertions.assert_plan_ledger(
        plan,
        guaranteed_seat_total=0,
        committed_seat_total=0,
        required_seat_total=12,
        seat_shortfall=12,
        at_risk_student_count=0,
        open_student_count=2,
        substituted_guarantee_count=0,
        waived_guarantee_count=1,
    )

    students, students_meta = read_students()
    assert students_meta["total_count"] == 2
    assertions.assert_projection(
        students[s1["id"]],
        "OPTIMISTIC_FULL_LOAD",
        2,
        5,
        False,
        required_seat_count=8,
    )
    assertions.assert_projection(
        students[s2["id"]],
        "OPTIMISTIC_FULL_LOAD",
        1,
        4,
        False,
        required_seat_count=4,
    )
    for student_id in (s1["id"], s2["id"]):
        assert students[student_id]["advising_status"] == "PENDING"
        assert students[student_id]["committed_seat_count"] == 0


def test_completion_needs_a_signed_plan_and_a_completed_student_is_terminal(api):
    """The two student errors partition one endpoint by cause, not by shape.

    Check 12's carve-out hands a COMPLETE from `PENDING` or `ADVISED` down to
    check 40, whose `ERR_ADVISING_REQUIRED` names the actionable cause, while a
    write on an already `COMPLETED` student is reported by check 12 as
    `ERR_STUDENT_STATE_INVALID`. §3.10 also releases every seat the completed
    student held and drops them out of every plan aggregate, while the second open
    student keeps the plan in `IN_EFFECT`.

    Design: Corner/errors/completion_needs_a_signed_plan_and_a_completed_student_is_terminal
    """
    registrar = make_registrar_headers()
    ctx = fixtures.setup_ratified_discontinuation(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    fixtures.acknowledge_all_notifications(api, ctx.decision["id"])
    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = ctx.plan["id"]
    g1 = fixtures.add_guarantee(
        api, ctx, course_code="HIST-301", term_index=4, seats_guaranteed=7
    )
    s1 = fixtures.enrol_student(
        api, ctx, student_number="S-0001", credits_remaining=12, max_credits_per_term=15
    )
    s2 = fixtures.enrol_student(
        api, ctx, student_number="S-0002", credits_remaining=9, max_credits_per_term=15
    )
    fixtures.submit_plan(api, ctx)
    fixtures.approve_plan(api, ctx)
    fixtures.effectuate_decision(api, ctx)
    activated = fixtures.activate_plan(api, ctx)
    assert activated["state"] == "IN_EFFECT"
    validate_success(
        api.allocate_seats(
            g1["id"], factories.seat_commit_payload(s1["id"], 4), registrar
        )
    )
    validate_success(
        api.allocate_seats(
            g1["id"], factories.seat_commit_payload(s2["id"], 3), registrar
        )
    )

    # From PENDING the carve-out names the missing signed advising plan.
    validate_error(
        api.record_student_progress(
            s1["id"], factories.student_complete_payload(completion_term_index=5), registrar
        ),
        ERR_ADVISING_REQUIRED,
        409,
    )

    advised = validate_success(
        api.record_advising(
            s1["id"],
            factories.advising_payload(advised_credits_per_term=9, plan_signed=False),
            registrar,
        )
    )
    assert advised["advising_status"] == "ADVISED"
    assert advised["advised_credits_per_term"] == 9
    assertions.assert_projection(
        advised, "CONSERVATIVE_ADVISED_LOAD", 2, 5, False, required_seat_count=4
    )

    # Recording advice without a signature is still not a signed plan.
    validate_error(
        api.record_student_progress(
            s1["id"], factories.student_complete_payload(completion_term_index=5), registrar
        ),
        ERR_ADVISING_REQUIRED,
        409,
    )

    signed = validate_success(
        api.record_advising(
            s1["id"],
            factories.advising_payload(advised_credits_per_term=9, plan_signed=True),
            registrar,
        )
    )
    assert signed["advising_status"] == "PLAN_SIGNED"
    assert signed["required_seat_count"] == 4
    assert signed["committed_seat_count"] == 4

    completed = validate_success(
        api.record_student_progress(
            s1["id"], factories.student_complete_payload(completion_term_index=5), registrar
        )
    )
    assert completed["advising_status"] == "COMPLETED"
    assert completed["completion_term_index"] == 5
    assert completed["committed_seat_count"] == 0

    # COMPLETED is terminal, so check 12 answers instead of check 40.
    validate_error(
        api.record_student_progress(
            s1["id"], factories.student_complete_payload(completion_term_index=5), registrar
        ),
        ERR_STUDENT_STATE_INVALID,
        409,
    )
    validate_error(
        api.record_student_progress(
            s1["id"],
            factories.student_withdraw_payload(withdrawal_reason_code="TRANSFER"),
            registrar,
        ),
        ERR_STUDENT_STATE_INVALID,
        409,
    )
    validate_error(
        api.record_advising(
            s1["id"],
            factories.advising_payload(advised_credits_per_term=6, plan_signed=True),
            registrar,
        ),
        ERR_STUDENT_STATE_INVALID,
        409,
    )

    students, students_meta = validate_paginated(
        api.list_displaced_students(plan_id, registrar, params={"limit": 10, "offset": 0})
    )
    assert students_meta["total_count"] == 2
    by_id = {row["id"]: row for row in students}
    assert by_id[s1["id"]]["withdrawal_reason_code"] is None
    assert by_id[s1["id"]]["advised_credits_per_term"] == 9, (
        "the refused advising write did not overwrite the stored load with 6"
    )
    assert by_id[s2["id"]]["advising_status"] == "PENDING"

    plan = validate_success(api.get_teach_out_plan(plan_id, registrar))
    assert plan["state"] == "IN_EFFECT"
    assertions.assert_plan_ledger(
        plan,
        guaranteed_seat_total=7,
        committed_seat_total=3,
        required_seat_total=3,
        seat_shortfall=0,
        at_risk_student_count=0,
        open_student_count=1,
        substituted_guarantee_count=0,
        waived_guarantee_count=0,
    )

    guarantees, _g_meta = validate_paginated(
        api.list_course_guarantees(plan_id, registrar, params={"limit": 10, "offset": 0})
    )
    assert guarantees[0]["status"] == "OFFERED"
    assert guarantees[0]["seats_guaranteed"] == 7
    assert guarantees[0]["seats_committed"] == 3
    assert guarantees[0]["seats_available"] == 4
    assertions.assert_seat_conservation(guarantees, students)

    program = fixtures.read_program(api, ctx.program_id)
    assertions.assert_axes(program, lifecycle_state="TEACH_OUT_ACTIVE")


def test_notices_follow_the_waterfall_order_and_the_statutory_minimum(api):
    """Two refusals guard one ordered queue, and their relative priority is observable.

    Check 41 requires the noticed appointment to hold the minimum non-null
    `reduction_sequence_position` among the program's `ASSIGNED` rows, and it is
    evaluated before check 42's statutory minimum, so a notice aimed at position 2
    with an also-illegal `notice_days` reports the sequence violation. §3.11's
    statutory lengths are per `tenure_status` — 30 days for an `ADJUNCT`, 90 for
    `NON_TENURE_TRACK` — and issuing a notice removes the load from
    `assigned_pool_fte`, which renumbers the queue from 1 with no gap.

    Design: Corner/errors/notices_follow_the_waterfall_order_and_the_statutory_minimum
    """
    hr = make_hr_partner_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_nonviable_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_id = program["id"]
    a1 = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-ADJ-1",
        tenure_status="ADJUNCT",
        fte=0.25,
        annual_salary_cents=4000000,
    )
    a2 = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-NTT-1",
        tenure_status="NON_TENURE_TRACK",
        fte=1.00,
        annual_salary_cents=7200000,
    )

    def read_appointments():
        rows, meta = validate_paginated(
            api.list_faculty_appointments(
                program_id, hr, params={"limit": 10, "offset": 0}
            )
        )
        return {row["id"]: row for row in rows}, meta

    # No teach-out plan, so no guaranteed sections shield any load: the whole
    # assigned pool is reducible and both appointments are funded.
    before = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        before,
        baseline=1.25,
        assigned_pool=1.25,
        retained=0.00,
        reducible=1.25,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=1857534,
        deferred=0.00,
        active=1.25,
    )
    seeded, _meta = read_appointments()
    assert seeded[a1["id"]]["notice_pay_cents"] == 82192
    assert seeded[a2["id"]]["notice_pay_cents"] == 1775342
    assert seeded[a1["id"]]["reduction_sequence_position"] == 1
    assert seeded[a2["id"]]["reduction_sequence_position"] == 2

    # Priority 41 outranks priority 42: a2 holds position 2, and its notice_days 5
    # is also below the 90-day NON_TENURE_TRACK minimum.
    validate_error(
        api.transition_faculty_appointment(
            a2["id"], factories.issue_notice_payload(5), hr
        ),
        ERR_REDUCTION_SEQUENCE_VIOLATION,
        409,
    )
    unchanged, _meta = read_appointments()
    assert unchanged[a2["id"]]["state"] == "ASSIGNED"
    assert unchanged[a2["id"]]["notice_days"] is None
    assert unchanged[a2["id"]]["notice_issued_at"] is None

    # a1 IS the minimum position, so the sequence check passes and the length
    # check decides: 29 is one day below the ADJUNCT minimum of 30.
    validate_error(
        api.transition_faculty_appointment(
            a1["id"], factories.issue_notice_payload(29), hr
        ),
        ERR_TENURE_NOTICE_TOO_SHORT,
        422,
    )
    unchanged, _meta = read_appointments()
    assert unchanged[a1["id"]]["state"] == "ASSIGNED"
    assert unchanged[a1["id"]]["notice_days"] is None

    noticed = validate_success(
        api.transition_faculty_appointment(
            a1["id"], factories.issue_notice_payload(30), hr
        )
    )
    assert noticed["state"] == "NOTICE_ISSUED"
    assert noticed["notice_days"] == 30
    assertions.assert_instant_equals(
        noticed["notice_issued_at"],
        constants.CLOCK_STARTUP_DEFAULT,
        "a1.notice_issued_at",
    )

    promoted, promoted_meta = read_appointments()
    assert promoted_meta["total_count"] == 2
    assert promoted[a2["id"]]["reduction_sequence_position"] == 1, (
        "the queue renumbered from 1 with no gap"
    )
    assert promoted[a1["id"]]["reduction_sequence_position"] is None, (
        "a1 left the ASSIGNED pool, so it is no longer a funded candidate"
    )

    # The exact call refused at the start now succeeds because the queue moved.
    second_notice = validate_success(
        api.transition_faculty_appointment(
            a2["id"], factories.issue_notice_payload(90), hr
        )
    )
    assert second_notice["state"] == "NOTICE_ISSUED"
    assert second_notice["notice_days"] == 90
    assert second_notice["notice_pay_cents"] == 1775342

    after = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        after,
        baseline=1.25,
        assigned_pool=0.00,
        retained=0.00,
        reducible=0.00,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=0,
        deferred=0.00,
        active=1.25,
        reassigned=0.00,
        separated=0.00,
    )


def test_an_unfundable_reduction_blocks_effectuation_until_the_fte_is_retained(api):
    """One unfundable appointment blocks both effectuation and its own notice.

    §3.11 tests the severance cap before an appointment is taken, so a TENURED
    appointment whose notice pay alone exceeds the cap is never funded: the walk
    stops before position 1 is handed out, the liability stays 0 and `deferred_fte`
    holds the full reducible amount. That single number blocks the effectuation
    (check 33) and the notice (check 41's null-position branch). Retention empties
    the assigned pool, which drives `deferred_fte` to 0.00 without spending a cent.

    Design: Corner/errors/an_unfundable_reduction_blocks_effectuation_until_the_fte_is_retained
    """
    hr = make_hr_partner_headers()
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)
    program = fixtures.create_nonviable_program(
        api, code="HIST-BA", name="History BA", department_code="HIST"
    )
    program_id = program["id"]
    a1 = fixtures.create_appointment(
        api,
        program_id,
        faculty_number="F-TEN-1",
        tenure_status="TENURED",
        fte=1.00,
        annual_salary_cents=12000000,
    )

    ctx = fixtures.carry_cycle_to_response_submitted(api, program=program)
    fixtures.set_clock(api, fixtures.CLOCK_AT_RATIFICATION)
    fixtures.propose_decision(api, ctx, "DISCONTINUATION")
    fixtures.ratify_decision(api, ctx)
    decision_id = ctx.decision["id"]
    fixtures.acknowledge_all_notifications(api, decision_id)
    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    fixtures.submit_plan(api, ctx)
    approved = fixtures.approve_plan(api, ctx)
    assert approved["state"] == "APPROVED"

    unfunded = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        unfunded,
        baseline=1.00,
        assigned_pool=1.00,
        retained=0.00,
        reducible=1.00,
        severance_cap_cents=constants.FIXTURE_A_SEVERANCE_CAP_CENTS,
        liability_cents=0,
        deferred=1.00,
        active=1.00,
    )
    appointments, _meta = validate_paginated(
        api.list_faculty_appointments(program_id, hr, params={"limit": 10, "offset": 0})
    )
    row = {item["id"]: item for item in appointments}[a1["id"]]
    assert row["notice_pay_cents"] == 12000000
    assert row["reduction_sequence_position"] is None, (
        "the cap check broke the loop before position 1 was assigned"
    )

    # Every other effectuation precondition holds, so this is the fiscal refusal.
    validate_error(
        api.transition_decision_record(
            decision_id, factories.effectuate_payload(), coordinator
        ),
        ERR_SEVERANCE_CAP_EXCEEDED,
        409,
    )
    blocked = fixtures.read_decision(api, decision_id)
    assert blocked["state"] == "RATIFIED"
    assert blocked["effectuated_at"] is None
    assertions.assert_axes(
        fixtures.read_program(api, program_id), lifecycle_state="TEACH_OUT_PENDING"
    )

    # A null position is never the minimum position, even for the only ASSIGNED
    # row, and even when notice_days meets the TENURED minimum exactly.
    validate_error(
        api.transition_faculty_appointment(
            a1["id"], factories.issue_notice_payload(365), hr
        ),
        ERR_REDUCTION_SEQUENCE_VIOLATION,
        409,
    )

    retained = validate_success(
        api.transition_faculty_appointment(a1["id"], factories.retain_payload(), hr)
    )
    assert retained["state"] == "TEACH_OUT_RETAINED"

    funded = fixtures.read_program(api, program_id)
    assertions.assert_waterfall(
        funded,
        baseline=1.00,
        assigned_pool=0.00,
        retained=0.00,
        reducible=0.00,
        liability_cents=0,
        deferred=0.00,
        active=1.00,
    )

    effectuated = validate_success(
        api.transition_decision_record(
            decision_id, factories.effectuate_payload(), coordinator
        )
    )
    assert effectuated["state"] == "EFFECTUATED"
    assertions.assert_instant_equals(
        effectuated["effectuated_at"],
        fixtures.CLOCK_AT_RATIFICATION,
        "decision.effectuated_at",
    )
    assertions.assert_axes(
        fixtures.read_program(api, program_id),
        lifecycle_state="TEACH_OUT_ACTIVE",
        catalog_status="ADMISSIONS_CLOSED",
    )

    final_decision = fixtures.read_decision(api, decision_id)
    assert final_decision["notification_count"] == 2
    assert final_decision["unacknowledged_notification_count"] == 0
