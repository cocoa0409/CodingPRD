"""Delegate bookings and the minutes-review verdict: the closed occupancy
interval, the agenda deadline, the exposure a review prices and the two
segregation-of-duties pairs that guard the file.
"""
from test_helpers import (
    ADMIN, COUNSEL, ApiErrorId, assert_attendance, assert_instant_equals,
    book_attendance, create_attendance_payload, create_meeting_payload,
    justify_business, make_business_lead_headers, make_counsel_headers,
    minutes_review_payload, read_attendance, read_business_unit, read_employee,
    read_participation, remediation_closure_payload, review_minutes,
    schedule_meeting, set_clock, setup_active_participation,
    setup_attendance_in_minutes_submitted, validate_error, validate_paginated,
    validate_success,
)

COATINGS_UNIT = {
    "name": "Industrial Coatings EMEA",
    "market_code": "EU-COAT",
    "exposure_budget_points": 200,
}


def _violation_scenario():
    """One ATTENDED-then-submitted attendance plus a second future booking."""
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT))
    unit_id, part_id = bundle["unit"]["id"], bundle["participation"]["id"]
    meeting_1 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T09:00:00Z",
                                 scheduled_end="2026-09-10T11:00:00Z",
                                 meeting_type="COMMITTEE", agenda_received=True)
    meeting_2 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-10-05T09:00:00Z",
                                 scheduled_end="2026-10-05T11:00:00Z",
                                 meeting_type="BOARD", agenda_received=True)
    attendance_1 = book_attendance(meeting_1["id"], part_id, unit_id)
    attendance_2 = book_attendance(meeting_2["id"], part_id, unit_id)
    set_clock("2026-09-10T12:00:00Z")
    from test_helpers import confirm_attendance, submit_minutes
    confirm_attendance(attendance_1["id"], bundle["employee"]["id"])
    submit_minutes(
        attendance_1["id"], bundle["employee"]["id"],
        "Standard revision walkthrough; a member raised regional list price timing",
        ["STANDARDS", "PRICING"])
    bundle["attendance_1"] = attendance_1
    bundle["attendance_2"] = attendance_2
    return bundle


def test_violation_verdict_flags_the_attendance_and_prices_the_exposure(api):
    """PRD §3.5: "Every review prices exposure, regardless of verdict. The
    finding points are summed — 8 for a pricing discussion, 6 for a capacity
    discussion, 10 for customer allocation, 10 for bid coordination, 1 for
    aggregated market data, and 0 for a finding of `NONE` — and that sum is
    capped at 15."
    PRD §3.5: "The verdict points are then added **after** the cap, never
    before: 0 for `CLEAN`, 5 for `CONCERN`, 12 for `VIOLATION`."
    PRD §3.5: "The verdict lands in `minutes_verdict`, the findings in
    `minutes_findings`, and the reviewing counsel's `X-User-ID` in
    `minutes_reviewed_by_user_id`."

    Design: Difficulty/transitive_cascade/minutes_violation_flag_review_clearance_four_hop_chain
    """
    set_clock()
    bundle = _violation_scenario()

    data = validate_success(api.review_minutes(
        bundle["attendance_1"]["id"],
        minutes_review_payload("VIOLATION", ["PRICING_DISCUSSION"]),
        make_counsel_headers("counsel-9")))

    assert_attendance(data)
    assert data["status"] == "FLAGGED"
    assert data["minutes_verdict"] == "VIOLATION"
    assert data["exposure_points_assessed"] == 20.00, "12 verdict + 8 finding at LOW"
    assert data["minutes_reviewed_by_user_id"] == "counsel-9"

    unit = read_business_unit(bundle["unit"]["id"])
    assert unit["exposure_points"] == 20.00
    assert unit["posture"] == "OPEN"


