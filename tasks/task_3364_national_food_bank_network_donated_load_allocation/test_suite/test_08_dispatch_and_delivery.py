"""Dispatch appointment windows, delivery confirmation, and activity bonuses."""
from datetime import datetime

import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_agreement,
    create_bidding_load,
    create_certified_member_with_shares,
    expected_activity_bonus,
    is_iso8601_timestamp,
    record_freight_decision,
    setup_awarded_load,
    submit_bid,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 instant so two renderings of the same moment compare equal.

    PRD §2.4 fixes the three-fractional-digit rendering only for `created_at` and
    `updated_at`; it never states the string form of a delivery window, so the
    window is compared as the instant it denotes rather than as raw text.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _awarded_covered_load(api, agreement_id, member, **overrides):
    """Awarded load with freight_decision COVERED and no delivery window yet."""
    awarded, bid = setup_awarded_load(api, agreement_id, member, **overrides)
    covered = record_freight_decision(api, awarded["id"], decision="COVERED")
    return covered, bid


def test_overlapping_delivery_window_rejected(api):
    """PRD §3.7: "The window must also not collide with the same member's existing
    commitments: no other load of that same awarded member that is currently
    `IN_TRANSIT` may hold a delivery window that overlaps the new one, and a
    collision is rejected with `ERR_DELIVERY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_adjacency_on_member
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    first, _ = _awarded_covered_load(
        api, agreement["id"], member, weight_lbs=30_000, lot_code="LOT-11A",
        distance_miles=400, shares_offered=300, can_self_transport=True,
    )
    second, _ = _awarded_covered_load(
        api, agreement["id"], member, weight_lbs=30_000, lot_code="LOT-11B",
        distance_miles=400, shares_offered=300, can_self_transport=True,
    )

    dispatched = api.dispatch_load(
        first["id"],
        {"delivery_window_start": "2026-09-10T08:00:00Z",
         "delivery_window_end": "2026-09-10T12:00:00Z"},
        ADMIN,
    )
    in_transit = validate_success(dispatched, 200)
    assert in_transit["status"] == "IN_TRANSIT"

    res = api.dispatch_load(
        second["id"],
        {"delivery_window_start": "2026-09-10T11:00:00Z",
         "delivery_window_end": "2026-09-10T13:00:00Z"},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DELIVERY_WINDOW_OVERLAP)

    still_awarded = validate_success(api.get_load(second["id"], ADMIN), 200)
    assert still_awarded["status"] == "AWARDED"


def test_touching_delivery_window_accepted(api):
    """PRD §2.12: "A window runs from its `window_start` up to but not including
    its `window_end`, which means two windows that merely touch — one ending
    exactly where the next begins — do not overlap and are both legal."

    Design: Difficulty/resource_temporal_overlap/delivery_window_half_open_adjacency_on_member
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    first, _ = _awarded_covered_load(
        api, agreement["id"], member, weight_lbs=30_000, lot_code="LOT-11A",
        distance_miles=400, shares_offered=300, can_self_transport=True,
    )
    second, _ = _awarded_covered_load(
        api, agreement["id"], member, weight_lbs=30_000, lot_code="LOT-11B",
        distance_miles=400, shares_offered=300, can_self_transport=True,
    )

    validate_success(
        api.dispatch_load(
            first["id"],
            {"delivery_window_start": "2026-09-10T08:00:00Z",
             "delivery_window_end": "2026-09-10T12:00:00Z"},
            ADMIN,
        ),
        200,
    )
    touching = api.dispatch_load(
        second["id"],
        {"delivery_window_start": "2026-09-10T12:00:00Z",
         "delivery_window_end": "2026-09-10T14:00:00Z"},
        ADMIN,
    )
    in_transit = validate_success(touching, 200)
    assert in_transit["status"] == "IN_TRANSIT"
    assert is_iso8601_timestamp(in_transit["delivery_window_start"])
    assert _instant(in_transit["delivery_window_start"]) == _instant("2026-09-10T12:00:00Z")


def test_malformed_delivery_window_rejected(api):
    """PRD §3.7: "The window must be properly ordered, with the start strictly
    before the end, and both endpoints must be at or after the current logical
    clock time; a window that is malformed in either respect is rejected with
    `ERR_DELIVERY_WINDOW_INVALID`."

    Design: Corner/errors/delivery_window_invalid_returns_400
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    awarded, _bid = _awarded_covered_load(api, agreement["id"], member)

    res = api.dispatch_load(
        awarded["id"],
        {"delivery_window_start": "2026-09-03T12:00:00Z",
         "delivery_window_end": "2026-09-03T08:00:00Z"},
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_DELIVERY_WINDOW_INVALID)

    after = validate_success(api.get_load(awarded["id"], ADMIN), 200)
    assert after["status"] == "AWARDED"
    assert after["delivery_window_start"] is None


def test_delivery_sets_pounds_meals_and_activity_bonus(api):
    """PRD §3.7: "On delivery, `delivered_lbs` is set to the load's full
    `weight_lbs` and the load's `meal_equivalent` is computed as the delivered
    pounds divided by the agreement's `meal_equivalency_factor`, floored to a whole
    number of meals."
    PRD §3.7: "An `ACTIVITY_BONUS` ledger entry is appended for the awarded member,
    worth 15 shares for every full ten thousand pounds delivered — the delivered
    poundage is divided by ten thousand and floored before the multiplier is
    applied."

    Design: Corner/state_machines/deliver_sets_delivered_lbs_and_activity_bonus
    """
    member = create_certified_member_with_shares(api)
    agreement = create_active_agreement(api)
    awarded, _bid = _awarded_covered_load(
        api, agreement["id"], member, weight_lbs=40_000, distance_miles=120,
        shares_offered=400, can_self_transport=False,
    )
    validate_success(
        api.dispatch_load(
            awarded["id"],
            {"delivery_window_start": "2026-09-03T08:00:00Z",
             "delivery_window_end": "2026-09-03T12:00:00Z"},
            ADMIN,
        ),
        200,
    )

    delivered = validate_success(api.deliver_load(awarded["id"], ADMIN), 200)
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivered_lbs"] == 40_000
    assert delivered["meal_equivalent"] == 33_333

    member_after = validate_success(api.get_member(member["id"], ADMIN), 200)
    bonus = expected_activity_bonus(40_000)
    assert bonus == 60
    assert member_after["share_balance"] == 99_660

    ledger = validate_success(api.list_member_ledger(member["id"], ADMIN), 200)
    newest = ledger[-1]
    assert newest["entry_type"] == "ACTIVITY_BONUS"
    assert newest["amount"] == 60
    assert newest["balance_after"] == 99_660
