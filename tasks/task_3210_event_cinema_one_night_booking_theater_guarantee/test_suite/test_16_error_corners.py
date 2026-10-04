"""Error-reachability corners: the same guard firing from a second endpoint or method."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, make_distributor_headers,
    make_exhibitor_headers, validate_paginated, setup_circuit_venue_title,
    create_distributor, create_circuit, create_theater, create_title, get_line,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def test_line_create_against_an_unusable_parent_returns_invalid_state():
    """PRD §2.4: "an attempt to run a transition the resource's current state does not
    admit of is `ERR_INVALID_STATE`".
    PRD §3.1: "With the negotiation open, the exhibitor proposes venue commitments one
    at a time."

    Design: Corner/errors/line_create_against_an_unusable_parent_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    other = create_theater(c["circuit"]["id"], theater_name="Trellis Oakland",
                           city="Oakland", state_code="CA")
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"],
                             get_booking(booking["id"])["version"])
    assert booking["status"] == "PENDING_APPROVAL"
    resp = api_client.add_booking_line(booking["id"], {
        "theater_id": other["id"], "committed_screens": 20,
        "expected_attendance": 40,
        "expected_booking_version": booking["version"],
    }, c["exhibitor_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_refused_late_line_leaves_the_line_count_unchanged():
    """PRD §2.4: "Existence comes next, as described above. Only then does the system
    evaluate whether the target resource is in a state from which the requested
    transition is declared."

    Design: Corner/errors/line_create_against_an_unusable_parent_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    other = create_theater(c["circuit"]["id"], theater_name="Trellis Oakland",
                           city="Oakland", state_code="CA")
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"],
                             get_booking(booking["id"])["version"])
    api_client.add_booking_line(booking["id"], {
        "theater_id": other["id"], "committed_screens": 20,
        "expected_attendance": 40,
        "expected_booking_version": booking["version"],
    }, c["exhibitor_headers"])
    rows, _meta = validate_paginated(api_client.list_booking_lines(booking["id"], OPS))
    assert len(rows) == 1


def test_title_withdrawal_is_refused_while_a_booking_is_on_sale():
    """PRD §3.1: "A title in either `BOOKABLE` or `CLEARED` may be withdrawn, but only
    if no booking against it has reached `ON_SALE` or `CONFIRMED` — a run that is
    already selling tickets cannot be yanked."

    Design: Corner/errors/title_archive_on_a_title_with_bookings_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    booking = approve_booking(booking["id"], c["distributor"]["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    assert get_booking(booking["id"])["status"] == "ON_SALE"
    resp = api_client.withdraw_title(c["title"]["id"], PROG)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_refused_withdrawal_leaves_the_title_untouched():
    """PRD §3.1: "A title in either `BOOKABLE` or `CLEARED` may be withdrawn, but only
    if no booking against it has reached `ON_SALE` or `CONFIRMED`".

    Design: Corner/errors/title_archive_on_a_title_with_bookings_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    booking = approve_booking(booking["id"], c["distributor"]["id"],
                              booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    api_client.withdraw_title(c["title"]["id"], PROG)
    assert get_success_data(api_client.get_title(c["title"]["id"], PROG))["status"] == \
        "BOOKABLE"


def test_stale_booking_version_is_rejected_on_line_add():
    """PRD §2.5: "If that value does not equal the booking's current `version`, the
    request is rejected with `ERR_STALE_VERSION` and HTTP status 412, and no mutation is
    applied."

    Design: Corner/errors/stale_booking_version_is_rejected_on_line_add
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    other = create_theater(c["circuit"]["id"], theater_name="Trellis Oakland",
                           city="Oakland", state_code="CA")
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    stale_version = booking["version"]
    add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
             stale_version, committed_screens=60, expected_attendance=100)
    resp = api_client.add_booking_line(booking["id"], {
        "theater_id": other["id"], "committed_screens": 20,
        "expected_attendance": 40,
        "expected_booking_version": stale_version,
    }, c["exhibitor_headers"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_the_current_version_succeeds_after_a_stale_attempt():
    """PRD §2.5: "In every one of the three, a client working from a stale view must not
    have that view applied."

    Design: Corner/errors/stale_booking_version_is_rejected_on_line_add
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    other = create_theater(c["circuit"]["id"], theater_name="Trellis Oakland",
                           city="Oakland", state_code="CA")
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    stale_version = booking["version"]
    add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
             stale_version, committed_screens=60, expected_attendance=100)
    api_client.add_booking_line(booking["id"], {
        "theater_id": other["id"], "committed_screens": 20,
        "expected_attendance": 40,
        "expected_booking_version": stale_version,
    }, c["exhibitor_headers"])
    current = get_booking(booking["id"])
    fresh = get_success_data(api_client.add_booking_line(booking["id"], {
        "theater_id": other["id"], "committed_screens": 20,
        "expected_attendance": 40,
        "expected_booking_version": current["version"],
    }, c["exhibitor_headers"]))
    assert fresh["exhibit_state"] == "PROPOSED"


def test_unknown_booking_id_returns_booking_not_found():
    """PRD §2.4: "an unknown booking `ERR_BOOKING_NOT_FOUND`".
    PRD §2.4: "none is created through a nested parent URL".

    Design: Corner/errors/unknown_booking_id_returns_booking_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.get_booking("3f1a7c22-0000-4000-8000-0000000000aa", OPS)
    err = validate_error(resp, ApiErrorId.ERR_BOOKING_NOT_FOUND, 404)
    assert len(err["message"].strip()) > 0