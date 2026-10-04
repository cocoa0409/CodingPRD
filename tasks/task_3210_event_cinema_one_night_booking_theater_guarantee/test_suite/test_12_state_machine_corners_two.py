"""More state-machine corners: terminal lockdowns, side effects and cascade gates."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, first_screening, confirm_booking, get_line,
    create_settlement_payload, make_distributor_headers, make_theater_headers,
    create_encryption_key_payload, report_screening, get_key, get_theater,
    setup_circuit_venue_title, create_content_delivery_payload, get_circuit,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
FIN = TEST_USERS["finance_ops_headers"]
OFFICER = TEST_USERS["content_officer_headers"]


def _confirmed_reported_settled_scene():
    """Confirmed booking, screening reported, settlement created (and closed)."""
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
    booking = get_booking(booking["id"])
    booking = confirm_booking(booking["id"], booking["version"])
    screening = first_screening(booking["id"])
    report_screening(screening["id"], c["theater"]["id"], 175, "SCREENED",
                     at_instant="2026-12-01T21:30:00Z")
    booking = get_booking(booking["id"])
    settlement = get_success_data(api_client.create_settlement(
        create_settlement_payload(booking["id"], gross_box_office_cents=3000000),
        FIN))
    c.update({"booking": get_booking(booking["id"]), "line": line,
              "screening": screening, "settlement": settlement})
    return c


def test_ordinary_cancellation_is_refused_after_the_settlement_closed():
    """PRD §3.2: "A whole booking may instead be cancelled from `APPROVED`, which
    requires that no settlement of the booking has closed".
    PRD §3.6: "The ordinary cancellation move may be performed by an exhibitor or a
    distributor and requires that no settlement of the booking has closed".

    Design: Corner/state_machines/booking_cancel_is_refused_after_the_settlement_closed
    """
    c = _confirmed_reported_settled_scene()
    assert c["settlement"]["status"] == "CLOSED"
    resp = api_client.cancel_booking(
        c["booking"]["id"], c["booking"]["version"],
        make_distributor_headers(c["distributor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_compensating_cancellation_is_refused_after_the_settlement_closed():
    """PRD §3.6: "Cancelling with compensation is a distributor-only move that exists
    to unwind a confirmed run as an explicit compensating action ... and it carries the
    additional restriction that a settlement of the booking must not already be
    `CLOSED`".

    Design: Corner/state_machines/booking_cancel_is_refused_after_the_settlement_closed
    """
    c = _confirmed_reported_settled_scene()
    resp = api_client.cancel_booking_with_compensation(
        c["booking"]["id"], c["booking"]["version"],
        make_distributor_headers(c["distributor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    assert get_booking(c["booking"]["id"])["status"] == "SETTLED", (
        "the booking remains settled-but-standing"
    )


def test_feed_event_confirmation_revokes_the_affected_screenings_key():
    """PRD §3.5: "revokes every encryption key attached to those affected screenings
    with reason `FEED_LOSS` while incrementing the venue's `pending_rekey_count` once
    per revoked key"
    PRD §3.4: "Revocation records the supplied `revocation_reason`".

    Design: Corner/state_machines/feed_event_confirm_executes_its_revocation_side_effect
    """
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
    delivery = get_success_data(api_client.create_content_delivery(
        create_content_delivery_payload(booking["id"], booking["version"],
                                       delivery_method="SATELLITE",
                                       content_checksum="sha256:dd11ee22"), OPS))
    get_success_data(api_client.mark_delivery_delivered(
        delivery["id"], "sha256:dd11ee22", OPS))
    get_success_data(api_client.verify_delivery(delivery["id"], OPS))
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    screening = first_screening(booking["id"])
    key = get_success_data(api_client.create_encryption_key(
        create_encryption_key_payload(screening["id"],
                                      not_valid_before_utc="2026-12-01T19:00:00Z",
                                      not_valid_after_utc="2026-12-01T21:00:00Z"), OPS))
    get_success_data(api_client.issue_key(key["id"], OPS))
    event = get_success_data(api_client.create_feed_event({
        "booking_id": booking["id"], "failure_type": "SATELLITE_OUTAGE",
        "detected_at_utc": "2026-12-01T19:05:00Z", "outage_minutes": 20}, OPS))
    set_clock("2026-12-01T19:30:00Z")
    confirmed = get_success_data(api_client.confirm_feed_event(event["id"], TEST_USERS["platform_ops_headers_2"]))
    assert confirmed["state"] == "CONFIRMED"
    assert confirmed["affected_screening_count"] == 1
    assert get_key(key["id"])["issuance_status"] == "REVOKED"


def test_feed_event_confirmation_attributes_the_reason_to_the_feed_loss():
    """PRD §3.5: "revokes every encryption key attached to those affected screenings
    with reason `FEED_LOSS`".

    Design: Corner/state_machines/feed_event_confirm_executes_its_revocation_side_effect
    """
    c = _feed_event_key_scene()
    assert get_key(c["key"]["id"])["issuance_status"] == "REVOKED"
    assert get_key(c["key"]["id"])["revocation_reason"] == "FEED_LOSS"
    assert get_theater(c["theater"]["id"])["pending_rekey_count"] == 1


def _feed_event_key_scene():
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
    delivery = get_success_data(api_client.create_content_delivery(
        create_content_delivery_payload(booking["id"], booking["version"],
                                       delivery_method="SATELLITE",
                                       content_checksum="sha256:dd11ee22"), OPS))
    get_success_data(api_client.mark_delivery_delivered(
        delivery["id"], "sha256:dd11ee22", OPS))
    get_success_data(api_client.verify_delivery(delivery["id"], OPS))
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    screening = first_screening(booking["id"])
    key = get_success_data(api_client.create_encryption_key(
        create_encryption_key_payload(screening["id"],
                                      not_valid_before_utc="2026-12-01T19:00:00Z",
                                      not_valid_after_utc="2026-12-01T21:00:00Z"), OPS))
    get_success_data(api_client.issue_key(key["id"], OPS))
    event = get_success_data(api_client.create_feed_event({
        "booking_id": booking["id"], "failure_type": "SATELLITE_OUTAGE",
        "detected_at_utc": "2026-12-01T19:05:00Z", "outage_minutes": 20}, OPS))
    set_clock("2026-12-01T19:30:00Z")
    get_success_data(api_client.confirm_feed_event(event["id"], TEST_USERS["platform_ops_headers_2"]))
    c.update({"booking": get_booking(booking["id"]), "line": line,
              "screening": screening, "key": key})
    return c


def _circuit_suspension_scene():
    """Two bookings on one circuit: one still DRAFT with a proposed line, one ON_SALE
    with a committed 40-screen line. Suspends the circuit and returns the scene."""
    c = setup_circuit_venue_title()
    on_sale = create_booking(c["title"]["id"], c["circuit"]["id"])
    line_b = add_line(on_sale["id"], c["circuit"]["id"], c["theater"]["id"],
                      on_sale["version"], committed_screens=40,
                      expected_attendance=100)
    on_sale = submit_booking(on_sale["id"], c["circuit"]["id"], line_b["version"])
    on_sale = approve_booking(on_sale["id"], c["distributor"]["id"],
                              on_sale["version"], line_b["id"])
    line_b = get_line(line_b["id"])
    set_clock(on_sale["on_sale_at"])
    run_on_sale_sweep()
    draft = create_booking(c["title"]["id"], c["circuit"]["id"],
                           showtime_plan=[{"index": 1,
                                           "date_utc": "2026-12-03T00:00:00Z",
                                           "start_minute_utc": 1140,
                                           "auditorium": "AUD-2"}],
                           on_sale_at="2026-10-05T00:00:00Z")
    line_a = add_line(draft["id"], c["circuit"]["id"], c["theater"]["id"],
                      draft["version"], committed_screens=20,
                      expected_attendance=60)
    suspended = get_success_data(
        api_client.suspend_circuit(c["circuit"]["id"], OPS))
    c.update({"draft_booking": draft, "draft_line": line_a,
              "on_sale_booking": get_booking(on_sale["id"]),
              "on_sale_line": line_b, "suspended": suspended})
    return c


def test_circuit_suspension_cancels_the_draft_booking_and_releases_its_line():
    """PRD §3.1: "it moves the circuit to `SUSPENDED` and unwinds every booking it
    holds in `DRAFT`, `PENDING_APPROVAL`, `COUNTERED`, or `APPROVED`".

    Design: Corner/state_machines/circuit_suspend_cascades_to_uncommitted_bookings
    """
    c = _circuit_suspension_scene()
    assert c["suspended"]["status"] == "SUSPENDED"
    assert get_booking(c["draft_booking"]["id"])["status"] == "CANCELLED"
    assert get_line(c["draft_line"]["id"])["exhibit_state"] == "RELEASED"


def test_circuit_suspension_leaves_the_on_sale_booking_untouched():
    """PRD §3.1: "It is refused if any booking of that circuit is currently `ON_HOLD`,
    because a held run is mid-flight and must be resolved rather than silently
    unwound."
    PRD §2.10: "A circuit's `committed_screens_balance` is the number of screens
    currently committed by that circuit's non-terminal bookings".

    Design: Corner/state_machines/circuit_suspend_cascades_to_uncommitted_bookings
    """
    c = _circuit_suspension_scene()
    assert get_booking(c["on_sale_booking"]["id"])["status"] == "ON_SALE", (
        "a booking that has reached ON_SALE is deliberately untouched"
    )
    assert get_circuit(c["circuit"]["id"])["committed_screens_balance"] == 40


def test_marking_a_package_failed_is_a_terminal_delivery_state():
    """PRD §2.11: "A package that fails verification can never become verified, and the
    consequence is deliberate: the booking's encryption keys remain permanently
    unissuable until a replacement package is registered".

    Design: Corner/state_machines/failed_delivery_blocks_key_issuance_permanently
    """
    c = _ready_booking_with_deliveries([("sha256:expected0000", "sha256:corrupt9999")])
    failed = get_success_data(
        api_client.mark_delivery_failed(c["deliveries"][0]["id"], OFFICER))
    assert failed["status"] == "FAILED"


def test_key_issuance_is_blocked_while_only_a_failed_package_exists():
    """PRD §2.11: "the booking's encryption keys remain permanently unissuable until a
    replacement package is registered".

    Design: Corner/state_machines/failed_delivery_blocks_key_issuance_permanently
    """
    c = _ready_booking_with_deliveries([("sha256:expected0000", "sha256:corrupt9999")])
    get_success_data(api_client.mark_delivery_failed(c["deliveries"][0]["id"], OFFICER))
    resp = api_client.issue_key(c["key"]["id"], OPS)
    validate_error(resp, ApiErrorId.ERR_DELIVERY_NOT_VERIFIED, 409)


def test_a_replacement_package_verifies_and_unblocks_key_issuance():
    """PRD §3.4: "until a replacement package is registered and verified, no key of
    that booking can be issued at all, and the run cannot be played."

    Design: Corner/state_machines/failed_delivery_blocks_key_issuance_permanently
    """
    c = _ready_booking_with_deliveries([("sha256:expected0000", "sha256:corrupt9999"),
                                        ("sha256:good1111", "sha256:good1111")])
    get_success_data(api_client.mark_delivery_failed(c["deliveries"][0]["id"], OFFICER))
    replacement = c["deliveries"][1]
    # The replacement package is already `DELIVERED` from the fixture's delivery
    # step; §2.11 only admits `mark-delivered` from `SCHEDULED`, so the test verifies
    # the package it has rather than re-delivering it.
    assert replacement["status"] == "DELIVERED"
    verified = get_success_data(api_client.verify_delivery(replacement["id"], OPS))
    assert verified["status"] == "VERIFIED"
    issued = get_success_data(api_client.issue_key(c["key"]["id"], OPS))
    assert issued["issuance_status"] == "ISSUED"


def _ready_booking_with_deliveries(package_specs):
    """ON_SALE booking with one key and one package per (expected, delivered) pair."""
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
    booking = get_booking(booking["id"])
    deliveries = []
    for expected, delivered in package_specs:
        # §2.6: registering a package advances the booking's version, so each
        # registration must attest the version observed immediately before it.
        booking = get_booking(booking["id"])
        package = get_success_data(api_client.create_content_delivery(
            create_content_delivery_payload(booking["id"], booking["version"],
                                           delivery_method="FILE",
                                           content_checksum=expected), OPS))
        package = get_success_data(api_client.mark_delivery_delivered(
            package["id"], delivered, OPS))
        deliveries.append(package)
    booking = get_booking(booking["id"])
    screening = first_screening(booking["id"])
    key = get_success_data(api_client.create_encryption_key(
        create_encryption_key_payload(screening["id"],
                                      not_valid_before_utc="2026-12-01T19:00:00Z",
                                      not_valid_after_utc="2026-12-01T21:00:00Z"), OPS))
    c.update({"booking": booking, "line": line, "screening": screening,
              "key": key, "deliveries": deliveries})
    return c