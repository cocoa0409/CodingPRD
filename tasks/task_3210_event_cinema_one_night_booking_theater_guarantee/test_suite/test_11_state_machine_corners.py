"""State-machine corners: initial states, terminal lockdowns and guarded transitions."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, first_screening, confirm_booking, get_line,
    create_distributor, create_settlement_payload, make_distributor_headers,
    make_exhibitor_headers, make_theater_headers, setup_circuit_venue_title,
    report_screening, get_title,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]


def _approved_scene(screens=60, publish=True):
    """Accredited circuit, CA venue, published title, APPROVED booking + screening."""
    c = setup_circuit_venue_title(publish=publish)
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=screens,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    booking = approve_booking(booking["id"], c["distributor"]["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    c.update({"booking": booking, "line": line,
              "screening": first_screening(booking["id"])})
    return c


def test_new_booking_starts_in_draft_with_version_one():
    """PRD §3.1: "The booking starts `DRAFT`, with a committed screen total of zero
    and presale ticket count of zero."
    PRD §2.6: "A mutation to any resource refreshes its `updated_at` and, for the
    entities that carry the system version field, advances `version` by one."

    Design: Corner/state_machines/booking_new_booking_starts_in_draft
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    assert booking["status"] == "DRAFT"
    assert booking["version"] == 1
    assert booking["committed_screens_total"] == 0
    assert booking["pre_sale_tickets"] == 0


