"""The inquiry allowance ledger: settled vs reserved units and the scheduling gate."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_ledger_identity,
    create_account,
    create_active_seat,
    create_analyst,
    create_routed_inquiry,
    create_scheduled_inquiry,
    complete_inquiry,
    get_account,
    get_success_data,
    make_analyst_headers,
    make_client_admin_headers,
    make_seat_holder_headers,
    schedule_inquiry,
    set_clock,
    setup_account_with_active_seat,
    validate_error,
)


def test_consumption_and_reservation_remainders_diverge_by_the_open_bookings():
    """PRD §2.6: "`remaining_consumed_units` equals `inquiry_allowance_total` minus
    the settled units; this is the CONSUMPTION variant, read by renewal-overage
    reporting and by the usage component of the research-utilization score.
    `remaining_reserved_units` equals `inquiry_allowance_total` minus the settled
    units minus the reserved units; this is the RESERVATION variant, and it is the
    figure that must be at least 1 before a new inquiry can be scheduled."
    PRD §2.6: "A unit is reserved while the inquiry is `SCHEDULED` or `IN_PREP`."

    Design: Difficulty/dual_variant_calc/allowance_ledger_consumption_vs_reservation
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(seat_count_contracted=10, inquiry_allowance_total=10)
    seat = create_active_seat(account, seat_email="nina@acme.example")
    analyst = create_analyst()

    starts = [
        "2026-09-02T10:00:00Z",
        "2026-09-02T11:00:00Z",
        "2026-09-02T12:00:00Z",
        "2026-09-03T10:00:00Z",
        "2026-09-03T11:00:00Z",
    ]
    durations = [45, 45, 30, 30, 30]
    inquiries = []
    for index, start in enumerate(starts):
        inquiry = create_scheduled_inquiry(
            account, seat, analyst, start,
            question_summary=f"Ledger inquiry {index + 1}",
            duration_minutes=durations[index],
        )
        inquiries.append(inquiry)

    set_clock("2026-09-02T13:00:00Z")
    for inquiry in inquiries[:3]:
        complete_inquiry(analyst, inquiry, "2026-09-02T13:00:00Z")

    data = get_account(account, make_client_admin_headers(account["id"]))
    assert data["consumed_inquiry_units"] == 3
    assert data["reserved_inquiry_units"] == 2
    assert data["remaining_consumed_units"] == 7, (
        "CONSUMPTION variant ignores reservations: 10 - 3 settled = 7"
    )
    assert data["remaining_reserved_units"] == 5, (
        "RESERVATION variant debits settled and reserved: 10 - 3 - 2 = 5"
    )
    assert data["remaining_consumed_units"] - data["remaining_reserved_units"] == 2, (
        "The two variants differ by exactly the open SCHEDULED inquiries"
    )
    assert data["inquiry_allowance_total"] == 10
    assert_ledger_identity(data)


