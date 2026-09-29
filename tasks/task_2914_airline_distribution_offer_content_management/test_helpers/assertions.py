"""Domain assertions layered on the framework's generic ones."""

from typing import Any, Dict, Iterable, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .api_client import canonical_instant
from .constants import (
    CLAWBACK_RATES,
    CONTENT_TIER_RANKS,
    ITEM_TYPE_SURCHARGE,
    REFUND_FEE_HIGH_FLOOR_CENTS,
    REFUND_FEE_HIGH_RATE,
    REFUND_FEE_LOW_CENTS,
    REFUND_FEE_MID_CENTS,
    REFUND_FEE_MID_FLOOR_CENTS,
)

Resource = Dict[str, Any]


def round_half_up(value: float) -> int:
    """Round to the nearest integer, ties away from zero — the PRD's rule."""
    from decimal import ROUND_HALF_UP, Decimal

    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- identity, versioning and timestamps ---------------------------------
def assert_mutable_resource(resource: Resource, expected_version: Optional[int] = None) -> None:
    """A mutable resource carries id, created_at, updated_at and version."""
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert is_iso8601_timestamp(resource["updated_at"]), resource["updated_at"]
    assert isinstance(resource["version"], int) and resource["version"] >= 1
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_immutable_resource(resource: Resource) -> None:
    """An immutable resource carries only id and created_at — no updated_at, no version.

    The PRD requires those two fields to be absent from the payload entirely,
    not present-but-null.
    """
    assert is_valid_uuid(resource["id"]), f"id is not a UUID: {resource['id']!r}"
    assert is_iso8601_timestamp(resource["created_at"]), resource["created_at"]
    assert "updated_at" not in resource, "updated_at must be absent, not present-but-null"
    assert "version" not in resource, "version must be absent, not present-but-null"


def assert_three_fractional_digits(timestamp: str) -> None:
    """An ISO 8601 UTC instant with exactly three fractional digits."""
    assert isinstance(timestamp, str), timestamp
    assert timestamp.endswith("Z"), f"instant must end with Z: {timestamp!r}"
    assert "." in timestamp, f"instant must carry fractional digits: {timestamp!r}"
    fraction = timestamp.split(".")[1][:-1]
    assert len(fraction) == 3, f"instant must carry exactly three fractional digits: {timestamp!r}"
    assert fraction.isdigit(), timestamp


