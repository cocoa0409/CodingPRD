"""Transitive cascades: the suspension chain and the receipt-credit rollup."""
import pytest

from test_helpers import validate_success, validate_error, ApiErrorId
from test_helpers.fixtures import (
    declare_host,
    declare_sites,
    approve_host,
    setup_active_member,
    setup_confirmed_stay,
    setup_basic_scenario,
    file_stay,
    confirm_stay,
    suspend_host,
    conduct_injection,
    declare_patronization_record,
    verify_patronization_record,
    read_host,
    read_member,
    read_stay,
    read_capacity_summary,
    host_version,
    set_clock,
    make_member_headers,
    make_host_operator_headers,
    make_platform_admin_headers,
)


def test_suspension_strands_a_confirmed_stay_and_files_a_conduct_incident(api):
    """PRD §3.1: "The same four-hop cascade runs as for a rejection, except that the
    stays it strands are those in `REQUESTED` or `CONFIRMED` status and the `MAJOR`
    incidents it files against their members carry an origin of `STAFF_FILING`
    rather than `REVIEW_REPORT`"
    PRD §3.1: "On a suspension the host's `onboarding_status` becomes `SUSPENDED`
    and its `posture` collapses to `SUSPENDED` regardless of how many sites are free,
    with `effective_capacity` forced to 0."

    Design: Difficulty/transitive_cascade/suspend_host_four_hop_conduct_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=2, arrival_date="2026-07-01", nights=2,
        site_class="BACK_IN", max_vehicle_length_feet=40,
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    validate_success(
        api.decide_host(
            host_id,
            {"action": "SUSPEND", "reason": "ordinance audit",
             "expected_host_version": host_version(host_id)},
            make_platform_admin_headers(),
        )
    )

    stay = read_stay(parts["stay"]["id"], host_id)
    assert stay["request_status"] == "DECLINED", (
        "hop 1: the suspension closed the CONFIRMED stay"
    )
    member = read_member(member_id)
    assert member["strike_count"] == 1, (
        "hop 2's MAJOR incident cost the member one strike"
    )
    assert member["standing_score"] == 85
    summary = read_capacity_summary(host_id)
    assert summary["posture"] == "SUSPENDED"
    assert summary["effective_capacity"] == 0


def test_the_suspension_cascade_strikes_removal_on_the_third_incident(api):
    """PRD §3.1: "those members' `standing_score` and `strike_count` are recomputed,
    and any member whose `strike_count` reaches 3 or above flips to `REMOVED` and has
    their subscription set to `CANCELLED`."
    PRD §2.7: "a member with three `MAJOR` incidents is removed on the third
    regardless of how few points those incidents cost them"

    Design: Difficulty/transitive_cascade/suspend_host_four_hop_conduct_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=2, arrival_date="2026-07-01", nights=2,
        site_class="BACK_IN", max_vehicle_length_feet=40,
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    # Two strikes banked before the suspension, then the suspension's own incident.
    conduct_injection(member_id, severity="SEVERE", resolve_as="UPHOLD")
    conduct_injection(member_id, severity="MAJOR", resolve_as="UPHOLD")
    before = read_member(member_id)
    assert before["strike_count"] == 2
    assert before["removal_status"] == "NONE"

    validate_success(
        api.decide_host(
            host_id,
            {"action": "SUSPEND", "reason": "ordinance audit",
             "expected_host_version": host_version(host_id)},
            make_platform_admin_headers(),
        )
    )

    after = read_member(member_id)
    assert after["strike_count"] == 3
    assert after["removal_status"] == "REMOVED"
    assert after["subscription_status"] == "CANCELLED"


def test_a_verified_receipt_mints_its_per_record_credit_then_rolls_it_up(api):
    """PRD §2.8: "The support-the-host credit accrues at a flat five percent of a
    verified receipt's value, converted to a whole number of cents by rounding half
    up, and each individual receipt's credit is capped at 1500 cents."
    PRD §2.12: "`host_credit_cents` stays at zero until it is verified"

    Design: Difficulty/transitive_cascade/verify_patronization_two_hop_credit_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    record = declare_patronization_record(
        host_id, member_id, parts["stay"]["id"],
        receipt_cents=10050, purchase_kind="TASTING",
    )
    assert record["verification_status"] == "PENDING"
    assert record["host_credit_cents"] == 0
    assert record["verification_code"], "the server mints the verification code"

    verified = verify_patronization_record(
        host_id, record["id"], record["verification_code"]
    )
    assert verified["verification_status"] == "VERIFIED"
    assert verified["host_credit_cents"] == 503, "5% of 10050 rounds half up to 503"
    assert read_host(host_id)["patronization_credit_cents"] == 503


def test_the_credit_rollup_sums_per_record_credits_and_honours_the_cap(api):
    """PRD §2.8: "The cap and the rounding both apply per receipt, before any
    summation: a host's `patronization_credit_cents` is the total of the per-receipt
    credits of every record in `VERIFIED` status, not a percentage of their combined
    value."
    PRD §2.8: "three receipts of 40000 cents contribute 4500 rather than 6000"

    Design: Difficulty/transitive_cascade/verify_patronization_two_hop_credit_cascade
    """
    set_clock("2026-06-01T00:00:00Z")
    parts = setup_confirmed_stay(
        site_count=1, arrival_date="2026-06-20", nights=2,
        self_contained_required=True, category="WINERY", state_code="CA",
    )
    host_id = parts["host"]["id"]
    member_id = parts["member"]["id"]

    for cents in (10050, 20030, 40000):
        record = declare_patronization_record(
            host_id, member_id, parts["stay"]["id"],
            receipt_cents=cents, purchase_kind="MERCHANDISE",
        )
        verify_patronization_record(host_id, record["id"], record["verification_code"])

    # 503 + 1002 + min(2000, 1500) = 3005
    assert read_host(host_id)["patronization_credit_cents"] == 3005