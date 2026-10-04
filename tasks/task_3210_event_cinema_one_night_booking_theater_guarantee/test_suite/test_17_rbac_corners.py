"""Role separation corners: each role owns a disjoint operation set."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, first_screening, first_screening as fs,
    get_circuit, get_line, make_distributor_headers, make_theater_headers,
    setup_circuit_venue_title, validate_paginated,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def test_theater_role_cannot_submit_a_booking():
    """PRD §4: "The catalogue below names the authorized role for each operation; every
    read operation is open to the roles listed, and a request from any other role is
    refused with `ERR_FORBIDDEN`."

    Design: Corner/rbac/theater_role_cannot_submit_a_booking
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    resp = api_client.submit_booking(booking["id"], booking["version"],
                                     make_theater_headers(c["theater"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_the_refused_submit_leaves_the_booking_in_draft():
    """PRD §2.1: "A request whose acting role is not permitted on the targeted
    operation ... is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/theater_role_cannot_submit_a_booking
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    api_client.submit_booking(booking["id"], booking["version"],
                              make_theater_headers(c["theater"]["id"]))
    assert get_booking(booking["id"])["status"] == "DRAFT"
    submitted = submit_booking(booking["id"], c["circuit"]["id"], booking["version"])
    assert submitted["status"] == "PENDING_APPROVAL"


def test_exhibitor_role_cannot_approve_its_own_booking():
    """PRD §3.2: "Approval is the distributor's commitment of a single venue line, and
    it is the point at which a negotiation becomes a schedule."

    Design: Corner/rbac/exhibitor_role_cannot_approve_its_own_booking
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    resp = api_client.approve_booking(booking["id"], booking["version"],
                                      c["exhibitor_headers"], line["id"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_the_refused_approval_moves_no_screens_then_the_distributor_succeeds():
    """PRD §3.2: "The distributor submits the `line_id` of the line to commit, together
    with its `expected_booking_version`."

    Design: Corner/rbac/exhibitor_role_cannot_approve_its_own_booking
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    api_client.approve_booking(booking["id"], booking["version"],
                               c["exhibitor_headers"], line["id"])
    assert get_circuit(c["circuit"]["id"])["committed_screens_balance"] == 0
    approved = approve_booking(booking["id"], c["distributor"]["id"],
                               booking["version"], line["id"])
    line = get_line(line["id"])
    booking = get_booking(booking["id"])
    assert approved["status"] == "APPROVED"


def test_attendance_cannot_be_reported_by_a_distributor():
    """PRD §4: "POST | `/event-cinema/screenings/{id}/report` | File the exhibited
    outcome and headcount for a screening. | Theater".
    PRD §3.6: "A `Theater` files a report against a screening with
    `reported_attendance` and a `reported_outcome`."

    Design: Corner/rbac/attendance_cannot_be_reported_by_a_distributor
    """
    set_clock("2026-09-01T00:00:00Z")
    c = _on_sale_scene()
    set_clock("2026-12-01T21:30:00Z")
    resp = api_client.report_screening(
        c["screening"]["id"], 175, "SCREENED",
        make_distributor_headers(c["distributor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_the_venues_own_report_is_the_one_that_lands():
    """PRD §3.6: "Reporting requires that the current clock instant has reached the
    screening's `ends_at`".

    Design: Corner/rbac/attendance_cannot_be_reported_by_a_distributor
    """
    set_clock("2026-09-01T00:00:00Z")
    c = _on_sale_scene()
    set_clock("2026-12-01T21:30:00Z")
    api_client.report_screening(c["screening"]["id"], 175, "SCREENED",
                                make_distributor_headers(c["distributor"]["id"]))
    reported = get_success_data(api_client.report_screening(
        c["screening"]["id"], 175, "SCREENED",
        make_theater_headers(c["theater"]["id"])))
    assert reported["state"] == "SCREENED"
    assert reported["reported_attendance"] == 175


def test_content_officer_cannot_invent_a_venue_commitment():
    """PRD §2.1: "A request whose acting role is not permitted on the targeted
    operation ... is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/content_officer_cannot_invent_the_venue_commitment
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    resp = api_client.add_booking_line(booking["id"], {
        "theater_id": c["theater"]["id"], "committed_screens": 20,
        "expected_attendance": 40,
        "expected_booking_version": booking["version"],
    }, TEST_USERS["content_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_refused_commitment_from_the_content_officer_creates_no_line():
    """PRD §4: "POST | `/event-cinema/bookings/{id}/lines` | Propose a venue commitment
    line on a DRAFT booking, under optimistic concurrency on the booking. | Exhibitor".

    Design: Corner/rbac/content_officer_cannot_invent_the_venue_commitment
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    api_client.add_booking_line(booking["id"], {
        "theater_id": c["theater"]["id"], "committed_screens": 20,
        "expected_attendance": 40,
        "expected_booking_version": booking["version"],
    }, TEST_USERS["content_officer_headers"])
    rows, _meta = validate_paginated(api_client.list_booking_lines(booking["id"], OPS))
    assert rows == []
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=20,
                    expected_attendance=40)
    assert line["exhibit_state"] == "PROPOSED"


def _on_sale_scene():
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
    c.update({"booking": get_booking(booking["id"]), "line": line,
              "screening": first_screening(booking["id"])})
    return c