def test_violation_suspends_the_delegate_and_cancels_their_future_bookings(api):
    """PRD §3.5: "The second hop drives the parent participation `ACTIVE →
    UNDER_REVIEW`, holding its reserved review minutes rather than releasing
    them. The third hop moves the delegate's `clearance_status` from `GRANTED`
    to `SUSPENDED`. The fourth hop cancels every attendance anywhere in the
    system whose participation names that same delegate, whose status is still
    `PLANNED`, and whose meeting begins strictly after the current logical
    clock, processed in meeting start ascending order and then `created_at`
    ascending order."

    Design: Difficulty/transitive_cascade/minutes_violation_flag_review_clearance_four_hop_chain
    """
    set_clock()
    bundle = _violation_scenario()

    review_minutes(bundle["attendance_1"]["id"], "VIOLATION",
                   ["PRICING_DISCUSSION"], counsel_id="counsel-9")

    participation = read_participation(bundle["participation"]["id"])
    assert participation["status"] == "UNDER_REVIEW"
    assert participation["review_minutes_reserved"] == 30, (
        "the reservation is held rather than released")
    assert read_employee(bundle["employee"]["id"])["clearance_status"] == "SUSPENDED"
    assert read_attendance(bundle["attendance_2"]["id"])["status"] == "CANCELLED"


def test_findings_cap_applies_before_the_verdict_points_are_added(api):
    """PRD §3.5: "Every review prices exposure, regardless of verdict. The
    finding points are summed — 8 for a pricing discussion, 6 for a capacity
    discussion, 10 for customer allocation, 10 for bid coordination, 1 for
    aggregated market data, and 0 for a finding of `NONE` — and that sum is
    capped at 15."
    PRD §3.5: "The verdict points are then added **after** the cap, never
    before: 0 for `CLEAN`, 5 for `CONCERN`, 12 for `VIOLATION`."

    Design: Corner/calculations/minutes_review_findings_cap_applies_only_to_the_findings_sum
    """
    set_clock()
    bundle = setup_attendance_in_minutes_submitted(
        bu_overrides=dict(COATINGS_UNIT),
        summary="Wide-ranging discussion",
        topics_discussed=["PRICING", "BIDDING", "CUSTOMERS"])

    data = validate_success(api.review_minutes(
        bundle["attendance"]["id"],
        minutes_review_payload(
            "VIOLATION",
            ["PRICING_DISCUSSION", "BID_COORDINATION", "CUSTOMER_ALLOCATION"]),
        make_counsel_headers("counsel-9")))

    assert data["exposure_points_assessed"] == 27.00, (
        "28 findings points capped at 15, then 12 verdict points at multiplier 1.0")
    assert data["status"] == "FLAGGED"

    unit = read_business_unit(bundle["unit"]["id"])
    assert unit["exposure_points"] == 27.00
    assert unit["posture"] == "OPEN"
    assert read_participation(bundle["participation"]["id"])["status"] == "UNDER_REVIEW"
    assert read_employee(bundle["employee"]["id"])["clearance_status"] == "SUSPENDED"


def test_clean_verdict_assesses_zero_and_closes_the_file(api):
    """PRD §3.5: "A verdict of `CLEAN` or `CONCERN` moves `MINUTES_SUBMITTED →
    MINUTES_REVIEWED`, which is terminal, and there the file closes."
    PRD §3.5: "The result is multiplied by the business unit's band multiplier —
    1.0 at `LOW`, 1.25 at `MODERATE`, 1.5 at `HIGH`, 2.0 at `SEVERE`, read at
    review time from the participation's unit, and `LOW` whenever the unit has
    no `ACTIVE` risk assessment — and the product is rounded half up to 2
    decimal places into `exposure_points_assessed`."

    Design: Corner/calculations/minutes_review_clean_verdict_assesses_zero_exposure
    """
    set_clock()
    bundle = setup_attendance_in_minutes_submitted(
        bu_overrides=dict(COATINGS_UNIT), summary="Purely technical agenda",
        topics_discussed=["STANDARDS"])

    data = validate_success(api.review_minutes(
        bundle["attendance"]["id"], minutes_review_payload("CLEAN", ["NONE"]),
        make_counsel_headers("counsel-9")))

    assert data["status"] == "MINUTES_REVIEWED"
    assert data["exposure_points_assessed"] == 0.00
    assert read_business_unit(bundle["unit"]["id"])["exposure_points"] == 0.00
    assert read_participation(bundle["participation"]["id"])["status"] == "ACTIVE"
    assert read_employee(bundle["employee"]["id"])["clearance_status"] == "GRANTED"


