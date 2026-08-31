"""Seat placement: the enrolment ladder, the hold window and the seat pool."""

import pytest

from test_helpers import (
    IC,
    PD,
    ApiErrorId,
    UNUSED_UUIDS,
    api_client,
    assert_cohort_seat_pool,
    assert_enrollment,
    confirm_enrollment,
    cohort_version,
    create_assessed_participant,
    create_counseling_referral,
    create_meeting_space,
    create_open_cohort,
    create_participant,
    enroll,
    make_participant_headers,
    read_cohort,
    read_enrollment,
    read_participant,
    record_assessment,
    run_cadence_sweep,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_enrollment_naming_an_unknown_cohort_is_not_found():
    """PRD 2.5: "Every entity identifier named inside the request body resolves to
    an existing record — otherwise the corresponding not-found error (404). This
    rung guards enrollment creation, counselling-referral creation,
    counselling-referral assignment, companion-match creation, cohort creation,
    remembrance-event creation, invitation creation, funding-allocation creation
    and grant-report creation."

    Design: Corner/entities/enrollment_create_with_unknown_cohort_id_in_body_returns_cohort_not_found
    """
    set_clock()
    space, cohort = create_open_cohort(name="Real Group", loss_type="SUDDEN_DEATH")
    participant = create_assessed_participant(
        loss_type="SUDDEN_DEATH", grief_severity=10, isolation_index=4,
        functional_impairment=4)

    validate_error(
        api_client.create_enrollment(
            {"participant_id": participant["id"],
             "cohort_id": UNUSED_UUIDS["cohort"],
             "expected_cohort_version": cohort["version"]}, IC),
        ApiErrorId.ERR_COHORT_NOT_FOUND.value, 404)

    rows, meta = validate_paginated(
        api_client.list_enrollments(IC, params={"participant_id": participant["id"]}))
    assert meta["total_count"] == 0


def test_confirming_an_already_confirmed_seat_is_an_invalid_state():
    """PRD 3.4: "Confirming converts the hold into a real seat:
    `HELD → CONFIRMED`, allowed only while the cohort is still in
    `OPEN_ENROLLMENT` and only while the logical clock is at or before
    `held_until`. One unit moves out of `seats_held` and into `seats_filled` —
    `seats_open` does not change — and the cohort's `version` increases by one.
    Both an `IntakeCoordinator` and the `Participant` themselves may confirm."

    Design: Corner/state_machines/enrollment_confirm_twice_second_call_returns_invalid_state
    """
    set_clock()
    space, cohort = create_open_cohort(name="Idempotency Group")
    participant = create_assessed_participant(loss_type=cohort["loss_type"])
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])
    confirm_enrollment(enrollment["id"])

    validate_error(api_client.confirm_enrollment(enrollment["id"], IC),
                   ApiErrorId.ERR_INVALID_STATE.value, 409)

    assert read_enrollment(enrollment["id"])["status"] == "CONFIRMED"
    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_filled"] == 1, "the refused confirm must not double-count"
    assert refreshed["seats_held"] == 0
    assert refreshed["seats_open"] == 3
    assert_cohort_seat_pool(refreshed)


def test_confirming_an_unknown_enrollment_is_not_found():
    """PRD 2.5: "Every resource named by a path segment exists, validated from left
    to right, so the leftmost missing segment determines the reported error —
    otherwise the corresponding not-found error (404)."

    Design: Corner/errors/enrollment_confirm_with_unknown_id_returns_enrollment_not_found
    """
    set_clock()
    validate_error(
        api_client.confirm_enrollment(UNUSED_UUIDS["enrollment"], IC),
        ApiErrorId.ERR_ENROLLMENT_NOT_FOUND.value, 404)


def test_enrolment_without_a_needs_assessment_is_refused():
    """PRD 3.4: "The clinical safety gates come first: a participant with no
    `NEEDS` assessment on file cannot be placed in a group at all, and the attempt
    is refused with `ERR_ASSESSMENT_REQUIRED`; and when that participant's most
    recent `NEEDS` assessment carried `suicidality_flag` true, group placement
    additionally requires that they already have an open counselling referral,
    meaning one in status `WAITLISTED` or `ASSIGNED`, without which the placement
    is refused with `ERR_SUICIDALITY_REQUIRES_COUNSELING`."

    Design: Corner/validations/enrollment_without_a_needs_assessment_returns_assessment_required
    """
    set_clock()
    space, cohort = create_open_cohort(name="Safety Gate Group",
                                       loss_type="ANTICIPATED_ILLNESS")
    participant = create_participant(loss_type="ANTICIPATED_ILLNESS")

    validate_error(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort["version"]}, IC),
        ApiErrorId.ERR_ASSESSMENT_REQUIRED.value, 422)

    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_open"] == 4
    assert refreshed["seats_held"] == 0
    assert read_participant(participant["id"])["service_status"] == "INTAKE"


