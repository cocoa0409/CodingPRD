"""Transitive cascades: one trigger producing a chain where each hop causes the next."""
import pytest
from test_helpers import (
    validate_success, get_success_data, TEST_USERS, ApiErrorId,
    set_clock, get_booking, get_line, get_key, get_theater, get_circuit,
    setup_booking_with_issued_key, make_exhibitor_headers,
    create_encryption_key_payload,
)
from test_helpers.api_client import api_client

OPS = TEST_USERS["platform_ops_headers"]
PROG = TEST_USERS["programming_manager_headers"]


def test_title_withdrawal_hop_zero_lands_the_title_in_withdrawn():
    """PRD §3.1: "Withdrawal sets the title to `WITHDRAWN` and then applies a
    four-step cascade across everything still in flight".

    Design: Difficulty/transitive_cascade/title_withdrawal_four_hop_key_revocation_cascade
    """
    ctx = setup_booking_with_issued_key()
    result = get_success_data(api_client.withdraw_title(ctx["title"]["id"], PROG))
    assert result["status"] == "WITHDRAWN"


def test_title_withdrawal_hop_one_cancels_the_booking():
    """PRD §3.1: "every booking against the title in `PENDING_APPROVAL`,
    `COUNTERED`, or `APPROVED` moves to `CANCELLED`".

    Design: Difficulty/transitive_cascade/title_withdrawal_four_hop_key_revocation_cascade
    """
    ctx = setup_booking_with_issued_key()
    get_success_data(api_client.withdraw_title(ctx["title"]["id"], PROG))
    assert get_booking(ctx["booking"]["id"])["status"] == "CANCELLED", (
        "the booking is cancelled because of the withdrawal, not directly invoked"
    )


def test_title_withdrawal_hop_two_releases_the_line():
    """PRD §3.1: "every line of those bookings, whether `PROPOSED` or `COMMITTED`,
    moves to `RELEASED`".

    Design: Difficulty/transitive_cascade/title_withdrawal_four_hop_key_revocation_cascade
    """
    ctx = setup_booking_with_issued_key()
    get_success_data(api_client.withdraw_title(ctx["title"]["id"], PROG))
    assert get_line(ctx["line"]["id"])["exhibit_state"] == "RELEASED"


def test_title_withdrawal_hop_three_cancels_the_screening():
    """PRD §3.1: "every one of those bookings' screenings still in `SCHEDULED` moves
    to `SKIPPED_CANCELLED`".

    Design: Difficulty/transitive_cascade/title_withdrawal_four_hop_key_revocation_cascade
    """
    ctx = setup_booking_with_issued_key()
    get_success_data(api_client.withdraw_title(ctx["title"]["id"], PROG))
    screening = get_success_data(api_client.get_screening(ctx["screening"]["id"], OPS))
    assert screening["state"] == "SKIPPED_CANCELLED"


def test_title_withdrawal_hop_four_revokes_the_key_and_bumps_the_rekey_backlog():
    """PRD §3.1: "each screening that moved to `SKIPPED_CANCELLED` drives its
    encryption keys to `issuance_status` `REVOKED` and increments the owning venue's
    `pending_rekey_count` once per revoked key".
    PRD §2.10: "a venue's `pending_rekey_count` tracks revoked-but-unreplaced keys and
    is incremented by each revocation and reset to zero only by the rekey sweep."

    Design: Difficulty/transitive_cascade/title_withdrawal_four_hop_key_revocation_cascade
    """
    ctx = setup_booking_with_issued_key()
    get_success_data(api_client.withdraw_title(ctx["title"]["id"], PROG))
    assert get_key(ctx["key"]["id"])["issuance_status"] == "REVOKED", (
        "the key is revoked because of the screening change, not the withdrawal"
    )
    assert get_theater(ctx["theater"]["id"])["pending_rekey_count"] == 1


def test_title_withdrawal_recomputes_the_circuit_committed_screen_balance():
    """PRD §3.1: "The circuits whose screens were released then have their committed
    screen balance recomputed, and the distributor's bookable title count is
    recomputed as well."

    Design: Difficulty/transitive_cascade/title_withdrawal_four_hop_key_revocation_cascade
    """
    ctx = setup_booking_with_issued_key()
    assert get_circuit(ctx["circuit"]["id"])["committed_screens_balance"] == 60
    get_success_data(api_client.withdraw_title(ctx["title"]["id"], PROG))
    assert get_circuit(ctx["circuit"]["id"])["committed_screens_balance"] == 0
    assert get_booking(ctx["booking"]["id"])["committed_screens_total"] == 0


def test_venue_going_dark_takes_the_venue_out_of_service():
    """PRD §3.1: "Taking a venue out of service is done by going dark: the venue's
    status becomes `DARK`".

    Design: Difficulty/transitive_cascade/venue_go_dark_screening_and_key_cascade
    """
    ctx = setup_booking_with_issued_key(method="BOTH")
    result = get_success_data(api_client.go_dark(
        ctx["theater"]["id"], make_exhibitor_headers(ctx["circuit"]["id"])))
    assert result["status"] == "DARK"


def test_venue_going_dark_cancels_its_scheduled_screenings():
    """PRD §3.1: "every one of its screenings still in `SCHEDULED` moves to
    `SKIPPED_CANCELLED`".

    Design: Difficulty/transitive_cascade/venue_go_dark_screening_and_key_cascade
    """
    ctx = setup_booking_with_issued_key(method="BOTH")
    get_success_data(api_client.go_dark(
        ctx["theater"]["id"], make_exhibitor_headers(ctx["circuit"]["id"])))
    screening = get_success_data(api_client.get_screening(ctx["screening"]["id"], OPS))
    assert screening["state"] == "SKIPPED_CANCELLED"


def test_venue_going_dark_revokes_the_screenings_keys_and_bumps_the_backlog():
    """PRD §3.1: "each of those screenings drives its attached encryption keys to
    `REVOKED` while incrementing that venue's `pending_rekey_count` once per revoked
    key".

    Design: Difficulty/transitive_cascade/venue_go_dark_screening_and_key_cascade
    """
    ctx = setup_booking_with_issued_key(method="BOTH")
    get_success_data(api_client.go_dark(
        ctx["theater"]["id"], make_exhibitor_headers(ctx["circuit"]["id"])))
    assert get_key(ctx["key"]["id"])["issuance_status"] == "REVOKED"
    assert get_theater(ctx["theater"]["id"])["pending_rekey_count"] == 1


def test_venue_going_dark_leaves_the_booking_status_untouched():
    """PRD §3.1: "the affected circuits' committed screen balances are then
    recomputed."

    Design: Difficulty/transitive_cascade/venue_go_dark_screening_and_key_cascade
    """
    ctx = setup_booking_with_issued_key(method="BOTH")
    get_success_data(api_client.go_dark(
        ctx["theater"]["id"], make_exhibitor_headers(ctx["circuit"]["id"])))
    assert get_booking(ctx["booking"]["id"])["status"] == "APPROVED", (
        "the venue transition chain does not move the booking's own status"
    )