def assert_instant_equals(actual: Optional[str], expected: Optional[str]) -> None:
    """Compare instants after canonicalisation so sub-second width cannot matter."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"expected instant {expected!r}, got {actual!r}"
    )


def assert_unchanged(before: Resource, after: Resource, fields: Iterable[str]) -> None:
    """Every named field holds the same value before and after an operation."""
    for field in fields:
        assert after[field] == before[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


def assert_version_unchanged(before: Resource, after: Resource) -> None:
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']}"
    )
    assert_instant_equals(after["updated_at"], before["updated_at"])


def assert_version_bumped_by(before: Resource, after: Resource, delta: int = 1) -> None:
    assert after["version"] == before["version"] + delta, (
        f"expected version {before['version'] + delta}, got {after['version']}"
    )


# --- pagination -----------------------------------------------------------
def assert_pagination_meta(
    meta: Dict[str, Any],
    expected_total: Optional[int] = None,
    expected_limit: Optional[int] = None,
    expected_offset: Optional[int] = None,
    expected_has_more: Optional[bool] = None,
) -> None:
    for key in ("limit", "offset", "total_count", "has_more"):
        assert key in meta, f"list meta is missing {key}"
    if expected_total is not None:
        assert meta["total_count"] == expected_total
    if expected_limit is not None:
        assert meta["limit"] == expected_limit
    if expected_offset is not None:
        assert meta["offset"] == expected_offset
    if expected_has_more is not None:
        assert meta["has_more"] is expected_has_more


def assert_ordered_by(rows: Sequence[Resource], field: str) -> None:
    values = [row[field] for row in rows]
    assert values == sorted(values), f"rows are not ascending by {field}: {values}"


def assert_surcharge_rule_order(rules: Sequence[Resource]) -> None:
    """Surcharge rules list by ascending threshold_cents, then ascending created_at."""
    keys = [(rule["threshold_cents"], canonical_instant(rule["created_at"])) for rule in rules]
    assert keys == sorted(keys), f"surcharge rules are out of evaluation order: {keys}"


# --- channels -------------------------------------------------------------
def assert_content_tier_rank(channel: Resource) -> None:
    expected = CONTENT_TIER_RANKS[channel["content_tier"]]
    assert channel["content_tier_rank"] == expected, (
        f"tier {channel['content_tier']} must derive rank {expected}, "
        f"got {channel['content_tier_rank']}"
    )


def assert_channel_cost_ledger(
    channel: Resource,
    booking_count: int,
    activity_cost_cents: int,
    cost_per_booking_flat_cents: int,
    cost_per_booking_activity_cents: int,
) -> None:
    assert channel["booking_count"] == booking_count, channel
    assert channel["activity_cost_cents"] == activity_cost_cents, channel
    assert channel["cost_per_booking_flat_cents"] == cost_per_booking_flat_cents, channel
    assert channel["cost_per_booking_activity_cents"] == cost_per_booking_activity_cents, channel


# --- offers ---------------------------------------------------------------
def assert_offer_money(
    offer: Resource,
    subtotal_cents: int,
    surcharge_cents: int,
    item_count: Optional[int] = None,
) -> None:
    assert offer["subtotal_cents"] == subtotal_cents, offer
    assert offer["surcharge_cents"] == surcharge_cents, offer
    assert offer["total_cents"] == subtotal_cents + surcharge_cents, offer
    if item_count is not None:
        assert offer["item_count"] == item_count, offer


def assert_line(
    line: Resource,
    sequence: int,
    item_type: str,
    item_code: str,
    list_amount_cents: int,
    net_amount_cents: int,
    refundable: bool,
) -> None:
    assert line["sequence"] == sequence, line
    assert line["item_type"] == item_type, line
    assert line["item_code"] == item_code, line
    assert line["list_amount_cents"] == list_amount_cents, line
    assert line["net_amount_cents"] == net_amount_cents, line
    assert line["refundable"] is refundable, line
    assert_immutable_resource(line)


def assert_surcharge_lines_not_refundable(lines: Sequence[Resource]) -> None:
    for line in lines:
        if line["item_type"] == ITEM_TYPE_SURCHARGE:
            assert line["refundable"] is False, line


def line_by_code(lines: Sequence[Resource], item_code: str) -> Resource:
    matches = [line for line in lines if line["item_code"] == item_code]
    assert len(matches) == 1, f"expected exactly one line coded {item_code}, got {len(matches)}"
    return matches[0]


def markup_line_amount(list_amount_cents: int, markup_pct: float) -> int:
    """The PRD's per-line pricing: list amount times (1 + markup), rounded half up."""
    return round_half_up(list_amount_cents * (1 + markup_pct))


def bundled_line_amount(
    list_amount_cents: int, bundle_discount_pct: float, markup_pct: float
) -> int:
    """Bundle discount at full precision, then markup, then one rounding."""
    discounted = list_amount_cents * (1 - bundle_discount_pct)
    return round_half_up(discounted * (1 + markup_pct))


def surcharge_amounts(
    scope_base_cents: int, rate_pct: float, min_cents: int, max_cents: int
) -> Dict[str, int]:
    """Raw amount rounded before the clamps; clamped amount after."""
    raw = round_half_up(scope_base_cents * rate_pct)
    clamped = min(max(raw, min_cents), max_cents)
    return {"list_amount_cents": raw, "net_amount_cents": clamped}


# --- incentives -----------------------------------------------------------
def marginal_incentive(qualifying_revenue_cents: int) -> float:
    """Band walk of the PRD, carried at full precision with no rounding."""
    band_1 = min(qualifying_revenue_cents, 5000000)
    band_2 = min(max(qualifying_revenue_cents - 5000000, 0), 15000000)
    band_3 = max(qualifying_revenue_cents - 20000000, 0)
    return band_1 * 0.010 + band_2 * 0.025 + band_3 * 0.040


def expected_incentive_accrued(
    qualifying_revenue_cents: int,
    incentive_multiplier: float,
    agreed_incentive_pct: float,
    incentive_cap_cents: int,
) -> int:
    """Scale the marginal figure, cap it, then round half up exactly once."""
    scaled = (
        marginal_incentive(qualifying_revenue_cents)
        * incentive_multiplier
        * (agreed_incentive_pct / 0.025)
    )
    return round_half_up(min(scaled, incentive_cap_cents))


def expected_incentive_tier(qualifying_revenue_cents: int) -> str:
    if qualifying_revenue_cents >= 20000000:
        return "TIER_3"
    if qualifying_revenue_cents >= 5000000:
        return "TIER_2"
    return "TIER_1"