def test_suicidality_requires_an_open_counselling_referral_before_group_placement():
    """PRD 3.4: "The clinical safety gates come first: a participant with no
    `NEEDS` assessment on file cannot be placed in a group at all, and the attempt
    is refused with `ERR_ASSESSMENT_REQUIRED`; and when that participant's most
    recent `NEEDS` assessment carried `suicidality_flag` true, group placement
    additionally requires that they already have an open counselling referral,
    meaning one in status `WAITLISTED` or `ASSIGNED`, without which the placement
    is refused with `ERR_SUICIDALITY_REQUIRES_COUNSELING`."

    Design: Corner/validations/enrollment_with_suicidality_and_no_open_counseling_referral_is_refused
    """
    set_clock()
    space, cohort = create_open_cohort(name="Suicide Loss Group",
                                       loss_type="SUICIDE")
    participant = create_assessed_participant(
        loss_type="SUICIDE", instrument="PG13", grief_severity=30,
        isolation_index=10, functional_impairment=10, suicidality_flag=True)
    assert participant["composite_need_index"] == pytest.approx(85.00, abs=0.001)
    assert participant["risk_tier"] == "HIGH"

    validate_error(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort["version"]}, IC),
        ApiErrorId.ERR_SUICIDALITY_REQUIRES_COUNSELING.value, 422)

    counselling = create_counseling_referral(
        participant["id"], requested_minutes_per_week=60, urgency="URGENT",
        required_specialty="SUICIDE")
    assert counselling["queue_priority"] == pytest.approx(74.75, abs=0.001)

    enrollment = validate_success(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort["version"]}, IC), 201)
    assert enrollment["status"] == "HELD"
    assert read_cohort(cohort["id"])["seats_held"] == 1


def test_enrolment_into_a_cohort_of_a_different_loss_type_is_refused():
    """PRD 3.4: "Next comes attribute agreement: the cohort's `loss_type` must
    equal the participant's `loss_type` exactly, otherwise
    `ERR_LOSS_TYPE_MISMATCH`."

    Design: Corner/validations/enrollment_into_a_cohort_of_a_different_loss_type_returns_loss_type_mismatch
    """
    set_clock()
    space, cohort = create_open_cohort(name="Pediatric Group", loss_type="PEDIATRIC")
    participant = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")

    validate_error(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort["version"]}, IC),
        ApiErrorId.ERR_LOSS_TYPE_MISMATCH.value, 422)
    assert read_cohort(cohort["id"])["seats_open"] == 4


def test_enrolment_into_a_cohort_with_no_open_seat_is_refused():
    """PRD 3.4: "Then capacity and uniqueness: the cohort must have at least one
    seat in `seats_open`, otherwise `ERR_COHORT_FULL`; and the same participant
    must not already hold a seat in the same cohort in status `HELD`, `CONFIRMED`,
    `ATTENDING` or `COMPLETED`, otherwise `ERR_DUPLICATE_ENROLLMENT` — note that a
    previously `WITHDRAWN` or `EXPIRED` seat does not block a fresh placement."

    Design: Corner/validations/enrollment_into_a_full_cohort_returns_cohort_full
    """
    set_clock()
    space, cohort = create_open_cohort(name="One Seat Group", seats_total=1,
                                       min_viable_enrollment=1)
    first = create_assessed_participant(loss_type=cohort["loss_type"])
    second = create_assessed_participant(loss_type=cohort["loss_type"])
    enroll(first["id"], cohort["id"], cohort["version"])

    mid = read_cohort(cohort["id"])
    assert mid["seats_open"] == 0

    validate_error(
        api_client.create_enrollment(
            {"participant_id": second["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": mid["version"]}, IC),
        ApiErrorId.ERR_COHORT_FULL.value, 409)

    assert read_cohort(cohort["id"])["seats_held"] == 1
    rows, meta = validate_paginated(
        api_client.list_enrollments(IC, params={"cohort_id": cohort["id"]}))
    assert meta["total_count"] == 1


def test_a_second_live_seat_for_the_same_pair_is_a_duplicate():
    """PRD 3.4: "Then capacity and uniqueness: the cohort must have at least one
    seat in `seats_open`, otherwise `ERR_COHORT_FULL`; and the same participant
    must not already hold a seat in the same cohort in status `HELD`, `CONFIRMED`,
    `ATTENDING` or `COMPLETED`, otherwise `ERR_DUPLICATE_ENROLLMENT` — note that a
    previously `WITHDRAWN` or `EXPIRED` seat does not block a fresh placement."

    Design: Corner/validations/duplicate_enrollment_for_the_same_participant_and_cohort_is_refused
    """
    set_clock()
    space, cohort = create_open_cohort(name="Duplicate Group")
    participant = create_assessed_participant(loss_type=cohort["loss_type"])
    enroll(participant["id"], cohort["id"], cohort["version"])

    validate_error(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort_version(cohort["id"])}, IC),
        ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value, 409)

    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_held"] == 1
    assert refreshed["seats_open"] == 3