def test_new_booking_reports_its_declared_showtime_shape():
    """PRD §3.1: "`showtime_count` must be exactly 1 or 2 — this is a one-night or
    two-night business and the API enforces it, not merely documents it — and
    `showtime_plan` must be an array carrying exactly that many elements."
    PRD §3.1: "The `negotiating_user_id` is stamped from the `X-User-ID` header of the
    request and records the distributor principal who opened the negotiation; it is
    never supplied by the client."

    Design: Corner/state_machines/booking_new_booking_starts_in_draft
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"], showtime_count=2,
                             showtime_plan=[
                                 {"index": 1, "date_utc": "2026-12-01T00:00:00Z",
                                  "start_minute_utc": 1140, "auditorium": "AUD-1"},
                                 {"index": 2, "date_utc": "2026-12-02T00:00:00Z",
                                  "start_minute_utc": 1140, "auditorium": "AUD-1"}])
    assert booking["showtime_count"] == 2
    assert len(booking["showtime_plan"]) == 2
    assert booking["status"] == "DRAFT"


def test_second_report_against_a_screened_screening_is_refused_as_terminal():
    """PRD §3.6: "Both `SCREENED` and `SKIPPED_INCOMPLETE` are terminal, and a
    screening may not be reported twice: a report against a screening that has already
    reached a terminal state is refused with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/screening_report_from_terminal_state_returns_already_terminal
    """
    c = _approved_scene()
    set_clock(c["booking"]["on_sale_at"])
    run_on_sale_sweep()
    screening = first_screening(c["booking"]["id"])
    set_clock("2026-12-01T21:30:00Z")
    first = report_screening(screening["id"], c["theater"]["id"], 175, "SCREENED",
                             at_instant="2026-12-01T21:30:00Z")
    assert first["state"] == "SCREENED"
    resp = api_client.report_screening(
        screening["id"], 40, "SCREENED", make_theater_headers(c["theater"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL, 409)


def test_report_against_a_terminal_screening_does_not_move_the_state():
    """PRD §3.6: "A screening that had to be abandoned for reasons outside the feed —
    cancelled by a hold, a withdrawal, an expiry, a presale failure, or a venue going
    dark — does not pass through reporting at all".

    Design: Corner/state_machines/screening_report_from_terminal_state_returns_already_terminal
    """
    c = _approved_scene()
    set_clock(c["booking"]["on_sale_at"])
    run_on_sale_sweep()
    screening = first_screening(c["booking"]["id"])
    report_screening(screening["id"], c["theater"]["id"], 175, "SCREENED")
    api_client.report_screening(
        screening["id"], 40, "SCREENED", make_theater_headers(c["theater"]["id"]))
    current = get_success_data(api_client.get_screening(screening["id"], OPS))
    assert current["state"] == "SCREENED"


def test_report_against_a_void_screening_is_refused_as_invalid_state():
    """PRD §3.3: "every `COMMITTED` line is released, and — note the distinction from
    cancellation — every screening still in `SCHEDULED` moves to `VOID` rather than
    `SKIPPED_CANCELLED`, because the run has not failed, it has been set aside."

    Design: Corner/state_machines/screening_report_from_unscheduled_state_returns_invalid_state
    """
    c = _approved_scene()
    set_clock(c["booking"]["on_sale_at"])
    run_on_sale_sweep()
    booking = get_booking(c["booking"]["id"])
    screening = first_screening(booking["id"])
    get_success_data(api_client.suspend_booking(
        booking["id"], booking["version"],
        make_distributor_headers(c["distributor"]["id"])))
    assert get_success_data(
        api_client.get_screening(screening["id"], OPS))["state"] == "VOID"
    set_clock("2026-12-01T21:30:00Z")
    resp = api_client.report_screening(
        screening["id"], 175, "SCREENED", make_theater_headers(c["theater"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_screening_voided_by_a_hold_does_not_accept_a_report():
    """PRD §3.3: "The `VOID` screen state therefore means "set aside by a hold", and an
    auditorium recovered from a hold does not reuse its old screening record."

    Design: Corner/state_machines/screening_report_from_unscheduled_state_returns_invalid_state
    """
    c = _approved_scene()
    set_clock(c["booking"]["on_sale_at"])
    run_on_sale_sweep()
    booking = get_booking(c["booking"]["id"])
    screening = first_screening(booking["id"])
    held = get_success_data(api_client.suspend_booking(
        booking["id"], booking["version"],
        make_distributor_headers(c["distributor"]["id"])))
    assert held["status"] == "ON_HOLD"
    set_clock("2026-12-01T21:30:00Z")
    resp = api_client.report_screening(
        screening["id"], 175, "SCREENED", make_theater_headers(c["theater"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_close_is_refused_while_a_screening_remains_scheduled():
    """PRD §3.8: "A booking ends in `TERMINAL`, and reaching it is guarded on two
    conditions being simultaneously true: no screening of the booking may still be
    `SCHEDULED`, and no settlement of the booking may be in `OPEN` or `REOPENED`."

    Design: Corner/state_machines/booking_close_is_refused_while_screenings_remain_scheduled
    """
    c = _approved_scene()
    booking = c["booking"]
    assert get_success_data(
        api_client.get_screening(c["screening"]["id"], OPS))["state"] == "SCHEDULED"
    resp = api_client.close_booking(booking["id"], booking["version"], OPS)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_booking(booking["id"])["status"] == "APPROVED", (
        "the booking survived the refusal"
    )


def test_close_succeeds_once_no_screening_is_scheduled():
    """PRD §3.8: "A platform operator closes it from any of `DRAFT`,
    `PENDING_APPROVAL`, `COUNTERED`, `APPROVED`, `CANCELLED`, `ON_HOLD`, `SETTLED`, or
    `ON_SALE`, the booking moves to `TERMINAL`, and the circuit's committed screen
    balance is recomputed one last time."

    Design: Corner/state_machines/booking_close_is_refused_while_screenings_remain_scheduled
    """
    c = _approved_scene()
    booking = c["booking"]
    get_success_data(api_client.release_screens(
        booking["id"], c["line"]["id"], booking["version"],
        make_distributor_headers(c["distributor"]["id"])))
    assert get_success_data(
        api_client.get_screening(c["screening"]["id"], OPS))["state"] == \
        "SKIPPED_CANCELLED"
    # §2.6: releasing the line advanced the booking's version.
    booking = get_booking(booking["id"])
    closed = get_success_data(api_client.close_booking(booking["id"],
                                                       booking["version"], OPS))
    assert closed["status"] == "TERMINAL"


def test_title_clear_is_refused_when_no_bookings_exist():
    """PRD §3.1: "Clearing a `BOOKABLE` title moves it to `CLEARED` and is permitted
    only once at least one booking exists against it; it is not a cancellation."

    Design: Corner/state_machines/title_clear_is_refused_when_no_bookings_exist
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    resp = api_client.clear_title(c["title"]["id"], PROG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_title(c["title"]["id"])["status"] == "BOOKABLE"


def test_title_clear_succeeds_once_a_booking_exists():
    """PRD §3.1: "A `Title` names the `Distributor` that licensed it; a `Theater` names
    the `Circuit` that operates it; a `Booking` names the `Title` at issue and the
    `Circuit` that is negotiating".

    Design: Corner/state_machines/title_clear_is_refused_when_no_bookings_exist
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    api_client.clear_title(c["title"]["id"], PROG)
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    cleared = get_success_data(api_client.clear_title(c["title"]["id"], PROG))
    assert cleared["status"] == "CLEARED"
    assert booking["status"] == "DRAFT"


def test_title_clear_then_reopen_returns_the_title_to_bookable():
    """PRD §3.1: "Reopening a `CLEARED` title returns it to `BOOKABLE` and, like
    publishing, requires that the rights window has not yet closed."

    Design: Corner/state_machines/title_clear_then_reopen_is_a_revision_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    create_booking(c["title"]["id"], c["circuit"]["id"])
    first = get_success_data(api_client.clear_title(c["title"]["id"], PROG))
    second = get_success_data(api_client.reopen_title_bookings(c["title"]["id"], PROG))
    assert first["status"] == "CLEARED"
    assert second["status"] == "BOOKABLE", (
        "it returns to the state it already held, which no forward-only pipeline can "
        "express"
    )


def test_title_revision_loop_leaves_the_existing_booking_undisturbed():
    """PRD §3.1: "Clearing locks the title against *new* negotiations while leaving
    every existing booking untouched — no downstream record changes at all."

    Design: Corner/state_machines/title_clear_then_reopen_is_a_revision_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"], guarantee_cents=1000000)
    api_client.clear_title(c["title"]["id"], PROG)
    api_client.reopen_title_bookings(c["title"]["id"], PROG)
    current = get_booking(booking["id"])
    assert current["status"] == "DRAFT"
    assert current["guarantee_cents"] == 1000000