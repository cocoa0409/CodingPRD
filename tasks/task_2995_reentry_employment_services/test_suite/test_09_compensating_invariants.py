"""
Invariants observed across a move and the move that compensates it.

Money is committed and then released; a seat is taken, returned, and taken again.
In both pairs the interesting claim is not the end state alone but that the
conservation identity held at every observation along the way.
"""

from test_helpers.assertions import (
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    assert_session_seat_identity,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    CATEGORY_ID_FEE,
    ENROLLMENT_ENROLLED,
    ENROLLMENT_WITHDRAWN,
    FUNDING_POSTURE_OPEN,
    REQUEST_APPROVED,
    REQUEST_VOIDED,
    SESSION_SCHEDULED,
    SESSION_TYPE_RESUME_LAB,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR_2,
    PROGRAM_DIRECTOR_2_ID,
)

SETTLEMENT_NOTE = "Participant obtained the identification card through a county waiver"


def _grant_holding_one_approved_request(api, build):
    """A grant of 100,000 cents with a single 8,240-cent commitment on it."""
    grant = build.grant(authorized_cents=100000, per_participant_cap_cents=60000)
    participant = build.participant()
    request = build.support_request_approved(
        participant["id"],
        grant["id"],
        [f.line_item("Replacement state identification card", 8000)],
        category=CATEGORY_ID_FEE,
    )
    assert request["status"] == REQUEST_APPROVED
    assert_money_cents(request, "requested_cents", 8000)
    assert_money_cents(request, "admin_fee_cents", 240)
    assert_money_cents(request, "total_charge_cents", 8240)
    return grant, participant, request


def test_the_ledger_identity_holds_while_the_approved_request_is_committed(api, build):
    """
    An approved request holds its total in `committed_cents` and nowhere else, and
    the three money columns still add up to the award.

    PRD section 3.8: "Requests in `SUBMITTED`, `INFO_REQUESTED`, `DEFERRED`,
    `DENIED`, or `VOIDED` contribute nothing at all to the two money columns — only
    `APPROVED` (committed) and `DISBURSED` (disbursed) do."

    Design: Difficulty/compensating_invariant/grant_money_conservation_across_approve_then_void
    """
    grant, participant, request = _grant_holding_one_approved_request(api, build)

    ledger = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "authorized_cents", 100000)
    assert_money_cents(ledger, "committed_cents", 8240)
    assert_money_cents(ledger, "disbursed_cents", 0)
    assert_money_cents(ledger, "available_cents", 91760)
    assert_money_cents(ledger, "restricted_floor_cents", 15000)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_int_field(ledger, "open_request_count", 0)
    assert_ledger_identity(ledger)


