"""Cancellation, promotion compensation, and the parallel booking/attendance dimensions."""
from test_helpers import (
    ApiErrorId,
    assert_seat_invariant,
    check_in_admit,
    get_registration,
    get_session,
    lock_session,
    register_new_examinee,
    setup_bookable_session,
    validate_success,
)
from test_helpers import make_examinee_headers, make_program_admin_headers


def _four_registrants(name="Center SC"):
    """PUBLISHED session total_seats 3: E1-E3 CONFIRMED, E4 WAITLISTED."""
    ctx = setup_bookable_session(name=name, total_seats=3)
    session_id = ctx["session"]["id"]
    regs = [
        register_new_examinee(session_id, full_name=f"Ex S{i}",
                              id_document_number=f"PS0{i}")[1]
        for i in range(1, 5)
    ]
    return ctx, regs


def test_cancel_promotes_earliest_waitlisted_and_conserves_confirmed(api):
    """PRD §3.3: "When the cancelled booking was `CONFIRMED` and a free seat
    therefore opens in its pool, exactly one waitlisted registration in the
    same session and pool is promoted: the one with the smallest `created_at`
    (server-stamped at millisecond precision, so ties cannot occur and no
    further tie-break exists)."

    Design: Difficulty/compensating_invariant/seat_count_conservation_register_cancel
    """
    ctx, (reg1, reg2, reg3, reg4) = _four_registrants()
    validate_success(
        api.cancel_registration(reg2["id"], make_program_admin_headers("admin-1")),
        200,
    )
    reg4 = get_registration(reg4["id"])
    assert reg4["booking_status"] == "CONFIRMED", (
        "earliest-created WAITLISTED promoted"
    )
    assert reg4["waitlist_position"] is None
    session = get_session(ctx["session"]["id"])
    assert session["confirmed_count"] == 3, (
        "cancel plus promotion conserve the confirmed count"
    )


def test_seat_invariant_after_cascading_cancels(api):
    """PRD §3.3: "The seat invariant holds at all times for every session:
    confirmed plus waitlisted plus cancelled bookings equals the total
    registrations ever created for the session, and `confirmed_count` never
    exceeds `total_seats`."
    PRD §3.3: "The session's `confirmed_count` and `waitlist_count` are
    recomputed and its `version` increments by 1."

    Design: Difficulty/compensating_invariant/seat_count_conservation_register_cancel
    """
    ctx, (reg1, reg2, reg3, reg4) = _four_registrants(name="Center SC2")
    session_id = ctx["session"]["id"]
    admin = make_program_admin_headers("admin-1")
    validate_success(api.cancel_registration(reg2["id"], admin), 200)
    validate_success(api.cancel_registration(reg4["id"], admin), 200)
    session = get_session(session_id)
    assert session["confirmed_count"] == 2
    assert session["waitlist_count"] == 0
    assert_seat_invariant(session, cancelled_count=2, total_created=4)
    assert get_registration(reg4["id"])["waitlist_position"] is None


def test_registration_dimensions_booking_confirmed_attendance_admitted(api):
    """PRD §3.4: "The check-in moves the registration's `attendance_status`
    from `PENDING` to `ADMITTED` or `DENIED` to match the decision"
    PRD §3.3: "When occupancy is below the pool size, the registration is
    created `CONFIRMED` with `attendance_status` `PENDING` and the session's
    `confirmed_count` increases by 1."

    Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions
    """
    ctx = setup_bookable_session(name="Center PD", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex PD", id_document_number="PPD1"
    )
    lock_session(session_id, ctx["manager"]["id"])
    check_in_admit(registration["id"], examinee, ctx["proctor"]["id"])
    registration = get_registration(registration["id"])
    assert registration["booking_status"] == "CONFIRMED", (
        "check-in does not touch the booking dimension"
    )
    assert registration["attendance_status"] == "ADMITTED"


def test_cancel_leaves_attendance_dimension_untouched(api):
    """PRD §3.3: "An `Examinee` cancels their own registration, or a
    `ProgramAdmin` cancels any, provided the booking is still `CONFIRMED` or
    `WAITLISTED` and `attendance_status` is not `COMPLETED` — any other
    combination fails with `ERR_INVALID_STATE`. The cancelled booking's
    `waitlist_position` is cleared to null."
    PRD §3.4: "The check-in moves the registration's `attendance_status` from
    `PENDING` to `ADMITTED` or `DENIED` to match the decision"

    Design: Difficulty/non_linear_state_machine/registration_parallel_dimensions
    """
    ctx = setup_bookable_session(name="Center PD2", total_seats=5, with_proctor=True)
    session_id = ctx["session"]["id"]
    examinee, registration = register_new_examinee(
        session_id, full_name="Ex PD2", id_document_number="PPD2"
    )
    lock_session(session_id, ctx["manager"]["id"])
    check_in_admit(registration["id"], examinee, ctx["proctor"]["id"])
    cancelled = validate_success(
        api.cancel_registration(
            registration["id"], make_examinee_headers(examinee["id"])
        ),
        200,
    )
    assert cancelled["booking_status"] == "CANCELLED"
    registration = get_registration(registration["id"])
    assert registration["attendance_status"] == "ADMITTED", (
        "cancel does not rewrite the attendance dimension"
    )
