"""Domain assertion helpers and pure re-derivations of the PRD's arithmetic.

The re-derivations exist so a test can state an expected figure in the PRD's own
terms; the literal answers themselves are also asserted directly in the tests.
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from . import constants as K
from .types import NotificationChannel


# --- Instant arithmetic ------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating `Z` and any fractional width."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Render an instant as an ISO 8601 UTC string with three fractional digits."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


def instant(iso: str) -> str:
    """Canonicalise any accepted instant spelling to three fractional digits."""
    return format_instant(parse_instant(iso))


def plus_days(iso: str, days: int) -> str:
    """Add whole days, preserving the time-of-day component of the instant."""
    return format_instant(parse_instant(iso) + timedelta(days=days))


def plus_hours(iso: str, hours: int) -> str:
    return format_instant(parse_instant(iso) + timedelta(hours=hours))


def plus_seconds(iso: str, seconds: int) -> str:
    return format_instant(parse_instant(iso) + timedelta(seconds=seconds))


def whole_days_between(start_iso: str, end_iso: str) -> int:
    """Elapsed seconds divided by 86,400, taking the floor."""
    elapsed = (parse_instant(end_iso) - parse_instant(start_iso)).total_seconds()
    return math.floor(elapsed / 86400)


def assert_same_instant(actual: str, expected_iso: str, label: str = "instant") -> None:
    """Compare two instants by value, so fractional-digit width cannot matter."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected {expected_iso}, got {actual}"
    )


# --- Rounding ----------------------------------------------------------------
def round_half_up(value: float) -> int:
    """Round half up: a value exactly halfway rounds away from zero."""
    if value >= 0:
        return int(math.floor(value + 0.5))
    return -int(math.floor(-value + 0.5))


# --- Money / count re-derivations -------------------------------------------
def expected_royalty_cents(pages_requested: int) -> int:
    """The larger of a 1500-cent floor and 800 cents plus 65 cents per page."""
    return max(
        K.ROYALTY_FLOOR_CENTS,
        K.ROYALTY_BASE_CENTS + K.ROYALTY_PER_PAGE_CENTS * pages_requested,
    )


def expected_subsidy_rate(gross_charge_cents: int) -> float:
    """The subsidy tier keyed on the gross figure, never on the net."""
    if gross_charge_cents <= K.SUBSIDY_TIER_1_MAX_GROSS:
        return K.SUBSIDY_RATE_TIER_1
    if gross_charge_cents <= K.SUBSIDY_TIER_2_MAX_GROSS:
        return K.SUBSIDY_RATE_TIER_2
    if gross_charge_cents <= K.SUBSIDY_TIER_3_MAX_GROSS:
        return K.SUBSIDY_RATE_TIER_3
    return K.SUBSIDY_RATE_TIER_4


def expected_subsidy_cents(gross_charge_cents: int) -> int:
    """Gross times the tier rate, rounded half up, then capped at 4000 cents."""
    rounded = round_half_up(gross_charge_cents * expected_subsidy_rate(gross_charge_cents))
    return min(rounded, K.SUBSIDY_CAP_CENTS)


def expected_net_patron_charge_cents(gross_charge_cents: int) -> int:
    return gross_charge_cents - expected_subsidy_cents(gross_charge_cents)


def expected_landed_cost_cents(
    effective_fee_cents: int,
    quoted_turnaround_days: int,
    days_available: int,
    imbalance_penalty_cents: int = 0,
) -> int:
    """Effective fee, plus 250 cents per late day, plus any imbalance penalty."""
    late_days = max(0, quoted_turnaround_days - days_available)
    return (
        effective_fee_cents
        + K.LATE_DAY_PENALTY_CENTS * late_days
        + imbalance_penalty_cents
    )


def expected_overdue_fine_cents(overdue_days: int, breached: bool = False) -> int:
    """150 cents per billable day, times the multiplier, and only then capped."""
    billable_days = max(0, overdue_days - K.OVERDUE_GRACE_DAYS)
    raw = K.OVERDUE_FINE_PER_DAY_CENTS * billable_days
    multiplier = K.RECALL_BREACHED_FINE_MULTIPLIER if breached else 1
    return min(raw * multiplier, K.OVERDUE_FINE_CAP_CENTS)