def test_voiding_the_request_returns_every_cent_and_keeps_the_identity(api, build):
    """
    The void is the compensating move: the commitment is released, the balance
    returns to the full award, and the request keeps the charge it no longer holds.

    PRD section 3.8: "`APPROVED → VOIDED` cancels an approved request:
    `settled_by_user_id` is recorded, `committed_cents` falls by
    `total_charge_cents`, the ledger re-runs raising `available_cents` and possibly
    flipping `funding_posture` back toward `OPEN`, and because `available_cents`
    rose, the deferral waterfall runs."

    Design: Difficulty/compensating_invariant/grant_money_conservation_across_approve_then_void
    """
    grant, participant, request = _grant_holding_one_approved_request(api, build)
    before = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_ledger_identity(before)

    voided = validate_unpaginated(
        api.settle_support_request(
            request["id"],
            f.settle_payload(REQUEST_VOIDED, SETTLEMENT_NOTE),
            PROGRAM_DIRECTOR_2,
        )
    )
    assert voided["status"] == REQUEST_VOIDED
    assert voided["settled_by_user_id"] == PROGRAM_DIRECTOR_2_ID
    assert voided["settlement_note"] == SETTLEMENT_NOTE
    assert_money_cents(voided, "total_charge_cents", 8240)

    after = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(after, "committed_cents", 0)
    assert_money_cents(after, "disbursed_cents", 0)
    assert_money_cents(after, "available_cents", 100000)
    assert_money_cents(after, "restricted_floor_cents", 15000)
    assert after["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_int_field(after, "open_request_count", 0)
    assert_ledger_identity(after)


def _session_with_two_of_three_seats_taken(api, build):
    """A three-seat session holding two enrollments."""
    session = build.readiness_session(
        session_type=SESSION_TYPE_RESUME_LAB,
        coach_user_id="coach-1",
        starts_at="2026-08-03T13:00:00.000Z",
        ends_at="2026-08-03T15:00:00.000Z",
        seat_capacity=3,
    )
    first_participant = build.participant(full_name="Andre Colwell")
    second_participant = build.participant(full_name="Denise Whitlock")
    first = build.enrollment(session["id"], first_participant["id"])
    second = build.enrollment(session["id"], second_participant["id"])
    return session, first_participant, second_participant, first, second


def test_two_enrollments_consume_two_of_the_three_seats(api, build):
    """
    Every enrollment moves both counters, so the seat identity holds with two of
    three seats taken.

    PRD section 2.9: "For a readiness session, `seat_capacity` always equals
    `enrolled_count` plus `remaining_seats`."

    Design: Difficulty/compensating_invariant/session_seat_conservation_across_enroll_withdraw_reenroll
    """
    session, first_p, second_p, first, second = _session_with_two_of_three_seats_taken(
        api, build
    )

    stored = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert_int_field(stored, "seat_capacity", 3)
    assert_int_field(stored, "enrolled_count", 2)
    assert_int_field(stored, "remaining_seats", 1)
    assert_session_seat_identity(stored)
    assert stored["status"] == SESSION_SCHEDULED
    for enrollment in (first, second):
        assert enrollment["status"] == ENROLLMENT_ENROLLED


def test_a_withdrawal_returns_its_seat_and_a_fresh_enrollment_takes_it_again(
    api, build
):
    """
    A withdrawal is the only exit that returns a seat, and because a withdrawn
    enrollment leaves the uniqueness set the same participant may take the seat back
    with a new row, leaving three enrollments over three seats.

    PRD section 3.5: "`ENROLLED → WITHDRAWN` removes the participant and requires
    that the session's `status` is `SCHEDULED`; it is the only exit that decrements
    `enrolled_count` and increments `remaining_seats`, which is the compensating half
    of the seat-conservation identity."

    Design: Difficulty/compensating_invariant/session_seat_conservation_across_enroll_withdraw_reenroll
    """
    session, first_p, second_p, first, second = _session_with_two_of_three_seats_taken(
        api, build
    )

    withdrawn = validate_unpaginated(
        api.set_enrollment_status(
            first["id"], f.enrollment_status_payload(ENROLLMENT_WITHDRAWN), CASE_MANAGER
        )
    )
    assert withdrawn["status"] == ENROLLMENT_WITHDRAWN

    released = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert_int_field(released, "seat_capacity", 3)
    assert_int_field(released, "enrolled_count", 1)
    assert_int_field(released, "remaining_seats", 2)
    assert_session_seat_identity(released)

    again = validate_unpaginated(
        api.create_enrollment(
            session["id"], f.enrollment_payload(first_p["id"]), CASE_MANAGER
        ),
        201,
    )
    assert again["status"] == ENROLLMENT_ENROLLED
    assert again["id"] != first["id"]

    retaken = validate_unpaginated(api.get_readiness_session(session["id"], CASE_MANAGER))
    assert_int_field(retaken, "seat_capacity", 3)
    assert_int_field(retaken, "enrolled_count", 2)
    assert_int_field(retaken, "remaining_seats", 1)
    assert_session_seat_identity(retaken)

    assert (
        validate_unpaginated(api.get_enrollment(first["id"], CASE_MANAGER))["status"]
        == ENROLLMENT_WITHDRAWN
    )
    assert (
        validate_unpaginated(api.get_enrollment(second["id"], CASE_MANAGER))["status"]
        == ENROLLMENT_ENROLLED
    )

    rows, meta = validate_paginated(
        api.list_session_enrollments(session["id"], CASE_MANAGER)
    )
    assert meta["total_count"] == 3
    assert {row["id"] for row in rows} == {first["id"], second["id"], again["id"]}