def test_attendance_ratio_is_recomputed_to_four_decimal_places():
    """PRD 3.4: "Attendance is logged by an `IntakeCoordinator` supplying a
    `sessions_delta`, which is added to the enrollment's `sessions_attended`."
    PRD 3.4: "Every attendance write recomputes `attendance_ratio` as
    `sessions_attended` divided by the cohort's `sessions_total`, rounded half up
    to four decimal places."

    Design: Corner/calculations/enrollment_attendance_ratio_is_stored_to_four_decimal_places
    """
    set_clock()
    space, cohort = create_open_cohort(name="Precision Group", sessions_total=8)
    participant = create_assessed_participant(loss_type=cohort["loss_type"])
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])
    confirm_enrollment(enrollment["id"])

    data = validate_success(api_client.log_attendance(enrollment["id"], 3, IC))
    assert data["sessions_attended"] == 3
    assert data["attendance_ratio"] == pytest.approx(0.3750, abs=0.00001), (
        f"Expected 0.3750, got {data['attendance_ratio']}")
    assert read_enrollment(enrollment["id"])["status"] == "CONFIRMED"
    assert read_participant(participant["id"])["sessions_attended_total"] == 0, (
        "the participant total only moves when the enrollment reaches COMPLETED")


def test_the_sweep_expires_a_hold_only_once_the_seventy_two_hours_have_passed():
    """PRD 3.4: "A successful placement creates an enrollment in status `HELD` and
    answers with HTTP 201. Its `held_until` is stamped seventy-two hours after the
    record's `created_at` — a three-day window in which the family must confirm.
    One unit moves out of `seats_open` and into `seats_held`, the cohort's
    `version` increases by one, and if this is the participant's first live
    enrollment their `service_status` advances `ASSESSED → ACTIVE`."
    PRD 3.4: "If the hold window lapses instead, the operational sweep expires the
    seat: `HELD → EXPIRED` once the logical clock passes `held_until`, moving one
    unit out of `seats_held` and back into `seats_open` and incrementing the
    cohort's `version`."

    Design: Corner/state_machines/ops_run_expires_held_enrollment_after_the_seventy_two_hour_window
    """
    set_clock()
    space, cohort = create_open_cohort(name="Hold Window Group")
    participant = create_assessed_participant(loss_type=cohort["loss_type"])
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])
    assert enrollment["held_until"] == "2026-09-04T00:00:00.000Z", (
        f"Expected a 72-hour hold window, got {enrollment['held_until']}")

    set_clock("2026-09-03T23:59:00Z")
    early = run_cadence_sweep()
    assert early["enrollments_expired"] == 0, "the hold has not lapsed yet"
    assert read_enrollment(enrollment["id"])["status"] == "HELD"

    set_clock("2026-09-04T00:01:00Z")
    late = run_cadence_sweep()
    assert late["enrollments_expired"] == 1

    assert read_enrollment(enrollment["id"])["status"] == "EXPIRED"
    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_held"] == 0
    assert refreshed["seats_open"] == 4
    assert_cohort_seat_pool(refreshed)


def test_withdrawing_an_expired_seat_is_already_terminal():
    """PRD 3.4: "`COMPLETED` and `CANCELLED` are terminal for a cohort, and
    `COMPLETED`, `WITHDRAWN` and `EXPIRED` are terminal for an enrollment; any
    transition requested out of a terminal state is refused with
    `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/enrollment_withdraw_from_a_terminal_expired_enrollment_returns_already_terminal
    """
    set_clock()
    space, cohort = create_open_cohort(name="Terminal Group")
    participant = create_assessed_participant(loss_type=cohort["loss_type"])
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])

    set_clock("2026-09-05T00:00:00Z")
    run_cadence_sweep()

    validate_error(
        api_client.withdraw_enrollment(
            enrollment["id"], {"withdraw_reason": "PARTICIPANT_REQUEST"}, IC),
        ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)

    refreshed_enrollment = read_enrollment(enrollment["id"])
    assert refreshed_enrollment["status"] == "EXPIRED"
    assert refreshed_enrollment["withdraw_reason"] is None
    refreshed_cohort = read_cohort(cohort["id"])
    assert refreshed_cohort["seats_open"] == 4, "the seat must not be returned twice"
    assert refreshed_cohort["seats_held"] == 0


