"""Compensating invariants: denial reverses exactly the booked liability.

Depth file (queue A).
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    create_and_approve_budget,
    current_member_version,
    get_member,
    get_region,
    get_success_data,
    set_logical_clock,
    setup_multi_region_claims,
    setup_two_regions_each_with_member,
    submit_claim,
)

_RFO = TEST_USERS["regional_finance_officer_headers"]
_UR = TEST_USERS["utilization_reviewer_headers"]


def test_denial_reverses_exactly_the_pinned_liability(api):
    """PRD §3.6: "Denial is a `UtilizationReviewer` capability available from
    `ADJUDICATED` or `APPEALED`; it moves the claim to `DENIED` and reverses the
    booked `final_liability_cents` out of the region's
    `outside_services_spend_cents` and out of the budget's
    `outside_services_committed_cents`, so a denied claim returns the region's
    margin to where it stood before adjudication."

    Design: Difficulty/compensating_invariant/invariant_region_outside_services_spend_conserved_on_claim_denial
    """
    region_a, region_b, claim_a, claim_b, member_a, member_b = setup_multi_region_claims()

    spend_before = get_region(region_a["id"])["outside_services_spend_cents"]
    adjudicated = get_success_data(api_client.adjudicate_claim(claim_a["id"], {}, _RFO))
    billed_liability = adjudicated["final_liability_cents"]

    after_adjudication = get_region(region_a["id"])["outside_services_spend_cents"]
    assert after_adjudication == spend_before + billed_liability

    get_success_data(api_client.deny_claim(claim_a["id"], {}, _UR))
    after_denial = get_region(region_a["id"])["outside_services_spend_cents"]
    assert after_denial == spend_before, (
        "the denial restores the region spend to its pre-adjudication value"
    )
    assert after_denial != after_adjudication - 420000, (
        "the reversal uses the pinned final liability, not the billed amount"
    )


def test_total_outside_services_spend_is_conserved_across_regions(api):
    """PRD §2.6: "`outside_services_spend_cents` is the sum of
    `final_liability_cents` over the region's claims whose status is `PAID` or
    `ADJUDICATED`."
    PRD §3.6: "it moves the claim to `DENIED` and reverses the booked
    `final_liability_cents` out of the region's
    `outside_services_spend_cents`".

    Design: Difficulty/compensating_invariant/invariant_region_outside_services_spend_conserved_on_claim_denial
    """
    region_a, region_b, claim_a, claim_b, member_a, member_b = setup_multi_region_claims()

    spend_a_before = get_region(region_a["id"])["outside_services_spend_cents"]
    spend_b_before = get_region(region_b["id"])["outside_services_spend_cents"]

    get_success_data(api_client.adjudicate_claim(claim_a["id"], {}, _RFO))
    get_success_data(api_client.deny_claim(claim_a["id"], {}, _UR))

    spend_a_after = get_region(region_a["id"])["outside_services_spend_cents"]
    spend_b_after = get_region(region_b["id"])["outside_services_spend_cents"]

    assert spend_a_after + spend_b_after == spend_a_before + spend_b_before, (
        "the paired adjudicate-then-deny leaves system-wide spend unchanged"
    )
    assert spend_b_after == spend_b_before


def test_transfer_cancellation_leaves_the_member_in_place(api):
    """PRD §3.9: "from `PENDING_EFFECTIVE` the member additionally returns to
    `ACTIVE` with its region of record unchanged at the origin region."
    PRD §3.9: "Cancellation may be performed by a `RegionalFinanceOfficer` from
    `REQUESTED`, or from `PENDING_EFFECTIVE` while the logical clock is still
    before `effective_utc`."

    Design: Difficulty/compensating_invariant/invariant_region_premium_revenue_conserved_on_transfer_cancellation
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    (region_a, region_b, site_a, site_b, dept_a, dept_b,
     provider_a, provider_b, member_a, member_b) = setup_two_regions_each_with_member()

    transfer = get_success_data(
        api_client.create_member_transfer(
            {
                "member_id": member_a["id"],
                "from_region_id": region_a["id"],
                "to_region_id": region_b["id"],
                "effective_utc": "2026-09-10T00:00:00Z",
                "expected_member_version": current_member_version(member_a["id"]),
            },
            _RFO,
        )
    )
    get_success_data(api_client.accept_member_transfer(transfer["id"], {}, _RFO))
    assert get_member(member_a["id"])["status"] == "TRANSFER_PENDING"

    cancelled = get_success_data(
        api_client.cancel_member_transfer(transfer["id"], {}, _RFO)
    )
    assert cancelled["status"] == "CANCELLED"

    member_after = get_member(member_a["id"])
    assert member_after["region_id"] == region_a["id"], (
        "the cancelled transfer leaves the region of record at the origin"
    )
    assert member_after["status"] == "ACTIVE"


def test_premium_revenue_is_conserved_across_the_transfer_window(api):
    """PRD §3.1: "`premium_revenue_cents`, which sums `capitation_rate_cents`
    across exactly those members whose `region_id` matches and whose `status` is
    `ACTIVE` or `TRANSFER_PENDING`".
    PRD §3.9: "Acceptance moves the transfer to `PENDING_EFFECTIVE` and moves
    the member to `TRANSFER_PENDING`, which is the status that keeps the
    member's capitation counted in the origin region's `premium_revenue_cents`
    while the move is in flight."

    Design: Difficulty/compensating_invariant/invariant_region_premium_revenue_conserved_on_transfer_cancellation
    """
    set_logical_clock("2026-09-01T00:00:00Z")
    (region_a, region_b, site_a, site_b, dept_a, dept_b,
     provider_a, provider_b, member_a, member_b) = setup_two_regions_each_with_member()

    total_before = (
        get_region(region_a["id"])["premium_revenue_cents"]
        + get_region(region_b["id"])["premium_revenue_cents"]
    )

    transfer = get_success_data(
        api_client.create_member_transfer(
            {
                "member_id": member_a["id"],
                "from_region_id": region_a["id"],
                "to_region_id": region_b["id"],
                "effective_utc": "2026-09-10T00:00:00Z",
                "expected_member_version": current_member_version(member_a["id"]),
            },
            _RFO,
        )
    )
    get_success_data(api_client.accept_member_transfer(transfer["id"], {}, _RFO))

    # A transferring member's capitation stays counted in the origin region.
    during = (
        get_region(region_a["id"])["premium_revenue_cents"]
        + get_region(region_b["id"])["premium_revenue_cents"]
    )
    assert during == total_before, "the pending window does not move capitation"

    get_success_data(api_client.cancel_member_transfer(transfer["id"], {}, _RFO))
    after = (
        get_region(region_a["id"])["premium_revenue_cents"]
        + get_region(region_b["id"])["premium_revenue_cents"]
    )
    assert after == total_before, (
        "the total is unchanged across the pending window and the cancellation"
    )