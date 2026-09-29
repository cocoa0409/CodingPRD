"""State-machine corners: legal moves, guards, one-shots and terminal states."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    FACILITIES_HEADERS,
    FINANCE_HEADERS,
    REVIEWER_HEADERS,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
    USER_REVIEWER,
    make_producer_headers,
)


def _enrolled_producer_on_a_finished_basic_course(client):
    """An ENROLLED seat on a course whose session has already ended."""
    producer = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    course = fx.publish_course(
        client,
        course_code="TV-101",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    enrollment = fx.enroll(client, producer["id"], course["id"])
    fx.set_clock(client, "2026-08-06T00:00:00Z")
    return producer, course, enrollment


def test_recording_attendance_after_the_session_stamps_the_logical_clock(client):
    """Attendance alone advances the enrollment and grants no competency.

    PRD 3.1: "When `attended` is true the enrollment moves `ENROLLED → ATTENDED`
    and `attended_at` is stamped with the current logical instant."

    PRD 3.1: "Only `PASSED` enrollments feed that tier set — `ENROLLED`,
    `ATTENDED`, `FAILED` and `WITHDRAWN` enrollments contribute nothing."

    PRD 2.5: "Repositioning the clock never retroactively rewrites stored
    timestamps — an attestation's `effective_from`, a slot's `aired_at`, an asset's
    `published_at` and a reservation's `checked_out_at` are all frozen at the
    instant that was current when they were stamped."

    Design: Corner/state_machines/corner_enrollment_attendance_transitions_to_attended
    """
    producer, course, enrollment = _enrolled_producer_on_a_finished_basic_course(client)
    assert enrollment["status"] == "ENROLLED"

    attended = fx.mark_attended(client, enrollment["id"], True)

    assert attended["status"] == "ATTENDED"
    a.assert_instant_equals(attended["attended_at"], "2026-08-06T00:00:00Z", "attended_at")
    a.assert_field_absent_or_null(attended, "practical_score")
    a.assert_field_absent_or_null(attended, "graded_at")

    after_course = a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))
    assert after_course["enrolled_count"] == 1
    assert after_course["passed_count"] == 0

    after_producer = fx.read_producer(client, producer["id"])
    assert after_producer["certification_level"] == "NONE"
    assert after_producer["competency_codes"] == []


def test_grading_an_unattended_enrollment_has_no_transition_to_make(client):
    """Certification cannot be short-circuited by skipping the session.

    PRD 3.1: "A score of at least 80 drives `ATTENDED → PASSED`; a score below 80
    drives `ATTENDED → FAILED`."

    PRD 2.8: "**Transition legality (priority 9)** — `ERR_INVALID_STATE_TRANSITION`,
    409. Applies to every action operation that drives a state machine. Raised when
    the target's current state has no transition for that trigger, including any
    attempt from a terminal state and any second application of a one-shot action."

    Design: Corner/state_machines/corner_grade_before_attendance_returns_invalid_state
    """
    producer, course, enrollment = _enrolled_producer_on_a_finished_basic_course(client)

    response = client.grade_enrollment(
        enrollment["id"], f.grade_payload(95), TRAINER_HEADERS
    )

    a.error_of(response, e.ERR_INVALID_STATE_TRANSITION, 409)
    unchanged = a.data_of(client.get_course_enrollment(enrollment["id"], TRAINER_HEADERS))
    assert unchanged["status"] == "ENROLLED"
    a.assert_field_absent_or_null(unchanged, "practical_score")
    a.assert_field_absent_or_null(unchanged, "graded_at")

    after_producer = fx.read_producer(client, producer["id"])
    assert after_producer["certification_level"] == "NONE"
    assert after_producer["competency_codes"] == []
    after_course = a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))
    assert after_course["passed_count"] == 0
    assert after_course["enrolled_count"] == 1


def _confirmed_studio_booking_for_the_eighth(client):
    """A CONFIRMED 10:00-12:00 booking holding 12962 cents."""
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    resource = fx.create_resource(
        client,
        resource_code="STUDIO-A",
        resource_class="STUDIO_A",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=900000,
    )
    _res, reservation = fx.setup_confirmed_reservation(
        client, producer["id"], resource,
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
    )
    return producer, resource, reservation


def test_checkout_two_hours_early_is_outside_the_one_hour_lead_window(client):
    """The lead boundary is inclusive: 09:00 works for a 10:00 booking, 08:00 does not.

    PRD 3.6: "The `CONFIRMED → CHECKED_OUT` transition requires the producer to
    still be `ACTIVE`, otherwise `ERR_PRODUCER_NOT_ACTIVE` (409), and it is bounded
    on both sides: the logical clock must have reached the reservation's `start_at`
    less a one-hour lead — equipment may be collected up to 3600 seconds early, but
    no earlier — and must still be strictly before the reservation's `end_at`.
    Outside that window the request is refused with `ERR_CHECKOUT_WINDOW_NOT_OPEN`
    (409)."

    PRD 3.6: "A successful checkout stamps `checked_out_at` with the current
    logical instant, records the `condition_notes`, and increments the
    reservation's `version` by 1."

    Design: Corner/state_machines/corner_checkout_before_lead_window_rejected
    """
    producer, resource, reservation = _confirmed_studio_booking_for_the_eighth(client)

    fx.set_clock(client, "2026-08-08T08:00:00Z")
    early = client.checkout_reservation(
        reservation["id"], f.checkout_payload(condition_notes="Early pickup attempt"),
        FACILITIES_HEADERS,
    )

    a.error_of(early, e.ERR_CHECKOUT_WINDOW_NOT_OPEN, 409)
    refused = fx.read_reservation(client, reservation["id"])
    assert refused["status"] == "CONFIRMED"
    a.assert_field_absent_or_null(refused, "checked_out_at")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=12962)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1

    fx.set_clock(client, "2026-08-08T09:00:00Z")
    accepted = fx.checkout_reservation(
        client, reservation["id"], condition_notes="Pickup at the open of the lead window"
    )

    assert accepted["status"] == "CHECKED_OUT"
    a.assert_instant_equals(accepted["checked_out_at"], "2026-08-08T09:00:00Z", "checked_out_at")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=12962)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


def test_a_settled_reservation_accepts_no_further_lifecycle_action(client):
    """Once the money is settled the row has no transition left for any trigger.

    PRD 3.7: "**The clean branch** fires when `damage_observed` is false and drives
    `CHECKED_OUT → SETTLED` directly."

    PRD 2.8: "**Transition legality (priority 9)** — `ERR_INVALID_STATE_TRANSITION`,
    409. Applies to every action operation that drives a state machine. Raised when
    the target's current state has no transition for that trigger, including any
    attempt from a terminal state and any second application of a one-shot action."

    PRD 3.7: "One damage assessment is created in `FILED` status, recording the
    `reservation_id`, the `severity`, the operator's raw `repair_estimate_cents` and
    the `damage_notes`"

    Design: Corner/state_machines/corner_cancel_settled_reservation_rejected_from_terminal_state
    """
    producer, _resource, reservation = _confirmed_studio_booking_for_the_eighth(client)
    fx.set_clock(client, "2026-08-08T10:00:00Z")
    fx.checkout_reservation(client, reservation["id"], condition_notes="Handover clean")
    fx.set_clock(client, "2026-08-08T12:00:00Z")
    settled = fx.return_clean(client, reservation["id"], condition_notes="Returned on time")
    assert settled["status"] == "SETTLED"
    a.assert_cents(settled["deposit_refunded_cents"], 12962, "deposit_refunded_cents")

    a.error_of(
        client.cancel_reservation(
            reservation["id"], f.reservation_cancel_payload(), make_producer_headers(producer["id"])
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    a.error_of(
        client.checkout_reservation(reservation["id"], f.checkout_payload(), FACILITIES_HEADERS),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    a.error_of(
        client.return_reservation(
            reservation["id"],
            f.damaged_return_payload("MINOR", 1000, damage_notes="Reported after settlement"),
            FACILITIES_HEADERS,
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    still = fx.read_reservation(client, reservation["id"])
    assert still["status"] == "SETTLED"
    a.assert_cents(still["deposit_forfeited_cents"], 0, "deposit_forfeited_cents")
    a.assert_cents(still["deposit_refunded_cents"], 12962, "deposit_refunded_cents")
    a.assert_field_absent_or_null(still, "cancellation_reason")
    assert fx.list_assessments_for(client, reservation["id"]) == []
    a.assert_producer_counters(
        fx.read_producer(client, producer["id"]), held=0, suspension_points=0
    )


def test_an_approval_records_its_reviewer_and_refuses_editorial_annotation(client):
    """The centre does not annotate approvals, and the refusal leaves the claim intact.

    PRD 3.3: "An `APPROVE` decision must **not** carry a `finding_category` at all,
    and supplying one is rejected with the same `ERR_FINDING_CATEGORY_NOT_PERMITTED`
    (422) — the center does not annotate approvals with editorial commentary."

    PRD 3.3: "A `ContentReviewer` first claims the program, moving `SUBMITTED →
    UNDER_REVIEW` and recording their own `X-User-ID` in `reviewed_by_user_id`."

    PRD 3.3: "`UNDER_REVIEW → APPROVED` clears both `finding_category` and
    `finding_notes` back to null and increments the program's `version` by 1;
    nothing else moves, and the program is now bookable for airtime."

    Design: Corner/state_machines/corner_program_approval_records_reviewer_side_effects
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    program = fx.setup_cleared_program(client, producer["id"], title="Neighborhood Notes")
    fx.submit_program(client, program["id"], producer["id"])
    claimed = fx.claim_review(client, program["id"])
    assert claimed["review_status"] == "UNDER_REVIEW"
    assert claimed["reviewed_by_user_id"] == USER_REVIEWER

    annotated = client.decide_program_review(
        program["id"],
        f.review_decision_payload("APPROVE", finding_category="TECHNICAL_STANDARDS_FAILURE"),
        REVIEWER_HEADERS,
    )

    a.error_of(annotated, e.ERR_FINDING_CATEGORY_NOT_PERMITTED, 422)
    assert fx.read_program(client, program["id"])["review_status"] == "UNDER_REVIEW"

    approved = fx.approve_program(client, program["id"])

    assert approved["review_status"] == "APPROVED"
    assert approved["reviewed_by_user_id"] == USER_REVIEWER
    a.assert_field_absent_or_null(approved, "finding_category")
    a.assert_field_absent_or_null(approved, "finding_notes")
    assert approved["revision_round"] == 0
    assert approved["clearance_status"] == "CLEARED"


def test_airing_the_same_slot_twice_is_refused_and_mints_no_second_asset(client):
    """Going to air is one-shot, not an idempotent success.

    PRD 3.5: "Four conditions gate the `SCHEDULED → AIRED` transition: the slot
    must be `SCHEDULED`; the logical clock must have reached or passed the slot's
    `start_at`, otherwise `ERR_AIRTIME_NOT_REACHED` (409)"

    PRD 3.5: "On the channel's airtime ledger, `scheduled_seconds` falls by the
    slot's `occupied_seconds` and `aired_seconds` rises by the same figure, so the
    two counters together always account for every booked second exactly once."

    PRD 3.9: "Exactly one is minted by the system when a slot airs, recording the
    `program_id` of the aired program and the `source_slot_id` of the airing it was
    captured from."

    Design: Corner/state_machines/corner_air_same_slot_twice_returns_invalid_state
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_approved_program(
        client, producer["id"], title="Neighborhood Notes", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")
    fx.set_clock(client, "2026-08-20T18:00:00Z")
    first = fx.air_slot(client, slot["id"], 640)
    assert first["status"] == "AIRED"

    second = client.air_playback_slot(slot["id"], f.air_payload(900), SCHEDULER_HEADERS)

    a.error_of(second, e.ERR_INVALID_STATE_TRANSITION, 409)
    assert fx.read_slot(client, slot["id"])["measured_households"] == 640
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 0, 1920)

    assets, meta = a.assert_pagination_meta(
        client.list_archive_assets(ADMIN_HEADERS, {"source_slot_id": slot["id"]}), 1
    )
    assert len(assets) == 1
    assert assets[0]["measured_households"] == 640
    a.assert_index_equals(assets[0]["community_impact_index"], 32.00)
    assert assets[0]["impact_variant"] == "PROVISIONAL"
    assert meta["has_more"] is False


def test_a_new_funding_period_opens_in_draft_with_nothing_decided(client):
    """Every allocation figure and every operator stamp starts empty.

    PRD 3.8: "A new period opens in `DRAFT` report status with `revision_round` at
    0, with `allocable_base_cents`, `admin_reserve_cents`,
    `capital_allocation_cents`, `operating_allocation_cents` and
    `total_program_funds_cents` all at 0, and with `submitted_by_user_id`,
    `decided_by_user_id` and `decision_reason` all null."

    PRD 3.8: "A `FinanceOfficer` opens a reporting period by supplying
    `fiscal_year` — at least 2000 — and `quarter`, an integer from 1 through 4
    inclusive, together with the `basis` on which the period will be recognised,
    either `ACCRUAL` or `CASH`."

    Design: Corner/state_machines/corner_funding_period_starts_in_draft
    """
    period = a.created_of(
        client.create_funding_period(
            f.funding_period_payload(
                fiscal_year=2026,
                quarter=1,
                basis="ACCRUAL",
                gross_franchise_fee_cents=2000000,
                service_period_earned_cents=1900000,
                remittance_received_cents=1850000,
                capital_grant_cents=0,
            ),
            FINANCE_HEADERS,
        )
    )

    assert period["report_status"] == "DRAFT"
    assert period["revision_round"] == 0
    assert period["basis"] == "ACCRUAL"
    assert period["fiscal_year"] == 2026
    assert period["quarter"] == 1
    for field in (
        "allocable_base_cents",
        "admin_reserve_cents",
        "capital_allocation_cents",
        "operating_allocation_cents",
        "total_program_funds_cents",
    ):
        a.assert_cents(period[field], 0, field)
    a.assert_field_absent_or_null(period, "submitted_by_user_id")
    a.assert_field_absent_or_null(period, "decided_by_user_id")
    a.assert_field_absent_or_null(period, "decision_reason")
    a.assert_common_fields(period, expected_version=1)


def test_an_understaffed_slot_cannot_air_until_the_volunteer_confirms(client):
    """An offer nobody has accepted covers nothing, so the guard holds.

    PRD 3.5: "the slot's `staffing_status` must be either `READY` or
    `NOT_REQUIRED` — an `UNDERSTAFFED` slot cannot air and the attempt is refused
    with `ERR_SLOT_UNDERSTAFFED` (409)."

    PRD 3.5: "Otherwise, gather the set of `crew_role` values held by that slot's
    assignments whose status is `CONFIRMED` or `COMPLETED`; the slot is `READY`
    when every role in `required_crew_roles` appears in that set, and
    `UNDERSTAFFED` otherwise."

    PRD 3.5: "Every crew assignment on the slot whose status is `CONFIRMED` moves
    to `COMPLETED` and is credited with volunteer time: `credited_hours_tenths` is
    the slot's `occupied_seconds` divided by 360 and rounded **up** to a whole
    number of tenths of an hour"

    Design: Corner/state_machines/corner_air_understaffed_slot_blocked_by_guard
    """
    owner = fx.setup_live_certified_producer(client, legal_name="Ada Lovelace")
    volunteer = fx.setup_active_producer(client, legal_name="Vera Rubin")
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_approved_program(
        client, owner["id"], title="Crewed Feature", runtime_seconds=1800,
        is_live=True, required_crew_roles=["CAMERA"],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")
    assignment = fx.offer_crew(client, slot["id"], volunteer["id"], "CAMERA")
    assert slot["staffing_status"] == "UNDERSTAFFED"
    assert assignment["status"] == "OFFERED"

    fx.set_clock(client, "2026-08-20T18:00:00Z")
    blocked = client.air_playback_slot(slot["id"], f.air_payload(640), SCHEDULER_HEADERS)

    a.error_of(blocked, e.ERR_SLOT_UNDERSTAFFED, 409)
    held = fx.read_slot(client, slot["id"])
    assert held["status"] == "SCHEDULED"
    a.assert_field_absent_or_null(held, "aired_at")

    confirmed = fx.confirm_crew(client, assignment["id"], volunteer["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert fx.read_slot(client, slot["id"])["staffing_status"] == "READY"

    aired = fx.air_slot(client, slot["id"], 640)

    assert aired["status"] == "AIRED"
    assert aired["measured_households"] == 640
    completed = fx.read_crew(client, assignment["id"])
    assert completed["status"] == "COMPLETED"
    assert completed["credited_hours_tenths"] == 6
    a.assert_producer_counters(
        fx.read_producer(client, volunteer["id"]), volunteer_tenths=6, commitments=0
    )
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 0, 1920)
