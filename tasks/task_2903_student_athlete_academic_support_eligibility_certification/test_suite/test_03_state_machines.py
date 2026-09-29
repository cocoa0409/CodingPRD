"""Declared transitions, initial states, terminal lockdown and cascades.

Each test drives one entity's status machine through the public status
endpoints and then re-reads every row the transition was supposed to touch, so
that a cascade that fired in the wrong direction is visible.
"""

from test_helpers import (
    assert_benchmark,
    assert_close,
    assert_common_fields,
    assert_missed_class_budget_conserved,
    assert_null,
    assert_tutor_capacity_conserved,
    created,
    error,
    factories,
    fixtures,
    ok,
    page,
)
from test_helpers.api_errors import (
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOTIFICATION_LEAD_TIME_VIOLATION,
)
from test_helpers.constants import (
    ASSIGN_ACTION_ACTIVATE,
    ASSIGN_ACTIVE,
    ASSIGN_TERMINATED,
    AUDIT_AT_ENTRY,
    BENCHMARK_FAIL,
    CERT_DRAFT,
    CERT_TYPE_INITIAL,
    ELIGIBILITY_NOT_CERTIFIED,
    ENROLLMENT_DROPPED,
    EVENT_ACTION_APPROVE_TRAVEL,
    EVENT_SCHEDULED,
    EVENT_TRAVEL_APPROVED,
    EVENT_TYPE_REGULAR_SEASON,
    FAILURE_GPA,
    MCR_ACTION_CANCEL,
    MCR_ACTION_NOTIFY,
    MCR_CANCELLED,
    MCR_DRAFT,
    OUTCOME_DROP,
    REASON_ENROLLMENT_DROPPED,
    REASON_SPECIALIST_REQUEST,
    TUTOR_ACTION_REINSTATE,
    TUTOR_ACTION_SUSPEND,
    TUTOR_TERMINATED,
    TUTOR_TRAINED,
)
from test_helpers.test_users import (
    ADVISOR,
    CERT_OFFICER,
    CERT_OFFICER_REQUESTER,
    OPERATIONS,
    REGISTRAR,
    SPECIALIST,
)


def test_approve_travel_moves_scheduled_event_to_travel_approved(api):
    """PRD 3.8: "The event is created `SCHEDULED` with `charged_units_total` of 0
    and that derived multiplier."

    PRD 3.8: "Approving travel takes the event `SCHEDULED → TRAVEL_APPROVED` and
    requires the event's term to still be open; only from `TRAVEL_APPROVED` may
    missed-class requests be filed."

    Design: Corner/state_machines/approve_travel_moves_event_to_travel_approved
    """
    ctx = fixtures.catalogue(api, term_count=1, clock="2026-09-01T00:00:00Z")

    scheduled = created(
        api.create_event(
            factories.event(
                ctx.term_id,
                "2026-09-14T08:00:00Z",
                "2026-09-15T00:00:00Z",
                sport_code="WBB",
                event_type=EVENT_TYPE_REGULAR_SEASON,
            ),
            OPERATIONS,
        )
    )
    assert scheduled["status"] == EVENT_SCHEDULED
    assert_close(scheduled["charged_units_total"], 0.0)
    assert_close(scheduled["missed_class_unit_multiplier"], 1.0)
    assert_common_fields(scheduled, expect_version=1)

    approved = ok(
        api.event_status(
            scheduled["id"],
            factories.action(EVENT_ACTION_APPROVE_TRAVEL),
            OPERATIONS,
        )
    )
    assert approved["status"] == EVENT_TRAVEL_APPROVED
    assert_close(approved["missed_class_unit_multiplier"], 1.0)
    assert_close(approved["charged_units_total"], 0.0)
    assert approved["version"] == 2