def test_booking_refused_while_the_participation_is_only_partially_approved(api):
    """PRD §3.5: "The participation must be `ACTIVE`, or the booking fails with
    `ERR_PARTICIPATION_NOT_ACTIVE`."
    PRD §2.7: "Attendance booking requires the participation to be `ACTIVE`,
    failing with `ERR_PARTICIPATION_NOT_ACTIVE`; HSR filing requires the
    transaction to be `ANALYZED` with an `ACTIVE` analysis whose
    `filing_required` is true, failing with `ERR_TRANSACTION_NOT_ANALYZED`; a
    marker request requires the unit's `ACTIVE` risk assessment to sit in `HIGH`
    or `SEVERE`, failing with `ERR_RISK_BAND_TOO_LOW`; a disclosure submission
    requires `marker_status` to be `MARKER_REQUESTED` or `MARKER_GRANTED`,
    failing with `ERR_MARKER_NOT_GRANTED`. All four carry HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/attendance_booking_requires_active_participation
    """
    set_clock()
    from test_helpers import (clear_legally, create_approved_association,
                              create_trained_employee, grant_clearance,
                              nominate_participation, register_business_unit,
                              submit_participation)
    unit = register_business_unit(**COATINGS_UNIT)
    trained = create_trained_employee(unit["id"], role_category="SALES")
    grant_clearance(trained["employee"]["id"])
    association = create_approved_association(approval_tier="TIER_1_LOW",
                                              competitor_density_pct=0)
    participation = nominate_participation(unit["id"], association["id"],
                                           trained["employee"]["id"])
    submit_participation(participation["id"], unit["id"])
    clear_legally(participation["id"])
    meeting = schedule_meeting(association["id"], agenda_received=True)

    resp = api.create_attendance(
        create_attendance_payload(meeting["id"], participation["id"]),
        make_business_lead_headers(unit["id"]))

    validate_error(resp, ApiErrorId.ERR_PARTICIPATION_NOT_ACTIVE.value)
    assert resp.status_code == 409
    assert read_participation(participation["id"])["status"] == "PARTIALLY_APPROVED"


def test_the_same_booking_succeeds_once_the_join_makes_it_active(api):
    """PRD §3.4: "Whichever lands second moves `PARTIALLY_APPROVED → ACTIVE`,
    applying its own effects first and then joining: with `legal_cleared` and
    `business_justified` both true, the participation becomes `ACTIVE`."
    PRD §3.5: "The successful booking opens in `PLANNED` and freezes its
    occupancy edges: `occupied_start` is the meeting's `scheduled_start` moved
    60 minutes earlier to leave room for the counsel briefing, and
    `occupied_end` is the meeting's `scheduled_end` unchanged."

    Design: Difficulty/cross_entity_state_dependency/attendance_booking_requires_active_participation
    """
    set_clock()
    from test_helpers import (clear_legally, create_approved_association,
                              create_trained_employee, grant_clearance,
                              nominate_participation, register_business_unit,
                              submit_participation)
    unit = register_business_unit(**COATINGS_UNIT)
    trained = create_trained_employee(unit["id"], role_category="SALES")
    grant_clearance(trained["employee"]["id"])
    association = create_approved_association(approval_tier="TIER_1_LOW",
                                              competitor_density_pct=0)
    participation = nominate_participation(unit["id"], association["id"],
                                           trained["employee"]["id"])
    submit_participation(participation["id"], unit["id"])
    clear_legally(participation["id"])
    meeting = schedule_meeting(association["id"], agenda_received=True)

    justify_business(participation["id"], unit["id"])
    assert read_participation(participation["id"])["status"] == "ACTIVE"

    data = validate_success(api.create_attendance(
        create_attendance_payload(meeting["id"], participation["id"]),
        make_business_lead_headers(unit["id"])), 201)

    assert data["status"] == "PLANNED"
    assert_instant_equals(data["occupied_start"], "2026-09-10T08:00:00.000Z",
                          "MeetingAttendance.occupied_start")
    assert_instant_equals(data["occupied_end"], "2026-09-10T11:00:00.000Z",
                          "MeetingAttendance.occupied_end")


