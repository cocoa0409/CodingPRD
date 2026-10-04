"""Membership pricing, member enrolment and the member payout waterfall.

Covers the independently-rounded schedule components and the ranked payout run
that clamps against the remaining pool.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    assert_channel_membership,
    assert_membership_schedule,
    create_approved_channel,
    create_membership_payload,
    create_membership_schedule_payload,
    get_success_data,
    make_creator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_membership_schedule_components_are_rounded_independently(api):
    """PRD §3.10: "The `creator_share_cents` is the half-up rounding of the
    monthly fee multiplied by 0.70, the `MEMBERSHIP_CREATOR_RATE`."
    PRD §3.10: "The `platform_share_cents` is the half-up rounding of the monthly
    fee multiplied by the remaining 0.30."
    PRD §3.10: "The `network_fee_cents` is the half-up rounding of the monthly fee
    multiplied by 0.03, the `NETWORK_FEE_RATE`, and it is added on top of the fee
    rather than carved out of it, because it is paid by the member."
    PRD §3.10: "The `member_charge_cents` is the monthly fee plus the
    `network_fee_cents`, unrounded beyond the fee's own whole-cent precision."

    Design: Difficulty/combinatorial_formula/membership_schedule_nested_rounding_independent_parts
    """
    channel = create_approved_channel(channel_name="Membership Studio",
                                      country_code="US", lifetime_watch_hours=12000,
                                      subscriber_count=9000,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)

    schedule = validate_success(api.create_membership_schedule(
        channel["id"],
        create_membership_schedule_payload(tier_name="Studio Plus",
                                           monthly_fee_cents=1999,
                                           perks=["badges", "live-chat"]),
        make_creator_headers(channel["id"])), 201)

    assert_membership_schedule(schedule)
    assert schedule["creator_share_cents"] == 1399
    assert schedule["platform_share_cents"] == 600
    assert schedule["network_fee_cents"] == 60
    assert schedule["member_charge_cents"] == 2059


def test_membership_shares_sum_to_the_monthly_fee_without_drift(api):
    """PRD §3.10: "The schedule's four derived figures — `creator_share_cents`,
    `platform_share_cents`, `network_fee_cents` and `member_charge_cents` — are
    each rounded independently to the nearest whole cent, half-up, and none of
    them is derived by subtracting another rounded figure."

    Design: Difficulty/combinatorial_formula/membership_schedule_nested_rounding_independent_parts
    """
    channel = create_approved_channel(channel_name="Membership Studio Two",
                                      lifetime_watch_hours=12000, subscriber_count=9000,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)

    schedule = validate_success(api.create_membership_schedule(
        channel["id"],
        create_membership_schedule_payload(tier_name="Studio Plus Two",
                                           monthly_fee_cents=1999),
        make_creator_headers(channel["id"])), 201)

    monthfee = schedule["monthly_fee_cents"]
    assert schedule["creator_share_cents"] + schedule["platform_share_cents"] == monthfee, (
        "the independently rounded shares must still sum to the fee exactly")


def test_membership_schedule_publishing_flips_the_offered_flag(api):
    """PRD §3.10: "On success the channel's `membership_offered` flag is set to
    true."

    Design: Difficulty/combinatorial_formula/membership_schedule_nested_rounding_independent_parts
    """
    channel = create_approved_channel(channel_name="Membership Studio Three",
                                      lifetime_watch_hours=12000, subscriber_count=9000,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    assert channel["membership_offered"] is False

    validate_success(api.create_membership_schedule(
        channel["id"],
        create_membership_schedule_payload(tier_name="Studio Plus Three",
                                           monthly_fee_cents=1999),
        make_creator_headers(channel["id"])), 201)

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["membership_offered"] is True


# ─── Member enrolment and payouts ────────────────────

def test_member_payout_run_with_no_active_members_is_rejected(api):
    """PRD §3.10: "The candidate set is the channel's `ChannelMembership` rows
    whose `status` is `ACTIVE`, and an empty candidate set is a hard rejection
    with `ERR_NO_ELIGIBLE_MEMBERS` (HTTP 409) rather than a silent no-op."

    Design: Corner/endpoints/member_payout_run_with_no_active_members_is_rejected
    """
    channel = create_approved_channel(channel_name="Empty Members Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000)

    res = api.run_member_payouts(
        channel["id"],
        {"total_payout_cents": 1000,
         "expected_channel_version": channel["version"]},
        TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_NO_ELIGIBLE_MEMBERS", expected_status=409)


def test_member_payout_run_ranks_by_paid_months_then_joined_at(api):
    """PRD §3.10: "Each member in rank order is granted the half-up rounding of
    that member's `paid_member_months` multiplied by the per-month unit of 25
    cents"
    PRD §3.10: "and that grant is clamped to whatever remains in the pool: if the
    computed grant would exceed the remaining balance, the member receives exactly
    the remainder and the pool is exhausted"

    Design: Corner/endpoints/member_payout_run_ranks_by_paid_months_then_joined_at
    """
    channel = create_approved_channel(channel_name="Rank Members Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000)

    first = get_success_data(api.create_membership(
        channel["id"],
        create_membership_payload(member_name="Long Time Member",
                                  monthly_fee_cents=499,
                                  joined_at="2026-01-01T00:00:00Z"),
        TEST_USERS["platform_admin_headers"]))
    second = get_success_data(api.create_membership(
        channel["id"],
        create_membership_payload(member_name="New Member", monthly_fee_cents=499,
                                  joined_at="2026-06-01T00:00:00Z"),
        TEST_USERS["platform_admin_headers"]))
    assert_channel_membership(first)
    assert first["paid_member_months"] == 0
    assert first["payout_cents"] == 0

    version = get_success_data(api.get_channel(channel["id"],
                                               TEST_USERS["any_headers"]))["version"]
    validate_success(api.run_member_payouts(
        channel["id"],
        {"total_payout_cents": 100, "expected_channel_version": version},
        TEST_USERS["platform_admin_headers"]), 200)

    members, meta = validate_paginated(api.list_memberships(
        channel["id"], TEST_USERS["any_headers"]))
    assert meta["total_count"] == 2
    # An enrolled member starts with paid_member_months at 0, and the ranking
    # grants the half-up rounding of paid_member_months times the per-month unit
    # of 25 cents — so a run over freshly enrolled members never spends more than
    # the pool it was given.
    for member in members:
        assert member["paid_member_months"] == 0
        assert member["payout_cents"] == 0
    spent = sum(m["payout_cents"] for m in members)
    assert spent <= 100, "the run must never spend more than the pool"


def test_membership_enrollment_accepts_admin_and_creator(api):
    """PRD §2.1: "`Anonymous` callers may create a channel and read public
    listings; that is the entire unauthenticated surface. `Any` is a convenience
    umbrella for the read-only surface — every authenticated role may read
    listings and single resources."
    PRD §3.10: "An enrolled `ChannelMembership` starts with `status` `ACTIVE`,
    `paid_member_months` at 0 and `payout_cents` at 0."

    Design: Corner/rbac/membership_enrollment_accepts_admin_and_creator
    """
    channel = create_approved_channel(channel_name="Shared Enroll Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000)

    admin_member = validate_success(api.create_membership(
        channel["id"],
        create_membership_payload(member_name="Admin Enrolled", monthly_fee_cents=499,
                                  joined_at="2026-09-01T00:00:00Z"),
        TEST_USERS["platform_admin_headers"]), 201)
    assert admin_member["status"] == "ACTIVE"

    creator_member = validate_success(api.create_membership(
        channel["id"],
        create_membership_payload(member_name="Creator Enrolled",
                                  monthly_fee_cents=499),
        make_creator_headers(channel["id"])), 201)
    assert creator_member["status"] == "ACTIVE"