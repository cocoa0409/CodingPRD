"""Catalogue registration: creation contracts, defaults, listings and type constraints."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, ApiErrorId, NON_EXISTENT_UUID, is_iso8601_timestamp, is_valid_uuid,
    set_clock, create_distributor, create_circuit, create_theater, create_title,
    create_booking, add_line, get_circuit, get_distributor, unique_circuit_code,
    make_exhibitor_headers, make_distributor_headers, make_theater_headers,
    setup_circuit_venue_title,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def test_distributor_create_returns_declared_fields_and_starts_active():
    """PRD §3.1: "A `PlatformOps` operator registers a `Distributor` with
    `distributor_name`, `contact_email`, a `settlement_currency` defaulting to `USD`, a
    `guarantee_floor_cents`, and a `ticket_price_default_cents`."
    PRD §3.1: "A new distributor begins `ACTIVE`, and a platform operator can move it
    to `SUSPENDED` or back to `ACTIVE`".
    PRD §2.10: "a distributor's `bookable_title_count` counts the titles under that
    distributor whose `status` is `BOOKABLE`."

    Design: Corner/entities/distributor_create_returns_declared_fields_and_starts_active
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_distributor({
        "distributor_name": "Halcyon Concert Films",
        "contact_email": "booking@halcyon.example",
        "settlement_currency": "USD",
        "guarantee_floor_cents": 250000,
        "ticket_price_default_cents": 1250,
    }, OPS)
    data = validate_success(resp, expected_status=201)
    assert is_valid_uuid(data["id"])
    assert is_iso8601_timestamp(data["created_at"])
    assert data["distributor_name"] == "Halcyon Concert Films"
    assert data["ticket_price_default_cents"] == 1250
    assert data["status"] == "ACTIVE", "status is system-set, never client-supplied"
    assert data["bookable_title_count"] == 0


def test_circuit_create_returns_pending_status_and_zero_balance():
    """PRD §3.1: "A circuit starts `PENDING` and must be accredited before it may
    commit anything".
    PRD §3.1: "an `on_sale_lead_days_min` that defaults to 21 days".
    PRD §2.10: "A circuit's `committed_screens_balance` is the number of screens
    currently committed by that circuit's non-terminal bookings".

    Design: Corner/entities/circuit_create_returns_pending_status_and_zero_balance
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.create_circuit({
        "circuit_name": "Northgate Screen Partners",
        "circuit_code": "NGSP",
        "credit_rating": "C",
        "settlement_terms": "FOUR_WALL",
        "screen_pool_total": 120,
    }, OPS)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING"
    assert data["on_sale_lead_days_min"] == 21
    assert data["committed_screens_balance"] == 0
    assert data["credit_rating"] == "C"
    assert data["settlement_terms"] == "FOUR_WALL"


def test_theater_get_with_an_unknown_id_returns_theater_not_found():
    """PRD §2.4: "an unknown venue `ERR_THEATER_NOT_FOUND`".

    Design: Corner/entities/theater_get_with_an_unknown_id_returns_theater_not_found
    """
    set_clock("2026-09-01T00:00:00Z")
    resp = api_client.get_theater("3f1a7c22-0000-4000-8000-000000000000", OPS)
    err = validate_error(resp, ApiErrorId.ERR_THEATER_NOT_FOUND, 404)
    assert len(err["message"].strip()) > 0


def test_theaters_list_filters_by_circuit_and_reports_total_count():
    """PRD §2.3: "Every list response carries the four pagination fields in the `meta`
    object of the envelope: `limit`, `offset`, `total_count` (the size of the full
    result set before paging), and `has_more` (true when further pages remain)."
    PRD §2.3: "The filters available across the API are the reference fields by which a
    collection is naturally scoped — `booking_id`, `theater_id`, `title_id`,
    `circuit_id`, `distributor_id`, and `screening_id`".
    PRD §2.3: "`limit` caps the number of items returned, defaulting to 10 when omitted".

    Design: Corner/entities/theaters_list_filters_by_circuit_and_reports_total_count
    """
    set_clock("2026-09-01T00:00:00Z")
    circuit = create_circuit()
    other = create_circuit()
    venues = [
        create_theater(circuit["id"], theater_name="Cedar Point Sacramento",
                       city="Sacramento", state_code="CA"),
        create_theater(circuit["id"], theater_name="Cedar Point Reno",
                       city="Reno", state_code="NV"),
        create_theater(circuit["id"], theater_name="Cedar Point Boise",
                       city="Boise", state_code="ID"),
        create_theater(other["id"], theater_name="Alto Vista Tucson",
                       city="Tucson", state_code="AZ"),
    ]
    page1, meta1 = validate_paginated(api_client.list_theaters(
        OPS, {"circuit_id": circuit["id"], "limit": 2, "offset": 0}))
    page2, meta2 = validate_paginated(api_client.list_theaters(
        OPS, {"circuit_id": circuit["id"], "limit": 2, "offset": 2}))
    assert len(page1) == 2
    assert len(page2) == 1
    assert meta1["total_count"] == 3, "total_count counts the filtered set, not the page"
    assert meta2["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta2["has_more"] is False
    assert venues[3]["id"] not in [row["id"] for row in page1 + page2]
    everything, meta_all = validate_paginated(api_client.list_theaters(OPS))
    assert meta_all["total_count"] == 4
    assert meta_all["limit"] == 10
    assert meta_all["offset"] == 0


def test_title_create_computes_bookable_window_days():
    """PRD §2.10: "its `bookable_window_days` is the whole number of days between
    `rights_start_utc` and `rights_end_utc`".
    PRD §3.1: "A title is born `DRAFT`."
    PRD §2.9: "The states in which a title may be exhibited are listed on the title as
    `territory_state_codes`, which must contain at least one element".

    Design: Corner/entities/title_create_computes_bookable_window_days
    """
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000)
    resp = api_client.create_title({
        "distributor_id": distributor["id"],
        "title_name": "Winter Light Sessions",
        "content_type": "CONCERT",
        "is_live": False,
        "duration_minutes": 105,
        "rights_start_utc": "2026-09-01T00:00:00Z",
        "rights_end_utc": "2027-03-01T00:00:00Z",
        "territory_state_codes": ["CA"],
        "max_screen_commitment": 200,
        "ticket_price_cents": 1400,
    }, PROG)
    data = validate_success(resp, expected_status=201)
    assert data["bookable_window_days"] == 181, "2026-09-01 to 2027-03-01 is 181 days"
    assert data["status"] == "DRAFT"
    assert data["rights_start_utc"].startswith("2026-09-01")
    assert data["rights_end_utc"].startswith("2027-03-01")
    assert data["territory_state_codes"] == ["CA"]


def test_title_publish_updates_distributor_bookable_count():
    """PRD §3.1: "Publishing recomputes the distributor's `bookable_title_count`."
    PRD §2.10: "Every one of these figures is derived and recomputed; none is
    decremented in place."

    Design: Corner/entities/title_publish_updates_distributor_bookable_count
    """
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000)
    title = create_title(distributor["id"], publish=False)
    assert get_distributor(distributor["id"])["bookable_title_count"] == 0
    published = get_success_data(api_client.publish_title(title["id"], PROG))
    assert published["status"] == "BOOKABLE"
    assert get_distributor(distributor["id"])["bookable_title_count"] == 1
    get_success_data(api_client.unpublish_title(title["id"], PROG))
    assert get_distributor(distributor["id"])["bookable_title_count"] == 0


def test_booking_create_stamps_negotiating_user_from_header():
    """PRD §3.1: "The `negotiating_user_id` is stamped from the `X-User-ID` header of
    the request and records the distributor principal who opened the negotiation; it is
    never supplied by the client."

    Design: Corner/entities/booking_create_stamps_negotiating_user_from_header
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"],
                             negotiating_user_id="somebody-else")
    assert booking["negotiating_user_id"] == c["circuit"]["id"], (
        "the acting exhibitor's header value wins over any client-supplied field"
    )