def test_touching_delegate_occupancy_intervals_conflict(api):
    """PRD §2.10: "Two attendances of the same delegate conflict when the
    candidate's occupied start is at or before the existing occupied end **and**
    the existing occupied start is at or before the candidate's occupied end.
    Touching endpoints *do* conflict: an existing interval ending at exactly
    some instant collides with a candidate whose interval begins at exactly that
    instant."
    PRD §3.5: "And the delegate's resulting closed occupancy interval must not
    intersect any of their other occupying attendances, or it fails with
    `ERR_ATTENDEE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/delegate_closed_interval_with_briefing_buffer_rejects_touching_windows
    """
    set_clock()
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT))
    unit_id, part_id = bundle["unit"]["id"], bundle["participation"]["id"]
    meeting_1 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T09:00:00Z",
                                 scheduled_end="2026-09-10T11:00:00Z",
                                 agenda_received=True)
    attendance_1 = book_attendance(meeting_1["id"], part_id, unit_id)
    meeting_2 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T12:00:00Z",
                                 scheduled_end="2026-09-10T13:00:00Z",
                                 meeting_type="BOARD", agenda_received=True)

    resp = api.create_attendance(
        create_attendance_payload(meeting_2["id"], part_id),
        make_business_lead_headers(unit_id))

    validate_error(resp, ApiErrorId.ERR_ATTENDEE_WINDOW_CONFLICT.value)
    assert resp.status_code == 409
    assert_instant_equals(read_attendance(attendance_1["id"])["occupied_end"],
                          "2026-09-10T11:00:00.000Z",
                          "MeetingAttendance.occupied_end")


def test_one_minute_later_start_clears_the_delegate_occupancy_conflict(api):
    """PRD §2.10: "An attendance's `occupied_start` is the meeting's
    `scheduled_start` moved earlier by a 60-minute counsel briefing buffer, and
    its `occupied_end` is the meeting's `scheduled_end` unchanged."
    PRD §2.10: "Touching endpoints *do* conflict: an existing interval ending at
    exactly some instant collides with a candidate whose interval begins at
    exactly that instant."

    Design: Difficulty/resource_temporal_overlap/delegate_closed_interval_with_briefing_buffer_rejects_touching_windows
    """
    set_clock()
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT))
    unit_id, part_id = bundle["unit"]["id"], bundle["participation"]["id"]
    meeting_1 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T09:00:00Z",
                                 scheduled_end="2026-09-10T11:00:00Z",
                                 agenda_received=True)
    book_attendance(meeting_1["id"], part_id, unit_id)
    meeting_3 = schedule_meeting(bundle["association"]["id"],
                                 scheduled_start="2026-09-10T12:01:00Z",
                                 scheduled_end="2026-09-10T13:01:00Z",
                                 meeting_type="BOARD", agenda_received=True)

    data = validate_success(api.create_attendance(
        create_attendance_payload(meeting_3["id"], part_id),
        make_business_lead_headers(unit_id)), 201)

    assert data["status"] == "PLANNED"
    assert_instant_equals(data["occupied_start"], "2026-09-10T11:01:00.000Z",
                          "MeetingAttendance.occupied_start")

    _rows, meta = validate_paginated(api.list_attendances(
        COUNSEL, params={"participation_id": part_id}))
    assert meta["total_count"] == 2


