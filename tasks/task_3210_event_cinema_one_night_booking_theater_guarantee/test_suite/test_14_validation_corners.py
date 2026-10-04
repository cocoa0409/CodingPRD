"""Validation corners: auth layering, existence ordering, scope gates and aggregate bounds."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, make_distributor_headers,
    make_exhibitor_headers, make_theater_headers, setup_circuit_venue_title,
    create_circuit, create_theater, create_distributor, create_title,
    validate_paginated, get_circuit, get_line,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def test_missing_role_header_is_rejected_before_anything_else():
    """PRD §2.1: "A request that omits either header, or that presents an
    `X-User-Role` value that is not one of the roles enumerated below, is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD §2.4: "Authentication is decided before anything else: a request missing a
    header or presenting an unrecognised role never reaches an existence check".

    Design: Corner/validations/missing_role_header_is_rejected_before_anything_else
    """
    set_clock("2026-09-01T00:00:00Z")
    create_distributor()
    resp = api_client.create_booking({
        "title_id": "3f1a7c22-0000-4000-8000-000000000001",
        "circuit_id": "3f1a7c22-0000-4000-8000-000000000002",
        "showtime_count": 1,
        "showtime_plan": [{"index": 1, "date_utc": "2026-12-01T00:00:00Z",
                           "start_minute_utc": 1140, "auditorium": "AUD-1"}],
        "on_sale_at": "2026-10-01T00:00:00Z",
        "guarantee_cents": 1000000,
        "revenue_share_pct": 0.40,
        "min_screens": 1,
        "pre_sale_threshold": 0,
    }, {"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_a_role_outside_the_endpoint_allowlist_is_forbidden():
    """PRD §2.1: "A request whose acting role is not permitted on the targeted
    operation, or whose `X-User-ID` does not resolve to an existing instance of the
    role's backing entity, is rejected with `ERR_FORBIDDEN`."

    Design: Corner/validations/a_role_outside_the_endpoint_allowlist_is_forbidden
    """
    set_clock("2026-09-01T00:00:00Z")
    create_distributor()
    circuit = create_circuit()
    theater = create_theater(circuit["id"])
    resp = api_client.create_distributor({
        "distributor_name": "Rogue Licensor",
        "contact_email": "x@y.example",
        "settlement_currency": "USD",
        "guarantee_floor_cents": 1000,
        "ticket_price_default_cents": 1000,
    }, make_theater_headers(theater["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
    _rows, meta = validate_paginated(api_client.list_distributors(OPS))
    assert meta["total_count"] == 1


def test_unknown_theater_reference_is_reported_before_state_checks():
    """PRD §2.4: "References carried in the request body are checked in the same pass".
    PRD §2.4: "Existence comes next, as described above. Only then does the system
    evaluate whether the target resource is in a state from which the requested
    transition is declared".

    Design: Corner/validations/an_unknown_title_in_the_body_is_reported_before_state_checks
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    resp = api_client.add_booking_line(booking["id"], {
        "theater_id": "3f1a7c22-0000-4000-8000-0000000000ff",
        "committed_screens": 20,
        "expected_attendance": 50,
        "expected_booking_version": booking["version"],
    }, c["exhibitor_headers"])
    validate_error(resp, ApiErrorId.ERR_THEATER_NOT_FOUND, 404)