def test_new_certification_is_created_in_draft_and_undecided(api):
    """PRD 3.4: "Creation puts the certification in `DRAFT` and freezes the
    academic picture onto it"

    PRD 3.4: "`requested_by_user_id` is set to the creating operator's
    `X-User-ID`, `decided_by_user_id` and `decided_at` remain null,
    `credit_relief_applied` is 0, and the resolved variant is stored in
    `audit_variant`."

    PRD 3.4: "the grade-point test compares `cumulative_gpa` against a
    provisional floor of 1.80 rather than the program's `min_progress_gpa`"

    PRD 3.4: "`benchmark_result` is `PASS` exactly when that provisional
    grade-point test passes."

    PRD 3.3: "an `INITIAL` certification resolves to `CATALOG_AT_ENTRY`"

    Design: Corner/state_machines/new_certification_starts_in_draft
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", CERT_OFFICER)
    term = fixtures.make_term(api, index=1, catalog_year=2026)
    student = fixtures.make_student(
        api,
        full_name="Sam Thirtyseven",
        sport_code="TRACK",
        entry_term_index=1,
        entry_catalog_year=2026,
    )

    row = created(
        api.create_certification(
            factories.certification(
                student["id"],
                term["id"],
                student["version"],
                certification_type=CERT_TYPE_INITIAL,
            ),
            CERT_OFFICER,
        )
    )

    assert row["status"] == CERT_DRAFT
    assert_null(row, "decided_by_user_id", "decided_at")
    assert row["requested_by_user_id"] == CERT_OFFICER_REQUESTER
    assert_close(row["credit_relief_applied"], 0.0)

    assert row["audit_variant"] == AUDIT_AT_ENTRY
    assert_close(row["degree_applicable_credits_counted"], 0.0)
    assert_close(row["progress_pct"], 0.0)
    assert_close(row["required_progress_pct"], 0.0)
    assert_close(row["gpa_at_certification"], 0.0)
    assert row["completed_full_time_terms_counted"] == 0
    assert_benchmark(row, BENCHMARK_FAIL, [FAILURE_GPA])

    refreshed = fixtures.read_student(api, student["id"])
    assert refreshed["eligibility_state"] == ELIGIBILITY_NOT_CERTIFIED


def test_reinstate_on_terminated_tutor_is_rejected(api):
    """PRD 3.7: "From `SUSPENDED` the tutor may instead be moved to
    `TERMINATED`, which is terminal: the tutor accepts no further transitions and
    may not be named on any new assignment."

    PRD 3.7: "the system writes `training_completed_term_index` from that term's
    ordinal and `training_valid_through_term_index` as that ordinal plus the
    three-term validity span minus one — that is, the ordinal plus two, so
    training completed in term 5 remains valid through terms 5, 6 and 7."

    Design: Corner/state_machines/terminated_tutor_admits_no_further_transition
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z", SPECIALIST)
    term = fixtures.make_term(api, index=1)
    tutor = fixtures.make_trained_tutor(
        api, term["id"], subject_codes=["SOCI"], full_name="Tomas Terminal"
    )
    assert tutor["status"] == TUTOR_TRAINED

    fixtures.tutor_action(api, tutor["id"], TUTOR_ACTION_SUSPEND)
    terminated = ok(
        api.tutor_status(
            tutor["id"],
            factories.terminate(terminated_reason=REASON_SPECIALIST_REQUEST),
            SPECIALIST,
        )
    )
    assert terminated["status"] == TUTOR_TERMINATED

    error(
        api.tutor_status(
            tutor["id"], factories.action(TUTOR_ACTION_REINSTATE), SPECIALIST
        ),
        ERR_INVALID_STATE_TRANSITION,
    )

    refreshed = fixtures.read_tutor(api, tutor["id"])
    assert refreshed["status"] == TUTOR_TERMINATED
    assert refreshed["penalty_points"] == 0
    assert refreshed["training_completed_term_index"] == 1
    assert refreshed["training_valid_through_term_index"] == 3