def test_meeting_with_a_zero_length_interval_is_refused(api):
    """PRD §2.7: "**Interval well-formedness.** `scheduled_end` is strictly
    after `scheduled_start`, and `window_end` is strictly after `window_start` —
    otherwise `ERR_INVALID_INTERVAL`, HTTP 422."
    PRD §3.5: "The payload carries `association_id`, a `meeting_type` drawn from
    `BOARD`, `COMMITTEE`, `STANDARDS` and `SOCIAL`, a `scheduled_start` and a
    `scheduled_end` — both ISO 8601 UTC, with the end strictly after the start —
    and an optional `agenda_received` flag recording whether counsel has the
    written agenda in hand, which defaults to false."

    Design: Corner/validations/meeting_end_before_start_returns_invalid_interval
    """
    set_clock()
    from test_helpers import create_approved_association
    association = create_approved_association()

    resp = api.create_meeting(create_meeting_payload(
        association["id"], scheduled_start="2026-09-10T09:00:00Z",
        scheduled_end="2026-09-10T09:00:00Z", agenda_received=True), ADMIN)

    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)
    assert resp.status_code == 422

    _rows, meta = validate_paginated(api.list_meetings(
        COUNSEL, params={"association_id": association["id"]}))
    assert meta["total_count"] == 0


def test_booking_inside_the_forty_eight_hour_agenda_lead_time_is_refused(api):
    """PRD §3.5: "The meeting's agenda must already have been received **and**
    the meeting must begin at least 48 hours — two full days — after the current
    logical clock, or it fails with `ERR_AGENDA_DEADLINE_MISSED`; counsel cannot
    brief a delegate on a standards-body agenda that arrives the night before."
    PRD §2.5: "Thresholds are stated with explicit inclusivity throughout. Where
    a rule says a value must be at least some figure, a value exactly equal to
    that figure satisfies it."

    Design: Corner/validations/attendance_booking_within_48_hours_returns_agenda_deadline_missed
    """
    set_clock("2026-08-01T00:00:00Z")
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT))
    unit_id, part_id = bundle["unit"]["id"], bundle["participation"]["id"]
    late = schedule_meeting(bundle["association"]["id"],
                            scheduled_start="2026-08-02T23:00:00Z",
                            scheduled_end="2026-08-03T01:00:00Z",
                            agenda_received=True)
    on_time = schedule_meeting(bundle["association"]["id"],
                               scheduled_start="2026-08-03T00:00:00Z",
                               scheduled_end="2026-08-03T02:00:00Z",
                               meeting_type="BOARD", agenda_received=True)

    refused = api.create_attendance(
        create_attendance_payload(late["id"], part_id),
        make_business_lead_headers(unit_id))
    validate_error(refused, ApiErrorId.ERR_AGENDA_DEADLINE_MISSED.value)
    assert refused.status_code == 422

    accepted = validate_success(api.create_attendance(
        create_attendance_payload(on_time["id"], part_id),
        make_business_lead_headers(unit_id)), 201)
    assert accepted["status"] == "PLANNED"
    assert_instant_equals(accepted["occupied_start"], "2026-08-02T23:00:00.000Z",
                          "MeetingAttendance.occupied_start")


def test_booking_a_meeting_whose_agenda_has_not_arrived_is_refused(api):
    """PRD §3.5: "The meeting's agenda must already have been received **and**
    the meeting must begin at least 48 hours — two full days — after the current
    logical clock, or it fails with `ERR_AGENDA_DEADLINE_MISSED`; counsel cannot
    brief a delegate on a standards-body agenda that arrives the night before."
    PRD §2.7: "**Agenda deadline.** The meeting's `agenda_received` is true
    **and** the meeting begins at least 48 hours after the current logical clock
    — otherwise `ERR_AGENDA_DEADLINE_MISSED`, HTTP 422."

    Design: Corner/validations/agenda_not_received_returns_agenda_deadline_missed
    """
    set_clock("2026-08-01T00:00:00Z")
    bundle = setup_active_participation(bu_overrides=dict(COATINGS_UNIT))
    unit_id, part_id = bundle["unit"]["id"], bundle["participation"]["id"]
    meeting = schedule_meeting(bundle["association"]["id"],
                               scheduled_start="2026-09-10T09:00:00Z",
                               scheduled_end="2026-09-10T11:00:00Z",
                               agenda_received=False)

    resp = api.create_attendance(
        create_attendance_payload(meeting["id"], part_id),
        make_business_lead_headers(unit_id))

    validate_error(resp, ApiErrorId.ERR_AGENDA_DEADLINE_MISSED.value)
    assert resp.status_code == 422

    _rows, meta = validate_paginated(api.list_attendances(
        COUNSEL, params={"participation_id": part_id}))
    assert meta["total_count"] == 0


