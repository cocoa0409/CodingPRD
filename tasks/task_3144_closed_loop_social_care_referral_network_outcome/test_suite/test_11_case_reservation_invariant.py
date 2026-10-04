"""Case-reservation compensating invariant: route paired with cancel restores
the offering's counters exactly.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, get_success_data,
    setup_referral_scenario, create_referral, route_referral, get_offering,
    get_client, get_referral,
    make_case_worker_headers,
)


def test_case_reservation_invariant_route_then_cancel():
    """PRD §3.3: "The case-reservation invariant is exact: at all times, an
    offering's `capacity_consumed` equals the number of referrals routed to
    that offering whose status is `ROUTED`, `ACCEPTED`, or `IN_SERVICE`, and
    every transition that creates or destroys a reservation updates
    `capacity_consumed` by exactly 1 in the same request."
    PRD §3.5: "Cancelling from `ROUTED`, `ACCEPTED`, or `ESCALATED` releases
    the held reservation; from any state it decrements the client's
    `open_referral_count`."

    Design: Difficulty/compensating_invariant/case_reservation_invariant_route_then_cancel
    """
    ctx = setup_referral_scenario(capacity_total=3)
    referral = create_referral(ctx["sender_id"], ctx["client_id"],
                               ctx["receiver_id"], ctx["offering_id"],
                               ctx["consent_id"], ctx["category_code"])
    # DRAFT: no reservation held yet.
    offering = get_offering(ctx["offering_id"])
    assert offering["capacity_consumed"] == 0
    assert offering["capacity_available"] == 3

    # Forward action: route (+1).
    routed = route_referral(ctx, referral["id"])
    assert routed["status"] == "ROUTED"
    offering = get_offering(ctx["offering_id"])
    assert offering["capacity_consumed"] == 1
    assert offering["capacity_available"] == 2
    assert get_client(ctx["client_id"])["open_referral_count"] == 1

    # Compensating action: cancel (-1), restoring the pre-route values exactly.
    cancelled = validate_success(api_client.cancel_referral(
        referral["id"], {"reason": "client moved"},
        make_case_worker_headers(ctx["sender_id"])))
    assert cancelled["status"] == "CANCELLED"
    offering = get_offering(ctx["offering_id"])
    assert offering["capacity_consumed"] == 0
    assert offering["capacity_available"] == 3
    assert get_client(ctx["client_id"])["open_referral_count"] == 0


def test_case_reservation_invariant_holds_through_repeated_cycles():
    """PRD §3.3: "The case-reservation invariant is exact: at all times, an
    offering's `capacity_consumed` equals the number of referrals routed to
    that offering whose status is `ROUTED`, `ACCEPTED`, or `IN_SERVICE`, and
    every transition that creates or destroys a reservation updates
    `capacity_consumed` by exactly 1 in the same request."
    PRD §3.5: "A successful route reserves the case: the offering's
    `capacity_consumed` increments by 1 and the client's
    `open_referral_count` increments by 1."

    Design: Difficulty/compensating_invariant/case_reservation_invariant_route_then_cancel
    """
    ctx = setup_referral_scenario(capacity_total=3)
    referral = create_referral(ctx["sender_id"], ctx["client_id"],
                               ctx["receiver_id"], ctx["offering_id"],
                               ctx["consent_id"], ctx["category_code"])
    # Two full route/cancel cycles: the invariant holds at every step.
    for _ in range(2):
        route_referral(ctx, referral["id"])
        assert get_offering(ctx["offering_id"])["capacity_consumed"] == 1
        validate_success(api_client.cancel_referral(
            referral["id"], {"reason": "client moved"},
            make_case_worker_headers(ctx["sender_id"])))
        assert get_offering(ctx["offering_id"])["capacity_consumed"] == 0
        # Re-create a fresh DRAFT referral for the next cycle (the cancelled
        # one is terminal).
        referral = create_referral(ctx["sender_id"], ctx["client_id"],
                                   ctx["receiver_id"], ctx["offering_id"],
                                   ctx["consent_id"], ctx["category_code"])
    assert get_client(ctx["client_id"])["open_referral_count"] == 0
