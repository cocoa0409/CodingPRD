"""Referral lifecycle workflows: decline/reassign cycles, escalation windows,
reassignment boundaries, the aging sweep, and derived-field reconciliation.
"""
import pytest

from test_helpers import (
    api_client, COORDINATOR,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_category, create_org, create_offering,
    create_client, create_consent, create_and_approve_agreement, create_network,
    create_referral, get_referral, get_client, get_offering,
    setup_referral_scenario, setup_routed_referral, setup_two_receiver_scenario,
    route_referral, accept_referral, decline_referral, start_service,
    confirm_outcome, reassign_referral,
    make_case_worker_headers, make_org_admin_headers,
)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / referral_decline_reassign_cycle_with_counters
# ---------------------------------------------------------------------------

def _drive_decline_reassign_then_escalation_cycle():
    """Route to R1, decline, reassign to R2, age past the window, escalate,
    then reassign back to R1. Returns (ctx, referral)."""
    ctx = setup_two_receiver_scenario()
    route_referral(ctx, ctx["referral_id"])
    decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r1_id"], reason="full")
    referral = get_referral(ctx["referral_id"])
    resp = reassign_referral(ctx["case_worker"], ctx["referral_id"],
                             ctx["r2_id"], ctx["o2_id"], referral["version"])
    get_success_data(resp)
    set_clock("2026-09-05T00:00:00Z")
    get_success_data(api_client.escalate_referral(ctx["referral_id"], COORDINATOR))
    referral = get_referral(ctx["referral_id"])
    resp = reassign_referral(COORDINATOR, ctx["referral_id"],
                             ctx["r1_id"], ctx["o1_id"], referral["version"])
    return ctx, get_success_data(resp)


def test_decline_reassign_cycle_counters():
    """PRD §3.5: "Declining moves `ROUTED` → `DECLINED` with the same ownership
    rule, takes a free-text `reason`, releases the reservation
    (`capacity_consumed` decrements by 1), and increments
    `reassignment_count`".
    PRD §3.5: "The coordinator may then reassign an escalated referral under
    the same rules as a decline-reassign, including the loop check and the OCC
    field; an escalation-reassign additionally increments `reopen_count` as
    well as `reassignment_count` (which continues to count against the
    reassignment cap), and it swaps reservations — the old offering's
    `capacity_consumed` decrements by 1 while the new offering's increments
    by 1."

    Design: Difficulty/non_linear_state_machine/referral_decline_reassign_cycle_with_counters
    """
    ctx, referral = _drive_decline_reassign_then_escalation_cycle()
    assert referral["status"] == "ROUTED"
    assert referral["receiver_org_id"] == ctx["r1_id"]
    assert referral["service_offering_id"] == ctx["o1_id"]
    assert referral["reassignment_count"] == 2
    assert referral["reopen_count"] == 1


def test_decline_reassign_cycle_reservation_swap():
    """PRD §3.5: "it swaps reservations — the old offering's
    `capacity_consumed` decrements by 1 while the new offering's increments
    by 1."
    PRD §3.3: "The case-reservation invariant is exact: at all times, an
    offering's `capacity_consumed` equals the number of referrals routed to
    that offering whose status is `ROUTED`, `ACCEPTED`, or `IN_SERVICE`".

    Design: Difficulty/non_linear_state_machine/referral_decline_reassign_cycle_with_counters
    """
    ctx, referral = _drive_decline_reassign_then_escalation_cycle()
    o1 = get_offering(ctx["o1_id"])
    o2 = get_offering(ctx["o2_id"])
    assert o2["capacity_consumed"] == 0, "released when re-routed out of ESCALATED"
    assert o1["capacity_consumed"] == 1, "re-reserved on the receiving offering"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / escalate_at_exact_window_rejected_plus_one_hour_accepted
# ---------------------------------------------------------------------------

