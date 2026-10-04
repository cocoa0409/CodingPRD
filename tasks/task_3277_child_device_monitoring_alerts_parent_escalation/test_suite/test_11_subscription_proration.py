"""Subscription changes: proration rounding order and OCC guard."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_family,
    make_parent_headers,
    set_clock,
    validate_error,
    validate_success,
)


def test_subscription_proration_per_day_then_sum_mode_b(api):
    """PRD §3.14: "The prorated charge for a mid-period change is computed with
    a pinned rounding order. First, each tier's per-day rate is computed by
    dividing its monthly cents by 30 and rounding half-up to the nearest integer
    cent — rounding happens at this per-day step, before anything is multiplied.
    Second, the remaining days are counted as the integer number of days from
    the current clock up to, but not including, `billing_period_end`. Third, the
    charge is the per-day rate of the new tier minus the per-day rate of the old
    tier, multiplied by the number of remaining days; on a downgrade this charge
    is negative, representing a credit."
    PRD §3.14: "Monthly pricing is 999 cents for `BASIC`, 1999 cents for
    `STANDARD`, and 2999 cents for `PREMIUM`, and each billing period spans 30
    days."
    PRD §3.14: "The result is recorded on the family as
    `last_proration_charge_cents` (which defaults to 0 when no tier change has
    ever occurred), the family's `device_limit` is recomputed against the new
    tier, and the family's `version` increments by 1."

    Design: Difficulty/combinatorial_formula/subscription_proration_per_day_then_sum_mode_b
    """
    fam, parent = create_family(subscription_tier="STANDARD")
    headers = make_parent_headers(parent["id"])

    # Advance to 2026-09-24: 7 days remain before billing_period_end
    # (2026-10-01, exclusive).
    set_clock("2026-09-24T00:00:00Z")

    resp = api.change_subscription(
        fam["id"],
        {"new_tier": "PREMIUM", "expected_family_version": fam["version"]},
        headers,
    )
    updated = validate_success(resp)
    # daily: round_half_up(2999/30) = 100; round_half_up(1999/30) = 67.
    # charge = 7 * (100 - 67) = 231.
    assert updated["last_proration_charge_cents"] == 231
    assert updated["subscription_tier"] == "PREMIUM"
    assert updated["device_limit"] == 10


def test_subscription_proration_downgrade_is_negative_credit(api):
    """PRD §3.14: "The prorated charge for a mid-period change is computed with
    a pinned rounding order. First, each tier's per-day rate is computed by
    dividing its monthly cents by 30 and rounding half-up to the nearest integer
    cent — rounding happens at this per-day step, before anything is multiplied.
    Second, the remaining days are counted as the integer number of days from
    the current clock up to, but not including, `billing_period_end`. Third, the
    charge is the per-day rate of the new tier minus the per-day rate of the old
    tier, multiplied by the number of remaining days; on a downgrade this charge
    is negative, representing a credit."

    Design: Difficulty/combinatorial_formula/subscription_proration_per_day_then_sum_mode_b
    """
    fam, parent = create_family(subscription_tier="PREMIUM")
    headers = make_parent_headers(parent["id"])

    # At the default clock the period just started: 30 days remain.
    # daily: PREMIUM 100, BASIC round_half_up(999/30) = 33.
    # charge = 30 * (33 - 100) = -2010.
    resp = api.change_subscription(
        fam["id"],
        {"new_tier": "BASIC", "expected_family_version": fam["version"]},
        headers,
    )
    updated = validate_success(resp)
    assert updated["last_proration_charge_cents"] == -2010
    assert updated["subscription_tier"] == "BASIC"
    assert updated["device_limit"] == 2


def test_child_patch_with_stale_version_returns_412(api):
    """PRD §2.6: "Updating a child profile requires a non-optional
    `expected_child_version` field carrying the `version` of the `ChildProfile`
    the client last observed. If the value does not match the child profile's
    current `version` — because another write, such as a tuning change or an
    archive cascade, has advanced the profile since the client read it — the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.2: "Any successful update increments the child's `version` by 1."

    Design: Corner/cross_cutting/child_patch_with_stale_version_returns_412
    """
    from test_helpers import create_child

    fam, parent = create_family()
    headers = make_parent_headers(parent["id"])
    child = create_child(fam["id"], parent["id"])
    assert child["version"] == 1

    # First patch succeeds and advances version 1 -> 2.
    resp = api.patch_child(
        child["id"],
        {"monitoring_sensitivity": "STRICT", "expected_child_version": 1},
        headers,
    )
    updated = validate_success(resp)
    assert updated["monitoring_sensitivity"] == "STRICT"
    assert updated["version"] == 2

    # Second patch with the stale captured version 1 is rejected.
    resp = api.patch_child(
        child["id"],
        {"monitoring_sensitivity": "LENIENT", "expected_child_version": 1},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    current = validate_success(api.get_child(child["id"], headers))
    assert current["monitoring_sensitivity"] == "STRICT"


def test_subscription_change_with_stale_version_returns_412(api):
    """PRD §2.6: "Changing a family's subscription tier requires a non-optional
    `expected_family_version` field carrying the `version` of the
    `FamilyAccount` the client last observed. A mismatch against the family's
    current `version` — for example because another writer has just changed the
    tier or the family's state, which legitimately supersedes the prior billing
    view — is rejected with `ERR_STALE_VERSION` (HTTP 412), protecting the stale
    proration basis."
    PRD §3.15: "A `PlatformAdmin` may suspend or reactivate a family through the
    family state operation, moving `account_status` between `ACTIVE` and
    `SUSPENDED` in either direction; each transition increments the family's
    `version` by 1."

    Design: Corner/cross_cutting/subscription_change_with_stale_version_returns_412
    """
    from test_helpers import TEST_USERS

    fam, parent = create_family(subscription_tier="STANDARD")
    headers = make_parent_headers(parent["id"])
    admin = TEST_USERS["platform_admin_headers"]

    # Two state transitions advance the family version from 1 to 3.
    validate_success(api.set_family_state(fam["id"], {"to_status": "SUSPENDED"}, admin))
    validate_success(api.set_family_state(fam["id"], {"to_status": "ACTIVE"}, admin))

    resp = api.change_subscription(
        fam["id"],
        {"new_tier": "PREMIUM", "expected_family_version": fam["version"]},
        headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    fam_now = validate_success(api.get_family(fam["id"], headers))
    assert fam_now["subscription_tier"] == "STANDARD"
