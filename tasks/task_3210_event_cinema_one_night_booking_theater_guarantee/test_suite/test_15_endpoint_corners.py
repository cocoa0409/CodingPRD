"""Endpoint corners: computed reads after a mutation, and conditional operational sweeps."""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, create_booking, add_line, submit_booking, approve_booking,
    get_booking, run_on_sale_sweep, first_screening, get_line, get_key,
    create_encryption_key_payload, create_content_delivery_payload, get_theater,
    setup_circuit_venue_title, make_distributor_headers, make_exhibitor_headers,
    validate_paginated,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def _approved_scene(screens=60):
    c = setup_circuit_venue_title()
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


def test_approval_commits_the_line_and_moves_the_booking():
    """PRD §3.2: "On success the booking moves to `APPROVED`, the nominated line's
    `exhibit_state` moves from `PROPOSED` to `COMMITTED`".
    PRD §3.2: "one screening is synthesized per element of the booking's showtime plan
    for that line — each starting `SCHEDULED`".

    Design: Corner/endpoints/booking_computed_read_reflects_the_allocation_after_approval
    """
    c = _approved_scene()
    assert c["booking"]["status"] == "APPROVED"
    assert c["line"]["exhibit_state"] == "COMMITTED"
    assert c["screening"]["state"] == "SCHEDULED"


def test_computed_read_after_approval_reflects_screens_and_allocation():
    """PRD §3.2: "the booking's guarantee allocation is recomputed by the waterfall of
    §3.2, the committed screen total is recomputed".
    PRD §2.10: "A booking's `committed_screens_total` answers the same question one
    level down, summing the screens committed across that booking's lines in the
    `COMMITTED` exhibit state".

    Design: Corner/endpoints/booking_computed_read_reflects_the_allocation_after_approval
    """
    c = _approved_scene(screens=40)
    reread = get_booking(c["booking"]["id"])
    line = get_line(c["line"]["id"])
    assert reread["committed_screens_total"] == 40
    assert line["guarantee_applied_cents"] == reread["guarantee_cents"], (
        "the whole guarantee lands on the only committed line"
    )


def test_screening_synthesized_by_approval_carries_the_plan_auditorium():
    """PRD §3.1: "The auditorium label travels with the plan element and is copied onto
    every screening later synthesized from it, which is why a venue never has to be told
    twice which room a showtime occupies."

    Design: Corner/endpoints/booking_computed_read_reflects_the_allocation_after_approval
    """
    c = _approved_scene()
    assert c["screening"]["auditorium"] == c["booking"]["showtime_plan"][0]["auditorium"]
    assert c["screening"]["is_encore"] is False


def test_go_dark_returns_the_venues_own_advanced_backlog():
    """PRD §2.10: "a venue's `pending_rekey_count` tracks revoked-but-unreplaced keys
    and is incremented by each revocation and reset to zero only by the rekey sweep."

    Design: Corner/endpoints/go_dark_executes_every_declared_side_effect
    """
    c = _issued_key_scene()
    result = get_success_data(api_client.go_dark(
        c["theater"]["id"], c["exhibitor_headers"]))
    assert result["status"] == "DARK"
    assert result["pending_rekey_count"] == 1


def test_go_dark_cancels_the_screening_and_revokes_its_key():
    """PRD §3.1: "the venue's status becomes `DARK`, every one of its screenings still
    in `SCHEDULED` moves to `SKIPPED_CANCELLED`, and each of those screenings drives its
    attached encryption keys to `REVOKED`".

    Design: Corner/endpoints/go_dark_executes_every_declared_side_effect
    """
    c = _issued_key_scene()
    get_success_data(api_client.go_dark(c["theater"]["id"], c["exhibitor_headers"]))
    current = get_success_data(api_client.get_screening(c["screening"]["id"], OPS))
    assert current["state"] == "SKIPPED_CANCELLED"
    assert get_key(c["key"]["id"])["issuance_status"] == "REVOKED"