def test_escalate_at_exact_window_rejected():
    """PRD §3.5: "Escalation — `ROUTED` → `ESCALATED`, a `NetworkCoordinator`
    act — requires the referral to be genuinely aging: the whole hours elapsed
    since it was routed must strictly exceed the network's
    `auto_accept_window_hours`, with that window halved for `URGENT` referrals;
    a referral exactly at the window is not aging and the request fails with
    `ERR_NOT_AGING`."

    Design: Difficulty/boundary_precision_check/escalate_at_exact_window_rejected_plus_one_hour_accepted
    """
    ctx, referral = setup_routed_referral(
        network_overrides={"auto_accept_window_hours": 72})
    # Routed at 2026-09-01T00:00:00Z; exactly 72 hours later is NOT aging.
    set_clock("2026-09-04T00:00:00Z")
    validate_error(api_client.escalate_referral(referral["id"], COORDINATOR),
                   ApiErrorId.ERR_NOT_AGING, expected_status=409)
    assert get_referral(referral["id"])["status"] == "ROUTED"


def test_escalate_one_hour_past_window_accepted():
    """PRD §3.5: "the whole hours elapsed since it was routed must strictly
    exceed the network's `auto_accept_window_hours`, with that window halved
    for `URGENT` referrals; a referral exactly at the window is not aging and
    the request fails with `ERR_NOT_AGING`."

    Design: Difficulty/boundary_precision_check/escalate_at_exact_window_rejected_plus_one_hour_accepted
    """
    ctx, referral = setup_routed_referral(
        network_overrides={"auto_accept_window_hours": 72})
    set_clock("2026-09-04T01:00:00Z")
    escalated = validate_success(api_client.escalate_referral(referral["id"], COORDINATOR))
    assert escalated["status"] == "ESCALATED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / reassign_past_max_count_boundary_auto_cancel
# ---------------------------------------------------------------------------

def _setup_max_reassignment_scenario(max_count):
    ctx = setup_two_receiver_scenario(
        network_overrides={"max_reassignment_count": max_count})
    route_referral(ctx, ctx["referral_id"])
    return ctx


def test_first_decline_at_max_count_boundary_stays_declined():
    """PRD §3.5: "Declining moves `ROUTED` → `DECLINED` with the same ownership
    rule, takes a free-text `reason`, releases the reservation
    (`capacity_consumed` decrements by 1), and increments
    `reassignment_count`; if that count now exceeds the network's
    `max_reassignment_count`, the referral auto-cancels to `CANCELLED` and the
    client's `open_referral_count` decrements — so with the default cap of 3, a
    fourth decline is rejected into cancellation."

    Design: Difficulty/boundary_precision_check/reassign_past_max_count_boundary_auto_cancel
    """
    ctx = _setup_max_reassignment_scenario(1)
    declined = decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r1_id"],
                                reason="no capacity fit")
    # Count becomes 1; 1 > 1 is false, so the referral stays DECLINED.
    assert declined["status"] == "DECLINED"
    assert declined["reassignment_count"] == 1
    assert get_client(ctx["client_id"])["open_referral_count"] == 1


def test_decline_past_max_count_auto_cancels():
    """PRD §3.5: "if that count now exceeds the network's
    `max_reassignment_count`, the referral auto-cancels to `CANCELLED` and the
    client's `open_referral_count` decrements — so with the default cap of 3, a
    fourth decline is rejected into cancellation."

    Design: Difficulty/boundary_precision_check/reassign_past_max_count_boundary_auto_cancel
    """
    ctx = _setup_max_reassignment_scenario(1)
    decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r1_id"],
                     reason="no capacity fit")
    referral = get_referral(ctx["referral_id"])
    get_success_data(reassign_referral(ctx["case_worker"], ctx["referral_id"],
                                       ctx["r2_id"], ctx["o2_id"], referral["version"]))
    declined = decline_referral(ctx, ctx["referral_id"], receiver_id=ctx["r2_id"],
                                reason="also full")
    # Count becomes 2; 2 > 1 is true, so the referral auto-cancels.
    assert declined["status"] == "CANCELLED"
    assert declined["reassignment_count"] == 2
    assert get_client(ctx["client_id"])["open_referral_count"] == 0


# ---------------------------------------------------------------------------
# Corner: endpoints / reassign_to_same_receiver_rejected
# ---------------------------------------------------------------------------