def test_a_participant_may_not_confirm_another_participants_seat():
    """PRD 2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id` of the
    acting `Participant`; ownership checks compare it against the participant named
    by the path, or against the `participant_id` of the enrollment, invitation or
    anniversary touchpoint named by the path."
    PRD 2.1: "Any of these comparisons failing yields `ERR_NOT_RESOURCE_OWNER` and
    HTTP 403."

    Design: Corner/rbac/participant_cannot_confirm_another_participants_enrollment
    """
    set_clock()
    space, cohort = create_open_cohort(name="Ownership Group")
    owner = create_assessed_participant(loss_type=cohort["loss_type"])
    stranger = create_assessed_participant(loss_type=cohort["loss_type"])
    enrollment = enroll(owner["id"], cohort["id"], cohort["version"])

    validate_error(
        api_client.confirm_enrollment(
            enrollment["id"], make_participant_headers(stranger["id"])),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    data = validate_success(
        api_client.confirm_enrollment(
            enrollment["id"], make_participant_headers(owner["id"])))
    assert data["status"] == "CONFIRMED"
    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_filled"] == 1
    assert refreshed["seats_held"] == 0


def test_enrolment_against_a_forming_cohort_is_refused():
    """PRD 3.4: "Enrolment is also only possible while the cohort is in
    `OPEN_ENROLLMENT`; against a cohort in any other status the attempt is refused
    with `ERR_COHORT_NOT_ENROLLING`."
    PRD 3.4: "A cohort in `FORMING` accepts nobody."

    Design: Difficulty/cross_entity_state_dependency/enrollment_creation_depends_on_cohort_open_enrollment_state
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    cohort = validate_success(
        api_client.create_cohort(
            {"name": "Not Yet Open", "loss_type": "ANTICIPATED_ILLNESS",
             "meeting_space_id": space["id"], "seats_total": 4,
             "min_viable_enrollment": 1, "weekday": "TUE", "start_minute_utc": 600,
             "duration_minutes": 90, "series_start_date": "2026-09-08",
             "sessions_total": 8, "direct_cost_cents": 240_000}, PD), 201)
    assert cohort["status"] == "FORMING"
    participant = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")

    validate_error(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort["version"]}, IC),
        ApiErrorId.ERR_COHORT_NOT_ENROLLING.value, 409)

    refreshed = read_cohort(cohort["id"])
    assert refreshed["status"] == "FORMING"
    assert refreshed["seats_open"] == 4
    assert refreshed["seats_held"] == 0


def test_the_same_enrolment_succeeds_once_the_cohort_opens_for_enrolment():
    """PRD 3.4: "A `ProgramDirector` opens it with a transition into
    `OPEN_ENROLLMENT`, which is permitted from `FORMING` and, for a group that
    failed to fill the first time round, from `UNDERSUBSCRIBED` as well — the
    second path is what makes the cohort lifecycle a cycle rather than a line.
    Either way, the room must be `AVAILABLE`, and the cohort's `version` increases
    by one."
    PRD 3.4: "A successful placement creates an enrollment in status `HELD` and
    answers with HTTP 201. Its `held_until` is stamped seventy-two hours after the
    record's `created_at` — a three-day window in which the family must confirm.
    One unit moves out of `seats_open` and into `seats_held`, the cohort's
    `version` increases by one, and if this is the participant's first live
    enrollment their `service_status` advances `ASSESSED → ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_creation_depends_on_cohort_open_enrollment_state
    """
    set_clock()
    space = create_meeting_space(name="Chapel Room", capacity=20,
                                 turnover_buffer_minutes=30)
    cohort = validate_success(
        api_client.create_cohort(
            {"name": "Not Yet Open", "loss_type": "ANTICIPATED_ILLNESS",
             "meeting_space_id": space["id"], "seats_total": 4,
             "min_viable_enrollment": 1, "weekday": "TUE", "start_minute_utc": 600,
             "duration_minutes": 90, "series_start_date": "2026-09-08",
             "sessions_total": 8, "direct_cost_cents": 240_000}, PD), 201)
    participant = create_assessed_participant(loss_type="ANTICIPATED_ILLNESS")

    validate_error(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": cohort["version"]}, IC),
        ApiErrorId.ERR_COHORT_NOT_ENROLLING.value, 409)

    opened = validate_success(api_client.open_cohort_enrollment(cohort["id"], PD))
    enrollment = validate_success(
        api_client.create_enrollment(
            {"participant_id": participant["id"], "cohort_id": cohort["id"],
             "expected_cohort_version": opened["version"]}, IC), 201)
    assert_enrollment(enrollment)
    assert enrollment["status"] == "HELD"

    refreshed = read_cohort(cohort["id"])
    assert refreshed["status"] == "OPEN_ENROLLMENT"
    assert refreshed["seats_held"] == 1
    assert refreshed["seats_open"] == 3
    assert read_participant(participant["id"])["service_status"] == "ACTIVE"


def test_seat_pool_moves_one_unit_from_open_to_held_then_to_filled():
    """PRD 2.7: "A cohort's seat pool satisfies, at all times, that `seats_total`
    equals `seats_open` plus `seats_held` plus `seats_filled`. A held enrollment
    occupies one unit of `seats_held`; a confirmed or attending enrollment occupies
    one unit of `seats_filled`; every other seat sits in `seats_open`. Every
    enrollment transition that changes which compartment a seat belongs to must
    move exactly one unit and leave the sum untouched."

    Design: Difficulty/compensating_invariant/cohort_seat_pool_conserved_across_hold_confirm_and_withdraw
    """
    set_clock()
    space, cohort = create_open_cohort(name="Seat Conservation Group",
                                       loss_type="PERINATAL", seats_total=4,
                                       min_viable_enrollment=1,
                                       direct_cost_cents=240_000)
    assert cohort["seats_open"] == 4 and cohort["seats_held"] == 0
    assert cohort["seats_filled"] == 0
    assert_cohort_seat_pool(cohort)

    participant = create_assessed_participant(loss_type="PERINATAL")
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])

    after_hold = read_cohort(cohort["id"])
    assert after_hold["seats_held"] == 1
    assert after_hold["seats_open"] == 3
    assert after_hold["seats_filled"] == 0
    assert_cohort_seat_pool(after_hold)

    confirm_enrollment(enrollment["id"])
    after_confirm = read_cohort(cohort["id"])
    assert after_confirm["seats_filled"] == 1
    assert after_confirm["seats_held"] == 0
    assert after_confirm["seats_open"] == 3, "confirming must not touch seats_open"
    assert_cohort_seat_pool(after_confirm)


def test_withdrawing_a_confirmed_seat_restores_the_pool_to_its_opening_split():
    """PRD 3.4: "Withdrawing a single seat is available from `HELD`, `CONFIRMED` or
    `ATTENDING` and records a `withdraw_reason` — one of `PARTICIPANT_REQUEST`,
    `NO_SHOW`, `TRANSFERRED` or `PROGRAM_CANCELLED`."
    PRD 3.4: "Which compartment the seat comes out of depends on where it was: a
    `HELD` seat returns one unit from `seats_held` to `seats_open`, while a
    `CONFIRMED` or `ATTENDING` seat returns one unit from `seats_filled` to
    `seats_open`. In every case the cohort's `version` increases by one."

    Design: Difficulty/compensating_invariant/cohort_seat_pool_conserved_across_hold_confirm_and_withdraw
    """
    set_clock()
    space, cohort = create_open_cohort(name="Seat Conservation Group",
                                       loss_type="PERINATAL", seats_total=4,
                                       min_viable_enrollment=1,
                                       direct_cost_cents=240_000)
    participant = create_assessed_participant(loss_type="PERINATAL")
    enrollment = enroll(participant["id"], cohort["id"], cohort["version"])
    confirm_enrollment(enrollment["id"])

    data = validate_success(
        api_client.withdraw_enrollment(
            enrollment["id"], {"withdraw_reason": "PARTICIPANT_REQUEST"}, IC))
    assert data["status"] == "WITHDRAWN"
    assert data["withdraw_reason"] == "PARTICIPANT_REQUEST"

    refreshed = read_cohort(cohort["id"])
    assert refreshed["seats_total"] == 4
    assert refreshed["seats_open"] == 4
    assert refreshed["seats_held"] == 0
    assert refreshed["seats_filled"] == 0
    assert refreshed["status"] == "OPEN_ENROLLMENT"
    assert_cohort_seat_pool(refreshed)
