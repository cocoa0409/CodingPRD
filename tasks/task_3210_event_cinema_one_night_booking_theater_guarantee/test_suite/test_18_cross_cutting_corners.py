"""Cross-cutting corners and immediate-consistency races."""
import threading
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, first_screening, get_key, get_line,
    create_encryption_key_payload, create_content_delivery_payload, get_theater,
    setup_circuit_venue_title, make_distributor_headers, make_theater_headers,
    run_race, assert_exactly_one_succeeds, validate_error_is_one_of,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]
OFFICER = TEST_USERS["content_officer_headers"]


def _confirmed_reported_scene():
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
    booking = get_success_data(api_client.confirm_booking(
        booking["id"], booking["version"], OPS))
    c.update({"booking": booking, "line": get_line(line["id"]),
              "screening": first_screening(booking["id"])})
    return c


def _encore_payload(c, expected_booking_version):
    return {
        "booking_id": c["booking"]["id"],
        "window_start_utc": "2026-12-10T00:00:00Z",
        "window_end_utc": "2026-12-20T00:00:00Z",
        "standard_ticket_price_cents": 1500,
        "encore_ticket_price_cents": 1000,
        "planned_screen_count": 25,
        "expected_booking_version": expected_booking_version,
    }


def test_encore_window_creation_rejects_a_stale_booking_version():
    """PRD §2.5: "Adding a booking line, creating an encore window, and registering a
    content delivery each require `expected_booking_version` in the request body".
    PRD §2.5: "If that value does not equal the booking's current `version`, the request
    is rejected with `ERR_STALE_VERSION` and HTTP status 412".

    Design: Corner/cross_cutting_layers/encore_window_create_rejects_a_stale_booking_version
    """
    c = _confirmed_reported_scene()
    stale = c["booking"]["version"]
    set_clock("2026-12-01T21:30:00Z")
    get_success_data(api_client.report_screening(
        c["screening"]["id"], 175, "SCREENED",
        make_theater_headers(c["theater"]["id"])))
    resp = api_client.create_encore_window(_encore_payload(c, stale),
                                           make_distributor_headers(
                                               c["distributor"]["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_the_current_version_is_accepted_for_the_same_encore_payload():
    """PRD §2.5: "encore planning legitimately replaces a prior window on the same
    booking".

    Design: Corner/cross_cutting_layers/encore_window_create_rejects_a_stale_booking_version
    """
    c = _confirmed_reported_scene()
    stale = c["booking"]["version"]
    set_clock("2026-12-01T21:30:00Z")
    get_success_data(api_client.report_screening(
        c["screening"]["id"], 175, "SCREENED",
        make_theater_headers(c["theater"]["id"])))
    api_client.create_encore_window(_encore_payload(c, stale),
                                    make_distributor_headers(c["distributor"]["id"]))
    current = get_booking(c["booking"]["id"])
    created = get_success_data(api_client.create_encore_window(
        _encore_payload(c, current["version"]),
        make_distributor_headers(c["distributor"]["id"])))
    assert created["status"] == "DRAFT"


def test_every_accepted_mutation_advances_the_booking_version_by_one():
    """PRD §2.6: "A mutation to any resource refreshes its `updated_at` and, for the
    entities that carry the system version field, advances `version` by one."
    PRD §3.2: "Each counter, each answer, and each other booking mutation advances the
    booking's version, so the negotiation's participants must re-read between rounds."

    Design: Corner/cross_cutting_layers/booking_version_increments_on_every_accepted_mutation
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    created_version = booking["version"]
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    assert get_line(line["id"])["version"] == created_version, (
        "the *BookingLine's* own version advances by one from its creation value, "
        "while the mutation it causes advances the parent Booking's version"
    )
    booking = get_booking(booking["id"])
    # §2.6: adding a line mutates the Booking, so the Booking's version advances by one.
    assert booking["version"] == created_version + 1
    submitted = submit_booking(booking["id"], c["circuit"]["id"], booking["version"])
    assert submitted["version"] == booking["version"] + 1
    countered = get_success_data(api_client.counter_booking(
        booking["id"], 1500000, 0.35, submitted["version"],
        make_distributor_headers(c["distributor"]["id"])))
    assert countered["version"] == submitted["version"] + 1
    reproposed = get_success_data(api_client.repropose_booking(
        booking["id"], countered["version"], c["exhibitor_headers"]))
    assert reproposed["version"] == countered["version"] + 1


def test_reusing_a_superseded_version_after_a_counter_is_refused():
    """PRD §2.5: "a client working from a stale view must not have that view applied."

    Design: Corner/cross_cutting_layers/booking_version_increments_on_every_accepted_mutation
    """
    set_clock("2026-09-01T00:00:00Z")
    c = setup_circuit_venue_title()
    booking = create_booking(c["title"]["id"], c["circuit"]["id"])
    line = add_line(booking["id"], c["circuit"]["id"], c["theater"]["id"],
                    booking["version"], committed_screens=60,
                    expected_attendance=100)
    submitted = submit_booking(booking["id"], c["circuit"]["id"],
                               get_booking(booking["id"])["version"])
    superseded = submitted["version"]
    countered = get_success_data(api_client.counter_booking(
        booking["id"], 1500000, 0.35, superseded,
        make_distributor_headers(c["distributor"]["id"])))
    # §3.2: the exhibitor's answer returns the booking to PENDING_APPROVAL, so the
    # only thing wrong with the retried approval below is its stale attestation —
    # the state gate must not fire instead.
    get_success_data(api_client.repropose_booking(
        booking["id"], countered["version"], c["exhibitor_headers"]))
    assert get_booking(booking["id"])["status"] == "PENDING_APPROVAL"
    resp = api_client.approve_booking(booking["id"], superseded,
                                      make_distributor_headers(c["distributor"]["id"]),
                                      line["id"])
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def _on_sale_with_issued_key():
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
                                       delivery_method="BOTH",
                                       content_checksum="sha256:b1c2d3e4"), OPS))
    get_success_data(api_client.mark_delivery_delivered(
        delivery["id"], "sha256:b1c2d3e4", OPS))
    get_success_data(api_client.verify_delivery(delivery["id"], OPS))
    set_clock(booking["on_sale_at"])
    run_on_sale_sweep()
    screening = first_screening(booking["id"])
    key = get_success_data(api_client.create_encryption_key(
        create_encryption_key_payload(screening["id"],
                                      not_valid_before_utc="2026-12-01T18:00:00Z",
                                      not_valid_after_utc="2026-12-01T21:00:00Z"), OPS))
    key = get_success_data(api_client.issue_key(key["id"], OPS))
    c.update({"booking": get_booking(booking["id"]), "line": line,
              "screening": screening, "key": key})
    return c


def test_report_is_visible_in_the_same_request():
    """PRD §2.12: "every state cascade triggered by a request is applied atomically
    inside that request".
    PRD §3.6: "Either way the reported headcount is stored on the screening as
    `reported_attendance`, and the line's `sold_tickets` is recomputed as the sum of
    `reported_attendance` over that line's screenings in state `SCREENED`".

    Design: Corner/consistency_model/screening_report_is_visible_in_the_same_request
    """
    c = _on_sale_with_issued_key()
    set_clock("2026-12-01T21:30:00Z")
    reported = get_success_data(api_client.report_screening(
        c["screening"]["id"], 175, "SCREENED",
        make_theater_headers(c["theater"]["id"])))
    assert reported["reported_attendance"] == 175
    assert reported["state"] == "SCREENED"
    assert get_line(c["line"]["id"])["sold_tickets"] == 175
    assert get_booking(c["booking"]["id"])["pre_sale_tickets"] == 0, (
        "presale is tracked separately from post-event attendance"
    )


def test_revocation_is_visible_in_the_same_request():
    """PRD §3.4: "Revocation records the supplied `revocation_reason` and increments the
    owning venue's `pending_rekey_count` by one."
    PRD §3.8: "A fifth capability reissues keys at a venue: given a `theater_id` it
    resets that venue's pending rekey backlog to zero, which is the only operation that
    clears `pending_rekey_count`."

    Design: Corner/consistency_model/revoke_is_visible_in_the_same_request
    """
    c = _on_sale_with_issued_key()
    revoked = get_success_data(api_client.revoke_key(c["key"]["id"], "FEED_LOSS",
                                                     OFFICER))
    assert revoked["issuance_status"] == "REVOKED"
    assert get_theater(c["theater"]["id"])["pending_rekey_count"] == 1
    cleared = get_success_data(api_client.run_rekey_sweep(c["theater"]["id"], OPS))
    assert cleared["pending_rekey_count"] == 0