def expected_surcharged_line_cents(line_amount_cents: int) -> int:
    """One invoice line plus the 7.5 percent levy, rounded half up."""
    return round_half_up(
        line_amount_cents + line_amount_cents * K.CONSORTIUM_SURCHARGE_RATE
    )


def expected_surcharged_total_cents(line_amounts: Iterable[int]) -> int:
    """Round each line, then sum the rounded values."""
    return sum(expected_surcharged_line_cents(amount) for amount in line_amounts)


def expected_standing_base(
    lost_count: int = 0,
    damaged_count: int = 0,
    late_return_count: int = 0,
    unclaimed_count: int = 0,
    unpaid_balance_cents: int = 0,
) -> int:
    """The weighted base shared by the provisional and final standing variants."""
    return (
        K.STANDING_WEIGHT_LOST * lost_count
        + K.STANDING_WEIGHT_DAMAGED * damaged_count
        + K.STANDING_WEIGHT_LATE_RETURN * late_return_count
        + K.STANDING_WEIGHT_UNCLAIMED * unclaimed_count
        + unpaid_balance_cents // K.STANDING_UNPAID_CENTS_PER_POINT
    )


def clamp_score(value: int) -> int:
    return max(K.STANDING_SCORE_MIN, min(K.STANDING_SCORE_MAX, value))


def expected_embargo_years(embargo_months: int) -> int:
    """Months to years, taking the ceiling."""
    return math.ceil(embargo_months / 12)


# --- Shape assertions --------------------------------------------------------
def assert_common_fields(entity: dict, expected_version: Optional[int] = None) -> None:
    """A resource carrying `id`, `created_at`, `updated_at` and `version`."""
    assert is_valid_uuid(entity["id"]), f"id is not a bare UUID: {entity['id']!r}"
    assert is_iso8601_timestamp(entity["created_at"]), entity["created_at"]
    assert is_iso8601_timestamp(entity["updated_at"]), entity["updated_at"]
    assert isinstance(entity["version"], int), entity["version"]
    assert entity["version"] >= 1, entity["version"]
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_notification_shape(notification: dict) -> None:
    """A notice carries only `id` and `created_at`, with no `updated_at` or `version`."""
    assert is_valid_uuid(notification["id"]), notification["id"]
    assert is_iso8601_timestamp(notification["created_at"]), notification["created_at"]
    assert "updated_at" not in notification, (
        "a notification must not carry updated_at"
    )
    assert "version" not in notification, "a notification must not carry version"
    assert notification["channel"] == NotificationChannel.EMAIL, notification["channel"]


def assert_money_is_integer_cents(entity: dict, *fields: str) -> None:
    """Monetary fields are transported as JSON integers, never as strings."""
    for field in fields:
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be a JSON integer of cents, got {value!r}"
        )


def assert_loan_buckets_consistent(loan: dict) -> None:
    """`total_charge_cents` is the sum of the four buckets and `outstanding_cents`
    is `total_charge_cents` minus `total_paid_cents`."""
    expected_total = (
        loan["overdue_fine_cents"]
        + loan["damage_fee_cents"]
        + loan["lost_replacement_cents"]
        + loan["lender_processing_fee_cents"]
    )
    assert loan["total_charge_cents"] == expected_total, (
        f"total_charge_cents {loan['total_charge_cents']} != {expected_total}"
    )
    expected_paid = (
        loan["paid_overdue_cents"]
        + loan["paid_damage_cents"]
        + loan["paid_lost_cents"]
        + loan["paid_processing_cents"]
    )
    assert loan["total_paid_cents"] == expected_paid, (
        f"total_paid_cents {loan['total_paid_cents']} != {expected_paid}"
    )


def assert_all_counters_zero(summary: dict) -> None:
    """An idempotent sweep returns all-zero counters."""
    for field in K.OPS_RUN_COUNTER_FIELDS:
        assert summary[field] == 0, f"{field} should be 0, got {summary[field]}"


def find_by_id(rows: list, row_id: str) -> dict:
    for row in rows:
        if row.get("id") == row_id:
            return row
    raise AssertionError(f"no row with id {row_id} among {[r.get('id') for r in rows]}")


def ids_of(rows: list) -> list:
    return [row.get("id") for row in rows]


def kinds_of(rows: list) -> list:
    return [row.get("kind") for row in rows]