def test_second_activate_on_active_assignment_is_rejected(api):
    """PRD 3.7: "Activating an assignment takes it `PROPOSED → ACTIVE` and
    additionally requires the tutor to be `TRAINED` and the referenced enrollment
    to still be `ENROLLED`. On activation the tutor's `assigned_weekly_hours`
    increases by the assignment's `weekly_hours`"

    PRD 2.7: "it covers every attempt made from a terminal state and every repeat
    of an already-applied action"

    PRD 2.10: "For every tutor, `assigned_weekly_hours` equals the sum of
    `weekly_hours` over that tutor's assignments whose status is `ACTIVE` — no
    more and no less — after every assignment transition, every cascade and every
    tutor status change."

    Design: Corner/state_machines/second_activate_on_active_assignment_rejected
    """
    ctx = fixtures.tutoring_world(
        api, clock="2026-09-01T00:00:00Z", weekly_hours=2.0, subject_code="SOCI"
    )
    assert ctx.assignment["status"] == ASSIGN_ACTIVE
    assert_close(ctx.tutor["assigned_weekly_hours"], 2.0)

    error(
        api.assignment_status(
            ctx.assignment_id, factories.action(ASSIGN_ACTION_ACTIVATE), SPECIALIST
        ),
        ERR_INVALID_STATE_TRANSITION,
    )

    assignment = ok(api.get_assignment(ctx.assignment_id, SPECIALIST))
    assert assignment["status"] == ASSIGN_ACTIVE
    assert assignment["suspension_count"] == 0

    tutor = fixtures.read_tutor(api, ctx.tutor_id)
    assert_close(tutor["assigned_weekly_hours"], 2.0)

    rows, _ = page(api.list_assignments(SPECIALIST, {"tutor_id": ctx.tutor_id}))
    assert_tutor_capacity_conserved(tutor, rows)


def test_notify_instructor_six_days_ahead_rejected(api):
    """PRD 3.8: "notification must occur at least 7 days before the event's
    `departure_at`, with the boundary inclusive, so notification exactly 7 days
    ahead is accepted and notification 6 days and 23 hours ahead is rejected with
    `ERR_NOTIFICATION_LEAD_TIME_VIOLATION`."

    Design: Corner/state_machines/notify_instructor_six_days_ahead_rejected
    """
    ctx = fixtures.travel_world(
        api,
        clock="2026-09-01T00:00:00Z",
        meeting_days=[1],
        meeting_start_minute_utc=600,
        meeting_duration_minutes=50,
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-15T00:00:00Z",
        sport_code="WBB",
        event_type=EVENT_TYPE_REGULAR_SEASON,
    )

    request = fixtures.make_request(api, ctx.event_id, ctx.enrollment_id)
    assert request["status"] == MCR_DRAFT
    assert_close(request["missed_units"], 0.83)

    # 2026-09-07T08:00:00Z is exactly seven days ahead; one hour later is not.
    fixtures.set_clock(api, "2026-09-07T09:00:00Z", ADVISOR)

    error(
        api.missed_class_request_status(
            request["id"], factories.action(MCR_ACTION_NOTIFY), ADVISOR
        ),
        ERR_NOTIFICATION_LEAD_TIME_VIOLATION,
    )

    refreshed = ok(api.get_missed_class_request(request["id"], ADVISOR))
    assert refreshed["status"] == MCR_DRAFT
    assert_null(refreshed, "notified_at", "acknowledgement_deadline_at")
    assert_close(refreshed["missed_units"], 0.83)

    student = fixtures.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 0.83)
    assert_missed_class_budget_conserved(student)