def test_unknown_theater_reference_creates_no_line():
    """PRD §2.4: "a resource that fails to resolve is a hard stop: nothing downstream of
    the existence check is evaluated".

    Design: Corner/validations/an_unknown_title_in_the_body_is_reported_before_state_checks
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    api_client.add_booking_line(booking["id"], {
        "theater_id": "3f1a7c22-0000-4000-8000-0000000000ff",
        "committed_screens": 20,
        "expected_attendance": 50,
        "expected_booking_version": booking["version"],
    }, c["exhibitor_headers"])
    rows, _meta = validate_paginated(api_client.list_booking_lines(
        booking["id"], OPS))
    assert rows == []


def test_territory_gate_rejects_a_venue_outside_the_licensed_states():
    """PRD §2.9: "A venue whose `state_code` does not appear in the territory list of
    the title being booked cannot commit screens for that title."

    Design: Corner/validations/territory_gate_rejects_a_venue_outside_the_licensed_states
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    nevada = create_theater(c["circuit"]["id"], theater_name="Cedar Point Reno",
                            city="Reno", state_code="NV")
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    resp = api_client.add_booking_line(booking["id"], {
        "theater_id": nevada["id"], "committed_screens": 40,
        "expected_attendance": 90,
        "expected_booking_version": booking["version"],
    }, c["exhibitor_headers"])
    validate_error(resp, ApiErrorId.ERR_TERRITORY_UNLICENSED, 422)


def test_territory_gate_accepts_the_licensed_state_from_the_identical_payload():
    """PRD §3.1: "a venue whose `state_code` does not appear in the title's territory
    list cannot be committed to that title at all".

    Design: Corner/validations/territory_gate_rejects_a_venue_outside_the_licensed_states
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = get_success_data(api_client.add_booking_line(booking["id"], {
        "theater_id": c["theater"]["id"], "committed_screens": 40,
        "expected_attendance": 90,
        "expected_booking_version": booking["version"],
    }, c["exhibitor_headers"]))
    assert line["exhibit_state"] == "PROPOSED"


def test_rights_window_gate_rejects_a_showtime_after_expiry():
    """PRD §3.1: "The `on_sale_at` instant at which ticketing will open is part of the
    booking itself and must precede every showtime date in the plan; a booking whose
    on-sale instant follows its first showtime is refused with
    `ERR_RIGHTS_WINDOW_VIOLATION`, as is any booking whose showtimes fall outside the
    interval from the title's `rights_start_utc` up to but not including
    `rights_end_utc`."

    Design: Corner/validations/rights_window_gate_rejects_a_showtime_after_expiry
    """
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000)
    circuit = create_circuit()
    title = create_title(distributor["id"], content_type="SPECIAL",
                         rights_end_utc="2026-11-30T00:00:00Z", duration_minutes=90)
    resp = api_client.create_booking({
        "title_id": title["id"], "circuit_id": circuit["id"], "showtime_count": 1,
        "showtime_plan": [{"index": 1, "date_utc": "2026-12-15T00:00:00Z",
                           "start_minute_utc": 1140, "auditorium": "AUD-1"}],
        "on_sale_at": "2026-10-01T00:00:00Z", "guarantee_cents": 1000000,
        "revenue_share_pct": 0.40, "min_screens": 1, "pre_sale_threshold": 0,
    }, make_exhibitor_headers(circuit["id"]))
    validate_error(resp, ApiErrorId.ERR_RIGHTS_WINDOW_VIOLATION, 422)


def test_showtime_inside_the_rights_window_is_accepted():
    """PRD §2.8: "Rights are held for a window that opens at `rights_start_utc` and
    closes at `rights_end_utc`, and the window is a half-open interval".

    Design: Corner/validations/rights_window_gate_rejects_a_showtime_after_expiry
    """
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000)
    circuit = create_circuit()
    title = create_title(distributor["id"], content_type="SPECIAL",
                         rights_end_utc="2026-11-30T00:00:00Z", duration_minutes=90)
    booking = get_success_data(api_client.create_booking({
        "title_id": title["id"], "circuit_id": circuit["id"], "showtime_count": 1,
        "showtime_plan": [{"index": 1, "date_utc": "2026-11-20T00:00:00Z",
                           "start_minute_utc": 1140, "auditorium": "AUD-1"}],
        "on_sale_at": "2026-10-01T00:00:00Z", "guarantee_cents": 1000000,
        "revenue_share_pct": 0.40, "min_screens": 1, "pre_sale_threshold": 0,
    }, make_exhibitor_headers(circuit["id"])))
    assert booking["status"] == "DRAFT"


def test_screen_pool_exhaustion_rejects_the_second_commitment():
    """PRD §3.2: "If the circuit's committed screen balance plus the nominee's
    committed screens would push past the circuit's `screen_pool_total`, the approval is
    refused with `ERR_SCREEN_POOL_EXHAUSTED`."

    Design: Corner/validations/screen_pool_exhaustion_rejects_the_second_commitment
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title(
        circ_overrides={"screen_pool_total": 50},
        dist_overrides={"guarantee_floor_cents": 10000},
        title_overrides={"max_screen_commitment": 200})
    first = _approved_on_pool(c, 40, "AUD-1", "2026-12-01T00:00:00Z")
    second, second_line = _pending_on_pool(c, 20, "AUD-2", "2026-12-02T00:00:00Z")
    assert get_circuit(c["circuit"]["id"])["committed_screens_balance"] == 40
    resp = api_client.approve_booking(
        second["id"], second["version"],
        make_distributor_headers(c["distributor"]["id"]), second_line["id"])
    validate_error(resp, ApiErrorId.ERR_SCREEN_POOL_EXHAUSTED, 409)