def test_booking_create_accepts_the_declared_two_showtime_plan():
    """PRD §3.1: "`showtime_count` must be exactly 1 or 2 — this is a one-night or
    two-night business and the API enforces it, not merely documents it — and
    `showtime_plan` must be an array carrying exactly that many elements."

    Design: Corner/entities/booking_create_stamps_negotiating_user_from_header
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"], showtime_count=2,
                             showtime_plan=[
                                 {"index": 1, "date_utc": "2026-12-01T00:00:00Z",
                                  "start_minute_utc": 1140, "auditorium": "AUD-1"},
                                 {"index": 2, "date_utc": "2026-12-02T00:00:00Z",
                                  "start_minute_utc": 1140, "auditorium": "AUD-1"}],
                             guarantee_cents=1000000, revenue_share_pct=0.40)
    assert booking["status"] == "DRAFT"
    assert booking["showtime_count"] == 2
    assert booking["guarantee_cents"] == 1000000
    assert booking["revenue_share_pct"] == 0.40


def test_duplicate_circuit_code_is_rejected():
    """PRD §3.1: "A second circuit claiming an existing `circuit_code` is refused with
    `ERR_DUPLICATE_CIRCUIT_CODE`."

    Design: Corner/entities/duplicate_circuit_code_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    create_circuit(circuit_code="CEDR")
    resp = api_client.create_circuit({
        "circuit_name": "A Completely Different Chain",
        "circuit_code": "CEDR",
        "credit_rating": "A",
        "settlement_terms": "NET_60",
        "screen_pool_total": 500,
    }, OPS)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CIRCUIT_CODE, 409)
    _rows, meta = validate_paginated(api_client.list_circuits(OPS))
    assert meta["total_count"] == 1


def test_title_content_type_enum_rejects_an_unknown_value():
    """PRD §3.1: "The creative asset itself is the `Title`, acquired by a
    `ProgrammingManager` with a `distributor_id`, a `title_name`, a `content_type` of
    `CONCERT`, `ANNIVERSARY`, `FAITH`, `LIVE_BROADCAST`, or `SPECIAL`".
    PRD §5: "The table below lists every error identifier this API can return together
    with its HTTP status."

    Design: Corner/entities/title_content_type_enum_rejects_an_unknown_value
    """
    set_clock("2026-09-01T00:00:00Z")
    distributor = create_distributor(guarantee_floor_cents=10000)
    resp = api_client.create_title({
        "distributor_id": distributor["id"],
        "title_name": "Interview Hour",
        "content_type": "PODCAST",
        "is_live": False,
        "duration_minutes": 60,
        "rights_start_utc": "2026-09-01T00:00:00Z",
        "rights_end_utc": "2027-03-01T00:00:00Z",
        "territory_state_codes": ["CA"],
        "max_screen_commitment": 50,
        "ticket_price_cents": 1200,
    }, PROG)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
    _rows, meta = validate_paginated(api_client.list_titles(
        PROG, {"distributor_id": distributor["id"]}))
    assert meta["total_count"] == 0