def test_cancel_on_already_cancelled_request_is_rejected(api):
    """PRD 3.8: "`CANCELLED` and `VOIDED` are the request's two terminal states,
    and the void produced by an event cancellation runs precisely the same release
    chain as an explicit cancellation."

    PRD 3.8: "the student's `missed_class_units_charged` decreases by the request's
    `missed_units` and `missed_class_units_remaining` increases by the same amount,
    restoring the identity that allowance equals charged plus remaining exactly;
    the event's `charged_units_total` decreases by the same `missed_units`"

    PRD 2.7: "it covers every attempt made from a terminal state and every repeat
    of an already-applied action"

    Design: Corner/state_machines/cancel_already_cancelled_request_returns_invalid_state_transition
    """
    ctx = fixtures.travel_world(
        api,
        clock="2026-09-01T00:00:00Z",
        meeting_days=[1],
        meeting_start_minute_utc=600,
        meeting_duration_minutes=50,
        departure_at="2026-09-14T08:00:00Z",
        return_at="2026-09-15T00:00:00Z",
        sport_code="WBB",
        event_type=EVENT_TYPE_REGULAR_SEASON,
    )

    request = fixtures.make_request(api, ctx.event_id, ctx.enrollment_id)
    assert request["status"] == MCR_DRAFT
    assert_close(request["missed_units"], 0.83)

    cancelled = ok(
        api.missed_class_request_status(
            request["id"], factories.action(MCR_ACTION_CANCEL), ADVISOR
        )
    )
    assert cancelled["status"] == MCR_CANCELLED

    student = fixtures.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 0.0)
    assert_close(student["missed_class_units_remaining"], 9.0)
    assert_missed_class_budget_conserved(student)

    event = ok(api.get_event(ctx.event_id, OPERATIONS))
    assert_close(event["charged_units_total"], 0.0)

    error(
        api.missed_class_request_status(
            request["id"], factories.action(MCR_ACTION_CANCEL), ADVISOR
        ),
        ERR_INVALID_STATE_TRANSITION,
    )

    # The refused replay releases nothing a second time.
    refreshed = ok(api.get_missed_class_request(request["id"], ADVISOR))
    assert refreshed["status"] == MCR_CANCELLED
    assert_close(refreshed["missed_units"], 0.83)

    student = fixtures.read_student(api, ctx.student_id)
    assert_close(student["missed_class_units_charged"], 0.0)
    assert_close(student["missed_class_units_remaining"], 9.0)
    assert_missed_class_budget_conserved(student)

    event = ok(api.get_event(ctx.event_id, OPERATIONS))
    assert_close(event["charged_units_total"], 0.0)


def test_dropping_an_enrollment_terminates_its_active_assignment(api):
    """PRD 3.2: "`DROP` moves an `ENROLLED` row to `DROPPED`, and `WITHDRAW` moves
    either an `ENROLLED` or an `INCOMPLETE` row to `WITHDRAWN`; both set
    `earned_credit_hours` to 0, `DROP` additionally zeroes
    `degree_applicable_credits_counted`, and both run the same tutoring cascade —
    every tutor assignment on that enrollment whose status is `PROPOSED` or
    `ACTIVE` moves to `TERMINATED` with `terminated_reason` set to
    `ENROLLMENT_DROPPED`, processed in `created_at` ascending order, each formerly
    `ACTIVE` assignment releasing its `weekly_hours` from the tutor's
    `assigned_weekly_hours`."

    PRD 2.10: "For every tutor, `assigned_weekly_hours` equals the sum of
    `weekly_hours` over that tutor's assignments whose status is `ACTIVE` — no
    more and no less — after every assignment transition, every cascade and every
    tutor status change."

    PRD 3.2: "Enrollments in `ENROLLED`, `DROPPED`, `WITHDRAWN` or `INCOMPLETE`
    contribute to neither aggregate."

    Design: Corner/state_machines/enrollment_drop_cascades_assignment_termination
    """
    ctx = fixtures.tutoring_world(
        api, clock="2026-09-01T00:00:00Z", weekly_hours=2.0, subject_code="SOCI"
    )
    assert ctx.assignment["status"] == ASSIGN_ACTIVE
    assert_close(ctx.tutor["assigned_weekly_hours"], 2.0)

    dropped = ok(
        api.record_outcome(
            ctx.enrollment_id, factories.action(OUTCOME_DROP), REGISTRAR
        )
    )
    assert dropped["status"] == ENROLLMENT_DROPPED
    assert_close(dropped["earned_credit_hours"], 0.0)
    assert_close(dropped["degree_applicable_credits_counted"], 0.0)

    assignment = ok(api.get_assignment(ctx.assignment_id, SPECIALIST))
    assert assignment["status"] == ASSIGN_TERMINATED
    assert assignment["terminated_reason"] == REASON_ENROLLMENT_DROPPED

    tutor = fixtures.read_tutor(api, ctx.tutor_id)
    assert_close(tutor["assigned_weekly_hours"], 0.0)
    assert tutor["status"] == TUTOR_TRAINED

    rows, _ = page(api.list_assignments(SPECIALIST, {"tutor_id": ctx.tutor_id}))
    assert_tutor_capacity_conserved(tutor, rows)

    student = fixtures.read_student(api, ctx.student_id)
    assert_close(student["cumulative_gpa"], 0.0)
    assert student["completed_full_time_terms"] == 0