def test_clearing_counsel_may_not_review_that_participations_minutes(api):
    """PRD §2.9: "First, the `AntitrustCounsel` whose `X-User-ID` was recorded
    as `legal_cleared_by_user_id` when a participation received legal clearance
    may not later review the minutes of any attendance belonging to that
    participation."
    PRD §2.9: "Either collision is rejected with `ERR_SEGREGATION_OF_DUTIES` and
    HTTP 409, evaluated at rung 9 of the ladder — that is, after ownership and
    concurrency checks but before the transition's own legality is considered."

    Design: Corner/rbac/same_counsel_cannot_review_minutes_after_granting_legal_clearance
    """
    set_clock()
    bundle = setup_attendance_in_minutes_submitted(
        bu_overrides=dict(COATINGS_UNIT), legal_counsel_id="counsel-1",
        summary="Technical agenda only", topics_discussed=["STANDARDS"])

    refused = api.review_minutes(
        bundle["attendance"]["id"], minutes_review_payload("CLEAN", ["NONE"]),
        make_counsel_headers("counsel-1"))
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert refused.status_code == 409
    assert read_participation(
        bundle["participation"]["id"])["legal_cleared_by_user_id"] == "counsel-1"

    accepted = validate_success(api.review_minutes(
        bundle["attendance"]["id"], minutes_review_payload("CLEAN", ["NONE"]),
        make_counsel_headers("counsel-2")))
    assert accepted["status"] == "MINUTES_REVIEWED"
    assert accepted["minutes_reviewed_by_user_id"] == "counsel-2"


def test_flagging_counsel_may_not_close_the_remediation_they_opened(api):
    """PRD §2.9: "Second, the `AntitrustCounsel` whose `X-User-ID` was recorded
    as `minutes_reviewed_by_user_id` when an attendance was flagged may not
    close that attendance's remediation."
    PRD §3.5: "Remediation closure is the way back. A **second** counsel — never
    the one recorded in `minutes_reviewed_by_user_id` — supplies `notes` and
    moves `FLAGGED → MINUTES_REVIEWED`. The `exposure_points_assessed` figure is
    deliberately retained: closing the file records that the matter was handled,
    but it does not refund the exposure the violation created."

    Design: Corner/rbac/same_counsel_cannot_close_the_remediation_they_flagged
    """
    set_clock()
    bundle = setup_attendance_in_minutes_submitted(
        bu_overrides=dict(COATINGS_UNIT),
        summary="A member raised regional list price timing",
        topics_discussed=["PRICING"])
    review_minutes(bundle["attendance"]["id"], "VIOLATION", ["PRICING_DISCUSSION"],
                   counsel_id="counsel-9")

    refused = api.close_remediation(
        bundle["attendance"]["id"],
        remediation_closure_payload("Closing my own finding"),
        make_counsel_headers("counsel-9"))
    validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert refused.status_code == 409

    accepted = validate_success(api.close_remediation(
        bundle["attendance"]["id"],
        remediation_closure_payload("Independent review confirms remediation complete"),
        make_counsel_headers("counsel-3")))
    assert accepted["status"] == "MINUTES_REVIEWED"
    assert accepted["exposure_points_assessed"] == 20.00, (
        "closing the file does not refund the exposure the violation created")
    assert read_business_unit(bundle["unit"]["id"])["exposure_points"] == 20.00
    assert read_participation(bundle["participation"]["id"])["status"] == "UNDER_REVIEW"