def test_reassign_to_same_receiver_rejected():
    """PRD §3.5: "The new receiver must differ from the one that just declined
    — otherwise `ERR_REASSIGNMENT_LOOP`".

    Design: Corner/endpoints/reassign_to_same_receiver_rejected
    """
    ctx, referral = setup_routed_referral()
    decline_referral(ctx, referral["id"], reason="no")
    referral = get_referral(referral["id"])
    validate_error(
        reassign_referral(ctx["case_worker"], referral["id"],
                          ctx["receiver_id"], ctx["offering_id"], referral["version"]),
        ApiErrorId.ERR_REASSIGNMENT_LOOP, expected_status=409)
    assert get_referral(referral["id"])["status"] == "DECLINED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting / aging_sweep_expires_idle_routed_referral
# ---------------------------------------------------------------------------

def test_aging_sweep_boundary_still_routed_at_exact_expiry_days():
    """PRD §2.4: "Advancing the clock triggers the referral aging sweep as a
    side effect: any referral still in `ROUTED` whose whole-day age since it
    was routed — the number of complete 24-hour days between the routed
    timestamp and the clock, rounded down — is strictly greater than the
    network's `referral_expiry_days` transitions to `EXPIRED`". "The strictness
    of the comparison matters: a referral exactly `referral_expiry_days` days
    old is not yet expired."

    Design: Corner/cross_cutting/aging_sweep_expires_idle_routed_referral
    """
    ctx, referral = setup_routed_referral(
        network_overrides={"referral_expiry_days": 10})
    set_clock("2026-09-11T00:00:00Z")
    assert get_referral(referral["id"])["status"] == "ROUTED"
    assert get_offering(ctx["offering_id"])["capacity_consumed"] == 1


def test_aging_sweep_expires_past_expiry_days_with_reservation_release():
    """PRD §2.4: "any referral still in `ROUTED` whose whole-day age since it
    was routed — the number of complete 24-hour days between the routed
    timestamp and the clock, rounded down — is strictly greater than the
    network's `referral_expiry_days` transitions to `EXPIRED`, releasing its
    capacity reservation and decrementing the client's open-referral count."

    Design: Corner/cross_cutting/aging_sweep_expires_idle_routed_referral
    """
    ctx, referral = setup_routed_referral(
        network_overrides={"referral_expiry_days": 10})
    set_clock("2026-09-12T00:00:00Z")
    assert get_referral(referral["id"])["status"] == "EXPIRED"
    assert get_offering(ctx["offering_id"])["capacity_consumed"] == 0
    assert get_client(ctx["client_id"])["open_referral_count"] == 0


# ---------------------------------------------------------------------------
# Corner: cross_cutting / derived_fields_reconcile_through_full_lifecycle
# ---------------------------------------------------------------------------

def test_derived_fields_reconcile_through_full_lifecycle():
    """PRD §3.3: "The case-reservation invariant is exact: at all times, an
    offering's `capacity_consumed` equals the number of referrals routed to
    that offering whose status is `ROUTED`, `ACCEPTED`, or `IN_SERVICE`, and
    every transition that creates or destroys a reservation updates
    `capacity_consumed` by exactly 1 in the same request."
    PRD §3.6: "The case closes: the offering's `capacity_consumed` decrements
    by 1, the client's `open_referral_count` decrements by 1".

    Design: Corner/cross_cutting/derived_fields_reconcile_through_full_lifecycle
    """
    ctx, referral = setup_routed_referral(capacity_total=2)
    # Route reserved the case.
    mid = get_offering(ctx["offering_id"])
    assert mid["capacity_consumed"] == 1
    assert mid["capacity_available"] == 1
    assert get_client(ctx["client_id"])["open_referral_count"] == 1

    accept_referral(ctx, referral["id"])
    start_service(ctx, referral["id"])
    # Reservation is held through ACCEPTED and IN_SERVICE (no double-count).
    assert get_offering(ctx["offering_id"])["capacity_consumed"] == 1

    confirm_outcome(ctx, referral["id"], "PARTIALLY_DELIVERED", 2)
    final_offering = get_offering(ctx["offering_id"])
    assert final_offering["capacity_consumed"] == 0
    assert final_offering["capacity_available"] == 2
    assert get_client(ctx["client_id"])["open_referral_count"] == 0