def _issued_key_scene():
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
                                       delivery_method="FILE",
                                       content_checksum="sha256:a0b1c2d3"), OPS))
    get_success_data(api_client.mark_delivery_delivered(
        delivery["id"], "sha256:a0b1c2d3", OPS))
    get_success_data(api_client.verify_delivery(delivery["id"], OPS))
    screening = first_screening(booking["id"])
    # PRD §3.4 only revokes a key in `PENDING` when its screening is cancelled, so
    # the key stays unissued for the go-dark cascade to act on.
    key = get_success_data(api_client.create_encryption_key(
        create_encryption_key_payload(screening["id"],
                                      not_valid_before_utc="2026-12-01T19:00:00Z",
                                      not_valid_after_utc="2026-12-01T21:00:00Z"), OPS))
    c.update({"booking": get_booking(booking["id"]), "line": line,
              "screening": screening, "key": key})
    return c


def _two_approved_with_different_on_sale_dates():
    c = setup_circuit_venue_title()
    early = create_booking(c["title"]["id"], c["circuit"]["id"],
                           on_sale_at="2026-10-01T00:00:00Z")
    early_line = add_line(early["id"], c["circuit"]["id"], c["theater"]["id"],
                          early["version"], committed_screens=40,
                          expected_attendance=100)
    early = submit_booking(early["id"], c["circuit"]["id"], early_line["version"])
    early = approve_booking(early["id"], c["distributor"]["id"],
                            early["version"], early_line["id"])
    early_line = get_line(early_line["id"])
    late = create_booking(c["title"]["id"], c["circuit"]["id"],
                          on_sale_at="2026-11-15T00:00:00Z",
                          showtime_plan=[{"index": 1,
                                          "date_utc": "2026-12-05T00:00:00Z",
                                          "start_minute_utc": 1140,
                                          "auditorium": "AUD-2"}])
    late_line = add_line(late["id"], c["circuit"]["id"], c["theater"]["id"],
                         late["version"], committed_screens=40,
                         expected_attendance=100)
    late = submit_booking(late["id"], c["circuit"]["id"], late_line["version"])
    late = approve_booking(late["id"], c["distributor"]["id"],
                           late["version"], late_line["id"])
    late_line = get_line(late_line["id"])
    c.update({"early": early, "early_line": early_line,
              "late": late, "late_line": late_line})
    return c


def test_on_sale_sweep_advances_only_bookings_whose_instant_has_been_reached():
    """PRD §3.3: "the on-sale sweep walks every `APPROVED` booking whose `on_sale_at`
    has been reached and whose committed screen total still meets its `min_screens`,
    moves each to `ON_SALE`".

    Design: Corner/endpoints/presale_sweep_advances_only_bookings_at_or_past_their_on_sale_instant
    """
    c = _two_approved_with_different_on_sale_dates()
    set_clock("2026-10-05T00:00:00Z")
    swept = get_success_data(api_client.run_on_sale_sweep(OPS))
    assert swept["advanced_count"] == 1
    assert get_booking(c["early"]["id"])["status"] == "ON_SALE"
    assert get_booking(c["late"]["id"])["status"] == "APPROVED"


def test_on_sale_sweep_boundary_is_inclusive_at_the_exact_instant():
    """PRD §3.3: "the on-sale sweep walks every `APPROVED` booking whose `on_sale_at`
    has been reached".
    PRD §2.8: "A platform operator may set it forward to any supplied `to_iso8601`
    instant through the administrative clock capability".

    Design: Corner/endpoints/presale_sweep_advances_only_bookings_at_or_past_their_on_sale_instant
    """
    c = _two_approved_with_different_on_sale_dates()
    set_clock("2026-10-05T00:00:00Z")
    api_client.run_on_sale_sweep(OPS)
    set_clock("2026-11-15T00:00:00Z")
    swept = get_success_data(api_client.run_on_sale_sweep(OPS))
    assert swept["advanced_count"] == 1
    assert get_booking(c["late"]["id"])["status"] == "ON_SALE", (
        "a booking dated exactly at the clock instant is advanced"
    )