def assert_agreement_ledger(
    agreement: Resource,
    cumulative_net_revenue_cents: int,
    incentive_accrued_cents: int,
    incentive_tier: str,
    tier_downgrade_count: Optional[int] = None,
) -> None:
    assert agreement["cumulative_net_revenue_cents"] == cumulative_net_revenue_cents, agreement
    assert agreement["incentive_accrued_cents"] == incentive_accrued_cents, agreement
    assert agreement["incentive_tier"] == incentive_tier, agreement
    if tier_downgrade_count is not None:
        assert agreement["tier_downgrade_count"] == tier_downgrade_count, agreement


# --- refund settlement ---------------------------------------------------
def expected_cancellation_fee(refundable_base_cents: int) -> int:
    if refundable_base_cents < REFUND_FEE_MID_FLOOR_CENTS:
        return REFUND_FEE_LOW_CENTS
    if refundable_base_cents < REFUND_FEE_HIGH_FLOOR_CENTS:
        return REFUND_FEE_MID_CENTS
    return round_half_up(refundable_base_cents * REFUND_FEE_HIGH_RATE)


def expected_refund_total(refundable_base_cents: int) -> int:
    return max(refundable_base_cents - expected_cancellation_fee(refundable_base_cents), 0)


def expected_clawback(refund_total_cents: int, incentive_tier: Optional[str]) -> int:
    if incentive_tier is None:
        return 0
    return round_half_up(refund_total_cents * CLAWBACK_RATES[incentive_tier])


def assert_settlement(
    request: Resource,
    refundable_base_cents: int,
    cancellation_fee_cents: int,
    refund_total_cents: int,
    incentive_clawback_cents: int,
) -> None:
    assert request["refundable_base_cents"] == refundable_base_cents, request
    assert request["cancellation_fee_cents"] == cancellation_fee_cents, request
    assert request["refund_total_cents"] == refund_total_cents, request
    assert request["incentive_clawback_cents"] == incentive_clawback_cents, request


# --- readiness ------------------------------------------------------------
def weighted_mean_score(tests: Sequence[Dict[str, Any]]) -> int:
    """Weighted mean of (score, weight) pairs, rounded half up; 0 when empty."""
    weights = sum(weight for _, weight in tests)
    if weights == 0:
        return 0
    numerator = sum(score * weight for score, weight in tests)
    return round_half_up(numerator / weights)


def assert_readiness(
    certification: Resource,
    strict: int,
    provisional: int,
    mandatory_failed_count: Optional[int] = None,
    reserved_test_minutes: Optional[int] = None,
) -> None:
    assert certification["readiness_score_strict"] == strict, certification
    assert certification["readiness_score_provisional"] == provisional, certification
    if mandatory_failed_count is not None:
        assert certification["mandatory_failed_count"] == mandatory_failed_count, certification
    if reserved_test_minutes is not None:
        assert certification["reserved_test_minutes"] == reserved_test_minutes, certification


# --- cost per booking ----------------------------------------------------
def expected_cost_per_booking_flat(monthly_platform_fee_cents: int, paid_bookings: int) -> int:
    if paid_bookings == 0:
        return 0
    return round_half_up(monthly_platform_fee_cents / paid_bookings)


def expected_cost_per_booking_activity(activity_cost_cents: int, paid_bookings: int) -> int:
    if paid_bookings == 0:
        return 0
    return round_half_up(activity_cost_cents / paid_bookings)


__all__: List[str] = [
    "assert_agreement_ledger",
    "assert_channel_cost_ledger",
    "assert_content_tier_rank",
    "assert_immutable_resource",
    "assert_instant_equals",
    "assert_line",
    "assert_mutable_resource",
    "assert_offer_money",
    "assert_ordered_by",
    "assert_pagination_meta",
    "assert_readiness",
    "assert_settlement",
    "assert_surcharge_lines_not_refundable",
    "assert_surcharge_rule_order",
    "assert_three_fractional_digits",
    "assert_unchanged",
    "assert_version_bumped_by",
    "assert_version_unchanged",
    "bundled_line_amount",
    "expected_cancellation_fee",
    "expected_clawback",
    "expected_cost_per_booking_activity",
    "expected_cost_per_booking_flat",
    "expected_incentive_accrued",
    "expected_incentive_tier",
    "expected_refund_total",
    "line_by_code",
    "marginal_incentive",
    "markup_line_amount",
    "round_half_up",
    "surcharge_amounts",
    "weighted_mean_score",
]