def test_screen_pool_exhaustion_leaves_the_rejected_booking_and_balance_intact():
    """PRD §2.10: "Its `screen_pool_total` is the ceiling against which that balance is
    measured".

    Design: Corner/validations/screen_pool_exhaustion_rejects_the_second_commitment
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title(
        circ_overrides={"screen_pool_total": 50},
        dist_overrides={"guarantee_floor_cents": 10000},
        title_overrides={"max_screen_commitment": 200})
    _approved_on_pool(c, 40, "AUD-1", "2026-12-01T00:00:00Z")
    second, second_line = _pending_on_pool(c, 20, "AUD-2", "2026-12-02T00:00:00Z")
    api_client.approve_booking(second["id"], second["version"],
                               make_distributor_headers(c["distributor"]["id"]),
                               second_line["id"])
    assert get_booking(second["id"])["status"] == "PENDING_APPROVAL"
    assert get_circuit(c["circuit"]["id"])["committed_screens_balance"] == 40


def _approved_on_pool(c, screens, auditorium, date_utc):
    booking = create_booking(c["title"]["id"], c["circuit"]["id"],
                             showtime_plan=[{"index": 1, "date_utc": date_utc,
                                             "start_minute_utc": 1140,
                                             "auditorium": auditorium}])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=screens,
                    expected_attendance=100)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    return approve_booking(booking["id"], c["distributor"]["id"],
                           booking["version"], line["id"])


def _pending_on_pool(c, screens, auditorium, date_utc):
    # §3.2: the guarantee may not exceed the ceiling derived from this booking's own
    # committed screens, so the second booking carries a guarantee it can clear —
    # leaving the circuit's screen pool as the only thing its approval trips.
    booking = create_booking(c["title"]["id"], c["circuit"]["id"],
                             guarantee_cents=400000,
                             showtime_plan=[{"index": 1, "date_utc": date_utc,
                                             "start_minute_utc": 1140,
                                             "auditorium": auditorium}])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=screens,
                    expected_attendance=40)
    booking = submit_booking(booking["id"], c["circuit"]["id"], line["version"])
    return booking, line


def test_guarantee_below_the_distributor_floor_is_rejected():
    """PRD §3.1: "The floor is distributor-wide: every booking written under that
    licensor must carry a guarantee at or above it, which is why the floor is checked
    not only when a booking is first opened but again when it is submitted, when the
    licensor counters with new terms, and when the exhibitor re-proposes after a
    counter. Falling below it is `ERR_GUARANTEE_BELOW_FLOOR`."

    Design: Corner/validations/guarantee_below_the_distributor_floor_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    resp = api_client.create_booking({
        "title_id": c["title"]["id"], "circuit_id": c["circuit"]["id"],
        "showtime_count": 1,
        "showtime_plan": [{"index": 1, "date_utc": "2026-12-01T00:00:00Z",
                           "start_minute_utc": 1140, "auditorium": "AUD-1"}],
        "on_sale_at": "2026-10-01T00:00:00Z", "guarantee_cents": 100,
        "revenue_share_pct": 0.40, "min_screens": 1, "pre_sale_threshold": 0,
    }, c["exhibitor_headers"])
    validate_error(resp, ApiErrorId.ERR_GUARANTEE_BELOW_FLOOR, 422)