def test_reservation_variant_debits_open_bookings_while_consumption_does_not():
    """PRD §2.6: "Because the reservation variant debits both settled and reserved
    units while the consumption variant ignores reservations entirely, an account
    with open `SCHEDULED` inquiries reads a smaller `remaining_reserved_units` than
    `remaining_consumed_units`, and the scheduling gate blocks a new booking before
    the settled ledger would."

    Design: Difficulty/dual_variant_calc/allowance_ledger_consumption_vs_reservation
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=4, inquiry_allowance_total=4
    )
    create_scheduled_inquiry(
        account, seat, analyst, "2026-09-08T10:00:00Z", question_summary="Open booking one"
    )
    create_scheduled_inquiry(
        account, seat, analyst, "2026-09-08T11:00:00Z", question_summary="Open booking two"
    )

    data = get_account(account, make_client_admin_headers(account["id"]))
    assert data["consumed_inquiry_units"] == 0
    assert data["reserved_inquiry_units"] == 2
    assert data["remaining_consumed_units"] == 4, (
        "No inquiry has settled, so the CONSUMPTION remainder is untouched"
    )
    assert data["remaining_reserved_units"] == 2, (
        "Both open bookings are debited from the RESERVATION remainder"
    )
    assert data["remaining_reserved_units"] < data["remaining_consumed_units"]
    assert_ledger_identity(data)


def test_booking_at_one_free_unit_succeeds_and_zero_is_rejected():
    """PRD §2.6: "`remaining_reserved_units` equals `inquiry_allowance_total` minus
    the settled units minus the reserved units; this is the RESERVATION variant, and
    it is the figure that must be at least 1 before a new inquiry can be scheduled."
    PRD §2.11: "Allowance: the account's reservation remainder must be at least 1
    before an inquiry may be scheduled (`ERR_INQUIRY_ALLOWANCE_EXHAUSTED`, HTTP 409)."

    Design: Difficulty/boundary_precision_check/allowance_reservation_boundary_at_zero_units
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(seat_count_contracted=3, inquiry_allowance_total=2)
    seat = create_active_seat(account)
    analyst = create_analyst()

    first = create_scheduled_inquiry(
        account, seat, analyst, "2026-09-04T10:00:00Z", question_summary="Inquiry one"
    )
    assert first["status"] == "SCHEDULED"

    second = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-05T10:00:00Z",
        question_summary="Inquiry two",
    )
    third = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-06T10:00:00Z",
        question_summary="Inquiry three",
    )

    before = get_account(account, make_client_admin_headers(account["id"]))
    assert before["remaining_reserved_units"] == 1, "One of two units is already reserved"

    booked = schedule_inquiry(analyst, second, "2026-09-05T10:00:00Z")
    assert booked["status"] == "SCHEDULED"

    after = get_account(account, make_client_admin_headers(account["id"]))
    assert after["remaining_reserved_units"] == 0

    resp = api_client.schedule_inquiry(
        third["id"], {"scheduled_start_utc": "2026-09-06T10:00:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INQUIRY_ALLOWANCE_EXHAUSTED)
    still_routed = get_success_data(
        api_client.get_inquiry(third["id"], make_analyst_headers(analyst["id"]))
    )
    assert still_routed["status"] == "ROUTED"


def test_booking_at_exactly_zero_free_units_is_rejected():
    """PRD §2.6: "it is the figure that must be at least 1 before a new inquiry can
    be scheduled."
    PRD §2.11: "Allowance: the account's reservation remainder must be at least 1
    before an inquiry may be scheduled (`ERR_INQUIRY_ALLOWANCE_EXHAUSTED`, HTTP 409)."

    Design: Difficulty/boundary_precision_check/allowance_reservation_boundary_at_zero_units
    """
    set_clock("2026-09-01T00:00:00Z")
    account = create_account(seat_count_contracted=2, inquiry_allowance_total=1)
    seat = create_active_seat(account)
    analyst = create_analyst()

    create_scheduled_inquiry(
        account, seat, analyst, "2026-09-04T10:00:00Z", question_summary="Consumes the term"
    )
    blocked = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-05T10:00:00Z",
        question_summary="No units left",
    )

    exhausted = get_account(account, make_client_admin_headers(account["id"]))
    assert exhausted["remaining_reserved_units"] == 0

    resp = api_client.schedule_inquiry(
        blocked["id"], {"scheduled_start_utc": "2026-09-05T10:00:00Z"},
        make_analyst_headers(analyst["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INQUIRY_ALLOWANCE_EXHAUSTED)

    after = get_account(account, make_client_admin_headers(account["id"]))
    assert after["remaining_reserved_units"] == 0
    assert after["reserved_inquiry_units"] == 1


def test_free_cancel_releases_the_reservation_and_late_cancel_consumes_it():
    """PRD §3.3: "Cancelling a scheduled or in-preparation inquiry is free while the
    clock reading is at or before `scheduled_start_utc` minus 24 hours —
    `units_consumed` is 0 and only the reservation is released, decrementing
    `reserved_inquiry_units` — and is late once the clock reading is strictly after
    that instant, in which case `units_consumed` is 1 and the account's
    `reserved_inquiry_units` is decremented while its `consumed_inquiry_units` is
    incremented."

    Design: Difficulty/compensating_invariant/inquiry_units_conserved_across_schedule_and_cancel
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    seat_headers = make_seat_holder_headers(seat["id"])

    first = create_scheduled_inquiry(
        account, seat, analyst, "2026-09-10T10:00:00Z", question_summary="Reserve then release"
    )
    reserved = get_account(account, make_client_admin_headers(account["id"]))
    assert reserved["reserved_inquiry_units"] == 1
    assert reserved["remaining_reserved_units"] == 9
    assert reserved["consumed_inquiry_units"] == 0
    assert_ledger_identity(reserved)

    released = get_success_data(
        api_client.cancel_inquiry(first["id"], {"cancel_reason": "Rescheduled internally"},
                                  seat_headers)
    )
    assert released["units_consumed"] == 0

    free = get_account(account, make_client_admin_headers(account["id"]))
    assert free["reserved_inquiry_units"] == 0
    assert free["remaining_reserved_units"] == 10
    assert free["consumed_inquiry_units"] == 0
    assert_ledger_identity(free)

    second = create_scheduled_inquiry(
        account, seat, analyst, "2026-09-03T10:00:00Z", question_summary="Late cancel branch"
    )
    set_clock("2026-09-03T00:00:00Z")
    late = get_success_data(
        api_client.cancel_inquiry(
            second["id"], {"cancel_reason": "Cancelled inside the 24 hour window"},
            seat_headers,
        )
    )
    assert late["units_consumed"] == 1

    after_late = get_account(account, make_client_admin_headers(account["id"]))
    assert after_late["consumed_inquiry_units"] == 1
    assert after_late["reserved_inquiry_units"] == 0
    assert after_late["remaining_reserved_units"] == 9
    assert after_late["remaining_consumed_units"] == 9
    assert_ledger_identity(after_late)


def test_cancel_at_the_exact_boundary_is_free():
    """PRD §2.4: "An inquiry cancellation is free while the clock reading is at or
    before `scheduled_start_utc` minus 24 hours, and is late once the clock reading
    is strictly after that instant."
    PRD §3.3: "Cancelling a scheduled or in-preparation inquiry is free while the
    clock reading is at or before `scheduled_start_utc` minus 24 hours —
    `units_consumed` is 0 and only the reservation is released, decrementing
    `reserved_inquiry_units` — and is late once the clock reading is strictly after
    that instant, in which case `units_consumed` is 1 and the account's
    `reserved_inquiry_units` is decremented while its `consumed_inquiry_units` is
    incremented."

    Design: Difficulty/compensating_invariant/inquiry_units_conserved_across_schedule_and_cancel
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    inquiry = create_scheduled_inquiry(
        account, seat, analyst, "2026-09-10T10:00:00Z", question_summary="Boundary cancel"
    )

    set_clock("2026-09-09T10:00:00Z")
    cancelled = get_success_data(
        api_client.cancel_inquiry(
            inquiry["id"], {"cancel_reason": "Exactly at the boundary"},
            make_seat_holder_headers(seat["id"]),
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["units_consumed"] == 0, (
        "The boundary is inclusive, so cancelling exactly 24 hours ahead is free"
    )

    data = get_account(account, make_client_admin_headers(account["id"]))
    assert data["consumed_inquiry_units"] == 0
    assert data["reserved_inquiry_units"] == 0
    assert data["remaining_reserved_units"] == 10
    assert data["remaining_consumed_units"] == 10
    assert_ledger_identity(data)


def test_routed_inquiry_contributes_to_neither_ledger_aggregate():
    """PRD §2.6: "Inquiries that are `SUBMITTED` or `ROUTED`, and inquiries cancelled
    without charge, contribute to neither aggregate."

    Design: Corner/calculations/allowance_ledger_excludes_routed_inquiries_from_both_variants
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    inquiry = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-20T10:00:00Z",
        question_summary="Routed but not booked",
    )
    assert inquiry["status"] == "ROUTED"

    data = get_account(account, make_client_admin_headers(account["id"]))
    assert data["remaining_consumed_units"] == 10
    assert data["remaining_reserved_units"] == 10
    assert data["consumed_inquiry_units"] == 0
    assert data["reserved_inquiry_units"] == 0
    assert_ledger_identity(data)


def test_reservation_written_by_scheduling_is_visible_to_the_immediate_next_read():
    """PRD §2.6: "Every `ClientAccount` carries an inquiry allowance ledger,
    recomputed on every inquiry state change and on every read of the account."

    Design: Corner/cross_cutting_complexity_layers/immediate_consistency_reservation_is_visible_in_the_same_request
    """
    set_clock("2026-09-01T00:00:00Z")
    account, seat, analyst = setup_account_with_active_seat(
        seat_count_contracted=10, inquiry_allowance_total=10
    )
    inquiry = create_routed_inquiry(
        account, seat, requested_start_utc="2026-09-20T10:00:00Z",
        question_summary="Immediate visibility",
    )

    before = get_account(account, make_client_admin_headers(account["id"]))
    assert before["reserved_inquiry_units"] == 0
    assert before["remaining_reserved_units"] == 10

    scheduled = schedule_inquiry(analyst, inquiry, "2026-09-20T10:00:00Z")
    assert scheduled["status"] == "SCHEDULED"

    after = get_account(account, make_client_admin_headers(account["id"]))
    assert after["reserved_inquiry_units"] == 1
    assert after["remaining_reserved_units"] == 9
    assert after["consumed_inquiry_units"] == 0
    assert after["remaining_consumed_units"] == 10
