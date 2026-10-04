"""Seat subscriptions: capacity boundary, pool conservation, half-open overlap."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_org_owner_headers,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    assert_seat_pool_invariant,
    create_org,
    create_subscription,
    setup_personal_and_pro_tiers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check / seat_assign_on_empty_pool_zero_available
# ---------------------------------------------------------------------------

class TestSeatCapacityBoundary:
    def test_assign_on_empty_pool_rejected(self, api):
        """PRD §3.2: "An assign against a subscription with no available seats is
        rejected with ERR_SEAT_CAPACITY."
        PRD §3.2: "When the last available seat is assigned and active_seats reaches
        purchased_seats, the subscription_status flips from ACTIVE to EXHAUSTED
        automatically."

        Design: Difficulty/boundary_precision_check/seat_assign_on_empty_pool_zero_available
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Seat Co", contact_email="se@x.com")
        sub = create_subscription(org, purchased_seats=1)
        owner = make_org_owner_headers(org["id"])
        get_success_data(api.assign_seat(sub["id"], {"member_label": "dev1"}, owner), 200)

        resp = api.assign_seat(sub["id"], {"member_label": "dev2"}, owner)
        validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY.value)

        subs, _ = validate_paginated(api.list_seat_subscriptions(org["id"], owner))
        current = subs[0]
        assert current["subscription_status"] == "EXHAUSTED"
        assert current["active_seats"] == 1
        assert current["available_seats"] == 0

    def test_assign_on_empty_pool_leaves_pool_unchanged(self, api):
        """PRD §3.2: "the invariant active_seats plus available_seats equals
        purchased_seats holds at all times."

        Design: Difficulty/boundary_precision_check/seat_assign_on_empty_pool_zero_available
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Seat Co", contact_email="se@x.com")
        sub = create_subscription(org, purchased_seats=1)
        owner = make_org_owner_headers(org["id"])
        get_success_data(api.assign_seat(sub["id"], {"member_label": "dev1"}, owner), 200)

        resp = api.assign_seat(sub["id"], {"member_label": "dev2"}, owner)
        validate_error(resp, ApiErrorId.ERR_SEAT_CAPACITY.value)

        subs, _ = validate_paginated(api.list_seat_subscriptions(org["id"], owner))
        assert_seat_pool_invariant(subs[0])


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / seat_assign_release_conserves_purchased_pool
# ---------------------------------------------------------------------------

class TestSeatPoolConservation:
    def test_release_then_assign_conserves_pool(self, api):
        """PRD §3.2: "the invariant active_seats plus available_seats equals
        purchased_seats holds at all times."
        PRD §3.2: "Releasing a seat is the mirror image: it requires at least one
        active seat (otherwise ERR_SEAT_CAPACITY), decrements active_seats, increments
        available_seats, and returns an EXHAUSTED subscription to ACTIVE once the
        active count falls below the purchased count."

        Design: Difficulty/compensating_invariant/seat_assign_release_conserves_purchased_pool
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Pool Co", contact_email="pl@x.com")
        sub = create_subscription(org, purchased_seats=2)
        owner = make_org_owner_headers(org["id"])
        get_success_data(api.assign_seat(sub["id"], {"member_label": "a"}, owner), 200)
        exhausted = get_success_data(api.assign_seat(sub["id"], {"member_label": "b"}, owner), 200)
        assert exhausted["subscription_status"] == "EXHAUSTED"

        released = get_success_data(api.release_seat(sub["id"], owner), 200)
        assert released["subscription_status"] == "ACTIVE"
        assert released["active_seats"] == 1
        assert released["available_seats"] == 1

        final = get_success_data(api.assign_seat(sub["id"], {"member_label": "c"}, owner), 200)
        assert final["active_seats"] == 2
        assert final["available_seats"] == 0
        assert final["subscription_status"] == "EXHAUSTED"
        assert_seat_pool_invariant(final)

    def test_every_step_of_cycle_conserves_pool(self, api):
        """PRD §3.2: "the invariant active_seats plus available_seats equals
        purchased_seats holds at all times."

        Design: Difficulty/compensating_invariant/seat_assign_release_conserves_purchased_pool
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Pool Co", contact_email="pl@x.com")
        sub = create_subscription(org, purchased_seats=2)
        owner = make_org_owner_headers(org["id"])
        assert_seat_pool_invariant(sub)

        s1 = get_success_data(api.assign_seat(sub["id"], {"member_label": "a"}, owner), 200)
        assert_seat_pool_invariant(s1)
        s2 = get_success_data(api.assign_seat(sub["id"], {"member_label": "b"}, owner), 200)
        assert_seat_pool_invariant(s2)
        s3 = get_success_data(api.release_seat(sub["id"], owner), 200)
        assert_seat_pool_invariant(s3)
        s4 = get_success_data(api.release_seat(sub["id"], owner), 200)
        assert_seat_pool_invariant(s4)
        assert s4["active_seats"] == 0
        assert s4["available_seats"] == 2


# ---------------------------------------------------------------------------
# Queue A — resource_temporal_overlap / seat_subscription_halfopen_adjacency_allowed
# ---------------------------------------------------------------------------

class TestSeatSubscriptionOverlap:
    def test_adjacent_half_open_subscription_allowed_then_overlap_rejected(self, api):
        """PRD §3.2: "Two subscriptions for the same org and the same tier_code may not
        overlap in half-open terms; back-to-back coverage where one subscription ends
        exactly on the day another begins is explicitly allowed. An overlapping
        purchase is rejected with ERR_SUBSCRIPTION_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/seat_subscription_halfopen_adjacency_allowed
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Overlap Co", contact_email="o@x.com")
        owner = make_org_owner_headers(org["id"])

        create_subscription(org, purchased_seats=2,
                            coverage_start="2026-09-01", coverage_end="2027-03-01")
        # Adjacent: starts exactly when the first ends — allowed under half-open terms.
        adjacent = create_subscription(org, purchased_seats=2,
                                       coverage_start="2027-03-01", coverage_end="2027-09-01")
        assert adjacent["coverage_start"] == "2027-03-01"

        org_now = get_success_data(api.get_org(org["id"], owner), 200)
        resp = api.create_seat_subscription(
            org["id"],
            {
                "tier_code": "PRO",
                "purchased_seats": 1,
                "coverage_start": "2027-02-28",
                "coverage_end": "2027-04-01",
                "expected_org_version": org_now["version"],
            },
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_OVERLAP.value)

    def test_overlap_by_one_day_rejected(self, api):
        """PRD §3.2: "Coverage is a half-open interval: it includes coverage_start and
        excludes coverage_end, so coverage_start must be strictly before coverage_end or
        the purchase fails with ERR_INVALID_INTERVAL. Two subscriptions for the same org
        and the same tier_code may not overlap in half-open terms; back-to-back coverage
        where one subscription ends exactly on the day another begins is explicitly
        allowed."

        Design: Difficulty/resource_temporal_overlap/seat_subscription_halfopen_adjacency_allowed
        """
        setup_personal_and_pro_tiers()
        org = create_org("PRO", legal_name="Overlap Co", contact_email="o@x.com")
        owner = make_org_owner_headers(org["id"])

        create_subscription(org, purchased_seats=2,
                            coverage_start="2026-09-01", coverage_end="2027-03-01")
        org_now = get_success_data(api.get_org(org["id"], owner), 200)
        # New window starts one day before the existing window ends: overlap.
        resp = api.create_seat_subscription(
            org["id"],
            {
                "tier_code": "PRO",
                "purchased_seats": 1,
                "coverage_start": "2027-02-28",
                "coverage_end": "2027-06-01",
                "expected_org_version": org_now["version"],
            },
            owner,
        )
        validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_OVERLAP.value)