def test_guarantee_below_floor_creates_no_booking():
    """PRD §3.1: "The floor is distributor-wide: every booking written under that
    licensor must carry a guarantee at or above it".

    Design: Corner/validations/guarantee_below_the_distributor_floor_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    api_client.create_booking({
        "title_id": c["title"]["id"], "circuit_id": c["circuit"]["id"],
        "showtime_count": 1,
        "showtime_plan": [{"index": 1, "date_utc": "2026-12-01T00:00:00Z",
                           "start_minute_utc": 1140, "auditorium": "AUD-1"}],
        "on_sale_at": "2026-10-01T00:00:00Z", "guarantee_cents": 100,
        "revenue_share_pct": 0.40, "min_screens": 1, "pre_sale_threshold": 0,
    }, c["exhibitor_headers"])
    _rows, meta = validate_paginated(api_client.list_bookings(
        OPS, {"circuit_id": c["circuit"]["id"]}))
    assert meta["total_count"] == 0


def test_territory_gate_outranks_the_guarantee_floor_check():
    """PRD §2.4: "Within the business layer the safety and rights checks precede the
    fiscal ones, which is why a showtime falling outside the rights window surfaces as
    `ERR_RIGHTS_WINDOW_VIOLATION` rather than as an unrelated money error."
    PRD §3.1: "Falling below it is `ERR_GUARANTEE_BELOW_FLOOR`."
    PRD §2.9: "A venue whose `state_code` does not appear in the territory list of the
    title being booked cannot commit screens for that title."

    Design: Corner/validations/territory_gate_outranks_the_floor_check
    """
    set_clock("2026-09-01T00:00:00Z")
    # §3.1: the floor is distributor-wide, so a booking that is meant to trip the
    # safety gate instead of the floor must open *above* the floor.
    c = setup_circuit_venue_title(
        dist_overrides={"guarantee_floor_cents": 10000})
    nevada = create_theater(c["circuit"]["id"], theater_name="Cedar Point Reno",
                            city="Reno", state_code="NV")
    # The venue is licensed when the line is proposed, then the title's territory
    # grant shrinks behind it — exactly the change §3.1 anticipates when it says
    # territory "is repeated when screens are committed on approval and when the
    # booking is confirmed".
    c["title"] = get_success_data(api_client.update_title(
        c["title"]["id"], {"territory_state_codes": ["CA", "NV"]}, PROG))
    booking = create_booking(c["title"]["id"], c["circuit"]["id"],
                             guarantee_cents=1000000)
    line = get_success_data(api_client.add_booking_line(booking["id"], {
        "theater_id": nevada["id"], "committed_screens": 40,
        "expected_attendance": 90,
        "expected_booking_version": booking["version"],
    }, c["exhibitor_headers"]))
    assert line["exhibit_state"] == "PROPOSED", (
        "the safety gate is what fires on the unlicensed venue"
    )
    get_success_data(api_client.update_title(
        c["title"]["id"], {"territory_state_codes": ["CA"]}, PROG))
    booking = get_booking(booking["id"])
    resp = api_client.submit_booking(booking["id"], booking["version"],
                                     c["exhibitor_headers"])
    validate_error(resp, ApiErrorId.ERR_TERRITORY_UNLICENSED, 422)
    assert get_booking(booking["id"])["status"] == "DRAFT", (
        "the booking is unchanged after the safety rejection"
    )
